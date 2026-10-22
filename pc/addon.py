"""Additive Desktop compatibility RPCs for a NEW, explicitly authorized runtime.

Original endpoint routing, Pydantic validation and dashboard authorization remain
in the request path. No HTTP client, arbitrary forwarding, auth header parameter,
provider access token, or caller-selected URL crosses this seam.
"""
from __future__ import annotations

import asyncio
import base64
import contextvars
from concurrent.futures import CancelledError as FutureCancelledError
import hashlib
import hmac
import json
import mimetypes
from pathlib import Path
import re
import secrets
import tempfile
import threading
import time
from urllib.parse import urlencode
import weakref

from .catalog import (CapabilityError, MAX_JSON_BYTES, NAME, PROFILE, OPERATIONS, SETTINGS,
                      integer, obj, string, validate_call, validate_schema)

MAX_DOWNLOAD_BYTES = 32 * 1024 * 1024
MAX_DOWNLOADS = 8
CHUNK_BYTES = 64 * 1024
DOWNLOAD_TTL = 60
REQUEST_TIMEOUT = 120
RPC_WAIT_TIMEOUT = 125
_SECRET_FIELD = re.compile(r'(^|_)(api_?key|access_?token|refresh_?token|token|secret|password|credential|authorization|cookie|env|headers)($|_)', re.I)
_BEARER = re.compile(r'(?i)\bBearer\s+[^\s"\'<>]+')
_QUERY_SECRET = re.compile(r'(?i)([?&](?:token|key|api_key|secret|authorization)=)[^&#\s"\']+')
_USERINFO = re.compile(r'(?i)(https?://)[^/@\s]+:[^/@\s]+@')
_KEY_TOKEN = re.compile(r'\b(?:sk-[A-Za-z0-9_-]{12,}|gh[pousr]_[A-Za-z0-9_]{12,}|eyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+)\b')


def redact(value):
    if isinstance(value, dict):
        return {k: redact(v) for k, v in value.items() if not _SECRET_FIELD.search(k)}
    if isinstance(value, list):
        return [redact(v) for v in value]
    if isinstance(value, str):
        value = _BEARER.sub('Bearer [REDACTED]', value)
        value = _QUERY_SECRET.sub(r'\1[REDACTED]', value)
        value = _USERINFO.sub(r'\1[REDACTED]@', value)
        return _KEY_TOKEN.sub('[REDACTED]', value)
    return value


def project_mcp(value):
    """Compatibility name for the closed, structurally typed MCP DTO."""
    from .projections import project_metadata
    return project_metadata('mcp', value)


def _settings(value, schema=SETTINGS):
    if not isinstance(value, dict):
        return {}
    projected = {}
    for key, child in schema['properties'].items():
        if key in value:
            if child.get('type') == 'object':
                projected[key] = _settings(value[key], child)
            else:
                try:
                    validate_schema(value[key], child)
                    projected[key] = value[key]
                except CapabilityError:
                    pass
    return projected


