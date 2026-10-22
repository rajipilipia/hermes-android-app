"""Synthetic HTTPX dictation through the actual pinned original runtime.

Test-only: reuse production_proof.child's scrubbed startup, native broker, tickets,
WS/RPC, original ASGI and lifespan. No providers, live discovery or enrollment.
Run ONLY through production_test_runner. The 60-second expiry case deliberately
ages an untouched real upload reservation; it does not replace a clock or TTL.
"""
from __future__ import annotations

import argparse
import asyncio
import base64
from contextlib import ExitStack, redirect_stdout
import hashlib
import io
import json
import os
from pathlib import Path
import sys
import subprocess
import tempfile
import threading
import time
import types
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

PROJECT = Path(__file__).resolve().parents[1]
UPSTREAM = Path('C:/example/hermes-agent')
GEORGIAN = '  გამარჯობა, გიორგი.\nთბილისში ვბრუნდები.  '
MIXED = 'რაჯი, send the revised drawing to გიორგი — არ თარგმნო.\n'
WAVE = b'RIFF\x10\x00\x00\x00WAVEfmt \x00\x00\x00\x00synthetic-only'


def payload():
    return {'data_url': 'data:audio/wav;base64,' + base64.b64encode(WAVE).decode('ascii'),
            'mime_type': 'audio/wav'}


class Wire:
    """Real original authenticated WS; no direct handler invocation."""
    def __init__(self, ws, check):
        self.ws, self.check, self.sequence = ws, check, 0

    def rpc(self, method, params):
        self.sequence += 1
        request_id = self.sequence
        self.ws.send(json.dumps({'jsonrpc': '2.0', 'id': request_id,
                                 'method': method, 'params': params}))
        while True:
            reply = json.loads(self.ws.recv(timeout=20))
            if reply.get('id') == request_id:
                self.check('result' in reply, 'registered original WS method ' + method)
                return reply['result']

    def direct(self, profile='research'):
        return self.rpc('desktop.call', {'operation': 'POST /api/audio/transcribe',
                                        'profile': profile, 'body': payload()})

    def begin(self, **changes):
        metadata = {'profile': 'research', 'purpose': 'transcribe',
                    'filename': 'synthetic.wav', 'mimeType': 'audio/wav', 'byteSize': len(WAVE)}
        metadata.update(changes)
        return self.rpc('desktop.upload.begin', metadata)

    def upload(self):
        before = time.monotonic()
        result = self.begin()
        after = time.monotonic()
        self.check(result['status'] == 200, 'actual upload reservation admitted')
        body = result['body']
        self.check(set(body) == {'uploadId', 'chunkBytes', 'expiresInSeconds'} and
                   body['chunkBytes'] == 65536 and body['expiresInSeconds'] == 60,
                   'unchanged closed upload begin DTO and original sixty-second TTL')
        handle = body['uploadId']
        appended = self.rpc('desktop.upload.append', {'profile': 'research', 'uploadId': handle,
            'offset': 0, 'sequence': 0, 'dataBase64': base64.b64encode(WAVE).decode('ascii')})
        self.check(appended == {'status': 200, 'body': {'offset': len(WAVE), 'sequence': 1}},
                   'actual upload exact append acknowledgement')
        return handle, before, after

    def complete(self, handle):
        return self.rpc('desktop.upload.complete', {'profile': 'research', 'uploadId': handle})


