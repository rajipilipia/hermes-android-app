"""Synthetic-only Gemini source contract; all actual DNS/socket egress denied."""
from __future__ import annotations
import asyncio
import base64
from dataclasses import replace
import json
from pathlib import Path
import socket
import time
import httpx
import unittest
from unittest.mock import patch

from pc.catalog import CapabilityError
from pc.policy import Owner
try:
    from pc import gemini_dictation as gd
except ImportError:
    gd = None

WEBM = b'\x1a\x45\xdf\xa3\x42\x82\x84webm' + b'\x00' * 16
OGG = b'OggS\x00' + b'\x00' * 24 + b'OpusHead' + b'\x00' * 16
WAV = b'RIFF\x04\x00\x00\x00WAVE'


def payload(raw=WEBM, mime='audio/webm;codecs=opus'):
    return {'data_url': 'data:' + mime + ';base64,' + base64.b64encode(raw).decode('ascii'),
            'mime_type': mime}


def setUpModule():
    global _network_patches, _network_attempts
    _network_attempts = []
    def denied(*args, **kwargs):
        _network_attempts.append('denied')
        raise AssertionError('real network forbidden in dictation tests')
    _network_patches = [patch.object(socket, name, denied) for name in
                        ('getaddrinfo', 'create_connection')]
    for guard in _network_patches:
        guard.start()


