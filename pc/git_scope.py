"""Confined Git metadata reads; opaque aggregate/content operations fail closed.

Pinned upstream web_git uses repository-wide diffs and unfiltered/truncated
status rows. A cwd preflight cannot authorize their bytes. Do NOT call those
helpers then turn a denied result into an empty 200. Until a bounded scoped
Git engine is proved, status/review lists/diffs/commit-context are explicit 403.

Ordinary standalone repositories retain branches/base-branches/worktrees and
simple named-ref resolution through bounded, pinned local metadata reads. No
Git subprocess, local/global config, include, filter, hook, gh or network runs.
Linked/shared worktrees and reftable layouts are deliberately not supported.
"""
from __future__ import annotations

import os
from pathlib import Path
import re

from .catalog import CapabilityError
from .filesystem import _pin_absolute, pin_paths

OID = re.compile(r'(?:[0-9a-fA-F]{40}|[0-9a-fA-F]{64})\Z')
MAX_METADATA_BYTES = 1024 * 1024
MAX_REFS = 10000
SAFE_ROUTES = frozenset({'/api/git/branches', '/api/git/base-branches',
                         '/api/git/worktrees', '/api/git/review/rev-parse'})


def _ref_name(value):
    if (not isinstance(value, str) or not value or len(value) > 256 or
            not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_./-]*', value) or
            '..' in value or '//' in value or value.endswith(('/', '.', '.lock')) or
            any(part.startswith('.') or part.endswith('.lock') for part in value.split('/'))):
        raise CapabilityError(400, 'only literal Git ref names or object IDs are supported')
    return value


def repository_root(policy, owner, raw):
    target = Path(policy.path(owner, raw))
    with pin_paths(policy, owner, [str(target)]):
        cursor = target if target.is_dir() else target.parent
        while True:
            policy.path(owner, str(cursor))
            with pin_paths(policy, owner, [str(cursor)]):
                marker = cursor / '.git'
                if marker.exists():
                    with _pin_absolute([marker]):
                        if not marker.is_dir():
                            raise CapabilityError(403, 'linked Git worktree is not a confined repository')
                    return cursor
            if cursor.parent == cursor:
                raise CapabilityError(403, 'confined standalone repository required')
            cursor = cursor.parent


def _metadata_text(metadata, relative, *, optional=False):
    target = metadata / relative
    if optional and not target.exists():
        return None
    with _pin_absolute([target]):
        if not target.is_file():
            raise CapabilityError(403, 'regular Git metadata file required')
        with target.open('rb') as handle:
            data = handle.read(MAX_METADATA_BYTES + 1)
        if len(data) > MAX_METADATA_BYTES:
            raise CapabilityError(413, 'Git metadata too large')
        try:
            return data.decode('utf-8').rstrip('\r\n')
        except UnicodeError:
            raise CapabilityError(403, 'unsupported Git metadata encoding') from None


def _refs(metadata):
    result = {}
    packed = _metadata_text(metadata, 'packed-refs', optional=True)
    if packed is not None:
        for line in packed.splitlines():
            if not line or line.startswith(('#', '^')):
                continue
            oid, separator, name = line.partition(' ')
            if not separator or OID.fullmatch(oid) is None or not name.startswith('refs/'):
                raise CapabilityError(403, 'unsupported packed Git references')
            try:
                _ref_name(name)
            except CapabilityError:
                raise CapabilityError(403, 'unsupported Git reference name') from None
            result[name] = oid
            if len(result) > MAX_REFS:
                raise CapabilityError(413, 'too many Git references')
    def visit(directory):
        if not directory.exists():
            return
        with _pin_absolute([directory]):
            with os.scandir(directory) as scan:
                entries = sorted(scan, key=lambda entry: entry.name)
            if len(entries) > MAX_REFS:
                raise CapabilityError(413, 'too many Git references')
            for entry in entries:
                child = Path(entry.path)
                with _pin_absolute([child]):
                    if child.is_dir():
                        visit(child)
                    else:
                        name = child.relative_to(metadata).as_posix()
                        try:
                            _ref_name(name)
                        except CapabilityError:
                            raise CapabilityError(403, 'unsupported Git reference name') from None
                        result[name] = _metadata_text(metadata, child.relative_to(metadata))
                        if len(result) > MAX_REFS:
                            raise CapabilityError(413, 'too many Git references')
    visit(metadata / 'refs')
    return result


