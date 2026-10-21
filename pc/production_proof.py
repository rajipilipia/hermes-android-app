"""Hermetic pinned-source composition proof, never a production launcher.

Synthetic identity/provider seams and audited background side-effect seams only.
Normal original cmd_dashboard/start_server/Uvicorn/ASGI/lifespan/auth/ticket/WS
code executes. No actual accounts, keys, live homes or cloud STT are accessed.
"""
from __future__ import annotations
import asyncio
import hashlib
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import threading
import time
import traceback
from unittest.mock import patch
from urllib.parse import urlsplit, parse_qs, urlencode

PROJECT = Path(__file__).resolve().parents[1]
UPSTREAM = Path('C:/example/hermes-agent')


def outer():
    scratch = Path(os.environ['TMPDIR'])
    with tempfile.TemporaryDirectory(prefix='pc-production-', dir=scratch) as temporary:
        base = Path(temporary).resolve()
        env = {k: v for k, v in os.environ.items() if k.upper() in {
            'SYSTEMROOT', 'WINDIR', 'COMSPEC', 'PATH', 'PATHEXT', 'SYSTEMDRIVE',
            'NUMBER_OF_PROCESSORS', 'PROCESSOR_ARCHITECTURE'}}
        env.update(HOME=str(base), USERPROFILE=str(base), HERMES_HOME=str(base/'managed'),
                   APPDATA=str(base/'roaming'), LOCALAPPDATA=str(base/'local'),
                   TMP=str(base), TEMP=str(base), TMPDIR=str(base),
                   HERMES_DISABLE_LAZY_INSTALLS='1', PYTHONDONTWRITEBYTECODE='1',
                   PYTHONPATH=str(PROJECT), NO_PROXY='*', HERMES_GATEWAY_LOCK_DIR=str(base/'locks'))
        scenario = ('failure' if '--startup-failure' in sys.argv else
                    'cli-junction' if '--cli-junction' in sys.argv else
                    'cli-default' if '--cli-default' in sys.argv else
                    'cli-named' if '--cli-named' in sys.argv else 'normal')
        proc = subprocess.run([sys.executable, '-B', '-m', 'pc.production_proof', '--child', str(base),scenario],
                              cwd=PROJECT, env=env, capture_output=True, text=True, timeout=140)
        print(proc.stdout, end='')
        print(proc.stderr, end='', file=sys.stderr)
        raise SystemExit(proc.returncode)


