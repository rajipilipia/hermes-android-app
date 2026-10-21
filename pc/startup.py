"""Finite startup read composition for an already authorized Desktop request.

Call execute_startup INSIDE the original route dependant, after original ASGI
middleware and FastAPI parameter validation. Nondelegated requests must keep
calling the original dependant. This module does not install or retarget routes.
"""
from __future__ import annotations

import asyncio
from concurrent.futures import Future
from contextvars import copy_context
import threading

from .catalog import BOOL, CapabilityError, SETTINGS, obj, validate_schema
from .projections import (_OMIT, _array, _boolean, _enum, _integer, _named_map, _nullable,
                          _number, _object, _text)

# Catalog input contract: the host decodes HTTP 0/1 to JSON booleans, never
# truthy strings. There is no caller profile selector inside query.
STARTUP_QUERIES = {
    'GET /api/status': obj(), 'GET /api/profiles/active': obj(),
    'GET /api/config/defaults': obj(), 'GET /api/fs/default-cwd': obj(),
    'GET /api/config/schema': obj(), 'GET /api/env': obj(),
    'GET /api/model/options': obj({'explicit_only': BOOL, 'include_unconfigured': BOOL, 'refresh': BOOL}),
}
STARTUP_OPERATIONS = frozenset(STARTUP_QUERIES)

_PICKER_CAPABILITIES = _object({'fast': _boolean, 'ultrafast': _boolean,
                                'reasoning': _boolean, 'can_disable_reasoning': _nullable(_boolean)})
_PICKER_PRICING = _object({'input': _text, 'output': _text, 'cache': _nullable(_text),
                          'free': _boolean, 'discount_percent': _nullable(_number),
                          'was_input': _nullable(_text), 'was_output': _nullable(_text)})
_PICKER_PROVIDER = _object({
    'slug': _text, 'name': _text, 'models': _array(_text), 'total_models': _integer,
    'is_current': _boolean, 'is_user_defined': _boolean, 'source': _text,
    'aliases': _array(_text), 'auth_type': _text, 'authenticated': _boolean,
    'key_env': _text, 'featured_models': _array(_text),
    'capabilities': _named_map(_PICKER_CAPABILITIES), 'pricing': _named_map(_PICKER_PRICING),
    'pricing_pending': _boolean, 'free_tier': _boolean, 'free_tier_pending': _boolean,
    'free_tier_row': _boolean, 'unavailable_models': _array(_text),
    'limit': _object({'scope': _enum('account', 'models'), 'resets_at': _nullable(_text),
                      'models': _named_map(_text)}),
})
_PICKER = _object({'model': _text, 'provider': _text, 'providers': _array(_PICKER_PROVIDER)})

_GATEWAY_STATE = _nullable(_enum('starting', 'running', 'draining', 'stopped',
                                 'degraded', 'startup_failed'))
_PLATFORM_STATE = _enum('connected', 'connecting', 'running', 'ok', 'disabled',
                        'stopped', 'disconnected', 'degraded', 'fatal', 'error',
                        'starting', 'reconnecting', 'pending')
_PLATFORM = _object({'state': _PLATFORM_STATE, 'status': _PLATFORM_STATE})
_STATUS = _object({
    'version': _text, 'release_date': _text, 'config_version': _integer,
    'latest_config_version': _integer, 'gateway_running': _boolean,
    'gateway_state': _GATEWAY_STATE, 'gateway_updated_at': _nullable(_text),
    'gateway_heartbeat_stale_s': _nullable(_number),
})

_ENV_PROFILE = _object({'provider': _text, 'provider_label': _text,
                        'description': _text, 'primary': _boolean})
_ENV_ROW = _object({
    'is_set': _boolean, 'is_password': _boolean, 'advanced': _boolean,
    'channel_managed': _boolean, 'provider_primary': _boolean, 'custom': _boolean,
    'category': _text, 'description': _text, 'provider': _text, 'provider_label': _text,
    'tools': _array(_text), 'provider_profiles': _array(_ENV_PROFILE),
})

