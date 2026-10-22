"""Original ASGI byte-path tests. Runs in its own scrubbed-home subprocess."""
import asyncio
import base64
import importlib.util
import json
import os
from pathlib import Path
import sys
import unittest
from unittest.mock import patch
ROOT = Path(__file__).resolve().parents[2]
UPSTREAM = Path('C:/example/hermes-agent')

class OriginalMedia(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not Path(os.environ['HERMES_HOME']).resolve().is_relative_to(ROOT/'.cache/pc-lab'):
            raise RuntimeError('scrubbed home required')
        sys.path.insert(0,str(UPSTREAM))

    def test_original_multipart_workspace_upload_and_audio_bytes(self):
        from pc.addon import Adapter
        from pc.policy import Policy
        from pc.catalog import validate_call
        from pc.bootstrap import load_pinned_onboarding
        load_pinned_onboarding(UPSTREAM)
        from tui_gateway.ws import WSTransport
        from hermes_cli import web_server
        home = Path(os.environ['HERMES_HOME'])
        workspace = home/'workspace'; workspace.mkdir(exist_ok=True)
        profile = home/'profiles/mediafixture'; profile.mkdir(parents=True,exist_ok=True)
        (profile/'config.yaml').write_text('{}\n')
        policy = Policy.from_dict({'principals':[{'provider':'fixture','user_id':'alice','profiles':{
            'mediafixture':{'roots':[str(workspace)],'permissions':['read','files.write','audio']}}}]})
        app = web_server.app
        app.state.auth_required=True; app.state.bound_host='127.0.0.1'; app.state.trusted_public_hosts=frozenset()
        class Transport: closed=False
        async def run():
            adapter = Adapter(app,None,policy,home/'spool')
            # Exercise the actual current transport-owner admission with an
            # explicitly synthetic authenticated identity; no socket is opened.
            transport = WSTransport(None,asyncio.get_running_loop(),
                auth_identity={'provider':'fixture','user_id':'alice'})
            owner = adapter.owner(transport,'mediafixture','audio')
            data = bytes(range(256))*1300
            try:
                self.assertTrue(callable(getattr(adapter,'complete_upload',None)), 'original ASGI upload composition missing')
                upload = adapter.uploads.begin(owner,transport,{'purpose':'workspace','filename':'ქართული bytes.bin',
                    'path':'ქართული bytes.bin','mimeType':'application/octet-stream','byteSize':len(data),'overwrite':False})
                handle = upload['uploadId']
                for seq,offset in enumerate(range(0,len(data),65536)):
                    adapter.uploads.append(owner,handle,offset,seq,base64.b64encode(data[offset:offset+65536]).decode())
                result = await adapter.complete_upload(owner,transport,handle)
                self.assertEqual(result['status'],200,result)
                self.assertEqual((workspace/'ქართული bytes.bin').read_bytes(),data)
                self.assertTrue(result['body']['ok'])
                self.assertEqual(result['body']['entry']['name'],'ქართული bytes.bin')
                from pc.catalog import CapabilityError
                denied=adapter.uploads.begin(owner,transport,{'purpose':'workspace','filename':'revoked.bin',
                    'path':str(workspace/'revoked.bin'),'mimeType':'application/octet-stream','byteSize':3,'overwrite':False})
                adapter.uploads.append(owner,denied['uploadId'],0,0,'YWJj')
                key=('fixture','alice','mediafixture'); saved_grant=policy._grants[key]
                other_root=home/'other-workspace'; other_root.mkdir()
                policy._grants[key]=((other_root,),saved_grant[1])
                try:
                    with self.assertRaises(CapabilityError): await adapter.complete_upload(owner,transport,denied['uploadId'])
                finally: policy._grants[key]=saved_grant
                self.assertFalse((workspace/'revoked.bin').exists())
                recording = b'RIFF'+bytes(range(128))*200
                observed=[]
                def transcribe(path):
                    observed.append((Path(path).read_bytes(),Path(path)))
                    return {'success':True,'transcript':'  ქართული ტექსტი  ','provider':'fixture'}
                upload = adapter.uploads.begin(owner,transport,{'purpose':'transcribe','filename':'recording.wav',
                    'mimeType':'audio/wav','byteSize':len(recording)})
                adapter.uploads.append(owner,upload['uploadId'],0,0,base64.b64encode(recording).decode())
                with patch('tools.voice_mode.transcribe_recording',side_effect=transcribe):
                    result = await adapter.complete_upload(owner,transport,upload['uploadId'])
                self.assertEqual(result,{'status':200,'body':{'ok':True,'transcript':'ქართული ტექსტი','provider':'fixture'}})
                self.assertEqual(observed[0][0],recording)
                self.assertFalse(observed[0][1].exists(),'original audio tempfile orphaned')
                legacy = await adapter.invoke(validate_call({'operation':'POST /api/files/upload','profile':'mediafixture',
                    'body':{'path':'legacy.txt','data_url':'data:text/plain;base64,bGVnYWN5','overwrite':False}}),owner,transport)
                self.assertEqual(legacy['status'],200,legacy)
                self.assertEqual((workspace/'legacy.txt').read_bytes(),b'legacy')
                from starlette.datastructures import UploadFile as StarletteUpload
                read_once=set()
                original_read=StarletteUpload.read
                async def partial_read(file,size=-1):
                    if id(file) in read_once: raise OSError('opaque-provider-text-must-not-leak')
                    read_once.add(id(file))
                    return await original_read(file,3)
                up=adapter.uploads.begin(owner,transport,{'purpose':'workspace','filename':'legacy.txt',
                    'path':'legacy.txt','mimeType':'text/plain','byteSize':6,'overwrite':True})
                adapter.uploads.append(owner,up['uploadId'],0,0,'YWJjZGVm')
                with patch.object(StarletteUpload,'read',partial_read):
                    failed_upload=await adapter.complete_upload(owner,transport,up['uploadId'])
                self.assertGreaterEqual(failed_upload['status'],400)
                self.assertNotIn('opaque-provider-text',json.dumps(failed_upload))
                self.assertEqual((workspace/'legacy.txt').read_bytes(),b'legacy','partial upload clobbered original')
                self.assertEqual(list(workspace.glob('*.upload')),[])
                self.assertEqual(list(workspace.glob('.pc-guard-*')),[])
                from pc.catalog import CapabilityError
                for path in ('../outside.bin','.env','config.yaml','https://example.invalid/a'):
                    with self.assertRaises(CapabilityError):
                        await adapter.invoke(validate_call({'operation':'POST /api/files/upload','profile':'mediafixture',
                            'body':{'path':path,'data_url':'data:text/plain;base64,YWJj','overwrite':True}}),owner,transport)
                speech = b'RIFF'+bytes(range(256))*2048
                produced=[]
                def synthesize(text):
                    self.assertEqual(text,'read aloud')
                    path = profile/'speech.wav'; path.write_bytes(speech); produced.append(path)
                    return json.dumps({'success':True,'file_path':str(path),'provider':'fixture'})
                with patch('tools.tts_tool.text_to_speech_tool',side_effect=synthesize):
                    spoken = await adapter.invoke(validate_call({'operation':'POST /api/audio/speak','profile':'mediafixture',
                        'body':{'text':'read aloud'}}),owner,transport)
                self.assertEqual(spoken['status'],200,spoken)
                self.assertIn('downloadId',spoken['body'],'TTS leaked whole data URL instead of bounded descriptor')
                output = bytearray(); descriptor = spoken['body']
                while len(output)<descriptor['byteSize']:
                    chunk = adapter.downloads.read(owner,descriptor['downloadId'],len(output),65536)
                    output.extend(base64.b64decode(chunk['dataBase64']))
                self.assertEqual(bytes(output),speech)
                self.assertFalse(produced[0].exists())
                adapter.downloads.release(owner,descriptor['downloadId'])
                with patch('tools.tts_tool.text_to_speech_tool',side_effect=synthesize), patch('pc.addon.MAX_DOWNLOAD_BYTES',64):
                    oversized=await adapter.invoke(validate_call({'operation':'POST /api/audio/speak','profile':'mediafixture',
                        'body':{'text':'read aloud'}}),owner,transport)
                self.assertEqual(oversized['status'],413,oversized)
                self.assertFalse(produced[-1].exists())
                self.assertEqual(adapter.downloads._pending,{})
                from pc.bootstrap import load_pinned_onboarding
                load_pinned_onboarding(UPSTREAM)
                from tui_gateway import server
                adapter.server = server
                server._sessions['media-live'] = {'session_key':'media-stored','profile_home':str(profile),
                    'auth_user_id':'fixture:alice','transport':transport,'cwd':str(workspace),'attached_images':[]}
                try:
                    upload = adapter.uploads.begin(owner,transport,{'purpose':'file.attach','filename':'ქართული note.txt',
                        'mimeType':'text/plain','byteSize':3,'sessionId':'media-live','storedSessionId':'media-stored'})
                    adapter.uploads.append(owner,upload['uploadId'],0,0,'YWJj')
                    attached = await adapter.complete_upload(owner,transport,upload['uploadId'])
                    self.assertEqual(attached['status'],200,attached)
                    self.assertEqual(attached['body']['name'],'ქართული note.txt')
                    self.assertTrue(attached['body']['ref_text'].startswith('@file:'))
                    self.assertEqual(Path(attached['body']['path']).read_bytes(),b'abc')
                    self.assertTrue(Path(attached['body']['path']).is_relative_to(profile/'attachments'))
                    hidden = adapter.uploads.begin(owner,transport,{'purpose':'file.attach','filename':'.note.txt',
                        'mimeType':'text/plain','byteSize':3,'sessionId':'media-live','storedSessionId':'media-stored'})
                    adapter.uploads.append(owner,hidden['uploadId'],0,0,'YWJj')
                    hidden_result=await adapter.complete_upload(owner,transport,hidden['uploadId'])
                    self.assertEqual(hidden_result['body']['name'],'.note.txt','valid literal filename was repaired')
                    image=base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jCWQAAAAASUVORK5CYII=')
                    up=adapter.uploads.begin(owner,transport,{'purpose':'image.attach','filename':'literal.png',
                        'mimeType':'image/png','byteSize':len(image),'sessionId':'media-live','storedSessionId':'media-stored'})
                    adapter.uploads.append(owner,up['uploadId'],0,0,base64.b64encode(image).decode())
                    image_result=await adapter.complete_upload(owner,transport,up['uploadId'])
                    self.assertEqual(image_result['status'],200,image_result)
                    self.assertEqual(image_result['body']['count'],1)
                    self.assertEqual(Path(image_result['body']['path']).read_bytes(),image)
                    self.assertIn(image_result['body']['path'],server._sessions['media-live']['attached_images'])
                    from pc.catalog import CapabilityError
                    for field,value in (('sessionId','media'),('storedSessionId','media'),('storedSessionId','foreign')):
                        metadata={'purpose':'file.attach','filename':'denied.txt','mimeType':'text/plain','byteSize':3,
                                  'sessionId':'media-live','storedSessionId':'media-stored',field:value}
                        up=adapter.uploads.begin(owner,transport,metadata)
                        adapter.uploads.append(owner,up['uploadId'],0,0,'YWJj')
                        with self.assertRaises(CapabilityError): await adapter.complete_upload(owner,transport,up['uploadId'])
                    for field,value in (('auth_user_id','fixture:bob'),('profile_home',str(home)),('transport',Transport())):
                        session=server._sessions['media-live']; before=session[field]; session[field]=value
                        try:
                            up=adapter.uploads.begin(owner,transport,{'purpose':'file.attach','filename':'denied.txt',
                                'mimeType':'text/plain','byteSize':3,'sessionId':'media-live','storedSessionId':'media-stored'})
                            adapter.uploads.append(owner,up['uploadId'],0,0,'YWJj')
                            with self.assertRaises(CapabilityError): await adapter.complete_upload(owner,transport,up['uploadId'])
                        finally: session[field]=before
                    from hermes_cli.web_server_sessions import _session_db_path_for_profile
                    from hermes_state import SessionDB
                    seed=SessionDB(_session_db_path_for_profile('mediafixture'))
                    try:
                        seed._conn.execute('PRAGMA foreign_keys=OFF')
                        seed.create_session('media-stored',source='cli',profile_name='mediafixture',parent_session_id='missing-parent')
                    finally: seed.close()
                    up=adapter.uploads.begin(owner,transport,{'purpose':'file.attach','filename':'dangling.txt',
                        'mimeType':'text/plain','byteSize':3,'sessionId':'media-live','storedSessionId':'media-stored'})
                    adapter.uploads.append(owner,up['uploadId'],0,0,'YWJj')
                    with self.assertRaises(CapabilityError): await adapter.complete_upload(owner,transport,up['uploadId'])
                finally:
                    server._sessions.pop('media-live',None)
                # Provider errors can contain arbitrary plaintext secrets that
                # pattern redaction cannot recognize. Relay errors must be static.
                marker='opaque-unrecognizable-provider-secret'
                def fail_transcribe(path):
                    return {'success':False,'error':marker,'provider':'fixture','api_key':marker}
                with patch('tools.voice_mode.transcribe_recording',side_effect=fail_transcribe):
                    failed = await adapter.invoke(validate_call({'operation':'POST /api/audio/transcribe','profile':'mediafixture',
                        'body':{'data_url':'data:audio/wav;base64,YWJj','mime_type':'audio/wav'}}),owner,transport)
                self.assertEqual(failed['status'],400,failed)
                self.assertNotIn(marker,json.dumps(failed),'provider error leaked opaque credential')
                import threading
                from pc.catalog import Call, OPERATIONS, CapabilityError
                started,finish=threading.Event(),threading.Event()
                def blocking(path):
                    started.set(); finish.wait(5)
                    return {'success':False,'error':marker,'provider':'fixture'}
                upload=adapter.uploads.begin(owner,transport,{'purpose':'transcribe','filename':'cancel.wav',
                    'mimeType':'audio/wav','byteSize':3})
                handle=upload['uploadId']; adapter.uploads.append(owner,handle,0,0,'YWJj')
                stream=adapter.uploads._items[handle]['file']
                with patch('tools.voice_mode.transcribe_recording',side_effect=blocking), patch('pc.media.UPLOAD_COUNT',1):
                    adapter._slots.acquire(False)
                    call=Call(OPERATIONS['POST /api/audio/transcribe'],owner.profile,{}, {},None)
                    pending=asyncio.create_task(adapter._run_admitted(call,owner,transport,
                        action=lambda:adapter.complete_upload(owner,transport,handle)))
                    await asyncio.to_thread(started.wait,2)
                    self.assertTrue(started.is_set())
                    with self.assertRaises(CapabilityError) as duplicate:
                        await adapter.complete_upload(owner,transport,handle)
                    self.assertEqual(duplicate.exception.status,409)
                    adapter.uploads.release(owner,handle)
                    await asyncio.sleep(.1)
                    self.assertFalse(pending.done(),'cancellation released settling provider')
                    self.assertFalse(stream.closed)
                    self.assertTrue(adapter._write_barrier.locked())
                    with self.assertRaises(CapabilityError):
                        adapter.uploads.begin(owner,transport,{'purpose':'transcribe','filename':'other.wav',
                            'mimeType':'audio/wav','byteSize':3})
                    finish.set()
                    with self.assertRaises(asyncio.CancelledError): await pending
                    self.assertTrue(stream.closed)
                    self.assertFalse(adapter._write_barrier.locked())
            finally:
                await adapter.aclose()
        asyncio.run(run())

if __name__=='__main__': unittest.main()