def _resolve(refs, name, *, depth=0):
    if depth > 16:
        raise CapabilityError(403, 'cyclic Git reference')
    value = refs.get(name)
    if value is None:
        return None
    if OID.fullmatch(value):
        return value
    if value.startswith('ref: refs/'):
        target = value[5:]
        try:
            _ref_name(target)
        except CapabilityError:
            raise CapabilityError(403, 'unsupported symbolic Git reference') from None
        return _resolve(refs, target, depth=depth + 1)
    raise CapabilityError(403, 'unsupported Git reference contents')


def git_read(policy, owner, route, arguments):
    if route not in SAFE_ROUTES:
        raise CapabilityError(403, 'Git aggregate/content operation withheld: workspace confinement not proved')
    requested = arguments.get('ref')
    if route == '/api/git/review/rev-parse' and requested is not None:
        _ref_name(requested)  # no option/revision/pathspec interpretation
    root = repository_root(policy, owner, arguments['path'])
    metadata = root / '.git'
    with pin_paths(policy, owner, [str(root)]), _pin_absolute([metadata]):
        # No metadata redirection through gitdir/commondir/worktree registries.
        # Presence itself denies; never read potentially external target paths.
        if any((metadata / name).exists() for name in ('commondir', 'gitdir', 'worktrees', 'reftable')):
            raise CapabilityError(403, 'shared Git metadata/worktrees are not confined')
        refs = _refs(metadata)
        head = _metadata_text(metadata, 'HEAD')
        refs['HEAD'] = head
        current = head[5:] if head.startswith('ref: refs/heads/') else None
        # Validate every stored value even if this response would omit it.
        for name in refs:
            _resolve(refs, name)
        if route == '/api/git/review/rev-parse':
            ref = requested or 'HEAD'
            if OID.fullmatch(ref):
                # Exact IDs are opaque identifiers; do not dereference objects
                # or alternates to test their existence.
                return {'sha': ref}
            candidates = (ref, 'refs/heads/' + ref, 'refs/tags/' + ref, 'refs/remotes/' + ref)
            return {'sha': next((sha for candidate in candidates if (sha := _resolve(refs, candidate))), None)}
        if route == '/api/git/worktrees':
            return {'worktrees': [{'path': str(root), 'branch': current.removeprefix('refs/heads/') if current else None,
                                  'isMain': True, 'detached': current is None, 'locked': False}]}
        local = sorted(name for name in refs if name.startswith('refs/heads/'))
        remote = sorted(name for name in refs if name.startswith('refs/remotes/'))
        default = next((name for name in ('refs/heads/main', 'refs/heads/master',
                                          'refs/remotes/origin/main', 'refs/remotes/origin/master') if name in refs), None)
        if route == '/api/git/base-branches':
            return {'branches': [{'name': name.removeprefix('refs/heads/').removeprefix('refs/remotes/'),
                                  'isRemote': name.startswith('refs/remotes/'), 'isDefault': name == default}
                                 for name in local + remote]}
        names = {name.removeprefix('refs/heads/') for name in local}
        return {'branches': [
            *({'name': name.removeprefix('refs/heads/'), 'checkedOut': name == current,
               'isDefault': name == default, 'isRemote': False,
               'worktreePath': str(root) if name == current else None} for name in local),
            *({'name': name.removeprefix('refs/remotes/'), 'checkedOut': False,
               'isDefault': False, 'isRemote': True, 'worktreePath': None} for name in remote
              if not name.endswith('/HEAD') and name.split('/', 3)[-1] not in names)]}
