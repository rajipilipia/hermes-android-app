"""Real pinned original DB/service composition; every home is synthetic pc-lab."""
from contextlib import closing
import asyncio
import os
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
UPSTREAM = Path('C:/example/hermes-agent')


class HistoryReads(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not Path(os.environ['HERMES_HOME']).resolve().is_relative_to(ROOT / '.cache' / 'pc-lab'):
            raise RuntimeError('use pc-startup-run.py synthetic runner')
        sys.path.insert(0, str(UPSTREAM))
        from hermes_state import SessionDB
        import warnings
        cls.warning_scope = warnings.catch_warnings()
        cls.warning_scope.__enter__()
        cls.addClassCleanup(cls.warning_scope.__exit__, None, None, None)
        warnings.filterwarnings('ignore', message="'audioop' is deprecated and slated for removal in Python 3.13",
                                category=DeprecationWarning, module=r'discord\.player')
        cls.SessionDB = SessionDB

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=os.environ['HERMES_HOME'])
        self.home = Path(self.temp.name)
        from hermes_constants import set_hermes_home_override
        self.token = set_hermes_home_override(self.home)
        self.db = self.SessionDB(db_path=self.home / 'state.db')

    def tearDown(self):
        self.db.close()
        from hermes_constants import reset_hermes_home_override
        reset_hermes_home_override(self.token)
        self.temp.cleanup()

    def row(self, sid, owner='work', parent=None, source='cli'):
        self.db.create_session(session_id=sid, source=source, profile_name=owner,
                               parent_session_id=parent)
        self.db.append_message(sid, 'user', 'searchable evidence ' + sid)

    def test_list_uses_original_materialization_with_owned_source_scope_and_totals(self):
        from pc.history import read_on_db
        self.row('owned')
        self.row('cron-owned', source='cron')
        self.row('foreign', owner='other')
        self.row('legacy', owner=None)
        self.row('mixed-root')
        self.row('mixed-child', owner='other', parent='mixed-root')
        result = read_on_db(self.db, 'GET /api/sessions', 'work',
                            {'limit': 100, 'min_messages': 1, 'exclude_sources': 'cron'}, home=self.home)
        self.assertEqual([r['id'] for r in result['sessions']], ['owned'])
        self.assertEqual(result['total'], 1)
        self.assertEqual(result['sessions'][0]['profile'], 'work')
        self.assertIn('preview', result['sessions'][0])
        self.assertNotIn('system_prompt', result['sessions'][0])
        self.assertEqual(self.db.get_session('legacy')['profile_name'], None)
        self.assertEqual(self.db.session_count(include_archived=True), 6)
    def test_search_uses_original_fts_and_excludes_foreign_hits_before_limit(self):
        from pc.history import read_on_db
        self.row('owned')
        self.db.set_session_title('owned', 'Distinct title')
        for index in range(40):
            self.row('foreign-' + str(index), owner='other')
        self.row('mixed')
        self.row('child', owner=None, parent='mixed')
        result = read_on_db(self.db, 'GET /api/sessions/search', 'work',
                            {'q': 'searchable', 'limit': 1}, home=self.home)
        self.assertEqual([r['session_id'] for r in result['results']], ['owned'])
        title = read_on_db(self.db, 'GET /api/sessions/search', 'work',
                           {'q': 'Distinct'}, home=self.home)
        self.assertEqual(title['results'][0]['id'], 'owned')
        self.assertEqual(read_on_db(self.db, 'GET /api/sessions/search', 'work',
                                   {'q': 'foreign'}, home=self.home)['results'], [])
    def test_timeline_and_around_use_original_exact_snapshot_and_reject_foreign_anchor(self):
        from pc.session_scope import execute_on_db
        from pc.catalog import CapabilityError
        self.row('owned')
        self.db.append_message('owned', 'assistant', 'answer')
        self.row('foreign', owner='other')
        timeline = execute_on_db(self.db, 'GET /api/sessions/{session_id}/timeline',
                                 'work', 'owned', home=self.home)
        self.assertEqual(timeline['entries'][0]['preview'], 'searchable evidence owned')
        anchor = timeline['entries'][0]['row_id']
        page = execute_on_db(self.db, 'GET /api/sessions/{session_id}/messages/around',
                             'work', 'owned', query={'row_id': anchor, 'limit': 2}, home=self.home)
        self.assertEqual([m['content'] for m in page['messages']], ['searchable evidence owned', 'answer'])
        other_anchor = self.db._read_one('SELECT id FROM messages WHERE session_id=?', ('foreign',))[0]
        with self.assertRaises(CapabilityError) as caught:
            execute_on_db(self.db, 'GET /api/sessions/{session_id}/messages/around', 'work', 'owned',
                          query={'row_id': other_anchor}, home=self.home)
        self.assertEqual(caught.exception.status, 404)
        for sid in ('own', 'foreign'):
            with self.subTest(sid=sid), self.assertRaises(CapabilityError):
                execute_on_db(self.db, 'GET /api/sessions/{session_id}/timeline', 'work', sid, home=self.home)
    def test_sidebar_original_slices_and_usage_are_filtered_at_snapshot_source(self):
        from pc.history import read_targets
        self.row('owned')
        self.row('cron-owned', source='cron')
        self.row('chat-owned', source='telegram')
        self.row('foreign', owner='other')
        self.db._write_sql('UPDATE sessions SET input_tokens=10 WHERE profile_name=?', ('work',))
        self.db._write_sql('UPDATE sessions SET input_tokens=999 WHERE profile_name=?', ('other',))
        targets = {'work': (self.db, self.home)}
        result = read_targets('GET /api/profiles/sessions/sidebar', targets,
                               {'recents_profile': 'all', 'recents_limit': 20,
                                'recents_exclude': 'cron,telegram', 'messaging_exclude': 'cli,cron'})
        self.assertEqual([r['id'] for r in result['recents']['sessions']], ['owned'])
        self.assertEqual([r['id'] for r in result['cron']['sessions']], ['cron-owned'])
        self.assertEqual([r['id'] for r in result['messaging']['sessions']], ['chat-owned'])
        self.assertEqual(result['recents']['profiles_usage'], {'work': {'tokens': 30, 'cost_usd': 0.0}})
        self.assertEqual(result['errors'], [])
        self.assertEqual(set(result['recents']['profiles_truncated']), {'work'})
        # Original global caches must not leak a previous owner's materialization.
        second = read_targets('GET /api/profiles/sessions/sidebar', {'other': (self.db, self.home)},
                                {'recents_profile': 'all'})
        self.assertEqual([r['id'] for r in second['recents']['sessions']], ['foreign'])
        self.assertEqual(set(second['recents']['profiles_usage']), {'other'})
    def test_granted_aggregate_pages_and_all_sidebar_never_enumerate_ungranted_db(self):
        from pc.history import execute_history
        from pc.policy import Policy
        from pc.catalog import CapabilityError, validate_call
        from hermes_cli.web_server_sessions import _session_db_path_for_profile
        from shutil import rmtree
        process_home = Path(os.environ['HERMES_HOME'])
        for name in ('readwork', 'readshared', 'readforeign'):
            directory = process_home / 'profiles' / name
            directory.mkdir(parents=True)
            (directory / 'config.yaml').write_text('{}\n', encoding='utf-8')
        self.addCleanup(lambda: [rmtree(process_home / 'profiles' / name, ignore_errors=True)
                                for name in ('readwork', 'readshared', 'readforeign')])
        for name in ('readwork', 'readshared'):
            seed = self.SessionDB(db_path=_session_db_path_for_profile(name))
            try:
                seed.create_session(session_id=name + '-owned', source='cli', profile_name=name)
                seed.append_message(name + '-owned', 'user', 'synthetic ' + name)
            finally:
                seed.close()
        # An invalid ungranted store is a tripwire: neither rows nor errors may
        # reveal its existence even when the caller explicitly selects all.
        (process_home / 'profiles' / 'readforeign' / 'state.db').write_text('not sqlite')
        policy = Policy.from_dict({'principals': [{'provider': 'fixture', 'user_id': 'alice', 'profiles': {
            name: {'roots': [str(self.home)], 'permissions': ['read']} for name in ('readwork', 'readshared')}}]})
        owner = policy.authorize({'provider': 'fixture', 'user_id': 'alice'}, 'readwork', 'read', 'connection')
        request = validate_call({'operation': 'GET /api/profiles/sessions', 'profile': 'readwork',
                                 'query': {'profile': 'all', 'limit': 200, 'offset': 1, 'min_messages': 1, 'order': 'recent'}})
        page = execute_history(request.operation.id, owner, request.query, policy)
        self.assertEqual(len(page['sessions']), 1)
        self.assertEqual(page['total'], 2)
        self.assertEqual(page['profile_totals'], {'readshared': 1, 'readwork': 1})
        self.assertEqual(page['errors'], [])
        side = execute_history('GET /api/profiles/sessions/sidebar', owner, {'recents_profile': 'all'}, policy)
        self.assertEqual({r['profile'] for r in side['recents']['sessions']}, {'readwork', 'readshared'})
        self.assertEqual(set(side['recents']['profiles_usage']), {'readwork', 'readshared'})
        only = execute_history('GET /api/profiles/sessions/sidebar', owner, {'recents_profile': 'readshared'}, policy)
        self.assertEqual({r['profile'] for r in only['messaging']['sessions']}, {'readshared'})
        for selector in ('readforeign', 'current', 'Readwork'):
            with self.subTest(selector=selector), self.assertRaises(CapabilityError):
                execute_history('GET /api/profiles/sessions', owner, {'profile': selector}, policy)
        _session_db_path_for_profile('readshared').write_bytes(b'fixture damaged store')
        partial = execute_history('GET /api/profiles/sessions/sidebar', owner, {'recents_profile': 'all'}, policy)
        self.assertEqual([r['profile'] for r in partial['recents']['sessions']], ['readwork'])
        self.assertEqual(partial['errors'], [{'profile': 'readshared', 'error': 'session store unavailable'}])
        self.assertTrue(partial['profiles_failed']['readshared']['retry'])
        failed = execute_history('GET /api/profiles/sessions/sidebar', owner, {'recents_profile': 'readshared'}, policy)
        self.assertTrue(failed['recents']['failed'])
        self.assertNotIn('sessions', failed['recents'])
    def test_registered_adapter_composes_original_auth_routes_for_startup_and_history(self):
        from pc.addon import Adapter
        from pc.catalog import validate_call
        from pc.policy import Policy
        from hermes_cli import web_server
        from hermes_cli.web_server_sessions import _session_db_path_for_profile
        from shutil import rmtree
        process_home = Path(os.environ['HERMES_HOME'])
        profile_home = process_home / 'profiles' / 'readbridge'
        profile_home.mkdir(parents=True)
        (profile_home / 'config.yaml').write_text('{}\n', encoding='utf-8')
        self.addCleanup(lambda: rmtree(profile_home, ignore_errors=True))
        seed = self.SessionDB(db_path=_session_db_path_for_profile('readbridge'))
        try:
            seed.create_session(session_id='bridge-owned', source='cli', profile_name='readbridge')
            seed.append_message('bridge-owned', 'user', 'real original middleware history')
        finally:
            seed.close()
        policy = Policy.from_dict({'principals': [{'provider': 'fixture', 'user_id': 'alice', 'profiles': {
            'readbridge': {'roots': [str(self.home)], 'permissions': ['read']}}}]})
        owner = policy.authorize({'provider': 'fixture', 'user_id': 'alice'}, 'readbridge', 'read', 'connection')
        app = web_server.app
        app.state.auth_required = True
        app.state.bound_host = '127.0.0.1'
        app.state.trusted_public_hosts = frozenset()
        class Transport:
            closed = False
        async def run():
            adapter = Adapter(app, None, policy, self.home / 'spool')
            try:
                async def call(operation, **kwargs):
                    request = validate_call({'operation': operation, 'profile': 'readbridge', **kwargs})
                    result = await adapter.invoke(request, owner, Transport())
                    self.assertEqual(result['status'], 200, result)
                    return result['body']
                self.assertEqual(await call('GET /api/profiles/active'), {'active': 'readbridge', 'current': 'readbridge'})
                self.assertIn('version', await call('GET /api/status'))
                self.assertIn('display', await call('GET /api/config/defaults'))
                self.assertIn('fields', await call('GET /api/config/schema'))
                self.assertEqual((await call('GET /api/fs/default-cwd'))['cwd'], str(self.home.resolve()))
                self.assertIn('OPENAI_API_KEY', await call('GET /api/env'))
                import json
                import socket
                from unittest.mock import patch
                (profile_home / 'config.yaml').write_text(json.dumps({
                    'model': {'provider': 'custom:lab', 'default': 'vendor/model-a'},
                    'custom_providers': [{'name': 'lab', 'base_url': 'https://fixture.invalid/v1',
                        'api_key': 'OPAQUE_FIXTURE', 'model': 'vendor/model-a',
                        'models': ['vendor/model-a'], 'discover_models': False}]}), encoding='utf-8')
                (profile_home / 'models_dev_cache.json').write_text(
                    json.dumps({'fixture': {'id': 'fixture', 'models': {}}}), encoding='utf-8')
                (profile_home / 'cache').mkdir(exist_ok=True)
                (profile_home / 'cache' / 'model_catalog.json').write_text(
                    json.dumps({'version': 1, 'providers': {}}), encoding='utf-8')
                with patch('hermes_cli.inventory._prewarm_pricing_async', return_value=None), \
                     patch.object(socket, 'create_connection', side_effect=AssertionError('network forbidden')) as connect_call, \
                     patch.object(socket, 'getaddrinfo', side_effect=AssertionError('network forbidden')) as dns_call:
                    picker = await call('GET /api/model/options', query={'explicit_only': True})
                    connect_call.assert_not_called()
                    dns_call.assert_not_called()
                self.assertEqual(picker['provider'], 'custom:lab')
                self.assertEqual(next(row for row in picker['providers'] if row['slug'] == 'custom:lab')['models'],
                                 ['vendor/model-a'])
                self.assertNotIn('OPAQUE_FIXTURE', json.dumps(picker))
                sidebar = await call('GET /api/profiles/sessions/sidebar', query={'recents_profile': 'all'})
                self.assertEqual(sidebar['recents']['sessions'][0]['id'], 'bridge-owned')
                listed = await call('GET /api/profiles/sessions', query={'limit': 200, 'profile': 'all'})
                self.assertEqual(listed['sessions'][0]['profile'], 'readbridge')
                search = await call('GET /api/sessions/search', query={'q': 'middleware'})
                self.assertEqual(search['results'][0]['id'], 'bridge-owned')
                timeline = await call('GET /api/sessions/{session_id}/timeline', pathParams={'session_id': 'bridge-owned'})
                await call('GET /api/sessions/{session_id}/messages/around', pathParams={'session_id': 'bridge-owned'},
                           query={'row_id': timeline['entries'][0]['row_id']})
            finally:
                await adapter.aclose()
        asyncio.run(run())
    def test_cyclic_or_incomplete_components_cannot_enter_original_recursive_readers(self):
        from pc.history import scoped_snapshot
        self.row('cycle-a')
        self.row('cycle-b', parent='cycle-a')
        self.db._write_sql('UPDATE sessions SET parent_session_id=? WHERE id=?', ('cycle-b', 'cycle-a'))
        self.row('orphan')
        with closing(sqlite3.connect(self.home / 'state.db')) as connection:
            connection.execute('UPDATE sessions SET parent_session_id=? WHERE id=?', ('absent-parent', 'orphan'))
            connection.commit()
        with scoped_snapshot(self.db, 'work') as view:
            self.assertEqual(view.session_count(include_archived=True), 0)

    def test_owned_list_authorization_and_materialization_share_snapshot_through_owner_change(self):
        from pc.history import read_on_db
        self.row('owned')
        path = self.home / 'state.db'
        class RacingDB(self.SessionDB):
            def list_sessions_rich(view, *args, **kwargs):
                with closing(sqlite3.connect(path)) as other:
                    other.execute('UPDATE sessions SET profile_name=? WHERE id=?', ('other', 'owned'))
                    other.commit()
                return super().list_sessions_rich(*args, **kwargs)
        reader = RacingDB(db_path=path, read_only=True)
        try:
            page = read_on_db(reader, 'GET /api/sessions', 'work', {}, home=self.home)
        finally:
            reader.close()
        self.assertEqual([row['id'] for row in page['sessions']], ['owned'])
        self.assertEqual(page['total'], 1)
        self.assertEqual(self.db.get_session('owned')['profile_name'], 'other')
        # A new snapshot must not reuse any previous authorization/row cache.
        self.assertEqual(read_on_db(self.db, 'GET /api/sessions', 'work', {}, home=self.home)['total'], 0)
    def test_around_requires_exact_anchor_at_catalog_ingress(self):
        from pc.catalog import CapabilityError, validate_call
        with self.assertRaises(CapabilityError) as caught:
            validate_call({'operation': 'GET /api/sessions/{session_id}/messages/around',
                           'profile': 'work', 'pathParams': {'session_id': 'owned'}})
        self.assertEqual(caught.exception.status, 400)
    def test_oversized_connected_lineage_is_failed_read_not_successful_empty_history(self):
        from pc.history import read_on_db
        from pc.catalog import CapabilityError
        self.row('root')
        def seed(connection):
            connection.executemany('INSERT INTO sessions(id,source,started_at,parent_session_id,profile_name) '
                'VALUES (?, ?, ?, ?, ?)',
                [('chain-' + str(i), 'cli', i + 1,
                  'root' if i == 0 else 'chain-' + str(i - 1), 'work') for i in range(4096)])
        self.db._execute_write(seed)
        with self.assertRaises(CapabilityError) as caught:
            read_on_db(self.db, 'GET /api/sessions', 'work', {}, home=self.home)
        self.assertEqual(caught.exception.status, 503)
        self.assertEqual(self.db.session_count(include_archived=True), 4097)
    def test_sidebar_preserves_original_corrupt_storage_signal_only_for_selected_sources(self):
        from pc.history import read_targets
        from hermes_state_health import note_storage_error
        with self.assertLogs('hermes_state_health', level='ERROR'):
            note_storage_error(self.home / 'state.db', sqlite3.DatabaseError('database disk image is malformed'))
        body = read_targets('GET /api/profiles/sessions/sidebar', {'work': (None, self.home)},
                            {'recents_profile': 'all'},
                            errors=[{'profile': 'work', 'error': 'session store unavailable'}])
        self.assertEqual(body['storage'], {'work': 'corrupt'})
        self.assertEqual(body['errors'], [{'profile': 'work', 'error': 'session store unavailable'}])


if __name__ == '__main__':
    unittest.main()
