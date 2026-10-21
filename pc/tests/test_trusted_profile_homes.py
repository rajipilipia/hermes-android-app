"""Synthetic, host-owned Windows junctions only; no real profile/runtime writes."""
import os
from pathlib import Path
import subprocess
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from pc.catalog import CapabilityError
from pc.tests import test_production_policy as policy_tests


class TrustedProfileHomeTests(unittest.TestCase):
    setUp = policy_tests.BoundPolicyTests.setUp
    module = policy_tests.BoundPolicyTests.module
    value = policy_tests.BoundPolicyTests.value
    load = policy_tests.BoundPolicyTests.load
    admit = policy_tests.BoundPolicyTests.admit

    def junction_fixture(self):
        target = self.base / 'external' / 'profiles' / 'research'
        target.mkdir(parents=True)
        self.home.rmdir()
        self.home.parent.rmdir()
        subprocess.run(['cmd.exe', '/d', '/c', 'mklink', '/J', str(self.home.parent),
                        str(target.parent)], check=True, capture_output=True)
        # Remove the junction before TemporaryDirectory's recursive cleanup.
        self.addCleanup(lambda: self.home.parent.rmdir())
        value = self.value()
        value.update(launchProfile='default', launchHome=str(self.root))
        value['principals'][0]['profiles']['research']['expectedHome'] = str(target)
        resolver = lambda name: self.root if name == 'default' else self.home
        server = SimpleNamespace(_launch_home=lambda: self.root, _profile_home=resolver)
        return value, target, server, resolver

    def test_explicit_canonical_home_accepts_owned_junction_without_retargeting_default(self):
        value, target, server, resolver = self.junction_fixture()
        policy = self.load(value).bind(server, resolver)
        self.assertEqual(self.admit(policy).profile, 'research')
        self.assertEqual(policy.root, self.root)
        self.assertEqual(policy.launch_home, self.root)
        self.assertEqual(policy._expected_homes['research'], target)
        self.assertIsNone(policy.validate())


    def test_canonical_home_guard_holds_identity_through_use(self):
        value, target, server, resolver = self.junction_fixture()
        policy = self.load(value).bind(server, resolver)
        owner = self.admit(policy)
        self.assertTrue(callable(getattr(policy, 'profile_home', None)),
                        'canonical profile-home I/O guard missing')
        with policy.profile_home(owner) as home:
            self.assertEqual(home, target)
            with self.assertRaises(OSError):
                target.rename(target.with_name('parked'))
        self.assertEqual(self.admit(policy), owner)

    def test_profile_home_guard_holds_the_declared_junction_through_service_use(self):
        value, target, server, resolver = self.junction_fixture()
        policy = self.load(value).bind(server, resolver)
        owner = self.admit(policy)
        junction = self.home.parent
        parked = junction.with_name('profiles-parked')
        renamed = False
        with policy.profile_home(owner):
            try:
                try:
                    junction.rename(parked)
                    renamed = True
                except OSError:
                    pass
            finally:
                if renamed:
                    parked.rename(junction)
        self.assertFalse(renamed, 'profile alias can move during admitted service I/O')
        self.assertEqual(self.admit(policy), owner)

    def test_adapter_holds_profile_home_for_the_entire_original_service_call(self):
        import asyncio
        import contextvars
        from pc.addon import Adapter
        from pc.catalog import validate_call
        value, target, server, resolver = self.junction_fixture()
        policy = self.load(value).bind(server, resolver)
        owner = self.admit(policy)
        adapter = object.__new__(Adapter)
        adapter.policy = policy
        adapter._delegation = contextvars.ContextVar('trusted-home-test', default=None)
        junction = self.home.parent
        parked = junction.with_name('profiles-parked')
        async def service(*args, **kwargs):
            renamed = False
            try:
                try:
                    junction.rename(parked)
                    renamed = True
                except OSError:
                    pass
            finally:
                if renamed:
                    parked.rename(junction)
            self.assertFalse(renamed, 'adapter service ran without its held profile home')
            return 200, {'active': owner.profile, 'current': owner.profile}, 'application/json'
        adapter._asgi = service
        call = validate_call({'operation': 'GET /api/profiles/active', 'profile': owner.profile})
        result = asyncio.run(adapter.invoke(call, owner, SimpleNamespace(closed=False)))
        self.assertEqual(result['status'], 200)
        junction.rename(parked)
        parked.rename(junction)

    def test_picker_worker_keeps_profile_home_held_after_client_timeout(self):
        import asyncio
        import sys
        import threading
        from types import ModuleType
        from pc import startup
        value, target, server, resolver = self.junction_fixture()
        policy = self.load(value).bind(server, resolver)
        owner = self.admit(policy)
        started, release = threading.Event(), threading.Event()
        models = ModuleType('hermes_cli.web_routers.models')
        async def picker(**kwargs):
            started.set()
            await asyncio.to_thread(release.wait)
            return {'providers': []}
        models.get_model_options = picker
        junction = self.home.parent
        parked = junction.with_name('profiles-parked')
        async def exercise():
            try:
                with self.assertRaises(CapabilityError) as caught:
                    await startup.execute_startup('GET /api/model/options', owner, {}, policy)
                self.assertEqual(caught.exception.status, 504)
                for _ in range(200):
                    if started.is_set():
                        break
                    await asyncio.sleep(.01)
                self.assertTrue(started.is_set(), 'picker worker did not enter')
                renamed = False
                try:
                    try:
                        junction.rename(parked)
                        renamed = True
                    except OSError:
                        pass
                finally:
                    if renamed:
                        parked.rename(junction)
                self.assertFalse(renamed, 'timed-out picker released its profile-home lease early')
            finally:
                release.set()
                for _ in range(200):
                    if startup._picker_pending == 0:
                        break
                    await asyncio.sleep(.01)
                self.assertEqual(startup._picker_pending, 0)
        with patch.dict(sys.modules, {'hermes_cli.web_routers.models': models}), \
                patch.object(startup, '_PICKER_TIMEOUT_SECONDS', .03):
            asyncio.run(exercise())

    def test_attachment_accepts_only_the_bound_live_home_and_writes_canonical_storage(self):
        import io
        import sys
        import threading
        from types import ModuleType
        from pc.attachments import attach_upload
        value, target, server, resolver = self.junction_fixture()
        policy = self.load(value).bind(server, resolver)
        owner = self.admit(policy)
        transport = SimpleNamespace(closed=False)
        server._hermes_home = self.root
        server._sessions_lock = threading.RLock()
        session = {'session_key': 'stored', 'transport': transport,
                   'auth_user_id': f'{owner.provider}:{owner.user_id}',
                   'profile_home': str(self.home)}
        server._sessions = {'live': session}
        def stage(session, *, data_url, name, **kwargs):
            destination = _session_home_dir(session) / name
            destination.write_bytes(__import__('base64').b64decode(data_url.partition(',')[2]))
            return destination, True
        server._stage_session_file_attachment = stage
        server._attachment_ref_path = lambda session, path: str(path)
        server._format_ref_value = lambda path: path
        modules = {name: ModuleType(name) for name in (
            'hermes_cli.web_routers.sessions', 'hermes_cli.web_server_sessions', 'hermes_state')}
        modules['hermes_cli.web_routers.sessions']._history_profile_home = resolver
        modules['hermes_cli.web_server_sessions']._session_db_path_for_profile = lambda name: resolver(name) / 'state.db'
        modules['hermes_state'].SessionDB = lambda **kwargs: self.fail('absent draft DB opened')
        def upload():
            return attach_upload(server, policy, owner, transport, {
                'sessionId': 'live', 'storedSessionId': 'stored', 'cancelled': False,
                'purpose': 'file.attach', 'file': io.BytesIO(b'safe'), 'byteSize': 4,
                'filename': 'fixture.txt', 'mimeType': 'text/plain'})
        with patch.dict(sys.modules, modules):
            result = upload()
            path = Path(result['path'])
            self.assertTrue(path.is_relative_to(target / 'attachments'))
            self.assertEqual(path.read_bytes(), b'safe')
            foreign = self.base / 'foreign'
            foreign.mkdir()
            session['profile_home'] = str(foreign)
            with self.assertRaises(CapabilityError) as home_error:
                upload()
            self.assertEqual(home_error.exception.detail, 'attachment live session home mismatch')
            self.assertEqual(list(foreign.iterdir()), [])
            session['profile_home'] = str(self.home)
            # Same user, key and home on ANOTHER socket (the phone's capability socket): allowed.
            session['transport'] = SimpleNamespace(closed=False)
            self.assertEqual(Path(upload()['path']).read_bytes(), b'safe')
            # Another authenticated user or another stored key: refused, with its own reason.
            session['auth_user_id'] = 'other:user'
            with self.assertRaises(CapabilityError) as user_error:
                upload()
            self.assertEqual(user_error.exception.detail, 'attachment live session user mismatch')
            session['auth_user_id'] = f'{owner.provider}:{owner.user_id}'
            session['session_key'] = 'someone-elses'
            with self.assertRaises(CapabilityError) as key_error:
                upload()
            self.assertEqual(key_error.exception.detail, 'attachment live session key mismatch')

    def test_profile_home_lease_allows_original_atomic_save_and_cleans_private_guards(self):
        value, target, server, resolver = self.junction_fixture()
        policy = self.load(value).bind(server, resolver)
        owner = self.admit(policy)
        source, destination = target/'replacement.tmp', target/'fixture.txt'
        source.write_bytes(b'new')
        destination.write_bytes(b'old')
        with policy.profile_home(owner):
            os.replace(source, destination)
            self.assertEqual(destination.read_bytes(), b'new')
            with self.assertRaises(OSError):
                target.rename(target.with_name('parked'))
        self.assertEqual(list(target.glob('.pc-guard-*')), [])
        self.assertEqual(list(self.root.glob('.pc-guard-*')), [])

    def test_replacing_runtime_resolver_even_with_same_result_invalidates_binding(self):
        value, target, server, resolver = self.junction_fixture()
        policy = self.load(value).bind(server, resolver)
        server._profile_home = lambda name: resolver(name)
        with self.assertRaises(CapabilityError):
            self.admit(policy)


    def test_history_opens_canonical_store_under_held_home_guard(self):
        import sys
        from types import ModuleType
        from pc import history
        value, target, server, resolver = self.junction_fixture()
        policy = self.load(value).bind(server, resolver)
        owner = self.admit(policy)
        (target / 'state.db').write_bytes(b'synthetic')
        modules = {name: ModuleType(name) for name in (
            'hermes_cli', 'hermes_cli.profiles', 'hermes_cli.web_server_sessions', 'hermes_state')}
        modules['hermes_cli.profiles'].get_profile_dir = resolver
        modules['hermes_cli.web_server_sessions']._session_db_path_for_profile = lambda name: resolver(name) / 'state.db'
        seen = []
        case = self
        class DB:
            def __init__(self, *, db_path, read_only):
                seen.append(db_path)
                case.assertEqual(db_path, target / 'state.db')
                with case.assertRaises(OSError):
                    target.rename(target.with_name('parked'))
            def close(self): pass
        modules['hermes_state'].SessionDB = DB
        with patch.dict(sys.modules, modules), patch.object(history, 'read_on_db', return_value={'sessions': []}):
            result = history.execute_history('GET /api/sessions', owner, {}, policy)
        self.assertEqual(result, {'sessions': []})
        self.assertEqual(seen, [target / 'state.db'])


    def test_undeclared_alias_and_wrong_canonical_target_are_rejected(self):
        value, target, server, resolver = self.junction_fixture()
        value['principals'][0]['profiles']['research']['expectedHome'] = str(self.home)
        with self.assertRaises(ValueError):
            self.load(value)
        wrong = self.base / 'wrong' / 'research'
        wrong.mkdir(parents=True)
        value['principals'][0]['profiles']['research']['expectedHome'] = str(wrong)
        with self.assertRaises(ValueError):
            self.load(value)

    def test_builtin_administrator_owned_junction_preserves_user_owned_homes(self):
        value, target, server, resolver = self.junction_fixture()
        module = self.module()
        real_owner = module._path_owner
        with patch.object(module, '_path_owner', side_effect=lambda path:
                'S-1-5-32-544' if Path(path) == self.home.parent else real_owner(path)):
            policy = self.load(value).bind(server, resolver)
            owner = self.admit(policy)
            with policy.profile_home(owner) as selected:
                self.assertEqual(selected, target)
            self.assertEqual(policy.launch_home, self.root)

    def test_unowned_junction_or_canonical_home_is_rejected(self):
        value, target, server, resolver = self.junction_fixture()
        module = self.module()
        real_owner = module._path_owner
        for selected in (self.home.parent, target):
            with self.subTest(selected=selected), patch.object(module, '_path_owner',
                    side_effect=lambda p: 'foreign-owner' if Path(p) == selected else real_owner(p)):
                with self.assertRaises(ValueError):
                    self.load(value)

    def test_retargeted_junction_revokes_admission_before_canonical_io(self):
        value, target, server, resolver = self.junction_fixture()
        policy = self.load(value).bind(server, resolver)
        owner = self.admit(policy)
        wrong = self.base / 'wrong-storage' / 'research'
        wrong.mkdir(parents=True)
        junction = self.home.parent
        parked = junction.with_name('profiles-parked')
        junction.rename(parked)
        self.addCleanup(parked.rmdir)
        subprocess.run(['cmd.exe', '/d', '/c', 'mklink', '/J', str(junction), str(wrong.parent)],
                       check=True, capture_output=True)
        with self.assertRaises(ValueError):
            policy.validate()
        with self.assertRaises(CapabilityError):
            self.admit(policy)
        with self.assertRaises(CapabilityError):
            with policy.profile_home(owner):
                self.fail('retargeted alias reached service I/O')

    def test_cross_profile_swaps_and_ungranted_profiles_remain_denied(self):
        value, target, server, resolver = self.junction_fixture()
        other = target.with_name('writing')
        other.mkdir()
        value['principals'][0]['profiles']['writing'] = {
            'expectedHome': str(other), 'roots': [str(self.workspace)], 'permissions': ['read']}
        selected = {'default': self.root, 'research': self.home, 'writing': self.home.with_name('writing')}
        server._profile_home = selected.__getitem__
        policy = self.load(value).bind(server, selected.__getitem__)
        self.assertEqual(self.admit(policy, profile='writing').profile, 'writing')
        selected['research'], selected['writing'] = selected['writing'], selected['research']
        with self.assertRaises(CapabilityError):
            self.admit(policy)
        with self.assertRaises(CapabilityError):
            self.admit(policy, profile='writing')
        with self.assertRaises(CapabilityError):
            self.admit(policy, profile='cpm')

    def test_canonical_profile_storage_cannot_be_granted_as_workspace(self):
        value, target, server, resolver = self.junction_fixture()
        for workspace in (target, target.parent, target.parent.parent):
            with self.subTest(workspace=workspace):
                value['principals'][0]['profiles']['research']['roots'] = [str(workspace)]
                with self.assertRaises(ValueError):
                    self.load(value)


if __name__ == '__main__':
    unittest.main()
