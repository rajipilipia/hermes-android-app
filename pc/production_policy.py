"""Explicit host-owned policy for production composition; imports no runtime.

Path/owner checks are admission observations, not an atomic OS access lease or
an ACL audit. Untrusted principals must not control concurrent namespace changes.
Integrations must still pin paths through actual I/O with the filesystem guard.
"""
from __future__ import annotations

import ctypes
from contextlib import contextmanager, ExitStack
from ctypes import wintypes
from dataclasses import dataclass
import json
import os
from pathlib import Path
import re
import stat
from types import MappingProxyType

from .catalog import CapabilityError
from .identifiers import canonical_profile
from .policy import PERMISSIONS, Policy


_FIELDS = {'schemaVersion', 'owner', 'root', 'launchProfile', 'launchHome', 'spool', 'principals'}
_DEVICES = frozenset({'con', 'prn', 'aux', 'nul', 'clock$', 'conin$', 'conout$'} |
                     {f'{prefix}{i}' for prefix in ('com', 'lpt') for i in '123456789¹²³'})
_AMBIENT = re.compile(r'(?:^|[-_.:/])(?:all|any|internal|loopback|local|delegat(?:e|ed|ion)|anonymous|system)(?:$|[-_.:/])', re.I)


def _object(value, fields, label):
    if not isinstance(value, dict) or set(value) != fields:
        raise ValueError(f'{label} must contain exactly its declared fields')


def _nonempty(value, label):
    if not isinstance(value, str) or not value or value.strip() != value:
        raise ValueError(f'{label} must be an exact nonempty string')
    return value


def _identity(value):
    _nonempty(value, 'principal identity')
    if (len(value) > 1024 or any(c.isspace() or ord(c) < 32 or ord(c) == 127 for c in value)
            or any(c in value for c in '*?[]') or _AMBIENT.search(value)):
        raise ValueError('wildcard, internal or delegation principal forbidden')
    return value


def _profile(value):
    try:
        result = canonical_profile(value)
        if result in _DEVICES:
            raise ValueError('device profile name forbidden')
        return result
    except ValueError:
        raise ValueError('exact canonical profile name required') from None


def _canonical_path(raw, *, directory=True, existing=True):
    raw = os.fspath(raw)
    _nonempty(raw, 'path')
    normalized = raw.replace('\\', '/')
    path = Path(raw)
    if (len(raw) > 4096 or not path.is_absolute() or normalized.startswith('//')
            or any(ord(c) < 32 or ord(c) == 127 for c in raw)
            or any(c in raw for c in '%$~*?[]<>"|')
            or ':' in re.sub(r'^[A-Za-z]:/', '', normalized)
            or (os.name != 'nt' and '\\' in raw)):
        raise ValueError('absolute unambiguous local path required')
    remainder = normalized[len(path.anchor.replace('\\', '/')):]
    parts = remainder.split('/') if remainder else []
    if any(not p or p in {'.', '..'} or p.rstrip(' .') != p
           or p.split('.')[0].lower() in _DEVICES for p in parts):
        raise ValueError('canonical path components required')
    _unlinked(path, missing_ok=not existing)
    resolved = path.resolve(strict=existing)
    if str(resolved) != raw:
        raise ValueError('path must use its exact canonical spelling')
    if existing:
        info = resolved.stat()
        if not (stat.S_ISDIR(info.st_mode) if directory else stat.S_ISREG(info.st_mode)):
            raise ValueError('existing directory required' if directory else 'regular manifest file required')
    return resolved


def _overlap(left, right):
    return left.is_relative_to(right) or right.is_relative_to(left)


