"""Project composition tracer bullets; no original runtime imported here."""
import importlib.util
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch


class ProductionLauncher(unittest.TestCase):
    def test_missing_manifest_refused_before_upstream_import_or_environment_change(self):
        self.assertIsNotNone(importlib.util.find_spec('pc.production_runtime'),
                             'project-owned production composition is missing')
        from pc.production_runtime import run
        before = dict(os.environ)
        with tempfile.TemporaryDirectory(dir=os.environ['TMPDIR']) as temp:
            with self.assertRaises((ValueError, FileNotFoundError)):
                run(upstream=Path(temp), manifest=Path(temp)/'absent.json',
                    mode='serve', host='127.0.0.1', port=0, isolated=True)
        self.assertEqual(before, dict(os.environ))
        self.assertNotIn('hermes_cli.main', sys.modules)

    def test_launch_contract_refuses_implicit_routing_and_loaded_runtime(self):
        from pc.production_runtime import validate_launch
        for change in ({'isolated': False}, {'mode': 'gateway'}, {'port': -1},
                       {'host': ''}, {'port': True}):
            values = dict(mode='serve', host='127.0.0.1', port=0, isolated=True)
            values.update(change)
            with self.subTest(change=change), self.assertRaises(ValueError):
                validate_launch(**values)
        with patch.dict(sys.modules, {'hermes_cli.web_server': object()}):
            with self.assertRaisesRegex(ValueError, 'fresh'):
                validate_launch(mode='serve', host='127.0.0.1', port=0, isolated=True)

    def test_original_named_profile_auth_ticket_rpc_and_lifespan_composition(self):
        import subprocess
        process = subprocess.run([sys.executable, '-B', '-m', 'pc.production_proof'],
                                 cwd=Path(__file__).resolve().parents[2],
                                 capture_output=True, text=True, timeout=150)
        self.assertEqual(process.returncode, 0, process.stdout + process.stderr)
        import json
        records=[json.loads(line) for line in (process.stdout+process.stderr).splitlines()
                 if line.startswith('{"checks":')]
        self.assertEqual(len(records),1,process.stdout+process.stderr)
        evidence = records[0]
        self.assertTrue(evidence['normalLifespan'])
        self.assertTrue(evidence['listenerReleased'])
        self.assertGreaterEqual(evidence['checks'], 15)

    def test_actual_cli_default_auth_rpc_and_original_isolated_lifecycle(self):
        self._assert_actual_cli('default')

    def test_actual_cli_named_auth_rpc_and_original_isolated_lifecycle(self):
        self._assert_actual_cli('named')

    def test_existing_dictation_normal_proof_entry_remains_composable(self):
        self._assert_existing_dictation_proof([])

    def test_existing_dictation_failure_proof_entry_remains_composable(self):
        self._assert_existing_dictation_proof(['--startup-failure'])

    def _assert_existing_dictation_proof(self, flags):
        import json
        import subprocess
        process = subprocess.run([sys.executable, '-B', '-m', 'pc.production_dictation_proof', *flags],
                                 cwd=Path(__file__).resolve().parents[2],
                                 capture_output=True, text=True, timeout=175)
        self.assertEqual(process.returncode, 0, process.stdout + process.stderr)
        records = [json.loads(line) for line in (process.stdout + process.stderr).splitlines()
                   if line.startswith('{"dictationProof":')]
        self.assertEqual(len(records), 1, process.stdout + process.stderr)
        self.assertEqual(records[0]['factoryCalls'], 1)
        self.assertEqual(records[0]['serviceInstances'], 1)
        self.assertTrue(records[0]['synthetic'])
        self.assertFalse(records[0]['liveProviderAcceptance'])

    def _assert_actual_cli(self, selection):
        import json
        import subprocess
        process = subprocess.run([sys.executable, '-B', '-m', 'pc.production_proof', '--cli-' + selection],
                                 cwd=Path(__file__).resolve().parents[2],
                                 capture_output=True, text=True, timeout=150)
        self.assertEqual(process.returncode, 0, process.stdout + process.stderr)
        records = [json.loads(line) for line in (process.stdout + process.stderr).splitlines()
                   if line.startswith('{"checks":')]
        self.assertEqual(len(records), 1, process.stdout + process.stderr)
        evidence = records[0]
        self.assertEqual(evidence['entry'], 'pc.production_runtime CLI')
        self.assertEqual(evidence['primaryProfile'], 'default' if selection == 'default' else 'research')
        self.assertTrue(evidence['listenerReleased'])
        self.assertEqual(evidence['blockedNetworkAttempts'], 0)
        self.assertEqual(evidence['blockedProcessAttempts'], 0)
        self.assertIn('original isolated startup publishes synthetic host rendezvous', evidence['assertions'])
        self.assertIn('adapter prevents managed provisioning and hook-losing reexec', evidence['assertions'])

    def test_original_managed_handoff_reproduces_incompatible_original_profile_argv(self):
        """Use the pinned relaunch builder, not an invented reexec fixture.

        The inherited guard deliberately forbids -I descendants. Execute its
        exact generated Python payload through the guarded child: this isolates
        the original argv-loss defect without disabling descendant activation.
        The independent -I import-path loss is recorded, not bypassed.
        """
        import subprocess
        upstream = Path('C:/example/hermes-agent')
        sys.path.insert(0, str(upstream))
        self.addCleanup(sys.path.remove, str(upstream))
        from hermes_cli.venv_sync import relaunch_command
        original_frame = [str(upstream/'hermes_cli/main.py'), '-p', 'default',
                          'dashboard', '--host', '127.0.0.1', '--port', '0', '--isolated', '--no-open']
        command = relaunch_command(Path(sys.executable), upstream, original_frame,
                                   [sys.executable, '-m', 'pc.production_runtime'], 'pc.production_runtime')
        self.assertIn('-I', command)
        self.assertIn("runpy.run_module('pc.production_runtime'", command[-1])
        self.assertNotIn(str(Path(__file__).resolve().parents[2]), command[-1])
        process = subprocess.run([sys.executable, '-B', '-c', command[-1]],
                                 cwd=Path(__file__).resolve().parents[2],
                                 capture_output=True, text=True, timeout=30)
        self.assertEqual(process.returncode, 2, process.stdout + process.stderr)
        self.assertIn('--upstream', process.stderr)
        self.assertIn('--manifest', process.stderr)
        self.assertIn('required', process.stderr)

    def test_builder_failure_closes_adapter_before_any_listener(self):
        import subprocess
        process=subprocess.run([sys.executable,'-B','-m','pc.production_proof','--startup-failure'],
                               cwd=Path(__file__).resolve().parents[2],capture_output=True,text=True,timeout=150)
        self.assertEqual(process.returncode,0,process.stdout+process.stderr)
        self.assertIn('"failureCleanup": true',process.stdout+process.stderr)

    def test_runtime_lock_rejects_duplicate_and_releases_on_error(self):
        from pc.tests.test_production_policy import BoundPolicyTests
        from pc.production_composition import runtime_lock
        fixture=BoundPolicyTests('test_host_owned_manifest_loads_without_importing_runtime')
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        policy=fixture.load()
        with runtime_lock(policy):
            with self.assertRaises(ValueError):
                with runtime_lock(policy):
                    self.fail('duplicate runtime lock admitted')
        try:
            with runtime_lock(policy):
                raise RuntimeError('synthetic launch failed')
        except RuntimeError:
            pass
        with runtime_lock(policy):
            pass

    def test_original_root_resolution_is_preflighted_before_main_import(self):
        from pc.tests.test_production_policy import BoundPolicyTests
        from pc.production_composition import preflight_profile
        fixture=BoundPolicyTests('test_host_owned_manifest_loads_without_importing_runtime')
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        policy=fixture.load()
        (fixture.home/'config.yaml').write_text('{}',encoding='utf-8')
        sys.path.insert(0,'C:/example/hermes-agent')
        self.addCleanup(sys.path.remove,'C:/example/hermes-agent')
        before='hermes_cli.main' in sys.modules
        with patch.dict(os.environ,HERMES_HOME=str(policy.root)):
            preflight_profile(policy)
            with patch('hermes_constants.get_default_hermes_root',return_value=fixture.workspace):
                with self.assertRaisesRegex(ValueError,'root'):
                    preflight_profile(policy)
        self.assertEqual('hermes_cli.main' in sys.modules,before)

    def test_source_pin_verifies_real_bytes_and_refuses_other_revision(self):
        from pc.production_composition import verify_source
        upstream=Path('C:/example/hermes-agent')
        self.assertEqual(verify_source(upstream),upstream.resolve())
        with patch('pc.production_composition.subprocess.check_output',return_value='wrong-pin'):
            with self.assertRaisesRegex(ValueError,'pin'):
                verify_source(upstream)


if __name__ == '__main__':
    unittest.main()