class Downloads:
    """Quota includes in-flight reservations. A live reaper needs no client traffic."""
    def __init__(self, spool_dir):
        self.spool_dir = Path(spool_dir)
        self.spool_dir.mkdir(parents=True, exist_ok=True)
        self._items, self._pending = {}, {}
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._watch, name='pc-download-reaper', daemon=True)
        self._thread.start()

    def _watch(self):
        while not self._stop.wait(.05):
            with self._lock:
                self._reap()

    def _reap(self):
        now = time.monotonic()
        # Pending reservations are released ONLY by the owning call's finally
        # or successful put. A cancelled worker may still be settling; evicting
        # its reservation early would admit an unbounded number of live spools.
        for key, item in list(self._items.items()):
            transport = item['transport']()
            if item['expires'] <= now or transport is None or getattr(transport, 'closed', True):
                item['file'].close()
                del self._items[key]

    def reserve(self, owner, transport):
        with self._lock:
            self._reap()
            if self._stop.is_set() or getattr(transport, 'closed', True):
                raise CapabilityError(410, 'download owner disconnected or adapter closed')
            if len(self._items) + len(self._pending) >= MAX_DOWNLOADS:
                raise CapabilityError(429, 'download quota reached')
            handle = secrets.token_urlsafe(24)
            self._pending[handle] = {'owner': owner.key, 'expires': time.monotonic() + RPC_WAIT_TIMEOUT,
                                     'transport': weakref.ref(transport)}
            return handle

    def cancel(self, reservation):
        with self._lock:
            self._pending.pop(reservation, None)

    def put(self, owner, stream, size, mime, transport, *, reservation=None):
        try:
            if reservation is None:
                reservation = self.reserve(owner, transport)
            with self._lock:
                self._reap()
                pending = self._pending.pop(reservation, None)
                if (self._stop.is_set() or getattr(transport, 'closed', True) or pending is None
                        or pending['owner'] != owner.key or pending['expires'] <= time.monotonic()):
                    raise CapabilityError(410, 'download reservation expired')
                if not 0 <= size <= MAX_DOWNLOAD_BYTES:
                    raise CapabilityError(413, 'download size limit exceeded')
                self._items[reservation] = {**pending, 'file': stream, 'size': size, 'mime': mime,
                                            'expires': time.monotonic() + DOWNLOAD_TTL}
            return {'downloadId': reservation, 'byteSize': size, 'mimeType': mime,
                    'chunkBytes': CHUNK_BYTES, 'expiresInSeconds': DOWNLOAD_TTL}
        except BaseException:
            stream.close()
            raise

    def read(self, owner, handle, offset, length):
        with self._lock:
            self._reap()
            item = self._items.get(handle)
            if item is None or item['owner'] != owner.key:
                raise CapabilityError(404, 'download unavailable for this owner')
            if offset > item['size']:
                raise CapabilityError(416, 'download offset out of bounds')
            item['file'].seek(offset)
            data = item['file'].read(length)
            return {'dataBase64': base64.b64encode(data).decode('ascii'), 'offset': offset,
                    'byteSize': item['size'], 'mimeType': item['mime'], 'eof': offset + len(data) >= item['size']}

    def release(self, owner, handle):
        with self._lock:
            self._reap()
            item = self._items.get(handle)
            if item is None or item['owner'] != owner.key:
                raise CapabilityError(404, 'download unavailable for this owner')
            item['file'].close()
            del self._items[handle]
        return {'released': True}

    def close(self):
        self._stop.set()
        self._thread.join(timeout=2)
        with self._lock:
            for item in self._items.values():
                item['file'].close()
            self._items.clear()
            self._pending.clear()


async def settled_thread(function, *args, **kwargs):
    """Cancellation cannot free a slot/write barrier while its worker still runs.

    Python cannot interrupt an OS-blocking thread safely. Keep its admission
    lease until settlement; the client receives uncertainty, never a retry.
    """
    worker = asyncio.create_task(asyncio.to_thread(function, *args, **kwargs))
    cancelled = False
    while not worker.done():
        try:
            await asyncio.shield(worker)
        except asyncio.CancelledError:
            cancelled = True
    if cancelled:
        # Retrieve any worker exception before propagating cancellation.
        if not worker.cancelled():
            worker.exception()
        raise asyncio.CancelledError
    return worker.result()


async def settled_await(awaitable):
    """Keep an admitted original mutation's critical section until it settles."""
    worker = asyncio.create_task(awaitable)
    cancelled = False
    while not worker.done():
        try:
            await asyncio.shield(worker)
        except asyncio.CancelledError:
            cancelled = True
    if cancelled:
        if not worker.cancelled():
            worker.exception()
        raise asyncio.CancelledError
    return worker.result()


def install_settlement_routes(app, owner_getter):
    from functools import wraps
    # Original services may delegate work to their own threads. Do not cancel
    # that await then release admission while an uncertain writer still runs.
    for route in app.routes:
        if not hasattr(route, 'dependant') or not hasattr(route, 'methods') or 'GET' in route.methods:
            continue
        if not any(op.path == route.path and op.method in route.methods for op in OPERATIONS.values()):
            continue
        def wrap(original):
            @wraps(original)
            async def invoke(**arguments):
                if owner_getter() is None:
                    return await original(**arguments)
                return await settled_await(original(**arguments))
            return invoke
        route.dependant.call = wrap(route.dependant.call)


