"""Closed, source-pinned Desktop REST compatibility catalog (MIT, Pilipia.us).

No request can select a URL, header, HTTP method or an unlisted path. The operation
string is an exact catalog key, not executable routing syntax.
"""
from __future__ import annotations

from dataclasses import dataclass
import json
import re
from typing import Any

SOURCE_COMMIT = '93ac19694ea0c4cc1e1661ff37c2a171d96a1bc0'
MAX_REQUEST_BYTES = 4 * 1024 * 1024
MAX_JSON_BYTES = 4 * 1024 * 1024


class CapabilityError(ValueError):
    def __init__(self, status: int, detail: str):
        super().__init__(detail)
        self.status, self.detail = status, detail


def string(maximum=4096, *, enum=None):
    return {'type': 'string', 'maxLength': maximum, **({'enum': enum} if enum else {})}


def integer(minimum=0, maximum=500):
    return {'type': 'integer', 'minimum': minimum, 'maximum': maximum}


BOOL = {'type': 'boolean'}
NAME = {'type': 'string', 'pattern': r'^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$', 'maxLength': 128}
# Kept here to avoid a catalog/identifier import cycle. This is authority, not
# upstream's convenience normalization; request names are never repaired.
PROFILE = {'type': 'string', 'pattern': r'^(?!(?:all|current|hermes|test|tmp|root|sudo)$)[a-z0-9][a-z0-9_-]{0,63}$', 'maxLength': 64}
PATH = string(4096)


def obj(properties=None, required=()):
    return {'type': 'object', 'properties': properties or {}, 'required': list(required), 'additionalProperties': False}


# Denied operations remain explicit catalog entries to return an honest 403,
# rather than a successful empty DTO. They are not claimed feature parity.
WITHHELD_OPERATIONS = frozenset({
    'PUT /api/learning/node', 'DELETE /api/learning/node', 'PUT /api/skills/toggle',
    'POST /api/files/mkdir', 'POST /api/audio/stt-lease', 'POST /api/audio/tts-lease', 'GET /api/git/status',
    'GET /api/git/review/list', 'GET /api/git/review/commit-context',
    'GET /api/git/review/diff', 'GET /api/git/file-diff',
})


@dataclass(frozen=True)
class Operation:
    id: str
    method: str
    path: str
    source: str
    query: dict
    body: dict | None
    permission: str
    output: str = 'json'
    profile_query: bool = True
    path_fields: tuple[str, ...] = ()
    result_projection: str = 'redact'

    def contract(self):
        path_params = re.findall(r'\{(\w+)\}', self.path)
        return {'id': self.id, 'method': self.method, 'pathTemplate': self.path,
                'source': self.source, 'permission': self.permission, 'output': self.output,
                'profileQuery': self.profile_query, 'pathFields': list(self.path_fields),
                'resultProjection': self.result_projection,
                'availability': 'withheld' if self.id in WITHHELD_OPERATIONS else 'implemented',
                'limitations': (['Explicit 403: safe authoritative scoped implementation pending'] if self.id in WITHHELD_OPERATIONS else [])
                    + (['session_id-bound file reads are explicitly withheld'] if self.path in ('/api/fs/read-data-url', '/api/fs/download') else []),
                'pathParams': obj({n: NAME for n in path_params}, path_params),
                'query': self.query, 'body': self.body}


OPERATIONS: dict[str, Operation] = {}


def _add(method, path, source, *, query=None, body=None, permission=None,
         output='json', profile_query=True, paths=(), projection='redact', query_required=()):
    key = f'{method} {path}'
    from .projections import METADATA_OPERATION_PROJECTIONS
    projection = METADATA_OPERATION_PROJECTIONS.get(key, projection)
    if key in OPERATIONS:
        raise RuntimeError('duplicate operation')
    OPERATIONS[key] = Operation(key, method, path, f'hermes_cli/web_routers/{source}.py',
                               obj(query, query_required), body, permission or ('read' if method == 'GET' else 'write'),
                               output, profile_query, tuple(paths), projection)


_add('GET', '/api/profiles', 'profiles', profile_query=False, projection='profiles')
_add('GET', '/api/profiles/active', 'profiles', profile_query=False, projection='startup')
_add('GET', '/api/status', 'status', projection='startup')

