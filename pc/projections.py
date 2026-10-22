"""Closed renderer metadata DTOs for source pin 93ac19694ea0c4cc1e1661ff37c2a171d96a1bc0.

This is an output boundary, not a recursive secret-pattern scrubber. Every object
level, dynamic row, and leaf has an explicit shape. Endpoints, invocation data,
credential values, provider probe detail, and env defaults are never copied.
Malformed leaves are omitted, never coerced/stringified. Display strings remain
user/plugin-authored metadata; no claim is made to detect arbitrary secrets that
an administrator deliberately puts in a model name or human-readable label.
"""
from __future__ import annotations

from collections.abc import Callable
from types import MappingProxyType
from typing import Any

_OMIT = object()
Projector = Callable[[object], Any]


def _text(value: object) -> object:
    if type(value) is not str or len(value) > 4096:
        return _OMIT
    # The pinned auxiliary/MoA handlers stringify malformed saved containers.
    # Reject serialized object/list leaves too; checking Python types alone would
    # re-admit credential subtrees after upstream's str(...) coercion.
    if value.lstrip().startswith(('{', '[')):
        return _OMIT
    # Supplemental endpoint guard, independent of credential spelling. The primary
    # guarantee is the absent endpoint fields in the schemas below, not this guard.
    from urllib.parse import unquote, urlsplit
    if any(ord(c) < 32 for c in value):
        return _OMIT
    # Only inspect for endpoint structure; ordinary '&', '?', '#' and '%' in
    # display prose (or ':' in model IDs) are not credentials and stay intact.
    decoded = unquote(unquote(value))
    if '://' in decoded or '\\' in decoded or decoded.startswith('//'):
        return _OMIT
    for word in decoded.split():
        try:
            parsed = urlsplit(word)
        except ValueError:
            return _OMIT
        if parsed.scheme.lower() in {'http', 'https', 'ws', 'wss', 'ftp', 'data'} or parsed.netloc:
            return _OMIT
        head, separator, tail = word.partition('?')
        if separator and ('=' in tail or '/' in head or '.' in head):
            return _OMIT
    return value


def _boolean(value: object) -> object:
    return value if type(value) is bool else _OMIT


def _enum(*choices: str) -> Projector:
    allowed = frozenset(choices)
    return lambda value: value if type(value) is str and value in allowed else _OMIT


def _nullable(project: Projector) -> Projector:
    return lambda value: None if value is None else project(value)


def _object(fields: dict[str, Projector]) -> Projector:
    def project(value: object) -> object:
        if type(value) is not dict:
            return _OMIT
        result = {}
        for key, convert in fields.items():
            if key in value:
                item = convert(value[key])
                if item is not _OMIT:
                    result[key] = item
        return result
    return project


def _array(project: Projector) -> Projector:
    def convert(value: object) -> object:
        if type(value) is not list or len(value) > 4096:
            return _OMIT
        result = []
        for entry in value:
            item = project(entry)
            if item is not _OMIT:
                result.append(item)
        return result
    return convert


_REASONING = _nullable(_text)  # The pinned parser also permits provider-specific tier strings.
_ASSIGNMENT = _object({'provider': _text, 'model': _text})
_AUXILIARY = _object({
    'tasks': _array(_object({
        'task': _text, 'provider': _text, 'model': _text, 'reasoning_effort': _REASONING,
        'local_endpoint': _boolean, 'label': _text, 'hint': _text, 'plugin': _text,
        'inherit_from': _nullable(_text), 'effective': _ASSIGNMENT,
    })),
    'main': _ASSIGNMENT,
})

def _integer(value: object) -> object:
    return value if type(value) is int and 0 <= value <= 2**53 - 1 else _OMIT


_INFO = _object({
    'model': _text, 'provider': _text,
    'auto_context_length': _integer, 'config_context_length': _integer,
    'effective_context_length': _integer,
    'capabilities': _object({
        'supports_tools': _boolean, 'supports_vision': _nullable(_boolean),
        'supports_reasoning': _nullable(_boolean),
        'context_window': _integer, 'max_output_tokens': _nullable(_integer), 'model_family': _text,
    }),
})

def _named_map(project: Projector) -> Projector:
    def convert(value: object) -> object:
        if type(value) is not dict or len(value) > 4096:
            return _OMIT
        result = {}
        for key, entry in value.items():
            if _text(key) is _OMIT:
                continue
            item = project(entry)
            if item is not _OMIT:
                result[key] = item
        return result
    return convert


def _number(value: object) -> object:
    from math import isfinite
    if type(value) not in (int, float):
        return _OMIT
    try:
        return value if isfinite(value) else _OMIT
    except OverflowError:
        return _OMIT


def _fanout(value: object) -> object:
    if type(value) is str:
        if value in ('user_turn', 'per_iteration'):
            return value
        mode, _, n = value.partition(':')
        if mode == 'every_n' and n.isascii() and n.isdigit() and len(n) < 16 and int(n) >= 2:
            return value
    return _OMIT


