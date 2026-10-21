"""Synthetic supervisor regressions: never use the live Dashboard or home."""
import importlib.util
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

from pc.catalog import SOURCE_COMMIT


class SourceDigestTests(unittest.TestCase):
    def test_digest_covers_names_bytes_and_only_top_level_pc_source(self):
        self.assertIsNotNone(importlib.util.find_spec('pc.windows_service'),
                             'project-owned supervisor is missing')
        from pc.windows_service import source_digest
        with tempfile.TemporaryDirectory(dir=os.environ['TMPDIR']) as temp:
            root = Path(temp).resolve()
            pc = root / 'pc'
            pc.mkdir()
            (pc / 'a.py').write_bytes(b'first')
            (pc / 'pins.json').write_bytes(b'{}')
            before = source_digest(root)
            self.assertEqual(before, source_digest(root))
            (pc / 'tests').mkdir()
            (pc / 'tests' / 'ignored.py').write_bytes(b'ignored')
            (pc / '__pycache__').mkdir()
            (pc / '__pycache__' / 'a.pyc').write_bytes(b'ignored')
            self.assertEqual(before, source_digest(root))
            (pc / 'a.py').write_bytes(b'second')
            self.assertNotEqual(before, source_digest(root))
            changed = source_digest(root)
            (pc / 'a.py').rename(pc / 'b.py')
            self.assertNotEqual(changed, source_digest(root))
            changed = source_digest(root)
            (pc / 'pins.json').write_bytes(b'{"drift":true}')
            self.assertNotEqual(changed, source_digest(root))
            changed = source_digest(root)
            (pc / 'windows-case.PY').write_bytes(b'Windows imports are case-insensitive')
            self.assertNotEqual(changed, source_digest(root))


class Fixture(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=os.environ['TMPDIR'])
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.project = self.root / 'project'
        self.upstream = self.root / 'upstream'
        self.home = self.root / 'original-home'
        for folder in (self.project / 'pc', self.project / '.cache', self.upstream, self.home):
            folder.mkdir(parents=True)
        (self.project / 'pc' / 'runtime.py').write_text('synthetic', encoding='utf-8')
        self.manifest = self.project / '.cache' / 'manifest.json'
        self.manifest.write_text('{}', encoding='utf-8')
        self.config_path = self.project / '.cache' / 'service.json'

    def raw_config(self):
        from pc.windows_service import source_digest
        python = str(Path(sys.executable).resolve())
        return dict(schemaVersion=1, projectRoot=str(self.project), upstream=str(self.upstream),
                    manifest=str(self.manifest), python=python,
                    pythonPath=[str(self.project), str(self.upstream)],
                    argv=[python, '-B', '-m', 'pc.production_runtime',
                          '--upstream', str(self.upstream), '--manifest', str(self.manifest),
                          '--mode', 'serve', '--host', '127.0.0.1', '--port', '17911',
                          '--isolated', '--skip-build'],
                    port=17911, bindHost='127.0.0.1', home=str(self.home),
                    stateFile=str(self.project / '.cache' / 'service-state.json'),
                    logFile=str(self.project / '.cache' / 'service.log'),
                    updateMarker=str(self.home / '.hermes-update-in-progress'),
                    sourceDigest=source_digest(self.project), sourceCommit=SOURCE_COMMIT)

    def config(self, **changes):
        from pc.windows_service import load_config
        value = self.raw_config()
        value.update(changes)
        self.config_path.write_text(json.dumps(value), encoding='utf-8')
        return load_config(self.config_path)


