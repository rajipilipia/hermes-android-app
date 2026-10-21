"""Server-owned grants; a profile name or stored session ID is not authority."""
from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path
import re
import stat
from .catalog import CapabilityError, NAME, validate_schema
from .identifiers import canonical_profile

SENSITIVE_NAMES = frozenset({'.env', '.git', '.ssh', '.aws', '.azure', '.hermes', 'auth.json',
    'config.yaml', 'config.yml', 'credentials', 'credentials.json', 'token.json', 'tokens.json',
    'state.db', 'cookies', 'cookies.json', 'id_rsa', 'id_ed25519', '.npmrc', '.pypirc', '.netrc',
    # Preserve the pinned upstream managed-file read rules in the explicit
    # host-local implementations, including credential subtrees.
    '.envrc', '.git-credentials', 'auth.lock', '.anthropic_oauth.json',
    'google_token.json', 'google_oauth_pending.json', 'google_oauth.json',
    'webhook_subscriptions.json', 'bws_cache.json', 'bws_cache.enc.json',
    'mcp-tokens', 'pairing'})
SENSITIVE_SUFFIXES = ('.pem', '.key', '.keystore', '.p12', '.pfx', '.sqlite', '.db', '.env')
PERMISSIONS = frozenset({'read', 'files.write', 'settings.write', 'sessions.write', 'skills.write',
                         'tools.write', 'mcp.write', 'audio', 'network'})


@dataclass(frozen=True)
class Owner:
    provider: str
    user_id: str
    profile: str
    connection: str
    roots: tuple[Path, ...]
    permissions: frozenset[str]

    @property
    def key(self):
        return self.provider, self.user_id, self.profile, self.connection


class Policy:
    def __init__(self, grants, forbidden_roots):
        for provider, user_id, profile in grants:
            canonical_profile(profile)
        self._grants = dict(grants)
        self.forbidden_roots = tuple(Path(p).resolve() for p in forbidden_roots)

    @classmethod
    def from_dict(cls, value, *, forbidden_roots=()):
        if not isinstance(value, dict) or set(value) != {'principals'} or not isinstance(value['principals'], list):
            raise ValueError('policy must contain only principals')
        grants = {}
        for principal in value['principals']:
            if set(principal) != {'provider', 'user_id', 'profiles'}:
                raise ValueError('invalid policy principal')
            provider, user_id = principal['provider'], principal['user_id']
            if not isinstance(provider, str) or not provider or not isinstance(user_id, str) or not user_id:
                raise ValueError('policy identity required')
            for profile, grant in principal['profiles'].items():
                canonical_profile(profile)
                if set(grant) != {'roots', 'permissions'}:
                    raise ValueError('grant must explicitly set roots and permissions')
                if not isinstance(grant['roots'], list) or not isinstance(grant['permissions'], list):
                    raise ValueError('roots and permissions must be lists')
                roots = tuple(Path(p).resolve(strict=True) for p in grant['roots'])
                if any(not p.is_dir() for p in roots):
                    raise ValueError('workspace root must be an existing directory')
                if not set(grant['permissions']) <= PERMISSIONS:
                    raise ValueError('unlisted permission')
                key = provider, user_id, profile
                if key in grants:
                    raise ValueError('duplicate principal/profile grant')
                grants[key] = roots, frozenset(grant['permissions'])
        return cls(grants, forbidden_roots)

    def authorize(self, identity, profile, permission, connection):
        canonical_profile(profile)
        if not isinstance(identity, dict) or not connection:
            raise CapabilityError(401, 'authenticated connection required')
        provider, user_id = identity.get('provider'), identity.get('user_id')
        if not isinstance(provider, str) or not provider or not isinstance(user_id, str) or not user_id:
            raise CapabilityError(401, 'authenticated connection required')
        grant = self._grants.get((provider, user_id, profile))
        if grant is None or permission not in grant[1]:
            raise CapabilityError(403, 'principal/profile permission denied')
        return Owner(provider, user_id, profile, connection, *grant)

    def profiles(self, owner):
        return frozenset(profile for provider, user_id, profile in self._grants
                         if (provider, user_id) == (owner.provider, owner.user_id))

    def path(self, owner, raw, *, relative_to=None):
        if not isinstance(raw, str) or not raw or len(raw) > 4096 or any(ord(c) < 32 for c in raw):
            raise CapabilityError(400, 'invalid workspace path')
        normalized = raw.replace('\\', '/')
        # Ban ambiguous decoding, UNC/device paths, URL schemes, ADS, traversal,
        # Win32 trailing-dot/space aliases and shell/home variable expansion.
        if '%' in raw or normalized.startswith('//') or re.match(r'^[a-zA-Z][\w+.-]*://', raw):
            raise CapabilityError(400, 'URL or encoded path forbidden')
        if ':' in re.sub(r'^[A-Za-z]:/', '', normalized) or any(c in raw for c in ('~', '$')):
            raise CapabilityError(400, 'ambiguous path forbidden')
        parts = normalized.split('/')
        if any(p == '..' or (p and p != '.' and p.rstrip(' .') != p) for p in parts):
            raise CapabilityError(400, 'path traversal forbidden')
        self._check_sensitive(parts)
        if not owner.roots:
            raise CapabilityError(403, 'no workspace grant')
        path = Path(raw)
        if not path.is_absolute():
            path = Path(relative_to or owner.roots[0]) / path
        # This is admission validation, not an open/use capability. Filesystem
        # integrations must also hold filesystem.pin_paths through actual I/O.
        cursor = path
        while True:
            try:
                info = cursor.lstat()
            except FileNotFoundError:
                info = None
            except OSError:
                raise CapabilityError(403, 'workspace path cannot be verified') from None
            if info is not None and (stat.S_ISLNK(info.st_mode) or
                    getattr(info, 'st_file_attributes', 0) & getattr(stat, 'FILE_ATTRIBUTE_REPARSE_POINT', 0x400)):
                raise CapabilityError(403, 'linked path forbidden')
            if cursor.parent == cursor:
                break
            cursor = cursor.parent
        try:
            target = path.resolve()
        except (OSError, RuntimeError):
            raise CapabilityError(403, 'workspace path cannot be verified') from None
        self._check_sensitive(target.parts)
        if not any(target.is_relative_to(root) for root in owner.roots) or any(target.is_relative_to(p) for p in self.forbidden_roots):
            raise CapabilityError(403, 'path outside owner workspace')
        return str(target)

    @staticmethod
    def _check_sensitive(parts):
        if any(p.lower() in SENSITIVE_NAMES or p.lower().startswith('.env.') or
               p.lower().endswith(SENSITIVE_SUFFIXES) for p in parts):
            raise CapabilityError(403, 'sensitive path forbidden')