# Deliberately narrow settings DTO: no effective secret-bearing config is ever
# obtained for a read. Reads use the raw saved config and project these leaves.
SETTINGS = obj({
    'display': obj({'skin': string(128), 'theme': string(128), 'language': string(32),
                    'show_reasoning': BOOL, 'show_cost': BOOL, 'compact': BOOL}),
    'agent': obj({'max_turns': integer(1, 1000)}),
    'compression': obj({'enabled': BOOL}),
    'voice': obj({'enabled': BOOL}),
    'stt': obj({'enabled': BOOL, 'provider': string(64)}),
    'tts': obj({'provider': string(64), 'voice': string(256)}),
})
_add('GET', '/api/config', 'config_env', query={'include_defaults': BOOL}, projection='settings')
_add('GET', '/api/config/defaults', 'config_env', profile_query=False, projection='startup')
_add('GET', '/api/config/schema', 'config_env', projection='startup')
_add('GET', '/api/env', 'config_env', projection='startup')
_add('GET', '/api/fs/default-cwd', 'files', projection='startup')
_add('GET', '/api/model/options', 'models',
     query={'explicit_only': BOOL, 'include_unconfigured': BOOL, 'refresh': BOOL}, projection='startup')
_add('PUT', '/api/config', 'config_env', body=obj({'config': SETTINGS}, ('config',)), permission='settings.write')

# File paths are resolved against the server-owned workspace grant BEFORE the
# original endpoint validates/handles them; no host-wide default directory API.
for suffix in ('list', 'read-text', 'read-data-url', 'git-root'):
    _add('GET', '/api/fs/' + suffix, 'files',
         query={'path': PATH, **({'session_id': NAME} if suffix == 'read-data-url' else {})},
         paths=('query.path',), projection='files' if suffix == 'list' else 'redact')
_add('GET', '/api/fs/download', 'files', query={'path': PATH, 'session_id': NAME},
     paths=('query.path',), output='download')
_add('POST', '/api/fs/write-text', 'files',
     body=obj({'path': PATH, 'content': string(1024 * 1024)}, ('path', 'content')),
     permission='files.write', paths=('body.path',))
_add('POST', '/api/files/mkdir', 'files', body=obj({'path': PATH}, ('path',)),
     permission='files.write', paths=('body.path',), profile_query=False)
_add('POST', '/api/files/upload', 'files',
     body=obj({'path': PATH, 'data_url': string(3 * 1024 * 1024), 'overwrite': BOOL}, ('path', 'data_url')),
     permission='files.write', paths=('body.path',), profile_query=False)

PAGE = {'limit': integer(1, 100), 'offset': integer(0, 1000000), 'min_messages': integer(),
        'archived': string(16, enum=['exclude', 'only', 'include']), 'order': string(16, enum=['created', 'recent'])}
SOURCES = {'source': string(64), 'sources': string(256), 'exclude_sources': string(256)}
# 'all' is a query selector ONLY, never an authority-bearing owner profile.
SELECTOR = {**PROFILE, 'pattern': r'^(?:all|(?!(?:current|hermes|test|tmp|root|sudo)$)[a-z0-9][a-z0-9_-]{0,63})$'}
_add('GET', '/api/sessions', 'sessions', query={**PAGE, **SOURCES})
_add('GET', '/api/sessions/search', 'sessions', query={'q': string(1024), 'limit': integer(1, 100), **SOURCES})
_add('GET', '/api/sessions/{session_id}', 'sessions')
_add('GET', '/api/sessions/{session_id}/messages', 'sessions',
     query={'limit': integer(1, 500), 'offset': integer(0, 1000000),
            'order': string(16, enum=['latest', 'oldest']), 'include_compacted': BOOL, 'inline_images': BOOL})
_add('GET', '/api/sessions/{session_id}/timeline', 'sessions',
     query={'limit': integer(1, 500), 'after_row_id': integer(0, 2147483647)})
_add('GET', '/api/sessions/{session_id}/messages/around', 'sessions',
     query={'limit': integer(1, 120), 'row_id': integer(1, 2147483647)}, query_required=('row_id',))
