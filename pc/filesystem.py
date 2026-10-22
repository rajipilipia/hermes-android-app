"""Use-time local filesystem capabilities for the additive PC adapter.

Admission strings are not capabilities. On Windows, hold non-write/non-delete
sharing handles for EVERY ancestor and leaf, validate the opened object rather
than a previous stat, and keep the guard until the last read/stream chunk. Other
platforms fail closed until they have an equivalent openat/O_NOFOLLOW backend.
These guards do not defend against an administrator, kernel driver, or hostile
pre-existing writable memory mapping. They are not an OS sandbox.
"""
from __future__ import annotations

from contextlib import contextmanager, ExitStack
import os
from pathlib import Path
import stat

from .catalog import CapabilityError


@contextmanager
def _pin_windows_path(path, *, share=0x1, _profile_junction=False):
    """Private primitive; policy must authorize the caller's path separately."""
    if os.name != 'nt':
        raise CapabilityError(403, 'race-safe local filesystem backend unavailable')
    import ctypes
    from ctypes import wintypes

    class FileInformation(ctypes.Structure):
        _fields_ = [('attributes', wintypes.DWORD), ('created', wintypes.FILETIME),
                   ('accessed', wintypes.FILETIME), ('written', wintypes.FILETIME),
                   ('volume', wintypes.DWORD), ('size_high', wintypes.DWORD),
                   ('size_low', wintypes.DWORD), ('links', wintypes.DWORD),
                   ('index_high', wintypes.DWORD), ('index_low', wintypes.DWORD)]

    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
                                  wintypes.LPVOID, wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
    kernel.CreateFileW.restype = wintypes.HANDLE
    kernel.GetFileInformationByHandle.argtypes = [wintypes.HANDLE, ctypes.POINTER(FileInformation)]
    kernel.GetFileInformationByHandle.restype = wintypes.BOOL
    kernel.GetFinalPathNameByHandleW.argtypes = [wintypes.HANDLE, wintypes.LPWSTR, wintypes.DWORD, wintypes.DWORD]
    kernel.GetFinalPathNameByHandleW.restype = wintypes.DWORD
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel.CloseHandle.restype = wintypes.BOOL
    # GENERIC_READ (metadata-only access does NOT participate in Windows share
    # accounting), FILE_SHARE_READ only, OPEN_EXISTING,
    # FILE_FLAG_BACKUP_SEMANTICS | FILE_FLAG_OPEN_REPARSE_POINT. Read guards
    # disallow WRITE. The atomic-write parent guard allows WRITE only after a
    # held no-delete sentinel makes the directory nonempty (cannot set reparse).
    handle = kernel.CreateFileW(str(path), 0x80000000, share, None, 3, 0x02200000, None)
    if handle == wintypes.HANDLE(-1).value:
        raise CapabilityError(403, 'workspace path cannot be pinned')
    try:
        info = FileInformation()
        if not kernel.GetFileInformationByHandle(handle, ctypes.byref(info)):
            raise CapabilityError(403, 'workspace object cannot be verified')
        if info.attributes & 0x400:
            # Only BoundPolicy's separately authenticated, exact profiles-root
            # junction may use this private branch. Generic workspace paths
            # retain the unconditional no-reparse rule. OPEN_REPARSE_POINT and
            # read-only sharing hold the junction itself against rewrite/delete.
            if (not _profile_junction or not info.attributes & 0x10
                    or getattr(path.lstat(), 'st_reparse_tag', 0) != 0xA0000003):
                raise CapabilityError(403, 'linked path forbidden')
        elif _profile_junction:
            raise CapabilityError(403, 'declared profiles junction unavailable')
        if not info.attributes & 0x10 and info.links != 1:
            raise CapabilityError(403, 'hardlinked workspace file forbidden')
        buffer = ctypes.create_unicode_buffer(32768)
        size = kernel.GetFinalPathNameByHandleW(handle, buffer, len(buffer), 0)
        if not size or size >= len(buffer):
            raise CapabilityError(403, 'workspace object identity unavailable')
        final = buffer.value
        if final.startswith('\\\\?\\UNC\\'):
            raise CapabilityError(403, 'network filesystem path forbidden')
        if final.startswith('\\\\?\\'):
            final = final[4:]
        if Path(final) != path:
            raise CapabilityError(403, 'workspace object identity changed')
        yield info
    finally:
        kernel.CloseHandle(handle)


@contextmanager
def _pin_absolute(paths, *, share=0x1):
    """Open root-to-leaf so a checked parent cannot be swapped under a child."""
    with ExitStack() as stack:
        seen = set()
        for path in paths:
            path = Path(path)
            if not path.is_absolute():
                raise CapabilityError(403, 'absolute pinned path required')
            for component in (*reversed(path.parents), path):
                if component not in seen:
                    stack.enter_context(_pin_windows_path(component, share=share))
                    seen.add(component)
        yield


