"""Synthetic PC-01/PC-02 regressions. No active profile or network is used."""
from __future__ import annotations

import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from pc.catalog import CapabilityError
from pc.policy import Policy

ROOT = Path(__file__).resolve().parents[2]


class SyntheticWorkspace(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='pc-repair-path-', dir=ROOT / '.cache' / 'port-checkpoints')
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.workspace = self.base / 'workspace'
        self.workspace.mkdir()
        self.policy = Policy.from_dict({'principals': [{'provider': 'fixture', 'user_id': 'alice',
            'profiles': {'default': {'roots': [str(self.workspace)], 'permissions': ['read', 'files.write']}}}]})
        self.owner = self.policy.authorize({'provider': 'fixture', 'user_id': 'alice'}, 'default', 'read', 'connection')

    def denied(self, action, status=403):
        with self.assertRaises(CapabilityError) as caught:
            action()
        self.assertEqual(caught.exception.status, status)

    def junction(self, link, target):
        if os.name != 'nt':
            link.symlink_to(target, target_is_directory=True)
        else:
            result = subprocess.run(['cmd.exe', '/d', '/c', 'mklink', '/J', str(link), str(target)],
                                    capture_output=True, text=True, check=False)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.addCleanup(lambda: link.rmdir() if os.name == 'nt' and link.exists() else link.unlink(missing_ok=True))


class PathPolicyRepairs(SyntheticWorkspace):
    def test_python311_in_root_junction_to_sensitive_directory_is_denied(self):
        sensitive = self.workspace / '.git'
        sensitive.mkdir()
        (sensitive / 'config').write_text('SYNTHETIC DENIED CONTENT', encoding='utf-8')
        alias = self.workspace / 'ordinary-alias'
        self.junction(alias, sensitive)
        self.denied(lambda: self.policy.path(self.owner, str(alias / 'config')))

    def test_python311_reparse_attribute_is_checked_without_is_junction(self):
        directory = self.workspace / 'ordinary'
        directory.mkdir()
        actual = Path.lstat
        def attributes(path, *args, **kwargs):
            st = actual(path, *args, **kwargs)
            if path == directory:
                class Reparse:
                    st_mode = st.st_mode
                    st_file_attributes = getattr(st, 'st_file_attributes', 0) | 0x400
                return Reparse()
            return st
        with patch.object(Path, 'lstat', attributes):
            self.denied(lambda: self.policy.path(self.owner, str(directory / 'note.txt')))

    def test_final_resolved_sensitive_components_are_independently_denied(self):
        normal = self.workspace / 'normal.txt'
        normal.write_text('safe', encoding='utf-8')
        actual = Path.resolve
        def resolved(path, *args, **kwargs):
            if path == normal:
                return self.workspace / '.git' / 'config'
            return actual(path, *args, **kwargs)
        with patch.object(Path, 'resolve', resolved):
            self.denied(lambda: self.policy.path(self.owner, str(normal)))


@unittest.skipUnless(os.name == 'nt', 'Windows handle-sharing regression')
class PinnedPathRepairs(SyntheticWorkspace):
    def filesystem(self):
        import importlib.util
        self.assertIsNotNone(importlib.util.find_spec('pc.filesystem'), 'use-time filesystem boundary missing')
        from pc import filesystem
        return filesystem

    def test_parent_and_file_replacement_are_blocked_through_original_path_open(self):
        fs = self.filesystem()
        directory = self.workspace / 'documents'
        directory.mkdir()
        target = directory / 'note.txt'
        target.write_text('SAFE', encoding='utf-8')
        with fs.pin_paths(self.policy, self.owner, [str(target)]):
            with self.assertRaises(PermissionError):
                directory.rename(self.workspace / 'moved')
            with self.assertRaises(PermissionError):
                target.unlink()
            self.assertEqual(target.read_text(encoding='utf-8'), 'SAFE')
        target.unlink()
        directory.rename(self.workspace / 'moved')

    def test_swap_after_admission_is_rejected_at_actual_use(self):
        fs = self.filesystem()
        directory = self.workspace / 'documents'
        directory.mkdir()
        target = directory / 'note.txt'
        approved = self.policy.path(self.owner, str(target))
        directory.rmdir()
        secret = self.workspace / '.git'
        secret.mkdir()
        (secret / 'note.txt').write_text('DO NOT READ', encoding='utf-8')
        self.junction(directory, secret)
        def read():
            with fs.pin_paths(self.policy, self.owner, [approved]):
                return Path(approved).read_text(encoding='utf-8')
        self.denied(read)

    def test_hardlinked_regular_file_alias_is_denied_at_use(self):
        fs = self.filesystem()
        secret = self.workspace / '.env'
        secret.write_text('SYNTHETIC', encoding='utf-8')
        alias = self.workspace / 'ordinary.txt'
        os.link(secret, alias)
        self.denied(lambda: fs.read_bytes(self.policy, self.owner, str(alias), maximum=1024))


