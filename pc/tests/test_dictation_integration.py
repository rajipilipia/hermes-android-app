"""Focused integration regressions; actual original-runtime proof is separate."""
import inspect
import unittest


class InjectionContract(unittest.TestCase):
    def test_production_requires_explicit_host_factory_not_client_configuration(self):
        from pc.production_composition import Composition, run
        self.assertIn('dictation_factory', inspect.signature(run).parameters)
        self.assertIn('dictation_factory', inspect.signature(Composition).parameters)
        from pc.dictation_integration import DictationSpec
        self.assertEqual(set(DictationSpec.__dataclass_fields__), {'bindings', 'budget', 'transport_factory'})


class IntegrationBehavior(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        import asyncio, base64, contextvars, tempfile, threading, types
        from pathlib import Path
        from fastapi import FastAPI
        from pydantic import BaseModel
        from pc.addon import Adapter, Downloads
        from pc.media import Uploads
        from pc.policy import Policy
        self.directory = tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[2]/'.cache'/'pc-lab')
        self.home = Path(self.directory.name).resolve()
        self.transport = types.SimpleNamespace(closed=False, identity={'provider':'fixture','user_id':'alice'}, connection='actual-captured')
        # Weakref-capable fixture transport; actual WSTransport is proved by
        # production_dictation_proof, never claimed by these focused tests.
        class Transport: pass
        transport = Transport()
        transport.__dict__.update(self.transport.__dict__)
        self.transport = transport
        a = self.adapter = Adapter.__new__(Adapter)
        a.app = FastAPI()
        class Payload(BaseModel):
            data_url: str
            mime_type: str | None = None
        self.fallback_calls = 0
        async def original(payload: Payload, profile: str):
            self.fallback_calls += 1
            return {'ok':True, 'transcript':'original', 'provider':'fixture'}
        a.app.post('/api/audio/transcribe')(original)
        a.policy = Policy({('fixture','alice','research'):((),frozenset({'read','audio','network'}))}, ())
        a.policy._expected_homes = {'research':self.home}
        a.server = types.SimpleNamespace(_ok=lambda rid,result:result)
        a.provider = types.SimpleNamespace(name='synthetic-delegation')
        def current_owner(transport, profile, permission):
            from pc.catalog import CapabilityError
            if a._closed or transport.closed:
                raise CapabilityError(410, 'owner disconnected')
            return a.policy.authorize(transport.identity, profile, permission, transport.connection)
        a.owner = current_owner
        a.downloads, a.uploads = Downloads(self.home), Uploads(self.home)
        a._closed, a._closing, a.dictation = False, None, None
        a._lock, a._write_barrier, a._slots = threading.Lock(), threading.Lock(), threading.BoundedSemaphore(8)
        a._tasks = set()
        a._delegation = contextvars.ContextVar('test-delegation', default=None)
        a._admission_deadline = contextvars.ContextVar('test-admission', default=None)
        self.owner = a.owner(self.transport, 'research', 'audio')
        self.raw = b'RIFF0000WAVEsynthetic'
        self.payload = {'data_url':'data:audio/wav;base64,'+base64.b64encode(self.raw).decode(), 'mime_type':'audio/wav'}
        self.metadata = {'profile':'research','purpose':'transcribe','filename':'fixture.wav','mimeType':'audio/wav','byteSize':len(self.raw)}
        self.sent = []
        from pc.gemini_dictation import SharedBudget
        self.budget = SharedBudget(max_requests=30,max_output_tokens=122880,window_seconds=300)

    async def asyncTearDown(self):
        if self.adapter.dictation is not None:
            await self.adapter.dictation.aclose()
        self.adapter.uploads.close()
        self.adapter.downloads.close()
        self.directory.cleanup()

    def configure(self, **changes):
        import httpx
        from pc.dictation_integration import DictationSpec, install
        from pc.gemini_dictation import HostBinding
        values = dict(profile='research',expected_home=str(self.home),model='gemini-fixture',
                      model_reviewed=True,cloud_approved=True,key_supplier=lambda:'synthetic-only')
        values.update(changes)
        async def exchange(request):
            self.sent.append(request)
            return httpx.Response(200,json={'candidates':[{'finishReason':'STOP','content':{'parts':[{'text':'  ქართული mixed  '}]}}]})
        return install(self.adapter,lambda:DictationSpec(bindings=(HostBinding(**values),),
                          budget=self.budget,transport_factory=lambda:httpx.MockTransport(exchange)))

    async def direct(self, payload=None):
        from pc.catalog import validate_call
        a = self.adapter
        call = validate_call({'operation':'POST /api/audio/transcribe','profile':'research',
                              'body':self.payload if payload is None else payload})
        a._slots.acquire(False)
        return await a._run_admitted(call,self.owner,self.transport)

    def begin(self):
        import sys, types
        from unittest.mock import patch
        module = types.ModuleType('tui_gateway.transport')
        module.current_transport = lambda:self.transport
        with patch.dict(sys.modules,{'tui_gateway.transport':module}):
            return self.adapter.media_handler(1,self.metadata,'desktop.upload.begin')

    async def test_direct_uses_one_service_and_closed_exact_dto(self):
        self.configure()
        result = await self.direct()
        self.assertEqual(result,{'status':200,'body':{'ok':True,'transcript':'  ქართული mixed  ','provider':'gemini'}})
        self.assertEqual(len(self.sent),1)
        self.assertEqual(self.fallback_calls,0)
        self.assertNotIn(b'synthetic-only',self.sent[0].content)

    async def test_missing_key_model_home_binding_network_audio_deny_without_reservation_or_send(self):
        from pc.catalog import CapabilityError
        from pc.dictation_integration import DictationSpec, install
        cases = [dict(key_supplier=lambda:None),dict(model=None),dict(expected_home=str(self.home/'wrong')),
                 dict(model_reviewed=False),dict(cloud_approved=False),'missing-binding','network','audio']
        for case in cases:
            with self.subTest(case=str(case)):
                a = self.adapter
                if a.dictation is not None:
                    await a.dictation.aclose()
                    a.dictation = None
                a.policy._grants[('fixture','alice','research')] = (),frozenset({'read','audio','network'})
                if case == 'missing-binding':
                    install(a,lambda:DictationSpec(bindings=(),budget=self.budget))
                else:
                    self.configure(**(case if isinstance(case,dict) else {}))
                if case in ('network','audio'):
                    a.policy._grants[('fixture','alice','research')] = (),frozenset({'read','audio','network'}-{case})
                try:
                    result = await self.direct()
                except CapabilityError as exc:
                    result = {'status':exc.status}
                self.assertGreaterEqual(result['status'],400)
                self.assertGreaterEqual(self.begin()['status'],400)
                self.assertFalse(a.uploads._items)
                self.assertFalse(self.sent)
                self.assertFalse(self.budget._entries)

    async def test_invalid_audio_rejected_without_provider_budget(self):
        self.configure()
        result = await self.direct({'data_url':'data:audio/wav;base64,YmFk','mime_type':'audio/wav'})
        self.assertEqual(result['status'],415)
        self.assertIn('do not retry automatically',result['body']['detail'])
        self.assertFalse(self.sent)
        self.assertFalse(self.budget._entries)

    async def test_upload_begin_narrow_limit_and_mime_before_general_store(self):
        self.configure()
        for changes in ({'byteSize':8388609},{'mimeType':'audio/mp4'},{'mimeType':'video/webm'}):
            with self.subTest(changes=changes):
                original = dict(self.metadata)
                self.metadata.update(changes)
                self.assertGreaterEqual(self.begin()['status'],400)
                self.assertFalse(self.adapter.uploads._items)
                self.metadata = original
        self.assertFalse(self.sent)
        self.assertFalse(self.budget._entries)

    async def test_original_fallback_is_only_nondelegated(self):
        self.configure()
        import httpx
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=self.adapter.app),base_url='http://fixture') as client:
            result = await client.post('/api/audio/transcribe?profile=research',json=self.payload)
        self.assertEqual(result.json()['provider'],'fixture')
        self.assertEqual(self.fallback_calls,1)
        self.assertFalse(self.sent)

    async def test_context_never_refreshes_upload_expiry(self):
        import time, weakref
        from pc.dictation_integration import request_context
        expired = time.monotonic()-1
        item = {'expires':expired,'cancelled':False,'transport':weakref.ref(self.transport)}
        context = request_context(self.adapter,self.owner,self.transport,deadline=time.monotonic()+120,source='upload',item=item)
        self.assertEqual(context.deadline,expired)
        self.assertEqual(context.source,'upload')
        self.transport.connection = 'rebound'
        self.assertFalse(context.owner_valid())

    async def test_missing_or_invalid_factory_cannot_create_service(self):
        from pc.dictation_integration import install
        for factory in (None,lambda:None,lambda:object()):
            with self.assertRaises(ValueError):
                install(self.adapter,factory)
            self.assertIsNone(self.adapter.dictation)
        self.assertFalse(self.sent)