class Scenario:
    def __init__(self, base, mode):
        import httpx
        from . import gemini_dictation as gd
        self.base, self.mode, self.httpx, self.gd = base, mode, httpx, gd
        self.home = base / 'managed' / 'profiles' / 'research'
        self.adapter = None
        self.services, self.contexts, self.sends, self.transports = [], [], [], []
        self.factory_calls = self.begin_calls = self.original_calls = 0
        self.output = GEORGIAN
        self.on_send = None
        self.effect = 'success'
        self.expiry_entered, self.expiry_cancelled = threading.Event(), threading.Event()
        self.expiry_release = None
        self.expiry_close_entered = threading.Event()
        self.expiry_close_release = None
        self.expiry_item = None
        self.expiry_observation = None
        self.original_paths = []
        self.check = None
        self.assertions = []
        self.budget = gd.SharedBudget(max_requests=20, max_output_tokens=81920, window_seconds=300)

    def factory(self):
        from .dictation_integration import DictationSpec
        self.factory_calls += 1
        binding = self.gd.HostBinding(profile='research', expected_home=str(self.home),
            model='gemini-synthetic-proof', model_reviewed=True, cloud_approved=True,
            key_supplier=lambda: 'synthetic-proof-not-a-provider-key')
        return DictationSpec(bindings=(binding,), budget=self.budget,
                             transport_factory=self.make_transport)

    def make_transport(self):
        scenario = self
        class ObservedTransport(self.httpx.MockTransport):
            async def aclose(self):
                if scenario.effect == 'expiry':
                    scenario.expiry_close_release = asyncio.Event()
                    scenario.expiry_close_entered.set()
                    await scenario.expiry_close_release.wait()
                await super().aclose()
                self.proof_closed = True
        transport = ObservedTransport(scenario.exchange)
        transport.proof_closed = False
        self.transports.append(transport)
        return transport

    async def exchange(self, request):
        self.sends.append(request)
        self.check(request.method == 'POST' and str(request.url) ==
            'https://generativelanguage.googleapis.com/v1beta/models/gemini-synthetic-proof:generateContent',
            'HTTPX fixed single POST target')
        self.check(set(request.url.params) == set() and
                   request.headers.get('x-goog-api-key') == 'synthetic-proof-not-a-provider-key',
                   'synthetic credential confined to provider header')
        body = json.loads(request.content)
        self.check(body == {
            'systemInstruction': {'parts': [{'text': self.gd.SYSTEM_INSTRUCTION}]},
            'generationConfig': {'candidateCount': 1, 'maxOutputTokens': 4096,
                'responseMimeType': 'text/plain', 'responseModalities': ['TEXT']},
            'contents': [{'role': 'user', 'parts': [{'inlineData': {
                'mimeType': 'audio/wav', 'data': base64.b64encode(WAVE).decode('ascii')}}]}]},
            'actual HTTPX request carries exact fixture bytes instruction and closed generation settings')
        self.check(all(text in body['systemInstruction']['parts'][0]['text'] for text in
                       ('original language', 'Georgian Mkhedruli', 'code-switching', 'do not translate')),
                   'provider instruction explicitly preserves Georgian and code-switching without translation')
        if self.on_send is not None:
            self.on_send()
        if self.effect == 'expiry':
            context = self.contexts[-1]['context']
            self.expiry_observation = {'source': context.source, 'deadline': context.deadline,
                'itemExpires': self.expiry_item['expires'],
                'remainingAtSend': context.deadline - time.monotonic()}
            self.check(context.source == 'upload' and context.deadline == self.expiry_item['expires'],
                       'service receives untouched original claimed-upload absolute expiry')
            self.expiry_release = asyncio.Event()
            self.expiry_entered.set()
            try:
                await self.expiry_release.wait()
            except asyncio.CancelledError:
                # Deliberately resistant synthetic I/O: parent must retain claim,
                # spool, admission/write barrier until this actual worker settles.
                self.expiry_cancelled.set()
                await self.expiry_release.wait()
        response = {'candidates': [{'finishReason': 'STOP', 'content': {
            'role': 'model', 'parts': [{'text': self.output}]}}]}
        return self.httpx.Response(200, json=response)

    def install_spies(self, stack):
        from . import addon, production_runtime, production_proof
        original_install = addon.install
        original_run = production_runtime.run
        original_init = self.gd.GeminiDictation.__init__
        original_transcribe = self.gd.GeminiDictation.transcribe
        from .media import Uploads
        original_begin = Uploads.begin

        def install(*args, **kwargs):
            self.adapter = original_install(*args, **kwargs)
            return self.adapter

        def run(**kwargs):
            # Alter only the freshly written SYNTHETIC manifest, before load and
            # fingerprint capture. This is host injection, never a DTO grant.
            path = Path(kwargs['manifest'])
            manifest = json.loads(path.read_text(encoding='utf-8'))
            permissions = manifest['principals'][0]['profiles']['research']['permissions']
            if 'network' not in permissions:
                permissions.append('network')
            path.write_text(json.dumps(manifest), encoding='utf-8')
            if self.mode != 'red':
                kwargs['dictation_factory'] = self.factory
            return original_run(**kwargs)

        def init(service, *args, **kwargs):
            original_init(service, *args, **kwargs)
            self.services.append(service)

        async def transcribe(service, owner, incoming, *, context):
            self.contexts.append({'context': context, 'owner': owner, 'service': service})
            # This observes actual captured host state. It never replaces owner,
            # authority callbacks, RequestContext, route result or service logic.
            grant = self.adapter._delegation.get()
            self.check(isinstance(grant, dict) and grant.get('owner').key == owner.key,
                       'service executes under actual Adapter delegated Owner')
            return await original_transcribe(service, owner, incoming, context=context)

        def begin(uploads, *args, **kwargs):
            self.begin_calls += 1
            return original_begin(uploads, *args, **kwargs)

        # Keep the actual original transcription function, Pydantic validation,
        # strict decoding, temporary-file lifecycle and profile scope unchanged.
        # Replace ONLY its lazy provider import, before any original voice code.
        if 'tools.voice_mode' in sys.modules:
            raise AssertionError('proof must not inherit an already imported voice provider')
        voice = types.ModuleType('tools.voice_mode')
        def transcribe_recording(path):
            from hermes_constants import get_hermes_home
            self.original_calls += 1
            target = Path(path)
            self.original_paths.append(target)
            self.check(target.is_relative_to(self.base) and target.read_bytes() == WAVE,
                       'original nondelegated transcription decoded exact bytes to synthetic temporary file')
            self.check(Path(get_hermes_home()).resolve() == self.home,
                       'original nondelegated provider executes in actual named-profile config scope')
            return {'success': True, 'transcript': '  SYNTHETIC ORIGINAL PC  ', 'provider': 'fixture'}
        voice.transcribe_recording = transcribe_recording
        sys.modules['tools.voice_mode'] = voice
        stack.callback(sys.modules.pop, 'tools.voice_mode', None)

        stack.enter_context(patch.object(addon, 'install', install))
        stack.enter_context(patch.object(production_runtime, 'run', run))
        stack.enter_context(patch.object(self.gd.GeminiDictation, '__init__', init))
        stack.enter_context(patch.object(self.gd.GeminiDictation, 'transcribe', transcribe))
        stack.enter_context(patch.object(Uploads, 'begin', begin))
        if self.mode != 'failure':
            stack.enter_context(patch.object(production_proof, 'exercise', self.exercise))

    def authenticate(self, client, check):
        verifier = 'd' * 43
        challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b'=').decode()
        response = client.get('/auth/native/authorize', params={'provider': 'fixture',
            'code_challenge': challenge, 'code_challenge_method': 'S256',
            'redirect_uri': 'http://127.0.0.1:23456/callback', 'state': 'dictation-fixture'})
        check(response.status_code == 302, 'original native authorize for dictation')
        response = client.get('/auth/callback', params={'code': 'synthetic-code', 'state': 'synthetic-csrf'})
        check(response.status_code == 302, 'original native callback for dictation')
        code = parse_qs(urlsplit(response.headers['location']).query)['code'][0]
        request = {'code': code, 'code_verifier': verifier}
        token = client.post('/auth/native/token', json=request)
        check(token.status_code == 200, 'same-process original native token redemption')
        check(client.post('/auth/native/token', json=request).status_code == 400,
              'original native code remains single-use')
        auth = {'Authorization': 'Bearer ' + token.json()['access_token']}
        check(client.get('/api/auth/me', headers=auth).json()['user_id'] == 'alice',
              'original authenticated native principal')
        return auth

    def ticket(self, client, auth):
        response = client.post('/api/auth/ws-ticket', headers=auth)
        self.check(response.status_code == 200, 'original verified one-use WS ticket')
        return response.json()['ticket']

    def exercise(self, port, check, home, root, manifest):
        import websockets.sync.client
        from .production_proof import bootstrap_primary
        native_check = check
        def observed_check(value, label):
            native_check(value, label)
            self.assertions.append(label)
        check = self.check = observed_check
        check(home == self.home, 'proof reuses exact original synthetic named home')
        url = 'http://127.0.0.1:' + str(port)
        with self.httpx.Client(base_url=url, trust_env=False, timeout=20, follow_redirects=False) as client:
            check(client.post('/api/auth/ws-ticket').status_code == 401, 'original unauthenticated ticket denial')
            auth = self.authenticate(client, check)
            socket_url = 'ws://127.0.0.1:' + str(port) + '/api/ws?ticket=' + self.ticket(client, auth)
            with websockets.sync.client.connect(socket_url, open_timeout=10) as ws:
                wire = Wire(ws, check)
                primary = bootstrap_primary(wire.rpc, check)
                check(primary == 'research', 'actual cold bootstrap chooses named-only owner')
                before = len(self.sends)
                direct = wire.direct(primary)
                check(direct == {'status': 200, 'body': {
                    'ok': True, 'transcript': GEORGIAN, 'provider': 'gemini'}},
                    'actual original direct transcription preserves exact Georgian closed DTO; got ' + str(direct['status']))
                if self.mode == 'red':
                    raise AssertionError('baseline unexpectedly admitted approved dictation without host injection')
                check(len(self.sends) == before + 1 and len(self.contexts) == 1 and
                      self.contexts[0]['context'].source == 'catalog',
                      'direct path makes exactly one HTTPX send with actual catalog context')
                check(self.factory_calls == 1 and len(self.services) == 1 and
                      self.services[0]._budget is self.budget,
                      'Composition creates exactly one service from one host factory and shared budget')
                self.output = MIXED
                handle, _, _ = wire.upload()
                uploaded = wire.complete(handle)
                check(uploaded == {'status': 200, 'body': {
                    'ok': True, 'transcript': MIXED, 'provider': 'gemini'}},
                    'actual original binary claim preserves exact mixed-language closed DTO')
                check(len(self.sends) == before + 2 and self.contexts[-1]['context'].source == 'upload',
                      'binary begin append claim complete makes exactly one additional HTTPX send')
                check(wire.complete(handle)['status'] == 404 and len(self.sends) == before + 2,
                      'binary completion consumed once without provider retry')
                check(self.original_calls == 0, 'delegated direct and upload never fall back to original PC provider')
                self.controls(wire, client, auth, root)
                self.late_denials(wire, root)
                self.expiry(wire)
                check(self.original_calls == 1, 'only explicit nondelegated request reached synthetic original boundary')
            # Verify that the dictation proof did not replace original WS admission.
            try:
                with websockets.sync.client.connect(socket_url, open_timeout=5) as replay:
                    replay.recv(timeout=5)
            except Exception:
                check(True, 'original dictation socket ticket replay denied')
            else:
                raise AssertionError('original one-use ticket replay admitted')

    def controls(self, wire, client, auth, root):
        check = self.check
        check(wire.rpc('desktop.audio.config', {'profile': 'research'})['status'] == 403,
              'audio config remains403 despite approved dictation injection')
        check(wire.direct('default')['status'] == 403, 'ungranted canonical default cannot transcribe')
        count, begin_count = len(self.sends), self.begin_calls
        for changes, expected, label in [({'byteSize': 8388609}, 413, '8MiB plus one byte'),
                ({'mimeType': 'audio/mp4'}, 415, 'unsupported MP4'),
                ({'mimeType': 'video/webm'}, 415, 'video container MIME')]:
            check(wire.begin(**changes)['status'] == expected, label + ' denied at upload begin')
            check(self.begin_calls == begin_count and not self.adapter.uploads._items,
                  label + ' denied BEFORE reservation or spool creation')
        check(len(self.sends) == count, 'metadata denials perform no provider HTTPX send')
        # Original endpoint provider boundary is intentionally synthetic. The
        # original request's validation/auth route is exercised over real TCP.
        result = client.post('/api/audio/transcribe', params={'profile': 'research'},
                             headers=auth, json=payload())
        check(result.status_code == 200 and result.json() == {'ok': True,
              'transcript': 'SYNTHETIC ORIGINAL PC', 'provider': 'fixture'} and self.original_calls == 1,
              'authenticated nondelegated original PC route remains unchanged')
        check(len(self.original_paths) == 1 and not self.original_paths[0].exists(),
              'original nondelegated transcription removes its actual temporary file')
        invalid = client.post('/api/audio/transcribe', params={'profile': 'research'}, headers=auth,
                              json={'data_url': 'data:audio/wav;base64,NOT-BASE64'})
        check(invalid.status_code == 400 and self.original_calls == 1,
              'original nondelegated strict data-URL validation precedes provider boundary')
        check(len(self.sends) == count, 'nondelegated original PC route does not invoke Gemini')
        import websockets.sync.client
        ticket = self.ticket(client, {'Authorization': 'Bearer synthetic-mallory'})
        url = str(client.base_url).rstrip('/').replace('http://', 'ws://') + '/api/ws?ticket=' + ticket
        with websockets.sync.client.connect(url, open_timeout=10) as ws:
            denied = Wire(ws, check)
            check(denied.direct()['status'] == 403, 'unknown original authenticated principal cannot transcribe')
            check(denied.begin()['status'] == 403, 'unknown principal cannot reserve transcription spool')
        check(len(self.sends) == count, 'principal denials perform no provider send')

    def late_denials(self, wire, root):
        check, policy = self.check, self.adapter.policy
        from tui_gateway import server
        with self.adapter._lock:
            transports = tuple(self.adapter._connections)
        transport = next(t for t in transports if t.auth_identity.get('user_id') == 'alice' and not t.closed)
        grant_key = ('fixture', 'alice', 'research')
        original_grants = policy._grants
        original_grant = original_grants[grant_key]
        original_home = server._profile_home
        with self.adapter._lock:
            connection = self.adapter._connections[transport]
        def permission_change():
            changed = dict(original_grants)
            changed[grant_key] = original_grant[0], original_grant[1] - {'network'}
            policy._grants = types.MappingProxyType(changed)
        def home_change():
            server._profile_home = lambda name: root
        def owner_change():
            with self.adapter._lock:
                self.adapter._connections[transport] = 'synthetic-rebound-owner'
        for action, label in [(permission_change, 'network permission'), (home_change, 'actual runtime home'),
                              (owner_change, 'captured transport Owner connection')]:
            before = len(self.sends)
            self.on_send = action
            try:
                result = wire.direct()
                check(result['status'] in (403, 410) and 'transcript' not in result['body'],
                      'late ' + label + ' change prevents transcript publication')
                check(len(self.sends) == before + 1, 'late ' + label + ' denial never retries sent request')
            finally:
                policy._grants = original_grants
                server._profile_home = original_home
                with self.adapter._lock:
                    self.adapter._connections[transport] = connection
                self.on_send = None
        check(all(t.proof_closed for t in self.transports), 'all settled synthetic HTTPX transports closed')

    def expiry(self, wire):
        check = self.check
        self.effect = 'expiry'
        handle, before, after = wire.upload()
        with self.adapter.uploads._lock:
            item = self.adapter.uploads._items[handle]
        self.expiry_item = item
        expires = item['expires']
        check(before + 60 <= expires <= after + 60, 'untouched upload item has actual begin plus sixty-second expiry')
        original_expiry = expires
        # This is the only deliberate elapsed-time gate. No polling, clock patch,
        # item mutation, fake claim, shortened TTL or now+60 replacement.
        time.sleep(max(0, expires - time.monotonic() - 5.0))
        check(item['expires'] == original_expiry and 0 < expires - time.monotonic() <= 5.2,
              'actual original reservation aged to its last five seconds without deadline renewal')
        result, errors = [], []
        def complete():
            try:
                result.append(wire.complete(handle))
            except BaseException as exc:
                errors.append(exc)
        worker = threading.Thread(target=complete, name='dictation-expiry-client')
        sends = len(self.sends)
        worker.start()
        try:
            check(self.expiry_entered.wait(5), 'actual claimed-upload provider request entered before fixed expiry')
            check(self.expiry_cancelled.wait(10), 'untouched original sixty-second expiry cancels resistant HTTPX request')
            with self.adapter.uploads._lock:
                held = self.adapter.uploads._items.get(handle)
                check(held is item and held['claimed'] and not held['file'].closed,
                      'expired resistant provider work retains actual upload claim spool and quota')
            check(self.adapter._write_barrier.locked(), 'expired resistant provider work retains actual write barrier')
            check(worker.is_alive(), 'completion cannot publish or finish while resistant I/O remains unsettled')
            item['task'].get_loop().call_soon_threadsafe(self.expiry_release.set)
            check(self.expiry_close_entered.wait(5), 'expired request enters independently gated actual HTTPX client close')
            with self.adapter.uploads._lock:
                check(self.adapter.uploads._items.get(handle) is item and not item['file'].closed,
                      'actual claim spool and quota remain held THROUGH asynchronous HTTPX client close')
            check(self.adapter._write_barrier.locked() and worker.is_alive() and
                  not self.transports[-1].proof_closed,
                  'write barrier and unpublished completion remain held THROUGH HTTPX transport close')
        finally:
            if self.expiry_release is not None:
                item['task'].get_loop().call_soon_threadsafe(self.expiry_release.set)
                if self.expiry_close_entered.wait(5) and self.expiry_close_release is not None:
                    item['task'].get_loop().call_soon_threadsafe(self.expiry_close_release.set)
            worker.join(timeout=10)
        if errors:
            raise errors[0]
        check(not worker.is_alive() and len(result) == 1 and result[0]['status'] in (410, 504) and
              'transcript' not in result[0]['body'], 'expired upload never publishes late synthetic transcript')
        check(time.monotonic() >= original_expiry and item['expires'] == original_expiry,
              'fixed original expiration, not fresh completion TTL, determined cancellation')
        check(item['file'].closed and handle not in self.adapter.uploads._items and
              not self.adapter._write_barrier.locked(), 'claim spool quota and write barrier release ONLY after settlement')
        check(len(self.sends) == sends + 1 and wire.complete(handle)['status'] == 404,
              'expired upload consumed once with exactly one HTTPX send and no replay')
        check(not self.services[0]._operations and all(t.proof_closed for t in self.transports),
              'expired provider operation and HTTPX client transport fully settled')
        self.effect = 'success'

    def verify_closed(self):
        assertions = []
        def require(value, label):
            if not value:
                raise AssertionError(label)
            assertions.append(label)
        require(self.factory_calls == 1 and len(self.services) == 1, 'one factory and one Composition-owned service')
        require(self.services[0]._closed and not self.services[0]._operations, 'Composition closes service and settles owned operations')
        require(all(t.proof_closed for t in self.transports), 'Composition leaves no synthetic HTTPX transport open')
        require(not self.gd._PROVIDER_SLOT.locked(), 'process-global provider slot released')
        if self.mode == 'failure':
            require(not self.sends and not self.transports, 'original builder failure creates no provider transport or send')
        else:
            require(len(self.budget._entries) == len(self.sends), 'one shared budget charge per actual HTTPX send including denials')
            require(not self.adapter.uploads._items, 'all original upload reservations released')
        return assertions


