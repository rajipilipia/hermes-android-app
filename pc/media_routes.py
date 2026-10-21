"""Private original-service composition after original ASGI auth and validation.

No module/global monkeypatches. Original multipart parser, upload helper and DTO
materializer are reused, with a held Windows workspace boundary through final
rename. Parents must already exist; no arbitrary mkdir authority is added.
"""
from __future__ import annotations
from contextlib import contextmanager
from functools import wraps
import io
import os
from pathlib import Path
import types
from .catalog import CapabilityError


def clone(function, **overrides):
    result = types.FunctionType(function.__code__, {**function.__globals__,**overrides},
                                function.__name__,function.__defaults__,function.__closure__)
    result.__kwdefaults__ = function.__kwdefaults__
    return result


def install_media_routes(app, policy, context_getter):
    from fastapi import HTTPException, UploadFile
    from hermes_cli.web_routers import files
    from .filesystem import _write_parent
    from .addon import settled_thread

    def wrapper(original, path):
        @wraps(original)
        async def invoke(**arguments):
            context = context_getter()
            if context is None:
                return await original(**arguments)
            owner = context['owner']
            if path=='/api/files/upload':
                payload = arguments['payload']
                # Original strict data-URL decoding and size checks.
                data,mime = files._decode_data_url(payload.data_url)
                file = UploadFile(io.BytesIO(data),filename=Path(payload.path).name)
                raw,overwrite = payload.path,payload.overwrite
            else:
                file = arguments['file']
                raw,overwrite = arguments['path'],arguments['overwrite']
            try:
                target = Path(policy.path(owner,raw))
                # The same guard as write-text; retain it across ALL original
                # streaming reads and rename, not merely admission.
                with _write_parent(policy,owner,target.parent):
                    if target.exists() and (not target.is_file() or not overwrite):
                        raise CapabilityError(409,'upload destination exists')
                    async def stream():
                        # Windows rename is exclusive when overwrite=false;
                        # unlike replace it cannot clobber a racing creator.
                        class ScopedOS:
                            def __getattr__(self,name): return getattr(os,name)
                            @staticmethod
                            def replace(source,destination):
                                if overwrite:
                                    os.replace(source,destination)
                                else:
                                    os.rename(source,destination)
                        write = clone(files.stream_upload_to_path,os=ScopedOS())
                        await write(file,target,too_large='File is too large',
                            not_writable='File is not writable',write_failed='Upload failed')
                    # Own the original coroutine through any cancellation; an
                    # uncertain rename cannot release its parent/write guard.
                    from .addon import settled_await
                    await settled_await(stream())
                    # Original metadata body, with ONLY the authorized root.
                    from types import SimpleNamespace
                    root = next(root for root in owner.roots if target.is_relative_to(root))
                    scoped = SimpleNamespace(root=root,locked_root=root,can_change_path=False)
                    return files._managed_write_result(scoped,target,str(target))
            except CapabilityError as exc:
                raise HTTPException(exc.status,detail=exc.detail) from None
            except OSError:
                raise HTTPException(403,detail='confined upload unavailable') from None
            finally:
                await file.close()
        return invoke
    def tts_wrapper(original):
        @wraps(original)
        async def invoke(**arguments):
            if context_getter() is None:
                return await original(**arguments)
            import base64
            import builtins
            from fastapi.responses import StreamingResponse
            from .addon import MAX_DOWNLOAD_BYTES
            from .filesystem import _pin_absolute
            @contextmanager
            def bounded_open(path,mode='rb'):
                target = Path(path)
                with _pin_absolute([target]):
                    with builtins.open(target,mode) as handle:
                        if os.fstat(handle.fileno()).st_size>MAX_DOWNLOAD_BYTES:
                            raise CapabilityError(413,'speech size limit exceeded')
                        class Bounded:
                            def read(self):
                                data = handle.read(MAX_DOWNLOAD_BYTES+1)
                                if len(data)>MAX_DOWNLOAD_BYTES:
                                    raise CapabilityError(413,'speech size limit exceeded')
                                return data
                        yield Bounded()
            # Keep original input validation, config scope, provider selection,
            # file deletion, MIME selection and result encoding. Only cap its
            # file read, then translate the bounded original JSON into bytes.
            try:
                result = await clone(original,open=bounded_open)(**arguments)
            except CapabilityError as exc:
                raise HTTPException(exc.status,detail='audio relay bounds exceeded') from None
            if set(result)-{'ok','data_url','mime_type','provider'} or not result.get('ok'):
                raise HTTPException(502,detail='invalid relay speech result')
            header,encoded = result['data_url'].split(',',1)
            data = base64.b64decode(encoded,validate=True)
            if len(data)>MAX_DOWNLOAD_BYTES or result['mime_type'] not in ('audio/mpeg','audio/ogg','audio/wav','audio/flac'):
                raise HTTPException(413,detail='invalid relay speech bytes')
            return StreamingResponse((data[n:n+65536] for n in range(0,len(data),65536)),media_type=result['mime_type'])
        return invoke

    for route in app.routes:
        if hasattr(route,'dependant') and route.path=='/api/audio/speak':
            route.dependant.call = tts_wrapper(route.endpoint)
        if hasattr(route,'dependant') and route.path in ('/api/files/upload','/api/files/upload-stream'):
            route.dependant.call = wrapper(route.endpoint,route.path)
