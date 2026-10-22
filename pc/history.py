"""Owner-scoped original SessionDB reads on one source-filtered SQLite snapshot.

TEMP views filter BEFORE original SQL aggregation, LIMIT, previews or hydration.
No persistent table is repaired/rewritten and no upstream aggregate is forwarded.
"""
from contextlib import closing, contextmanager
from pathlib import Path
import re
import time
from .catalog import CapabilityError
from .identifiers import canonical_profile
from .session_scope import _pinned_db

MAX_SCAN_ROWS = 20000


@contextmanager
def scoped_snapshot(db, profile):
    canonical_profile(profile)
    with db._read_ctx() as conn:
        if conn.in_transaction:
            raise CapabilityError(403, 'history snapshot must own its transaction')
        conn.execute('BEGIN')
        try:
            rows = conn.execute('SELECT id, parent_session_id, profile_name FROM main.sessions LIMIT ?',
                                (MAX_SCAN_ROWS + 1,)).fetchall()
            if len(rows) > MAX_SCAN_ROWS:
                raise CapabilityError(503, 'session store exceeds bounded ownership scan')
            by_id = {row['id']: row for row in rows}
            adjacency = {sid: set() for sid in by_id}
            bad = set()
            for sid, row in by_id.items():
                parent = row['parent_session_id']
                if row['profile_name'] != profile or not isinstance(sid, str) or re.fullmatch(
                        r'[A-Za-z0-9][A-Za-z0-9_-]{0,127}', sid) is None:
                    bad.add(sid)
                if parent:
                    if parent not in by_id:
                        bad.add(sid)
                    else:
                        adjacency[sid].add(parent)
                        adjacency[parent].add(sid)
            # Reject cyclic components too: original recursive compression CTEs
            # use UNION ALL and cannot be trusted to terminate on a cycle.
            visited = set()
            for start in by_id:
                if start in visited:
                    continue
                component, stack = set(), [start]
                while stack:
                    current = stack.pop()
                    if current in component:
                        continue
                    component.add(current)
                    stack.extend(adjacency[current] - component)
                visited.update(component)
                edges = sum(by_id[sid]['parent_session_id'] in component for sid in component)
                if len(component) > 4096:
                    raise CapabilityError(503, 'session lineage exceeds bounded ownership scan')
                if component & bad or edges >= len(component):
                    bad.update(component)
            conn.execute('CREATE TEMP TABLE pc_history_allowed (id TEXT PRIMARY KEY)')
            conn.executemany('INSERT INTO pc_history_allowed VALUES (?)',
                             ((sid,) for sid in by_id if sid not in bad))
            conn.execute('CREATE TEMP VIEW sessions AS SELECT s.* FROM main.sessions s '
                         'JOIN pc_history_allowed a ON a.id=s.id')
            # Keep messages' real indexes (original SQL uses INDEXED BY).
            # Every selected original reader joins scoped sessions or binds an
            # exact session ID derived from this authorized source view.
            view = _pinned_db(db, conn, write=False)
            view._conn = conn
            yield view
        finally:
            # TEMP DDL was created in this transaction: rollback drops every
            # request-local view/table as well as ending the main DB snapshot.
            if conn.in_transaction:
                conn.rollback()


def _list(view, profile, query, home):
    from hermes_cli.session_listing import subagent_listing_scope
    from hermes_cli.web_routers.profiles import _tag_rows
    from hermes_cli.web_server_gateway import _strip_session_list_rows
    csv = lambda value: [s.strip() for s in (value or '').split(',') if s.strip()]
    include_subagents, exclude = subagent_listing_scope(home, source=query.get('source'),
        sources=csv(query.get('sources')) or None, exclude_sources=csv(query.get('exclude_sources')) or None)
    filters = dict(source=query.get('source') or None, sources=csv(query.get('sources')) or None,
                   exclude_sources=exclude, min_message_count=query.get('min_messages', 0),
                   include_archived=query.get('archived') == 'include',
                   archived_only=query.get('archived') == 'only', include_subagents=include_subagents)
    limit, offset = query.get('limit', 20), query.get('offset', 0)
    rows = view.list_sessions_rich(limit=limit, offset=offset,
        order_by_last_active=query.get('order', 'created') == 'recent', compact_rows=True,
        include_pinned=True, **filters)
    _tag_rows(rows, profile, time.time())
    _strip_session_list_rows(rows)
    return {'sessions': rows, 'total': view.session_count(exclude_children=True, **filters),
            'limit': limit, 'offset': offset, 'storage': {}}


def _clone(original, **bindings):
    """Private function composition; never mutate upstream module globals."""
    from types import FunctionType
    from inspect import unwrap
    original = unwrap(original)
    cloned = FunctionType(original.__code__, {**original.__globals__, **bindings},
                          original.__name__, original.__defaults__, original.__closure__)
    cloned.__kwdefaults__ = original.__kwdefaults__
    return cloned