@contextmanager
def pin_paths(policy, owner, paths):
    """Reauthorize and pin existing paths through the entire original ASGI call.

    Missing files are 404; unsafe or unpinnable paths are 403. A caller needing
    creation must use atomic_write_text, not an unguarded upstream path-open.
    """
    targets = tuple(Path(policy.path(owner, raw)) for raw in paths)
    for target in targets:
        if not target.exists():
            raise CapabilityError(404, 'workspace path not found')
    with _pin_absolute(targets):
        for target in targets:
            if Path(policy.path(owner, str(target))) != target:
                raise CapabilityError(403, 'workspace object identity changed')
        yield targets


def read_bytes(policy, owner, raw, *, maximum, limit=None):
    """Bounded regular-file read while the path guard and opened file coexist."""
    with pin_paths(policy, owner, [raw]) as (target,):
        with target.open('rb') as handle:
            info = os.fstat(handle.fileno())
            if not stat.S_ISREG(info.st_mode):
                raise CapabilityError(400, 'regular workspace file required')
            if info.st_size > maximum:
                raise CapabilityError(413, 'file too large')
            data = handle.read(min(maximum, limit) + 1 if limit is not None else maximum + 1)
            if len(data) > (limit if limit is not None else maximum):
                if limit is None:
                    raise CapabilityError(413, 'file too large')
                data = data[:limit]
            return data, info.st_size, target


@contextmanager
def _write_parent(policy, owner, parent):
    """Keep each ancestor immovable and nonempty while allowing child rename.

    Windows MoveFileEx needs WRITE sharing on parent directory handles. Start
    with restrictive handles; pin an exclusive sentinel so the leaf parent
    cannot become empty/reparse; acquire RW-sharing/no-DELETE directory handles
    BEFORE releasing the restrictive ones. Every higher ancestor contains the
    next held directory. Never allow DELETE sharing on any directory handle.
    """
    import tempfile
    with ExitStack() as restrictive:
        restrictive.enter_context(pin_paths(policy, owner, [str(parent)]))
        fd, name = tempfile.mkstemp(prefix='.pc-guard-', dir=parent)
        os.close(fd)
        sentinel = Path(name)
        sentinel_guard = ExitStack()
        writable = False
        try:
            sentinel_guard.enter_context(_pin_windows_path(sentinel))
            with _pin_absolute([parent], share=0x3):
                writable = True
                restrictive.close()
                try:
                    yield
                finally:
                    sentinel_guard.close()
                    sentinel.unlink(missing_ok=True)
        finally:
            sentinel_guard.close()
            # If acquiring writable directory handles failed, the restrictive
            # stack still protects cleanup. Never attempt a second path delete
            # after the writable directory guard has been released.
            if not writable:
                sentinel.unlink(missing_ok=True)


@contextmanager
def _pin_owned_directory(path):
    """Private host-home lease: allow atomic child saves, never directory swaps.

    BoundPolicy authorizes the exact canonical home before this is entered.
    Reuse the existing held sentinel + RW/no-DELETE directory guard rather
    than pinning user config files or blocking their atomic replacement.
    """
    path = Path(path)
    class ExactDirectory:
        def path(self, _owner, raw):
            if Path(raw) != path:
                raise CapabilityError(403, 'declared profile directory differs')
            return str(path)
    with _write_parent(ExactDirectory(), None, path):
        yield


def atomic_write_text(policy, owner, raw, content):
    """Replace a leaf without following it; never reuse upstream's fixed tmp name.

    Parent handles prevent directory/junction replacement. An unpredictable,
    exclusively-created sibling is written through its fd, then os.replace
    changes the directory entry (not a symlink/hardlink's target). This is not
    compare-and-swap stale-editor detection; last successful writer wins.
    """
    import tempfile
    target = Path(policy.path(owner, raw))
    data = content.encode('utf-8')
    if len(data) > 8 * 1024 * 1024:
        raise CapabilityError(413, 'content too large')
    with _write_parent(policy, owner, target.parent):
        if target.exists() and not target.is_file():
            raise CapabilityError(400, 'regular workspace file required')
        descriptor, name = tempfile.mkstemp(prefix='.pc-write-', dir=target.parent)
        temporary = Path(name)
        try:
            with os.fdopen(descriptor, 'wb') as handle:
                handle.write(data)
                handle.flush()
            # Windows replacement does not follow a leaf reparse point. All
            # ancestors remain held, including the selected workspace root.
            os.replace(temporary, target)
        finally:
            temporary.unlink(missing_ok=True)
    return {'ok': True, 'path': str(target), 'byteSize': len(data)}


