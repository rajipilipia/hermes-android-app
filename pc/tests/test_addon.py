"""Runtime adapter tests. The real upstream composition is exercised by pc.prove."""
import importlib.util
from pathlib import Path
import unittest


class AdapterExists(unittest.TestCase):
    def test_addon_exposes_real_install_seam(self):
        self.assertIsNotNone(importlib.util.find_spec('pc.addon'), 'registered RPC adapter missing')
        from pc.addon import install
        self.assertTrue(callable(install))


class StreamAndProjectionTests(unittest.TestCase):
    def test_mcp_projection_does_not_copy_command_args_or_urls(self):
        import pc.addon as addon
        self.assertTrue(hasattr(addon, 'project_mcp'), 'safe MCP DTO projection missing')
        value = {'servers': [{'name': 'test', 'transport': 'stdio', 'enabled': True,
                            'args': ['--password', 'plain-synthetic-secret'], 'command': 'token-in-command',
                            'url': 'https://user:password@example.test/?token=hidden', 'env': {'A': 'secret'}}]}
        result = addon.project_mcp(value)
        self.assertEqual(result, {'servers': [{'name': 'test', 'transport': 'stdio', 'enabled': True}]})

    def test_downloads_fence_connection_size_release_and_expiry(self):
        import io
        import tempfile
        from pc.addon import Downloads
        from pc.catalog import CapabilityError
        from pc.policy import Owner
        from unittest.mock import patch
        class Transport:
            closed = False
        transport = Transport()
        owner = Owner('lab', 'alice', 'default', 'A', (), frozenset({'read'}))
        other = Owner('lab', 'alice', 'default', 'B', (), frozenset({'read'}))
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[2] / '.cache') as directory:
            store = Downloads(directory)
            handle = store.put(owner, io.BytesIO(b'abc'), 3, 'text/plain', transport)['downloadId']
            with self.assertRaises(CapabilityError):
                store.read(other, handle, 0, 2)
            with self.assertRaises(CapabilityError):
                store.read(owner, handle, 4, 2)
            self.assertEqual(store.read(owner, handle, 1, 2)['dataBase64'], 'YmM=')
            with patch('pc.addon.time.monotonic', return_value=10**12):
                with self.assertRaises(CapabilityError):
                    store.read(owner, handle, 0, 2)
            store.close()


if __name__ == '__main__':
    unittest.main()