_SCHEMA_FIELD = _object({
    'type': _enum('boolean', 'list', 'number', 'select', 'string', 'text'),
    'category': _enum(*SETTINGS['properties']), 'description': _text,
    'options': _array(_text), 'searchable': _boolean, 'clearable': _boolean,
})


def _schema(value):
    fields = {}
    original = value.get('fields', {}) if isinstance(value, dict) else {}
    for category, spec in SETTINGS['properties'].items():
        for leaf in spec['properties']:
            name = category + '.' + leaf
            row = _SCHEMA_FIELD(original.get(name))
            if row is not _OMIT and 'type' in row:
                fields[name] = row
    return {'fields': fields, 'category_order': [name for name in value.get('category_order', [])
                                                if name in SETTINGS['properties']]}


def _settings(value, schema=SETTINGS):
    if not isinstance(value, dict):
        return {}
    result = {}
    for name, child in schema['properties'].items():
        if name not in value:
            continue
        if child['type'] == 'object':
            result[name] = _settings(value[name], child)
        else:
            try:
                validate_schema(value[name], child)
            except CapabilityError:
                continue
            if child['type'] == 'string' and _text(value[name]) is _OMIT:
                continue
            result[name] = value[name]
    return result


_PICKER_TIMEOUT_SECONDS = 8.0
_picker_lock = threading.Lock()
_picker_pending = 0


async def _model_options(profile, query, *, policy=None, owner=None):
    """Bound cold-cache/provider latency, retaining admission until settlement.

    Original picker cache refresh/warm behavior is preserved, not a claim of an
    offline API. Timeouts do not kill Python threads or roll back upstream cache
    work. At most two admitted original foreground builds may remain unsettled.
    """
    from hermes_cli.web_routers.models import get_model_options
    global _picker_pending
    with _picker_lock:
        if _picker_pending >= 2:
            raise CapabilityError(429, 'startup picker is settling')
        _picker_pending += 1
    future = Future()
    context = copy_context()

    def run():
        global _picker_pending
        try:
            # Own the loop until all original foreground work has really
            # settled; cancelling a client await never cancels this worker.
            from contextlib import nullcontext
            lease = (policy.profile_home(owner) if policy is not None
                     and hasattr(policy, 'profile_home') else nullcontext())
            # This worker can outlive the client deadline. It, not the waiter,
            # owns the home/junction lease until original provider work settles.
            with lease:
                value = context.run(asyncio.run, get_model_options(profile=profile, **query))
        except BaseException as error:
            future.set_exception(error)
        else:
            future.set_result(value)
        finally:
            with _picker_lock:
                _picker_pending -= 1
    try:
        threading.Thread(target=run, name='pc-startup-picker', daemon=True).start()
    except BaseException:
        with _picker_lock:
            _picker_pending -= 1
        raise
    wrapped = asyncio.wrap_future(future)
    # Retrieve eventual errors even if the request timed out or disconnected.
    wrapped.add_done_callback(lambda done: None if done.cancelled() else done.exception())
    try:
        return await asyncio.wait_for(asyncio.shield(wrapped), _PICKER_TIMEOUT_SECONDS)
    except TimeoutError:
        raise CapabilityError(504, 'startup picker deadline exceeded; original read is settling') from None


async def execute_startup(operation, owner, query, policy):
    """Original-shaped allowlisted body, or a static CapabilityError.

    Integrate only inside the original route dependant after authentication and
    original argument validation. Do not pass the injected ``profile`` through
    ``query``: the Owner alone supplies profile authority.
    """
    from fastapi import HTTPException
    try:
        return await _execute_startup(operation, owner, query, policy)
    except HTTPException as error:
        raise CapabilityError(error.status_code, 'startup read unavailable') from None


