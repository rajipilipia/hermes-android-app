"""Bounded byte protocol tracer bullets; all data and spools are disposable."""
import base64
from dataclasses import replace
import importlib
import importlib.util
import os
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch
from pc.catalog import CapabilityError
from pc.policy import Owner

ROOT = Path(__file__).resolve().parents[2]
class Transport:
    closed = False

class OriginalMediaHarness(unittest.TestCase):
    def test_original_asgi_media_in_fresh_scrubbed_home(self):
        import subprocess
        import sys
        with tempfile.TemporaryDirectory(dir=ROOT/'.cache/pc-lab',prefix='media-service-') as directory:
            env={k:v for k,v in os.environ.items() if k.upper() in {'SYSTEMROOT','WINDIR','COMSPEC',
                'PATH','PATHEXT','SYSTEMDRIVE','NUMBER_OF_PROCESSORS','PROCESSOR_ARCHITECTURE'}}
            env['PYTHONPATH']=str(ROOT)
            env.update(HOME=directory,USERPROFILE=directory,HERMES_HOME=directory,
                APPDATA=str(Path(directory)/'roaming'),LOCALAPPDATA=str(Path(directory)/'local'),
                TMP=directory,TEMP=directory,TMPDIR=directory,PYTHONDONTWRITEBYTECODE='1',HERMES_DISABLE_LAZY_INSTALLS='1')
            result=subprocess.run([sys.executable,'-B','-m','pc.tests.media_service_cases','-v'],
                cwd=ROOT,env=env,text=True,capture_output=True,timeout=120)
            self.assertEqual(result.returncode,0,result.stdout+result.stderr)
            self.assertIn('Ran 1 test',result.stderr)
            self.assertIn('OK',result.stderr)


class UploadProtocol(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(dir=ROOT/'.cache/pc-lab')
        self.addCleanup(self.directory.cleanup)
        self.owner = Owner('fixture', 'alice', 'research', 'connection', (), frozenset({'read','files.write','audio'}))
        self.transport = Transport()

    def store(self):
        self.assertIsNotNone(importlib.util.find_spec('pc.media'), 'finite upload protocol missing')
        module = importlib.import_module('pc.media')
        store = module.Uploads(self.directory.name)
        self.addCleanup(store.close)
        return store

    def begin(self, store, data=b'first\x00\xffsecond'):
        return store.begin(self.owner, self.transport, {
            'purpose':'workspace', 'filename':'სცადა file.bin', 'mimeType':'application/octet-stream',
            'byteSize':len(data), 'path':'სცადა file.bin', 'overwrite':False})['uploadId']

    def test_bytes_are_ordered_spooled_claimed_once_and_removed_at_settlement(self):
        store = self.store()
        data = b'first\x00\xffsecond'
        handle = self.begin(store, data)
        result = store.append(self.owner, handle, 0, 0, base64.b64encode(data).decode())
        self.assertEqual(result, {'offset':len(data),'sequence':1})
        with store.claim(self.owner, handle) as item:
            self.assertEqual(item['file'].read(), data)
            self.assertEqual(item['filename'], 'სცადა file.bin')
        self.assertTrue(item['file'].closed)
        with self.assertRaises(CapabilityError):
            with store.claim(self.owner, handle):
                self.fail('uncertain completion retried')
        self.assertEqual(list(Path(self.directory.name).iterdir()), [])

    def test_partial_spool_failure_closes_and_releases_reservation(self):
        store = self.store()
        handle = self.begin(store,b'abc')
        stream=store._items[handle]['file']
        class ShortWriter:
            def write(self,data): stream.write(data[:1]); return 1
            def close(self): stream.close()
        store._items[handle]['file']=ShortWriter()
        with self.assertRaises(CapabilityError): store.append(self.owner,handle,0,0,'YWJj')
        self.assertTrue(stream.closed)
        self.assertEqual(store._items,{})

    def test_shutdown_retains_claimed_stream_until_its_finally_settles(self):
        store=self.store(); handle=self.begin(store,b'abc')
        store.append(self.owner,handle,0,0,'YWJj')
        with store.claim(self.owner,handle) as item:
            store.close()
            self.assertFalse(item['file'].closed)
            with self.assertRaises(CapabilityError): self.begin(store,b'abc')
        self.assertTrue(item['file'].closed)
        self.assertEqual(store._items,{})

    def test_tiny_nonfinal_chunks_cannot_create_unbounded_rpc_sequence(self):
        store = self.store()
        handle = self.begin(store,b'x'*65537)
        with self.assertRaises(CapabilityError): store.append(self.owner,handle,0,0,'eA==')

    def test_upload_metadata_chunks_and_pending_quota_are_bounded(self):
        store = self.store()
        for changes in ({'byteSize':True}, {'byteSize':-1}, {'filename':'../bad'},
                        {'filename':'x\r\ny'}, {'filename':'CON.txt'}, {'filename':'name.'},
                        {'mimeType':'audio/wav\r\nX: y'}, {'url':'https://invalid'},
                        {'purpose':'arbitrary'}, {'profile':'other'}):
            params = {'purpose':'workspace','filename':'literal.bin','mimeType':'application/octet-stream',
                      'byteSize':3,'path':'literal.bin','overwrite':False, **changes}
            with self.subTest(changes=changes), self.assertRaises(CapabilityError):
                store.begin(self.owner,self.transport,params)
        handle = self.begin(store,b'abc')
        for encoded in ('!!!!','YQ','YQ==\n',base64.b64encode(b'x'*65537).decode(), 'YWI='):
            offset = 2 if encoded == 'YWI=' else 0
            with self.subTest(encoded=encoded[:10]), self.assertRaises(CapabilityError):
                store.append(self.owner,handle,offset,0,encoded)
        store.release(self.owner,handle)
        module = importlib.import_module('pc.media')
        with patch.object(module,'UPLOAD_COUNT',2), patch.object(module,'UPLOAD_AGGREGATE',5):
            first = self.begin(store,b'abc')
            with self.assertRaises(CapabilityError): self.begin(store,b'abc')
            store.release(self.owner,first)
            first = self.begin(store,b'a')
            second = self.begin(store,b'b')
            with self.assertRaises(CapabilityError): self.begin(store,b'c')
            store.release(self.owner,first); store.release(self.owner,second)

    def test_owner_fences_duplicate_offsets_expiry_disconnect_and_claimed_cancel(self):
        store = self.store()
        handle = self.begin(store,b'abc')
        for owner in (replace(self.owner,user_id='bob'),replace(self.owner,profile='default'),
                      replace(self.owner,connection='new')):
            with self.assertRaises(CapabilityError): store.append(owner,handle,0,0,'YWJj')
        store.append(self.owner,handle,0,0,'YWJj')
        with self.assertRaises(CapabilityError): store.append(self.owner,handle,0,0,'YWJj')
        with store.claim(self.owner,handle) as item:
            with self.assertRaises(CapabilityError):
                with store.claim(self.owner,handle): self.fail('duplicate complete')
            store.release(self.owner,handle)
            self.assertFalse(item['file'].closed,'pending writer released before settlement')
        self.assertTrue(item['file'].closed)
        with patch('pc.media.UPLOAD_TTL',.02): handle = self.begin(store,b'abc')
        time.sleep(.12)
        self.assertEqual(store._items,{})
        handle = self.begin(store,b'abc')
        stream = store._items[handle]['file']
        self.transport.closed = True
        time.sleep(.12)
        self.assertTrue(stream.closed)