class ConfigTests(Fixture):
    def test_config_is_closed_exact_and_credential_free(self):
        import pc.windows_service as service
        self.assertTrue(hasattr(service, 'load_config'), 'closed config loader is missing')
        config = self.config()
        self.assertEqual(config.startupGraceSeconds, 300)
        self.assertEqual(config.readyTimeoutSeconds, 120)
        for change in ({'token': 'never-accepted'}, {'schemaVersion': True}, {'port': True},
                       {'sourceDigest': 'bad'}, {'sourceCommit': 'not-approved'},
                       {'readyTimeoutSeconds': -1}, {'readyTimeoutSeconds': 301},
                       {'startupGraceSeconds': 0}, {'pythonPath': [str(self.home)]}):
            with self.subTest(change=change), self.assertRaises(ValueError):
                self.config(**change)
        value = self.raw_config()
        del value['home']
        self.config_path.write_text(json.dumps(value), encoding='utf-8')
        with self.assertRaises(ValueError):
            service.load_config(self.config_path)
        self.config_path.write_text('{"schemaVersion":1,"schemaVersion":1}', encoding='utf-8')
        with self.assertRaises(ValueError):
            service.load_config(self.config_path)

    def test_argv_paths_and_writes_are_narrowly_validated(self):
        value = self.raw_config()
        for argv in (value['argv'] + ['--token', 'secret'],
                     [value['python'], '-c', 'print(1)'],
                     [*value['argv'][:4], '--host', '0.0.0.0', *value['argv'][4:]],
                     [part if part != '17911' else '17912' for part in value['argv']]):
            with self.subTest(argv=argv), self.assertRaises(ValueError):
                self.config(argv=argv)
        for change in ({'updateMarker': str(self.project / '.cache' / 'updating')},
                       {'updateMarker': str(self.home / 'other-marker')},
                       {'stateFile': str(self.home / 'state.json')},
                       {'logFile': str(self.project / 'pc' / 'runtime.py')},
                       {'logFile': str(self.manifest)},
                       {'stateFile': str(self.config_path)},
                       {'projectRoot': str(self.project / '..' / 'project')},
                       {'updateMarker': str(self.project / '.cache' / 'service.log')}):
            with self.subTest(change=change), self.assertRaises(ValueError):
                self.config(**change)

    def managed(self, install='0123456789abcdef', env='0123456789abcdef0123456789abcdef'):
        folder = self.home / 'installs' / install / 'environments' / env / 'venv' / 'Lib' / 'site-packages'
        folder.mkdir(parents=True, exist_ok=True)
        return folder

    def test_only_the_exact_managed_site_packages_may_live_under_home(self):
        site = self.managed()
        config = self.config(pythonPath=[str(self.project), str(self.upstream), str(site)])
        self.assertEqual(config.pythonPath[-1], str(site))
        profile = self.home / 'profiles' / 'x'
        profile.mkdir(parents=True)
        bad_shape = self.managed(install='short')
        sibling = site.parent / 'Scripts'
        sibling.mkdir()
        for extra in (self.home, profile, bad_shape, sibling, site.parent):
            with self.subTest(extra=str(extra)), self.assertRaises(ValueError):
                self.config(pythonPath=[str(self.project), str(self.upstream), str(extra)])
        other = self.managed(install='fedcba9876543210')
        with self.assertRaises(ValueError):
            self.config(pythonPath=[str(self.project), str(self.upstream), str(site), str(other)])

    def test_update_marker_is_the_real_home_marker_and_never_created(self):
        config = self.config()
        self.assertEqual(config.updateMarker, str(self.home / '.hermes-update-in-progress'))
        self.assertFalse(Path(config.updateMarker).exists())
        self.assertFalse((self.project / '.cache' / 'updating').exists())

    def test_control_files_cannot_write_other_project_sources_or_policy(self):
        for change in ({'logFile': str(self.project / 'package.json')},
                       {'logFile': str(self.project / '.cache' / 'other.py')},
                       {'stateFile': str(self.project / 'state.json')},
                       {'stateFile': str(self.project / '.cache' / 'other.py')}):
            with self.subTest(change=change), self.assertRaises(ValueError):
                self.config(**change)

    def test_child_environment_scrubs_profiles_credentials_and_safety_overrides(self):
        import pc.windows_service as service
        self.assertTrue(hasattr(service, 'child_environment'), 'sanitized environment is missing')
        config = self.config()
        inherited = dict(PATH='safe-path', SYSTEMROOT='windows', USERPROFILE='user',
                         HERMES_PROFILE='wrong-profile', HERMES_HOME='wrong-home',
                         OPENAI_API_KEY='secret', HTTP_PROXY='secret-proxy',
                         PYTHONSTARTUP='bad', PYTHONPATH='bad', PYTHONINSPECT='1',
                         HERMES_YOLO='1', HERMES_DESKTOP='1')
        env = service.child_environment(config, 'generation', config.sourceDigest, inherited)
        self.assertEqual(env['PATH'], 'safe-path')
        self.assertEqual(env['HERMES_HOME'], str(self.home))
        self.assertEqual(env['PYTHONPATH'], ';'.join(config.pythonPath))
        self.assertEqual(env['HERMES_ANDROID_ADAPTER_GENERATION'], 'generation')
        self.assertEqual(env['HERMES_ANDROID_ADAPTER_SOURCE_SHA256'], config.sourceDigest)
        for name in ('HERMES_PROFILE', 'OPENAI_API_KEY', 'HTTP_PROXY', 'PYTHONSTARTUP',
                     'PYTHONINSPECT', 'HERMES_YOLO', 'HERMES_DESKTOP'):
            self.assertNotIn(name, env)
        self.assertEqual(env['HERMES_DISABLE_LAZY_INSTALLS'], '1')
        self.assertEqual(env['PYTHONDONTWRITEBYTECODE'], '1')
        self.assertEqual(env['PYTHONUNBUFFERED'], '1')