def child(base,scenario='normal'):
    if (Path(os.environ['HOME']).resolve() != base or Path(os.environ['USERPROFILE']).resolve() != base
            or Path(os.environ['HERMES_HOME']).resolve() != base/'managed'
            or not base.name.startswith('pc-production-')):
        raise RuntimeError('proof requires a fresh synthetic home')
    root = base/'managed'
    primary = 'default' if scenario in ('cli-default', 'cli-junction') else 'research'
    mode = 'dashboard' if primary == 'default' else 'serve'
    home = root if primary == 'default' else root/'profiles'/primary
    workspace, spool = base/'workspace', base/'spool'
    for path in (root, home, workspace, spool, base/'locks'):
        path.mkdir(parents=True, exist_ok=True)
    junction_home = None
    if scenario == 'cli-junction':
        junction_home = base/'canonical-profiles'/'research'
        junction_home.mkdir(parents=True)
        subprocess.run(['cmd.exe', '/d', '/c', 'mklink', '/J', str(root/'profiles'),
                        str(junction_home.parent)], check=True, capture_output=True)
        (junction_home/'config.yaml').write_text('local_runtime:\n  enabled: false\n', encoding='utf-8')
    (home/'config.yaml').write_text('dashboard:\n  public_url: https://composition.invalid\nlocal_runtime:\n  enabled: false\n', encoding='utf-8')
    (root/'active_profile').write_text('ungranted-sticky-profile', encoding='utf-8')
    from .production_policy import current_owner
    value = {'schemaVersion':1, 'owner':current_owner(), 'root':str(root),
             'launchProfile':primary, 'launchHome':str(home), 'spool':str(spool),
             'principals':[{'provider':'fixture','user_id':'alice','profiles':{
                 primary:{'expectedHome':str(home),'roots':[str(workspace)],
                             'permissions':['read','files.write','audio']}}}]}
    if junction_home is not None:
        value['principals'][0]['profiles']['research'] = {
            'expectedHome': str(junction_home), 'roots': [str(workspace)],
            'permissions': ['read', 'files.write', 'audio']}
    manifest = base/'grants.json'
    manifest.write_text(json.dumps(value), encoding='utf-8')
    ports, blocked_network, blocked_processes, events = set(), [], [], []
    original_connect, original_bind, original_dns = socket.socket.connect, socket.socket.bind, socket.getaddrinfo
    def connect(sock, address):
        if not isinstance(address, tuple) or address[0] not in ('127.0.0.1','::1') or address[1] not in ports:
            blocked_network.append('connect')
            raise OSError('proof denies non-suite connection')
        return original_connect(sock,address)
    def bind(sock,address):
        if not isinstance(address,tuple) or address[0] not in ('127.0.0.1','::1') or address[1] != 0:
            raise OSError('proof denies non-loopback or fixed-port bind')
        result=original_bind(sock,address)
        ports.add(sock.getsockname()[1])
        return result
    def dns(host,port,*args,**kwargs):
        if host not in ('127.0.0.1','::1') or int(port or 0) not in ports:
            blocked_network.append('dns')
            raise OSError('proof denies external DNS')
        return original_dns(host,port,*args,**kwargs)
    socket.socket.connect, socket.socket.bind, socket.getaddrinfo = connect, bind, dns
    # Audit subprocess and private file accesses before the first runtime import.
    def audit(event,args):
        if event in ('socket.sendto','socket.sendmsg'):
            blocked_network.append('datagram')
            raise PermissionError('proof denies datagram egress')
        if event=='socket.connect':
            address=args[1]
            if not isinstance(address,tuple) or address[0] not in ('127.0.0.1','::1') or address[1] not in ports:
                blocked_network.append('socket-audit')
                raise PermissionError('proof denies non-suite socket egress')
        if event == 'subprocess.Popen':
            command=args[1]
            pieces=command if isinstance(command,(list,tuple)) else str(command).split()
            # Native Windows audit emits a commandline string. Git is allowed
            # ONLY for source fingerprints/version/status; no shell or children.
            text=' '.join(map(str,pieces))
            if 'git' not in text.lower() or not any(x in text for x in ('rev-parse','status --porcelain','log -1','diff --quiet')):
                blocked_processes.append('process')
                raise PermissionError('proof denies unapproved subprocess')
        if event == 'open' and isinstance(args[0],(str,bytes,os.PathLike)):
            path=Path(os.fsdecode(args[0])).absolute()
            if path.name in ('.env','.op.env','auth.json') and not path.is_relative_to(base):
                raise PermissionError('proof denies real credentials')
            if path.is_relative_to(Path('C:/Users/example-user')) and not path.is_relative_to(base):
                raise PermissionError('proof denies actual user data')
    sys.addaudithook(audit)
    sys.path.insert(0,str(UPSTREAM))
    # Real dotenv parser reads synthetic home only; checkout .env is excluded.
    from hermes_cli import env_loader, _early_recovery
    dotenv=env_loader.load_hermes_dotenv
    env_loader.load_hermes_dotenv=lambda *args,**kwargs: dotenv(*args,**{**kwargs,'project_env':None,'load_external_secrets':False})
    _early_recovery.recover_interrupted_update=lambda *a,**k: None
    import hermes_cli.banner
    hermes_cli.banner.prefetch_update_check=lambda: events.append('passive-update-withheld')
    from hermes_cli.dashboard_auth import DashboardAuthProvider, Session, register_provider
    from hermes_cli.dashboard_auth.base import LoginStart, InvalidCodeError, RefreshExpiredError
    class FixtureProvider(DashboardAuthProvider):
        name, display_name='fixture','SYNTHETIC proof provider'
        def start_login(self,*,redirect_uri):
            return LoginStart('/synthetic-idp',{'hermes_session_pkce':'state=synthetic-csrf;verifier=synthetic-upstream-verifier'})
        def complete_login(self,**kwargs):
            if kwargs['code']!='synthetic-code':
                raise InvalidCodeError('fixture rejected')
            return self.session('alice')
        def session(self,user):
            return Session(user,'','Synthetic','','fixture',int(time.time())+3600,'synthetic-'+user,'synthetic-refresh')
        def verify_session(self,*,access_token):
            if access_token in ('synthetic-alice','synthetic-mallory'):
                return self.session(access_token.removeprefix('synthetic-'))
            return None
        def refresh_session(self,**kwargs):
            raise RefreshExpiredError('fixture has no refresh')
        def revoke_session(self,**kwargs):
            return None
    fixture=FixtureProvider()
    from hermes_cli import plugins
    plugins.discover_plugins=lambda *a,**k: register_provider(fixture)
    # Patch only effect boundaries AFTER original main import. This retains
    # actual profile override, routing functions, prep, server builder/lifespan.
    import importlib
    original_import=importlib.import_module
    capture={}
    def module_import(name,*args,**kwargs):
        module=original_import(name,*args,**kwargs)
        if name=='hermes_cli.main':
            module._sync_bundled_skills_quietly=lambda: events.append('skills-seed-withheld')
            from hermes_state import SessionDB
            db = SessionDB(home/'state.db')
            try:
                db.create_session('synthetic-p0-session', source='cli', profile_name=primary,
                                  cwd=str(workspace))
                db.append_message('synthetic-p0-session', 'user', 'SYNTHETIC P0 stored prompt')
                db.append_message('synthetic-p0-session', 'assistant', 'SYNTHETIC P0 stored response')
            finally:
                db.close()
            if junction_home is not None:
                db = SessionDB(junction_home/'state.db')
                try:
                    db.create_session('synthetic-junction-session', source='cli', profile_name='research',
                                      cwd=str(workspace))
                    db.append_message('synthetic-junction-session', 'assistant', 'SYNTHETIC junction response')
                finally:
                    db.close()
            # Any erroneous attach/reexec would hit blocked network/processes.
        if name=='hermes_cli.web_server':
            capture['web']=module
            capture['original_lifespan']=module.app.router.lifespan_context
            module._warm_gateway_module=lambda: events.append('gateway-warmup-withheld')
            capture['original_started'] = module._on_server_started
            module._on_server_started=started
            if scenario=='failure':
                def builder_failure(*args,**kwargs):
                    raise RuntimeError('synthetic builder failure')
                module._build_uvicorn_server=builder_failure
            from hermes_cli import free_tier_bootstrap
            free_tier_bootstrap.start_background_bootstrap=lambda: events.append('free-tier-withheld')
            from hermes_cli import nous_auth_keepalive
            nous_auth_keepalive.start_nous_auth_keepalive=lambda: events.append('keepalive-withheld')
        return module
    checks=[]
    def check(value,label):
        if not value:
            raise AssertionError(label)
        checks.append(label)
    client_done=threading.Event()
    client_error=[]
    def started(server,**kwargs):
        capture['uvicorn']=server
        capture['port']=server.servers[0].sockets[0].getsockname()[1]
        if scenario.startswith('cli-'):
            capture['original_started'](server, **kwargs)
            from gateway import host_rendezvous as hr
            record = hr.read_record(hr.ROLE_SERVE)
            check(record is not None and record.pid == os.getpid()
                  and record.port == capture['port'], 'original isolated startup publishes synthetic host rendezvous')
            check(kwargs['isolated'] is True, 'original isolated startup retained')
            check(capture['web'].app.state.serves_spa == (mode == 'dashboard'),
                  'original dashboard versus headless lifecycle retained')
            from hermes_cli import process_identity
            entries = process_identity.ledger_entries(verified_only=True)
            check(any(entry['pid'] == os.getpid() and entry.get('isolated') is True
                      for entry in entries), 'original startup registers synthetic process ownership')
        web=capture['web']
        check(web.app.state.auth_required,'original gate required')
        check(hasattr(web.app.state,'event_lock'),'original lifespan initialized locks')
        check(web.app.router.lifespan_context is not capture['original_lifespan'],'lifespan wrapped, not removed')
        def client():
            try:
                if scenario == 'cli-junction':
                    exercise(capture['port'],check,home,root,manifest,primary,extra_profile='research')
                elif scenario.startswith('cli-'):
                    exercise(capture['port'],check,home,root,manifest,primary)
                else:
                    # Preserve the existing reusable dictation-proof seam.
                    exercise(capture['port'],check,home,root,manifest)
            except BaseException:
                client_error.append(traceback.format_exc())
            finally:
                server.should_exit=True
                client_done.set()
        threading.Thread(target=client,name='production-proof-client',daemon=True).start()
    from . import addon, production_bootstrap
    original_install=addon.install
    original_bootstrap_install=production_bootstrap.install
    def install(*args,**kwargs):
        capture['adapter']=original_install(*args,**kwargs)
        return capture['adapter']
    def install_bootstrap(adapter):
        capture['bootstrap']=original_bootstrap_install(adapter)
        capture['bootstrap_handler']=adapter.server._methods['desktop.bootstrap']
        return capture['bootstrap']
    with patch('importlib.import_module',module_import), patch.object(addon,'install',install), \
            patch.object(production_bootstrap,'install',install_bootstrap):
        if scenario.startswith('cli-'):
            from .production_composition import run
        else:
            # The existing dictation proof injects its explicit trusted factory
            # at this public entry. CLI mode must not preload the runpy module.
            from .production_runtime import run
        if scenario=='failure':
            try:
                run(upstream=UPSTREAM,manifest=manifest,mode='serve',host='127.0.0.1',port=0,isolated=True)
            except RuntimeError as exc:
                check(str(exc)=='synthetic builder failure','original builder failure propagated')
            else:
                raise AssertionError('synthetic builder failure was swallowed')
            adapter=capture['adapter']
            check(adapter._closed,'failure adapter cleanup')
            from tui_gateway.contracts.registry import METHODS
            check('desktop.bootstrap' not in adapter.server._methods and 'desktop.bootstrap' not in METHODS,
                  'failure bootstrap registration cleanup')
            check(capture['bootstrap'].adapter is None, 'failure bootstrap adapter closure released')
            check(capture['bootstrap_handler'](0,{})['result']['status']==410, 'failure retained bootstrap handler revoked')
            check(capture['web'].app.router.lifespan_context is capture['original_lifespan'],
                  'failure original lifespan restored')
            check(not adapter.downloads._thread.is_alive(),'failure download reaper joined')
            check(not adapter.uploads._thread.is_alive(),'failure upload reaper joined')
            check('uvicorn' not in capture,'no failure listener started')
            from .production_composition import runtime_lock
            with runtime_lock(adapter.policy):
                check(True,'failure runtime lock released')
            print(json.dumps({'checks':len(checks),'failureCleanup':True,'synthetic':True}))
            return
        if scenario.startswith('cli-'):
            # Exercise the actual production module CLI, including argparse.
            # The adapter must not inherit the test runner's lazy-install guard
            # by accident: original prepare_launch is allowed to decide here.
            os.environ.pop('HERMES_DISABLE_LAZY_INSTALLS', None)
            import runpy
            sys.argv = ['pc.production_runtime', '--upstream', str(UPSTREAM), '--manifest', str(manifest),
                        '--mode', mode, '--host', '127.0.0.1', '--port', '0', '--isolated', '--skip-build']
            runpy.run_module('pc.production_runtime', run_name='__main__', alter_sys=True)
            from types import SimpleNamespace
            composition = SimpleNamespace(adapter=capture['adapter'], bootstrap=capture['bootstrap'])
            check(os.environ.get('HERMES_DISABLE_LAZY_INSTALLS') == '1', 'adapter prevents managed provisioning and hook-losing reexec')
        else:
            composition=run(upstream=UPSTREAM,manifest=manifest,mode='serve',host='127.0.0.1',port=0,isolated=True)
    if not client_done.wait(1) or client_error:
        raise AssertionError('\n'.join(client_error) or 'client did not finish')
    check(composition.adapter._closed,'adapter cleanup')
    from tui_gateway.contracts.registry import METHODS
    check('desktop.bootstrap' not in composition.adapter.server._methods and 'desktop.bootstrap' not in METHODS,
          'bootstrap registration cleanup')
    check(composition.bootstrap.adapter is None, 'bootstrap adapter closure released')
    check(capture['bootstrap_handler'](0,{})['result']['status']==410, 'retained bootstrap handler revoked')
    check(capture['web'].app.router.lifespan_context is capture['original_lifespan'], 'original lifespan restored')
    check(not composition.adapter.downloads._thread.is_alive(),'download reaper joined')
    check(not composition.adapter.uploads._thread.is_alive(),'upload reaper joined')
    check(not any(t.name=='statedb-eager-reconcile' and t.is_alive() for t in threading.enumerate()),'normal DB worker joined')
    check(not capture['uvicorn'].servers[0].is_serving(),'listener closed')
    # Actual OS rebind (the proof guard permits only ephemeral binds normally).
    with socket.socket() as probe:
        original_bind(probe,('127.0.0.1',capture['port']))
    check((home/'state.db').is_file(),'normal eager DB worker materialized selected home')
    check((root/'active_profile').read_text()=='ungranted-sticky-profile','original explicit -p ignored sticky without mutating it')
    from hermes_cli.dashboard_auth.registry import get_provider
    check(get_provider('android-desktop-delegation') is None,'delegation provider cleanup')
    from .production_composition import runtime_lock
    from .production_policy import BoundPolicy
    # The deliberate manifest mutation above permanently revokes the old
    # fingerprint, even after bytes are restored. A fresh host-owned launch must
    # reload it; never weaken the old immutable policy just to check the lock.
    with runtime_lock(BoundPolicy.load(manifest, forbidden_roots=[UPSTREAM])):
        check(True, 'normal runtime lock released')
    print(json.dumps({'checks':len(checks),'assertions':checks,'normalLifespan':True,'listenerReleased':True,
                      'blockedNetworkAttempts':len(blocked_network),'blockedProcessAttempts':len(blocked_processes),
                      'events':events,'synthetic':True,'liveSttAcceptance':False,
                      'entry': 'pc.production_runtime CLI' if scenario.startswith('cli-') else 'run',
                      'primaryProfile':primary,'mode':mode,'identityProvider':'SYNTHETIC fixture',
                      'port':capture['port']}))