def _local_file_result(policy, owner, route, arguments):
    """Explicit host-local implementations, after original ASGI auth/validation.

    Never consult _fs_backend: a local grant is NOT a grant to an SSH machine.
    Upstream SSH backend selection cannot redirect one of these capabilities.
    """
    import base64
    from hermes_cli.web_routers import files
    from fastapi.responses import StreamingResponse

    if route in {'/api/files/mkdir', '/api/files/upload'}:
        raise CapabilityError(403, 'filesystem mutation withheld pending race-safe implementation')
    if route == '/api/fs/write-text':
        payload = arguments['payload']
        return atomic_write_text(policy, owner, payload.path, payload.content or '')
    raw = arguments['path']
    if route == '/api/fs/git-root':
        from .git_scope import repository_root
        return {'root': str(repository_root(policy, owner, raw))}
    if route == '/api/fs/list':
        with pin_paths(policy, owner, [raw]) as (target,):
            entries = []
            with os.scandir(target) as scan:
                for entry in scan:
                    if entry.name in files._FS_READDIR_HIDDEN:
                        continue
                    try:
                        child = policy.path(owner, entry.path)
                    except CapabilityError:
                        continue
                    entries.append({'name': entry.name, 'path': child,
                                    'isDirectory': entry.is_dir(follow_symlinks=False)})
                    if len(entries) > 10000:
                        raise CapabilityError(413, 'directory listing too large')
            entries.sort(key=lambda item: (not item['isDirectory'], item['name'].lower(), item['name']))
            return {'entries': entries}
    if route == '/api/fs/read-text':
        data, size, target = read_bytes(policy, owner, raw, maximum=files._FS_TEXT_SOURCE_MAX_BYTES,
                                        limit=files._FS_TEXT_PREVIEW_MAX_BYTES)
        return {'binary': files._fs_looks_binary(data[:4096]), 'byteSize': size,
                'language': files._FS_PREVIEW_LANGUAGE_BY_EXT.get(target.suffix.lower(), 'text'),
                'mimeType': files._fs_mime_type(target), 'path': str(target),
                'text': data.decode('utf-8', errors='replace'),
                'truncated': size > files._FS_TEXT_PREVIEW_MAX_BYTES}
    if route == '/api/fs/read-data-url':
        data, _size, target = read_bytes(policy, owner, raw, maximum=25 * 1024 * 1024)
        encoded = base64.b64encode(data).decode('ascii')
        return {'dataUrl': f'data:{files._fs_mime_type(target)};base64,{encoded}'}
    if route == '/api/fs/download':
        # Collect once under the held guard; a deferred FileResponse path-open
        # would recreate the race. Memory is explicitly bounded to the catalog
        # download ceiling; the adapter then spools/chunks these exact bytes.
        data, _size, target = read_bytes(policy, owner, raw, maximum=32 * 1024 * 1024)
        return StreamingResponse(iter([data]), media_type=files._fs_mime_type(target))
    raise CapabilityError(403, 'filesystem operation has no confined implementation')


def install_guarded_routes(app, policy, owner_getter):
    """Install once after router inclusion and before serving a NEW runtime.

    owner_getter MUST read the adapter's private per-call ContextVar (never
    params/request headers). With no delegated owner, normal REST is unchanged.
    The adapter must still invoke its original complete ASGI app: this replaces
    only APIRoute.dependant.call AFTER existing auth and request validation.
    It does not replace middleware or synthesize an identity. Session-bound
    file arguments still require the adapter's exact stored-session guard.
    """
    import asyncio
    from functools import wraps
    from fastapi import HTTPException
    if getattr(app.state, '_pc_path_guards_installed', False):
        raise ValueError('PC filesystem boundary already installed')
    guarded = {'/api/fs/list', '/api/fs/read-text', '/api/fs/read-data-url',
               '/api/fs/download', '/api/fs/write-text', '/api/fs/git-root',
               '/api/files/mkdir', '/api/files/upload'}
    from .catalog import OPERATIONS
    required = {operation.path for operation in OPERATIONS.values()
                if operation.source.endswith(('/files.py', '/git.py'))}
    available = {route.path for route in app.routes if hasattr(route, 'dependant')}
    if not required <= available:
        raise ValueError('include all original file/Git routes before installing PC boundary')
    installed = []
    def wrapper(original, path):
        @wraps(original)
        async def invoke(**arguments):
            owner = owner_getter()
            if owner is None:
                return await original(**arguments)
            try:
                if path.startswith('/api/git/'):
                    from .git_scope import git_read
                    from .addon import settled_thread
                    return await settled_thread(git_read, policy, owner, path, arguments)
                from .addon import settled_thread
                return await settled_thread(_local_file_result, policy, owner, path, arguments)
            except CapabilityError as exc:
                raise HTTPException(status_code=exc.status, detail=exc.detail) from None
            except OSError:
                raise HTTPException(status_code=403, detail='local workspace I/O unavailable') from None
        return invoke
    for route in app.routes:
        if hasattr(route, 'dependant') and (route.path in guarded or route.path.startswith('/api/git/')):
            route.dependant.call = wrapper(route.dependant.call, route.path)
            installed.append(route.path)
    app.state._pc_path_guards_installed = True
    return tuple(installed)