def _closed_json(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('duplicate JSON key forbidden')
        result[key] = value
    return result


def _invalid_constant(value):
    raise ValueError('non-JSON number forbidden')


def _shape(value):
    _object(value, _FIELDS, 'manifest')
    if type(value['schemaVersion']) is not int or value['schemaVersion'] != 1:
        raise ValueError('schemaVersion must be integer 1')
    for name in ('owner', 'root', 'launchHome', 'spool'):
        _nonempty(value[name], name)
    _profile(value['launchProfile'])
    principals = value['principals']
    if not isinstance(principals, list) or not principals:
        raise ValueError('nonempty principal list required')
    seen = set()
    for principal in principals:
        _object(principal, {'provider', 'user_id', 'profiles'}, 'principal')
        key = _identity(principal['provider']), _identity(principal['user_id'])
        if key in seen:
            raise ValueError('duplicate principal forbidden')
        seen.add(key)
        profiles = principal['profiles']
        if not isinstance(profiles, dict) or not profiles:
            raise ValueError('nonempty exact profile grants required')
        for name, grant in profiles.items():
            _profile(name)
            _object(grant, {'expectedHome', 'roots', 'permissions'}, 'profile grant')
            _nonempty(grant['expectedHome'], 'expectedHome')
            for field in ('roots', 'permissions'):
                items = grant[field]
                if not isinstance(items, list) or not items:
                    raise ValueError(f'nonempty {field} list required')
                for item in items:
                    _nonempty(item, field)
                if len(set(items)) != len(items):
                    raise ValueError(f'duplicate {field} forbidden')
            if not set(grant['permissions']) <= PERMISSIONS:
                raise ValueError('unlisted permission')


def _windows_apis():
    advapi = ctypes.WinDLL('advapi32', use_last_error=True)
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    advapi.OpenProcessToken.argtypes = [wintypes.HANDLE, wintypes.DWORD,
                                       ctypes.POINTER(wintypes.HANDLE)]
    advapi.OpenProcessToken.restype = wintypes.BOOL
    advapi.GetTokenInformation.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p,
                                          wintypes.DWORD, ctypes.POINTER(wintypes.DWORD)]
    advapi.GetTokenInformation.restype = wintypes.BOOL
    advapi.ConvertSidToStringSidW.argtypes = [ctypes.c_void_p, ctypes.POINTER(wintypes.LPWSTR)]
    advapi.ConvertSidToStringSidW.restype = wintypes.BOOL
    kernel.GetCurrentProcess.argtypes = []
    kernel.GetCurrentProcess.restype = wintypes.HANDLE
    kernel.LocalFree.argtypes = [ctypes.c_void_p]
    kernel.LocalFree.restype = ctypes.c_void_p
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel.CloseHandle.restype = wintypes.BOOL
    return advapi, kernel


def _sid_text(advapi, kernel, sid):
    text = wintypes.LPWSTR()
    if not advapi.ConvertSidToStringSidW(sid, ctypes.byref(text)):
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        return text.value
    finally:
        kernel.LocalFree(ctypes.cast(text, ctypes.c_void_p))


def current_owner():
    """Current process TokenUser SID on Windows, decimal real uid on POSIX."""
    if os.name != 'nt':
        return str(os.getuid())
    advapi, kernel = _windows_apis()
    token = wintypes.HANDLE()
    if not advapi.OpenProcessToken(kernel.GetCurrentProcess(), 0x0008, ctypes.byref(token)):
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        size = wintypes.DWORD()
        advapi.GetTokenInformation(token, 1, None, 0, ctypes.byref(size))
        if not size.value:
            raise ctypes.WinError(ctypes.get_last_error())
        data = ctypes.create_string_buffer(size.value)
        if not advapi.GetTokenInformation(token, 1, data, size, ctypes.byref(size)):
            raise ctypes.WinError(ctypes.get_last_error())
        # TOKEN_USER starts with SID_AND_ATTRIBUTES, whose first member is PSID.
        sid = ctypes.cast(data, ctypes.POINTER(ctypes.c_void_p)).contents.value
        return _sid_text(advapi, kernel, sid)
    finally:
        kernel.CloseHandle(token)


def _check_link(info):
    if stat.S_ISLNK(info.st_mode) or getattr(info, 'st_file_attributes', 0) & 0x400:
        raise ValueError('link or reparse path forbidden')


def _unlinked(path, *, missing_ok=False):
    for component in (path, *path.parents):
        try:
            info = component.lstat()
        except FileNotFoundError:
            if missing_ok:
                continue
            raise
        _check_link(info)


