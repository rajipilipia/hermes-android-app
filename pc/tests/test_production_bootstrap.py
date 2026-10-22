"""Bootstrap tracer bullets: synthetic stdlib seams, never original runtime imports."""
from __future__ import annotations

import importlib
import importlib.util
import json
import os
from pathlib import Path
import sys
import tempfile
import threading
from types import ModuleType, SimpleNamespace
import unittest
from unittest.mock import patch
import weakref

from pc.catalog import CapabilityError, SOURCE_COMMIT
from pc.production_policy import BoundPolicy, current_owner


PROJECT = Path(__file__).resolve().parents[2]
FIXTURES = PROJECT / '.cache' / 'port-checkpoints' / 'pc-bootstrap-repair-fixtures'


class SyntheticWS:
    def __init__(self, identity=None, *, closed=False):
        self.auth_identity = identity
        self.closed = closed


def synthetic_runtime():
    """Explicit stand-ins only; no original source is imported or executed."""
    modules = {name: ModuleType(name) for name in (
        'tui_gateway', 'tui_gateway.ws', 'tui_gateway.transport',
        'tui_gateway.methods_browser_control', 'tui_gateway.contracts',
        'tui_gateway.contracts.base', 'tui_gateway.contracts.registry')}
    modules['tui_gateway.ws'].WSTransport = SyntheticWS
    modules['tui_gateway.methods_browser_control']._is_authenticated_identity = lambda identity: (
        isinstance(identity, dict) and all(isinstance(identity.get(k), str) and identity[k].strip()
                                         for k in ('provider', 'user_id'))
        and (identity['provider'], identity['user_id']) != ('internal', 'internal'))
    modules['tui_gateway.contracts.base'].Params = type('Params', (), {})
    modules['tui_gateway.contracts.base'].Result = type('Result', (), {})
    registry = modules['tui_gateway.contracts.registry']
    registry.METHODS = {}
    def method(name, **kwargs):
        if name in registry.METHODS:
            raise RuntimeError('duplicate synthetic contract')
        value = SimpleNamespace(name=name, **kwargs)
        registry.METHODS[name] = value
        return value
    registry.method = method
    modules['tui_gateway.contracts'].registry = registry
    return modules