@unittest.skipUnless(os.name == 'nt', 'Windows filesystem integration')
class LocalRouteRepairs(SyntheticWorkspace):
    def test_original_route_validators_and_middleware_wrap_safe_file_implementation(self):
        from pc import filesystem as fs
        self.assertTrue(hasattr(fs, 'install_guarded_routes'), 'guarded original route integration missing')
        import asyncio
        import contextvars
        import sys
        import httpx
        from fastapi import FastAPI, Request
        sys.path.insert(0, 'C:/example/hermes-agent')
        from hermes_cli.web_routers import files, git
        app = FastAPI()
        app.include_router(files.router)
        app.include_router(git.router)
        principal = contextvars.ContextVar('fixture-owner', default=None)
        observations = []
        @app.middleware('http')
        async def identity(request: Request, call_next):
            observations.append(principal.get().user_id)
            request.state.session = {'provider': 'fixture', 'user_id': 'alice'}
            return await call_next(request)
        fs.install_guarded_routes(app, self.policy, principal.get)
        async def run():
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(transport=transport, base_url='http://fixture.invalid') as client:
                token = principal.set(self.owner)
                try:
                    target = str(self.workspace / 'note.txt')
                    written = await client.post('/api/fs/write-text', json={'path': target, 'content': 'fixture text'})
                    self.assertEqual(written.status_code, 200, written.text)
                    self.assertEqual(written.json()['byteSize'], len(b'fixture text'))
                    read = await client.get('/api/fs/read-text', params={'path': target})
                    self.assertEqual(read.status_code, 200, read.text)
                    self.assertEqual(read.json()['text'], 'fixture text')
                    invalid = await client.post('/api/fs/write-text', json={'path': target})
                    self.assertEqual(invalid.status_code, 422)
                    # Dangerous old upload/mkdir paths are explicitly withheld,
                    # never forwarded and never reported as empty success.
                    for route, body in (('/api/files/mkdir', {'path': str(self.workspace / 'nested')}),
                                        ('/api/files/upload', {'path': target, 'data_url': 'data:text/plain;base64,eA=='})):
                        denied = await client.post(route, json=body)
                        self.assertEqual(denied.status_code, 403, denied.text)
                finally:
                    principal.reset(token)
        asyncio.run(run())
        for operation in ('/api/git/status', '/api/git/review/commit-context'):
            # The installed original route itself, not just a helper, is gated.
            async def denied_request():
                token = principal.set(self.owner)
                try:
                    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://fixture.invalid') as client:
                        response = await client.get(operation, params={'path': str(self.workspace)})
                        self.assertEqual(response.status_code, 403, response.text)
                finally:
                    principal.reset(token)
            asyncio.run(denied_request())
        self.assertEqual(observations, ['alice'] * 7)

    def test_partial_route_installation_is_rejected_before_any_handler_changes(self):
        from pc import filesystem as fs
        from fastapi import FastAPI
        import sys
        sys.path.insert(0, 'C:/example/hermes-agent')
        from hermes_cli.web_routers import files
        app = FastAPI()
        app.include_router(files.router)
        before = {route.path: route.dependant.call for route in app.routes if hasattr(route, 'dependant')}
        with self.assertRaises(ValueError):
            fs.install_guarded_routes(app, self.policy, lambda: self.owner)
        self.assertEqual(before, {route.path: route.dependant.call for route in app.routes if hasattr(route, 'dependant')})

    def test_original_sensitive_filename_rules_are_not_lost_by_local_route_replacement(self):
        from pc import filesystem as fs
        for name in ('.envrc', '.git-credentials', 'google_token.json', 'mcp-tokens/server.json'):
            target = self.workspace / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text('SYNTHETIC PRIVATE', encoding='utf-8')
            with self.subTest(name=name):
                self.denied(lambda: fs.read_bytes(self.policy, self.owner, str(target), maximum=1024))

    def test_download_uses_captured_bytes_not_a_deferred_path_open(self):
        from pc import filesystem as fs
        self.assertTrue(hasattr(fs, '_local_file_result'))
        import asyncio
        target = self.workspace / 'artifact.bin'
        target.write_bytes(b'ORIGINAL BYTES')
        response = fs._local_file_result(self.policy, self.owner, '/api/fs/download', {'path': str(target)})
        target.write_bytes(b'REPLACED AFTER RESPONSE')
        async def consume():
            chunks = []
            async for chunk in response.body_iterator:
                chunks.append(chunk)
            return b''.join(chunks)
        self.assertEqual(asyncio.run(consume()), b'ORIGINAL BYTES')

    def test_atomic_write_guard_has_no_unpinned_cleanup_path(self):
        from pc import filesystem as fs
        target = self.workspace / 'note.txt'
        removed = []
        actual = Path.unlink
        def unlink(path, *args, **kwargs):
            if path.name.startswith('.pc-guard-'):
                removed.append(path)
            return actual(path, *args, **kwargs)
        with patch.object(Path, 'unlink', unlink):
            fs.atomic_write_text(self.policy, self.owner, str(target), 'safe')
        self.assertEqual(len(removed), 1, 'never re-delete a sentinel path after releasing directory guards')


