"""Isolated original auth-middleware and provider-discovery regression."""
import asyncio
import contextvars
import json
import sys
import time
from pathlib import Path

def main():
    upstream = Path(sys.argv[1]); sys.path.insert(0, str(upstream))
    from fastapi import FastAPI, Request
    import httpx
    from hermes_cli.dashboard_auth import DashboardAuthProvider, Session, register_provider, clear_providers, list_session_providers
    from hermes_cli.dashboard_auth.middleware import gated_auth_middleware, _auto_sso_response
    from pc.addon import Adapter
    from pc.policy import Owner
    class Real(DashboardAuthProvider):
        name, display_name = 'fixture-oauth', 'Fixture OAuth'
        def start_login(self, **kw): raise RuntimeError('no network')
        def complete_login(self, **kw): raise RuntimeError('no network')
        def verify_session(self, **kw): return None
        def refresh_session(self, **kw): raise RuntimeError('no network')
        def revoke_session(self, **kw): pass
    clear_providers(); register_provider(Real())
    adapter = Adapter.__new__(Adapter)
    adapter._delegation = contextvars.ContextVar('test-delegation', default=None)
    adapter._install_provider()
    assert [p.name for p in list_session_providers()] == ['fixture-oauth'], 'private verifier polluted real login roster'
    app = FastAPI(); app.state.auth_required = True
    app.middleware('http')(gated_auth_middleware)
    @app.get('/api/identity')
    async def identity(request: Request):
        session = request.state.session
        return {'provider': session.provider, 'user_id': session.user_id}
    async def run():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url='http://127.0.0.1') as client:
            assert (await client.get('/api/identity')).status_code == 401
            request = Request({'type':'http','method':'GET','path':'/','headers':[], 'scheme':'http','server':('127.0.0.1',80),'query_string':b''})
            response = _auto_sso_response(request)
            assert response is not None and 'provider=fixture-oauth' in response.headers['location']
            async def one(n):
                owner = Owner('fixture-oauth', 'alice-' + str(n), 'default', str(n), (), frozenset({'read'}))
                nonce = 'synthetic-nonce-' + str(n)
                token = adapter._delegation.set({'nonce':nonce, 'owner':owner})
                try:
                    response = await client.get('/api/identity', cookies={'hermes_session_at':nonce,'hermes_session_provider':adapter.provider.name})
                    assert response.status_code == 200, response.text
                    assert response.json() == {'provider':'fixture-oauth','user_id':owner.user_id}, response.text
                finally:
                    adapter._delegation.reset(token)
            await asyncio.gather(*(one(i) for i in range(8)))
            assert (await client.get('/api/identity', cookies={'hermes_session_at':'synthetic-nonce-0','hermes_session_provider':adapter.provider.name})).status_code == 401
    asyncio.run(run())
    print(json.dumps({'passed':True,'checks':5,'parallelIdentities':8,'originalMiddleware':True,'singleProviderAutoselection':True}))

if __name__ == '__main__': main()
