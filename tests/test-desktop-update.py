"""Private Git fixtures only; run directly with Python (no discovery elsewhere)."""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

HERE = Path(__file__).absolute().parent
SCRIPT = HERE.parent / 'scripts' / 'update-desktop.py'
CACHE = HERE.parent / '.cache' / 'desktop-update-tests'


class UpdaterTests(unittest.TestCase):
    def setUp(self):
        CACHE.mkdir(parents=True, exist_ok=True)
        self.tmp = tempfile.TemporaryDirectory(dir=CACHE)
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.repo = self.root / 'upstream'
        self.project = self.root / 'project'
        self.repo.mkdir()
        self.project.mkdir()
        self.env = {k: v for k, v in os.environ.items() if not k.startswith('GIT_')}
        self.env.update(GIT_CONFIG_NOSYSTEM='1', GIT_CONFIG_GLOBAL=os.devnull,
                        GIT_AUTHOR_NAME='Fixture', GIT_AUTHOR_EMAIL='fixture@invalid',
                        GIT_COMMITTER_NAME='Fixture', GIT_COMMITTER_EMAIL='fixture@invalid')
        self.git('init', '-q')
        self.put('apps/desktop/src/keep.ts', b'old\r\n\x00')
        self.put('apps/desktop/src/remove.ts', b'remove')
        self.put('apps/desktop/electron/owned.ts', b'owned')
        self.put('apps/desktop/electron/unowned.ts', b'unowned')
        self.put('apps/shared/src/transport.ts', b'transport')
        self.put('LICENSE', b'license')
        self.put('package-lock.json', b'lock1')
        self.base = self.commit()
        files = []
        for source in ('apps/desktop/src/keep.ts', 'apps/desktop/src/remove.ts',
                       'apps/desktop/electron/owned.ts', 'LICENSE'):
            data = (self.repo / source).read_bytes()
            dest = 'vendor/hermes/' + source
            self.local(dest, data)
            files.append(dict(source=source, path=dest, bytes=len(data),
                              sha256=hashlib.sha256(data).hexdigest()))
        self.manifest = dict(commit=self.base, upstream='fixture',
                             installedRendererFingerprint='OLD-FINGERPRINT', files=files)
        self.local('vendor/hermes/source-manifest.json', json.dumps(self.manifest).encode())
        transport = 'apps/shared/src/transport.ts'
        self.local('src/upstream/transport.ts', b'transport')
        self.provenance = dict(upstream_commit=self.base, vendored_files_byte_verified={
            'src/upstream/transport.ts': dict(upstream_path=transport,
                                              sha256=hashlib.sha256(b'transport').hexdigest())})
        self.local('docs/evidence/source-provenance.json', json.dumps(self.provenance).encode())
        for name in ('android/signing-certificate.sha256', '.cache/prototype-debug.keystore',
                     'package.json', 'pc/production-source-pins.json', 'profiles/secret.yaml',
                     'src/desktop/capability-contract.json', 'artifacts/accepted.apk'):
            self.local(name, b'SENSITIVE-SENTINEL')

    def git(self, *args, data=None):
        return subprocess.check_output(['git', '-c', 'core.hooksPath=' + str(self.root / 'no-hooks'),
                                        '-c', 'commit.gpgSign=false', '-C', str(self.repo), *args],
                                       input=data, env=self.env).decode().strip()

    def put(self, name, data):
        p = self.repo / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data)

    def local(self, name, data):
        p = self.project / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data)

    def commit(self):
        self.git('add', '--all')
        self.git('commit', '-qm', 'private fixture')
        return self.git('rev-parse', 'HEAD')

    def cli(self, *args):
        return subprocess.run([sys.executable, '-B', str(SCRIPT), '--project', str(self.project),
                               '--upstream', str(self.repo), *args], env=self.env,
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)

    def snapshot(self):
        return {p.relative_to(self.project).as_posix(): p.read_bytes()
                for p in self.project.rglob('*') if p.is_file()}

    def report(self, *args):
        p = self.cli(*args)
        self.assertEqual(p.returncode, 0, p.stderr)
        return json.loads(p.stdout)

    def test_default_check_is_read_only(self):
        before = self.snapshot()
        directories = {p.relative_to(self.project) for p in self.project.rglob('*') if p.is_dir()}
        report = self.report()
        self.assertEqual(before, self.snapshot())
        self.assertEqual(directories, {p.relative_to(self.project) for p in self.project.rglob('*') if p.is_dir()})
        self.assertEqual(report['candidateCommit'], self.base)
        self.assertEqual(report['requestedRef'], 'HEAD')
        self.assertEqual(report['changes'], dict(added=[], changed=[], deleted=[]))
        self.assertEqual(report['status'], 'review-only; compatibility and parity unverified')
        self.assertIsNone(report['installedRendererFingerprint'])
        self.assertTrue(report['reviewRequired']['compatibility'])

    def test_inventory_add_change_remove_and_unowned_review(self):
        self.put('apps/desktop/src/keep.ts', b'new\x00\r\n$Format:%H$')
        (self.repo / 'apps/desktop/src/remove.ts').unlink()
        self.put('apps/desktop/src/new/deep.ts', b'new inventory')
        self.put('apps/desktop/electron/new.ts', b'not approved')
        self.put('package-lock.json', b'lock2')
        self.put('NOTICE', b'new notice')
        commit = self.commit()
        # Worktree dirt must not participate; export-subst must not rewrite object bytes.
        self.put('apps/desktop/src/keep.ts', b'DIRTY WORKTREE')
        self.put('apps/desktop/src/untracked.ts', b'untracked')
        before = self.snapshot()
        report = self.report('--ref', commit)
        self.assertEqual(before, self.snapshot())
        self.assertEqual(report['changes'], dict(added=['apps/desktop/src/new/deep.ts'],
                         changed=['apps/desktop/src/keep.ts'], deleted=['apps/desktop/src/remove.ts']))
        sources = {x['source'] for x in report['files']}
        self.assertIn('apps/desktop/src/new/deep.ts', sources)
        self.assertNotIn('apps/desktop/electron/new.ts', sources)
        self.assertNotIn('apps/desktop/src/untracked.ts', sources)
        self.assertEqual(report['outsideScopeChanges']['added'], ['NOTICE', 'apps/desktop/electron/new.ts'])
        self.assertEqual(report['reviewSignals']['dependencies'], ['package-lock.json'])
        self.assertEqual(report['reviewSignals']['licenses'], ['NOTICE'])
        self.assertIn('apps/desktop/src', report['sourceRoots'])

    def test_byte_exact_stage_hashes_and_preservation(self):
        content = b'\x00\xff\r\n$Format:%H$\n'
        self.put('apps/desktop/src/keep.ts', content)
        self.put('apps/desktop/src/new.ts', b'new')
        self.put('.gitattributes', b'*.ts export-subst\n')
        commit = self.commit()
        self.put('apps/desktop/src/keep.ts', b'not this')
        before = self.snapshot()
        report = self.report('--stage', '.cache/candidate', '--ref', commit)
        stage = self.project / '.cache/candidate'
        manifest = json.loads((stage / 'manifest.json').read_bytes())
        diff = json.loads((stage / 'diff-report.json').read_bytes())
        self.assertEqual(diff, report)
        self.assertEqual(manifest['candidateCommit'], commit)
        self.assertEqual(manifest['status'], 'review-only; compatibility and parity unverified')
        self.assertIsNone(manifest['installedRendererFingerprint'])
        self.assertNotIn('OLD-FINGERPRINT', json.dumps(manifest))
        self.assertEqual((stage / 'source/apps/desktop/src/keep.ts').read_bytes(), content)
        for entry in manifest['files']:
            raw = (stage / entry['path']).read_bytes()
            self.assertEqual(len(raw), entry['bytes'])
            self.assertEqual(hashlib.sha256(raw).hexdigest(), entry['sha256'])
        after = self.snapshot()
        self.assertEqual(before, {k: v for k, v in after.items() if not k.startswith('.cache/candidate/')})
        self.assertEqual(set(after) - set(before),
                         {'.cache/candidate/' + x['path'] for x in manifest['files']}
                         | {'.cache/candidate/manifest.json', '.cache/candidate/diff-report.json'})
        again = self.cli('--stage', '.cache/candidate')
        self.assertEqual(again.returncode, 2)
        self.assertEqual(after, self.snapshot())

    def test_casefold_collisions_rejected_before_stage_creation(self):
        # Use Git index plumbing: Windows worktrees cannot represent both names.
        oid = self.git('hash-object', '-w', '--stdin', data=b'collision')
        self.git('update-index', '--add', '--cacheinfo', '100644', oid, 'apps/desktop/src/KEEP.ts')
        tree = self.git('write-tree')
        commit = self.git('commit-tree', tree, '-p', self.base, data=b'collision fixture\n')
        before = self.snapshot()
        result = self.cli('--ref', commit, '--stage', '.cache/collision')
        self.assertEqual(result.returncode, 2, result.stdout)
        self.assertIn('collision', result.stderr.lower())
        self.assertEqual(before, self.snapshot())
        self.assertFalse((self.project / '.cache/collision').exists())

    def test_provenance_hash_mismatch_refused(self):
        self.manifest['files'][0]['sha256'] = '0' * 64
        self.local('vendor/hermes/source-manifest.json', json.dumps(self.manifest).encode())
        before = self.snapshot()
        result = self.cli('--stage', '.cache/bad-provenance')
        self.assertEqual(result.returncode, 2, result.stdout)
        self.assertIn('provenance', result.stderr.lower())
        self.assertEqual(before, self.snapshot())

    def test_stage_path_traversal_and_active_destinations_rejected(self):
        before = self.snapshot()
        for path in ('../escape', '.cache/../escape', '.cache//bad', 'vendor/hermes/new',
                     '.cache', '.cache/prototype-debug.keystore', '/absolute', '.cache/C:drive', '.cache/back\\slash',
                     '.cache/trailing.', '.cache/CON', '.cache/ space ', '.cache/./bad'):
            with self.subTest(path=path):
                result = self.cli('--stage', path)
                self.assertEqual(result.returncode, 2, result.stdout)
                self.assertEqual(before, self.snapshot())

    def test_invalid_literal_refs_and_unknown_options_rejected(self):
        before = self.snapshot()
        for ref in ('', '--help', 'HEAD~1', 'HEAD^{tree}', 'HEAD:path', self.base[:12],
                    ' ' + self.base, self.base + ' ', 'HEAD\n', 'missing-branch', 'refs/heads/../main'):
            with self.subTest(ref=ref):
                result = self.cli('--ref=' + ref, '--stage', '.cache/invalid')
                self.assertEqual(result.returncode, 2, result.stdout)
                self.assertEqual(before, self.snapshot())
        self.assertEqual(self.cli('--apply').returncode, 2)
        self.assertEqual(self.cli('--ups', str(self.repo)).returncode, 2)

    def test_named_ref_is_preserved_and_resolved_once_to_commit(self):
        self.git('tag', 'Review.Candidate-1', self.base)
        report = self.report('--ref', 'Review.Candidate-1')
        self.assertEqual(report['requestedRef'], 'Review.Candidate-1')
        self.assertEqual(report['candidateCommit'], self.base)

    def unsafe_index_commit(self, mode, name, oid):
        self.git('update-index', '--add', '--cacheinfo', mode, oid, name)
        return self.git('commit-tree', self.git('write-tree'), '-p', self.base, data=b'unsafe fixture\n')

    def test_git_symlink_rejected_without_reading_target(self):
        oid = self.git('hash-object', '-w', '--stdin', data=b'../../profiles/secret.yaml')
        commit = self.unsafe_index_commit('120000', 'apps/desktop/src/link.ts', oid)
        before = self.snapshot()
        result = self.cli('--ref', commit, '--stage', '.cache/unsafe-link')
        self.assertEqual(result.returncode, 2, result.stdout)
        self.assertIn('Unsafe Git tree entry', result.stderr)
        self.assertEqual(before, self.snapshot())

    def test_git_submodule_rejected(self):
        commit = self.unsafe_index_commit('160000', 'apps/desktop/src/submodule', self.base)
        result = self.cli('--ref', commit, '--stage', '.cache/unsafe-submodule')
        self.assertEqual(result.returncode, 2, result.stdout)
        self.assertIn('Unsafe Git tree entry', result.stderr)
        self.assertFalse((self.project / '.cache/unsafe-submodule').exists())

    def test_linked_cache_parent_rejected(self):
        outside = self.root / 'outside'
        outside.mkdir()
        link = self.project / '.cache' / 'linked'
        if os.name == 'nt':
            # Junctions exercise actual Windows reparse metadata without symlink privilege.
            result = subprocess.run(['cmd', '/c', 'mklink', '/J', str(link), str(outside)],
                                    stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.addCleanup(os.rmdir, link)
        else:
            link.symlink_to(outside, target_is_directory=True)
            self.addCleanup(link.unlink)
        result = self.cli('--stage', '.cache/linked/candidate')
        self.assertEqual(result.returncode, 2, result.stdout)
        self.assertIn('Link/reparse', result.stderr)
        self.assertEqual(list(outside.iterdir()), [])

    def test_check_reports_inconsistent_provenance_but_stage_refuses(self):
        self.manifest['files'].append(dict(source='apps/desktop/src/not-in-git.js',
            path='vendor/hermes/apps/desktop/src/not-in-git.js', bytes=3, sha256='0' * 64))
        self.manifest['files'][0]['sha256'] = '1' * 64
        self.local('vendor/hermes/source-manifest.json', json.dumps(self.manifest).encode())
        before = self.snapshot()
        result = self.cli()
        self.assertEqual(result.returncode, 1, result.stderr)
        report = json.loads(result.stdout)
        self.assertEqual(report['provenanceIssues']['missingFromPinnedGit'], ['apps/desktop/src/not-in-git.js'])
        self.assertEqual(report['provenanceIssues']['hashMismatch'], ['apps/desktop/src/keep.ts'])
        self.assertIn('apps/desktop/src/not-in-git.js', report['changes']['deleted'])
        refused = self.cli('--stage', '.cache/untrusted-baseline')
        self.assertEqual(refused.returncode, 2, refused.stdout)
        self.assertIn('provenance', refused.stderr.lower())
        self.assertEqual(before, self.snapshot())

    def test_duplicate_git_tree_names_rejected(self):
        oid = self.git('hash-object', '-w', '--stdin', data=b'duplicate')
        raw = (b'100644 keep.ts\0' + bytes.fromhex(oid)) * 2
        tree = self.git('hash-object', '-w', '--literally', '-t', 'tree', '--stdin', data=raw)
        for name in ('src', 'desktop', 'apps'):
            tree = self.git('mktree', data=f'040000 tree {tree}\t{name}\n'.encode())
        commit = self.git('commit-tree', tree, '-p', self.base, data=b'duplicate fixture\n')
        before = self.snapshot()
        result = self.cli('--ref', commit, '--stage', '.cache/duplicate')
        self.assertEqual(result.returncode, 2, result.stdout)
        self.assertIn('duplicate', result.stderr.lower())
        self.assertEqual(before, self.snapshot())

    def test_blob_reads_are_batched_not_one_process_per_file(self):
        from unittest.mock import patch
        spec = importlib.util.spec_from_file_location('draft_updater', SCRIPT)
        updater = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(updater)
        for number in range(30):
            self.put(f'apps/desktop/src/batch-{number}.ts', str(number).encode())
        self.commit()
        with patch.object(updater, 'git', wraps=updater.git) as calls:
            report, payload = updater.inspect(self.project, self.repo, 'HEAD')
        self.assertEqual(len(report['changes']['added']), 30)
        batches = [c for c in calls.call_args_list if c.args[1:3] == ('cat-file', '--batch')]
        self.assertEqual(len(batches), 2)
        self.assertLessEqual(calls.call_count, 7)
        self.assertEqual(len(payload), 35)

    def test_git_replace_refs_cannot_substitute_candidate_bytes(self):
        self.put('apps/desktop/src/keep.ts', b'replacement')
        replacement = self.commit()
        self.git('replace', self.base, replacement)
        report = self.report('--ref', self.base)
        entry = next(x for x in report['files'] if x['source'] == 'apps/desktop/src/keep.ts')
        self.assertEqual(entry['sha256'], hashlib.sha256(b'old\r\n\x00').hexdigest())
        self.assertEqual(report['candidateCommit'], self.base)

    def test_unsafe_manifest_source_and_duplicate_targets_rejected(self):
        original = json.dumps(self.manifest)
        before = self.snapshot()
        for source in ('../escape', '/absolute', 'apps/desktop/src/../escape', 'apps/desktop/src/CON.ts'):
            with self.subTest(source=source):
                altered = json.loads(original)
                altered['files'][0]['source'] = source
                altered['files'][0]['path'] = 'vendor/hermes/' + source
                self.local('vendor/hermes/source-manifest.json', json.dumps(altered).encode())
                self.assertEqual(self.cli('--stage', '.cache/unsafe').returncode, 2)
                self.assertFalse((self.project / '.cache/unsafe').exists())
        altered = json.loads(original)
        altered['files'].append(altered['files'][0])
        self.local('vendor/hermes/source-manifest.json', json.dumps(altered).encode())
        self.assertEqual(self.cli('--stage', '.cache/unsafe').returncode, 2)
        self.local('vendor/hermes/source-manifest.json', original.encode())
        self.assertEqual(before, self.snapshot())


if __name__ == '__main__':
    unittest.main(verbosity=2)
