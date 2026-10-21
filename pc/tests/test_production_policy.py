"""Source-only host policy regressions; fixtures stay in Hermes TMPDIR.

No upstream modules, runtime/lifespan, real homes, credentials, or subprocesses.
"""
from __future__ import annotations

import importlib
import importlib.util
import json
import os
from pathlib import Path
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from pc.catalog import CapabilityError
from pc.policy import Owner


class BoundPolicyTests(unittest.TestCase):
    def setUp(self):
        self.scratch = tempfile.TemporaryDirectory(
            prefix='bound-policy-', dir=os.environ['TMPDIR'])
        self.addCleanup(self.scratch.cleanup)
        self.base = Path(self.scratch.name).resolve(strict=True)
        self.root = self.base / 'managed'
        self.home = self.root / 'profiles' / 'research'
        self.home.mkdir(parents=True)
        self.workspace = self.base / 'workspace'
        self.workspace.mkdir()
        self.spool = self.base / 'spool'
        self.spool.mkdir()
        self.manifest = self.base / 'policy.json'

    def module(self):
        self.assertIsNotNone(importlib.util.find_spec('pc.production_policy'),
                             'host-owned production policy is missing')
        return importlib.import_module('pc.production_policy')

    def value(self):
        module = self.module()
        return {'schemaVersion': 1, 'owner': module.current_owner(),
                'root': str(self.root), 'launchProfile': 'research',
                'launchHome': str(self.home), 'spool': str(self.spool),
                'principals': [{'provider': 'fixture', 'user_id': 'alice', 'profiles': {
                    'default': {'expectedHome': str(self.root), 'roots': [str(self.workspace)],
                                'permissions': ['read']},
                    'research': {'expectedHome': str(self.home), 'roots': [str(self.workspace)],
                                 'permissions': ['read', 'files.write']}}}]}

    def load(self, value=None, **kwargs):
        self.manifest.write_text(json.dumps(self.value() if value is None else value),
                                 encoding='utf-8')
        return self.module().BoundPolicy.load(self.manifest, **kwargs)

    def test_host_owned_manifest_loads_without_importing_runtime(self):
        module = self.module()
        policy = self.load()
        self.assertEqual(policy.root, self.root)
        self.assertEqual(policy.launch_profile, 'research')
        self.assertEqual(policy.launch_home, self.home)
        self.assertEqual(policy.spool, self.spool)
        self.assertEqual(policy._grants[('fixture', 'alice', 'research')],
                         ((self.workspace,), frozenset({'read', 'files.write'})))
        self.assertIsNone(policy.validate())
        owner = module.current_owner()
        self.assertIsInstance(owner, str)
        self.assertTrue(owner)
        if os.name == 'nt':
            self.assertRegex(owner, r'^S-1-\d+(?:-\d+)+$')
        else:
            self.assertEqual(owner, str(os.getuid()))


    def test_manifest_schema_is_closed_and_values_are_explicit(self):
        mutations = [
            lambda v: v.update(extra=True),
            lambda v: v.pop('owner'),
            lambda v: v.update(schemaVersion=True),
            lambda v: v.update(schemaVersion=2),
            lambda v: v.update(principals=[]),
            lambda v: v.update(principals={}),
            lambda v: v['principals'][0].update(extra=True),
            lambda v: v['principals'][0].update(profiles={}),
            lambda v: v['principals'][0]['profiles']['research'].update(extra=True),
            lambda v: v['principals'][0]['profiles']['research'].pop('expectedHome'),
            lambda v: v['principals'][0]['profiles']['research'].update(roots=[]),
            lambda v: v['principals'][0]['profiles']['research'].update(roots='workspace'),
            lambda v: v['principals'][0]['profiles']['research'].update(permissions=[]),
            lambda v: v['principals'][0]['profiles']['research'].update(permissions=['admin']),
            lambda v: v['principals'][0]['profiles']['research'].update(permissions=['read', 'read']),
            lambda v: v['principals'][0]['profiles']['research'].update(roots=[str(self.workspace)] * 2),
        ]
        for index, mutate in enumerate(mutations):
            with self.subTest(index=index):
                value = self.value()
                mutate(value)
                with self.assertRaises(ValueError) as error:
                    self.load(value)
                self.assertIs(type(error.exception), ValueError)

    def test_duplicate_json_keys_are_rejected_at_every_depth(self):
        for raw in ('{"schemaVersion":1,"schemaVersion":1}',
                    '{"principals":[{"provider":"one","provider":"two"}]}',
                    '{"principals":[{"profiles":{"research":{},"research":{}}}]}'):
            with self.subTest(raw=raw):
                self.manifest.write_text(raw, encoding='utf-8')
                with self.assertRaisesRegex(ValueError, 'duplicate'):
                    self.module().BoundPolicy.load(self.manifest)

    def test_duplicate_and_ambient_principals_cannot_be_declared(self):
        value = self.value()
        value['principals'].append(dict(value['principals'][0]))
        with self.assertRaises(ValueError):
            self.load(value)
        for field in ('provider', 'user_id'):
            for raw in ('', ' alice', 'alice ', '*', 'a?b', 'a\nb', 'all',
                        'internal', 'delegation', 'android-desktop-delegation', 'loopback', 'local'):
                with self.subTest(field=field, raw=raw):
                    value = self.value()
                    value['principals'][0][field] = raw
                    with self.assertRaises(ValueError):
                        self.load(value)


    def test_profile_names_are_not_aliases_or_device_names(self):
        for name in ('Research', ' research', 'research ', 'all', 'current',
                     'hermes', 'test', 'tmp', 'root', 'sudo', 'con', 'aux',
                     'nul', 'com1', 'lpt9', '../research', 'research/default'):
            with self.subTest(name=name):
                value = self.value()
                value['principals'][0]['profiles'][name] = value['principals'][0]['profiles'].pop('research')
                with self.assertRaises(ValueError) as error:
                    self.load(value)
                self.assertIs(type(error.exception), ValueError)

    def test_homes_must_follow_exact_root_profile_and_launch_mapping(self):
        for field, raw in (('root', 'managed'), ('launchHome', str(self.root)),
                           ('spool', str(self.base / 'missing')),
                           ('launchProfile', 'Research')):
            with self.subTest(field=field):
                value = self.value()
                value[field] = raw
                with self.assertRaises(ValueError):
                    self.load(value)
        for profile, wrong in (('research', self.root), ('default', self.home)):
            value = self.value()
            value['principals'][0]['profiles'][profile]['expectedHome'] = str(wrong)
            with self.subTest(profile=profile), self.assertRaises(ValueError):
                self.load(value)
        value = self.value()
        value.update(launchProfile='default', launchHome=str(self.root))
        self.assertEqual(self.load(value).launch_home, self.root)

    def test_paths_must_be_absolute_existing_canonical_directories(self):
        file = self.base / 'ordinary-file'
        file.write_text('fixture', encoding='utf-8')
        raw_paths = ['workspace', str(self.base / 'missing'), str(file),
                     str(self.workspace) + os.sep, str(self.workspace) + os.sep + '.',
                     str(self.workspace) + os.sep + '..' + os.sep + 'workspace',
                     str(self.workspace) + ' ', str(self.workspace) + '.',
                     str(self.base / 'percent%20'), str(self.base / '$variable'),
                     str(self.base / '~home'), str(self.workspace) + ':stream',
                     '//server/share', '\\\\?\\C:\\device']
        for raw in raw_paths:
            with self.subTest(raw=raw):
                value = self.value()
                value['principals'][0]['profiles']['research']['roots'] = [raw]
                with self.assertRaises(ValueError):
                    self.load(value)
        with self.assertRaises(ValueError):
            self.module().BoundPolicy.load('relative-policy.json')

    def test_workspace_roots_cannot_overlap_managed_spool_forbidden_or_each_other(self):
        nested = self.workspace / 'nested'
        nested.mkdir()
        forbidden = self.base / 'forbidden'
        forbidden.mkdir()
        for root in (self.root, self.home, self.spool, self.base, forbidden):
            with self.subTest(root=root):
                value = self.value()
                value['principals'][0]['profiles']['research']['roots'] = [str(root)]
                with self.assertRaises(ValueError):
                    self.load(value, forbidden_roots=(forbidden,))
        value = self.value()
        value['principals'][0]['profiles']['research']['roots'] = [str(nested)]
        with self.assertRaises(ValueError):
            self.load(value)
        other = self.base / 'other-workspace'
        other.mkdir()
        value['principals'][0]['profiles']['research']['roots'] = [str(other)]
        self.assertIsNone(self.load(value, forbidden_roots=(forbidden,)).validate())


    def test_manifest_owner_is_an_os_identity_not_a_claim(self):
        value = self.value()
        value['owner'] = 'not-the-process-owner'
        with self.assertRaisesRegex(ValueError, 'owner'):
            self.load(value)

    def test_caller_must_own_manifest_root_homes_workspaces_and_spool(self):
        module = self.module()
        self.assertTrue(callable(getattr(module, '_path_owner', None)),
                        'OS file owner lookup missing')
        self.load()
        self.assertEqual(module._path_owner(self.manifest), module.current_owner())
        real_owner = module._path_owner
        for target in (self.manifest, self.root, self.home, self.workspace, self.spool):
            with self.subTest(target=target):
                def owner(path, *, selected=target):
                    return 'foreign-owner' if Path(path) == selected else real_owner(path)
                with patch.object(module, '_path_owner', side_effect=owner):
                    with self.assertRaisesRegex(ValueError, 'owner'):
                        self.load()
        with patch.object(module, '_path_owner', side_effect=OSError('owner unreadable')):
            with self.assertRaises(ValueError):
                self.load()

    def test_validate_detects_replacement_of_each_pinned_target(self):
        for target in (self.manifest, self.root, self.home, self.workspace, self.spool):
            with self.subTest(target=target):
                policy = self.load()
                parked = target.with_name(target.name + '-parked')
                target.rename(parked)
                try:
                    if target == self.manifest:
                        target.write_bytes(parked.read_bytes())
                    else:
                        target.mkdir()
                    with self.assertRaises(ValueError):
                        policy.validate()
                finally:
                    if target.is_dir():
                        target.rmdir()
                    else:
                        target.unlink()
                    parked.rename(target)

    def test_validate_rechecks_owners_and_process_owner(self):
        module = self.module()
        policy = self.load()
        with patch.object(module, 'current_owner', return_value='foreign-owner'):
            with self.assertRaises(ValueError):
                policy.validate()
        self.assertTrue(callable(getattr(module, '_path_owner', None)))
        real_owner = module._path_owner
        with patch.object(module, '_path_owner', side_effect=lambda p:
                          'foreign-owner' if Path(p) == self.workspace else real_owner(p)):
            with self.assertRaises(ValueError):
                policy.validate()

    def test_reparse_and_link_flags_on_any_ancestor_are_rejected(self):
        original = Path.lstat
        for flags, mode in ((0x400, 0o40700), (0, 0o120777)):
            with self.subTest(flags=flags, mode=mode):
                def lstat(path, *args, **kwargs):
                    info = original(path, *args, **kwargs)
                    if Path(path) == self.base:
                        return SimpleNamespace(st_mode=mode, st_file_attributes=flags,
                                               st_dev=info.st_dev, st_ino=info.st_ino)
                    return info
                with patch.object(Path, 'lstat', lstat):
                    with self.assertRaisesRegex(ValueError, 'link|reparse'):
                        self.load()


    def server(self):
        return SimpleNamespace(_launch_home=lambda: self.home,
                               _profile_home=lambda name: self.root if name == 'default' else self.home)

    def resolver(self, name):
        return self.root if name == 'default' else self.home

    def admit(self, policy, *, user_id='alice', profile='research', permission='read', connection='channel'):
        return policy.authorize({'provider': 'fixture', 'user_id': user_id},
                                profile, permission, connection)

    def test_authority_requires_binding_then_preserves_base_owner_contract(self):
        policy = self.load()
        with self.assertRaises(CapabilityError) as error:
            self.admit(policy)
        self.assertEqual(error.exception.status, 403)
        self.assertIs(policy.bind(self.server(), self.resolver), policy)
        owner = self.admit(policy)
        self.assertIsInstance(owner, Owner)
        self.assertEqual(owner, Owner('fixture', 'alice', 'research', 'channel',
                                     (self.workspace,), frozenset({'read', 'files.write'})))
        self.assertEqual(policy.profiles(owner), frozenset({'default', 'research'}))
        self.assertEqual(policy.path(owner, str(self.workspace / 'new.txt')),
                         str(self.workspace / 'new.txt'))

    def test_base_identity_and_permission_denials_precede_binding_or_filesystem_checks(self):
        policy = self.load()
        with patch.object(policy, 'validate', side_effect=AssertionError('must not inspect host')):
            for arguments, status in (({'user_id': 'outsider'}, 403),
                                      ({'permission': 'network'}, 403),
                                      ({'connection': ''}, 401)):
                with self.subTest(arguments=arguments), self.assertRaises(CapabilityError) as error:
                    self.admit(policy, **arguments)
                self.assertEqual(error.exception.status, status)

    def test_binding_checks_websocket_rest_launch_and_none_fallback_separately(self):
        policy = self.load()
        servers = [SimpleNamespace(_launch_home=lambda: self.root,
                                   _profile_home=self.resolver),
                   SimpleNamespace(_launch_home=lambda: self.home,
                                   _profile_home=lambda name: self.workspace),
                   SimpleNamespace(_launch_home=lambda: self.home,
                                   _profile_home=lambda name: None)]
        for server in servers:
            with self.subTest(server=server), self.assertRaises(CapabilityError) as error:
                policy.bind(server, self.resolver)
            self.assertEqual(error.exception.status, 403)
        with self.assertRaises(CapabilityError) as error:
            policy.bind(self.server(), lambda name: self.workspace)
        self.assertEqual(error.exception.status, 403)
        # None is only valid for a profile whose expected home IS the launch home.
        server = self.server()
        server._profile_home = lambda name: self.root if name == 'default' else None
        policy.bind(server, self.resolver)
        self.assertEqual(self.admit(policy).profile, 'research')

    def test_admission_rechecks_live_resolvers_and_failed_rebind_clears_authority(self):
        policy, server = self.load(), self.server()
        rest = {'research': self.home, 'default': self.root}
        policy.bind(server, rest.__getitem__)
        self.admit(policy)
        rest['research'] = self.workspace
        with self.assertRaises(CapabilityError) as error:
            self.admit(policy)
        self.assertEqual(error.exception.status, 403)
        rest['research'] = self.home
        server._profile_home = lambda name: self.workspace
        with self.assertRaises(CapabilityError):
            self.admit(policy)
        server._profile_home = self.resolver
        server._launch_home = lambda: self.root
        with self.assertRaises(CapabilityError):
            self.admit(policy)
        with self.assertRaises(CapabilityError):
            policy.bind(server, rest.__getitem__)
        server._launch_home = lambda: self.home
        with self.assertRaises(CapabilityError):
            self.admit(policy)

    def test_admission_rechecks_fingerprints_and_sanitizes_resolver_failures(self):
        policy = self.load().bind(self.server(), self.resolver)
        parked = self.workspace.with_name('parked-workspace')
        self.workspace.rename(parked)
        self.workspace.mkdir()
        with self.assertRaises(CapabilityError) as error:
            self.admit(policy)
        self.assertEqual(error.exception.status, 403)
        policy = self.load()
        def broken(name):
            raise RuntimeError('secret resolver internals')
        with self.assertRaises(CapabilityError) as error:
            policy.bind(self.server(), broken)
        self.assertEqual(error.exception.status, 403)
        self.assertNotIn('secret', str(error.exception))

    def test_loaded_binding_fields_grants_and_fingerprints_are_immutable(self):
        policy = self.load()
        for attribute in ('root', 'launch_profile', 'launch_home', 'spool'):
            with self.subTest(attribute=attribute), self.assertRaises(AttributeError):
                setattr(policy, attribute, self.workspace)
        with self.assertRaises(TypeError):
            policy._grants[('fixture', 'alice', 'research')] = ((self.base,), frozenset({'read'}))
        self.assertIsInstance(policy._fingerprints, tuple)
        with self.assertRaises(AttributeError):
            policy._fingerprints[0].owner = 'different-owner'


    def test_manifest_cannot_live_inside_a_writable_workspace(self):
        self.manifest = self.workspace / 'host-policy.json'
        with self.assertRaisesRegex(ValueError, 'manifest'):
            self.load()


    def test_manifest_hardlinks_are_not_authority(self):
        self.load()
        alias = self.workspace / 'hardlinked-policy.json'
        os.link(self.manifest, alias)
        with self.assertRaisesRegex(ValueError, 'link'):
            self.module().BoundPolicy.load(self.manifest)

    def test_forbidden_volume_root_is_canonical_and_blocks_all_workspaces(self):
        # A root-only path has no components, not an empty filename component.
        self.load()
        with self.assertRaisesRegex(ValueError, 'overlap'):
            self.module().BoundPolicy.load(self.manifest,
                                          forbidden_roots=(Path(self.base.anchor),))


    def test_separately_granted_nonlaunch_home_is_pinned_and_owner_checked(self):
        module = self.module()
        extra_home = self.root / 'profiles' / 'writing'
        extra_home.mkdir()
        value = self.value()
        value['principals'][0]['profiles']['writing'] = {
            'expectedHome': str(extra_home), 'roots': [str(self.workspace)], 'permissions': ['read']}
        real_owner = module._path_owner
        with patch.object(module, '_path_owner', side_effect=lambda p:
                          'foreign-owner' if Path(p) == extra_home else real_owner(p)):
            with self.assertRaises(ValueError):
                self.load(value)
        resolver = lambda name: extra_home if name == 'writing' else self.resolver(name)
        server = self.server()
        server._profile_home = resolver
        policy = self.load(value).bind(server, resolver)
        self.assertEqual(self.admit(policy, profile='writing').profile, 'writing')
        extra_home.rename(extra_home.with_name('writing-parked'))
        extra_home.mkdir()
        with self.assertRaises(CapabilityError) as error:
            self.admit(policy, profile='writing')
        self.assertEqual(error.exception.status, 403)

    def test_runtime_admission_rejects_ancestor_links_and_reparse_flags(self):
        policy = self.load().bind(self.server(), self.resolver)
        original = Path.lstat
        for mode, attributes in ((0o120777, 0), (0o40700, 0x400)):
            with self.subTest(mode=mode):
                def lstat(path, *args, **kwargs):
                    info = original(path, *args, **kwargs)
                    if Path(path) == self.base:
                        return SimpleNamespace(st_mode=mode, st_file_attributes=attributes)
                    return info
                with patch.object(Path, 'lstat', lstat):
                    with self.assertRaises(CapabilityError) as error:
                        self.admit(policy)
                    self.assertEqual(error.exception.status, 403)

    def test_runtime_admission_rechecks_owner_and_resolver_exceptions(self):
        module, server = self.module(), self.server()
        policy = self.load().bind(server, self.resolver)
        real_owner = module._path_owner
        with patch.object(module, '_path_owner', side_effect=lambda p:
                          'foreign-owner' if Path(p) == self.workspace else real_owner(p)):
            with self.assertRaises(CapabilityError) as error:
                self.admit(policy)
            self.assertEqual(error.exception.status, 403)
        def broken(name):
            raise RuntimeError('secret runtime resolver detail')
        server._profile_home = broken
        with self.assertRaises(CapabilityError) as error:
            self.admit(policy)
        self.assertEqual(error.exception.status, 403)
        self.assertNotIn('secret', str(error.exception))

    def test_policy_import_load_bind_and_admit_do_not_import_upstream(self):
        import builtins
        import sys
        importer = builtins.__import__
        before = set(sys.modules)
        def guarded(name, *args, **kwargs):
            if name.split('.')[0] in {'hermes_cli', 'hermes_constants', 'gateway', 'run_agent'}:
                self.fail('production policy imported upstream runtime: ' + name)
            return importer(name, *args, **kwargs)
        with patch.object(builtins, '__import__', guarded):
            importlib.reload(self.module())
            self.admit(self.load().bind(self.server(), self.resolver))
        self.assertFalse(any(name == 'hermes_cli' or name.startswith('hermes_cli.')
                             for name in set(sys.modules) - before))

    def test_profile_shaped_root_cannot_reroute_before_binding(self):
        value=self.value()
        value.update(root=str(self.home),launchProfile='default',launchHome=str(self.home))
        value['principals'][0]['profiles']={'default':{
            'expectedHome':str(self.home),'roots':[str(self.workspace)],'permissions':['read']}}
        with self.assertRaisesRegex(ValueError,'root'):
            self.load(value)

    def test_writable_composition_targets_cannot_overlap_protected_source(self):
        protected=self.base/'protected-source'
        protected.mkdir()
        value=self.value()
        value['spool']=str(protected)
        with self.assertRaisesRegex(ValueError,'overlap'):
            self.load(value,forbidden_roots=[protected])
        value=self.value()
        value.update(root=str(protected),launchProfile='default',launchHome=str(protected))
        value['principals'][0]['profiles']={'default':{
            'expectedHome':str(protected),'roots':[str(self.workspace)],'permissions':['read']}}
        with self.assertRaisesRegex(ValueError,'overlap'):
            self.load(value,forbidden_roots=[protected])

    def test_manifest_in_place_edits_invalidate_existing_admission(self):
        policy = self.load().bind(self.server(), self.resolver)
        with self.manifest.open('a', encoding='utf-8') as manifest:
            manifest.write('\n ')
        with self.assertRaises(CapabilityError) as error:
            self.admit(policy)
        self.assertEqual(error.exception.status, 403)


if __name__ == '__main__':
    unittest.main()