class SyntheticAsync(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        # Windows needs its private socketpair during loop construction. Once
        # the loop exists, every connect/sendto used by the tested service fails.
        def denied(*args, **kwargs):
            _network_attempts.append('denied')
            raise AssertionError('real network forbidden in dictation tests')
        self._egress = [patch.object(socket.socket, name, denied)
                        for name in ('connect', 'connect_ex', 'sendto')]
        for guard in self._egress:
            guard.start()

    async def asyncTearDown(self):
        pending = [task for task in asyncio.all_tasks() if task is not asyncio.current_task() and not task.done()]
        for guard in reversed(self._egress):
            guard.stop()
        self.assertEqual(pending, [], 'owned service tasks leaked beyond settlement')


def tearDownModule():
    for guard in reversed(_network_patches):
        guard.stop()
    if _network_attempts:
        raise AssertionError('dictation tests attempted real DNS/socket egress')


class PayloadTests(unittest.TestCase):
    def test_canonical_opus_data_url_decodes_without_relabeling(self):
        self.assertIsNotNone(gd, 'bounded Gemini module has not been implemented')
        decoded = gd.decode_payload(payload())
        self.assertEqual(decoded.mime_type, 'audio/webm')
        self.assertEqual(decoded.data, WEBM)
        self.assertEqual(decoded.encoded, base64.b64encode(WEBM).decode('ascii'))

    def test_payload_refuses_untrusted_mime_container_and_noncanonical_base64(self):
        cases = [({}, 400), ({**payload(), 'profile': 'other'}, 400),
                 ({'data_url': 123}, 400), ({'data_url': 'not a data URL'}, 400),
                 (payload(b'', 'audio/webm'), 400),
                 (payload(WEBM, 'video/webm'), 415),
                 (payload(b'....ftypisom', 'audio/mp4'), 415),
                 (payload(WEBM, 'audio/webm;codecs=vorbis'), 415),
                 ({**payload(), 'mime_type': 'audio/ogg;codecs=opus'}, 415),
                 (payload(b'not webm'), 415),
                 ({'data_url': 'data:audio/webm;base64,AB=='}, 400),
                 ({'data_url': 'data:audio/webm;base64,AA==\n'}, 400)]
        for value, status in cases:
            with self.subTest(status=status, kind=type(value).__name__):
                with self.assertRaises(CapabilityError) as caught:
                    gd.decode_payload(value)
                self.assertEqual(caught.exception.status, status)

    def test_supported_basic_container_signatures_are_not_transcoded(self):
        for raw, mime in ((OGG, 'audio/ogg;codecs=opus'), (OGG, 'audio/opus'),
                          (WAV, 'audio/wav')):
            with self.subTest(mime=mime):
                decoded = gd.decode_payload(payload(raw, mime))
                self.assertEqual(decoded.data, raw)
                self.assertEqual(decoded.mime_type, mime.split(';')[0])

    def test_raw_and_catalog_limits_are_independent_and_exact(self):
        self.assertEqual(gd.RAW_AUDIO_BYTES, 8_388_608)
        self.assertEqual(gd.LEGACY_DATA_URL_CHARS, 3_145_728)
        raw = WEBM + b'\x00' * (gd.RAW_AUDIO_BYTES - len(WEBM))
        value = payload(raw)
        with self.assertRaises(CapabilityError) as caught:
            gd.decode_payload(value)
        self.assertEqual(caught.exception.status, 413)
        self.assertEqual(len(gd.decode_payload(value, binary_upload=True).data), gd.RAW_AUDIO_BYTES)
        with self.assertRaises(CapabilityError) as caught:
            gd.decode_payload(payload(raw + b'\x00'), binary_upload=True)
        self.assertEqual(caught.exception.status, 413)



def completed(text='გამარჯობა English Giorgi'):
    return {'candidates': [{'finishReason': 'STOP', 'content': {
        'role': 'model', 'parts': [{'text': text}]}}]}


class ResponseTests(unittest.TestCase):
    def test_completed_original_language_text_and_explicit_silence(self):
        self.assertTrue(callable(getattr(gd, 'parse_response', None)))
        for text in ('გამარჯობა English Giorgi', ''):
            self.assertEqual(gd.parse_response(json.dumps(completed(text)).encode()),
                             {'ok': True, 'transcript': text, 'provider': 'gemini'})
        value = completed('a')
        value['candidates'][0]['content']['parts'] = [
            {'text': 'private reasoning', 'thought': True}, {'text': 'ქართული'}, {'text': ' English'}]
        self.assertEqual(gd.parse_response(json.dumps(value).encode())['transcript'], 'ქართული English')

    def test_incomplete_blocked_nontext_and_malformed_are_never_silence(self):
        self.assertTrue(callable(getattr(gd, 'parse_response', None)))
        cases = [{}, {'candidates': []}, {'candidates': [completed()['candidates'][0]] * 2},
                 {**completed(), 'promptFeedback': {'blockReason': 'SAFETY'}},
                 {**completed(), 'promptFeedback': {'safetyRatings': [{'blocked': True}]}}]
        for reason in ('MAX_TOKENS', 'CONTINUATION', 'SAFETY', None):
            value = completed()
            value['candidates'][0]['finishReason'] = reason
            cases.append(value)
        for parts in ([], [{'thought': True, 'text': 'hidden'}], [{'functionCall': {}}],
                      [{'inlineData': {'data': ''}}], [{'text': None}], [{'text': 'x', 'thought': 1}]):
            value = completed()
            value['candidates'][0]['content']['parts'] = parts
            cases.append(value)
        for value in cases:
            with self.subTest(shape=list(value)):
                with self.assertRaises(CapabilityError) as caught:
                    gd.parse_response(json.dumps(value).encode())
                self.assertEqual(caught.exception.status, 502)
        for raw in (b'bad JSON', b'{"candidates":[],"candidates":[]}', b'\xff'):
            with self.assertRaises(CapabilityError):
                gd.parse_response(raw)

    def test_exact_response_and_utf8_transcript_bounds(self):
        self.assertTrue(callable(getattr(gd, 'parse_response', None)))
        self.assertEqual(gd.RESPONSE_BYTES, 262144)
        self.assertEqual(gd.TRANSCRIPT_BYTES, 65536)
        text = 'ა' * (65536 // 3) + 'x'
        self.assertEqual(len(text.encode()), 65536)
        raw = json.dumps(completed(text), ensure_ascii=False).encode()
        self.assertEqual(gd.parse_response(raw)['transcript'], text)
        with self.assertRaises(CapabilityError):
            gd.parse_response(json.dumps(completed(text + 'x'), ensure_ascii=False).encode())
        raw = json.dumps(completed('')).encode()
        self.assertEqual(gd.parse_response(raw + b' ' * (262144 - len(raw)))['transcript'], '')
        with self.assertRaises(CapabilityError):
            gd.parse_response(raw + b' ' * (262145 - len(raw)))


OWNER = Owner('synthetic', 'fixture-user', 'fixture-a', 'captured-socket', (), frozenset({'audio', 'network'}))
HOME = 'C:/synthetic-only/hermes/profiles/fixture-a'
# Harmless fixture value: never a real credential, never emitted in assertion output.
_FAKE_KEY = 'synthetic-dictation-test-only'


class Host:
    def __init__(self):
        self.home = HOME
        self.valid = True
        self.cancelled = False
        self.permissions = {'audio', 'network'}
        self.authorizations = []
        self.current_owner = OWNER
        self.key = _FAKE_KEY

    def authorize(self, owner, permission):
        self.authorizations.append((owner.key, permission))
        if permission not in self.permissions or owner.key != self.current_owner.key:
            raise CapabilityError(403, 'fixture private failure must never escape')
        return owner

    def context(self, *, remaining=5, source='catalog'):
        return gd.RequestContext(deadline=time.monotonic() + remaining, source=source,
                                 owner_valid=lambda: self.valid, cancelled=lambda: self.cancelled)

    def binding(self, **changes):
        options = dict(profile=OWNER.profile, expected_home=HOME, model='gemini-reviewed-001',
                       model_reviewed=True, cloud_approved=True, key_supplier=lambda: self.key)
        options.update(changes)
        return gd.HostBinding(**options)

    def service(self, *, bindings=None, transport=None, budget=None):
        return gd.GeminiDictation(bindings=[self.binding()] if bindings is None else bindings,
            authorize=self.authorize, current_home=lambda owner: self.home,
            budget=budget if budget is not None else gd.SharedBudget(max_requests=10,
                max_output_tokens=40960, window_seconds=60),
            transport_factory=(lambda: httpx.MockTransport(transport)) if transport is not None else None)


class BindingTests(SyntheticAsync):
    async def test_host_validity_callback_failures_are_static_even_capability_errors(self):
        host = Host()
        service = host.service()
        def private_failure():
            raise CapabilityError(418, _FAKE_KEY + ' private callback')
        try:
            for name in ('owner_valid', 'cancelled'):
                context = replace(host.context(), **{name: private_failure})
                with self.assertRaises(CapabilityError) as caught:
                    service.require_ready(OWNER, context=context)
                self.assertEqual(caught.exception.status, 410)
                self.assertNotIn(_FAKE_KEY, str(caught.exception))
        finally:
            await service.aclose()

    async def test_missing_binding_key_model_permission_home_cloud_or_owner_refuses_locally(self):
        self.assertTrue(callable(getattr(gd, 'GeminiDictation', None)))
        for defect, status in [('binding', 403), ('key', 503), ('model', 503),
                               ('audio', 403), ('network', 403), ('home', 403),
                               ('cloud', 403), ('review', 503), ('owner', 403), ('cancel', 410),
                               ('expiry', 410), ('disconnect', 410)]:
            with self.subTest(defect=defect):
                host, calls = Host(), []
                changes = {}
                if defect == 'key': host.key = None
                if defect == 'model': changes['model'] = None
                if defect in ('audio', 'network'): host.permissions.remove(defect)
                if defect == 'home': host.home = HOME + '-replacement'
                if defect == 'cloud': changes['cloud_approved'] = False
                if defect == 'review': changes['model_reviewed'] = False
                if defect == 'owner': host.current_owner = replace(OWNER, connection='different')
                if defect == 'cancel': host.cancelled = True
                if defect == 'disconnect': host.valid = False
                service = host.service(bindings=[] if defect == 'binding' else [host.binding(**changes)],
                                       transport=lambda request: calls.append(request))
                context = host.context(remaining=-1 if defect == 'expiry' else 5)
                try:
                    with self.assertRaises(CapabilityError) as caught:
                        service.require_ready(OWNER, context=context)
                    self.assertEqual(caught.exception.status, status)
                    self.assertNotIn('fixture private', str(caught.exception))
                    self.assertEqual(calls, [])
                finally:
                    await service.aclose()

    async def test_host_binding_is_immutable_redacted_and_validates_model_resource(self):
        self.assertTrue(callable(getattr(gd, 'HostBinding', None)))
        host = Host()
        binding = host.binding()
        self.assertNotIn(_FAKE_KEY, repr(binding))
        with self.assertRaises((AttributeError, TypeError)):
            binding.model = 'gemini-other'
        for model in ('gemini-latest', 'gemini-x/latest', 'https://elsewhere',
                      'gemini-x?key=bad', 'gemini-x%2fother', 'gemini-x\r\nheader', '', 'gpt-4'):
            with self.subTest(kind='invalid model'):
                with self.assertRaises(ValueError):
                    host.binding(model=model)
        for profile in ('all', 'current', 'Fixture-a', '../other'):
            with self.assertRaises(ValueError):
                host.binding(profile=profile)

    async def test_upload_admission_rechecks_both_permissions_and_narrow_raw_mime_limit(self):
        self.assertTrue(callable(getattr(gd, 'GeminiDictation', None)))
        host = Host()
        service = host.service()
        metadata = dict(purpose='transcribe', filename='fixture.webm',
                        mimeType='audio/webm;codecs=opus', byteSize=gd.RAW_AUDIO_BYTES)
        try:
            service.validate_upload_metadata(OWNER, metadata, context=host.context(source='upload'))
            self.assertEqual([x[1] for x in host.authorizations], ['audio', 'network'])
            for changes, status in (({'byteSize': gd.RAW_AUDIO_BYTES + 1}, 413),
                                    ({'mimeType': 'audio/mp4'}, 415), ({'byteSize': 0}, 400)):
                with self.assertRaises(CapabilityError) as caught:
                    service.validate_upload_metadata(OWNER, {**metadata, **changes}, context=host.context(source='upload'))
                self.assertEqual(caught.exception.status, status)
        finally:
            await service.aclose()


class TransportTests(SyntheticAsync):
    async def test_factory_tls_environment_redirect_and_retry_controls_are_explicit(self):
        host = Host()
        service = host.service()
        original_client = httpx.AsyncClient
        transport = httpx.MockTransport(lambda request: httpx.Response(200, json=completed()))
        try:
            with patch.object(gd.httpx, 'AsyncHTTPTransport', return_value=transport) as make_transport, \
                    patch.object(gd.httpx, 'AsyncClient', wraps=original_client) as make_client:
                await service.transcribe(OWNER, payload(), context=host.context())
            options = make_transport.call_args.kwargs
            self.assertIs(options['verify'], True)
            self.assertIs(options['trust_env'], False)
            self.assertEqual(options['retries'], 0)
            options = make_client.call_args.kwargs
            self.assertIs(options['verify'], True)
            self.assertIs(options['trust_env'], False)
            self.assertIs(options['follow_redirects'], False)
            self.assertIsNone(options['proxy'])
        finally:
            await service.aclose()

    async def test_streamed_response_bounds_ignore_untrusted_content_length_and_close_stream(self):
        class Stream(httpx.AsyncByteStream):
            def __init__(self, raw):
                self.raw, self.closed, self.reads = raw, False, 0
            async def __aiter__(self):
                for index in range(0, len(self.raw), 16384):
                    self.reads += 1
                    yield self.raw[index:index + 16384]
            async def aclose(self):
                self.closed = True
        for size in (262144, 262145):
            host = Host()
            raw = json.dumps(completed('')).encode()
            stream = Stream(raw + b' ' * (size - len(raw)))
            service = host.service(transport=lambda request: httpx.Response(200, stream=stream,
                headers={'content-type': 'application/json; charset=utf-8', 'content-length': '1'}))
            try:
                if size == 262144:
                    self.assertEqual((await service.transcribe(OWNER, payload(), context=host.context()))['transcript'], '')
                else:
                    with self.assertRaises(CapabilityError) as caught:
                        await service.transcribe(OWNER, payload(), context=host.context())
                    self.assertEqual(caught.exception.status, 502)
                self.assertTrue(stream.closed)
                self.assertLessEqual(stream.reads, 17)
            finally:
                await service.aclose()

    async def test_authority_is_recaptured_immediately_before_send_and_at_publication(self):
        for phase in ('send', 'publish'):
            for defect in ('home', 'permission', 'connection'):
                with self.subTest(phase=phase, defect=defect):
                    host, calls = Host(), []
                    def change():
                        if defect == 'home': host.home += '-rebound'
                        if defect == 'permission': host.permissions.remove('network')
                        if defect == 'connection': host.current_owner = replace(OWNER, connection='new-socket')
                    def handler(request):
                        calls.append(None)
                        if phase == 'publish': change()
                        return httpx.Response(200, json=completed())
                    service = host.service()
                    def factory():
                        if phase == 'send': change()
                        return httpx.MockTransport(handler)
                    service._transport_factory = factory
                    try:
                        with self.assertRaises(CapabilityError) as caught:
                            await service.transcribe(OWNER, payload(), context=host.context())
                        self.assertEqual(caught.exception.status, 403)
                        self.assertEqual(len(calls), 0 if phase == 'send' else 1)
                    finally:
                        await service.aclose()

    async def test_serialized_utf8_body_cap_is_explicit_and_exact_before_dispatch(self):
        self.assertEqual(gd.BODY_BYTES, 12_000_000)
        audio = gd.decode_payload(payload())
        body = gd._request_body(audio)
        with patch.object(gd, 'BODY_BYTES', len(body)):
            self.assertEqual(gd._request_body(audio), body)
        with patch.object(gd, 'BODY_BYTES', len(body) - 1):
            host, calls = Host(), []
            service = host.service(transport=lambda request: calls.append(None))
            try:
                with self.assertRaises(CapabilityError) as caught:
                    await service.transcribe(OWNER, payload(), context=host.context())
                self.assertEqual(caught.exception.status, 413)
                self.assertEqual(calls, [])
            finally:
                await service.aclose()

    async def test_compression_and_unexpected_media_types_are_rejected_before_stream_read(self):
        class MustNotRead(httpx.AsyncByteStream):
            async def __aiter__(self):
                raise AssertionError('unexpected encoding/type must be refused before reading')
                yield b''
        for headers in ({'content-type': 'application/json', 'content-encoding': 'gzip'},
                        {'content-type': 'text/html'}, {}, {'content-type': 'application/octet-stream'}):
            with self.subTest(headers=headers):
                host, calls = Host(), []
                def handler(request):
                    calls.append(None)
                    return httpx.Response(200, headers=headers, stream=MustNotRead())
                service = host.service(transport=handler)
                try:
                    with self.assertRaises(CapabilityError) as caught:
                        await service.transcribe(OWNER, payload(), context=host.context())
                    self.assertEqual(caught.exception.detail, 'invalid dictation provider response')
                    self.assertEqual(caught.exception.status, 502)
                    self.assertEqual(len(calls), 1)
                finally:
                    await service.aclose()

    async def test_http_failures_are_one_attempt_sanitized_and_auth_binding_latches_unusable(self):
        for status in (301, 307, 400, 401, 403, 408, 429, 500, 503):
            with self.subTest(status=status):
                host, calls = Host(), []
                def handler(request):
                    calls.append(None)
                    return httpx.Response(status, json=completed(_FAKE_KEY + ' private body'),
                                          headers={'location': 'https://not-allowed.invalid'})
                service = host.service(transport=handler)
                try:
                    with self.assertRaises(CapabilityError) as caught:
                        await service.transcribe(OWNER, payload(), context=host.context())
                    self.assertEqual(caught.exception.status, 503 if status in (401, 403) else 429 if status == 429 else 502)
                    self.assertNotIn(_FAKE_KEY, str(caught.exception))
                    self.assertEqual(len(calls), 1)
                    if status in (401, 403):
                        host.key = 'different-synthetic-test-key'
                        with self.assertRaises(CapabilityError) as caught:
                            await service.transcribe(OWNER, payload(), context=host.context())
                        self.assertEqual(caught.exception.status, 503)
                        self.assertEqual(len(calls), 1)
                finally:
                    await service.aclose()

    async def test_transport_losses_are_not_retried_or_leaked(self):
        for error in (httpx.ConnectError, httpx.ReadError, httpx.WriteError,
                      httpx.ConnectTimeout, httpx.ReadTimeout, httpx.WriteTimeout, httpx.PoolTimeout):
            with self.subTest(kind=error.__name__):
                host, calls = Host(), []
                def handler(request):
                    calls.append(None)
                    raise error(_FAKE_KEY + ' private exception')
                service = host.service(transport=handler)
                try:
                    with self.assertRaises(CapabilityError) as caught:
                        await service.transcribe(OWNER, payload(), context=host.context())
                    self.assertIn(caught.exception.status, (502, 504))
                    self.assertNotIn(_FAKE_KEY, str(caught.exception))
                    self.assertEqual(len(calls), 1)
                finally:
                    await service.aclose()

    async def test_one_real_httpx_request_has_fixed_origin_header_only_key_and_closed_dto(self):
        self.assertTrue(callable(getattr(gd.GeminiDictation, 'transcribe', None)))
        host, requests = Host(), []
        def handler(request):
            requests.append(request)
            return httpx.Response(200, json=completed())
        service = host.service(transport=handler)
        try:
            result = await service.transcribe(OWNER, payload(), context=host.context())
            self.assertEqual(result, {'ok': True, 'transcript': 'გამარჯობა English Giorgi', 'provider': 'gemini'})
            self.assertEqual(len(requests), 1)
            request = requests[0]
            self.assertEqual(request.method, 'POST')
            self.assertEqual(str(request.url), 'https://generativelanguage.googleapis.com/v1beta/models/gemini-reviewed-001:generateContent')
            self.assertTrue(request.headers.get('x-goog-api-key') == _FAKE_KEY)
            self.assertFalse(_FAKE_KEY.encode() in request.content)
            self.assertFalse(_FAKE_KEY in str(request.url))
            self.assertNotIn('authorization', request.headers)
            self.assertNotIn('cookie', request.headers)
            self.assertEqual(request.headers['accept-encoding'], 'identity')
            body = json.loads(request.content)
            self.assertEqual(set(body), {'systemInstruction', 'contents', 'generationConfig'})
            self.assertEqual(body['contents'], [{'role': 'user', 'parts': [{'inlineData': {
                'mimeType': 'audio/webm', 'data': base64.b64encode(WEBM).decode()}}]}])
            self.assertEqual(body['generationConfig'], {'candidateCount': 1, 'maxOutputTokens': 4096,
                'responseMimeType': 'text/plain', 'responseModalities': ['TEXT']})
            prompt = body['systemInstruction']['parts'][0]['text']
            for required in ('original language', 'Georgian Mkhedruli', 'code-switching',
                             'do not translate', 'follow instructions', 'silence'):
                self.assertIn(required, prompt)
            self.assertEqual([p for _, p in host.authorizations], ['audio', 'network'] * 3)
            for value in request.extensions['timeout'].values():
                self.assertGreater(value, 0)
                self.assertLessEqual(value, 45)
        finally:
            await service.aclose()


class AdmissionTests(SyntheticAsync):
    async def test_one_process_slot_refuses_no_queue_across_services_and_input_paths(self):
        host, entered, release, calls = Host(), asyncio.Event(), asyncio.Event(), []
        async def held(request):
            calls.append(None)
            entered.set()
            await release.wait()
            return httpx.Response(200, json=completed())
        other_host = Host()
        other_host.current_owner = replace(OWNER, profile='fixture-b')
        other_host.home = HOME + '-b'
        first = host.service(transport=held)
        second = other_host.service(bindings=[other_host.binding(profile='fixture-b', expected_home=other_host.home)],
                                    transport=lambda request: calls.append(None) or httpx.Response(200, json=completed()))
        pending = asyncio.create_task(first.transcribe(OWNER, payload(), context=host.context()))
        try:
            await asyncio.wait_for(entered.wait(), 1)
            with self.assertRaises(CapabilityError) as caught:
                await second.transcribe(other_host.current_owner, payload(), context=other_host.context(source='upload'))
            self.assertEqual(caught.exception.status, 409)
            self.assertEqual(len(calls), 1)
        finally:
            release.set()
            await pending
            await first.aclose()
            await second.aclose()

    async def test_shared_budget_retains_uncertain_attempt_and_enforces_output_reservation(self):
        for request_limit, output_limit in ((1, 8192), (2, 4096)):
            with self.subTest(requests=request_limit, tokens=output_limit):
                host, calls = Host(), []
                budget = gd.SharedBudget(max_requests=request_limit, max_output_tokens=output_limit, window_seconds=60)
                def lost(request):
                    calls.append(None)
                    raise httpx.ReadError('uncertain synthetic delivery')
                first, second = host.service(transport=lost, budget=budget), host.service(transport=lost, budget=budget)
                try:
                    with self.assertRaises(CapabilityError):
                        await first.transcribe(OWNER, payload(), context=host.context())
                    with self.assertRaises(CapabilityError) as caught:
                        await second.transcribe(OWNER, payload(), context=host.context(source='upload'))
                    self.assertEqual(caught.exception.status, 429)
                    self.assertEqual(len(calls), 1)
                finally:
                    await first.aclose()
                    await second.aclose()

    async def test_budget_requires_explicit_finite_capacity_and_rolls_without_refund(self):
        self.assertTrue(callable(getattr(gd.SharedBudget, 'reserve', None)))
        for options in ({'max_requests': -1}, {'max_requests': True}, {'max_output_tokens': -1},
                        {'window_seconds': 0}, {'window_seconds': float('inf')}):
            with self.assertRaises(ValueError):
                gd.SharedBudget(**{**dict(max_requests=1, max_output_tokens=4096, window_seconds=60), **options})
        now = [10.0]
        budget = gd.SharedBudget(max_requests=1, max_output_tokens=4096, window_seconds=60, clock=lambda: now[0])
        budget.reserve()
        with self.assertRaises(CapabilityError):
            budget.reserve()
        now[0] = 70.0
        budget.reserve()


class ResistantTransport(httpx.MockTransport):
    def __init__(self):
        self.entered = asyncio.Event()
        self.cancel_seen = asyncio.Event()
        self.release_io = asyncio.Event()
        self.close_entered = asyncio.Event()
        self.release_close = asyncio.Event()
        self.closed = False
        self.calls = 0
        super().__init__(self._held)

    async def _held(self, request):
        self.calls += 1
        self.entered.set()
        try:
            await self.release_io.wait()
        except asyncio.CancelledError:
            self.cancel_seen.set()
            await self.release_io.wait()
        return httpx.Response(200, json=completed('late private transcript'))

    async def aclose(self):
        self.close_entered.set()
        await self.release_close.wait()
        self.closed = True


class SettlementTests(SyntheticAsync):
    async def test_disconnect_release_and_overall_timeout_cancel_without_late_publication(self):
        for reason in ('disconnect', 'release', 'overall'):
            with self.subTest(reason=reason):
                host, transport = Host(), ResistantTransport()
                service = host.service()
                service._transport_factory = lambda: transport
                # Only shorten the overall deadline in a synthetic fixture.
                with patch.object(gd, 'OVERALL_SECONDS', .06 if reason == 'overall' else 45):
                    pending = asyncio.create_task(service.transcribe(OWNER, payload(), context=host.context()))
                    try:
                        await asyncio.wait_for(transport.entered.wait(), 1)
                        if reason == 'disconnect': host.valid = False
                        if reason == 'release': host.cancelled = True
                        await asyncio.wait_for(transport.cancel_seen.wait(), .5)
                        self.assertFalse(pending.done())
                        transport.release_io.set()
                        transport.release_close.set()
                        with self.assertRaises(CapabilityError) as caught:
                            await pending
                        self.assertEqual(caught.exception.status, 504 if reason == 'overall' else 410)
                        self.assertTrue(transport.closed)
                        self.assertEqual(transport.calls, 1)
                    finally:
                        transport.release_io.set()
                        transport.release_close.set()
                        await asyncio.gather(pending, return_exceptions=True)
                        await service.aclose()

    async def test_client_constructor_failure_closes_the_owned_transport_without_sending(self):
        host, transport = Host(), ResistantTransport()
        transport.release_close.set()
        service = host.service()
        service._transport_factory = lambda: transport
        try:
            with patch.object(gd.httpx, 'AsyncClient', side_effect=RuntimeError('private synthetic init failure')):
                with self.assertRaises(CapabilityError) as caught:
                    await service.transcribe(OWNER, payload(), context=host.context())
            self.assertEqual(caught.exception.status, 502)
            self.assertTrue(transport.closed)
            self.assertEqual(transport.calls, 0)
        finally:
            await service.aclose()

    async def test_first_cancellation_during_response_close_also_settles_owned_cleanup(self):
        class ClosingStream(httpx.AsyncByteStream):
            def __init__(self):
                self.entered, self.release, self.closed = asyncio.Event(), asyncio.Event(), False
            async def __aiter__(self):
                yield json.dumps(completed()).encode()
            async def aclose(self):
                self.entered.set()
                await self.release.wait()
                self.closed = True
        host, stream = Host(), ClosingStream()
        service = host.service(transport=lambda request: httpx.Response(200, stream=stream,
                                             headers={'content-type': 'application/json'}))
        pending = asyncio.create_task(service.transcribe(OWNER, payload(), context=host.context()))
        try:
            await asyncio.wait_for(stream.entered.wait(), 1)
            pending.cancel()
            await asyncio.sleep(.02)
            self.assertFalse(pending.done())
            stream.release.set()
            with self.assertRaises(asyncio.CancelledError):
                await pending
            self.assertTrue(stream.closed)
        finally:
            stream.release.set()
            await asyncio.gather(pending, return_exceptions=True)
            await service.aclose()

    async def test_first_cancellation_during_client_close_does_not_interrupt_cleanup(self):
        host, transport = Host(), ResistantTransport()
        transport.release_io.set()
        service = host.service()
        service._transport_factory = lambda: transport
        other = host.service(transport=lambda request: httpx.Response(200, json=completed()))
        pending = asyncio.create_task(service.transcribe(OWNER, payload(), context=host.context()))
        try:
            await asyncio.wait_for(transport.close_entered.wait(), 1)
            pending.cancel()
            await asyncio.sleep(.02)
            self.assertFalse(pending.done())
            self.assertFalse(transport.closed)
            with self.assertRaises(CapabilityError) as caught:
                await other.transcribe(OWNER, payload(), context=host.context())
            self.assertEqual(caught.exception.status, 409)
            transport.release_close.set()
            with self.assertRaises(asyncio.CancelledError):
                await pending
            self.assertTrue(transport.closed)
        finally:
            transport.release_close.set()
            await asyncio.gather(pending, return_exceptions=True)
            await service.aclose()
            await other.aclose()

    async def test_overall_45_second_deadline_is_still_enforced_at_publication(self):
        host = Host()
        service = host.service(transport=lambda request: httpx.Response(200, json=completed()))
        # Deterministic loop stall after the provider worker has completed but
        # before the caller resumes to publish. No network or real sleep45.
        original_run = service._run
        async def stalled(*args, **kwargs):
            result = await original_run(*args, **kwargs)
            time.sleep(.06)
            return result
        service._run = stalled
        try:
            self.assertEqual(gd.OVERALL_SECONDS, 45.0)
            with patch.object(gd, 'OVERALL_SECONDS', .02):
                with self.assertRaises(CapabilityError) as caught:
                    await service.transcribe(OWNER, payload(), context=host.context())
            self.assertEqual(caught.exception.status, 504)
        finally:
            await service.aclose()

    async def test_cancellation_never_publishes_late_text_or_releases_slot_before_io_and_client_close(self):
        host, transport = Host(), ResistantTransport()
        service = host.service()
        service._transport_factory = lambda: transport
        other = host.service(transport=lambda request: httpx.Response(200, json=completed()))
        pending = asyncio.create_task(service.transcribe(OWNER, payload(), context=host.context()))
        try:
            await asyncio.wait_for(transport.entered.wait(), 1)
            pending.cancel()
            await asyncio.wait_for(transport.cancel_seen.wait(), 1)
            self.assertFalse(pending.done())
            with self.assertRaises(CapabilityError) as caught:
                await other.transcribe(OWNER, payload(), context=host.context())
            self.assertEqual(caught.exception.status, 409)
            transport.release_io.set()
            await asyncio.wait_for(transport.close_entered.wait(), 1)
            pending.cancel()  # repeated cancellation must not interrupt owned cleanup
            await asyncio.sleep(.02)
            self.assertFalse(pending.done())
            with self.assertRaises(CapabilityError) as caught:
                await other.transcribe(OWNER, payload(), context=host.context())
            self.assertEqual(caught.exception.status, 409)
            transport.release_close.set()
            with self.assertRaises(asyncio.CancelledError):
                await pending
            self.assertTrue(transport.closed)
            self.assertEqual(transport.calls, 1)
            self.assertTrue((await other.transcribe(OWNER, payload(), context=host.context()))['ok'])
        finally:
            transport.release_io.set()
            transport.release_close.set()
            await asyncio.gather(pending, return_exceptions=True)
            await service.aclose()
            await other.aclose()

    async def test_original_upload_expiry_cancels_but_settles_without_refresh_or_publication(self):
        host, transport = Host(), ResistantTransport()
        service = host.service()
        service._transport_factory = lambda: transport
        context = host.context(remaining=.08, source='upload')
        original_deadline = context.deadline
        pending = asyncio.create_task(service.transcribe(OWNER, payload(), context=context))
        try:
            await asyncio.wait_for(transport.entered.wait(), 1)
            await asyncio.wait_for(transport.cancel_seen.wait(), .5)
            self.assertFalse(pending.done())
            self.assertEqual(context.deadline, original_deadline)
            transport.release_io.set()
            transport.release_close.set()
            with self.assertRaises(CapabilityError) as caught:
                await pending
            self.assertEqual(caught.exception.status, 410)
            self.assertEqual(transport.calls, 1)
        finally:
            transport.release_io.set()
            transport.release_close.set()
            await asyncio.gather(pending, return_exceptions=True)
            await service.aclose()

    async def test_shutdown_settles_owned_work_and_never_publishes_its_late_result(self):
        host, transport = Host(), ResistantTransport()
        service = host.service()
        service._transport_factory = lambda: transport
        pending = asyncio.create_task(service.transcribe(OWNER, payload(), context=host.context()))
        closing = None
        try:
            await asyncio.wait_for(transport.entered.wait(), 1)
            closing = asyncio.create_task(service.aclose())
            await asyncio.sleep(.02)
            self.assertFalse(closing.done())
            transport.release_io.set()
            await asyncio.wait_for(transport.close_entered.wait(), 1)
            self.assertFalse(closing.done())
            transport.release_close.set()
            await closing
            result = (await asyncio.gather(pending, return_exceptions=True))[0]
            self.assertIsInstance(result, (CapabilityError, asyncio.CancelledError))
            self.assertTrue(transport.closed)
        finally:
            transport.release_io.set()
            transport.release_close.set()
            await asyncio.gather(pending, *([closing] if closing is not None else []), return_exceptions=True)
            await service.aclose()


if __name__ == '__main__':
    unittest.main()