class Adapter:
    def __init__(self, app, server, policy, spool_dir):
        self.app, self.server, self.policy = app, server, policy
        self.downloads = Downloads(spool_dir)
        from .media import Uploads
        self.uploads = Uploads(spool_dir)
        self._connections = weakref.WeakKeyDictionary()
        self._lock = threading.Lock()
        self._slots = threading.BoundedSemaphore(8)
        self._write_barrier = threading.Lock()
        self._tasks = set()
        self._closed = False
        self.dictation = None
        self._closing = None
        self._admission_deadline = contextvars.ContextVar('android_desktop_deadline', default=None)
        # This private context capability is never serialized to the client.
        # The original auth middleware must verify it via its provider seam.
        self._delegation = contextvars.ContextVar('android_desktop_delegation', default=None)
        try:
            self._install_provider()
            from .filesystem import install_guarded_routes
            from .session_routes import install_session_routes
            from .read_routes import install_read_routes
            install_guarded_routes(app, policy, lambda: (self._delegation.get() or {}).get('owner'))
            install_session_routes(app, lambda: (self._delegation.get() or {}).get('owner'))
            install_read_routes(app, policy, self._delegation.get)
            from .media_routes import install_media_routes
            install_media_routes(app, policy, self._delegation.get)
            install_settlement_routes(app, lambda: (self._delegation.get() or {}).get('owner'))
        except BaseException:
            self.uploads.close()
            self.downloads.close()
            if hasattr(self, 'provider'):
                from hermes_cli.dashboard_auth.registry import unregister_global_provider
                unregister_global_provider(self.provider.name, self.provider)
            raise

    def _install_provider(self):
        from hermes_cli.dashboard_auth import DashboardAuthProvider, Session, register_provider
        from hermes_cli.dashboard_auth.base import InvalidCodeError, RefreshExpiredError
        context = self._delegation

        class DelegatedPrincipal(DashboardAuthProvider):
            name = 'android-desktop-delegation'
            display_name = 'Internal Android Desktop delegation (not a login)'

            @property
            def supports_session(self):
                # Discovery and verification share upstream's roster. Only the
                # private delegated call context enables verification; external
                # login discovery never sees this noninteractive provider.
                return context.get() is not None

            def start_login(self, **kwargs):
                raise InvalidCodeError('internal delegation is not a login provider')

            def complete_login(self, **kwargs):
                raise InvalidCodeError('internal delegation is not a login provider')

            def verify_session(self, *, access_token):
                grant = context.get()
                if grant is None or not hmac.compare_digest(access_token, grant['nonce']):
                    return None
                owner = grant['owner']
                # Preserve the original ticket principal, not an internal service
                # identity. No provider refresh/access credentials are copied.
                return Session(user_id=owner.user_id, provider=owner.provider, email='', display_name='',
                               org_id='', expires_at=int(time.time()) + 30, access_token='', refresh_token='')

            def refresh_session(self, **kwargs):
                raise RefreshExpiredError('delegation cannot refresh')

            def revoke_session(self, **kwargs):
                return None

        self.provider = DelegatedPrincipal()
        register_provider(self.provider)

    def owner(self, transport, profile, permission):
        from tui_gateway.ws import WSTransport
        from tui_gateway.methods_browser_control import _is_authenticated_identity
        if self._closed or not isinstance(transport, WSTransport) or transport.closed or not _is_authenticated_identity(transport.auth_identity):
            raise CapabilityError(401, 'server-authenticated WebSocket required')
        with self._lock:
            connection = self._connections.setdefault(transport, secrets.token_hex(16))
        return self.policy.authorize(transport.auth_identity, profile, permission, connection)

    async def invoke(self, call, owner, transport):
        # The production lease pins both the exact canonical home and its one
        # declared junction through original ASGI/service settlement. Legacy lab
        # policies have no profile-home namespace and retain their old behavior.
        from contextlib import nullcontext
        lease = self.policy.profile_home(owner) if hasattr(self.policy, 'profile_home') else nullcontext()
        with lease:
            return await settled_await(self._invoke_held(call, owner, transport))

    async def _invoke_held(self, call, owner, transport):
        if call.operation.path.endswith(('/stt-lease','/tts-lease')):
            raise CapabilityError(403,'provider engine leases withheld; relay transport does not expose engine authority')
        path = call.operation.path.format(**call.path_params)
        if call.path_params.get('name') and call.operation.source.endswith('profiles.py'):
            if call.path_params['name'] != owner.profile:
                raise CapabilityError(403, 'profile path owner mismatch')
        query = dict(call.query)
        body = dict(call.body) if isinstance(call.body, dict) else call.body
        if call.operation.profile_query:
            query['profile'] = owner.profile
        if call.operation.id == 'PATCH /api/sessions/{session_id}':
            body['profile'] = owner.profile
        if call.operation.id == 'PUT /api/config':
            body['profile'] = owner.profile
        if call.operation.id == 'GET /api/config':
            if query.get('include_defaults') is True:
                raise CapabilityError(403, 'effective config is not a renderer capability')
            query['include_defaults'] = False
        for location in call.operation.path_fields:
            scope, name = location.split('.')
            target = query if scope == 'query' else body
            if name not in target:
                raise CapabilityError(400, 'workspace path required')
            target[name] = self.policy.path(owner, target[name], relative_to=query.get('path') if name == 'file' else None)
        from .identifiers import guard_learning_mutation
        from .session_scope import SUPPORTED, guard_session_forwarding
        from .history import HISTORY_OPERATIONS
        guard_learning_mutation(call.operation.id, body)
        sid = call.path_params.get('session_id') or query.get('session_id')
        if call.operation.id not in SUPPORTED | HISTORY_OPERATIONS:
            guard_session_forwarding(call.operation.id, session_id=sid)
        # Lease IDs become server-derived owner-specific handles. A different
        # socket/profile cannot release an unrelated engine lease by guessing it.
        if call.operation.path.endswith('-lease'):
            body['lease'] = 'android-' + hashlib.sha256(repr((owner.key, body['lease'])).encode()).hexdigest()[:32]
        nonce = secrets.token_urlsafe(32)
        reservation = self.downloads.reserve(owner, transport) if call.operation.output == 'download' else None
        grant = {'nonce': nonce, 'owner': owner, 'transport': transport,
                 'operation': call.operation.id, 'call_query': dict(call.query)}
        dictating = call.operation.path == '/api/audio/transcribe' and self.dictation is not None
        if dictating:
            from .dictation_integration import request_context
            grant['dictation_context'] = request_context(self, owner, transport,
                deadline=self._admission_deadline.get())
        token = self._delegation.set(grant)
        try:
            request = self._asgi(path, call.operation.method, query, body, nonce,
                                 binary=call.operation.output == 'download')
            status, response, mime = await (settled_await(request) if dictating else request)
            if call.operation.output == 'download' and status < 300:
                stream, size = response
                result = self.downloads.put(owner, stream, size, mime, transport, reservation=reservation)
        finally:
            self._delegation.reset(token)
            if reservation is not None:
                self.downloads.cancel(reservation)
        if call.operation.path in ('/api/audio/transcribe','/api/audio/speak') and status>=300:
            return {'status':status,'body':{'detail':'audio relay service unavailable; outcome may be uncertain; do not retry automatically'}}
        if call.operation.path=='/api/audio/transcribe' and status<300:
            from .media import transcription_result
            return {'status':status,'body':transcription_result(response)}
        if call.operation.output == 'download' and status < 300:
            pass
        else:
            result = response
            projection = call.operation.result_projection
            from .projections import METADATA_PROJECTIONS, project_metadata
            if projection == 'startup':
                # Closed startup DTOs deliberately retain API_KEY-named
                # environment PRESENCE rows, never credential values/previews.
                return {'status': status, 'body': result if 200 <= status < 300 else {'detail': 'startup read unavailable'}}
            if projection in METADATA_PROJECTIONS:
                result = project_metadata(projection, result) if 200 <= status < 300 else {'detail': 'metadata service unavailable'}
                return {'status': status, 'body': result}
            if projection == 'settings' and status < 300:
                result = _settings(result)
            elif projection == 'mcp' and status < 300 and isinstance(result, dict):
                result = project_mcp(result)
            elif projection == 'profiles' and isinstance(result, dict):
                allowed = self.policy.profiles(owner)
                result = {'profiles': [p for p in result.get('profiles', []) if p.get('name') in allowed]}
            elif projection == 'files' and isinstance(result, dict):
                entries = []
                for item in result.get('entries', []):
                    try:
                        self.policy.path(owner, item['path'])
                        entries.append(item)
                    except (CapabilityError, KeyError):
                        continue
                result = {**result, 'entries': entries}
            result = redact(result)
        return {'status': status, 'body': result}

    async def complete_upload(self, owner, transport, handle):
        with self.uploads.claim(owner,handle,task=asyncio.current_task()) as item:
            permission = 'audio' if item['purpose']=='transcribe' else 'files.write'
            # Repeat the current principal/profile grant at authoritative use.
            current = self.owner(transport, owner.profile, permission)
            if current.key != owner.key or item['transport']() is not transport:
                raise CapabilityError(403, 'upload owner changed')
            owner = current
            if transport.closed or item['cancelled']:
                raise CapabilityError(410,'upload owner disconnected')
            nonce = secrets.token_urlsafe(32)
            grant = {'nonce':nonce, 'owner':owner, 'transport':transport, 'call_query':{},
                     'operation':'POST /api/audio/transcribe'}
            if item['purpose'] == 'transcribe' and self.dictation is not None:
                from .dictation_integration import request_context
                grant['dictation_context'] = request_context(self, owner, transport,
                    deadline=self._admission_deadline.get(), source='upload', item=item)
            token = self._delegation.set(grant)
            try:
                if item['purpose'].endswith('.attach'):
                    from .attachments import attach_upload
                    body = await settled_thread(attach_upload,self.server,self.policy,owner,transport,item)
                    return {'status':200,'body':redact(body)}
                if item['purpose']=='workspace':
                    target = self.policy.path(owner,item['path'])
                    boundary = 'pc-' + secrets.token_hex(24)
                    start = (f'--{boundary}\r\nContent-Disposition: form-data; name="path"\r\n\r\n{target}\r\n'
                        f'--{boundary}\r\nContent-Disposition: form-data; name="overwrite"\r\n\r\n{str(item["overwrite"]).lower()}\r\n'
                        f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="{item["filename"]}"\r\n'
                        f'Content-Type: {item["mimeType"]}\r\n\r\n').encode('utf-8')
                    end = f'\r\n--{boundary}--\r\n'.encode()
                    def chunks():
                        yield start
                        while data := item['file'].read(CHUNK_BYTES):
                            if item['cancelled'] or transport.closed:
                                raise CapabilityError(410,'upload cancelled before service read')
                            yield data
                        yield end
                    status,body,_ = await self._asgi('/api/files/upload-stream','POST',{},None,nonce,
                        wire=(chunks(),len(start)+item['byteSize']+len(end),'multipart/form-data; boundary='+boundary))
                else:
                    encoded = base64.b64encode(item['file'].read(item['byteSize']+1)).decode('ascii')
                    request = self._asgi('/api/audio/transcribe','POST',{'profile':owner.profile},
                        {'data_url':f'data:{item["mimeType"]};base64,{encoded}','mime_type':item['mimeType']},nonce)
                    status,body,_ = await (settled_await(request) if self.dictation is not None else request)
                if status>=300:
                    body = {'detail':'media service unavailable; do not retry automatically'}
                elif item['purpose']=='transcribe':
                    from .media import transcription_result
                    body=transcription_result(body)
                return {'status':status,'body':redact(body)}
            finally:
                self._delegation.reset(token)

    async def _asgi(self, path, method, query, body, nonce, *, binary=False, wire=None):
        """Invoke the original ASGI stack with a bounded streaming collector.

        Unlike httpx.ASGITransport this never joins an unlimited binary response.
        Auth is handled by the original cookie gate with a per-call context-only
        delegation nonce. These cookies exist ONLY in this in-process request.
        """
        raw_body = b'' if body is None else json.dumps(body, ensure_ascii=False, allow_nan=False).encode()
        content_length = len(raw_body) if wire is None else wire[1]
        content_type = 'application/json' if wire is None else wire[2]
        source = iter([raw_body]) if wire is None else iter(wire[0])
        query_text = urlencode({k: str(v).lower() if isinstance(v, bool) else v for k, v in query.items()})
        bound = getattr(self.app.state, 'bound_host', '127.0.0.1')
        scope = {'type': 'http', 'asgi': {'version': '3.0', 'spec_version': '2.3'}, 'http_version': '1.1',
                 'scheme': 'http', 'method': method, 'path': path, 'raw_path': path.encode('ascii'),
                 'query_string': query_text.encode('ascii'), 'root_path': '',
                 'client': ('127.0.0.1', 0), 'server': (bound, 80),
                 'headers': [(b'host', bound.encode('ascii')), (b'content-type', content_type.encode('ascii')),
                             (b'content-length', str(content_length).encode()),
                             (b'cookie', f'hermes_session_at={nonce}; hermes_session_provider={self.provider.name}'.encode())]}
        sent = False
        completed = asyncio.Event()
        chunks, status, mime, size = [], 500, 'application/octet-stream', 0
        spool = None

        async def receive():
            nonlocal sent
            if not sent:
                try:
                    data = next(source)
                    return {'type':'http.request','body':data,'more_body':True}
                except StopIteration:
                    sent = True
                    return {'type':'http.request','body':b'','more_body':False}
            await completed.wait()
            return {'type': 'http.disconnect'}

        async def send(message):
            nonlocal status, mime, size, spool
            if message['type'] == 'http.response.start':
                status = message['status']
                headers = dict(message.get('headers', ()))
                mime = headers.get(b'content-type', b'application/octet-stream').decode('latin-1')
                if binary and status < 300:
                    spool = tempfile.SpooledTemporaryFile(max_size=256 * 1024, dir=self.downloads.spool_dir, mode='w+b')
            elif message['type'] == 'http.response.body':
                data = message.get('body', b'')
                size += len(data)
                if size > (MAX_DOWNLOAD_BYTES if spool is not None else MAX_JSON_BYTES):
                    raise CapabilityError(413, 'upstream response size limit exceeded')
                if spool is not None:
                    spool.write(data)
                else:
                    chunks.append(data)
                if not message.get('more_body', False):
                    completed.set()

        try:
            await asyncio.wait_for(self.app(scope, receive, send), timeout=REQUEST_TIMEOUT)
            if not completed.is_set():
                raise CapabilityError(502, 'incomplete upstream response')
            if spool is not None:
                spool.seek(0)
                return status, (spool, size), mime
            try:
                result = json.loads(b''.join(chunks))
            except (ValueError, UnicodeError):
                raise CapabilityError(502, 'non-JSON upstream response') from None
            if status >= 500:
                # Provider failures can put an API key in exception text. Never
                # forward internal errors or logs to the renderer.
                result = {'detail': 'upstream service failed'}
            return status, result, mime
        except BaseException:
            if spool is not None:
                spool.close()
            raise

    async def _run_admitted(self, call, owner, transport, action=None):
        task = asyncio.current_task()
        self._tasks.add(task)
        writing = call.operation.method != 'GET'
        acquired = False
        deadline = time.monotonic() + REQUEST_TIMEOUT
        deadline_token = self._admission_deadline.set(deadline)
        async def monitor():
            while True:
                await asyncio.sleep(.05)
                if self._closed or transport.closed or time.monotonic() >= deadline:
                    task.cancel()
                    return
        watcher = asyncio.create_task(monitor())
        try:
            if self._closed or transport.closed:
                raise CapabilityError(410, 'capability owner disconnected')
            if writing:
                acquired = self._write_barrier.acquire(blocking=False)
                if not acquired:
                    raise CapabilityError(409, 'another write is settling; no automatic retry')
            return await (action() if action is not None else self.invoke(call, owner, transport))
        finally:
            watcher.cancel()
            await asyncio.gather(watcher, return_exceptions=True)
            if acquired:
                self._write_barrier.release()
            self._tasks.discard(task)
            self._admission_deadline.reset(deadline_token)
            self._slots.release()

    async def aclose(self):
        if self._closing is None:
            self._closing = asyncio.create_task(self._close_owned())
        # Repeated shutdown cancellation must not release owned provider cleanup.
        async def wait_closed():
            return await asyncio.shield(self._closing)
        await settled_await(wait_closed())

    async def _close_owned(self):
        self._closed = True
        self.uploads.close()
        self.downloads.close()
        tasks = tuple(self._tasks)
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        if self.dictation is not None:
            await self.dictation.aclose()
        from hermes_cli.dashboard_auth.registry import unregister_global_provider
        unregister_global_provider(self.provider.name, self.provider)

    def handler(self, rid, params):
        from tui_gateway.transport import current_transport
        try:
            call = validate_call(params)
            transport = current_transport()
            owner = self.owner(transport, call.profile, call.operation.permission)
            if not self._slots.acquire(blocking=False):
                raise CapabilityError(429, 'capability concurrency limit')
            try:
                future = asyncio.run_coroutine_threadsafe(self._run_admitted(call, owner, transport), transport._loop)
            except BaseException:
                self._slots.release()
                raise
            try:
                result = future.result(timeout=RPC_WAIT_TIMEOUT)
            except TimeoutError:
                future.cancel()
                raise CapabilityError(504, 'request deadline; write outcome may be uncertain; do not retry automatically') from None
            except FutureCancelledError:
                raise CapabilityError(504, 'request cancelled; write outcome may be uncertain; do not retry automatically') from None
            return self.server._ok(rid, result)
        except CapabilityError as exc:
            return self.server._ok(rid, {'status': exc.status, 'body': {'detail': exc.detail}})
        except Exception as exc:
            from fastapi import HTTPException
            if isinstance(exc, HTTPException):
                return self.server._ok(rid, {'status': exc.status_code, 'body': {'detail': redact(exc.detail)}})
            # No input, auth identity, exception, config or provider body logging.
            return self.server._ok(rid, {'status': 502, 'body': {'detail': 'capability service failed'}})

    def media_handler(self, rid, params, method):
        from tui_gateway.transport import current_transport
        from .media import BINARY_SCHEMAS
        try:
            validate_schema(params,BINARY_SCHEMAS[method],'params')
            transport=current_transport()
            if method=='desktop.audio.config':
                self.owner(transport,params['profile'],'audio')
                return self.server._ok(rid,{'status':200,'body':{'ok':True,
                    'stt':{'mode':'relay','streaming':False},'tts':{'mode':'relay','streaming':False}}})
            owner=self.owner(transport,params['profile'],'read')
            if method=='desktop.upload.begin':
                metadata={k:v for k,v in params.items() if k!='profile'}
                permission='audio' if metadata['purpose']=='transcribe' else 'files.write'
                owner=self.owner(transport,params['profile'],permission)
                if metadata['purpose']=='transcribe' and self.dictation is not None:
                    from .dictation_integration import request_context
                    context = request_context(self, owner, transport, deadline=time.monotonic()+REQUEST_TIMEOUT)
                    token = self._delegation.set({'owner':owner,'transport':transport})
                    try:
                        self.dictation.validate_upload_metadata(owner, metadata, context=context)
                    finally:
                        self._delegation.reset(token)
                if metadata['purpose']=='workspace':
                    metadata['path'] = self.policy.path(owner,metadata.get('path'))
                result={'status':200,'body':self.uploads.begin(owner,transport,metadata)}
            elif method=='desktop.upload.append':
                result={'status':200,'body':self.uploads.append(owner,params['uploadId'],params['offset'],
                    params['sequence'],params['dataBase64'])}
            elif method=='desktop.upload.release':
                result={'status':200,'body':self.uploads.release(owner,params['uploadId'])}
            else:
                if not self._slots.acquire(blocking=False):
                    raise CapabilityError(429,'capability concurrency limit')
                from .catalog import Call
                call=Call(OPERATIONS['POST /api/audio/transcribe'],owner.profile,{}, {},None)
                try:
                    future=asyncio.run_coroutine_threadsafe(self._run_admitted(call,owner,transport,
                        action=lambda:self.complete_upload(owner,transport,params['uploadId'])),transport._loop)
                except BaseException:
                    self._slots.release()
                    raise
                try:
                    result=future.result(timeout=RPC_WAIT_TIMEOUT)
                except (TimeoutError,FutureCancelledError):
                    future.cancel()
                    raise CapabilityError(504,'media request uncertain; do not retry automatically') from None
            return self.server._ok(rid,result)
        except CapabilityError as exc:
            return self.server._ok(rid,{'status':exc.status,'body':{'detail':exc.detail}})
        except Exception:
            return self.server._ok(rid,{'status':502,'body':{'detail':'media service failed; do not retry automatically'}})

    def download_handler(self, rid, params, *, release=False):
        from tui_gateway.transport import current_transport
        try:
            props = {'profile': PROFILE, 'downloadId': string(128)}
            if not release:
                props.update(offset=integer(0, MAX_DOWNLOAD_BYTES), length=integer(1, CHUNK_BYTES))
            validate_schema(params, obj(props, props), 'params')
            owner = self.owner(current_transport(), params['profile'], 'read')
            if release:
                body = self.downloads.release(owner, params['downloadId'])
            else:
                body = self.downloads.read(owner, params['downloadId'], params['offset'], params['length'])
            return self.server._ok(rid, {'status': 200, 'body': body})
        except CapabilityError as exc:
            return self.server._ok(rid, {'status': exc.status, 'body': {'detail': exc.detail}})