@unittest.skipUnless(os.name == 'nt', 'Windows Git metadata guard')
class GitScopeRepairs(SyntheticWorkspace):
    def git_scope(self):
        import importlib.util
        self.assertIsNotNone(importlib.util.find_spec('pc.git_scope'), 'confined Git capability gate missing')
        from pc import git_scope
        return git_scope

    def repository(self):
        metadata = self.workspace / '.git'
        (metadata / 'refs' / 'heads').mkdir(parents=True)
        (metadata / 'HEAD').write_text('ref: refs/heads/main\n', encoding='utf-8')
        (metadata / 'refs' / 'heads' / 'main').write_text('1' * 40 + '\n', encoding='utf-8')
        return metadata

    def test_parent_repository_for_subdirectory_grant_is_explicitly_denied(self):
        git = self.git_scope()
        metadata = self.repository()
        (metadata / 'index').write_bytes(b'SYNTHETIC OUTSIDE-GRANT STAGED CONTENT')
        allowed = self.workspace / 'allowed'
        allowed.mkdir()
        from dataclasses import replace
        owner = replace(self.owner, roots=(allowed,))
        for route in ('status', 'branches', 'worktrees', 'review/commit-context', 'review/list', 'review/diff'):
            with self.subTest(route=route):
                self.denied(lambda: git.git_read(self.policy, owner, '/api/git/' + route, {'path': str(allowed)}))

    def test_opaque_aggregate_diffs_never_return_sensitive_content_or_empty_success(self):
        git = self.git_scope()
        self.repository()
        (self.workspace / '.env').write_text('SYNTHETIC DENIED CONTENT', encoding='utf-8')
        for route in ('status', 'review/commit-context', 'review/list', 'review/diff', 'file-diff'):
            with self.subTest(route=route):
                self.denied(lambda: git.git_read(self.policy, self.owner, '/api/git/' + route,
                                               {'path': str(self.workspace), 'file': '.env'}))

    def test_normal_repository_metadata_remains_available_without_config_or_subprocess(self):
        git = self.git_scope()
        self.repository()
        (self.workspace / '.git' / 'config').write_text('[include]\n path = ../outside-secret\n', encoding='utf-8')
        with patch('subprocess.run', side_effect=AssertionError('no Git/gh/config/filter execution')):
            branches = git.git_read(self.policy, self.owner, '/api/git/branches', {'path': str(self.workspace)})
            self.assertEqual(branches['branches'][0]['name'], 'main')
            self.assertEqual(branches['branches'][0]['worktreePath'], str(self.workspace))
            result = git.git_read(self.policy, self.owner, '/api/git/review/rev-parse',
                                  {'path': str(self.workspace), 'ref': 'HEAD'})
            self.assertEqual(result, {'sha': '1' * 40})
            worktrees = git.git_read(self.policy, self.owner, '/api/git/worktrees', {'path': str(self.workspace)})
            self.assertEqual(worktrees['worktrees'][0]['path'], str(self.workspace))

    def test_option_looking_or_revision_expression_ref_is_not_interpreted(self):
        git = self.git_scope()
        self.repository()
        for ref in ('--local-env-vars', '--git-dir=outside', 'HEAD:config.yaml', 'HEAD~1', ' main', 'main..other'):
            with self.subTest(ref=ref):
                self.denied(lambda: git.git_read(self.policy, self.owner, '/api/git/review/rev-parse',
                                               {'path': str(self.workspace), 'ref': ref}), status=400)

    def test_external_worktree_and_junction_ref_metadata_are_denied(self):
        git = self.git_scope()
        metadata = self.repository()
        (metadata / 'worktrees' / 'external').mkdir(parents=True)
        (metadata / 'worktrees' / 'external' / 'gitdir').write_text(str(self.base / 'outside' / '.git'), encoding='utf-8')
        self.denied(lambda: git.git_read(self.policy, self.owner, '/api/git/worktrees', {'path': str(self.workspace)}))
        # A metadata alias must not turn an ordinary branch list into an
        # outside-workspace file read (even though .git is private internally).
        refs = metadata / 'refs' / 'heads'
        (refs / 'main').unlink()
        refs.rmdir()
        outside = self.base / 'outside'
        outside.mkdir()
        (outside / 'hidden').write_text('2' * 40, encoding='utf-8')
        self.junction(refs, outside)
        self.denied(lambda: git.git_read(self.policy, self.owner, '/api/git/branches', {'path': str(self.workspace)}))


if __name__ == '__main__':
    unittest.main()
