"""Reproducible isolated TCP/WebSocket proof; no active profile or real credentials.

Run with the upstream interpreter: python -m pc.prove --upstream C:/example/hermes-agent
All generated state/logs stay in .cache/pc-lab/. Each subprocess gets a scrubbed
OS-only environment, a fresh HERMES_HOME, and a free exclusive loopback listener.
"""
from __future__ import annotations
import argparse
import base64
import hashlib
import json
import os
from pathlib import Path
import secrets
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
import uuid

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--upstream', required=True)
    parser.add_argument('--media', action='store_true', help='inject synthetic provider boundaries; never a model pass')
    args = parser.parse_args()
    from websockets.sync.client import connect
    from pc.catalog import SOURCE_COMMIT

    lab = ROOT / '.cache' / 'pc-lab' / ('run-' + uuid.uuid4().hex[:12])
    home, workspace, scratch = lab / 'home', lab / 'workspace', lab / 'scratch'
    for directory in (home, workspace, scratch):
        directory.mkdir(parents=True)
    bearer = secrets.token_urlsafe(32)
    (lab / 'token').write_text(bearer, encoding='utf-8')
    # A sentinel is deliberately unlike a real provider key. Never clone a PC
    # config, .env, auth pool, account, or session into this lab.
    (home / 'config.yaml').write_text('model:\n  default: synthetic-model\n  api_key: SYNTHETIC_NEVER_EXPOSE_THIS\ndisplay:\n  skin: default\n  language: en\nauxiliary:\n  vision:\n    provider: auto\n    model: fixture-vision\n    base_url: https://example.invalid/v1?access_token=OPAQUE_FIXTURE_ENDPOINT\nstt:\n  enabled: false\n', encoding='utf-8')
    (workspace / 'readme.txt').write_text('isolated desktop capability proof\n', encoding='utf-8')
    (workspace / '.env').write_text('SYNTHETIC_DENIED_FILE=sentinel\n', encoding='utf-8')
    binary = bytes(range(256)) * 1024
    (workspace / 'artifact.bin').write_bytes(binary)
    policy = {'principals': [{'provider': 'android-lab', 'user_id': 'alice', 'profiles': {
        'default': {'roots': [str(workspace)], 'permissions': ['read', 'files.write', 'settings.write', 'sessions.write', 'skills.write', 'audio']}}}]}
    (lab / 'policy.json').write_text(json.dumps(policy), encoding='utf-8')
    keep = {'PATH', 'SYSTEMROOT', 'WINDIR', 'COMSPEC', 'PATHEXT', 'PROCESSOR_ARCHITECTURE', 'NUMBER_OF_PROCESSORS',
            'SYSTEMDRIVE', 'PROGRAMFILES', 'PROGRAMFILES(X86)', 'PROGRAMDATA'}
    env = {k: v for k, v in os.environ.items() if k.upper() in keep}
    env.update(HERMES_HOME=str(home), HOME=str(home), USERPROFILE=str(home),
               APPDATA=str(home / 'AppData/Roaming'), LOCALAPPDATA=str(home / 'AppData/Local'),
               TMPDIR=str(scratch), TEMP=str(scratch), TMP=str(scratch), PYTHONPATH=str(ROOT),
               PYTHONDONTWRITEBYTECODE='1', HERMES_TEST_ISOLATION='1', HERMES_DISABLE_LAZY_INSTALLS='1')
    ready = lab / 'ready.json'
    command = [sys.executable, '-u', '-m', 'pc.lab_runtime', '--upstream', str(Path(args.upstream).resolve()),
               '--home', str(home), '--policy', str(lab / 'policy.json'), '--token-file', str(lab / 'token'),
               '--ready', str(ready)]
    if args.media:
        command.append('--media-fixture')
    checks, port, proc, runtime_pid = [], None, None, None
    owned_children = []
    import psutil
    error = None
    with (lab / 'runtime.log').open('w', encoding='utf-8') as log:
        try:
            proc = subprocess.Popen(command, env=env, cwd=ROOT, stdout=log, stderr=subprocess.STDOUT)
            deadline = time.monotonic() + 100
            while not ready.exists():
                if proc.poll() is not None:
                    raise AssertionError(f'isolated runtime exited {proc.returncode}; inspect {lab / "runtime.log"}')
                if time.monotonic() > deadline:
                    raise AssertionError('isolated runtime readiness timed out')
                time.sleep(0.1)
            info = json.loads(ready.read_text())
            owned_children = psutil.Process(proc.pid).children(recursive=True)
            runtime_pid, port = info['pid'], info['port']
            assert runtime_pid in {proc.pid, *(p.pid for p in owned_children)}, 'readiness PID not in owned process tree'
            assert info['sourceCommit'] == SOURCE_COMMIT
            base = f'http://127.0.0.1:{port}'

            def http(path, method='GET', body=None, auth=True):
                req = urllib.request.Request(base + path, method=method, data=None if body is None else json.dumps(body).encode(),
                                             headers={'Content-Type': 'application/json', **({'Authorization': f'Bearer {bearer}'} if auth else {})})
                try:
                    with urllib.request.urlopen(req, timeout=15) as response:
                        return response.status, json.load(response)
                except urllib.error.HTTPError as exc:
                    return exc.code, json.load(exc)

            # Readiness must come from this exact new process, not any existing
            # listener. The server bound port 0 and passed its own socket to uvicorn.
            for _ in range(100):
                try:
                    code, health = http('/health', auth=False)
                    if code == 200:
                        break
                except (OSError, urllib.error.URLError):
                    time.sleep(0.05)
            assert health['pid'] == runtime_pid
            checks.append('new-process-loopback-readiness')
            assert http('/api/auth/ws-ticket', 'POST', {}, auth=False)[0] == 401
            checks.append('original-auth-rejects-missing-bearer')
            status, ticket = http('/api/auth/ws-ticket', 'POST', {})
            assert status == 200, ticket
            protocols = ['hermes-gateway-v1', 'hermes-gateway-ticket.' + ticket['ticket']]
            with connect(f'ws://127.0.0.1:{port}/api/ws', subprotocols=protocols,
                         origin=f'http://127.0.0.1:{port}', max_size=8 * 1024 * 1024, open_timeout=20) as ws:
                frame = json.loads(ws.recv(timeout=30))
                assert frame['params']['type'] == 'gateway.ready', frame
                assert ws.subprotocol == 'hermes-gateway-v1'
                checks.append('single-use-ticket-authenticated-gateway-ready')
                sequence = 0

                def rpc(method, params, *, expect_error=False):
                    nonlocal sequence
                    sequence += 1
                    ws.send(json.dumps({'jsonrpc': '2.0', 'id': sequence, 'method': method, 'params': params}))
                    while True:
                        message = json.loads(ws.recv(timeout=35))
                        if message.get('id') == sequence:
                            if expect_error:
                                assert 'error' in message, message
                                return message['error']
                            assert 'error' not in message, message
                            return message['result']

                def call(operation, **params):
                    return rpc('desktop.call', {'operation': operation, 'profile': 'default', **params})

                if args.media:
                    config = rpc('desktop.audio.config', {'profile':'default'})
                    assert config == {'status':200,'body':{'ok':True,'stt':{'mode':'relay','streaming':False},'tts':{'mode':'relay','streaming':False}}}, config
                    checks.append('credential-free-relay-only-config')
                    def upload(purpose,data,**fields):
                        begun=rpc('desktop.upload.begin',{'profile':'default','purpose':purpose,
                            'filename':fields.pop('filename','recording.wav'),'mimeType':fields.pop('mimeType','audio/wav'),
                            'byteSize':len(data),**fields})
                        assert begun['status']==200,begun
                        handle=begun['body']['uploadId']
                        for seq,offset in enumerate(range(0,len(data),65536)):
                            result=rpc('desktop.upload.append',{'profile':'default','uploadId':handle,'offset':offset,
                                'sequence':seq,'dataBase64':base64.b64encode(data[offset:offset+65536]).decode()})
                            assert result['status']==200,result
                        return handle
                    raw=bytes(range(256))*1300
                    handle=upload('workspace',raw,filename='ქართული upload.bin',mimeType='application/octet-stream',
                        path='ქართული upload.bin',overwrite=False)
                    result=rpc('desktop.upload.complete',{'profile':'default','uploadId':handle})
                    assert result['status']==200,result
                    assert (workspace/'ქართული upload.bin').read_bytes()==raw
                    assert rpc('desktop.upload.complete',{'profile':'default','uploadId':handle})['status']==404
                    checks.append('real-ws-multipart-original-file-upload-byte-readback-no-retry')
                    handle=upload('transcribe',raw)
                    result=rpc('desktop.upload.complete',{'profile':'default','uploadId':handle})
                    assert result=={'status':200,'body':{'ok':True,'transcript':'ქართული fixture '+str(len(raw)),'provider':'injected-fixture'}},result
                    checks.append('real-ws-original-stt-injected-provider-exact-bytes-dto')
                    result=call('POST /api/audio/speak',body={'text':'synthetic fixed audio'})
                    assert result['status']==200,result
                    descriptor=result['body']; output=bytearray()
                    while len(output)<descriptor['byteSize']:
                        part=rpc('desktop.download.read',{'profile':'default','downloadId':descriptor['downloadId'],
                            'offset':len(output),'length':65536})
                        assert part['status']==200,part
                        output.extend(base64.b64decode(part['body']['dataBase64']))
                    assert bytes(output)==b'RIFF'+bytes(range(256))*300
                    assert rpc('desktop.download.release',{'profile':'default','downloadId':descriptor['downloadId']})['status']==200
                    checks.append('real-ws-original-tts-injected-provider-bounded-download-bytes')
                    created=rpc('session.create',{'profile':'default','cwd':str(workspace)})
                    live,stored=created['session_id'],created['stored_session_id']
                    handle=upload('file.attach',b'actual attachment bytes',filename='ქართული note.txt',mimeType='text/plain',
                        sessionId=live,storedSessionId=stored)
                    attached=rpc('desktop.upload.complete',{'profile':'default','uploadId':handle})
                    assert attached['status']==200,attached
                    assert Path(attached['body']['path']).read_bytes()==b'actual attachment bytes'
                    assert attached['body']['ref_text'].startswith('@file:')
                    assert Path(attached['body']['path']).is_relative_to(home/'attachments')
                    checks.append('real-ws-live-draft-owned-attachment-original-staging-ref-byte-readback')
                    for profile in ('current','all','Default',' x','a'*65,'root'):
                        rejected=rpc('desktop.audio.config',{'profile':profile})
                        assert rejected['status']==(413 if len(profile)>64 else 400),rejected
                    assert rpc('desktop.upload.begin',{'profile':'default','purpose':'transcribe','filename':'x.wav',
                        'mimeType':'audio/wav','byteSize':3,'headers':{}},expect_error=True)['code']==4000
                    for kind in ('stt','tts'):
                        assert call('POST /api/audio/'+kind+'-lease',body={'lease':'voice-input','active':True})['status']==403
                    checks.append('new-rpc-canonical-profile-unknown-fields-and-engine-lease-denials')

                profiles = call('GET /api/profiles')
                assert profiles['status'] == 200, profiles
                assert [p['name'] for p in profiles['body']['profiles']] == ['default'], profiles
                checks.append('registered-rpc-original-profile-service-response')
                saved = call('POST /api/fs/write-text', body={'path': 'roundtrip.txt', 'content': 'Android → PC round trip ✓'})
                assert saved['status'] == 200, saved
                read = call('GET /api/fs/read-text', query={'path': 'roundtrip.txt'})
                assert read['status'] == 200 and read['body']['text'] == 'Android → PC round trip ✓', read
                checks.append('original-file-write-read-roundtrip')
                missing = call('GET /api/fs/read-text', query={'path': 'missing.txt'})
                assert missing['status'] == 404, missing
                checks.append('upstream-service-status-preserved')
                for path in ('../outside', '%2e%2e/auth.json', 'https://evil.invalid/a', '.env', str(home / 'config.yaml')):
                    result = call('GET /api/fs/read-text', query={'path': path})
                    assert result['status'] in (400, 403), result
                checks.append('workspace-url-traversal-encoded-secret-file-denials')
                for operation in ('GET /api/audio/voice-config', 'POST /api/env/reveal', 'GET https://evil.invalid/api/profiles'):
                    assert call(operation)['status'] == 404
                checks.append('raw-voice-env-generic-proxy-denials')
                assert rpc('desktop.call', {'operation': 'GET /api/profiles', 'profile': 'default', 'headers': {'Authorization': 'attacker'}}, expect_error=True)['code'] == 4000
                assert rpc('desktop.call', {'operation': 'GET /api/profiles', 'profile': 'other'})['status'] == 403
                checks.append('caller-header-and-cross-profile-denials')
                settings = call('GET /api/config')
                assert settings['status'] == 200 and 'model' not in settings['body'], settings
                assert 'SYNTHETIC_NEVER_EXPOSE_THIS' not in json.dumps(settings), settings
                assert call('GET /api/config', query={'include_defaults': True})['status'] == 403
                changed = call('PUT /api/config', body={'config': {'display': {'language': 'ka'}}})
                assert changed['status'] == 200, changed
                assert call('GET /api/config')['body']['display']['language'] == 'ka'
                checks.append('raw-settings-projection-save-readback-no-effective-key')
                page = call('GET /api/sessions/{session_id}/messages', pathParams={'session_id': 'synthetic-session'}, query={'limit': 10})
                assert page['status'] == 200, page
                assert page['body']['messages'][-1]['content'] == 'Synthetic stored response', page
                patch = call('PATCH /api/sessions/{session_id}', pathParams={'session_id': 'synthetic-session'}, body={'title': 'Owner-scoped changed title'})
                assert patch['status'] == 200, patch
                detail = call('GET /api/sessions/{session_id}', pathParams={'session_id': 'synthetic-session'})
                assert detail['status'] == 200 and 'Owner-scoped changed title' in json.dumps(detail), detail
                assert call('GET /api/sessions/{session_id}', pathParams={'session_id': 'synthetic'})['status'] == 404
                checks.append('stored-session-page-mutation-exact-id-owner-readback')
                for operation in ('GET /api/sessions/{session_id}', 'GET /api/sessions/{session_id}/messages'):
                    assert call(operation, pathParams={'session_id': 'mixed-owned-root'})['status'] == 403
                assert call('PATCH /api/sessions/{session_id}', pathParams={'session_id': 'mixed-owned-root'}, body={'archived': True})['status'] == 403
                listed = call('GET /api/sessions')
                assert listed['status'] == 200, listed
                assert [row['id'] for row in listed['body']['sessions']] == ['synthetic-session'], listed
                assert listed['body']['total'] == 1, listed
                assert call('GET /api/fs/download', query={'path': 'artifact.bin', 'session_id': 'synthetic-session'})['status'] == 403
                checks.append('mixed-owner-lineage-descendant-and-unsafe-forwarding-refused')
                for operation, field in (('GET /api/status', 'version'),
                                         ('GET /api/profiles/active', 'active'),
                                         ('GET /api/config/defaults', 'display'),
                                         ('GET /api/config/schema', 'fields'),
                                         ('GET /api/env', 'OPENAI_API_KEY'),
                                         ('GET /api/fs/default-cwd', 'cwd')):
                    response = call(operation)
                    assert response['status'] == 200 and field in response['body'], response
                    assert 'SYNTHETIC_NEVER_EXPOSE_THIS' not in json.dumps(response), response
                assert call('GET /api/profiles/active')['body'] == {'active': 'default', 'current': 'default'}
                assert call('GET /api/fs/default-cwd')['body']['cwd'] == str(workspace.resolve())
                checks.append('six-startup-reads-original-auth-asgi-closed-owner-dtos')
                sidebar = call('GET /api/profiles/sessions/sidebar', query={'recents_profile': 'all', 'recents_exclude': 'cron'})
                assert sidebar['status'] == 200, sidebar
                assert [row['id'] for row in sidebar['body']['recents']['sessions']] == ['synthetic-session'], sidebar
                assert set(sidebar['body']['recents']['profiles_usage']) == {'default'}, sidebar
                aggregate = call('GET /api/profiles/sessions', query={'profile': 'all', 'limit': 200, 'offset': 0, 'min_messages': 1})
                assert aggregate['status'] == 200 and aggregate['body']['total'] == 1, aggregate
                assert aggregate['body']['profile_totals'] == {'default': 1}, aggregate
                assert call('GET /api/profiles/sessions', query={'profile': 'work'})['status'] == 403
                checks.append('scoped-sidebar-and-desktop-200-page-exclude-mixed-components')
                search = call('GET /api/sessions/search', query={'q': 'stored', 'limit': 20})
                assert search['status'] == 200 and search['body']['results'][0]['id'] == 'synthetic-session', search
                assert call('GET /api/sessions/search', query={'q': 'FOREIGN_FIXTURE'})['body']['results'] == []
                checks.append('original-search-owned-positive-foreign-negative')
                timeline = call('GET /api/sessions/{session_id}/timeline', pathParams={'session_id': 'synthetic-session'})
                assert timeline['status'] == 200 and timeline['body']['entries'], timeline
                around = call('GET /api/sessions/{session_id}/messages/around', pathParams={'session_id': 'synthetic-session'},
                              query={'row_id': timeline['body']['entries'][0]['row_id'], 'limit': 2})
                assert around['status'] == 200 and len(around['body']['messages']) == 2, around
                assert call('GET /api/sessions/{session_id}/timeline', pathParams={'session_id': 'mixed-owned-root'})['status'] == 403
                assert call('GET /api/sessions/{session_id}/timeline', pathParams={'session_id': 'synthetic'})['status'] == 404
                checks.append('original-timeline-around-positive-exact-and-mixed-denials')
                auxiliary = call('GET /api/model/auxiliary')
                assert auxiliary['status'] == 200 and isinstance(auxiliary['body'].get('tasks'), list), auxiliary
                assert any(row.get('model') == 'fixture-vision' for row in auxiliary['body']['tasks']), auxiliary
                assert 'OPAQUE_FIXTURE_ENDPOINT' not in json.dumps(auxiliary) and 'base_url' not in json.dumps(auxiliary), auxiliary
                checks.append('original-auxiliary-model-service-closed-secret-free-dto')
                assert call('DELETE /api/learning/node', body={'id': '../../escaped'})['status'] == 400
                assert call('DELETE /api/learning/node', body={'id': 'canonical-skill'})['status'] == 403
                assert call('GET /api/git/review/commit-context', query={'path': str(workspace)})['status'] == 403
                checks.append('unsafe-learning-mutation-and-git-aggregate-explicit-denial')
                download = call('GET /api/fs/download', query={'path': 'artifact.bin'})
                assert download['status'] == 200, download
                handle = download['body']['downloadId']
                output = bytearray()
                while True:
                    chunk = rpc('desktop.download.read', {'profile': 'default', 'downloadId': handle, 'offset': len(output), 'length': 65536})
                    assert chunk['status'] == 200, chunk
                    output.extend(base64.b64decode(chunk['body']['dataBase64'], validate=True))
                    if chunk['body']['eof']:
                        break
                assert bytes(output) == binary
                checks.append('bounded-original-stream-download-sha256-byte-equality')
                # Same principal/profile on a different socket still cannot use
                # the handle: connection ownership is server-derived.
                pending_upload=None
                if args.media:
                    pending_upload=rpc('desktop.upload.begin',{'profile':'default','purpose':'transcribe',
                        'filename':'recording.wav','mimeType':'audio/wav','byteSize':3})['body']['uploadId']
                _, second_ticket = http('/api/auth/ws-ticket', 'POST', {})
                with connect(f'ws://127.0.0.1:{port}/api/ws', subprotocols=['hermes-gateway-v1', 'hermes-gateway-ticket.' + second_ticket['ticket']],
                             origin=base) as second:
                    second.recv(timeout=30)
                    second.send(json.dumps({'jsonrpc': '2.0', 'id': 900, 'method': 'desktop.download.read', 'params': {'profile': 'default', 'downloadId': handle, 'offset': 0, 'length': 100}}))
                    while True:
                        reply = json.loads(second.recv(timeout=20))
                        if reply.get('id') == 900:
                            assert reply['result']['status'] == 404, reply
                            break
                    if args.media:
                        for index,method in enumerate(('append','complete','release'),start=901):
                            parameters={'profile':'default','uploadId':pending_upload}
                            if method=='append': parameters.update(offset=0,sequence=0,dataBase64='YWJj')
                            second.send(json.dumps({'jsonrpc':'2.0','id':index,'method':'desktop.upload.'+method,'params':parameters}))
                            while True:
                                denied=json.loads(second.recv(timeout=20))
                                if denied.get('id')==index:
                                    assert denied['result']['status']==404,denied
                                    break
                if args.media:
                    assert rpc('desktop.upload.release',{'profile':'default','uploadId':pending_upload})['status']==200
                    checks.append('actual-ws-upload-cross-connection-append-complete-release-denied')
                assert rpc('desktop.download.release', {'profile': 'default', 'downloadId': handle})['status'] == 200
                assert rpc('desktop.download.read', {'profile': 'default', 'downloadId': handle, 'offset': 0, 'length': 10})['status'] == 404
                checks.append('download-cross-connection-and-release-denials')
                result = call('POST /api/audio/transcribe', body={'data_url': 'not audio'})
                assert result['status'] == 400, result
                result = call('POST /api/audio/speak', body={'text': ' '})
                assert result['status'] == 400, result
                checks.append('original-audio-relay-input-validation-no-provider-call')
                assert rpc('gateway.ping', {})['ok'] is True
                checks.append('original-typed-ws-heartbeat-retained')
                _, auth_proof = http('/health', auth=False)
                assert auth_proof['delegatedRequests'] > 0 and auth_proof['identityPreserved'], auth_proof
                checks.append('original-auth-middleware-retains-ticket-principal-at-service')
        except BaseException as exc:
            import traceback
            location = traceback.extract_tb(exc.__traceback__)[-1]
            error = f'{type(exc).__name__}: {exc} (line {location.lineno}: {location.line})'
        finally:
            if proc is not None and proc.poll() is None:
                try:
                    owned_children.extend(psutil.Process(proc.pid).children(recursive=True))
                except psutil.NoSuchProcess:
                    pass
                for child in reversed(owned_children):
                    try:
                        child.terminate()
                    except psutil.NoSuchProcess:
                        pass
                proc.terminate()
                try:
                    proc.wait(timeout=20)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    proc.wait(timeout=10)
                _, alive = psutil.wait_procs(owned_children, timeout=10)
                for child in alive:
                    child.kill()
                psutil.wait_procs(alive, timeout=5)
    released = True
    if port is not None:
        with socket.socket() as probe:
            released = probe.connect_ex(('127.0.0.1', port)) != 0
    evidence = {'sourceCommit': SOURCE_COMMIT, 'pid': proc.pid if proc else None, 'port': port,
                'checks': checks, 'checkCount': len(checks), 'error': error,
                'listenerReleased': released, 'processExited': proc is not None and proc.poll() is not None,
                'artifactSha256': hashlib.sha256(binary).hexdigest(), 'lab': str(lab),
                'limitations': ['Synthetic state/identity only; no live-account integration.',
                                'No microphone, valid STT/TTS provider, Android renderer, or complete Desktop parity proof.']}
    (lab / 'evidence.json').write_text(json.dumps(evidence, indent=2), encoding='utf-8')
    print(json.dumps(evidence, indent=2))
    if error or not released:
        raise SystemExit(1)


if __name__ == '__main__':
    main()
