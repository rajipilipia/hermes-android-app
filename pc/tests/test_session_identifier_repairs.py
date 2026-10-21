"""PC-04/05/08 regressions; upstream imports run only in a scrubbed cache child.

Original unsafe-service reproductions are explicitly fixture-only. The normal
suite always exercises the repair, never silently substitutes an old service.
"""
from __future__ import annotations

from contextlib import closing
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
UPSTREAM = Path('C:/example/hermes-agent')
CACHE = ROOT / '.cache' / 'port-checkpoints'


def profile_validator(value):
    from pc.identifiers import canonical_profile
    return canonical_profile(value)


class CanonicalProfiles(unittest.TestCase):
    def test_profiles_reject_aliases_lossy_case_whitespace_and_overlength(self):
        from pc.catalog import CapabilityError
        for name in ('all', 'current', 'Default', 'Work', ' work', 'work ',
                     'a' * 65, 'work\n', 'hermes', 'test', 'tmp', 'root', 'sudo'):
            with self.subTest(name=name), self.assertRaises(CapabilityError):
                profile_validator(name)

    def test_canonical_profile_is_returned_unaltered(self):
        for name in ('default', 'work', 'work_2', '9-team', 'a' * 64):
            with self.subTest(name=name):
                self.assertIs(profile_validator(name), name)
    def test_profile_schema_matches_validator_and_upstream_pinned_rules(self):
        from pc.identifiers import PROFILE_SCHEMA, canonical_profile
        from pc.catalog import CapabilityError, validate_schema
        import ast
        constants = ast.parse((UPSTREAM / 'hermes_constants.py').read_text(encoding='utf-8'))
        self.assertTrue(any(isinstance(n, ast.Constant) and n.value == '^[a-z0-9][a-z0-9_-]{0,63}$'
                            for n in ast.walk(constants)))
        for name in ('default', 'a' * 64, 'work_2', 'all', 'current', 'Default', 'work ', 'a' * 65, '', None, 0):
            with self.subTest(name=name):
                try:
                    canonical_profile(name)
                except CapabilityError:
                    with self.assertRaises(CapabilityError):
                        validate_schema(name, PROFILE_SCHEMA)
                else:
                    validate_schema(name, PROFILE_SCHEMA)

    def test_learning_ids_reject_traversal_ambiguous_memory_and_preserve_keys(self):
        from pc.identifiers import canonical_skill_name, learning_node_id, guard_learning_mutation
        from pc.catalog import CapabilityError
        for value in ('../../escaped', 'nested/name', 'Mixed', 'name ', 'a' * 65, 'con', 'nul.txt',
                      'memory:memory:-1:0123456789ab', 'memory:profile:01:0123456789ab',
                      'memory:memory:0', 'memory:memory:0:deadbeef', None):
            with self.subTest(value=value), self.assertRaises(CapabilityError):
                learning_node_id(value)
        for value in ('canonical-skill', 'valid.skill', 'memory:memory:0:0123456789ab', 'memory:profile:3:0123456789ab'):
            self.assertIs(learning_node_id(value), value)
        for operation, body in (('PUT /api/learning/node', {'id': 'canonical-skill', 'content': 'body'}),
                                ('DELETE /api/learning/node', {'id': 'canonical-skill'}),
                                ('DELETE /api/learning/node', {'id': 'memory:memory:0:0123456789ab'}),
                                ('PUT /api/skills/toggle', {'name': 'canonical-skill', 'enabled': True})):
            before = dict(body)
            with self.subTest(operation=operation), self.assertRaises(CapabilityError) as caught:
                guard_learning_mutation(operation, body)
            self.assertEqual(caught.exception.status, 403)
            self.assertEqual(body, before)
        self.assertIsNone(guard_learning_mutation('GET /api/learning/node', {'id': 'canonical-skill'}))


class IsolatedRuntimeHarness(unittest.TestCase):
    def test_actual_pinned_services_in_synthetic_home(self):
        CACHE.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix='pc-repair-session-home-', dir=CACHE) as directory:
            home = Path(directory)
            env = {k: v for k, v in os.environ.items() if k.upper() in {
                'SYSTEMROOT', 'WINDIR', 'COMSPEC', 'PATH', 'PATHEXT', 'SYSTEMDRIVE',
                'NUMBER_OF_PROCESSORS', 'PROCESSOR_ARCHITECTURE'}}
            env.update(HOME=str(home), USERPROFILE=str(home), HERMES_HOME=str(home),
                       APPDATA=str(home / 'appdata'), LOCALAPPDATA=str(home / 'localappdata'),
                       TMP=str(home), TEMP=str(home), TMPDIR=str(home),
                       PYTHONDONTWRITEBYTECODE='1', HERMES_DISABLE_LAZY_INSTALLS='1',
                       PC_REPAIR_SESSION_ISOLATED='1', PYTHONPATH=str(ROOT))
            result = subprocess.run([sys.executable, '-B', '-m', 'unittest',
                                     'pc.tests.test_session_identifier_repairs', '-v'],
                                    cwd=ROOT, env=env, text=True, capture_output=True, timeout=100)
            print(result.stdout + result.stderr)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


