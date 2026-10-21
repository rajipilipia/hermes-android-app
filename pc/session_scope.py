"""Exact, transactional session authority for the pinned upstream SessionDB.

The adapter must REPLACE the old preflight+REST forwarding for supported exact
session operations with execute_session_call. Never call this as a preflight
then invoke the original prefix/title endpoint: its return is the final DTO.
Original DB read/materialization, title validation and flag setters are reused
on the SAME held snapshot/write transaction as ownership authorization. No
upstream globals or original DB instance methods are patched.

Deliberately conservative: every parent/descendant-connected row must have the
exact owner (NULL legacy rows are withheld). Exact timeline/around reuse original
readers on this snapshot. Lists/search/sidebar are separately integrated by
pc.history's source-filtered snapshots; unsafe direct forwarding stays denied.
Session-dependent file reads remain withheld. Not full Desktop session parity.
"""
from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
import re

from .catalog import CapabilityError, OPERATIONS, validate_schema
from .identifiers import canonical_profile

SUPPORTED = frozenset({'GET /api/sessions/{session_id}',
                       'GET /api/sessions/{session_id}/messages',
                       'GET /api/sessions/{session_id}/timeline',
                       'GET /api/sessions/{session_id}/messages/around',
                       'PATCH /api/sessions/{session_id}'})
WITHHELD = frozenset({'GET /api/sessions', 'GET /api/sessions/search',
                      'GET /api/profiles/sessions'})
MAX_COMPONENT_ROWS = 4096

_COMPONENT_SQL = '''WITH RECURSIVE component(id) AS (
    SELECT id FROM sessions WHERE id = ?
    UNION
    SELECT s.parent_session_id FROM sessions s JOIN component c ON s.id = c.id
      WHERE s.parent_session_id IS NOT NULL
    UNION
    SELECT s.id FROM sessions s JOIN component c ON s.parent_session_id = c.id
) SELECT s.id, s.profile_name FROM sessions s JOIN component c ON s.id = c.id LIMIT ?'''


def guard_session_forwarding(operation, *, session_id=None):
    """Reject unsafe original forwarding; supported ops MUST use final scoped DTO."""
    if operation in SUPPORTED or operation in WITHHELD or session_id is not None:
        raise CapabilityError(403, 'session forwarding withheld; authoritative exact scoped service required')


def _component(conn, session_id, profile):
    if conn.execute('SELECT 1 FROM sessions WHERE id = ?', (session_id,)).fetchone() is None:
        raise CapabilityError(404, 'exact session not found in owner profile')
    rows = conn.execute(_COMPONENT_SQL, (session_id, MAX_COMPONENT_ROWS + 1)).fetchall()
    if len(rows) > MAX_COMPONENT_ROWS:
        raise CapabilityError(403, 'session ownership component exceeds safe bound')
    if any(row['profile_name'] != profile for row in rows):
        raise CapabilityError(403, 'every lineage/descendant row must have the exact owning profile')
    return frozenset(row['id'] for row in rows)


def _pinned_db(original, conn, *, write):
    """Per-call view of the ORIGINAL DB class, pinned to its caller-held connection.

    SessionDB mixins call self._read_ctx/_read_retrying_ioerr/_execute_write;
    binding these on a separate view prevents pooled-read escape/nested commits.
    The original object and its shared registry/thread state remain untouched.
    No token counters are flushed from the view: this is a private service read,
    and flushing a shared buffer would be an unrelated write outside its scope.
    """
    class PinnedView(type(original)):
        # A view does not own the copied underlying handle/registry state.
        def close(self):
            pass

        def __del__(self):
            pass

    view = object.__new__(PinnedView)
    view.__dict__.update(original.__dict__)
    view.read_only = not write

    @contextmanager
    def read_ctx():
        yield conn

    def execute_write(fn, patience_s=None):
        if not write:
            raise CapabilityError(403, 'read-only session snapshot cannot mutate')
        return fn(conn)

    view._read_ctx = read_ctx
    view._read_retrying_ioerr = lambda fn: fn(conn)
    view._execute_write = execute_write
    view.flush_token_counts = lambda: None
    # Historical resolvers are replaced, not preflighted: an absent exact id
    # remains absent, even if an owned/foreign prefix or title would match.
    view.resolve_session_id = lambda value: value if conn.execute(
        'SELECT 1 FROM sessions WHERE id = ?', (value,)).fetchone() else None
    return view