class BootstrapTests(unittest.TestCase):
    def setUp(self):
        FIXTURES.mkdir(parents=True, exist_ok=True)
        temporary = tempfile.TemporaryDirectory(prefix='synthetic-', dir=FIXTURES)
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name).resolve()
        self.root = self.base / 'managed'
        self.home = self.root / 'profiles' / 'research'
        self.workspace, self.spool = self.base / 'workspace', self.base / 'spool'
        for path in (self.home, self.workspace, self.spool):
            path.mkdir(parents=True)
        self.manifest = self.base / 'policy.json'
        self.value = {'schemaVersion': 1, 'owner': current_owner(), 'root': str(self.root),
                      'launchProfile': 'research', 'launchHome': str(self.home), 'spool': str(self.spool),
                      'principals': [{'provider': 'fixture', 'user_id': 'alice', 'profiles': {
                          'research': {'expectedHome': str(self.home), 'roots': [str(self.workspace)],
                                       'permissions': ['read']}}}]}
        self.server = SimpleNamespace(_launch_home=lambda: self.home,
                                      _profile_home=lambda name: self.root if name == 'default' else self.home,
                                      _methods={}, _LONG_HANDLERS={'existing'},
                                      _ok=lambda rid, result: {'jsonrpc': '2.0', 'id': rid, 'result': result})
        self.server.register_method = lambda name, handler: self.server._methods.__setitem__(name, handler)
        self.rest = lambda name: self.root if name == 'default' else self.home
        self.modules = synthetic_runtime()
        self.transport = SyntheticWS({'provider': 'fixture', 'user_id': 'alice'})
        self.modules['tui_gateway.transport'].current_transport = lambda: self.transport
        self.patch_modules = patch.dict('sys.modules', self.modules)
        self.patch_modules.start()
        self.addCleanup(self.patch_modules.stop)

    def load(self):
        self.manifest.write_text(json.dumps(self.value), encoding='utf-8')
        return BoundPolicy.load(self.manifest).bind(self.server, self.rest)

    def bootstrap(self, policy=None):
        self.assertIsNotNone(importlib.util.find_spec('pc.production_bootstrap'),
                             'authenticated production bootstrap is missing')
        module = importlib.import_module('pc.production_bootstrap')
        # Exercise the REAL addon owner gate without constructing its runtime/routes.
        from pc.addon import Adapter
        adapter = Adapter.__new__(Adapter)
        adapter.server, adapter.policy = self.server, policy or self.load()
        adapter._connections, adapter._lock = weakref.WeakKeyDictionary(), threading.Lock()
        adapter._closed = False
        return module.Bootstrap(adapter)

    def call(self, bootstrap, params=None):
        return bootstrap.handler(7, {} if params is None else params)['result']

    def test_named_only_launch_returns_exact_metadata_and_default_stays_denied(self):
        bootstrap = self.bootstrap()
        self.assertEqual(self.call(bootstrap), {'status': 200, 'body': {
            'schemaVersion': 1, 'sourceCommit': SOURCE_COMMIT, 'primaryProfile': 'research'}})
        with self.assertRaises(CapabilityError) as error:
            bootstrap.adapter.policy.authorize(self.transport.auth_identity, 'default', 'read', 'same-socket')
        self.assertEqual(error.exception.status, 403)

    def test_only_empty_params_are_accepted_no_caller_authority(self):
        bootstrap = self.bootstrap()
        for params in ({'profile': 'default'}, {'owner': 'research'}, {'principal': 'alice'},
                       {'home': str(self.home)}, {'grant': 'research'}, [], '', 0, True):
            with self.subTest(params=params):
                result = self.call(bootstrap, params)
                self.assertEqual(result['status'], 400)
                self.assertEqual(set(result['body']), {'detail'})
                self.assertNotIn(str(self.base), result['body']['detail'])

    def test_unknown_and_unauthenticated_transports_fail_before_host_probing(self):
        bootstrap = self.bootstrap()
        for transport, status in ((None, 401), (SimpleNamespace(auth_identity=self.transport.auth_identity, closed=False), 401),
                                  (SyntheticWS(), 401), (SyntheticWS({'provider': 'internal', 'user_id': 'internal'}), 401),
                                  (SyntheticWS({'provider': 'fixture', 'user_id': 'alice'}, closed=True), 401),
                                  (SyntheticWS({'provider': 'fixture', 'user_id': 'mallory'}), 403)):
            self.transport = transport
            with self.subTest(status=status), patch.object(bootstrap.adapter.policy, 'validate',
                                                          side_effect=AssertionError('must not probe host')):
                result = self.call(bootstrap)
                self.assertEqual(result['status'], status)
                self.assertEqual(set(result['body']), {'detail'})

    def test_launch_requires_read_and_does_not_choose_another_readable_grant(self):
        writing = self.root / 'profiles' / 'writing'
        writing.mkdir()
        grants = self.value['principals'][0]['profiles']
        grants['research']['permissions'] = ['files.write']
        grants['writing'] = {'expectedHome': str(writing), 'roots': [str(self.workspace)], 'permissions': ['read']}
        self.server._profile_home = lambda name: writing if name == 'writing' else self.home
        self.rest = self.server._profile_home
        result = self.call(self.bootstrap())
        self.assertEqual(result['status'], 403)
        self.assertNotIn('primaryProfile', result['body'])

    def test_current_binding_and_manifest_are_rechecked_on_every_bootstrap(self):
        bootstrap = self.bootstrap()
        self.assertEqual(self.call(bootstrap)['status'], 200)
        self.server._profile_home = lambda name: self.root
        self.assertEqual(self.call(bootstrap)['status'], 403)
        self.server._profile_home = lambda name: self.home
        self.server._launch_home = lambda: self.root
        self.assertEqual(self.call(bootstrap)['status'], 403)
        self.server._launch_home = lambda: self.home
        self.assertEqual(self.call(bootstrap)['status'], 200)
        self.manifest.write_bytes(self.manifest.read_bytes() + b' ')
        self.assertEqual(self.call(bootstrap)['status'], 403)

    def test_registration_close_revokes_retained_handler_and_restores_only_owned_entries(self):
        bootstrap = self.bootstrap()
        module = importlib.import_module('pc.production_bootstrap')
        self.assertTrue(callable(getattr(module, 'install', None)), 'bootstrap registration seam is missing')
        registry = self.modules['tui_gateway.contracts.registry']
        original_handler, original_contract = object(), object()
        self.server._methods['original.rpc'] = original_handler
        registry.METHODS['original.rpc'] = original_contract
        installed = module.install(bootstrap.adapter)
        handler = self.server._methods['desktop.bootstrap']
        self.assertEqual(handler(8, {})['result']['status'], 200)
        self.assertIn('desktop.bootstrap', registry.METHODS)
        installed.close()
        installed.close()
        self.assertEqual(self.server._methods, {'original.rpc': original_handler})
        self.assertEqual(registry.METHODS, {'original.rpc': original_contract})
        self.assertEqual(handler(9, {})['result']['status'], 410)
        self.assertIsNone(installed.adapter, 'closed bootstrap must release its adapter closure')

    def test_registration_collision_and_partial_failure_preserve_existing_registry(self):
        bootstrap = self.bootstrap()
        module = importlib.import_module('pc.production_bootstrap')
        self.assertTrue(callable(getattr(module, 'install', None)), 'bootstrap registration seam is missing')
        registry = self.modules['tui_gateway.contracts.registry']
        sentinel = object()
        for methods, contracts in (({'desktop.bootstrap': sentinel}, {}), ({}, {'desktop.bootstrap': sentinel})):
            self.server._methods.clear()
            self.server._methods.update(methods)
            registry.METHODS.clear()
            registry.METHODS.update(contracts)
            with self.assertRaises(ValueError):
                module.install(bootstrap.adapter)
            self.assertEqual(self.server._methods, methods)
            self.assertEqual(registry.METHODS, contracts)
        self.server._methods.clear()
        registry.METHODS.clear()
        def broken_registration(name, handler):
            self.server._methods[name] = handler
            raise RuntimeError('synthetic registration failure')
        self.server.register_method = broken_registration
        with self.assertRaisesRegex(RuntimeError, 'registration failure'):
            module.install(bootstrap.adapter)
        self.assertEqual(self.server._methods, {})
        self.assertEqual(registry.METHODS, {})

    def test_closed_adapter_and_unexpected_policy_errors_are_sanitized_denials(self):
        bootstrap = self.bootstrap()
        bootstrap.adapter._closed = True
        self.assertEqual(self.call(bootstrap)['status'], 410)
        bootstrap.adapter._closed = False
        with patch.object(bootstrap.adapter, 'owner', side_effect=RuntimeError('private identity/home detail')):
            result = self.call(bootstrap)
        self.assertEqual(result['status'], 403)
        self.assertEqual(set(result['body']), {'detail'})
        self.assertNotIn('private', result['body']['detail'])

    def composition(self, *, builder_failure=False, lifespan_failure=False):
        import asyncio
        from contextlib import asynccontextmanager
        from pc.production_composition import Composition
        policy = self.load()
        events = []
        @asynccontextmanager
        async def original_lifespan(app):
            events.append('original-enter')
            if lifespan_failure:
                raise RuntimeError('synthetic lifespan failure')
            try:
                yield {'original': True}
            finally:
                events.append('original-exit')
        app = SimpleNamespace(state=SimpleNamespace(auth_required=True), routes=[],
                              router=SimpleNamespace(lifespan_context=original_lifespan))
        original_handler, original_contract = object(), object()
        self.server._methods['original.rpc'] = original_handler
        registry = self.modules['tui_gateway.contracts.registry']
        registry.METHODS['original.rpc'] = original_contract
        self.modules['tui_gateway'].server = self.server
        auth = ModuleType('hermes_cli.dashboard_auth')
        auth.list_session_providers = lambda: ['fixture']
        profiles = ModuleType('hermes_cli.web_server_profiles')
        profiles._resolve_profile_dir = self.rest
        patches = patch.dict('sys.modules', {'hermes_cli': ModuleType('hermes_cli'),
                                             'hermes_cli.dashboard_auth': auth,
                                             'hermes_cli.web_server_profiles': profiles})
        patches.start()
        self.addCleanup(patches.stop)
        from pc.addon import Adapter
        adapter = Adapter.__new__(Adapter)
        adapter.server, adapter.policy, adapter.app = self.server, policy, app
        adapter._connections, adapter._lock = weakref.WeakKeyDictionary(), threading.Lock()
        adapter._closed = False
        async def aclose():
            if not adapter._closed:
                events.append('adapter-close')
                adapter._closed = True
        adapter.aclose = aclose
        def install(app, server, policy, **kwargs):
            events.append('adapter-install')
            server._methods['desktop.call'] = object()
            registry.METHODS['desktop.call'] = object()
            server._LONG_HANDLERS = server._LONG_HANDLERS | {'desktop.call'}
            return adapter
        def original_builder(*args, **kwargs):
            events.append('original-builder')
            self.assertIn('desktop.bootstrap', self.server._methods,
                          'bootstrap must be installed before the original builder')
            if builder_failure:
                raise RuntimeError('synthetic builder failure')
            return 'original-server'
        composition = Composition(policy, self.base)
        composition.web = SimpleNamespace(app=app)
        composition.original_builder = original_builder
        for target, value in (('pc.bootstrap.load_pinned_onboarding', lambda path: events.append('onboarding')),
                              ('pc.addon.install', install),
                              ('pc.production_composition.refuse_android_stt', lambda adapter: events.append('stt-guard'))):
            p = patch(target, value)
            p.start()
            self.addCleanup(p.stop)
        return composition, events, original_lifespan

    def test_actual_composition_registers_after_binding_and_preserves_original_lifespan(self):
        import asyncio
        composition, events, original_lifespan = self.composition()
        self.assertEqual(composition.builder('127.0.0.1', 0), 'original-server')
        handler = self.server._methods['desktop.bootstrap']
        self.assertEqual(handler(5, {})['result']['status'], 200)
        with self.assertRaises(ValueError):
            composition.builder('127.0.0.1', 0)
        async def exercise():
            async with composition.web.app.router.lifespan_context(composition.web.app) as state:
                self.assertEqual(state, {'original': True})
            await composition.close()
        asyncio.run(exercise())
        self.assertLess(events.index('original-exit'), events.index('adapter-close'))
        self.assertEqual(events.count('adapter-close'), 1)
        self.assertEqual(set(self.server._methods), {'original.rpc'})
        self.assertEqual(set(self.modules['tui_gateway.contracts.registry'].METHODS), {'original.rpc'})
        self.assertEqual(self.server._LONG_HANDLERS, {'existing'})
        self.assertIs(composition.web.app.router.lifespan_context, original_lifespan)
        self.assertEqual(handler(6, {})['result']['status'], 410)

    def test_original_builder_and_lifespan_failures_revoke_bootstrap_and_close_adapter(self):
        import asyncio
        for phase in ('builder', 'lifespan'):
            with self.subTest(phase=phase):
                composition, events, original_lifespan = self.composition(
                    builder_failure=phase == 'builder', lifespan_failure=phase == 'lifespan')
                try:
                    if phase == 'builder':
                        with self.assertRaisesRegex(RuntimeError, 'synthetic builder failure'):
                            composition.builder()
                    else:
                        composition.builder()
                        async def startup():
                            async with composition.web.app.router.lifespan_context(composition.web.app):
                                self.fail('failing original lifespan yielded')
                        with self.assertRaisesRegex(RuntimeError, 'synthetic lifespan failure'):
                            asyncio.run(startup())
                finally:
                    # Mirrors run()'s outer failure-finally cleanup, before a listener.
                    asyncio.run(composition.close())
                self.assertTrue(composition.adapter._closed)
                self.assertNotIn('desktop.bootstrap', self.server._methods)
                self.assertNotIn('desktop.bootstrap', self.modules['tui_gateway.contracts.registry'].METHODS)
                self.assertIs(composition.web.app.router.lifespan_context, original_lifespan)

    def test_proof_discovers_primary_only_through_authenticated_bootstrap_rpc(self):
        from pc import production_proof as proof
        self.assertTrue(callable(getattr(proof, 'bootstrap_primary', None)),
                        'production proof still supplies a manual profile instead of bootstrap')
        calls, checks = [], []
        def rpc(method, params):
            calls.append((method, params))
            return {'status': 200, 'body': {'schemaVersion': 1, 'sourceCommit': SOURCE_COMMIT,
                                           'primaryProfile': 'writing'}}
        def check(value, label):
            self.assertTrue(value, label)
            checks.append(label)
        self.assertEqual(proof.bootstrap_primary(rpc, check), 'writing')
        self.assertEqual(calls, [('desktop.bootstrap', {})])
        self.assertTrue(checks)
        for reply in ({'status': 403, 'body': {'detail': 'denied'}},
                      {'status': 200, 'body': {'schemaVersion': 1, 'sourceCommit': 'wrong', 'primaryProfile': 'research'}},
                      {'status': 200, 'body': {'schemaVersion': 1, 'sourceCommit': SOURCE_COMMIT,
                                              'primaryProfile': 'research', 'home': '/private'}}):
            with self.subTest(reply=reply), self.assertRaises(AssertionError):
                proof.bootstrap_primary(lambda method, params: reply, check)

    def test_partial_install_is_revoked_even_without_returned_adapter(self):
        import asyncio
        composition, events, original_lifespan = self.composition()
        from pc import addon
        registry = self.modules['tui_gateway.contracts.registry']
        def failure(*args, **kwargs):
            self.server._methods['desktop.call'] = object()
            registry.METHODS['desktop.call'] = object()
            self.server._LONG_HANDLERS = self.server._LONG_HANDLERS | {'desktop.call'}
            raise RuntimeError('synthetic partial installation')
        with patch.object(addon, 'install', failure):
            with self.assertRaisesRegex(RuntimeError, 'partial installation'):
                composition.builder()
        self.assertIsNone(composition.adapter)
        asyncio.run(composition.close())
        self.assertEqual(set(self.server._methods), {'original.rpc'})
        self.assertEqual(set(registry.METHODS), {'original.rpc'})
        self.assertEqual(self.server._LONG_HANDLERS, {'existing'})
        self.assertIs(composition.web.app.router.lifespan_context, original_lifespan)

    def test_run_failure_restores_preparation_and_revokes_partial_registrations(self):
        from pc import production_composition as production
        composition, events, original_lifespan = self.composition()
        preparation = lambda args, headless: 'original-prepared'
        original_builder = composition.original_builder
        composition.web._build_uvicorn_server = original_builder
        original_prepare_method = composition.prepare
        # The real run() patches main preparation. A minimal synthetic original
        # main drives that seam, then deliberately fails addon installation.
        def prepare(original, args, headless):
            result = original(args, headless)
            composition.web._build_uvicorn_server = composition.builder
            return result
        composition.prepare = prepare
        main = SimpleNamespace(_dashboard_prepare_runtime=preparation)
        def cmd_dashboard(args):
            main._dashboard_prepare_runtime(args, True)
            composition.web._build_uvicorn_server()
        main.cmd_dashboard = cmd_dashboard
        constants = ModuleType('hermes_constants')
        constants.get_process_hermes_home = lambda: self.home
        profiles = ModuleType('hermes_cli.profiles')
        profiles.get_active_profile_name = lambda: 'research'
        dashboard = ModuleType('hermes_cli.subcommands.dashboard')
        def parser_builder(subparsers, **kwargs):
            parser = subparsers.add_parser('serve')
            parser.add_argument('--host')
            parser.add_argument('--port')
            parser.add_argument('--no-open', action='store_true')
            parser.add_argument('--isolated', action='store_true')
            parser.add_argument('-p')
        # Argument parsing itself is not this test's subject; preserve all real
        # cleanup behavior around the synthetic main without runtime imports.
        registry = self.modules['tui_gateway.contracts.registry']
        def failure(*args, **kwargs):
            self.server._methods['desktop.call'] = object()
            registry.METHODS['desktop.call'] = object()
            raise RuntimeError('synthetic partial installation')
        with patch.dict('sys.modules', {'hermes_constants': constants, 'hermes_cli.profiles': profiles,
                                        'hermes_cli.subcommands': ModuleType('hermes_cli.subcommands'),
                                        'hermes_cli.subcommands.dashboard': dashboard}), \
             patch.object(production.BoundPolicy, 'load', return_value=composition.policy), \
             patch.object(production, 'Composition', return_value=composition), \
             patch.object(production, 'verify_source', return_value=self.base), \
             patch.object(production, 'preflight_profile'), \
             patch('argparse.ArgumentParser.parse_args', return_value=SimpleNamespace()), \
             patch('pc.addon.install', failure), \
             patch.dict(os.environ, HERMES_DESKTOP='', HERMES_DESKTOP_OWNER_NONCE=''), \
             patch.object(production.sys, 'path', production.sys.path[:]), \
             patch.object(production.importlib, 'import_module', return_value=main):
            dashboard.build_dashboard_parser = parser_builder
            # This test supplies a synthetic fresh main. Other full-suite cases
            # may already have imported real modules; restore them on context exit.
            for name in ('hermes_cli.main', 'hermes_cli.web_server', 'tui_gateway.server'):
                sys.modules.pop(name, None)
            with self.assertRaisesRegex(RuntimeError, 'partial installation'):
                production.run(upstream=self.base, manifest=self.manifest, mode='serve',
                               host='127.0.0.1', port=0, isolated=True)
        self.assertEqual(set(self.server._methods), {'original.rpc'})
        self.assertEqual(set(registry.METHODS), {'original.rpc'})
        self.assertIs(main._dashboard_prepare_runtime, preparation)
        self.assertIs(composition.web._build_uvicorn_server, original_builder)

    def test_contract_declaration_failure_propagates_without_masking_or_leaking(self):
        bootstrap = self.bootstrap()
        module = importlib.import_module('pc.production_bootstrap')
        registry = self.modules['tui_gateway.contracts.registry']
        with patch.object(registry, 'method', side_effect=RuntimeError('synthetic declaration failure')):
            with self.assertRaises(Exception) as error:
                module.install(bootstrap.adapter)
        self.assertIs(type(error.exception), RuntimeError)
        self.assertEqual(str(error.exception), 'synthetic declaration failure')
        self.assertEqual(self.server._methods, {})
        self.assertEqual(registry.METHODS, {})


if __name__ == '__main__':
    unittest.main()