class ActualUpstreamCases(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        home = Path(os.environ['HERMES_HOME']).resolve()
        if not home.is_relative_to(CACHE.resolve()) or os.environ.get('PC_REPAIR_SESSION_ISOLATED') != '1':
            raise RuntimeError('upstream tests require a scrubbed project-cache child')
        sys.path.insert(0, str(UPSTREAM))
        from hermes_state import SessionDB
        cls.SessionDB = SessionDB

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='case-', dir=Path(os.environ['HERMES_HOME']))
        self.home = Path(self.temp.name)
        from hermes_constants import set_hermes_home_override
        self.home_token = set_hermes_home_override(self.home)
        self.db = self.SessionDB(db_path=self.home / 'state.db')

    def tearDown(self):
        self.db.close()
        from hermes_constants import reset_hermes_home_override
        reset_hermes_home_override(self.home_token)
        self.temp.cleanup()

    def row(self, sid, owner='work', parent=None, end=None, source='cli', title=None):
        self.db.create_session(session_id=sid, source=source, profile_name=owner,
                               parent_session_id=parent)
        if end:
            self.db._write_sql('UPDATE sessions SET end_reason = ? WHERE id = ?', (end, sid))
        if title:
            self.db.set_session_title(sid, title)
        self.db.append_message(sid, 'user', 'synthetic message ' + sid)

    def invoke(self, operation, sid, query=None, body=None):
        from pc.session_scope import execute_on_db
        return execute_on_db(self.db, operation, 'work', sid, query=query or {},
                             body=body, home=self.home)

    def test_foreign_middle_in_owned_root_tip_denied(self):
        from pc.catalog import CapabilityError
        self.row('root', end='compression')
        self.row('middle', owner='other', parent='root', end='compression')
        self.row('tip', parent='middle')
        with self.assertRaises(CapabilityError) as caught:
            self.invoke('GET /api/sessions/{session_id}/messages', 'root')
        self.assertEqual(caught.exception.status, 403)

    def test_archive_foreign_tool_descendant_denied_without_mutation(self):
        from pc.catalog import CapabilityError
        self.row('root', end='compression')
        self.row('tool-child', owner='other', parent='root', source='tool')
        with self.assertRaises(CapabilityError) as caught:
            self.invoke('PATCH /api/sessions/{session_id}', 'root', body={'archived': True})
        self.assertEqual(caught.exception.status, 403)
        self.assertFalse(self.db.get_session('root')['archived'])
        self.assertFalse(self.db.get_session('tool-child')['archived'])

    def test_deleted_exact_id_does_not_fall_back_to_foreign_prefix(self):
        from pc.catalog import CapabilityError
        self.row('exact')
        self.row('exact-foreign', owner='other')
        # Deterministic old closed-preflight/use race: exact was valid, but
        # disappears before the next authoritative operation starts.
        from hermes_cli.web_routers.sessions import _timeline_session_id
        self.assertEqual(_timeline_session_id(self.db, 'exact', 'work'), 'exact')
        self.db._write_sql('DELETE FROM messages WHERE session_id = ?', ('exact',))
        self.db._write_sql('DELETE FROM sessions WHERE id = ?', ('exact',))
        with self.assertRaises(CapabilityError) as caught:
            self.invoke('GET /api/sessions/{session_id}/messages', 'exact')
        self.assertEqual(caught.exception.status, 404)

    def test_owned_chain_read_and_atomic_flags_use_original_db_contracts(self):
        self.row('root', end='compression')
        self.row('tip', parent='root')
        first = self.invoke('GET /api/sessions/{session_id}/messages', 'root', query={'limit': 10})
        self.assertEqual(first['session_id'], 'tip')
        self.assertEqual([m['content'] for m in first['messages']],
                         ['synthetic message root', 'synthetic message tip'])
        result = self.invoke('PATCH /api/sessions/{session_id}', 'tip',
                             body={'title': 'Renamed', 'archived': True, 'pinned': True})
        self.assertEqual(result, {'ok': True, 'title': 'Renamed', 'archived': True, 'pinned': True})
        for sid in ('root', 'tip'):
            self.assertTrue(self.db.get_session(sid)['archived'])
            self.assertTrue(self.db.get_session(sid)['pinned'])
        again = self.invoke('GET /api/sessions/{session_id}/messages', 'root')
        self.assertEqual(len(again['messages']), 2)

    def test_adapter_learning_delete_refuses_before_any_archive_write(self):
        from pc.catalog import CapabilityError
        skill = self.home / 'skills' / 'malformed'
        skill.mkdir(parents=True)
        (skill / 'SKILL.md').write_text('---\nname: ../../escaped\ndescription: synthetic\n---\nBody\n', encoding='utf-8')
        (self.home / 'skills' / '.usage.json').write_text(json.dumps({
            '../../escaped': {'created_by': 'agent', 'state': 'active'}}), encoding='utf-8')
        if os.environ.get('PC_REPAIR_IDENTIFIERS_BASELINE') == '1':
            from agent.learning_mutations import delete_node
            action = lambda: delete_node('../../escaped')
        else:
            from pc.identifiers import guard_learning_mutation
            action = lambda: guard_learning_mutation('DELETE /api/learning/node', {'id': '../../escaped'})
        with self.assertRaises(CapabilityError):
            action()
        self.assertTrue(skill.is_dir())
        self.assertFalse((self.home / 'escaped').exists())
        self.assertFalse((self.home / 'skills' / '.archive').exists())

    def test_read_snapshot_survives_concurrent_exact_deletion(self):
        import sqlite3
        from pc.session_scope import execute_on_db
        self.row('exact')
        self.row('exact-foreign', owner='other')
        path = self.home / 'state.db'
        class RacingDB(self.SessionDB):
            def get_messages(view, *args, **kwargs):
                with closing(sqlite3.connect(path)) as other:
                    other.execute('DELETE FROM messages WHERE session_id = ?', ('exact',))
                    other.execute('DELETE FROM sessions WHERE id = ?', ('exact',))
                    other.commit()
                return super().get_messages(*args, **kwargs)
        reader = RacingDB(db_path=path, read_only=True)
        try:
            result = execute_on_db(reader, 'GET /api/sessions/{session_id}/messages', 'work', 'exact', home=self.home)
        finally:
            reader.close()
        self.assertEqual([m['content'] for m in result['messages']], ['synthetic message exact'])
        self.assertIsNone(self.db.get_session('exact'))
        self.assertEqual(self.db.resolve_session_id('exact'), 'exact-foreign')

    def test_patch_keeps_write_lock_through_authoritative_setter(self):
        import sqlite3
        from pc.session_scope import execute_on_db
        self.row('root')
        path, attempts = self.home / 'state.db', []
        class RacingDB(self.SessionDB):
            def set_session_archived(view, sid, value):
                with closing(sqlite3.connect(path, timeout=0)) as other:
                    try:
                        other.execute('UPDATE sessions SET profile_name = ? WHERE id = ?', ('other', sid))
                    except sqlite3.OperationalError as exc:
                        attempts.append(str(exc))
                    else:
                        raise AssertionError('owner changed between authorization and original setter')
                return super().set_session_archived(sid, value)
        writer = RacingDB(db_path=path)
        try:
            result = execute_on_db(writer, 'PATCH /api/sessions/{session_id}', 'work', 'root',
                                   body={'archived': True}, home=self.home)
        finally:
            writer.close()
        self.assertTrue(result['archived'])
        self.assertEqual(len(attempts), 1)
        self.assertIn('locked', attempts[0])
        self.assertEqual(self.db.get_session('root')['profile_name'], 'work')

    def test_atomic_patch_rolls_back_title_if_later_setter_refuses(self):
        from pc.catalog import CapabilityError
        from pc.session_scope import execute_on_db
        self.row('root', title='Original')
        class RefusingDB(self.SessionDB):
            def set_session_archived(view, sid, value):
                raise CapabilityError(403, 'synthetic late refusal')
        writer = RefusingDB(db_path=self.home / 'state.db')
        try:
            with self.assertRaises(CapabilityError):
                execute_on_db(writer, 'PATCH /api/sessions/{session_id}', 'work', 'root',
                              body={'title': 'Replacement', 'archived': True}, home=self.home)
        finally:
            writer.close()
        self.assertEqual(self.db.get_session_title('root'), 'Original')
        self.assertFalse(self.db.get_session('root')['archived'])

    def test_cross_owner_title_conflict_is_not_retired(self):
        from pc.catalog import CapabilityError
        self.row('root')
        self.row('other', owner='other', title='Reserved title')
        self.db._write_sql('UPDATE sessions SET archived = 1, hidden = 1 WHERE id = ?', ('other',))
        with self.assertRaises(CapabilityError) as caught:
            self.invoke('PATCH /api/sessions/{session_id}', 'root', body={'title': 'Reserved title'})
        self.assertEqual(caught.exception.status, 403)
        self.assertEqual(self.db.get_session_title('other'), 'Reserved title')
        self.assertIsNone(self.db.get_session_title('root'))

    def test_null_legacy_owner_and_unintegrated_operations_fail_closed(self):
        from pc.catalog import CapabilityError
        from pc.session_scope import WITHHELD, guard_session_forwarding, execute_on_db
        self.row('legacy', owner=None)
        with self.assertRaises(CapabilityError) as caught:
            self.invoke('GET /api/sessions/{session_id}', 'legacy')
        self.assertEqual(caught.exception.status, 403)
        for operation in WITHHELD:
            with self.subTest(operation=operation), self.assertRaises(CapabilityError) as caught:
                execute_on_db(self.db, operation, 'work', 'legacy', home=self.home)
            self.assertEqual(caught.exception.status, 403)
        with self.assertRaises(CapabilityError) as caught:
            guard_session_forwarding('GET /api/fs/download', session_id='legacy')
        self.assertEqual(caught.exception.status, 403)
        self.assertIsNone(guard_session_forwarding('GET /api/fs/download'))

    def test_public_hook_uses_exact_profile_store_and_returns_original_dto(self):
        from hermes_cli.web_server_sessions import _session_db_path_for_profile
        from pc.session_scope import execute_session_call
        path = _session_db_path_for_profile('default')
        self.assertTrue(path.resolve().is_relative_to(Path(os.environ['HERMES_HOME']).resolve()))
        seed = self.SessionDB(db_path=path)
        try:
            seed.create_session(session_id='public-exact', source='cli', profile_name='default')
            seed.append_message('public-exact', 'user', 'synthetic public hook')
        finally:
            seed.close()
        updated = execute_session_call('PATCH /api/sessions/{session_id}', 'default', 'public-exact',
                                       body={'title': 'Public renamed', 'archived': True})
        self.assertEqual(updated['title'], 'Public renamed')
        detail = execute_session_call('GET /api/sessions/{session_id}', 'default', 'public-exact')
        self.assertEqual(detail['profile'], 'default')
        self.assertEqual(detail['title'], 'Public renamed')
        self.assertTrue(detail['archived'])
        messages = execute_session_call('GET /api/sessions/{session_id}/messages', 'default', 'public-exact')
        self.assertEqual(messages['messages'][0]['content'], 'synthetic public hook')

    def test_actual_selected_skill_and_archive_destination_validation(self):
        from pc.identifiers import validate_selected_skill
        from pc.catalog import CapabilityError
        root = self.home / 'skills'
        skill = root / 'category' / 'canonical-skill'
        skill.mkdir(parents=True)
        content = '---\nname: canonical-skill\ndescription: synthetic\n---\nBody\n'
        (skill / 'SKILL.md').write_text(content, encoding='utf-8')
        self.assertEqual(validate_selected_skill('canonical-skill', skill, root,
                          archive_destination=root / '.archive' / 'canonical-skill', replacement=content), skill)
        for destination in (root / 'escaped', self.home / 'escaped', root / '.archive' / '..' / 'escaped'):
            with self.subTest(destination=destination), self.assertRaises(CapabilityError):
                validate_selected_skill('canonical-skill', skill, root, archive_destination=destination)
        (skill / 'SKILL.md').write_text(content.replace('name: canonical-skill', 'name: ../../escaped'), encoding='utf-8')
        with self.assertRaises(CapabilityError):
            validate_selected_skill('canonical-skill', skill, root,
                                    archive_destination=root / '.archive' / 'canonical-skill')
        self.assertTrue(skill.is_dir())
        self.assertFalse((root / '.archive').exists())
        self.assertFalse((self.home / 'escaped').exists())

    def test_upstream_original_delete_reproduces_escape_inside_fixture(self):
        from agent.learning_mutations import delete_node
        skill = self.home / 'skills' / 'malformed'
        skill.mkdir(parents=True)
        (skill / 'SKILL.md').write_text('---\nname: ../../escaped\ndescription: synthetic\n---\nBody\n', encoding='utf-8')
        (self.home / 'skills' / '.usage.json').write_text(json.dumps({
            '../../escaped': {'created_by': 'agent', 'state': 'active'}}), encoding='utf-8')
        result = delete_node('../../escaped')
        self.assertTrue(result['ok'], result)
        self.assertTrue((self.home / 'escaped' / 'SKILL.md').is_file())
        self.assertFalse(skill.exists())


def load_tests(loader, tests, pattern):
    suite = unittest.TestSuite()
    if os.environ.get('PC_REPAIR_SESSION_ISOLATED') == '1':
        suite.addTests(loader.loadTestsFromTestCase(ActualUpstreamCases))
    else:
        suite.addTests(loader.loadTestsFromTestCase(CanonicalProfiles))
        suite.addTests(loader.loadTestsFromTestCase(IsolatedRuntimeHarness))
    return suite


if __name__ == '__main__':
    unittest.main()