def _path_owner(path):
    """Read the file object's OS owner, never infer it from home/username/ACL."""
    if os.name != 'nt':
        return str(Path(path).lstat().st_uid)
    advapi, kernel = _windows_apis()
    advapi.GetNamedSecurityInfoW.argtypes = [wintypes.LPWSTR, ctypes.c_int, wintypes.DWORD,
        ctypes.POINTER(ctypes.c_void_p), ctypes.POINTER(ctypes.c_void_p),
        ctypes.POINTER(ctypes.c_void_p), ctypes.POINTER(ctypes.c_void_p),
        ctypes.POINTER(ctypes.c_void_p)]
    advapi.GetNamedSecurityInfoW.restype = wintypes.DWORD
    owner, descriptor = ctypes.c_void_p(), ctypes.c_void_p()
    error = advapi.GetNamedSecurityInfoW(str(path), 1, 0x00000001,
        ctypes.byref(owner), None, None, None, ctypes.byref(descriptor))
    if error:
        raise ctypes.WinError(error)
    try:
        if not owner.value:
            raise ValueError('file owner SID unavailable')
        return _sid_text(advapi, kernel, owner)
    finally:
        if descriptor.value:
            kernel.LocalFree(descriptor)


@dataclass(frozen=True)
class _Fingerprint:
    path: Path
    device: int
    inode: int
    owner: str
    kind: int
    # Directory contents may legitimately change; manifest contents may not.
    file_state: tuple | None


def _fingerprint(path):
    info = path.lstat()
    _check_link(info)
    owner = _path_owner(path)
    after = path.lstat()
    _check_link(after)
    before_key = info.st_dev, info.st_ino, stat.S_IFMT(info.st_mode)
    after_key = after.st_dev, after.st_ino, stat.S_IFMT(after.st_mode)
    if before_key != after_key or not info.st_ino:
        raise ValueError('path identity unavailable or changed during verification')
    file_state = None
    if stat.S_ISREG(info.st_mode):
        if info.st_nlink != 1 or after.st_nlink != 1:
            raise ValueError('hardlinked manifest file forbidden')
        file_state = info.st_size, info.st_mtime_ns, info.st_nlink
        if file_state != (after.st_size, after.st_mtime_ns, after.st_nlink):
            raise ValueError('manifest changed during verification')
    return _Fingerprint(path, info.st_dev, info.st_ino, owner,
                        stat.S_IFMT(info.st_mode), file_state)


