"""Strict vertical startup regressions against imported pinned original services.

Run only under a scrubbed pc-lab HOME, using the read-only upstream venv. No
lifespan, live runtime, provider connection, real credentials or install runs.
"""
from __future__ import annotations

import asyncio
import importlib
import importlib.util
import json
import os
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

from pc.catalog import CapabilityError, SETTINGS
from pc.policy import Policy

ROOT = Path(__file__).resolve().parents[2]
UPSTREAM = Path('C:/example/hermes-agent')
MARKER = 'violet-orchard-startup'
ENDPOINT = 'https://opaque.example.invalid/' + MARKER


class StartupReads(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.home = Path(os.environ['HERMES_HOME']).resolve()
        if not cls.home.is_relative_to(ROOT / '.cache' / 'pc-lab'):
            raise RuntimeError('startup tests require a scrubbed pc-lab HOME')
        sys.path.insert(0, str(UPSTREAM))
        import warnings
        cls.warning_scope = warnings.catch_warnings()
        cls.warning_scope.__enter__()
        cls.addClassCleanup(cls.warning_scope.__exit__, None, None, None)
        # Pinned optional Discord import on Python 3.11; not a startup-service
        # warning. Do not suppress any other category/message/module.
        warnings.filterwarnings('ignore', message="'audioop' is deprecated and slated for removal in Python 3.13",
                                category=DeprecationWarning, module=r'discord\.player')
        cls.workspace = cls.home / 'workspace'
        cls.workspace.mkdir(exist_ok=True)
        cls.policy = Policy.from_dict({'principals': [{
            'provider': 'fixture', 'user_id': 'alice', 'profiles': {
                'default': {'roots': [str(cls.workspace)], 'permissions': ['read']},
                'research': {'roots': [str(cls.workspace)], 'permissions': ['read']}}}]})
        cls.owner = cls.policy.authorize({'provider': 'fixture', 'user_id': 'alice'},
                                         'research', 'read', 'connection')
        (cls.home / 'profiles' / 'research').mkdir(parents=True, exist_ok=True)
        cls.profile_home = cls.home / 'profiles' / 'research'
        (cls.profile_home / 'config.yaml').write_text('{}\n', encoding='utf-8')
        (cls.home / 'config.yaml').write_text('{}\n', encoding='utf-8')

    def setUp(self):
        for home in (self.home, self.profile_home):
            (home / '.env').write_text('', encoding='utf-8')
            (home / 'config.yaml').write_text('{}\n', encoding='utf-8')
            (home / 'gateway_state.json').unlink(missing_ok=True)

    def service(self, operation, query=None, owner=None):
        self.assertIsNotNone(importlib.util.find_spec('pc.startup'), 'startup service module missing')
        module = importlib.import_module('pc.startup')
        return asyncio.run(module.execute_startup(operation, owner or self.owner, query or {}, self.policy))

    def test_defaults_are_original_nonsecret_settings_not_an_empty_success(self):
        from hermes_cli.web_routers.config_env import get_defaults
        original = asyncio.run(get_defaults())
        self.assertIn('max_turns', original['agent'])
        actual = self.service('GET /api/config/defaults')
        # Upstream's unlimited/null max_turns is outside the finite SETTINGS
        # write contract, so it is deliberately omitted rather than fabricated.
        self.assertIsNone(original['agent']['max_turns'])
        self.assertNotIn('max_turns', actual['agent'])
        self.assertEqual(actual['display']['show_reasoning'], original['display']['show_reasoning'])
        self.assertEqual(actual['compression']['enabled'], original['compression']['enabled'])
        self.assertTrue(set(actual) <= set(SETTINGS['properties']))
        self.assertNotIn('model', actual)
        self.assertNotIn('terminal', actual)

    def test_active_profile_presents_selected_owner_without_reading_global_sticky(self):
        from hermes_cli.profiles import get_active_profile
        before = get_active_profile()
        self.assertEqual(self.service('GET /api/profiles/active'),
                         {'active': 'research', 'current': 'research'})
        self.assertEqual(get_active_profile(), before)

    def test_entry_refuses_forged_owner_and_unlisted_query_before_original_service(self):
        from dataclasses import replace
        for owner, query in ((replace(self.owner, profile='foreign'), {}),
                             (replace(self.owner, permissions=frozenset()), {}),
                             (self.owner, {'profile': 'default'})):
            with self.subTest(owner=owner.profile, query=query):
                with self.assertRaises(CapabilityError):
                    self.service('GET /api/config/defaults', query, owner)

    def test_default_cwd_is_first_granted_workspace_not_original_process_cwd(self):
        from hermes_cli.web_routers.files import fs_default_cwd
        # The upstream service is real and demonstrates why ambient forwarding
        # is not an authority boundary; replace only its terminal-backend probe.
        with patch('hermes_cli.web_routers.files._fs_backend', return_value=None):
            original = asyncio.run(fs_default_cwd('research'))
        self.assertIn('cwd', original)
        self.assertEqual(self.service('GET /api/fs/default-cwd'),
                         {'cwd': str(self.workspace.resolve()), 'branch': None})

    def test_schema_uses_original_allowed_fields_with_closed_metadata(self):
        from hermes_cli.web_routers.config_env import get_schema
        original = asyncio.run(get_schema('research'))
        self.assertIn('display.show_reasoning', original['fields'])
        actual = self.service('GET /api/config/schema')
        self.assertEqual(actual['fields']['display.show_reasoning']['type'],
                         original['fields']['display.show_reasoning']['type'])
        self.assertEqual(actual['fields']['tts.provider']['options'],
                         original['fields']['tts.provider']['options'])
        self.assertNotIn('model', actual['fields'])
        self.assertNotIn('terminal.cwd', actual['fields'])
        for key, row in actual['fields'].items():
            group, leaf = key.split('.')
            self.assertIn(leaf, SETTINGS['properties'][group]['properties'])
            self.assertTrue(set(row) <= {'type', 'category', 'description', 'options',
                                         'searchable', 'clearable'})
        self.assertTrue(set(actual['category_order']) <= set(SETTINGS['properties']))

    def test_env_reports_selected_profile_presence_without_values_or_endpoint_previews(self):
        from hermes_cli.web_routers.config_env import get_env_vars
        (self.profile_home / '.env').write_text('OPENAI_API_KEY=' + MARKER + '\nLOCAL_SERVICE=' + ENDPOINT + '\n', encoding='utf-8')
        (self.home / '.env').write_text('ANTHROPIC_API_KEY=foreign-fixture\n', encoding='utf-8')
        original = asyncio.run(get_env_vars('research'))
        self.assertTrue(original['OPENAI_API_KEY']['is_set'])
        self.assertIn('redacted_value', original['OPENAI_API_KEY'])
        actual = self.service('GET /api/env')
        self.assertTrue(actual['OPENAI_API_KEY']['is_set'])
        self.assertFalse(actual['ANTHROPIC_API_KEY']['is_set'])
        self.assertTrue(actual['LOCAL_SERVICE']['is_set'])
        self.assertEqual(actual['OPENAI_API_KEY']['provider'], original['OPENAI_API_KEY']['provider'])
        self.assertNotIn(MARKER, json.dumps(actual))
        for row in actual.values():
            self.assertTrue(set(row) <= {'is_set', 'is_password', 'advanced', 'channel_managed',
                                         'provider_primary', 'custom', 'category', 'description',
                                         'provider', 'provider_label', 'tools', 'provider_profiles'})
            for peer in row.get('provider_profiles', []):
                self.assertTrue(set(peer) <= {'provider', 'provider_label', 'description', 'primary'})

    def test_status_composes_real_local_profile_liveness_without_topology_or_paths(self):
        from hermes_cli.web_routers.status import _resolve_gateway_status
        from hermes_cli.version_info import get_version_info
        import socket
        runtime = {'gateway_state': 'startup_failed', 'exit_reason': ENDPOINT,
                   'platforms': {'telegram': {'state': 'fatal', 'error_message': MARKER,
                                             'writer_pid': 12345}},
                   'served_profiles': ['research', 'foreign'], 'active_agents': 7}
        (self.profile_home / 'gateway_state.json').write_text(json.dumps(runtime), encoding='utf-8')
        async def read():
            with patch.object(socket.socket, 'connect', side_effect=AssertionError('network forbidden')):
                original = await _resolve_gateway_status(self.profile_home, None)
                self.assertIsNotNone(importlib.util.find_spec('pc.startup'))
                actual = await importlib.import_module('pc.startup').execute_startup(
                    'GET /api/status', self.owner, {}, self.policy)
                return original, actual
        original, actual = asyncio.run(read())
        self.assertEqual(actual['version'], get_version_info().base_version)
        self.assertEqual(actual['gateway_running'], original['gateway_running'])
        self.assertEqual(actual['gateway_state'], original['gateway_state'])
        self.assertNotIn(MARKER, json.dumps(actual))
        self.assertNotIn('foreign', json.dumps(actual))
        self.assertTrue(set(actual) <= {'version', 'release_date', 'config_version', 'latest_config_version',
                                       'gateway_running', 'gateway_state', 'gateway_platforms',
                                       'gateway_updated_at', 'gateway_heartbeat_stale_s'})
        for row in actual['gateway_platforms'].values():
            self.assertTrue(set(row) <= {'state', 'status'})

    def test_model_options_uses_real_picker_context_and_declared_models_not_generic_metadata(self):
        from hermes_cli.web_routers.models import get_model_options
        import socket
        cfg = {'model': {'provider': 'custom:lab', 'default': 'vendor/model-a'},
               'custom_providers': [{'name': 'lab', 'base_url': ENDPOINT, 'api_key': MARKER,
                                     'model': 'vendor/model-a', 'models': ['vendor/model-a', 'vendor/model-b'],
                                     'discover_models': False}]}
        (self.profile_home / 'config.yaml').write_text(json.dumps(cfg), encoding='utf-8')
        # A fresh nonempty original models.dev disk cache avoids its cold-fetch.
        (self.profile_home / 'models_dev_cache.json').write_text(
            json.dumps({'fixture': {'id': 'fixture', 'models': {}}}), encoding='utf-8')
        (self.profile_home / 'cache').mkdir(exist_ok=True)
        (self.profile_home / 'cache' / 'model_catalog.json').write_text(
            json.dumps({'version': 1, 'providers': {}}), encoding='utf-8')
        query = {'explicit_only': True, 'include_unconfigured': False, 'refresh': False}
        attempts = []
        def deny(*args, **kwargs):
            import traceback
            attempts.append([frame.name for frame in traceback.extract_stack(limit=35)])
            raise AssertionError('network forbidden')
        async def read():
            # Only the optional background network-warming boundary is replaced;
            # original route, scoped config, inventory and provider rows all run.
            with patch('hermes_cli.inventory._prewarm_pricing_async', return_value=None), \
                 patch.object(socket, 'create_connection', side_effect=deny), \
                 patch.object(socket, 'getaddrinfo', side_effect=deny):
                original = await get_model_options(profile='research', **query)
                actual = await importlib.import_module('pc.startup').execute_startup(
                    'GET /api/model/options', self.owner, query, self.policy)
                return original, actual
        original, actual = asyncio.run(read())
        self.maxDiff = None
        self.assertEqual(attempts, [])
        self.assertEqual(actual['model'], original['model'])
        self.assertEqual(actual['provider'], 'custom:lab')
        row = next(row for row in actual['providers'] if row['slug'] == 'custom:lab')
        self.assertEqual(row['models'], ['vendor/model-a', 'vendor/model-b'])
        self.assertTrue(row['is_current'])
        self.assertNotIn(MARKER, json.dumps(actual))
        self.assertNotIn('api_url', row)
        self.assertIn('capabilities', row)

    def test_slow_picker_deadline_retains_two_worker_slots_until_original_settlement(self):
        import threading
        import time
        module = importlib.import_module('pc.startup')
        release = threading.Event()
        calls = []
        async def slow(**kwargs):
            calls.append(kwargs['profile'])
            await asyncio.to_thread(release.wait, 2)
            return {'providers': [], 'model': 'settled', 'provider': 'fixture'}
        async def read():
            with patch('hermes_cli.web_routers.models.get_model_options', side_effect=slow), \
                 patch.object(module, '_PICKER_TIMEOUT_SECONDS', .02, create=True):
                try:
                    for expected in (504, 504, 429):
                        started = time.monotonic()
                        with self.assertRaises(CapabilityError) as error:
                            await module.execute_startup('GET /api/model/options', self.owner, {}, self.policy)
                        self.assertEqual(error.exception.status, expected)
                        self.assertLess(time.monotonic() - started, .5)
                    self.assertEqual(calls, ['research', 'research'])
                finally:
                    release.set()
                # Let both workers close their own original-service event loops.
                for _ in range(100):
                    if getattr(module, '_picker_pending', 0) == 0:
                        break
                    await asyncio.sleep(.01)
                self.assertEqual(getattr(module, '_picker_pending', 0), 0)
        asyncio.run(read())

    def test_original_defaults_cannot_smuggle_endpoint_or_malformed_leaf_into_allowed_settings(self):
        from hermes_cli.web_routers.config_env import DEFAULT_CONFIG
        with patch.dict(DEFAULT_CONFIG, {
                'display': {'skin': {'credential': MARKER}, 'theme': ENDPOINT,
                            'language': 'en', 'show_reasoning': MARKER},
                'agent': {'max_turns': True}, 'model': {'api_key': MARKER}}, clear=True):
            actual = self.service('GET /api/config/defaults')
        self.assertEqual(actual['display'], {'language': 'en'})
        self.assertEqual(actual['agent'], {})
        self.assertNotIn(MARKER, json.dumps(actual))

    def test_default_cwd_reads_confined_branch_without_git_or_config_execution(self):
        metadata = self.workspace / '.git'
        (metadata / 'refs' / 'heads').mkdir(parents=True, exist_ok=True)
        (metadata / 'HEAD').write_text('ref: refs/heads/main\n', encoding='utf-8')
        (metadata / 'refs' / 'heads' / 'main').write_text('a' * 40 + '\n', encoding='utf-8')
        (metadata / 'config').write_text('[core]\nfsmonitor = arbitrary-command\n', encoding='utf-8')
        with patch('subprocess.run', side_effect=AssertionError('no process execution')):
            actual = self.service('GET /api/fs/default-cwd')
        self.assertEqual(actual, {'cwd': str(self.workspace.resolve()), 'branch': 'main'})

    def test_picker_query_requires_json_booleans_without_truthiness_coercion(self):
        for field in ('explicit_only', 'include_unconfigured', 'refresh'):
            for value in (0, 1, '1', '0', 'false', 'true', None, [], {}):
                with self.subTest(field=field, value=value), \
                     patch('hermes_cli.web_routers.models.get_model_options',
                           side_effect=AssertionError('invalid query reached original service')):
                    with self.assertRaises(CapabilityError) as error:
                        self.service('GET /api/model/options', {field: value})
                    self.assertEqual(error.exception.status, 400)

    def test_model_projection_closes_nested_maps_without_mutating_original_payload(self):
        original = {'provider': 'custom:lab', 'model': 'vendor/a', 'base_url': ENDPOINT,
                    'providers': [{'slug': 'custom:lab', 'name': 'Lab', 'models': ['vendor/a', ENDPOINT],
                                   'api_url': ENDPOINT, 'credentials': {'value': MARKER},
                                   'capabilities': {'vendor/a': {'fast': True, 'reasoning': False,
                                                               'nested': {'credential': MARKER}},
                                                    ENDPOINT: {'fast': True}},
                                   'pricing': {'vendor/a': {'input': '$1.00', 'output': '$2.00', 'free': False,
                                                          'url': ENDPOINT, 'api_key': MARKER}},
                                   'usage': {'accounts': [{'id': MARKER, 'label': MARKER}]}}]}
        before = json.dumps(original, sort_keys=True)
        async def read(**kwargs):
            return original
        with patch('hermes_cli.web_routers.models.get_model_options', side_effect=read):
            actual = self.service('GET /api/model/options')
        self.assertNotIn(MARKER, json.dumps(actual))
        self.assertEqual(actual['providers'][0]['models'], ['vendor/a'])
        self.assertEqual(actual['providers'][0]['capabilities'], {'vendor/a': {'fast': True, 'reasoning': False}})
        self.assertEqual(actual['providers'][0]['pricing'], {'vendor/a': {'input': '$1.00', 'output': '$2.00', 'free': False}})
        self.assertEqual(json.dumps(original, sort_keys=True), before)

    def test_original_http_errors_keep_status_but_never_forward_probe_or_endpoint_detail(self):
        from fastapi import HTTPException
        async def fail(**kwargs):
            raise HTTPException(status_code=503, detail={'endpoint': ENDPOINT, 'error': MARKER})
        with patch('hermes_cli.web_routers.models.get_model_options', side_effect=fail):
            with self.assertRaises(CapabilityError) as error:
                self.service('GET /api/model/options')
        self.assertEqual(error.exception.status, 503)
        self.assertNotIn(MARKER, error.exception.detail)


if __name__ == '__main__':
    unittest.main()
