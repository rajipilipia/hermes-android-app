"""Disposable lab launcher, intentionally NOT an installer or production server.

Only .cache/pc-lab homes are accepted. It never launches the upstream dashboard
lifespan (cron, updater, external plugins, or MCP discovery). Real original auth
middleware, original /api/ws handler/dispatch, and original REST services run.
"""
from __future__ import annotations
import argparse
from contextlib import asynccontextmanager
import hmac
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import time


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--media-fixture',action='store_true')
    for field in ('upstream', 'home', 'policy', 'token-file', 'ready'):
        parser.add_argument('--' + field, required=True)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    home = Path(args.home).resolve(strict=True)
    if not home.is_relative_to(root / '.cache' / 'pc-lab') or Path(os.environ.get('HERMES_HOME', '')).resolve() != home:
        raise SystemExit('refusing a non-lab or mismatched HERMES_HOME')
    from .catalog import SOURCE_COMMIT
    upstream = Path(args.upstream).resolve(strict=True)
    revision = subprocess.check_output(['git', '-C', str(upstream), 'rev-parse', 'HEAD'], text=True).strip()
    if revision != SOURCE_COMMIT:
        raise SystemExit('upstream source pin mismatch')
    changes = subprocess.check_output(['git', '-C', str(upstream), 'status', '--porcelain', '--untracked-files=no'], text=True)
    if changes:
        raise SystemExit('refusing dirty upstream code')
    sys.path.insert(0, str(upstream))
    from hermes_cli import web_server
    from hermes_cli.dashboard_auth import DashboardAuthProvider, Session, register_provider
    from hermes_cli.dashboard_auth.base import InvalidCodeError, RefreshExpiredError
    from .bootstrap import load_pinned_onboarding
    load_pinned_onboarding(upstream)
    from tui_gateway import server
    from hermes_state import SessionDB
    from .policy import Policy
    from .addon import install
    import uvicorn

    # This token only authenticates this disposable loopback lab. Never print it
    # or reuse it as an actual Nous/provider credential.
    lab_token = Path(args.token_file).read_text(encoding='utf-8')

    class LabIdentity(DashboardAuthProvider):
        name, display_name = 'android-lab', 'Disposable local proof identity'
        def start_login(self, **kwargs):
            raise InvalidCodeError('lab has no interactive login')
        def complete_login(self, **kwargs):
            raise InvalidCodeError('lab has no interactive login')
        def verify_session(self, *, access_token):
            if not hmac.compare_digest(access_token, lab_token):
                return None
            return Session('alice', '', 'Synthetic Alice', '', self.name, int(time.time()) + 3600, '', '')
        def refresh_session(self, **kwargs):
            raise RefreshExpiredError('lab has no refresh')
        def revoke_session(self, **kwargs):
            return None

    register_provider(LabIdentity())
    app = web_server.app
    app.state.auth_required = True
    app.state.bound_host = '127.0.0.1'
    app.state.trusted_public_hosts = frozenset()
    app.state.delegated_request_count = 0
    app.state.delegated_identity_preserved = True

    @app.middleware('http')
    async def observe_original_auth_identity(request, call_next):
        response = await call_next(request)
        if 'hermes_session_provider=android-desktop-delegation' in request.headers.get('cookie', ''):
            session = getattr(request.state, 'session', None)
            app.state.delegated_request_count += 1
            app.state.delegated_identity_preserved &= bool(session and session.user_id == 'alice' and session.provider == 'android-lab')
        return response

    policy = Policy.from_dict(json.loads(Path(args.policy).read_text()), forbidden_roots=[home, upstream])
    adapter = install(app, server, policy, spool_dir=home.parent / 'spool')
    if args.media_fixture:
        # Explicit injectable provider boundaries ONLY in this disposable lab.
        # Real original routes, config scope and bytes are still exercised.
        import tools.voice_mode
        import tools.tts_tool
        def transcribe(path):
            data = Path(path).read_bytes()
            return {'success':True,'transcript':'ქართული fixture '+str(len(data)),'provider':'injected-fixture'}
        def speak(text):
            target = home/'fixture-speech.wav'
            target.write_bytes(b'RIFF'+bytes(range(256))*300)
            return json.dumps({'success':True,'file_path':str(target),'provider':'injected-fixture'})
        tools.voice_mode.transcribe_recording=transcribe
        tools.tts_tool.text_to_speech_tool=speak
    db = SessionDB(home / 'state.db')
    db.create_session('synthetic-session', source='cli', profile_name='default', cwd=str(home.parent / 'workspace'))
    db.append_message('synthetic-session', 'user', 'Synthetic stored prompt')
    db.append_message('synthetic-session', 'assistant', 'Synthetic stored response')
    db.create_session('mixed-owned-root', source='cli', profile_name='default')
    db.create_session('mixed-foreign-child', source='tool', profile_name='work', parent_session_id='mixed-owned-root')
    db.append_message('mixed-foreign-child', 'user', 'FOREIGN_FIXTURE_ROW_NOT_AUTHORIZED')
    db.close()

    # Bind before readiness and hold the socket all the way into uvicorn. Port 0
    # selects an unused local port without a probe/rebind race.
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    if os.name == 'nt':
        listener.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
    listener.bind(('127.0.0.1', 0))
    listener.listen(128)
    port = listener.getsockname()[1]

    @asynccontextmanager
    async def lab_lifespan(_):
        Path(args.ready).write_text(json.dumps({'pid': os.getpid(), 'port': port, 'sourceCommit': revision}), encoding='utf-8')
        try:
            yield
        finally:
            await adapter.aclose()
            listener.close()

    app.router.lifespan_context = lab_lifespan

    class PublicSurface:
        async def __call__(self, scope, receive, send):
            if scope['type'] == 'http' and scope['path'] == '/health':
                raw = json.dumps({'pid': os.getpid(), 'sourceCommit': revision,
                                  'delegatedRequests': app.state.delegated_request_count,
                                  'identityPreserved': app.state.delegated_identity_preserved}).encode()
                await send({'type': 'http.response.start', 'status': 200, 'headers': [(b'content-type', b'application/json')]})
                await send({'type': 'http.response.body', 'body': raw})
                return
            if scope['type'] == 'http' and scope['path'] != '/api/auth/ws-ticket':
                await send({'type': 'http.response.start', 'status': 404, 'headers': [(b'content-type', b'application/json')]})
                await send({'type': 'http.response.body', 'body': b'{"detail":"lab route not exposed"}'})
                return
            if scope['type'] == 'websocket' and scope['path'] != '/api/ws':
                await send({'type': 'websocket.close', 'code': 4404})
                return
            await app(scope, receive, send)

    uvicorn.Server(uvicorn.Config(PublicSurface(), host='127.0.0.1', port=port,
                                 log_level='warning', access_log=False, ws_max_size=4 * 1024 * 1024,
                                 proxy_headers=False, lifespan='on')).run(sockets=[listener])


if __name__ == '__main__':
    main()
