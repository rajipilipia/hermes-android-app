"""PC-03 component regressions: pinned source + saved synthetic JSON only.

Handlers are compiled from the pinned source AST; config, discovery and provider
probe seams are fixture-owned. This is not an authenticated ASGI/runtime proof.
"""
from __future__ import annotations

import ast
from contextlib import nullcontext
import importlib
import importlib.util
import json
from pathlib import Path
import tempfile
import types
from typing import Optional
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
UPSTREAM = Path('C:/example/hermes-agent')
MARKER = 'violet-orchard-ledger'
ENDPOINT = 'https://opaque.example.invalid/private/' + MARKER + '?access_token=' + MARKER


def source_functions(relative, names, namespace):
    """Compile exact original function bodies without importing runtime modules."""
    tree = ast.parse((UPSTREAM / relative).read_text(encoding='utf-8'))
    selected = []
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name in names:
            node.decorator_list = []
            selected.append(node)
    if {node.name for node in selected} != set(names):
        raise AssertionError('source-pinned fixture handler missing')
    code = compile(ast.Module(body=selected, type_ignores=[]), str(UPSTREAM / relative), 'exec')
    exec(code, namespace)
    return namespace


class MetadataRepairs(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        evidence = ROOT / '.cache/port-checkpoints'
        evidence.mkdir(parents=True, exist_ok=True)
        cls.fixture_dir = tempfile.TemporaryDirectory(prefix='pc-repair-metadata-', dir=evidence)
        cls.saved = Path(cls.fixture_dir.name) / 'saved-config.json'
        cls.config = {
            'model': {'default': 'vendor/ordinary-model:7b', 'provider': 'custom', 'base_url': ENDPOINT,
                      'api_key': MARKER, 'context_length': 64000},
            'auxiliary': {'vision': {'provider': 'custom', 'model': 'vision-ordinary',
                                     'base_url': ENDPOINT, 'api_key': MARKER, 'reasoning_effort': 'low'}},
        }
        cls.saved.write_text(json.dumps(cls.config), encoding='utf-8')

    @classmethod
    def tearDownClass(cls):
        cls.fixture_dir.cleanup()

    def setUp(self):
        self.saved.write_text(json.dumps(self.config), encoding='utf-8')

    def project(self, name, value):
        self.assertIsNotNone(importlib.util.find_spec('pc.projections'), 'allowlisted metadata DTO module missing')
        module = importlib.import_module('pc.projections')
        self.assertIn(name, module.METADATA_PROJECTIONS, 'required typed metadata projection missing')
        return module.project_metadata(name, value)

    def auxiliary_output(self):
        namespace = {'Optional': Optional, '_profile_scope': lambda _: nullcontext(),
                     'http_failure': lambda *a, **kw: nullcontext(),
                     'load_config': lambda: json.loads(self.saved.read_text(encoding='utf-8')),
                     '_AUX_TASK_SLOTS': ('vision', 'compression'),
                     '_plugin_aux_tasks': lambda: [{'key': 'plugin_task', 'display_name': 'Plugin task',
                         'description': 'Summarize a scene', 'plugin': 'fixture-plugin', 'inherit_from': 'vision'}],
                     'is_local_endpoint': lambda _: False}
        source_functions('hermes_cli/web_routers/models.py', ('get_auxiliary_models', '_main_model_fields'), namespace)
        auxiliary = types.ModuleType('agent.auxiliary_client')
        auxiliary._get_auxiliary_task_config = lambda _: {'provider': 'custom', 'model': 'vision-ordinary',
                                                         'base_url': ENDPOINT, 'api_key': MARKER}
        with patch.dict('sys.modules', {'agent.auxiliary_client': auxiliary}):
            return namespace['get_auxiliary_models']('default')

    def test_auxiliary_saved_and_inherited_endpoint_details_are_absent(self):
        output = self.auxiliary_output()
        self.assertIn(MARKER, json.dumps(output), 'original source must reproduce the PC-03 fixture')
        projected = self.project('model-auxiliary', output)
        self.assertNotIn(MARKER, json.dumps(projected))
        self.assertEqual(projected, {
            'tasks': [
                {'task': 'vision', 'provider': 'custom', 'model': 'vision-ordinary',
                 'reasoning_effort': 'low', 'local_endpoint': False},
                {'task': 'compression', 'provider': 'auto', 'model': '',
                 'reasoning_effort': None, 'local_endpoint': False},
                {'task': 'plugin_task', 'provider': 'auto', 'model': '', 'reasoning_effort': None,
                 'local_endpoint': False, 'label': 'Plugin task', 'hint': 'Summarize a scene',
                 'plugin': 'fixture-plugin', 'inherit_from': 'vision',
                 'effective': {'provider': 'custom', 'model': 'vision-ordinary'}}],
            'main': {'provider': 'custom', 'model': 'vendor/ordinary-model:7b'}})

    def test_model_info_preserves_only_typed_capabilities_and_context(self):
        import logging
        namespace = {'Optional': Optional, 'HTTPException': type('HTTPException', (Exception,), {}),
                     '_log': logging.getLogger('pc-metadata-fixture'),
                     '_load_config_scoped': lambda _: json.loads(self.saved.read_text(encoding='utf-8')),
                     '_bounded_context_length_probe': lambda *a: 128000,
                     '_CAPABILITY_FIELDS': ('supports_tools', 'supports_vision', 'supports_reasoning',
                                           'context_window', 'max_output_tokens', 'model_family')}
        source_functions('hermes_cli/web_routers/models.py', ('get_model_info', '_main_model_fields'), namespace)
        capabilities = types.ModuleType('agent.models_dev')
        capabilities.get_model_capabilities = lambda **kw: types.SimpleNamespace(
            supports_tools=True, supports_vision=False, supports_reasoning=True,
            context_window=128000, max_output_tokens=16000, model_family='ordinary')
        with patch.dict('sys.modules', {'agent.models_dev': capabilities}):
            output = namespace['get_model_info']('default')
        expected = json.loads(json.dumps(output))
        output['base_url'] = ENDPOINT
        output['api_key'] = MARKER
        output['capabilities']['extension'] = {'credential': MARKER}
        projected = self.project('model-info', output)
        self.assertEqual(projected, expected)
        output['capabilities']['model_family'] = {'base_url': ENDPOINT}
        output['capabilities']['supports_tools'] = MARKER
        output['config_context_length'] = True
        projected = self.project('model-info', output)
        self.assertNotIn('model_family', projected['capabilities'])
        self.assertNotIn('supports_tools', projected['capabilities'])
        self.assertNotIn('config_context_length', projected)
        self.assertNotIn(MARKER, json.dumps(projected))

    def test_moa_named_and_flat_views_have_typed_slots_not_opaque_subtrees(self):
        moa_module = types.ModuleType('hermes_cli.moa_config')
        path = UPSTREAM / 'hermes_cli/moa_config.py'
        exec(compile(ast.parse(path.read_text(encoding='utf-8')), str(path), 'exec'), moa_module.__dict__)
        constants = types.ModuleType('hermes_constants')
        constants.VALID_REASONING_EFFORTS = ('minimal', 'low', 'medium', 'high', 'xhigh', 'max', 'ultra')
        source_functions('hermes_constants.py', ('parse_reasoning_effort',), constants.__dict__)
        saved = json.loads(self.saved.read_text(encoding='utf-8'))
        saved['moa'] = {'default_preset': 'daily work', 'active_preset': 'daily work', 'privacy_filter': 'full',
                        'presets': {'daily work': {'enabled': True,
                            'reference_models': [{'provider': 'custom', 'model': 'advisor:7b',
                                'base_url': ENDPOINT, 'api_key': MARKER, 'reasoning_effort': 'high'}],
                            'aggregator': {'provider': 'openrouter', 'model': 'vendor/aggregate'},
                            'reference_temperature': 0.4, 'aggregator_temperature': None,
                            'reference_timeout': 420, 'degraded_reference_policy': 'loud', 'fanout': 'every_n:3'}}}
        self.saved.write_text(json.dumps(saved), encoding='utf-8')
        namespace = {'Optional': Optional, '_profile_scope': lambda _: nullcontext(),
                     'http_failure': lambda *a, **kw: nullcontext(),
                     'load_config': lambda: json.loads(self.saved.read_text(encoding='utf-8'))}
        source_functions('hermes_cli/web_routers/models.py', ('get_moa_models',), namespace)
        with patch.dict('sys.modules', {'hermes_cli.moa_config': moa_module, 'hermes_constants': constants}):
            output = namespace['get_moa_models']('default')
        expected = json.loads(json.dumps(output))
        output['presets']['daily work']['aggregator']['base_url'] = ENDPOINT
        output['presets']['daily work']['reference_models'][0]['credentials'] = {'value': MARKER}
        output['aggregator']['base_url'] = ENDPOINT
        output['presets'][ENDPOINT] = {'provider': MARKER}
        projected = self.project('model-moa', output)
        self.assertEqual(projected, expected)
        output['aggregator']['provider'] = {'value': MARKER}
        output['presets']['daily work']['reference_models'][0]['model'] = ['ordinary', MARKER]
        output['reference_temperature'] = float('nan')
        output['enabled'] = 1
        projected = self.project('model-moa', output)
        self.assertNotIn('provider', projected['aggregator'])
        self.assertNotIn('model', projected['presets']['daily work']['reference_models'][0])
        self.assertNotIn('reference_temperature', projected)
        self.assertNotIn('enabled', projected)
        self.assertNotIn(MARKER, json.dumps(projected))

    def test_tool_config_preserves_presence_and_picker_fields_but_never_env_values(self):
        import asyncio
        tools = types.ModuleType('hermes_cli.tools_config')
        tools.TOOL_CATEGORIES = {'image_gen': {'name': 'Fixture Images'}}
        tools._visible_providers = lambda *a, **kw: [{
            'name': 'Fixture Images', 'badge': 'local', 'tag': 'free', 'post_setup': 'fixture-setup',
            'env_vars': [{'key': 'FIXTURE_KEY', 'prompt': 'Provider credential', 'default': MARKER, 'url': ENDPOINT}],
            'requires_nous_auth': False, 'managed_nous_feature': None}]
        tools._is_provider_active = lambda *a, **kw: True
        tools.provider_readiness_status = lambda *a, **kw: 'ready'
        tools.web_provider_capabilities = lambda _: ['search', 'extract']
        config = types.ModuleType('hermes_cli.config')
        config.get_env_value = lambda _: MARKER
        subscription = types.ModuleType('hermes_cli.nous_subscription')
        subscription.get_nous_subscription_features = lambda *a, **kw: object()
        namespace = {'Optional': Optional, '_profile_scope': lambda _: nullcontext(),
                     '_require_known_toolset': lambda _: None,
                     'load_config': lambda: json.loads(self.saved.read_text(encoding='utf-8')),
                     'asyncio': asyncio}
        source_functions('hermes_cli/web_routers/tools.py', ('get_toolset_config',), namespace)
        with patch.dict('sys.modules', {'hermes_cli.tools_config': tools, 'hermes_cli.config': config,
                                       'hermes_cli.nous_subscription': subscription}):
            output = asyncio.run(namespace['get_toolset_config']('image_gen', 'default'))
        expected = json.loads(json.dumps(output))
        for env in expected['providers'][0]['env_vars']:
            del env['url'], env['default']
        output['providers'][0]['credentials'] = {'key': MARKER}
        projected = self.project('tool-config', output)
        self.assertEqual(projected, expected)
        row = output['providers'][0]
        row['env_vars'][0]['is_set'] = {'value': MARKER}
        row['post_setup'] = ['command', MARKER]
        row['capabilities'] = [{'value': MARKER}, 'search', 'extract']
        output['active_provider'] = {'name': MARKER}
        output.update({'active_search_backend': 'fixture', 'active_extract_backend': None,
                       'search_via_nous': True, 'extract_via_nous': False})
        projected = self.project('tool-config', output)
        self.assertNotIn('is_set', projected['providers'][0]['env_vars'][0])
        self.assertNotIn('post_setup', projected['providers'][0])
        self.assertEqual(projected['providers'][0]['capabilities'], ['search', 'extract'])
        self.assertEqual(projected['active_search_backend'], 'fixture')
        self.assertIsNone(projected['active_extract_backend'])
        self.assertNotIn(MARKER, json.dumps(projected))

    def test_tool_models_keep_picker_metadata_without_nested_payloads(self):
        import asyncio
        saved = json.loads(self.saved.read_text(encoding='utf-8'))
        saved['image_gen'] = {'model': 'fixture-image'}
        self.saved.write_text(json.dumps(saved), encoding='utf-8')
        namespace = {'Optional': Optional, '_profile_scope': lambda _: nullcontext(),
                     'load_config': lambda: json.loads(self.saved.read_text(encoding='utf-8')),
                     '_MODEL_CATALOG_TOOLSETS': {'image_gen': 'image_gen'},
                     '_find_toolset_provider_row': lambda *a: {'name': 'Fixture Images'},
                     '_resolve_toolset_model_plugin': lambda *a: 'fixture-plugin',
                     '_toolset_model_catalog': lambda *a: ({'fixture-image': {'display': 'Fixture Image',
                         'speed': 'fast', 'strengths': 'Line drawings', 'price': 'Free', 'base_url': ENDPOINT}}, 'fixture-image'),
                     'asyncio': asyncio}
        source_functions('hermes_cli/web_routers/tools.py', ('get_toolset_models', '_no_models'), namespace)
        output = asyncio.run(namespace['get_toolset_models']('image_gen', profile='default'))
        expected = json.loads(json.dumps(output))
        output['models'][0]['endpoint'] = ENDPOINT
        projected = self.project('tool-models', output)
        self.assertEqual(projected, expected)
        output['models'][0]['price'] = {'value': MARKER}
        output['default'] = {'base_url': ENDPOINT}
        projected = self.project('tool-models', output)
        self.assertNotIn('price', projected['models'][0])
        self.assertNotIn('default', projected)
        self.assertNotIn(MARKER, json.dumps(projected))
        empty = asyncio.run(namespace['get_toolset_models']('ordinary-toolset', profile='default'))
        self.assertEqual(self.project('tool-models', empty), empty)

    def test_terminal_backend_keeps_health_but_not_probe_detail_or_endpoint(self):
        import asyncio
        namespace = {'Optional': Optional, '_profile_scope': lambda _: nullcontext(),
                     'load_config': lambda: {'terminal': {'backend': 'fixture-terminal'}},
                     '_terminal_backend_rows': lambda: [
                         {'name': 'local', 'label': 'Local', 'description': 'Host shell'},
                         {'name': 'fixture-terminal', 'label': 'Fixture Terminal', 'description': 'Plugin backend'}],
                     '_probe_terminal_backend': lambda *a: ('ready', MARKER + ' ' + ENDPOINT),
                     'asyncio': asyncio}
        source_functions('hermes_cli/web_routers/tools.py', ('get_terminal_backends',), namespace)
        output = asyncio.run(namespace['get_terminal_backends']('default'))
        expected = json.loads(json.dumps(output))
        for row in expected['backends']:
            del row['detail']
        projected = self.project('terminal-backends', output)
        self.assertEqual(projected, expected)
        output['backends'][1]['status'] = {'detail': MARKER}
        output['active'] = [MARKER]
        output['backends'][0]['url'] = ENDPOINT
        projected = self.project('terminal-backends', output)
        self.assertNotIn('status', projected['backends'][1])
        self.assertNotIn('active', projected)
        self.assertNotIn(MARKER, json.dumps(projected))

    def test_mcp_servers_have_typed_auth_selection_and_no_invocation_data(self):
        common = types.ModuleType('tools.mcp_tool_common')
        common.mcp_server_enabled = lambda cfg: cfg.get('enabled', True)
        namespace = {'Any': object, '_redact_mcp_env': lambda env: dict(env)}
        source_functions('hermes_cli/web_server_mcp.py', ('_mcp_server_summary',), namespace)
        cfg = {'url': ENDPOINT, 'command': 'fixture-command ' + MARKER, 'args': [MARKER],
               'env': {'ORDINARY': MARKER}, 'auth': 'oauth', 'tools': ['ordinary_tool'], 'enabled': True}
        with patch.dict('sys.modules', {'tools.mcp_tool_common': common}):
            output = {'servers': [namespace['_mcp_server_summary']('fixture-mcp', cfg, 'fixture-plugin')]}
        projected = self.project('mcp', output)
        self.assertEqual(projected, {'servers': [{'name': 'fixture-mcp', 'transport': 'http', 'auth': 'oauth',
                                                 'tools': ['ordinary_tool'], 'enabled': True,
                                                 'source': 'plugin', 'plugin': 'fixture-plugin'}]})
        row = output['servers'][0]
        row['auth'] = {'access_token': MARKER}
        row['tools'] = ['first_tool', {'nested': MARKER}, 'ordinary_tool']
        row['plugin'] = {'credential': MARKER}
        row['source'] = MARKER
        projected = self.project('mcp', output)
        self.assertNotIn('auth', projected['servers'][0])
        self.assertNotIn('plugin', projected['servers'][0])
        self.assertNotIn('source', projected['servers'][0])
        self.assertEqual(projected['servers'][0]['tools'], ['first_tool', 'ordinary_tool'])
        self.assertNotIn(MARKER, json.dumps(projected))
        row['tools'] = None
        self.assertIsNone(self.project('mcp', output)['servers'][0]['tools'])

    def test_mcp_catalog_omits_bootstrap_urls_defaults_and_diagnostic_text(self):
        namespace = {'Any': object}
        source_functions('hermes_cli/web_routers/mcp.py', ('_catalog_entry_json',), namespace)
        entry = types.SimpleNamespace(
            name='fixture-mcp', description='Read fixture records', connector_slug='fixture', source=ENDPOINT,
            auth=types.SimpleNamespace(type='api_key', env=[types.SimpleNamespace(
                name='FIXTURE_KEY', prompt='Provider credential', required=True)]),
            transport=types.SimpleNamespace(type='stdio', command='fixture-command ' + MARKER,
                                            args=['--credential', MARKER], url=ENDPOINT),
            install=types.SimpleNamespace(url=ENDPOINT, ref=MARKER, bootstrap=[MARKER]),
            tools=types.SimpleNamespace(default_enabled=['ordinary_tool']), post_install=MARKER,
            suggest=types.SimpleNamespace(keywords=['fixture'], hosts=[ENDPOINT], applications=['Fixture App'],
                                          examples=['Find a fixture'], requires_app=True))
        output = {'entries': [namespace['_catalog_entry_json'](entry, True, True)],
                  'diagnostics': [{'name': 'broken-fixture', 'kind': 'invalid', 'message': MARKER + ' ' + ENDPOINT}]}
        projected = self.project('mcp-catalog', output)
        self.assertEqual(projected, {'entries': [{
            'name': 'fixture-mcp', 'description': 'Read fixture records', 'connector_slug': 'fixture',
            'transport': 'stdio', 'auth_type': 'api_key',
            'required_env': [{'name': 'FIXTURE_KEY', 'prompt': 'Provider credential', 'required': True}],
            'default_enabled': ['ordinary_tool'], 'needs_install': True, 'installed': True, 'enabled': True,
            'suggest': {'keywords': ['fixture'], 'applications': ['Fixture App'],
                        'examples': ['Find a fixture'], 'requires_app': True}}],
            'diagnostics': [{'name': 'broken-fixture', 'kind': 'invalid'}]})
        output['entries'][0]['required_env'][0]['prompt'] = {'credential': MARKER}
        output['entries'][0]['suggest']['keywords'] = [{'value': MARKER}, 'fixture']
        output['entries'][0]['default_enabled'] = [ENDPOINT, 'ordinary_tool']
        self.assertNotIn(MARKER, json.dumps(self.project('mcp-catalog', output)))

    def test_toolset_list_preserves_switches_platform_and_tool_names(self):
        # Shape follows the pinned get_toolsets row constructor, not a runtime response.
        output = [{'name': 'fixture-tools', 'label': 'Fixture Tools', 'description': 'Fixture toolset',
                   'platform': 'cli', 'platform_label': 'CLI', 'enabled': True, 'available': True,
                   'configured': False, 'tools': ['ordinary_tool'], 'env': {'value': MARKER}}]
        expected = [{k: v for k, v in output[0].items() if k != 'env'}]
        self.assertEqual(self.project('toolsets', output), expected)
        output[0]['tools'] = [{'credential': MARKER}, 'ordinary_tool']
        output[0]['configured'] = {'value': MARKER}
        projected = self.project('toolsets', output)
        self.assertEqual(projected[0]['tools'], ['ordinary_tool'])
        self.assertNotIn('configured', projected[0])
        self.assertNotIn(MARKER, json.dumps(projected))
        self.assertEqual(self.project('toolsets', {'tools': MARKER}), [])

    def test_source_nullable_capabilities_and_ordinary_display_punctuation_are_preserved(self):
        info = {'model': 'ordinary-model', 'capabilities': {'supports_tools': True,
                'supports_vision': None, 'supports_reasoning': None, 'max_output_tokens': None}}
        self.assertEqual(self.project('model-info', info), info)
        config = {'providers': [{'name': 'Search & Extract', 'env_vars': [
            {'key': 'FIXTURE_KEY', 'prompt': 'Which account? 100% local #1', 'is_set': False}]}]}
        self.assertEqual(self.project('tool-config', config), config)
        moa = {'aggregator': {'provider': 'custom', 'model': 'ordinary-model', 'reasoning_effort': 'thinking'}}
        # parse_reasoning_effort's dict form allows provider-specific tiers.
        self.assertEqual(self.project('model-moa', moa), moa)

    def test_integration_map_covers_exactly_the_audited_operation_shapes(self):
        module = importlib.import_module('pc.projections')
        self.assertTrue(hasattr(module, 'METADATA_OPERATION_PROJECTIONS'), 'catalog hook map missing')
        expected = {
            'GET /api/model/info': 'model-info', 'GET /api/model/auxiliary': 'model-auxiliary',
            'GET /api/model/moa': 'model-moa',
            'GET /api/tools/toolsets': 'toolsets',
            'GET /api/tools/toolsets/{name}/config': 'tool-config',
            'GET /api/tools/toolsets/{name}/models': 'tool-models',
            'GET /api/tools/terminal/backends': 'terminal-backends',
            'GET /api/mcp/servers': 'mcp', 'GET /api/mcp/catalog': 'mcp-catalog'}
        self.assertEqual(dict(module.METADATA_OPERATION_PROJECTIONS), expected)
        self.assertEqual(set(expected.values()), set(module.METADATA_PROJECTIONS))
        with self.assertRaises(ValueError):
            module.project_metadata('redact', {'value': MARKER})

    def test_endpoint_omission_does_not_depend_on_secret_spellings_or_url_syntax(self):
        endpoints = ['https://example.invalid/private/' + MARKER,
                     'https://user:' + MARKER + '@example.invalid/v1',
                     'plain-opaque-' + MARKER, 'unix:/' + MARKER, '//' + MARKER + '/v1']
        endpoints.extend('https://example.invalid/?' + key + '=' + MARKER
                         for key in ('access_token', 'refresh_token', 'password', 'unrecognized'))
        for endpoint in endpoints:
            with self.subTest(endpoint=endpoint):
                saved = json.loads(json.dumps(self.config))
                saved['auxiliary']['vision']['base_url'] = endpoint
                self.saved.write_text(json.dumps(saved), encoding='utf-8')
                output = self.auxiliary_output()
                projected = self.project('model-auxiliary', output)
                self.assertNotIn(MARKER, json.dumps(projected))
                self.assertNotIn('base_url', projected['tasks'][0])
                self.assertEqual(projected['tasks'][0]['model'], 'vision-ordinary')

    def test_auxiliary_allowed_keys_cannot_transport_arbitrary_nested_values(self):
        output = self.auxiliary_output()
        row = output['tasks'][2]
        for key in ('task', 'provider', 'model', 'label', 'hint', 'plugin', 'inherit_from', 'reasoning_effort'):
            row[key] = {'credentials': MARKER}
        row['local_endpoint'] = {'value': MARKER}
        row['effective'] = {'provider': {'key': MARKER}, 'model': [MARKER], 'base_url': ENDPOINT}
        output['main'] = {'provider': [MARKER], 'model': {'key': MARKER}, 'base_url': ENDPOINT}
        self.assertNotIn(MARKER, json.dumps(self.project('model-auxiliary', output)))
        self.assertEqual(self.project('model-auxiliary', {'tasks': [{'effective': [MARKER]}]}), {'tasks': [{}]})

    def test_projection_is_nonmutating_nonaliasing_and_bounded_for_bad_shapes(self):
        original = self.auxiliary_output()
        before = json.loads(json.dumps(original))
        projected = self.project('model-auxiliary', original)
        self.assertEqual(original, before)
        self.assertEqual(self.project('model-auxiliary', projected), projected)
        projected['tasks'][0]['model'] = 'changed-fixture'
        self.assertEqual(original['tasks'][0]['model'], 'vision-ordinary')
        module = importlib.import_module('pc.projections')
        for name in module.METADATA_PROJECTIONS:
            for malformed in (None, 'opaque-' + MARKER, 1, True):
                with self.subTest(projection=name, malformed=malformed):
                    self.assertEqual(self.project(name, malformed), [] if name == 'toolsets' else {})
        self.assertEqual(self.project('model-auxiliary', {'tasks': [None] * 4097}), {})
        bad_moa = {'fanout': {'value': MARKER}, 'enabled': 1, 'presets': [MARKER],
                   'reference_models': MARKER, 'aggregator': [MARKER],
                   'reference_temperature': float('inf'), 'reference_timeout': True}
        self.assertEqual(self.project('model-moa', bad_moa), {})

    def test_source_fixture_handlers_match_the_reviewed_upstream_bytes(self):
        import hashlib
        expected = {
            'hermes_cli/web_routers/models.py': '7250d2b17addca12b3e2d50b1b019dec96cbec03b7227de186f35810bbdd9d73',
            'hermes_cli/moa_config.py': 'e75d7d6f1c4f56c5add9c0b9055596e0d95c769fa58364e5f2e364d67780c0df',
            'hermes_cli/web_routers/tools.py': '731686aef7847d564b0ac6eda01fa874f1446e437de7ac2128319dfaf6ccf2ad',
            'hermes_cli/web_routers/mcp.py': 'b3832e7b6f2466f8c50abb806e09a920f2b500802afb30a7a16221b59d6eff2d',
            'hermes_cli/web_server_mcp.py': '5c6fc24bea98f504d9b246aa3bbb3ef064d4585848c74ba3bb1bd0d50c2c9811',
            'hermes_constants.py': '8d55a41452b625061f1f2e2f507a7e7ffb2a396e711afcc7aee28b03a6e8fa9d',
        }
        for relative, digest in expected.items():
            with self.subTest(source=relative):
                self.assertEqual(hashlib.sha256((UPSTREAM / relative).read_bytes()).hexdigest(), digest)

    def test_auxiliary_source_stringification_cannot_reintroduce_nested_credentials(self):
        saved = json.loads(json.dumps(self.config))
        saved['model']['default'] = [{'api_key': MARKER}]
        saved['model']['provider'] = {'credential': MARKER}
        saved['auxiliary']['vision']['model'] = [{'api_key': MARKER}]
        saved['auxiliary']['vision']['provider'] = {'credential': MARKER}
        self.saved.write_text(json.dumps(saved), encoding='utf-8')
        output = self.auxiliary_output()
        self.assertIsInstance(output['tasks'][0]['provider'], str)
        self.assertIn(MARKER, output['tasks'][0]['provider'])
        projected = self.project('model-auxiliary', output)
        self.assertNotIn(MARKER, json.dumps(projected))
        self.assertNotIn('provider', projected['tasks'][0])
        self.assertNotIn('model', projected['main'])


if __name__ == '__main__':
    unittest.main()