class FakeBackend:
    """Synthetic OS seam. Deliberately has no terminate/kill operation."""
    def __init__(self, config):
        self.config = config
        self.pids = set()
        self.processes = {}
        self.health_body = None
        self.spawned = []
        self.now = 1000.0
        self.after_sleep = None

    def listeners(self, port):
        self.assert_port(port)
        return set(self.pids)

    def assert_port(self, port):
        if port != 17911:
            raise AssertionError('not the synthetic configured port')

    def process(self, pid):
        return self.processes.get(pid)

    def find(self, config):
        return [p for p in self.processes.values()
                if p.executable == config.python and p.argv == config.argv]

    def health(self, port, timeout):
        self.assert_port(port)
        return self.health_body

    def wall_time(self):
        return self.now

    def monotonic(self):
        return self.now

    def sleep(self, seconds):
        self.now += seconds
        if self.after_sleep:
            self.after_sleep()

    def spawn(self, config, env):
        from pc.windows_service import ProcessIdentity
        self.spawned.append((config, env))
        child = ProcessIdentity(1234, self.now, config.python, config.argv)
        self.processes[child.pid] = child
        return child


class SupervisorTests(Fixture):
    def setUp(self):
        super().setUp()
        import pc.windows_service as service
        self.service = service
        self.assertTrue(hasattr(service, 'operate'), 'safe watchdog control flow is missing')
        self.cfg = self.config(readyTimeoutSeconds=2)
        self.backend = FakeBackend(self.cfg)

    def run_service(self, command='ensure'):
        return self.service.operate(self.cfg, command, backend=self.backend)

    def owned(self, *, created=999.0, generation='332284ca68384f76bac79637dac93001'):
        child = self.service.ProcessIdentity(1234, created, self.cfg.python, self.cfg.argv)
        self.backend.processes[child.pid] = child
        state = dict(schemaVersion=1, pid=child.pid, created=created, generation=generation,
                     sourceDigest=self.cfg.sourceDigest)
        Path(self.cfg.stateFile).write_text(json.dumps(state), encoding='utf-8')
        return state

    def healthy(self, state):
        self.backend.pids = {state['pid']}
        self.backend.health_body = {'ok': True, 'auth_required': True, 'androidAdapter': {
            'schemaVersion': 1, 'ready': True, 'generation': state['generation'],
            'sourceCommit': self.cfg.sourceCommit, 'sourceDigest': self.cfg.sourceDigest}}

    def test_update_marker_skips_without_process_or_health_inspection(self):
        Path(self.cfg.updateMarker).touch()
        (self.project / 'pc' / 'runtime.py').write_text('drift', encoding='utf-8')
        with patch.object(self.backend, 'listeners', side_effect=AssertionError('inspection forbidden')):
            result = self.run_service()
        self.assertEqual(result.status, 'updating')
        self.assertEqual(result.exit_code, 0)
        self.assertFalse(self.backend.spawned)

    def test_source_drift_fails_closed(self):
        (self.project / 'pc' / 'runtime.py').write_text('drift', encoding='utf-8')
        self.assertEqual(self.run_service().status, 'source-drift')
        self.assertFalse(self.backend.spawned)

    def test_unknown_listener_refuses_even_convincing_health(self):
        self.backend.pids = {5678}
        self.backend.health_body = {'ok': True, 'auth_required': True}
        result = self.run_service()
        self.assertEqual(result.status, 'foreign')
        self.assertNotEqual(result.exit_code, 0)
        self.assertFalse(self.backend.spawned)

    def test_correct_ready_requires_owned_pid_creation_executable_argv_and_generation(self):
        state = self.owned()
        self.healthy(state)
        self.assertEqual(self.run_service().status, 'healthy')
        self.assertFalse(self.backend.spawned)
        child = self.backend.processes[state['pid']]
        from dataclasses import replace
        for replacement in (replace(child, created=998), replace(child, executable='other-python'),
                            replace(child, argv=(*child.argv, '--other'))):
            with self.subTest(replacement=replacement):
                self.backend.processes[state['pid']] = replacement
                self.assertEqual(self.run_service().status, 'foreign')
        self.backend.processes[state['pid']] = child
        self.backend.health_body['androidAdapter']['generation'] = 'another-generation'
        self.assertEqual(self.run_service().status, 'degraded')
        self.assertFalse(self.backend.spawned)

    def test_wrong_or_ordinary_health_never_adopted(self):
        state = self.owned()
        self.healthy(state)
        good = self.backend.health_body
        for body in (None, {}, {'ok': True, 'auth_required': True},
                     {**good, 'auth_required': False}, {**good, 'ok': False},
                     {**good, 'androidAdapter': {**good['androidAdapter'], 'ready': False}},
                     {**good, 'androidAdapter': {**good['androidAdapter'], 'schemaVersion': True}},
                     {**good, 'androidAdapter': {**good['androidAdapter'], 'sourceCommit': 'wrong'}},
                     {**good, 'androidAdapter': {**good['androidAdapter'], 'sourceDigest': '0' * 64}}):
            with self.subTest(body=body):
                self.backend.health_body = body
                self.assertEqual(self.run_service().status, 'degraded')
        self.assertFalse(self.backend.spawned)

    def test_stale_reused_pid_with_no_listener_is_gone_and_restarts_once(self):
        state = self.owned()
        # After a reboot an unrelated process may reuse the recorded PID.
        self.backend.processes[state['pid']] = self.service.ProcessIdentity(
            state['pid'], 998, 'other', ('other',))
        self.backend.after_sleep = lambda: self.healthy(
            json.loads(Path(self.cfg.stateFile).read_text(encoding='utf-8')))
        self.assertEqual(self.run_service().status, 'healthy')
        self.assertEqual(len(self.backend.spawned), 1)

    def test_reused_pid_with_a_listener_stays_foreign(self):
        state = self.owned()
        from dataclasses import replace
        self.backend.processes[state['pid']] = replace(self.backend.processes[state['pid']], created=998)
        self.backend.pids = {state['pid']}
        self.assertEqual(self.run_service().status, 'foreign')
        self.assertFalse(self.backend.spawned)

    def test_empty_port_owned_child_boot_grace_and_stall_never_duplicate(self):
        self.owned()
        self.assertEqual(self.run_service().status, 'booting')
        self.backend.now += 301
        self.assertEqual(self.run_service().status, 'stalled')
        self.assertFalse(self.backend.spawned)

    def test_dead_previous_child_restarts_once_and_persists_before_readiness(self):
        previous = self.owned()
        self.backend.processes.clear()
        def ready():
            state = json.loads(Path(self.cfg.stateFile).read_text(encoding='utf-8'))
            self.assertNotEqual(state['generation'], previous['generation'])
            self.assertRegex(state['generation'], r'^[0-9a-f]{32}$')
            self.assertEqual(state['created'], 1000)
            self.healthy(state)
        self.backend.after_sleep = ready
        result = self.run_service()
        self.assertEqual(result.status, 'healthy')
        self.assertEqual(len(self.backend.spawned), 1)
        cfg, env = self.backend.spawned[0]
        self.assertEqual(cfg.upstream, str(self.upstream))
        self.assertEqual(env['HERMES_ANDROID_ADAPTER_SOURCE_SHA256'], cfg.sourceDigest)
        state = json.loads(Path(self.cfg.stateFile).read_text(encoding='utf-8'))
        self.assertEqual(set(state), {'schemaVersion', 'pid', 'created', 'generation', 'sourceDigest', 'lastStatus'})
        self.assertEqual(self.run_service().status, 'healthy')
        self.assertEqual(len(self.backend.spawned), 1)

    def test_child_markers_match_actual_health_hook(self):
        from pc.service_health import Health
        self.assertEqual(self.run_service().status, 'booting')
        _, env = self.backend.spawned[0]
        state = json.loads(Path(self.cfg.stateFile).read_text(encoding='utf-8'))
        with patch.dict(os.environ, env, clear=True):
            self.assertEqual(Health._marker('HERMES_ANDROID_ADAPTER_GENERATION', 32), state['generation'])
            self.assertEqual(Health._marker('HERMES_ANDROID_ADAPTER_SOURCE_SHA256', 64), self.cfg.sourceDigest)

    def test_timeout_retains_owned_child_and_next_tick_does_not_duplicate(self):
        result = self.run_service()
        self.assertEqual(result.status, 'booting')
        self.assertNotEqual(result.exit_code, 0)
        self.assertEqual(self.backend.now, 1002)
        self.assertTrue(Path(self.cfg.stateFile).exists())
        self.assertEqual(self.run_service().status, 'booting')
        self.assertEqual(len(self.backend.spawned), 1)

    def test_status_never_launches_or_changes_state_or_log(self):
        self.assertEqual(self.run_service('status').status, 'missing')
        self.assertFalse(self.backend.spawned)
        self.assertFalse(Path(self.cfg.stateFile).exists())
        self.assertFalse(Path(self.cfg.logFile).exists())

    def test_static_state_change_only_log_never_echoes_health_or_backend_error(self):
        state = self.owned()
        self.healthy(state)
        self.backend.health_body['private'] = 'secret-health-content'
        self.run_service()
        before = Path(self.cfg.logFile).read_bytes()
        self.run_service()
        self.assertEqual(before, Path(self.cfg.logFile).read_bytes())
        with patch.object(self.backend, 'listeners', side_effect=OSError('secret-exception-content')):
            self.assertEqual(self.run_service().status, 'inspection-failed')
        records = [json.loads(line) for line in Path(self.cfg.logFile).read_text().splitlines()]
        self.assertEqual([r['status'] for r in records], ['healthy', 'inspection-failed'])
        self.assertTrue(all(set(r) == {'timestamp', 'status'} for r in records))
        self.assertNotIn('secret', Path(self.cfg.logFile).read_text())

    def test_duplicate_ensure_is_locked_across_full_readiness_wait(self):
        import threading
        entered, release = threading.Event(), threading.Event()
        outcome = []
        def block(seconds):
            entered.set()
            if not release.wait(3):
                raise AssertionError('test did not release readiness')
            self.backend.now += seconds
        with patch.object(self.backend, 'sleep', side_effect=block):
            thread = threading.Thread(target=lambda: outcome.append(self.run_service()))
            thread.start()
            try:
                self.assertTrue(entered.wait(3))
                self.assertEqual(self.run_service().status, 'locked')
                self.assertEqual(len(self.backend.spawned), 1)
            finally:
                release.set()
                thread.join(3)
            self.assertFalse(thread.is_alive())
        self.assertEqual(outcome[0].status, 'booting')
        self.assertEqual(len(self.backend.spawned), 1)

    def test_failed_spawn_is_fenced_then_recovered_when_no_process_exists(self):
        with patch.object(self.backend, 'spawn', side_effect=OSError('private launch error')) as spawn:
            self.assertEqual(self.run_service().status, 'launch-failed')
            self.assertEqual(Path(self.cfg.lockFile).read_bytes()[:8], b'0pending')
            # No process exists, so the fence proves nothing is running: retry.
            self.assertEqual(self.run_service().status, 'launch-failed')
            self.assertEqual(spawn.call_count, 2)
        self.assertNotIn('private', Path(self.cfg.logFile).read_text())

    def fence(self, generation='a' * 32, since=999.0):
        Path(self.cfg.lockFile).write_bytes(b'0pending %s %.6f' % (generation.encode(), since))

    def test_crash_between_spawn_and_state_adopts_the_single_live_child(self):
        self.fence()
        child = self.service.ProcessIdentity(4321, 999.5, self.cfg.python, self.cfg.argv)
        self.backend.processes[child.pid] = child
        self.assertEqual(self.run_service().status, 'booting')
        self.assertFalse(self.backend.spawned)
        state = json.loads(Path(self.cfg.stateFile).read_text(encoding='utf-8'))
        self.assertEqual((state['pid'], state['created'], state['generation']),
                         (4321, 999.5, 'a' * 32))
        self.assertEqual(Path(self.cfg.lockFile).read_bytes(), b'0')
        self.healthy(state)
        self.assertEqual(self.run_service().status, 'healthy')
        self.assertFalse(self.backend.spawned)

    def test_fence_after_reboot_with_no_process_clears_and_relaunches(self):
        self.fence()
        self.backend.after_sleep = lambda: self.healthy(
            json.loads(Path(self.cfg.stateFile).read_text(encoding='utf-8')))
        self.assertEqual(self.run_service().status, 'healthy')
        self.assertEqual(len(self.backend.spawned), 1)
        self.assertEqual(Path(self.cfg.lockFile).read_bytes(), b'0')

    def test_process_older_than_the_fence_is_not_adopted(self):
        self.fence(since=5000.0)
        old = self.service.ProcessIdentity(4321, 1000.0, self.cfg.python, self.cfg.argv)
        self.backend.processes[old.pid] = old
        self.backend.after_sleep = lambda: self.healthy(
            json.loads(Path(self.cfg.stateFile).read_text(encoding='utf-8')))
        # The lookalike is older than the fence, so it is not the fenced launch.
        # It still occupies no port, so a fresh launch is allowed.
        self.assertEqual(self.run_service().status, 'healthy')
        self.assertEqual(len(self.backend.spawned), 1)

    def test_ambiguous_or_unreadable_fence_holds_without_launch(self):
        self.fence()
        for pid in (4321, 4322):
            self.backend.processes[pid] = self.service.ProcessIdentity(
                pid, 1001.0, self.cfg.python, self.cfg.argv)
        self.assertEqual(self.run_service().status, 'launch-failed')
        self.assertFalse(self.backend.spawned)
        self.assertNotEqual(Path(self.cfg.lockFile).read_bytes(), b'0')
        Path(self.cfg.lockFile).write_bytes(b'0garbage')
        self.assertEqual(self.run_service().status, 'launch-failed')
        self.assertFalse(self.backend.spawned)
        with patch.object(self.backend, 'find', side_effect=OSError('denied')):
            self.assertEqual(self.run_service().status, 'inspection-failed')
        self.assertFalse(self.backend.spawned)

    def test_status_reports_but_never_rewrites_a_fence_or_state(self):
        self.fence()
        before = Path(self.cfg.lockFile).read_bytes()
        child = self.service.ProcessIdentity(4321, 999.5, self.cfg.python, self.cfg.argv)
        self.backend.processes[child.pid] = child
        self.assertEqual(self.run_service('status').status, 'booting')
        self.assertEqual(Path(self.cfg.lockFile).read_bytes(), before)
        self.assertFalse(Path(self.cfg.stateFile).exists())
        self.assertFalse(self.backend.spawned)

    def test_child_exit_during_readiness_has_no_same_tick_restart(self):
        self.backend.after_sleep = self.backend.processes.clear
        self.assertEqual(self.run_service().status, 'child-exited')
        self.assertEqual(len(self.backend.spawned), 1)

    def test_marker_during_readiness_stops_checks_without_stopping_child(self):
        self.backend.after_sleep = lambda: Path(self.cfg.updateMarker).touch()
        self.assertEqual(self.run_service().status, 'updating')
        self.assertEqual(len(self.backend.processes), 1)
        self.assertEqual(len(self.backend.spawned), 1)

    def test_listener_identity_replacement_during_health_is_not_healthy(self):
        state = self.owned()
        self.healthy(state)
        body = self.backend.health_body
        def replacement(port, timeout):
            self.backend.pids = {9876}
            return body
        with patch.object(self.backend, 'health', side_effect=replacement):
            self.assertEqual(self.run_service().status, 'foreign')
        self.assertFalse(self.backend.spawned)

    def test_permission_failure_is_not_treated_as_dead_process(self):
        self.owned()
        with patch.object(self.backend, 'process', side_effect=OSError('access denied')):
            self.assertEqual(self.run_service().status, 'inspection-failed')
        self.assertFalse(self.backend.spawned)

    def test_linked_control_files_refused_without_writes(self):
        source = self.project / 'pc' / 'runtime.py'
        before = source.read_bytes()
        os.link(source, self.cfg.logFile)
        self.backend.pids = {5678}
        self.assertEqual(self.run_service().status, 'control-error')
        self.assertEqual(source.read_bytes(), before)
        self.assertFalse(self.backend.spawned)

    def test_unsafe_log_path_prevents_launch_not_just_logging(self):
        source = self.project / 'pc' / 'runtime.py'
        before = source.read_bytes()
        os.link(source, self.cfg.logFile)
        self.assertEqual(self.run_service().status, 'control-error')
        self.assertEqual(source.read_bytes(), before)
        self.assertEqual(len(self.backend.spawned), 0)

    def test_no_process_termination_api_in_supervisor(self):
        import ast
        tree = ast.parse(Path(self.service.__file__).read_text(encoding='utf-8'))
        calls = [node.func for node in ast.walk(tree) if isinstance(node, ast.Call)]
        self.assertFalse(any(isinstance(call, ast.Attribute) and call.attr in
                             {'kill', 'terminate', 'send_signal', 'killpg'} for call in calls))

    def test_unreadable_or_malformed_state_fails_closed(self):
        state_base = dict(schemaVersion=1, pid=1234, created=999,
                          generation='332284ca68384f76bac79637dac93001',
                          sourceDigest=self.cfg.sourceDigest)
        for raw in ('{}', '{', '{"schemaVersion":1,"pid":1234,"created":NaN}',
                    '[' * 1200 + '0' + ']' * 1200,
                    json.dumps({**state_base, 'pid': 2 ** 64}),
                    json.dumps({**state_base, 'created': 10 ** 1000}),
                    json.dumps(dict(schemaVersion=1, pid=True, created=999, generation='invalid',
                                    sourceDigest=self.cfg.sourceDigest))):
            with self.subTest(raw=raw):
                Path(self.cfg.stateFile).write_text(raw, encoding='utf-8')
                self.assertEqual(self.run_service().status, 'invalid-state')
        self.assertFalse(self.backend.spawned)