class BoundPolicy(Policy):
    """Manifest grants retaining Policy's Owner and (roots, permissions) layout."""

    @property
    def root(self):
        return self._root

    @property
    def launch_profile(self):
        return self._launch_profile

    @property
    def launch_home(self):
        return self._launch_home

    @property
    def spool(self):
        return self._spool

    def __init__(self, value, manifest, forbidden_roots):
        self._root = _canonical_path(value['root'])
        # Pinned resolve_profile_env strips profiles/<name> BEFORE main's
        # dotenv/logging imports. Reject that shape before importing runtime.
        if self.root.parent.name.casefold() == 'profiles':
            raise ValueError('root cannot itself be a named-profile-shaped home')
        self._launch_profile = value['launchProfile']
        self._launch_home = _canonical_path(value['launchHome'])
        self._spool = _canonical_path(value['spool'])
        self._manifest = manifest
        self._expected_homes = {}
        grants = {}
        for principal in value['principals']:
            for name, grant in principal['profiles'].items():
                home = _canonical_path(grant['expectedHome'])
                expected = self.root if name == 'default' else self.root / 'profiles' / name
                if str(home) != str(expected):
                    if name == 'default':
                        raise ValueError('default expectedHome must remain root')
                    self._profile_alias(name, home)
                if name in self._expected_homes and self._expected_homes[name] != home:
                    raise ValueError('principals disagree on canonical profile home')
                if any(other != name and other != 'default' and name != 'default'
                       and _overlap(home, previous)
                       for other, previous in self._expected_homes.items()):
                    raise ValueError('distinct profile homes overlap')
                self._expected_homes[name] = home
                grants[(principal['provider'], principal['user_id'], name)] = (
                    tuple(_canonical_path(p) for p in grant['roots']), frozenset(grant['permissions']))
        expected_launch = self._expected_homes.get(self.launch_profile,
            self.root if self.launch_profile == 'default' else self.root / 'profiles' / self.launch_profile)
        if str(expected_launch) != str(self.launch_home):
            raise ValueError('launchHome does not match root/launchProfile')
        forbidden = tuple(_canonical_path(p, existing=False) for p in forbidden_roots)
        if any(_overlap(target, blocked) for target in (
                self.root,self.launch_home,self.spool,*self._expected_homes.values()) for blocked in forbidden):
            raise ValueError('writable composition target overlaps forbidden root')
        workspaces = set(root for roots, _ in grants.values() for root in roots)
        for workspace in workspaces:
            if manifest.is_relative_to(workspace):
                raise ValueError('workspace cannot contain the host policy manifest')
            if any(_overlap(workspace, blocked) for blocked in (self.root, self.spool, *self._expected_homes.values(), *forbidden)):
                raise ValueError('workspace overlaps managed, spool or forbidden root')
            if any(workspace != other and _overlap(workspace, other) for other in workspaces):
                raise ValueError('distinct workspace roots overlap')
        super().__init__(grants, forbidden)
        self._grants = MappingProxyType(self._grants)
        self._expected_homes = MappingProxyType(self._expected_homes)
        self._binding = None
        self._host_owner = value['owner']
        if self._host_owner != current_owner():
            raise ValueError('manifest owner does not match current OS owner')
        self._owned_paths = frozenset((manifest, self.root, self.launch_home, self.spool,
                                      *self._expected_homes.values(), *workspaces))
        self._fingerprints = self._snapshot()

    def _snapshot(self):
        paths = set()
        for target in self._owned_paths:
            _unlinked(target)
            paths.update((target, *target.parents))
        fingerprints = tuple(_fingerprint(path) for path in sorted(paths, key=str))
        for fingerprint in fingerprints:
            if fingerprint.path in self._owned_paths and fingerprint.owner != self._host_owner:
                raise ValueError('manifest, home, workspace or spool owner differs from host owner')
        aliases = tuple(self._profile_alias(name, home)
                        for name, home in sorted(self._expected_homes.items())
                        if name != 'default' and home != self.root / 'profiles' / name)
        return fingerprints + aliases

    def _profile_alias(self, name, home):
        """Only the exact profiles-root directory junction is trusted, never user paths.

        expectedHome declares each canonical target; it does not authorize a
        storage subtree or any other profile. Inspect the junction BEFORE resolve.
        """
        junction = self.root / 'profiles'
        before = junction.lstat()
        if (os.name != 'nt' or not stat.S_ISDIR(before.st_mode)
                or getattr(before, 'st_reparse_tag', 0) != 0xA0000003
                or not before.st_ino or home.name != name):
            raise ValueError('expectedHome requires an exact owned profiles junction')
        owner = _path_owner(junction)
        # Elevated Windows installers commonly create this junction with the
        # local Administrators group as owner. Trust only that privileged OS
        # group or this user, never another account; pin the exact owner below.
        # Canonical profile homes and all other owned paths remain user-only.
        if owner not in (current_owner(), 'S-1-5-32-544'):
            raise ValueError('profiles junction owner differs from host owner')
        link = os.readlink(junction)
        target = _canonical_path(str(junction.resolve(strict=True)))
        if target != home.parent or target == self.root:
            raise ValueError('profiles junction differs from declared canonical storage')
        # Children themselves and the canonical storage chain remain no-link.
        _canonical_path(str(home))
        child = junction / name
        _check_link(child.lstat())
        if child.resolve(strict=True) != home:
            raise ValueError('profile alias differs from declared canonical home')
        after = junction.lstat()
        key = lambda info: (info.st_dev, info.st_ino, info.st_mode,
                            getattr(info, 'st_reparse_tag', 0))
        if key(before) != key(after) or os.readlink(junction) != link:
            raise ValueError('profiles junction changed during verification')
        return (str(junction), key(before), owner, link, str(target), name, str(home))

    def _runtime_home(self, name, raw):
        expected = self._expected_homes[name]
        if str(raw) == str(expected):
            return _canonical_path(raw)
        alias = self.root / 'profiles' / name
        if name != 'default' and expected != alias and str(raw) == str(alias):
            self._profile_alias(name, expected)
            return expected
        raise ValueError('runtime selected undeclared profile home')

    @classmethod
    def load(cls, path, *, forbidden_roots=()):
        try:
            path = _canonical_path(path, directory=False)
            before = _fingerprint(path)
            if before.owner != current_owner():
                raise ValueError('manifest file owner differs from host owner')
            value = json.loads(path.read_text(encoding='utf-8'), object_pairs_hook=_closed_json,
                               parse_constant=_invalid_constant)
            _shape(value)
            policy = cls(value, path, forbidden_roots)
            policy.validate()
            if _fingerprint(path) != before:
                raise ValueError('manifest changed during loading')
            return policy
        except (OSError, RuntimeError, UnicodeError, TypeError, RecursionError):
            raise ValueError('manifest or filesystem cannot be verified') from None

    def _check_binding(self, server, rest_resolver, profiles):
        if (self._binding is not None
                and any(name != 'default' and home != self.root / 'profiles' / name
                        for name, home in self._expected_homes.items())
                and self._bound_resolvers != (
                    server._launch_home, server._profile_home, rest_resolver)):
            raise ValueError('runtime resolver binding changed')
        launch = self._runtime_home(self.launch_profile, server._launch_home())
        if str(launch) != str(self.launch_home):
            raise ValueError('runtime launch home differs from manifest')
        for name in profiles:
            expected = self._expected_homes[name]
            websocket = server._profile_home(name)
            if websocket is None:
                websocket = server._launch_home()
            websocket = self._runtime_home(name, websocket)
            rest = self._runtime_home(name, rest_resolver(name))
            if str(websocket) != str(expected) or str(rest) != str(expected):
                raise ValueError('runtime selected home differs from manifest')

    def bind(self, server, rest_resolver):
        """Bind both original resolver seams; failures revoke any prior binding."""
        self._binding = None
        try:
            self.validate()
            self._check_binding(server, rest_resolver, self._expected_homes)
            self.validate()
        except Exception:
            raise CapabilityError(403, 'host policy runtime binding cannot be verified') from None
        self._binding = server, rest_resolver
        self._bound_resolvers = server._launch_home, server._profile_home, rest_resolver
        return self

    @contextmanager
    def profile_home(self, owner):
        """Canonical home held no-reparse/no-delete through finite service I/O."""
        from .filesystem import _pin_owned_directory, _pin_windows_path
        identity = {'provider': owner.provider, 'user_id': owner.user_id}
        if self.authorize(identity, owner.profile, 'read', owner.connection) != owner:
            raise CapabilityError(403, 'profile home owner differs from host grant')
        home = self._expected_homes[owner.profile]
        with ExitStack() as stack:
            for directory in dict.fromkeys((self.root, home)):
                stack.enter_context(_pin_owned_directory(directory))
            if any(name != 'default' and target != self.root / 'profiles' / name
                   for name, target in self._expected_homes.items()):
                stack.enter_context(_pin_windows_path(self.root / 'profiles', _profile_junction=True))
            self.authorize(identity, owner.profile, 'read', owner.connection)
            try:
                yield home
            finally:
                self.authorize(identity, owner.profile, 'read', owner.connection)

    def authorize(self, identity, profile, permission, connection):
        # Authenticate and authorize FIRST: callers cannot probe resolver/home
        # metadata simply by submitting a profile selector or permission.
        owner = super().authorize(identity, profile, permission, connection)
        if self._binding is None:
            raise CapabilityError(403, 'host policy is not bound to runtime resolvers')
        try:
            self.validate()
            self._check_binding(*self._binding, (owner.profile,))
            self.validate()
        except Exception:
            raise CapabilityError(403, 'host policy runtime boundary cannot be verified') from None
        return owner

    def validate(self):
        """Validate filesystem invariants before importing or binding a runtime."""
        try:
            if current_owner() != self._host_owner:
                raise ValueError('process owner differs from manifest owner')
            if self._snapshot() != self._fingerprints:
                raise ValueError('host-owned path fingerprint changed')
        except OSError:
            raise ValueError('host-owned filesystem cannot be verified') from None
