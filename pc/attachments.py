"""Exact live attachment use; fixed profile/private owner namespace only.

No client filesystem path, title/prefix resolution, agent build or ambient
attachments.storage selection is permitted. Completed attachments are durable
agent inputs, not transport temporary files. Live and stored IDs stay distinct.
"""
from contextlib import contextmanager
import base64
import hashlib
from pathlib import Path
from .catalog import CapabilityError
from .filesystem import _write_parent, pin_paths
from .media_routes import clone

class Namespace:
    """Internal path policy for one host-selected home, never renderer authority."""
    def __init__(self,root): self.root=Path(root)
    def path(self,owner,raw):
        path=Path(raw)
        if not path.is_absolute() or not path.is_relative_to(self.root) or '..' in path.parts:
            raise CapabilityError(403,'private attachment namespace mismatch')
        return str(path)

@contextmanager
def exact_session(server,owner,transport,item,*,policy=None):
    from contextlib import nullcontext
    lease=policy.profile_home(owner) if hasattr(policy,'profile_home') else nullcontext(None)
    with lease as home:
        with _exact_session_held(server,owner,transport,item,canonical_home=home,policy=policy) as selected:
            yield selected

@contextmanager
def _exact_session_held(server,owner,transport,item,*,canonical_home=None,policy=None):
    from hermes_cli.web_routers.sessions import _history_profile_home
    from hermes_cli.web_server_sessions import _session_db_path_for_profile
    from hermes_state import SessionDB
    from .history import scoped_snapshot
    home=Path(canonical_home) if canonical_home is not None else Path(_history_profile_home(owner.profile))
    # _sessions_lock prevents a close/rebind between authorization and staging.
    with server._sessions_lock:
        session=server._sessions.get(item['sessionId'])
        if session is None:
            raise CapabilityError(404,'exact live session unavailable')
        live_home=Path(session.get('profile_home') or server._hermes_home)
        if canonical_home is not None:
            try:
                live_home=policy._runtime_home(owner.profile,live_home)
            except (ValueError,OSError):
                raise CapabilityError(403,'attachment live session home mismatch') from None
        # Ownership is the authenticated user, the stored session key and the profile home.
        # It is NOT socket identity: the phone opens a chat socket (creates the session) and a
        # separate capability socket (uploads), so the transports always differ. Each refusal
        # has its own text so a phone log shows which check failed.
        if session.get('session_key')!=item['storedSessionId']:
            raise CapabilityError(403,'attachment live session key mismatch')
        if session.get('auth_user_id')!=f'{owner.provider}:{owner.user_id}':
            raise CapabilityError(403,'attachment live session user mismatch')
        if live_home!=home:
            raise CapabilityError(403,'attachment live session profile home mismatch')
        path=home/'state.db' if canonical_home is not None else Path(_session_db_path_for_profile(owner.profile))
        if not path.exists():
            if session.get('parent_session_id'):
                raise CapabilityError(403,'attachment lineage unavailable')
            yield session,home
            return
        db=SessionDB(db_path=path,read_only=True)
        try:
            with scoped_snapshot(db,owner.profile) as view:
                conn=view._conn
                key=item['storedSessionId']
                exists=conn.execute('SELECT 1 FROM main.sessions WHERE id=?',(key,)).fetchone()
                if exists:
                    if conn.execute('SELECT 1 FROM sessions WHERE id=?',(key,)).fetchone() is None:
                        raise CapabilityError(403,'attachment connected ownership invalid')
                else:
                    if conn.execute('SELECT 1 FROM main.sessions WHERE parent_session_id=? LIMIT 1',(key,)).fetchone():
                        raise CapabilityError(403,'attachment draft has dangling descendants')
                    parent=session.get('parent_session_id')
                    if parent and conn.execute('SELECT 1 FROM sessions WHERE id=?',(parent,)).fetchone() is None:
                        raise CapabilityError(403,'attachment parent ownership invalid')
                yield session,home
        finally:
            db.close()


def attach_upload(server,policy,owner,transport,item):
    with exact_session(server,owner,transport,item,policy=policy) as (session,home):
        if item['cancelled'] or transport.closed:
            raise CapabilityError(410,'attachment cancelled before write')
        namespace=Namespace(home)
        root=home/('images' if item['purpose']=='image.attach' else 'attachments')
        owner_root=root/('android-'+hashlib.sha256(repr((owner.provider,owner.user_id)).encode()).hexdigest())
        for directory in (root,owner_root):
            with _write_parent(namespace,owner,directory.parent):
                directory.mkdir(exist_ok=True)
        with _write_parent(namespace,owner,owner_root):
            data=item['file'].read(item['byteSize']+1)
            if len(data)!=item['byteSize']:
                raise CapabilityError(400,'attachment spool size mismatch')
            if item['purpose']=='image.attach':
                # Pinned original decoding, allowed extensions, queue and DTO.
                raw=base64.b64encode(data).decode()
                decoded,error=server._decode_attach_payload(None,raw,mime_prefix='image/',
                    max_bytes=25*1024*1024,label='image',empty_msg='image is empty')
                ext=server._sniff_image_ext(decoded,item['filename']) if error is None else None
                if error is not None or ext not in server._allowed_image_extensions():
                    raise CapabilityError(400,'unsupported image bytes')
                queue=clone(server._queue_attached_image,_session_images_dir=lambda _:owner_root)
                target=queue(session,decoded,ext,prefix='upload')
                return server._attached_image_result(session,target,remainder='',
                    text=f'[User attached image: {target.name}]',bytes=len(decoded))
            stage=clone(server._stage_session_file_attachment,_session_home_dir=lambda *_:owner_root,
                _sanitize_attachment_name=lambda value:value)  # already strictly validated; never repair
            target,uploaded=stage(session,raw_path='',
                data_url=f'data:{item["mimeType"]};base64,'+base64.b64encode(data).decode(),name=item['filename'])
            ref_path=server._attachment_ref_path(session,target)
            return {'attached':True,'name':target.name,'path':str(target),'ref_path':ref_path,
                'ref_text':f'@file:{server._format_ref_value(ref_path)}','uploaded':uploaded}