def read_targets(operation, targets, query, *, errors=None):
    """Original aggregate DTO with host-selected, snapshot-filtered sources only.

    No shared upstream sidebar cache is consulted or populated: grant/owner
    identity cannot accidentally alias a process-wide profile DB cache key.
    """
    from contextlib import ExitStack
    from hermes_cli.web_routers import profiles
    failures = list(errors or [])
    with ExitStack() as stack:
        views = {}
        for name, (db, home) in targets.items():
            canonical_profile(name)
            if db is None:
                continue
            try:
                views[name] = stack.enter_context(scoped_snapshot(db, name))
            except Exception:
                failures.append({'profile': name, 'error': 'session store unavailable'})
        def read(name, home, service_errors, fn):
            if name not in views:
                for failure in failures:
                    if failure['profile'] == name:
                        service_errors.append(dict(failure))
                return None
            try:
                return fn(views[name])
            except Exception:
                service_errors.append({'profile': name, 'error': 'session store unavailable'})
                return None
        failed_names = {row['profile'] for row in failures}
        class DeclaredStore:
            def __init__(self, home):
                self.home = home
            def exists(self):
                return any(home == self.home and (db is not None or name in failed_names)
                           for name, (db, home) in targets.items())
            def __str__(self):
                return str(self.home / 'state.db')
        bindings = dict(_profile_targets=lambda label: [(name, home) for name, (_, home) in targets.items()],
                        _profile_state_db=DeclaredStore,
                        _sidebar_db_fingerprint=lambda path: None,
                        _read_profile_db=read, _sidebar_profile_cache_get=lambda key: None,
                        _sidebar_profile_cache_put=lambda *args: None,
                        _sidebar_profile_cache_drop=lambda key: None,
                        _profile_heal_exhausted=lambda home: False)
        if operation == 'GET /api/profiles/sessions/sidebar':
            service = _clone(profiles.get_profiles_sessions_sidebar, **bindings)
        elif operation == 'GET /api/profiles/sessions':
            # Force the private service's enumerator branch even for one
            # selected profile: only the pre-authorized target map is visible.
            service = _clone(profiles.get_profiles_sessions, **bindings)
            query = {'limit': 20, 'offset': 0, **query, 'profile': 'all'}
        else:
            raise CapabilityError(403, 'aggregate operation not integrated')
        return service(**query)


HISTORY_OPERATIONS = frozenset({'GET /api/sessions', 'GET /api/sessions/search',
    'GET /api/profiles/sessions', 'GET /api/profiles/sessions/sidebar'})


def execute_history(operation, owner, query, policy):
    from contextlib import ExitStack
    from .catalog import OPERATIONS, validate_schema
    from hermes_cli.web_server_sessions import _session_db_path_for_profile
    from hermes_state import SessionDB
    canonical_profile(owner.profile)
    if policy.authorize({'provider': owner.provider, 'user_id': owner.user_id}, owner.profile,
                        'read', owner.connection) != owner:
        raise CapabilityError(403, 'history owner does not match host grant')
    if operation not in HISTORY_OPERATIONS:
        raise CapabilityError(404, 'unlisted history operation')
    validate_schema(query, OPERATIONS[operation].query, 'query')
    aggregate = operation.startswith('GET /api/profiles/')
    selector = query.get('recents_profile' if operation.endswith('/sidebar') else 'profile', owner.profile)
    if not aggregate:
        selector = owner.profile
    if selector != 'all':
        canonical_profile(selector)
        names = [selector]
    else:
        names = sorted(name for name in policy.profiles(owner)
                       if 'read' in policy._grants[(owner.provider, owner.user_id, name)][1])
    if len(names) > 32:
        raise CapabilityError(413, 'too many granted profile stores for one read')
    # Authorize every target before path lookup: selectors never confer grants.
    for name in names:
        policy.authorize({'provider': owner.provider, 'user_id': owner.user_id}, name, 'read', owner.connection)
    with ExitStack() as stack:
        targets, errors = {}, []
        for name in names:
            home_guard = getattr(policy, 'profile_home', None)
            if home_guard is not None:
                selected_owner = policy.authorize({'provider': owner.provider, 'user_id': owner.user_id},
                                                  name, 'read', owner.connection)
                home = stack.enter_context(home_guard(selected_owner))
                path = home / 'state.db'
            else:
                from hermes_cli.profiles import get_profile_dir
                home = get_profile_dir(name)
                path = Path(_session_db_path_for_profile(name))
            try:
                db = stack.enter_context(closing(SessionDB(db_path=path, read_only=True))) if path.is_file() else None
                targets[name] = (db, path.parent)
            except Exception:
                # Scope-static errors: no raw DB paths, exception text or
                # foreign-profile names can enter this DTO.
                targets[name] = (None, home)
                errors.append({'profile': name, 'error': 'session store unavailable'})
        if aggregate:
            selected = dict(query)
            if operation.endswith('/sidebar'):
                selected['recents_profile'] = 'all'
            return read_targets(operation, targets, selected, errors=errors)
        db, home = targets[owner.profile]
        if errors:
            raise CapabilityError(503, 'session store unavailable')
        if db is None:
            if operation.endswith('/search'):
                return {'results': []}
            return {'sessions': [], 'total': 0, 'limit': query.get('limit', 20),
                    'offset': query.get('offset', 0), 'storage': {}}
        return read_on_db(db, operation, owner.profile, query, home=home)


def read_on_db(db, operation, profile, query, *, home):
    with scoped_snapshot(db, profile) as view:
        if operation == 'GET /api/sessions':
            return _list(view, profile, query, home)
        if operation == 'GET /api/sessions/search':
            import asyncio
            from hermes_cli.web_routers.sessions import search_sessions
            service = _clone(search_sessions,
                _with_db=lambda selected, fn, **kw: fn(view),
                _serving_profile=lambda selected: profile)
            return asyncio.run(service(profile=profile, **query))
        raise CapabilityError(403, 'history operation not integrated')