_add('PATCH', '/api/sessions/{session_id}', 'sessions',
     body=obj({'title': string(512), **{k: BOOL for k in ('archived', 'hidden', 'pinned', 'unread')}}),
     permission='sessions.write', profile_query=False)
_add('GET', '/api/profiles/sessions', 'profiles',
     query={**PAGE, 'limit': integer(1, 500), **SOURCES, 'profile': SELECTOR}, profile_query=False)
_add('GET', '/api/profiles/sessions/sidebar', 'profiles', profile_query=False,
     query={'recents_profile': SELECTOR, 'recents_limit': integer(1, 500), 'recents_exclude': string(256),
            'cron_limit': integer(1, 500), 'messaging_limit': integer(1, 500), 'messaging_exclude': string(256)})

# All recordings and synthesis run through the original relay services. Direct
# provider config, provider keys, PC microphone capture and PC playback are NOT
# substitutes for Android capture/playback and are not added here.
_add('POST', '/api/audio/transcribe', 'audio',
     body=obj({'data_url': string(3 * 1024 * 1024), 'mime_type': string(128)}, ('data_url',)), permission='audio')
_add('POST', '/api/audio/speak', 'audio', body=obj({'text': string(20000)}, ('text',)), permission='audio', output='download')
for kind in ('stt', 'tts'):
    _add('POST', f'/api/audio/{kind}-lease', 'audio',
         body=obj({'lease': NAME, 'active': BOOL}, ('lease', 'active')), permission='audio')
_add('GET', '/api/audio/elevenlabs/voices', 'audio', permission='audio')
_add('GET', '/api/audio/voice-live/status', 'audio', permission='audio')

_add('GET', '/api/skills', 'skills')
_add('GET', '/api/skills/content', 'skills', query={'name': string(256)})
_add('PUT', '/api/skills/toggle', 'skills', body=obj({'name': string(256), 'enabled': BOOL}, ('name', 'enabled')), permission='skills.write')
for suffix in ('official', 'sources'):
    _add('GET', '/api/skills/hub/' + suffix, 'skills', permission='network')
_add('GET', '/api/skills/hub/search', 'skills', query={'q': string(512), 'source': string(256)}, permission='network')
for suffix in ('preview', 'scan'):
    _add('GET', '/api/skills/hub/' + suffix, 'skills', query={'identifier': string(512)}, permission='network')
# Installing arbitrary executable plugins/MCPs is left to existing typed WS
# approvals, not silently granted by read/write settings permissions.
_add('GET', '/api/mcp/servers', 'mcp', projection='mcp')
_add('GET', '/api/mcp/catalog', 'mcp')
_add('PUT', '/api/mcp/servers/{name}/enabled', 'mcp', body=obj({'enabled': BOOL}, ('enabled',)), permission='mcp.write')
_add('GET', '/api/tools/toolsets', 'tools')
_add('PUT', '/api/tools/toolsets/{name}', 'tools', body=obj({'enabled': BOOL}, ('enabled',)), permission='tools.write')
_add('GET', '/api/tools/toolsets/{name}/config', 'tools', projection='tool-config')
_add('GET', '/api/tools/toolsets/{name}/models', 'tools')
_add('GET', '/api/tools/terminal/backends', 'tools')
_add('GET', '/api/learning/graph', 'status')
_add('GET', '/api/learning/node', 'status', query={'id': string(256)})
_add('PUT', '/api/learning/node', 'status', body=obj({'id': string(256), 'content': string(200000)}, ('id', 'content')), permission='skills.write')
_add('DELETE', '/api/learning/node', 'status', body=obj({'id': string(256)}, ('id',)), permission='skills.write')

# Stored cron reads complement cron.manage's typed WS lifecycle. Trigger/create
# may send messages or execute arbitrary actions and require a future capability.
_add('GET', '/api/cron/jobs', 'cron')
_add('GET', '/api/cron/jobs/{job_id}', 'cron')
_add('GET', '/api/cron/jobs/{job_id}/runs', 'cron', query={'limit': integer(1, 100)})
_add('GET', '/api/cron/blueprints', 'cron')
_add('GET', '/api/model/info', 'models', projection='redact')
_add('GET', '/api/model/auxiliary', 'models', projection='redact')
_add('GET', '/api/model/moa', 'models', projection='redact')