async def _execute_startup(operation, owner, query, policy):
    # The route wrapper already authorized the call. Recheck the immutable
    # capability here so direct/internal composition cannot widen it.
    from .identifiers import canonical_profile
    canonical_profile(owner.profile)
    granted = policy.authorize({'provider': owner.provider, 'user_id': owner.user_id},
                               owner.profile, 'read', owner.connection)
    if granted != owner:
        raise CapabilityError(403, 'startup owner does not match host grant')
    if operation not in STARTUP_OPERATIONS:
        raise CapabilityError(404, 'unlisted startup operation')
    validate_schema(query, STARTUP_QUERIES[operation])
    if operation == 'GET /api/model/options':
        original = await _model_options(owner.profile, query, policy=policy, owner=owner)
        result = _PICKER(original)
        if result is _OMIT or 'providers' not in result:
            raise CapabilityError(502, 'invalid startup picker metadata')
        result['providers'] = [row for row in result['providers'] if 'slug' in row and 'name' in row]
        return result
    if operation == 'GET /api/status':
        import re
        from hermes_cli import __release_date__
        from hermes_cli.config import check_config_version
        from hermes_cli.version_info import get_version_info
        from hermes_cli.web_server_profiles import _config_profile_scope, _resolve_profile_dir
        from hermes_cli.web_routers.status import _resolve_gateway_status
        # Deliberately compose the original local liveness ladder, not the
        # whole machine-level handler: that scans ungranted topology, counts
        # other owners, probes a health URL and may persist an install identity.
        directory = _resolve_profile_dir(owner.profile)
        with _config_profile_scope(owner.profile):
            current, latest = check_config_version()
            gateway = await _resolve_gateway_status(directory, None)
        result = _STATUS({**gateway, 'version': get_version_info().base_version,
                          'release_date': __release_date__, 'config_version': current,
                          'latest_config_version': latest})
        platforms = {}
        for key, value in gateway.get('gateway_platforms', {}).items():
            if not isinstance(key, str):
                continue
            if ':' in key:
                profile, _, key = key.partition(':')
                if profile != owner.profile:
                    continue
            if re.fullmatch(r'[a-z0-9][a-z0-9_-]{0,63}', key):
                row = _PLATFORM(value)
                if row is not _OMIT:
                    platforms[key] = row
        result['gateway_platforms'] = platforms
        return result
    if operation == 'GET /api/profiles/active':
        # Original sticky/default state is process-wide, not this caller's
        # selection. Preserve its DTO without reading or changing that state.
        return {'active': owner.profile, 'current': owner.profile}
    if operation == 'GET /api/fs/default-cwd':
        if not owner.roots:
            raise CapabilityError(403, 'no workspace grant')
        cwd = policy.path(owner, str(owner.roots[0]))
        from .filesystem import pin_paths
        with pin_paths(policy, owner, [cwd]):
            from pathlib import Path
            if not Path(cwd).is_dir():
                raise CapabilityError(403, 'workspace directory unavailable')
        branch = None
        if (Path(cwd) / '.git').exists():
            # Same original cwd/branch DTO, but no git subprocess (config,
            # fsmonitor, includes and hooks are not a read capability).
            from .git_scope import git_read
            row = git_read(policy, owner, '/api/git/worktrees', {'path': cwd})['worktrees'][0]
            branch = row['branch']
        return {'cwd': cwd, 'branch': branch}
    if operation == 'GET /api/env':
        import re
        from hermes_cli.web_routers.config_env import get_env_vars
        original = await get_env_vars(profile=owner.profile)
        if not isinstance(original, dict) or len(original) > 4096:
            raise CapabilityError(502, 'invalid startup environment metadata')
        return {name: row for name, value in original.items()
                if isinstance(name, str) and re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]{0,127}', name)
                and (row := _ENV_ROW(value)) is not _OMIT and 'is_set' in row}
    if operation == 'GET /api/config/schema':
        from hermes_cli.web_routers.config_env import get_schema
        return _schema(await get_schema(profile=owner.profile))
    if operation == 'GET /api/config/defaults':
        from hermes_cli.web_routers.config_env import get_defaults
        return _settings(await get_defaults())
    raise CapabilityError(404, 'unlisted startup operation')