class OwnedClose(unittest.IsolatedAsyncioTestCase):
    async def test_composition_concurrent_close_cannot_restore_before_service_settlement(self):
        import asyncio, types
        from pc.addon import Adapter
        from pc.production_composition import Composition
        a = Adapter.__new__(Adapter)
        a._closed, a._closing = False, None
        entered, release = asyncio.Event(), asyncio.Event()
        async def close_owned():
            a._closed = True
            entered.set()
            await release.wait()
        a._close_owned = close_owned
        composition = Composition(None,None)
        composition.adapter = a
        restored = []
        composition._restore_registrations = lambda:restored.append(True)
        first = asyncio.create_task(composition.close())
        await entered.wait()
        second = asyncio.create_task(composition.close())
        await asyncio.sleep(.01)
        try:
            self.assertFalse(second.done(), 'concurrent close must await owned service cleanup')
            self.assertFalse(restored)
        finally:
            release.set()
            await asyncio.gather(first,second)

    async def test_adapter_closes_owned_resources_once(self):
        from pc.addon import Adapter
        adapter = Adapter.__new__(Adapter)
        adapter._closing = None
        closed = []
        async def close_owned():
            closed.append(True)
        adapter._close_owned = close_owned
        await adapter.aclose()
        await adapter.aclose()
        self.assertEqual(closed, [True])


if __name__ == '__main__':
    unittest.main()