class SystemBackendTests(Fixture):
    def test_real_local_http_health_is_direct_bounded_and_closed_json(self):
        import pc.windows_service as service
        self.assertTrue(hasattr(service, 'SystemBackend'), 'real OS and health backend is missing')
        from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
        import threading
        class Handler(BaseHTTPRequestHandler):
            body = b'{"ok":true,"auth_required":true,"androidAdapter":{"schemaVersion":1}}'
            code = 200
            def log_message(self, *args):
                pass
            def do_GET(self):
                self.server.paths.append(self.path)
                self.send_response(self.code)
                self.send_header('Content-Length', str(len(self.body)))
                self.end_headers()
                self.wfile.write(self.body)
        server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        server.paths = []
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            backend = service.SystemBackend()
            port = server.server_port
            with patch.dict(os.environ, HTTP_PROXY='http://not-used.invalid:1',
                            HTTPS_PROXY='http://not-used.invalid:1', ALL_PROXY='http://not-used.invalid:1'):
                body = backend.health(port, 1)
            self.assertIs(body['ok'], True)
            self.assertEqual(server.paths, ['/api/health'])
            for data, code in ((b'not-json', 200), (b'{"ok":true,"ok":false}', 200),
                               (b'{"number":NaN}', 200), (b'{}', 302),
                               (b' ' * 65537, 200), (b'[]', 200)):
                Handler.body, Handler.code = data, code
                with self.subTest(code=code, length=len(data)):
                    self.assertIsNone(backend.health(port, 1))
        finally:
            server.shutdown()
            server.server_close()
            thread.join(3)
            self.assertFalse(thread.is_alive())

    def test_slow_health_response_obeys_total_deadline(self):
        import pc.windows_service as service
        self.assertTrue(hasattr(service, 'SystemBackend'), 'bounded health backend is missing')
        import socket
        import threading
        import time
        listener = socket.socket()
        listener.bind(('127.0.0.1', 0))
        listener.listen()
        stop = threading.Event()
        def drip():
            connection, _ = listener.accept()
            with connection:
                connection.recv(4096)
                try:
                    for byte in b'HTTP/1.1 200 OK\r\nContent-Length: 2\r\n\r\n{}':
                        if stop.wait(0.025):
                            break
                        connection.send(bytes([byte]))
                except OSError:
                    pass
        thread = threading.Thread(target=drip, daemon=True)
        thread.start()
        try:
            started = time.monotonic()
            self.assertIsNone(service.SystemBackend().health(listener.getsockname()[1], 0.15))
            self.assertLess(time.monotonic() - started, 0.8)
        finally:
            stop.set()
            listener.close()
            thread.join(2)
            self.assertFalse(thread.is_alive())

    def test_real_listener_pid_and_current_process_identity(self):
        import pc.windows_service as service
        self.assertTrue(hasattr(service, 'SystemBackend'), 'real process inspection is missing')
        import socket
        import psutil
        backend = service.SystemBackend()
        with socket.socket() as listener:
            listener.bind(('127.0.0.1', 0))
            listener.listen()
            self.assertEqual(backend.listeners(listener.getsockname()[1]), {os.getpid()})
        identity = backend.process(os.getpid())
        self.assertEqual(identity.pid, os.getpid())
        self.assertEqual(identity.created, psutil.Process().create_time())
        self.assertEqual(identity.executable, psutil.Process().exe())
        self.assertEqual(identity.argv, tuple(psutil.Process().cmdline()))
        with patch('psutil.Process', side_effect=psutil.NoSuchProcess(987654)):
            self.assertIsNone(backend.process(987654))
        with patch('psutil.Process', side_effect=psutil.AccessDenied(987654)):
            with self.assertRaises(OSError):
                backend.process(987654)

    def test_detached_launch_has_exact_argv_upstream_cwd_no_backend_output(self):
        import pc.windows_service as service
        self.assertTrue(hasattr(service, 'SystemBackend'), 'safe detached launch is missing')
        import subprocess
        from types import SimpleNamespace
        cfg = self.config()
        env = service.child_environment(cfg, 'generation', cfg.sourceDigest)
        process = SimpleNamespace(pid=1234)
        with patch('subprocess.Popen', return_value=process) as popen, \
                patch('psutil.Process', return_value=SimpleNamespace(create_time=lambda: 1000.0)):
            identity = service.SystemBackend().spawn(cfg, env)
        self.assertEqual(identity.pid, 1234)
        self.assertEqual(identity.created, 1000.0)
        args, kwargs = popen.call_args
        self.assertEqual(tuple(args[0]), cfg.argv)
        self.assertEqual(kwargs['cwd'], cfg.upstream)
        self.assertIs(kwargs['env'], env)
        self.assertIs(kwargs['stdout'], subprocess.DEVNULL)
        self.assertIs(kwargs['stderr'], subprocess.DEVNULL)
        self.assertIs(kwargs['stdin'], subprocess.DEVNULL)
        self.assertTrue(kwargs['close_fds'])
        if os.name == 'nt':
            self.assertEqual(kwargs['creationflags'], subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP)
        else:
            self.assertTrue(kwargs['start_new_session'])

    def test_cli_update_skip_and_invalid_config_never_echo_sensitive_input(self):
        import pc.windows_service as service
        self.assertTrue(hasattr(service, 'main'), 'supervisor CLI is missing')
        import subprocess
        cfg = self.config()
        Path(cfg.updateMarker).touch()
        command = [sys.executable, '-B', '-m', 'pc.windows_service', '--config', str(self.config_path), 'ensure']
        result = subprocess.run(command, capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(json.loads(result.stdout), {'schemaVersion': 1, 'status': 'updating'})
        self.config_path.write_text('{"secret":"do-not-echo"}', encoding='utf-8')
        result = subprocess.run(command, capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 2)
        self.assertEqual(json.loads(result.stdout), {'schemaVersion': 1, 'status': 'invalid-config'})
        self.assertNotIn('do-not-echo', result.stdout + result.stderr)


class InterprocessLockTests(Fixture):
    def test_real_os_lock_blocks_competing_process_then_releases(self):
        from pc.windows_service import supervisor_lock
        import subprocess
        lock = self.project / '.cache' / 'test.lock'
        script = ('from pc.windows_service import supervisor_lock, LockBusy; import sys\n'
                  'try:\n'
                  '    with supervisor_lock(sys.argv[1]): print("acquired")\n'
                  'except LockBusy: print("locked"); sys.exit(3)\n')
        command = [sys.executable, '-B', '-c', script, str(lock)]
        with supervisor_lock(lock):
            result = subprocess.run(command, capture_output=True, text=True, timeout=10)
            self.assertEqual(result.returncode, 3, result.stdout + result.stderr)
            self.assertEqual(result.stdout.strip(), 'locked')
        result = subprocess.run(command, capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(result.stdout.strip(), 'acquired')


if __name__ == '__main__':
    unittest.main()