# Repository read capabilities have their own workspace gate. No commit, stage,
# push, reset, PR creation, worktree mutation or shell execution is added.
for suffix in ('status', 'worktrees', 'branches', 'base-branches', 'review/commit-context'):
    _add('GET', '/api/git/' + suffix, 'git', query={'path': PATH}, paths=('query.path',), profile_query=False)
_add('GET', '/api/git/review/list', 'git', query={'path': PATH, 'scope': string(32, enum=['uncommitted', 'branch']), 'base': string(256)}, paths=('query.path',), profile_query=False)
_add('GET', '/api/git/review/rev-parse', 'git', query={'path': PATH, 'ref': string(256)}, paths=('query.path',), profile_query=False)
for suffix in ('file-diff', 'review/diff'):
    _add('GET', '/api/git/' + suffix, 'git',
         query={'path': PATH, 'file': PATH, **({'scope': string(32, enum=['uncommitted', 'branch']), 'base': string(256), 'staged': BOOL} if suffix == 'review/diff' else {})},
         paths=('query.path', 'query.file'), profile_query=False)


@dataclass(frozen=True)
class Call:
    operation: Operation
    profile: str
    path_params: dict
    query: dict
    body: Any


def validate_schema(value, schema, label='value'):
    """Validate the deliberately small JSON-Schema subset emitted in the contract."""
    kind = schema.get('type')
    types = {'object': dict, 'array': list, 'string': str, 'integer': int, 'boolean': bool}
    if kind in types and (not isinstance(value, types[kind]) or (kind == 'integer' and isinstance(value, bool))):
        raise CapabilityError(400, f'{label}: expected {kind}')
    if kind == 'object':
        props = schema.get('properties', {})
        if schema.get('additionalProperties') is False and set(value) - set(props):
            raise CapabilityError(400, f'{label}: unlisted field')
        if set(schema.get('required', ())) - set(value):
            raise CapabilityError(400, f'{label}: missing field')
        for name, item in value.items():
            if name in props:
                validate_schema(item, props[name], f'{label}.{name}')
    elif kind == 'array':
        if len(value) > schema.get('maxItems', 1000):
            raise CapabilityError(413, f'{label}: too many items')
        for item in value:
            validate_schema(item, schema['items'], label)
    elif kind == 'string':
        if len(value) > schema.get('maxLength', 4096):
            raise CapabilityError(413, f'{label}: too long')
        if '\x00' in value or (schema.get('pattern') and not re.fullmatch(schema['pattern'], value)):
            raise CapabilityError(400, f'{label}: invalid value')
    elif kind == 'integer':
        if value < schema.get('minimum', 0) or value > schema.get('maximum', 500):
            raise CapabilityError(400, f'{label}: out of bounds')
    if 'enum' in schema and value not in schema['enum']:
        raise CapabilityError(400, f'{label}: unlisted value')


def validate_call(params: dict) -> Call:
    validate_schema(params, obj({'operation': string(256), 'profile': PROFILE,
                                'pathParams': {'type': 'object'}, 'query': {'type': 'object'},
                                'body': {}}, ('operation', 'profile')), 'params')
    try:
        size = len(json.dumps(params, ensure_ascii=False, allow_nan=False).encode('utf-8'))
    except (ValueError, TypeError, UnicodeError, RecursionError):
        raise CapabilityError(400, 'params: not finite JSON') from None
    if size > MAX_REQUEST_BYTES:
        raise CapabilityError(413, 'request too large')
    operation = OPERATIONS.get(params['operation'])
    if operation is None:
        raise CapabilityError(404, 'unlisted operation')
    path_params, query = params.get('pathParams', {}), params.get('query', {})
    validate_schema(path_params, operation.contract()['pathParams'], 'pathParams')
    validate_schema(query, operation.query, 'query')
    body = params.get('body')
    if operation.body is None:
        if body is not None:
            raise CapabilityError(400, 'operation has no body')
    else:
        validate_schema(body, operation.body, 'body')
    return Call(operation, params['profile'], path_params, query, body)