def child(base, selected):
    from . import production_proof
    if not base.is_relative_to(PROJECT / '.cache' / 'pc-lab'):
        raise RuntimeError('child fixture outside project pc-lab')
    os.environ.update(HOME=str(base), USERPROFILE=str(base), HERMES_HOME=str(base / 'managed'),
        APPDATA=str(base / 'roaming'), LOCALAPPDATA=str(base / 'local'),
        TMP=str(base), TEMP=str(base), TMPDIR=str(base),
        HERMES_GATEWAY_LOCK_DIR=str(base / 'locks'))
    if selected == 'default':
        production_proof.child(base)
        print(json.dumps({'dictationProof': 'default-deny', 'synthetic': True, 'injected': False}))
        return
    scenario = Scenario(base, selected)
    captured = io.StringIO()
    import builtins
    original_print = builtins.print
    def capture_print(*args, **kwargs):
        # Original main may replace sys.stdout; observe records without changing
        # its normal streams or relying on redirect_stdout surviving startup.
        if args and isinstance(args[0], str):
            captured.write(args[0] + '\n')
        return original_print(*args, **kwargs)
    try:
        with ExitStack() as stack:
            scenario.install_spies(stack)
            stack.enter_context(patch.object(builtins, 'print', capture_print))
            production_proof.child(base, 'failure' if selected == 'failure' else 'normal')
    except BaseException:
        print(json.dumps({'dictationProof': selected, 'completed': False,
            'passedExerciseChecksBeforeFailure': len(scenario.assertions),
            'factoryCalls': scenario.factory_calls, 'serviceInstances': len(scenario.services),
            'httpxSends': len(scenario.sends), 'synthetic': True}))
        raise
    runtime = None
    for line in captured.getvalue().splitlines():
        try:
            value = json.loads(line)
        except (ValueError, TypeError):
            continue
        if isinstance(value, dict) and 'checks' in value:
            runtime = value
    if runtime is None:
        raise AssertionError('original runtime fixture emitted no completed assertion record')
    post = scenario.verify_closed()
    print(json.dumps({'dictationProof': selected, 'runtimeChecks': runtime['checks'],
        'postCleanupChecks': len(post), 'totalChecks': runtime['checks'] + len(post),
        'postCleanupAssertions': post, 'factoryCalls': scenario.factory_calls,
        'serviceInstances': len(scenario.services), 'httpxSends': len(scenario.sends),
        'httpxTransports': len(scenario.transports), 'sharedBudgetCharges': len(scenario.budget._entries),
        'originalNondelegatedCalls': scenario.original_calls,
        'originalUploadExpiry': scenario.expiry_observation,
        'synthetic': True, 'liveProviderAcceptance': False}, ensure_ascii=True))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument('--red-baseline', action='store_true')
    mode.add_argument('--startup-failure', action='store_true')
    mode.add_argument('--default-deny', action='store_true')
    parser.add_argument('--child', help=argparse.SUPPRESS)
    parser.add_argument('--scenario', choices=('red', 'failure', 'default', 'normal'), help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    guard = os.environ.get('HERMES_PC_SOURCE_TEST_ROOT')
    if not guard or getattr(sys, '_hermes_pc_source_test_guard', None) != guard:
        raise RuntimeError('run proof through repaired pc.production_test_runner only')
    scratch = Path(os.environ['TMPDIR']).resolve()
    if not scratch.is_relative_to(PROJECT / '.cache' / 'pc-lab'):
        raise RuntimeError('proof fixture homes must remain under project pc-lab')
    if args.child:
        child(Path(args.child).resolve(), args.scenario)
        return
    selected = ('red' if args.red_baseline else 'failure' if args.startup_failure else
                'default' if args.default_deny else 'normal')
    # The original runtime retains its process-lifetime log lock. As in
    # production_proof.outer, remove the temporary tree AFTER the child exits.
    with tempfile.TemporaryDirectory(prefix='pc-production-', dir=scratch) as directory:
        result = subprocess.run([sys.executable, '-B', '-m', 'pc.production_dictation_proof',
            '--child', str(Path(directory).resolve()), '--scenario', selected], cwd=PROJECT,
            env=dict(os.environ), capture_output=True, text=True, timeout=160)
        print(result.stdout, end='')
        print(result.stderr, end='', file=sys.stderr)
        raise SystemExit(result.returncode)


if __name__ == '__main__':
    main()