def bootstrap_primary(rpc, check):
    """Discover the same authenticated closed DTO used by a cold Android host."""
    from .catalog import SOURCE_COMMIT
    from .identifiers import canonical_profile
    result = rpc('desktop.bootstrap', {})
    body = result.get('body')
    valid = (type(result.get('status')) is int and result['status'] == 200
             and isinstance(body, dict) and set(body) == {'schemaVersion', 'sourceCommit', 'primaryProfile'}
             and type(body['schemaVersion']) is int and body['schemaVersion'] == 1
             and body['sourceCommit'] == SOURCE_COMMIT)
    if valid:
        try:
            canonical_profile(body['primaryProfile'])
        except ValueError:
            valid = False
    check(valid, 'authenticated closed desktop bootstrap metadata')
    return body['primaryProfile']


def exercise(port,check,home,root,manifest,expected_primary='research',extra_profile=None):
    import httpx
    import websockets.sync.client
    url='http://127.0.0.1:'+str(port)
    with httpx.Client(base_url=url,trust_env=False,timeout=20,follow_redirects=False) as client:
        health = client.get('/api/health')
        check(health.status_code == 200 and health.json()['ok'] is True
              and health.json()['auth_required'] is True,
              'original public health route retains authenticated runtime liveness')
        adapter_health = health.json().get('androidAdapter', {})
        check(adapter_health.get('ready') is True
              and set(adapter_health) == {'schemaVersion', 'sourceCommit', 'generation', 'sourceDigest', 'ready'},
              'public health proves live adapter registration without credentials or profile data')
        check(client.post('/api/auth/ws-ticket').status_code==401,'unauthenticated ticket denied')
        check(client.post('/api/auth/ws-ticket',headers={'Authorization':'Bearer invalid'}).status_code==401,'invalid bearer denied')
        verifier='s'*43
        challenge=__import__('base64').urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b'=').decode()
        response=client.get('/auth/native/authorize',params={'provider':'fixture','code_challenge':challenge,
                         'code_challenge_method':'S256','redirect_uri':'http://127.0.0.1:23456/callback','state':'native-state'})
        check(response.status_code==302,'original native authorize')
        response=client.get('/auth/callback',params={'code':'synthetic-code','state':'synthetic-csrf'})
        check(response.status_code==302,'original native callback '+str(response.status_code)+' '+response.text[:500])
        code=parse_qs(urlsplit(response.headers['location']).query)['code'][0]
        token=client.post('/auth/native/token',json={'code':code,'code_verifier':verifier})
        check(token.status_code==200,'same-process native code redemption')
        check(client.post('/auth/native/token',json={'code':code,'code_verifier':verifier}).status_code==400,'native code replay denied')
        auth={'Authorization':'Bearer '+token.json()['access_token']}
        check(client.get('/api/auth/me',headers=auth).json()['user_id']=='alice','original authenticated metadata')
        def ticket(headers=auth):
            response=client.post('/api/auth/ws-ticket',headers=headers)
            check(response.status_code==200,'original verified ticket mint')
            return response.json()['ticket']
        one=ticket()
        origin_ticket=ticket()
        try:
            with websockets.sync.client.connect('ws://127.0.0.1:'+str(port)+'/api/ws?ticket='+origin_ticket,
                                                origin='https://foreign.invalid',open_timeout=5) as rejected:
                rejected.recv(timeout=5)
        except Exception:
            check(True,'original foreign Origin denied')
        else:
            raise AssertionError('foreign Origin admitted')
        socket_url='ws://127.0.0.1:'+str(port)+'/api/ws?ticket='+one
        with websockets.sync.client.connect(socket_url,open_timeout=10) as ws:
            sequence=0
            def rpc(method,params):
                nonlocal sequence
                sequence+=1
                ws.send(json.dumps({'jsonrpc':'2.0','id':sequence,'method':method,'params':params}))
                while True:
                    reply=json.loads(ws.recv(timeout=20))
                    if reply.get('id')==sequence:
                        check('result' in reply,'registered '+method)
                        return reply['result']
            primary = bootstrap_primary(rpc, check)
            check(primary == expected_primary, 'host-owned launch profile discovered without caller selector')
            params={'operation':'GET /api/profiles/active','profile':primary}
            result=rpc('desktop.call',params)
            check(result['status']==200 and result['body']['active']==primary,'desktop.call original profile service')
            messages = rpc('desktop.call', {'operation':'GET /api/sessions/{session_id}/messages',
                            'profile':primary, 'pathParams':{'session_id':'synthetic-p0-session'},
                            'query':{'limit':10}})
            check(messages['status'] == 200 and
                  messages['body']['messages'][-1]['content'] == 'SYNTHETIC P0 stored response',
                  'desktop.call reaches original exact-owner stored session service')
            profiles = rpc('desktop.call', {'operation': 'GET /api/profiles', 'profile': primary})
            expected_profiles = {primary} if extra_profile is None else {primary, extra_profile}
            profile_names = [row['name'] for row in profiles['body']['profiles']]
            exact_profiles = (profile_names == [primary] if extra_profile is None else
                              len(profile_names) == len(expected_profiles) and set(profile_names) == expected_profiles)
            check(profiles['status']==200 and exact_profiles,
                  'cold profile discovery uses only bootstrap owner')
            cwd = rpc('desktop.call', {'operation': 'GET /api/fs/default-cwd', 'profile': primary})
            check(cwd['status']==200, 'cold default cwd uses bootstrap owner')
            if extra_profile is not None:
                named = rpc('desktop.call', {'operation': 'GET /api/profiles/active', 'profile': extra_profile})
                check(named['status']==200 and named['body']['active']==extra_profile,
                      'junction profile keeps explicit owner with default launch unchanged')
                named = rpc('desktop.call', {'operation': 'GET /api/sessions/{session_id}/messages',
                    'profile': extra_profile, 'pathParams': {'session_id': 'synthetic-junction-session'},
                    'query': {'limit': 1}})
                check(named['status']==200 and named['body']['profile']==extra_profile and
                      named['body']['messages'][-1]['content']=='SYNTHETIC junction response',
                      'authenticated original session service reads exact canonical junction home')
                foreign = rpc('desktop.call', {'operation': 'GET /api/sessions/{session_id}/messages',
                    'profile': extra_profile, 'pathParams': {'session_id': 'synthetic-p0-session'}})
                check(foreign['status']==404, 'junction profile never falls back to default session store')
            denied_profile = 'ungranted' if extra_profile is not None else ('research' if primary == 'default' else 'default')
            check(rpc('desktop.call',{**params,'profile':denied_profile})['status']==403,'ungranted profile denied')
            from tui_gateway import server as original_server
            previous=original_server._profile_home
            original_server._profile_home=lambda name: home/'wrong-home'
            try:
                check(rpc('desktop.call',params)['status']==403,'actual runtime selected home mismatch denied')
                check(rpc('desktop.bootstrap',{})['status']==403,'bootstrap rechecks actual runtime home')
            finally:
                original_server._profile_home=previous
            check(rpc('desktop.call',params)['status']==200,'exact selected home restored')
            check(rpc('desktop.call',{'operation':'POST /api/audio/transcribe','profile':primary,
                  'body':{'data_url':'data:audio/wav;base64,UklGRg==','mime_type':'audio/wav'}})['status']==403,'Whisper fallback blocked')
            check(rpc('desktop.audio.config',{'profile':primary})['status']==403,'no fake STT ready config')
            check(rpc('desktop.upload.begin',{'profile':primary,'purpose':'transcribe','filename':'voice.wav',
                  'mimeType':'audio/wav','byteSize':4})['status']==403,'STT upload denied before spool reservation')
            # Alter only synthetic manifest: immutable-policy recheck must deny.
            original=manifest.read_bytes()
            manifest.write_bytes(original+b' ')
            check(rpc('desktop.call',params)['status']==403,'changed grant file denied at admission')
            check(rpc('desktop.bootstrap',{})['status']==403,'bootstrap rechecks changed grant file')
            manifest.write_bytes(original)
        try:
            with websockets.sync.client.connect(socket_url,open_timeout=5) as replay:
                replay.recv(timeout=5)
        except Exception:
            check(True,'one-use ticket replay denied')
        else:
            raise AssertionError('replayed ticket admitted')
        bad=ticket({'Authorization':'Bearer synthetic-mallory'})
        with websockets.sync.client.connect('ws://127.0.0.1:'+str(port)+'/api/ws?ticket='+bad) as ws:
            check(rpc('desktop.bootstrap', {})['status']==403, 'unknown authenticated bootstrap principal denied')
            check(rpc('desktop.call', params)['status']==403, 'unknown authenticated principal denied')
        # Diagnostic idle alone is not permission to stop a generation. Exercise
        # the original authenticated admission-freezing prepare/cancel API too.
        idle = client.get('/api/health/idle', headers=auth)
        check(idle.status_code == 200 and idle.json()['idle'] is True,
              'original authenticated dashboard idle ledger is determinate')
        permit = client.post('/api/health/retirement', headers=auth, json={'action':'prepare'})
        check(permit.status_code == 200 and permit.json()['ok'] is True,
              'original authenticated retirement prepare freezes admission')
        cancelled = client.post('/api/health/retirement', headers=auth,
                                json={'action':'cancel', 'token':permit.json()['token']})
        check(cancelled.status_code == 200 and cancelled.json()['ok'] is True,
              'original authenticated retirement cancel restores admission')


if __name__=='__main__':
    if sys.argv[1:2]==['--child']:
        child(Path(sys.argv[2]).resolve(),sys.argv[3] if len(sys.argv)>3 else 'normal')
    else:
        outer()