def install(app, server, policy, *, spool_dir):
    """Call once in a new runtime, before listener startup; never hot-patch a PC.

    The process must already have gated authentication enabled. Ownership policy
    is host-owned, not a renderer-supplied profile roster or credential object.
    """
    if not getattr(app.state, 'auth_required', False):
        raise ValueError('compatibility adapter requires authenticated gated runtime')
    if 'desktop.call' in server._methods:
        raise ValueError('desktop compatibility already installed')
    from typing import Any
    from tui_gateway.contracts.base import Params, Result
    from tui_gateway.contracts.registry import method

    class CallParams(Params):
        operation: str
        profile: str
        pathParams: dict[str, Any] | None = None
        query: dict[str, Any] | None = None
        body: Any = None

    class Reply(Result):
        status: int
        body: Any

    class DownloadParams(Params):
        profile: str
        downloadId: str
        offset: int
        length: int

    class ReleaseParams(Params):
        profile: str
        downloadId: str

    from pydantic import StrictStr, StrictInt, StrictBool
    class UploadBeginParams(Params):
        profile: StrictStr
        purpose: StrictStr
        filename: StrictStr
        mimeType: StrictStr
        byteSize: StrictInt
        path: StrictStr | None = None
        overwrite: StrictBool | None = None
        sessionId: StrictStr | None = None
        storedSessionId: StrictStr | None = None
    class UploadAppendParams(Params):
        profile: StrictStr
        uploadId: StrictStr
        offset: StrictInt
        sequence: StrictInt
        dataBase64: StrictStr
    class UploadHandleParams(Params):
        profile: StrictStr
        uploadId: StrictStr
    class AudioConfigParams(Params):
        profile: StrictStr

    adapter = Adapter(app, server, policy, spool_dir)
    method('desktop.call', params=CallParams, result=Reply, doc='Finite Android Desktop REST compatibility catalog.')
    method('desktop.download.read', params=DownloadParams, result=Reply, doc='Bounded owner-scoped binary chunk.')
    method('desktop.download.release', params=ReleaseParams, result=Reply, doc='Release an owner-scoped binary stream.')
    server.register_method('desktop.call', adapter.handler)
    server.register_method('desktop.download.read', adapter.download_handler)
    server.register_method('desktop.download.release', lambda rid, params: adapter.download_handler(rid, params, release=True))
    for name,model in {'desktop.upload.begin':UploadBeginParams,'desktop.upload.append':UploadAppendParams,
            'desktop.upload.complete':UploadHandleParams,'desktop.upload.release':UploadHandleParams,
            'desktop.audio.config':AudioConfigParams}.items():
        method(name,params=model,result=Reply,doc='Finite owner-scoped relay media transport.')
        server.register_method(name,lambda rid,params,name=name:adapter.media_handler(rid,params,name))
    server._LONG_HANDLERS = server._LONG_HANDLERS | {'desktop.call','desktop.upload.complete'}
    from contextlib import asynccontextmanager
    original_lifespan = app.router.lifespan_context
    @asynccontextmanager
    async def lifespan(application):
        async with original_lifespan(application) as state:
            try:
                yield state
            finally:
                await adapter.aclose()
    app.router.lifespan_context = lifespan
    return adapter
