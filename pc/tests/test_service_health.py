"""Credential-free adapter liveness on the original public health route."""
import asyncio
import os
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from pc.catalog import SOURCE_COMMIT


class ServiceHealthTests(unittest.TestCase):
    def setUp(self):
        self.original_body = {'ok': True, 'auth_required': True, 'commit': SOURCE_COMMIT}
        async def original():
            return dict(self.original_body)
        self.original = original
        self.route = SimpleNamespace(path='/api/health', methods={'GET'},
                                     dependant=SimpleNamespace(call=original))
        self.methods = {name: object() for name in ('desktop.bootstrap', 'desktop.call',
                                                   'desktop.upload.begin', 'desktop.download.read')}
        self.policy = SimpleNamespace(validate=lambda: None)
        self.adapter = SimpleNamespace(
            app=SimpleNamespace(routes=[self.route], state=SimpleNamespace(auth_required=True)),
            server=SimpleNamespace(_methods=self.methods), policy=self.policy, _closed=False)
        self.bootstrap = SimpleNamespace(_closed=False)

    def install(self):
        from pc.service_health import install
        return install(self.adapter, self.bootstrap)

    def response(self):
        return asyncio.run(self.route.dependant.call())

    def test_original_response_preserved_with_ready_adapter_metadata(self):
        with patch.dict(os.environ, {'HERMES_ANDROID_ADAPTER_GENERATION': 'a' * 32,
                                    'HERMES_ANDROID_ADAPTER_SOURCE_SHA256': 'b' * 64}):
            health = self.install()
        body = self.response()
        self.assertEqual({k: body[k] for k in self.original_body}, self.original_body)
        self.assertEqual(body['androidAdapter'], {'schemaVersion': 1, 'sourceCommit': SOURCE_COMMIT,
                         'generation': 'a' * 32, 'sourceDigest': 'b' * 64, 'ready': True})
        health.close()
        self.assertIs(self.route.dependant.call, self.original)

    def test_manifest_failure_is_unhealthy_without_exception_details(self):
        self.install()
        def denied():
            raise ValueError('private principal, credential and home must not escape')
        self.policy.validate = denied
        body = self.response()
        self.assertFalse(body['androidAdapter']['ready'])
        self.assertNotIn('private principal', repr(body))

    def test_method_removal_or_replacement_is_unhealthy(self):
        self.install()
        original = self.methods['desktop.bootstrap']
        self.methods['desktop.bootstrap'] = object()
        self.assertFalse(self.response()['androidAdapter']['ready'])
        self.methods['desktop.bootstrap'] = original
        self.assertTrue(self.response()['androidAdapter']['ready'])
        del self.methods['desktop.call']
        self.assertFalse(self.response()['androidAdapter']['ready'])

    def test_auth_disabled_or_adapter_bootstrap_closed_is_unhealthy(self):
        self.install()
        for target, attr in ((self.adapter.app.state, 'auth_required'),
                             (self.adapter, '_closed'), (self.bootstrap, '_closed')):
            old = getattr(target, attr)
            setattr(target, attr, not old)
            self.assertFalse(self.response()['androidAdapter']['ready'])
            setattr(target, attr, old)
        self.assertTrue(self.response()['androidAdapter']['ready'])

    def test_closed_retained_handler_is_unhealthy_and_does_not_validate_policy(self):
        health = self.install()
        retained = self.route.dependant.call
        health.close()
        self.policy.validate = lambda: self.fail('closed health must not validate')
        self.assertFalse(asyncio.run(retained())['androidAdapter']['ready'])
        self.assertEqual(self.response(), self.original_body)

    def test_teardown_does_not_remove_later_route_replacement(self):
        health = self.install()
        replacement = object()
        self.route.dependant.call = replacement
        health.close()
        self.assertIs(self.route.dependant.call, replacement)

    def test_invalid_generation_and_digest_are_not_echoed(self):
        with patch.dict(os.environ, {'HERMES_ANDROID_ADAPTER_GENERATION': 'SECRET_VALUE',
                                    'HERMES_ANDROID_ADAPTER_SOURCE_SHA256': 'PRIVATE_PATH'}):
            self.install()
        metadata = self.response()['androidAdapter']
        self.assertIsNone(metadata['generation'])
        self.assertIsNone(metadata['sourceDigest'])
        self.assertNotIn('SECRET_VALUE', repr(metadata))

    def test_requires_exact_existing_route_and_complete_registrations(self):
        self.route.path = '/some/other/route'
        with self.assertRaises(ValueError):
            self.install()
        self.route.path = '/api/health'
        del self.methods['desktop.bootstrap']
        with self.assertRaises(ValueError):
            self.install()


if __name__ == '__main__':
    unittest.main()