_MOA_SLOT_FIELDS = {'provider': _text, 'model': _text, 'reasoning_effort': _REASONING}
_MOA_PRESET_FIELDS = {
    'enabled': _boolean,
    'reference_models': _array(_object({**_MOA_SLOT_FIELDS, 'enabled': _boolean})),
    'aggregator': _object(_MOA_SLOT_FIELDS),
    'reference_temperature': _nullable(_number), 'aggregator_temperature': _nullable(_number),
    'reference_timeout': _nullable(_number),
    'degraded_reference_policy': _enum('loud', 'silent'), 'fanout': _fanout,
}
_MOA = _object({
    **_MOA_PRESET_FIELDS, 'default_preset': _text, 'active_preset': _text,
    'presets': _named_map(_object(_MOA_PRESET_FIELDS)), 'privacy_filter': _enum('', 'display', 'full'),
})

_TOOL_CONFIG = _object({
    'name': _text, 'has_category': _boolean, 'active_provider': _nullable(_text),
    'providers': _array(_object({
        'name': _text, 'badge': _text, 'tag': _text,
        'env_vars': _array(_object({'key': _text, 'prompt': _text, 'is_set': _boolean})),
        'post_setup': _nullable(_text), 'requires_nous_auth': _boolean,
        'managed_nous_feature': _nullable(_text), 'is_active': _boolean,
        'status': _enum('ready', 'needs_keys', 'needs_auth', 'needs_setup', 'unavailable'),
        'web_backend': _text, 'capabilities': _array(_enum('search', 'extract')), 'tts_provider': _text,
    })),
    'active_search_backend': _nullable(_text), 'active_extract_backend': _nullable(_text),
    'search_via_nous': _boolean, 'extract_via_nous': _boolean,
})

_TOOL_MODELS = _object({
    'name': _text, 'has_models': _boolean, 'provider': _nullable(_text), 'plugin': _nullable(_text),
    'models': _array(_object({'id': _text, 'display': _text, 'speed': _text, 'strengths': _text, 'price': _text})),
    'current': _nullable(_text), 'default': _nullable(_text),
})

_TERMINAL = _object({
    'active': _text,
    'backends': _array(_object({
        'name': _text, 'label': _text, 'description': _text,
        'active': _boolean, 'status': _enum('ready', 'needs_setup', 'unavailable'),
    })),
})

_MCP = _object({
    'servers': _array(_object({
        'name': _text, 'transport': _enum('http', 'stdio', 'unknown'), 'enabled': _boolean,
        'auth': _nullable(_enum('', 'none', 'oauth', 'header')),
        'tools': _nullable(_array(_text)), 'source': _enum('plugin', 'config'), 'plugin': _nullable(_text),
    })),
})

_MCP_CATALOG = _object({
    'entries': _array(_object({
        'name': _text, 'description': _text, 'connector_slug': _nullable(_text),
        'transport': _enum('stdio', 'http'), 'auth_type': _enum('api_key', 'oauth', 'none'),
        'required_env': _array(_object({'name': _text, 'prompt': _text, 'required': _boolean})),
        'default_enabled': _nullable(_array(_text)),
        'suggest': _nullable(_object({'keywords': _array(_text), 'applications': _array(_text),
                                      'examples': _array(_text), 'requires_app': _boolean})),
        'needs_install': _boolean, 'installed': _boolean, 'enabled': _boolean,
    })),
    'diagnostics': _array(_object({'name': _text, 'kind': _enum('future_manifest', 'invalid')})),
})

_TOOLSETS = _array(_object({
    'name': _text, 'label': _text, 'description': _text, 'platform': _text, 'platform_label': _text,
    'enabled': _boolean, 'available': _boolean, 'configured': _boolean, 'tools': _array(_text),
}))

# Catalog names are explicit. Unknown names fail closed instead of falling back
# to redaction or forwarding the original service result.
_PROJECTORS = MappingProxyType({'model-auxiliary': _AUXILIARY, 'model-info': _INFO, 'model-moa': _MOA,
                               'tool-config': _TOOL_CONFIG, 'tool-models': _TOOL_MODELS,
                               'terminal-backends': _TERMINAL, 'mcp': _MCP, 'mcp-catalog': _MCP_CATALOG,
                               'toolsets': _TOOLSETS})
METADATA_PROJECTIONS = frozenset(_PROJECTORS)
# Integration contract only: catalog/addon owners must opt into every mapping.
# Run these DTOs as the terminal success projection (do not remove env-presence
# fields with generic key redaction afterward). For non-2xx responses preserve
# the HTTP status and emit a static error DTO, never an arbitrary upstream body.
METADATA_OPERATION_PROJECTIONS = MappingProxyType({
    'GET /api/model/info': 'model-info',
    'GET /api/model/auxiliary': 'model-auxiliary',
    'GET /api/model/moa': 'model-moa',
    'GET /api/tools/toolsets': 'toolsets',
    'GET /api/tools/toolsets/{name}/config': 'tool-config',
    'GET /api/tools/toolsets/{name}/models': 'tool-models',
    'GET /api/tools/terminal/backends': 'terminal-backends',
    'GET /api/mcp/servers': 'mcp',
    'GET /api/mcp/catalog': 'mcp-catalog',
})


def project_metadata(projection: str, value: object) -> dict | list:
    """Project one successful original metadata result; reject unknown DTO names."""
    if projection not in _PROJECTORS:
        raise ValueError('unknown metadata projection')
    result = _PROJECTORS[projection](value)
    if result is _OMIT:
        return [] if projection == 'toolsets' else {}
    return result
