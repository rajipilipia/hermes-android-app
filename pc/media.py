"""Finite connection/principal/profile-owned byte uploads, never arbitrary HTTP."""
from __future__ import annotations
import base64
import binascii
from contextlib import contextmanager
from pathlib import Path
import secrets
import re
import tempfile
import threading
import time
import weakref
from .catalog import CapabilityError, PROFILE, NAME, BOOL, PATH, obj, string, integer, validate_schema

CHUNK_BYTES = 65536
UPLOAD_BYTES = 25 * 1024 * 1024
UPLOAD_COUNT = 4
UPLOAD_AGGREGATE = 50 * 1024 * 1024
UPLOAD_TTL = 60
BEGIN_PROPERTIES = {'purpose':string(32,enum=['workspace','transcribe','file.attach','image.attach']),
    'filename':string(255), 'mimeType':string(128), 'byteSize':integer(0,UPLOAD_BYTES),
    'path':PATH, 'overwrite':BOOL, 'sessionId':NAME, 'storedSessionId':NAME}
BEGIN_REQUIRED = ['purpose','filename','mimeType','byteSize']
BINARY_SCHEMAS = {
    'desktop.audio.config':obj({'profile':PROFILE},['profile']),
    'desktop.upload.begin':obj({'profile':PROFILE,**BEGIN_PROPERTIES},['profile',*BEGIN_REQUIRED]),
    'desktop.upload.append':obj({'profile':PROFILE,'uploadId':string(128),'offset':integer(0,UPLOAD_BYTES),
        'sequence':integer(0,UPLOAD_BYTES),'dataBase64':string(4*((CHUNK_BYTES+2)//3))},
        ['profile','uploadId','offset','sequence','dataBase64']),
    'desktop.upload.complete':obj({'profile':PROFILE,'uploadId':string(128)},['profile','uploadId']),
    'desktop.upload.release':obj({'profile':PROFILE,'uploadId':string(128)},['profile','uploadId'])}


def binary_contract():
    from .addon import CHUNK_BYTES as DOWNLOAD_CHUNK, MAX_DOWNLOAD_BYTES, DOWNLOAD_TTL
    read=obj({'profile':PROFILE,'downloadId':string(128),'offset':integer(0,MAX_DOWNLOAD_BYTES),
              'length':integer(1,DOWNLOAD_CHUNK)},['profile','downloadId','offset','length'])
    release=obj({'profile':PROFILE,'downloadId':string(128)},['profile','downloadId'])
    return {'schemaVersion':1,'transport':'authenticated original /api/ws JSON-RPC',
        'requestSchemas':{**BINARY_SCHEMAS,'desktop.download.read':read,'desktop.download.release':release},
        'replyEnvelope':obj({'status':integer(100,599),'body':{}},['status','body']),
        'purposeFields':{'workspace':['path','overwrite'],'transcribe':[],
            'file.attach':['sessionId','storedSessionId'],'image.attach':['sessionId','storedSessionId']},
        'purposePermission':{'workspace':'files.write','transcribe':'audio','file.attach':'files.write','image.attach':'files.write'},
        'requireReadForUploadRpc':True,
        'uploadLimits':{'byteSize':UPLOAD_BYTES,'countIncludingPending':UPLOAD_COUNT,'aggregateDeclaredBytes':UPLOAD_AGGREGATE,
            'chunkBytes':CHUNK_BYTES,'ttlSeconds':UPLOAD_TTL,'maxChunks':(UPLOAD_BYTES+CHUNK_BYTES-1)//CHUNK_BYTES,
            'fullChunksExceptFinal':True},
        'resultFields':{'begin':['uploadId','chunkBytes','expiresInSeconds'],'append':['offset','sequence'],
            'release':['released'],'transcribe':['ok','transcript','provider'],
            'workspace':['ok','entry','path','root','locked_root','can_change_path'],
            'file.attach':['attached','name','path','ref_path','ref_text','uploaded'],
            'image.attach':['attached','path','count','remainder','text','bytes','name','width?','height?','token_estimate?'],
            'downloadDescriptor':['downloadId','byteSize','mimeType','chunkBytes','expiresInSeconds'],
            'downloadChunk':['dataBase64','offset','byteSize','mimeType','eof']},
        'audioConfig':{'ok':True,'stt':{'mode':'relay','streaming':False},'tts':{'mode':'relay','streaming':False}},
        'completeResultPurpose':{'workspace':'original managed-file DTO','transcribe':'original transcription DTO',
            'file.attach':'original file.attach DTO','image.attach':'original image.attach_bytes DTO'},
        'ttsCall':{'operation':'POST /api/audio/speak','output':'downloadDescriptor','provider':None},
        'lifecycle':'Exact principal/profile/socket owner. Fixed TTL, no refresh. Complete consumes once; never retry uncertain writes. Release cancels pending work but keeps quota/handles/barrier through original settlement. Disconnect, expiry and shutdown cancel; temp files close after settlement. Completed attachments/workspace files are durable.',
        'credentials':'No URL, method, headers, identity, provider key, client-direct lease or bearer URL is accepted or returned.'}


def transcription_result(value):
    if not isinstance(value,dict) or value.get('ok') is not True or not isinstance(value.get('transcript'),str):
        raise CapabilityError(502,'invalid transcription relay result')
    provider=value.get('provider')
    if not isinstance(provider,str) or re.fullmatch(r'[a-z][a-z0-9-]{0,63}',provider) is None:
        provider=None
    return {'ok':True,'transcript':value['transcript'],'provider':provider}


def validate_metadata(params):
    validate_schema(params,obj(BEGIN_PROPERTIES,BEGIN_REQUIRED),'upload')
    name = params['filename']
    if (not name or name != name.strip() or name.endswith('.') or name in ('.','..')
            or any(ord(c)<32 or c in '/\\\\:*?"<>|%' for c in name)
            or re.match(r'(?i)^(?:con|prn|aux|nul|com[0-9]|lpt[0-9])(?:\.|$)',name)):
        raise CapabilityError(400,'invalid literal upload filename')
    if re.fullmatch(r'[A-Za-z0-9!#$&^_.+-]+/[A-Za-z0-9!#$&^_.+-]+(?:;codecs=[A-Za-z0-9_.+-]+)?',params['mimeType']) is None:
        raise CapabilityError(400,'invalid upload MIME type')
    if params['purpose']=='workspace':
        if 'path' not in params or 'overwrite' not in params:
            raise CapabilityError(400,'workspace upload requires path and overwrite')
        if Path(params['path']).name != name or set(params)-set(BEGIN_REQUIRED)-{'path','overwrite'}:
            raise CapabilityError(400,'destination and literal filename differ or unlisted fields')
    elif params['purpose'].endswith('.attach'):
        if (set(params)!=set(BEGIN_REQUIRED)|{'sessionId','storedSessionId'}
                or params['byteSize']==0):
            raise CapabilityError(400,'attachment requires exact live and stored IDs only')
        if params['purpose']=='image.attach' and not params['mimeType'].startswith('image/'):
            raise CapabilityError(400,'image MIME required')
    elif set(params)-set(BEGIN_REQUIRED) or params['byteSize']==0 or not (
            params['mimeType'].startswith('audio/') or params['mimeType'].split(';')[0]=='video/webm'):
        raise CapabilityError(400,'transcription requires nonempty audio and no workspace fields')

class Uploads:
    def __init__(self, spool_dir):
        self.spool_dir = Path(spool_dir)
        self.spool_dir.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._items = {}
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._watch, name='pc-upload-reaper', daemon=True)
        self._thread.start()

    def _watch(self):
        while not self._stop.wait(.05):
            with self._lock:
                self._reap()

    def _drop(self, handle):
        item = self._items.pop(handle, None)
        if item:
            item['file'].close()

    def _cancel(self,item):
        if not item['cancelled']:
            item['cancelled']=True
            task=item.get('task')
            if task is not None and not task.done():
                task.get_loop().call_soon_threadsafe(task.cancel)

    def _reap(self):
        for handle, item in tuple(self._items.items()):
            transport = item['transport']()
            if item['expires'] <= time.monotonic() or transport is None or transport.closed or self._stop.is_set():
                self._cancel(item)
                if not item['claimed']:
                    self._drop(handle)

    def _get(self, owner, handle):
        self._reap()
        item = self._items.get(handle)
        if item is None or item['owner'] != owner.key:
            raise CapabilityError(404, 'upload unavailable for this owner')
        if item['cancelled']:
            raise CapabilityError(410, 'upload cancelled; do not retry completion')
        return item

    def begin(self, owner, transport, params):
        validate_schema(owner.profile,PROFILE,'profile')
        validate_metadata(params)
        with self._lock:
            self._reap()
            if (len(self._items)>=UPLOAD_COUNT or
                    sum(item['byteSize'] for item in self._items.values())+params['byteSize']>UPLOAD_AGGREGATE):
                raise CapabilityError(429,'upload reservation quota reached')
            if self._stop.is_set() or transport.closed:
                raise CapabilityError(410, 'upload owner disconnected or adapter closed')
            handle = secrets.token_urlsafe(24)
            stream = tempfile.TemporaryFile(dir=self.spool_dir, mode='w+b')
            self._items[handle] = {**params, 'file':stream, 'owner':owner.key,
                'transport':weakref.ref(transport), 'offset':0, 'sequence':0,
                'expires':time.monotonic()+UPLOAD_TTL, 'claimed':False, 'cancelled':False}
            return {'uploadId':handle, 'chunkBytes':CHUNK_BYTES, 'expiresInSeconds':UPLOAD_TTL}

    def append(self, owner, handle, offset, sequence, data_base64):
        with self._lock:
            item = self._get(owner, handle)
            if item['claimed'] or offset != item['offset'] or sequence != item['sequence']:
                raise CapabilityError(409, 'upload offset or state conflict; do not retry automatically')
            validate_schema(offset,integer(0,UPLOAD_BYTES),'offset')
            validate_schema(sequence,integer(0,UPLOAD_BYTES),'sequence')
            validate_schema(data_base64,string(4*((CHUNK_BYTES+2)//3)),'dataBase64')
            try:
                data = base64.b64decode(data_base64, validate=True)
            except (ValueError,binascii.Error):
                raise CapabilityError(400,'invalid upload base64 chunk') from None
            if not data or len(data)>CHUNK_BYTES or base64.b64encode(data).decode()!=data_base64:
                raise CapabilityError(400,'invalid canonical upload chunk')
            if offset+len(data)>item['byteSize']:
                raise CapabilityError(413,'upload exceeds declared size')
            if len(data)!=min(CHUNK_BYTES,item['byteSize']-offset):
                raise CapabilityError(400,'upload chunks must be full sized except the final chunk')
            try:
                if item['file'].write(data)!=len(data):
                    raise OSError('short spool write')
            except BaseException:
                self._drop(handle)
                raise CapabilityError(502,'upload spool failed; upload discarded') from None
            item['offset'] += len(data)
            item['sequence'] += 1
            return {'offset':item['offset'], 'sequence':item['sequence']}

    @contextmanager
    def claim(self, owner, handle, *, task=None):
        with self._lock:
            item = self._get(owner, handle)
            if item['claimed'] or item['offset'] != item['byteSize']:
                raise CapabilityError(409, 'upload incomplete or already completing')
            item['claimed'] = True
            item['task'] = task
            item['file'].seek(0)
        try:
            yield item
        finally:
            with self._lock:
                self._drop(handle)

    def release(self, owner, handle):
        with self._lock:
            item = self._get(owner, handle)
            self._cancel(item)
            if not item['claimed']:
                self._drop(handle)
        return {'released':True}

    def close(self):
        self._stop.set()
        self._thread.join(timeout=2)
        with self._lock:
            self._reap()
