"""Contract tracer bullets; run under the upstream Python with synthetic state only."""
import asyncio
import importlib.util
import unittest
from pathlib import Path


class FirstCapability(unittest.TestCase):
    def test_catalog_has_typed_profiles_and_rejects_raw_voice(self):
        spec = importlib.util.find_spec('pc.catalog')
        self.assertIsNotNone(spec, 'finite PC operation catalog has not been implemented')
        from pc.catalog import OPERATIONS, validate_call, CapabilityError
        call = validate_call({'operation': 'GET /api/profiles', 'profile': 'default'})
        self.assertEqual(call.operation.path, '/api/profiles')
        with self.assertRaises(CapabilityError):
            validate_call({'operation': 'GET /api/audio/voice-config', 'profile': 'default'})


class TypedValidation(unittest.TestCase):
    def test_files_and_settings_have_bounded_typed_arguments(self):
        from pc.catalog import OPERATIONS, validate_call, CapabilityError
        self.assertIn('POST /api/fs/write-text', OPERATIONS)
        call = validate_call({'operation': 'POST /api/fs/write-text', 'profile': 'default',
                              'body': {'path': 'notes.txt', 'content': 'hello'}})
        self.assertEqual(call.body['content'], 'hello')
        for field in ('headers', 'url', 'method', 'principal', 'connectionId'):
            with self.subTest(field=field), self.assertRaises(CapabilityError):
                validate_call({'operation': 'GET /api/profiles', 'profile': 'default', field: 'x'})
        for settings in ({'model': {'api_key': 'synthetic'}}, {'mcp_servers': {}}, {'terminal': {'backend': 'ssh'}}):
            with self.subTest(settings=settings), self.assertRaises(CapabilityError):
                validate_call({'operation': 'PUT /api/config', 'profile': 'default', 'body': {'config': settings}})
        with self.assertRaises(CapabilityError):
            validate_call({'operation': 'GET /api/sessions/{session_id}/messages', 'profile': 'default',
                           'pathParams': {'session_id': 'good%2f..'}, 'query': {'limit': 999999}})


class OwnershipAndPaths(unittest.TestCase):
    def test_authenticated_owner_and_workspace_boundary(self):
        self.assertIsNotNone(importlib.util.find_spec('pc.policy'), 'owner policy missing')
        from pc.catalog import CapabilityError
        from pc.policy import Policy
        import tempfile
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[2] / '.cache') as directory:
            root = Path(directory)
            workspace = root / 'workspace'
            workspace.mkdir()
            policy = Policy.from_dict({'principals': [{'provider': 'lab', 'user_id': 'alice',
                                      'profiles': {'default': {'roots': [str(workspace)], 'permissions': ['read', 'files.write']}}}]},
                                      forbidden_roots=[root / 'home'])
            owner = policy.authorize({'provider': 'lab', 'user_id': 'alice'}, 'default', 'read', 'connection-A')
            self.assertEqual(policy.path(owner, 'a.txt'), str(workspace / 'a.txt'))
            for path in ('../secret', '%2e%2e/secret', 'https://example.com/a', '//server/share/a', '.env', 'config.yaml', 'foo:bar', str(root / 'outside')):
                with self.subTest(path=path), self.assertRaises(CapabilityError):
                    policy.path(owner, path)
            for identity, profile, permission in ((None, 'default', 'read'), ({'provider': 'lab', 'user_id': 'mallory'}, 'default', 'read'),
                                                    ({'provider': 'lab', 'user_id': 'alice'}, 'other', 'read'),
                                                    ({'provider': 'lab', 'user_id': 'alice'}, 'default', 'settings.write')):
                with self.subTest(identity=identity, profile=profile, permission=permission), self.assertRaises(CapabilityError):
                    policy.authorize(identity, profile, permission, 'connection-A')


if __name__ == '__main__':
    unittest.main()