def execute_on_db(db, operation, profile, session_id, *, query=None, body=None, home=None):
    """Final scoped DTO using an actual upstream DB; no endpoint forwarding follows.

    db must be an upstream SessionDB (or subclass), not an arbitrary service
    supplied by a remote caller. The host chooses it for the authorized profile.
    Ownership and service use share one read transaction or BEGIN IMMEDIATE.
    """
    canonical_profile(profile)
    if operation not in SUPPORTED:
        raise CapabilityError(403, 'session operation withheld: no exact transactional service integration')
    if not isinstance(session_id, str) or re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]{0,127}', session_id) is None:
        raise CapabilityError(400, 'exact stored session id required')
    query = {} if query is None else query
    validate_schema(query, OPERATIONS[operation].query, 'query')
    if operation.startswith('PATCH '):
        validate_schema(body, OPERATIONS[operation].body, 'body')
    elif body is not None:
        raise CapabilityError(400, 'read operation has no body')
    write = operation.startswith('PATCH ')

    def apply(conn):
        allowed = _component(conn, session_id, profile)
        view = _pinned_db(db, conn, write=write)
        if operation == 'GET /api/sessions/{session_id}':
            session = view.get_session(session_id)
            return {**session, 'profile': profile, 'is_default_profile': profile == 'default'}
        if write:
            if not body:
                raise CapabilityError(400, 'provide title or a session flag')
            if 'title' in body:
                title = view.sanitize_title(body['title'])
                if title:
                    # Upstream rename can retire a conflicting empty/archived
                    # row. Never let that touch a different ownership component.
                    conflict = conn.execute('SELECT id FROM sessions WHERE title = ? AND id != ?',
                                            (title, session_id)).fetchone()
                    if conflict and conflict['id'] not in allowed:
                        raise CapabilityError(403, 'title conflict lies outside authorized session component')
                try:
                    view.set_session_title(session_id, body['title'])
                except ValueError:
                    raise CapabilityError(400, 'upstream session title validation failed') from None
            result = {'ok': True, 'title': None}
            setters = {'archived': view.set_session_archived, 'hidden': view.set_session_hidden,
                       'pinned': view.set_session_pinned,
                       'unread': lambda sid, value: view.set_session_read(sid, read=not value)}
            for flag, setter in setters.items():
                if flag in body:
                    setter(session_id, body[flag])
                    result[flag] = body[flag]
            result['title'] = view.get_session_title(session_id) or ''
            return result
        tip = view.resolve_resume_session_id(session_id)
        # Belt and braces: no resolver/mixin may silently escape the component.
        lineage = view._resume_lineage_ids(tip)
        if tip not in allowed or not set(lineage) <= allowed:
            raise CapabilityError(403, 'resolved session escaped authorized component')
        if operation.endswith('/timeline') or operation.endswith('/messages/around'):
            # Original timeline readers own BEGIN/ROLLBACK internally. Their
            # private connection facade borrows this already-held transaction;
            # it must never end the authorization snapshot before hydration.
            class BorrowedSnapshot:
                def execute(self, sql, *args):
                    if sql.strip().upper() in {'BEGIN', 'ROLLBACK'}:
                        return conn.execute('SELECT 1')
                    return conn.execute(sql, *args)
                def __getattr__(self, name):
                    return getattr(conn, name)
            @contextmanager
            def borrowed():
                yield BorrowedSnapshot()
            view._read_ctx = borrowed
            if operation.endswith('/timeline'):
                from hermes_state_timeline import get_session_timeline
                page = get_session_timeline(view, tip, limit=query.get('limit', 500),
                                             after_row_id=query.get('after_row_id', 0))
            else:
                from hermes_state_timeline import get_session_messages_around
                page = get_session_messages_around(view, tip, query['row_id'], limit=query.get('limit', 120))
                if page is None:
                    raise CapabilityError(404, 'exact prompt not found in owner session')
            return {'session_id': tip, 'profile': profile, **page}
        limit, offset = query.get('limit', 500), query.get('offset', 0)
        order = query.get('order', 'latest' if 'limit' not in query else 'oldest')
        messages = view.get_messages(tip, limit=limit, offset=offset, latest=order == 'latest',
                                     include_compacted=query.get('include_compacted', False), include_ancestors=True)
        return {'session_id': tip, 'profile': profile, 'messages': messages,
                'pagination': {'limit': limit, 'offset': offset, 'order': order, 'returned': len(messages)}}

    if write:
        # Upstream owns the write lock, retry discipline and settlement. Nested
        # original setter callbacks run directly on this same connection.
        result = db._execute_write(apply)
    else:
        with db._read_ctx() as conn:
            if conn.in_transaction:
                raise CapabilityError(403, 'session snapshot must own its transaction')
            conn.execute('BEGIN')
            try:
                result = apply(conn)
            finally:
                if conn.in_transaction:
                    conn.rollback()
    if operation.endswith('/messages') or operation.endswith('/messages/around'):
        from hermes_cli.web_routers.sessions import _project_for_display
        result['messages'] = _project_for_display(result['messages'], home=home,
                                                  inline_images=query.get('inline_images', True))
        result['pagination']['returned'] = len(result['messages'])
    return result


def execute_session_call(operation, profile, session_id, *, query=None, body=None):
    """Production hook after host authorization; synchronous (run with to_thread).

    The exact profile DB path is selected once. There is no caller-provided DB
    path and no prefix/title fallback. Unknown/aggregate operations refuse 403.
    Parent adapter wraps the final DTO in {status:200,body:...} and redacts it.
    """
    canonical_profile(profile)
    if operation not in SUPPORTED:
        raise CapabilityError(403, 'session operation withheld: no exact transactional service integration')
    from hermes_cli.web_server_sessions import _session_db_path_for_profile
    from hermes_cli.web_routers.sessions import _history_profile_home
    from hermes_state import SessionDB
    path = Path(_session_db_path_for_profile(profile))
    if not path.is_file():
        raise CapabilityError(404, 'exact session store not found')
    db = SessionDB(db_path=path, read_only=not operation.startswith('PATCH '))
    try:
        return execute_on_db(db, operation, profile, session_id, query=query, body=body,
                             home=_history_profile_home(profile))
    finally:
        db.close()
