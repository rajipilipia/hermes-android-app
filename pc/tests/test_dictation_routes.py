"""Synthetic FastAPI route seam only; never imports the original runtime."""
from __future__ import annotations
import contextvars
import inspect
import unittest
import httpx
from fastapi import FastAPI
from pydantic import BaseModel, ConfigDict

from pc.tests.test_gemini_dictation import (Host, OWNER, SyntheticAsync, completed, payload,
                                           setUpModule, tearDownModule)
try:
    from pc import dictation_routes as dr
except ImportError:
    dr = None


class AudioDTO(BaseModel):
    model_config = ConfigDict(extra='forbid')
    data_url: str
    mime_type: str | None = None


class RouteTests(SyntheticAsync):
    async def test_delegated_missing_service_context_owner_and_profile_never_call_original(self):
        app, context, original_calls = FastAPI(), contextvars.ContextVar('fixture', default=None), []
        @app.post('/api/audio/transcribe')
        async def original(payload: AudioDTO, profile: str | None = None):
            original_calls.append(None)
            raise AssertionError('upstream Whisper/voice_mode must be unreachable')
        dr.install_dictation_routes(app, context.get, None)
        host = Host()
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url='http://fixture.invalid') as client:
            for value, selected, status in (({}, OWNER.profile, 403),
                ({'owner': OWNER}, 'fixture-b', 403),
                ({'owner': OWNER}, OWNER.profile, 503),
                ({'owner': OWNER, 'dictation_context': host.context()}, OWNER.profile, 503)):
                token = context.set(value)
                try:
                    result = await client.post('/api/audio/transcribe', params={'profile': selected}, json=payload())
                    self.assertEqual(result.status_code, status)
                    self.assertEqual(set(result.json()), {'detail'})
                finally:
                    context.reset(token)
            self.assertEqual(original_calls, [])

    async def test_original_asgi_validation_stays_authoritative_and_config_is_not_enabled(self):
        app, context, calls, host = FastAPI(), contextvars.ContextVar('fixture', default=None), [], Host()
        @app.post('/api/audio/transcribe')
        async def original(payload: AudioDTO, profile: str | None = None):
            raise AssertionError('delegated original path forbidden')
        @app.get('/api/audio/voice-config')
        async def config():
            from fastapi import HTTPException
            raise HTTPException(403, 'withheld')
        service = host.service(transport=lambda request: calls.append(None) or httpx.Response(200, json=completed()))
        dr.install_dictation_routes(app, context.get, service)
        token = context.set({'owner': OWNER, 'dictation_context': host.context()})
        try:
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url='http://fixture.invalid') as client:
                result = await client.post('/api/audio/transcribe', params={'profile': OWNER.profile}, json={**payload(), 'model': 'injected'})
                self.assertEqual(result.status_code, 422)
                result = await client.get('/api/audio/voice-config')
                self.assertEqual(result.status_code, 403)
                self.assertEqual(calls, [])
        finally:
            context.reset(token)
            await service.aclose()

    async def test_context_none_preserves_original_but_delegated_both_sources_only_use_new_service(self):
        self.assertIsNotNone(dr, 'safe delegated route helper is missing')
        app, context, original_calls, provider_calls, host = FastAPI(), contextvars.ContextVar('fixture', default=None), [], [], Host()
        @app.post('/api/audio/transcribe')
        async def original(payload: AudioDTO, profile: str | None = None):
            original_calls.append(profile)
            return {'original_pc': True}
        def provider(request):
            provider_calls.append(None)
            return httpx.Response(200, json=completed())
        service = host.service(transport=provider)
        dr.install_dictation_routes(app, context.get, service)
        route = next(r for r in app.routes if r.path == '/api/audio/transcribe')
        self.assertEqual(inspect.signature(route.dependant.call), inspect.signature(original))
        try:
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url='http://fixture.invalid') as client:
                self.assertEqual((await client.post('/api/audio/transcribe', json=payload())).json(), {'original_pc': True})
                for source in ('catalog', 'upload'):
                    token = context.set({'owner': OWNER, 'dictation_context': host.context(source=source)})
                    try:
                        result = await client.post('/api/audio/transcribe', params={'profile': OWNER.profile}, json=payload())
                        self.assertEqual(result.status_code, 200)
                        self.assertEqual(result.json(), {'ok': True, 'transcript': 'გამარჯობა English Giorgi', 'provider': 'gemini'})
                    finally:
                        context.reset(token)
                self.assertEqual(original_calls, [None])
                self.assertEqual(len(provider_calls), 2)
        finally:
            await service.aclose()


if __name__ == '__main__':
    unittest.main()
