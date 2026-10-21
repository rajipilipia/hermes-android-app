"""Canonical identifiers for the pinned Desktop adapter, never normalization.

Pinned rules: hermes_constants.PROFILE_ID_RE and
hermes_cli.profiles.normalize_profile_name/validate_profile_name. Upstream allows
case/whitespace normalization at ingress; capability grants deliberately do not.
Routing selectors all/current are NEVER names, even if a directory has that name.
"""
from __future__ import annotations

from pathlib import Path
import re
import stat

from .catalog import CapabilityError

PROFILE_PATTERN = r'^(?!(?:all|current|hermes|test|tmp|root|sudo)$)[a-z0-9][a-z0-9_-]{0,63}$'
PROFILE_SCHEMA = {'type': 'string', 'pattern': PROFILE_PATTERN, 'maxLength': 64}
_SKILL = re.compile(r'[a-z0-9][a-z0-9._-]{0,63}')
_MEMORY = re.compile(r'memory:(?:memory|profile):(?:0|[1-9][0-9]{0,8}):[0-9a-f]{12}')
_WINDOWS_DEVICES = frozenset({'con', 'prn', 'aux', 'nul', 'clock$', 'conin$', 'conout$'} |
                             {f'{prefix}{i}' for prefix in ('com', 'lpt') for i in range(1, 10)})


def canonical_profile(value, *, status=400):
    """Return the identical input object, or reject; usable at grant AND request ingress."""
    if not isinstance(value, str) or re.fullmatch(PROFILE_PATTERN, value) is None:
        raise CapabilityError(status, 'one exact canonical profile name required; aliases forbidden')
    return value


def canonical_skill_name(value):
    """Single safe upstream skill name; never a path, qualified selector or alias."""
    if (not isinstance(value, str) or _SKILL.fullmatch(value) is None or
            value.endswith('.') or value.split('.')[0] in _WINDOWS_DEVICES):
        raise CapabilityError(400, 'canonical single-component skill name required')
    return value


def learning_node_id(value):
    """Only content-addressed memory IDs or canonical skill IDs are mutation keys.

    Legacy positional memory IDs are withheld: a shifted list can name another
    card. This is stricter than the upstream compatibility parser, intentionally.
    """
    if isinstance(value, str) and value.startswith('memory:'):
        if _MEMORY.fullmatch(value) is None:
            raise CapabilityError(400, 'fingerprinted canonical memory node id required')
        return value
    return canonical_skill_name(value)


def _unlinked(path):
    path = Path(path).absolute()
    for component in (path, *path.parents):
        try:
            info = component.lstat()
        except FileNotFoundError:
            continue
        if stat.S_ISLNK(info.st_mode) or getattr(info, 'st_file_attributes', 0) & 0x400:
            raise CapabilityError(403, 'linked skill/archive path forbidden')
    return path.resolve()


def validate_selected_skill(name, selected_dir, skills_root, *, archive_destination=None, replacement=None):
    """Validate an ACTUAL selected local skill and archive target for inspection.

    This is NOT a mutation permit: the pinned original reselects by name and uses
    path-based rename/shutil.move, with no exact selected-path/dirfd contract.
    guard_learning_mutation therefore withholds the mutation even after this
    check. A closed preflight must never be treated as an authoritative lease.
    """
    canonical_skill_name(name)
    root, selected = _unlinked(skills_root), _unlinked(selected_dir)
    if selected == root or not selected.is_relative_to(root) or '.archive' in selected.relative_to(root).parts:
        raise CapabilityError(403, 'selected skill is not an active local skill')
    skill_md = _unlinked(selected / 'SKILL.md')
    if not skill_md.is_file():
        raise CapabilityError(404, 'selected SKILL.md missing')
    import yaml
    text = skill_md.read_text(encoding='utf-8-sig')
    _frontmatter_name(text, name, yaml)
    if replacement is not None:
        _frontmatter_name(replacement, name, yaml)
    if archive_destination is not None:
        archive = _unlinked(root / '.archive')
        target = _unlinked(archive_destination)
        if archive.parent != root or target.parent != archive or target.name != name:
            raise CapabilityError(403, 'archive target must be the exact skill under .archive')
        if target.exists():
            raise CapabilityError(403, 'archive collision handling is withheld')
    return selected


def _frontmatter_name(text, expected, yaml):
    if not isinstance(text, str) or not text.startswith('---\n'):
        raise CapabilityError(400, 'skill frontmatter required')
    match = re.search(r'\n---[ \t]*(?:\r?\n|$)', text[3:])
    if match is None:
        raise CapabilityError(400, 'closed skill frontmatter required')
    try:
        frontmatter = yaml.safe_load(text[3:3 + match.start()])
    except yaml.YAMLError:
        raise CapabilityError(400, 'invalid skill frontmatter') from None
    if not isinstance(frontmatter, dict):
        raise CapabilityError(400, 'skill frontmatter must be a mapping')
    actual = canonical_skill_name(frontmatter.get('name'))
    if actual != expected:
        raise CapabilityError(403, 'selected skill identity differs from mutation key')


def guard_learning_mutation(operation, body):
    """Fail closed BEFORE original learning/skill mutation services can run.

    No learning writes are currently forwarded, including legitimate canonical
    IDs. Upstream has no path-bound archive contract, skill edits may change their
    own name, and memory locking does not establish a filesystem owner boundary.
    Read-only graph/content operations are unaffected. This explicit 403 is a
    parity gap, not a claim that preflight makes upstream mutation race-free.
    """
    if operation not in {'PUT /api/learning/node', 'DELETE /api/learning/node', 'PUT /api/skills/toggle'}:
        return
    if not isinstance(body, dict):
        raise CapabilityError(400, 'mutation body required')
    if operation == 'PUT /api/skills/toggle':
        canonical_skill_name(body.get('name'))
    else:
        learning_node_id(body.get('id'))
    raise CapabilityError(403, 'learning/skill mutation withheld: no authoritative exact selected-path contract')
