"""Behavioral regressions; fixtures are synthetic, never actual APK/toolchain proof."""
import importlib.util
import pathlib
import tempfile
import unittest
import sys

SCRIPTS = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SCRIPTS))


def builder():
    # The entry point must be safely importable; importing must not invoke npm/signers.
    import ast
    tree = ast.parse((SCRIPTS / 'build-apk.py').read_text())
    if not any(isinstance(n, ast.If) and '__name__' in ast.unparse(n.test) for n in tree.body):
        raise AssertionError('Builder is not import-safe; it signs to final output before source rejection')
    spec = importlib.util.spec_from_file_location('apk_builder_entry', SCRIPTS / 'build-apk.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class PublicationRegression(unittest.TestCase):
    def test_rejected_source_never_replaces_previous_artifact_set(self):
        module = builder()
        with tempfile.TemporaryDirectory(prefix='apk-fixture-', dir=SCRIPTS.parent / '.cache') as tmp:
            root = pathlib.Path(tmp)
            out = root / 'artifacts'
            out.mkdir()
            previous = {'hermes-android-prototype-debug.apk': b'accepted APK',
                        'build-manifest.json': b'accepted manifest', 'SHA256SUMS': b'accepted checksum'}
            for name, value in previous.items():
                (out / name).write_bytes(value)
            stage = root / 'candidate'
            stage.mkdir()
            (stage / 'new.apk').write_bytes(b'rejected APK')
            with self.assertRaisesRegex(module.BuildError, 'source inputs changed'):
                module.publish_accepted(root, stage, lambda: (_ for _ in ()).throw(
                    module.BuildError('source inputs changed')))
            self.assertEqual({n: (out / n).read_bytes() for n in previous}, previous)
            self.assertFalse((out / 'accepted-apk.json').exists())


class FixtureCase(unittest.TestCase):
    def setUp(self):
        self.module = builder()
        self.temp = tempfile.TemporaryDirectory(prefix='apk-paths-', dir=SCRIPTS.parent / '.cache')
        self.base = pathlib.Path(self.temp.name)
        self.root = self.base / 'root'
        self.root.mkdir()
        self.addCleanup(self.temp.cleanup)



class ContainmentRegression(FixtureCase):
    def test_input_symlink_rejected_without_reading_target(self):
        self.assertTrue(hasattr(self.module, 'read_guarded'), 'Missing per-file no-follow input boundary')
        target = self.base / 'outside.txt'
        target.write_bytes(b'outside fixture')
        link = self.root / 'asset.js'
        link.symlink_to(target)
        with self.assertRaisesRegex(self.module.BuildError, 'link|reparse'):
            self.module.read_guarded(self.root, link)

    def test_existing_child_output_link_cannot_overwrite_outside(self):
        self.assertTrue(hasattr(self.module, 'write_new'), 'Missing child output boundary')
        target = self.base / 'outside.txt'
        target.write_bytes(b'preserve')
        link = self.root / 'unsigned.apk'
        link.symlink_to(target)
        with self.assertRaises(self.module.BuildError):
            self.module.write_new(self.root, link, b'overwrite')
        self.assertEqual(target.read_bytes(), b'preserve')

    def test_directory_link_rejected_for_input_and_output(self):
        self.assertTrue(hasattr(self.module, 'guard'), 'Missing parent reparse boundary')
        outside = self.base / 'outside'
        outside.mkdir()
        (outside / 'asset').write_bytes(b'outside fixture')
        alias = self.root / 'linked'
        alias.symlink_to(outside, target_is_directory=True)
        for path in (alias / 'asset', alias / 'new.apk'):
            with self.assertRaisesRegex(self.module.BuildError, 'link|reparse'):
                self.module.guard(self.root, path)

    def test_parent_above_project_root_cannot_hide_reparse_escape(self):
        actual = self.base / 'actual'
        (actual / 'root').mkdir(parents=True)
        (actual / 'root/input').write_bytes(b'external fixture')
        alias = self.base / 'alias'
        alias.symlink_to(actual, target_is_directory=True)
        with self.assertRaisesRegex(self.module.BuildError, 'link|reparse'):
            self.module.read_guarded(alias / 'root', alias / 'root/input')

    def test_publication_rejects_symlink_pointer(self):
        target = self.base / 'external-pointer.json'
        target.write_bytes(b'preserve')
        out = self.root / 'artifacts'
        out.mkdir()
        (out / 'accepted-apk.json').symlink_to(target)
        stage = BundleRegression.candidate(self, 'candidate', b'valid synthetic bundle')
        with self.assertRaisesRegex(self.module.BuildError, 'link|reparse'):
            self.module.publish_accepted(self.root, stage, lambda: None)
        self.assertEqual(target.read_bytes(), b'preserve')


class SnapshotRegression(FixtureCase):
    def test_captured_source_is_actual_build_input_during_A_B_A_change(self):
        self.assertTrue(hasattr(self.module, 'capture_files'), 'Missing captured compilation inputs')
        source = self.root / 'src/payload.txt'
        source.parent.mkdir()
        source.write_bytes(b'A')
        frozen = self.root / 'work/source'
        hashes = self.module.capture_files(self.root, frozen, ['src/payload.txt'])
        source.write_bytes(b'transient B')
        # A compiler reading the actual build cwd still sees A, not transient B.
        consumed = self.module.read_guarded(self.root, frozen / 'src/payload.txt')
        source.write_bytes(b'A')
        self.assertEqual(consumed, b'A')
        self.assertEqual(hashes, self.module.hash_files(self.root, ['src/payload.txt']))

    def test_direct_notices_are_captured_not_generated_dist_inputs(self):
        self.assertTrue(hasattr(self.module, 'source_paths'), 'Missing explicit source snapshot inventory')
        for directory in ('src', 'android', 'vendor', 'public', 'tests', 'scripts'):
            (self.root / directory).mkdir()
        for name in ('src/renderer.tsx', 'vendor/desktop.tsx', 'public/asset.svg', 'android/assets/native.js'):
            file = self.root / name
            file.parent.mkdir(parents=True, exist_ok=True)
            file.write_bytes(b'fixture source')
        for name in self.module.REQUIRED_FILES:
            file = self.root / name
            file.parent.mkdir(parents=True, exist_ok=True)
            file.write_bytes(b'fixture input')
        (self.root / 'dist').mkdir()
        (self.root / 'dist/index.html').write_bytes(b'stale fixture output')
        paths = self.module.source_paths(self.root)
        for name in ('src/renderer.tsx', 'vendor/desktop.tsx', 'public/asset.svg',
                     'android/assets/native.js', 'tsconfig.json'):
            self.assertIn(name, paths)
        self.assertIn('LICENSE.upstream', paths)
        self.assertIn('THIRD_PARTY_NOTICES.md', paths)
        self.assertFalse(any(p.startswith('dist/') for p in paths))
        captured = self.module.capture_files(self.root, self.root / 'work/source', paths)
        self.assertIn('LICENSE.upstream', captured)
        self.assertIn('THIRD_PARTY_NOTICES.md', captured)

    def test_source_tree_symlink_rejected_not_silently_ignored(self):
        self.assertTrue(hasattr(self.module, 'tree_files'), 'Missing guarded recursive inventory')
        tree = self.root / 'assets'
        tree.mkdir()
        outside = self.base / 'outside'
        outside.mkdir()
        (outside / 'stolen').write_bytes(b'external fixture')
        (tree / 'escape').symlink_to(outside, target_is_directory=True)
        with self.assertRaises(self.module.BuildError):
            self.module.tree_files(self.root, tree)

    def test_snapshot_tampering_is_rejected_even_if_original_unchanged(self):
        self.assertTrue(hasattr(self.module, 'check_hashes'), 'Missing captured-input revalidation')
        source = self.root / 'source.txt'
        source.write_bytes(b'A')
        frozen = self.root / 'work/source'
        hashes = self.module.capture_files(self.root, frozen, ['source.txt'])
        (frozen / 'source.txt').write_bytes(b'B')
        with self.assertRaisesRegex(self.module.BuildError, 'changed'):
            self.module.check_hashes(frozen, hashes)


class PackagingRegression(FixtureCase):
    def prepare(self):
        import zipfile
        for directory in ('dist', 'android/assets', 'dex'):
            (self.root / directory).mkdir(parents=True)
        (self.root / 'dist/index.html').write_bytes(b'captured generated page')
        (self.root / 'android/assets/native.js').write_bytes(b'native asset')
        (self.root / 'dex/classes.dex').write_bytes(b'synthetic dex, not executable')
        for name in ('LICENSE.upstream', 'THIRD_PARTY_NOTICES.md'):
            (self.root / name).write_bytes(name.encode())
        with zipfile.ZipFile(self.root / 'base.apk', 'w') as archive:
            archive.writestr('AndroidManifest.xml', b'synthetic binary manifest')
        return self.root / 'unsigned.apk'

    def test_packaged_bytes_are_bound_to_every_staged_entry(self):
        self.assertTrue(hasattr(self.module, 'package_unsigned'), 'Missing per-entry packaging validation')
        target = self.prepare()
        entries = self.module.package_unsigned(self.root, self.root, self.root / 'base.apk',
                                               self.root / 'dex', target)
        self.assertIn('assets/LICENSE.upstream', entries)
        self.assertIn('assets/THIRD_PARTY_NOTICES.md', entries)
        self.assertIn('assets/www/index.html', entries)
        self.assertEqual(entries, self.module.verify_zip(self.root, target, entries))

    def test_resource_table_is_stored_and_other_base_compression_is_preserved(self):
        import zipfile
        target = self.prepare()
        with zipfile.ZipFile(self.root / 'base.apk', 'a') as archive:
            archive.writestr('resources.arsc', b'resource table bytes', compress_type=zipfile.ZIP_DEFLATED)
            archive.writestr('res/raw/data.bin', b'already stored', compress_type=zipfile.ZIP_STORED)
        entries = self.module.package_unsigned(self.root, self.root, self.root / 'base.apk',
                                               self.root / 'dex', target)
        with zipfile.ZipFile(target) as archive:
            self.assertEqual(archive.getinfo('resources.arsc').compress_type, zipfile.ZIP_STORED)
            self.assertEqual(archive.getinfo('res/raw/data.bin').compress_type, zipfile.ZIP_STORED)
            self.assertEqual(archive.getinfo('AndroidManifest.xml').compress_type, zipfile.ZIP_STORED)
            self.assertEqual(archive.getinfo('classes.dex').compress_type, zipfile.ZIP_DEFLATED)
        self.assertEqual(entries, self.module.verify_zip(self.root, target, entries))

    def test_native_www_collision_fails_instead_of_duplicating_privileged_page(self):
        self.assertTrue(hasattr(self.module, 'package_unsigned'), 'Missing reserved native asset namespace')
        target = self.prepare()
        (self.root / 'android/assets/www').mkdir()
        (self.root / 'android/assets/www/index.html').write_bytes(b'untrusted second page')
        with self.assertRaisesRegex(self.module.BuildError, 'reserved|collision'):
            self.module.package_unsigned(self.root, self.root, self.root / 'base.apk',
                                         self.root / 'dex', target)
        self.assertFalse(target.exists())

    def test_empty_reserved_native_www_directory_is_rejected(self):
        target = self.prepare()
        (self.root / 'android/assets/www').mkdir()
        with self.assertRaisesRegex(self.module.BuildError, 'reserved'):
            self.module.package_unsigned(self.root, self.root, self.root / 'base.apk',
                                         self.root / 'dex', target)

    def test_base_duplicate_entries_are_rejected(self):
        import zipfile, warnings
        self.assertTrue(hasattr(self.module, 'package_unsigned'), 'Missing duplicate ZIP entry boundary')
        target = self.prepare()
        with warnings.catch_warnings():
            warnings.simplefilter('ignore')
            with zipfile.ZipFile(self.root / 'base.apk', 'a') as archive:
                archive.writestr('AndroidManifest.xml', b'duplicate')
        with self.assertRaisesRegex(self.module.BuildError, 'duplicate|collision'):
            self.module.package_unsigned(self.root, self.root, self.root / 'base.apk',
                                         self.root / 'dex', target)

    def test_final_zip_payload_change_and_extra_privileged_entry_rejected(self):
        import zipfile
        self.assertTrue(hasattr(self.module, 'verify_zip'), 'Missing signed archive binding')
        target = self.prepare()
        entries = self.module.package_unsigned(self.root, self.root, self.root / 'base.apk',
                                               self.root / 'dex', target)
        with zipfile.ZipFile(self.root / 'changed.apk', 'w') as archive:
            for name in entries:
                archive.writestr(name, b'changed bytes')
        with self.assertRaises(self.module.BuildError):
            self.module.verify_zip(self.root, self.root / 'changed.apk', entries)
        with zipfile.ZipFile(target, 'a') as archive:
            archive.writestr('assets/www/untracked.html', b'untracked')
        with self.assertRaises(self.module.BuildError):
            self.module.verify_zip(self.root, target, entries)


class LayoutRegression(FixtureCase):
    def resource_zip(self, *, compressed=False, local_padding=0):
        import io, struct, zipfile
        stream = io.BytesIO()
        with zipfile.ZipFile(stream, 'w') as archive:
            archive.writestr('resources.arsc', b'compiled resource bytes',
                             compress_type=zipfile.ZIP_DEFLATED if compressed else zipfile.ZIP_STORED)
        data = bytearray(stream.getvalue())
        if local_padding:
            # Local extra deliberately differs from central extra. Only local
            # headers establish the on-disk data offset Android actually reads.
            struct.pack_into('<H', data, 28, local_padding)
            data[44:44] = b'X' * local_padding
            eocd = data.rfind(b'PK\x05\x06')
            offset = struct.unpack_from('<I', data, eocd + 16)[0]
            struct.pack_into('<I', data, eocd + 16, offset + local_padding)
        path = self.root / 'layout.apk'
        path.write_bytes(data)
        return path

    def test_layout_rejects_compressed_resource_table(self):
        self.assertTrue(hasattr(self.module, 'verify_layout'), 'Missing Android resource-table layout gate')
        with self.assertRaisesRegex(self.module.BuildError, 'uncompressed|stored'):
            self.module.verify_layout(self.root, self.resource_zip(compressed=True))

    def test_layout_uses_local_not_central_extra_for_alignment(self):
        self.assertTrue(hasattr(self.module, 'verify_layout'), 'Missing actual local-header alignment gate')
        with self.assertRaisesRegex(self.module.BuildError, 'align'):
            self.module.verify_layout(self.root, self.resource_zip(local_padding=1))
        layout = self.module.verify_layout(self.root, self.resource_zip(local_padding=4))
        self.assertEqual(layout['resources.arsc']['data_offset'], 48)
        self.assertEqual(layout['resources.arsc']['compression'], 'stored')


class SignerRegression(FixtureCase):
    def test_sdk37_scheme_label_and_windows_lines_keep_exact_single_signer_pin(self):
        expected = 'a' * 64
        record = 'V3.0 Signer: certificate SHA-256 digest: '
        for ending in ('\n', '\r\n'):
            with self.subTest(ending=repr(ending)):
                output = ending.join(('Verifies', 'Number of signers: 1', record + expected, ''))
                try:
                    actual = self.module.verify_signer(output, expected)
                except self.module.BuildError as error:
                    self.fail('Supported SDK signer record was refused: ' + str(error))
                self.assertEqual(actual, expected)
        for output in (
            'Number of signers: 2\n' + record + expected,
            'Number of signers: 1\n' + record + expected + '\n' + record + expected,
            record + 'b' * 64,
            'Unrecognized Signer: certificate SHA-256 digest: ' + expected,
        ):
            with self.subTest(output=output):
                with self.assertRaises(self.module.BuildError):
                    self.module.verify_signer(output, expected)

    def test_valid_but_wrong_or_multiple_signer_rejected(self):
        self.assertTrue(hasattr(self.module, 'verify_signer'), 'Missing trusted certificate comparison')
        expected = 'a' * 64
        for result in ('Signer #1 certificate SHA-256 digest: ' + 'b' * 64,
                       'Signer #1 certificate SHA-256 digest: ' + expected + '\n' +
                       'Signer #2 certificate SHA-256 digest: ' + expected, 'signature is valid'):
            with self.assertRaises(self.module.BuildError):
                self.module.verify_signer(result, expected)
        self.assertEqual(self.module.verify_signer('Signer #1 certificate SHA-256 digest: ' + expected,
                                                  expected), expected)

    def test_malformed_pin_is_not_repaired_or_normalized(self):
        self.assertTrue(hasattr(self.module, 'read_pin'), 'Missing strict trusted public pin validation')
        path = self.root / 'pin'
        for value in ('AA:' * 31 + 'AA', 'A' * 64, 'a' * 63, 'a' * 64 + 'extra'):
            path.write_text(value)
            with self.assertRaises(self.module.BuildError):
                self.module.read_pin(self.root, path)
        path.write_text('a' * 64 + '\n')
        self.assertEqual(self.module.read_pin(self.root, path), 'a' * 64)


class BundleRegression(FixtureCase):
    def candidate(self, name, payload):
        import json
        stage = self.root / name
        stage.mkdir()
        (stage / self.module.APK_NAME).write_bytes(payload)
        manifest = {'schema': 2, 'apk': self.module.APK_NAME, 'sha256': self.module.sha256(payload),
                    'bytes': len(payload), 'package': self.module.PACKAGE,
                    'signer': {'expected_sha256': 'a' * 64, 'actual_sha256': 'a' * 64}}
        (stage / 'build-manifest.json').write_text(json.dumps(manifest))
        (stage / 'SHA256SUMS').write_bytes((manifest['sha256'] + '  ' + self.module.APK_NAME + '\n').encode())
        return stage

    def test_atomic_pointer_exposes_only_matching_bundle(self):
        self.assertTrue(hasattr(self.module, 'read_accepted'), 'Missing verified accepted-bundle reader')
        stage = self.candidate('first', b'first accepted')
        bundle = self.module.publish_accepted(self.root, stage, lambda: None)
        accepted, manifest = self.module.read_accepted(self.root)
        self.assertEqual(accepted, bundle / self.module.APK_NAME)
        self.assertEqual(manifest['sha256'], self.module.sha256(accepted.read_bytes()))

    def test_failed_pointer_replace_preserves_previous_accepted_bundle(self):
        import os
        self.assertTrue(hasattr(self.module, 'read_accepted'), 'Missing verified accepted-bundle reader')
        self.module.publish_accepted(self.root, self.candidate('first', b'accepted'), lambda: None)
        old_pointer = (self.root / 'artifacts/accepted-apk.json').read_bytes()
        def interrupted(source, target):
            if pathlib.Path(target).name == 'accepted-apk.json':
                raise OSError('synthetic publication interruption')
            os.replace(source, target)
        with self.assertRaisesRegex(OSError, 'interruption'):
            self.module.publish_accepted(self.root, self.candidate('second', b'candidate'),
                                         lambda: None, replace=interrupted)
        self.assertEqual((self.root / 'artifacts/accepted-apk.json').read_bytes(), old_pointer)
        self.assertEqual(self.module.read_accepted(self.root)[0].read_bytes(), b'accepted')

    def test_unexpected_candidate_link_is_rejected_before_publication(self):
        stage = self.candidate('linked', b'valid fixture APK')
        target = self.base / 'outside.txt'
        target.write_bytes(b'outside fixture')
        (stage / 'unexpected.txt').symlink_to(target)
        with self.assertRaisesRegex(self.module.BuildError, 'link|reparse'):
            self.module.publish_accepted(self.root, stage, lambda: None)
        self.assertFalse((self.root / 'artifacts/accepted-apk.json').exists())

    def test_inconsistent_candidate_cannot_be_published(self):
        self.assertTrue(hasattr(self.module, 'read_accepted'), 'Missing bundle integrity validation')
        stage = self.candidate('bad', b'accepted')
        (stage / self.module.APK_NAME).write_bytes(b'rejected changed bytes')
        with self.assertRaisesRegex(self.module.BuildError, 'match|hash|integrity'):
            self.module.publish_accepted(self.root, stage, lambda: None)
        self.assertFalse((self.root / 'artifacts/accepted-apk.json').exists())


class PipelineRegression(FixtureCase):
    def prepare(self):
        self.assertTrue(hasattr(self.module, 'build_project'), 'Missing source-captured executable build pipeline')
        for name in self.module.REQUIRED_FILES:
            path = self.root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b'synthetic source')
        for path in ('src/payload.txt', 'android/src/App.java', 'android/res/values/strings.xml',
                     'android/AndroidManifest.xml', 'android/assets/native.js',
                     'node_modules/typescript/bin/tsc', 'node_modules/vite/bin/vite.js',
                     'vendor/hermes/apps/shared/package.json'):
            file = self.root / path
            file.parent.mkdir(parents=True, exist_ok=True)
            file.write_bytes(b'A')
        (self.root / 'android/signing-certificate.sha256').write_bytes(
            (self.module.sha256(b'fixture public DER certificate') + '\n').encode())
        (self.root / '.cache').mkdir(exist_ok=True)
        (self.root / '.cache/prototype-debug.keystore').write_bytes(b'NOT-A-REAL-KEY')
        tools = self.module.make_tools(self.root / 'sdk', self.root / 'jdk', self.root / 'node.exe')
        for name, file in tools.items():
            if name in ('sdk_root', 'jdk_root'):
                continue
            file.parent.mkdir(parents=True, exist_ok=True)
            file.write_bytes(('fixture tool ' + name).encode())
        for path in (self.root / 'sdk/build-tools/37.0.0/source.properties',
                     self.root / 'sdk/platforms/android-36/source.properties', self.root / 'jdk/release'):
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b'fixture tool release')
        self.commands = []
        self.observed_source = []
        self.on_build = lambda cwd: None
        self.key_certificate = b'fixture public DER certificate'
        self.signer = self.module.sha256(self.key_certificate)
        self.on_sign = lambda cwd: None
        self.on_d8 = lambda cwd: None
        self.on_badging = lambda cwd, apk: None
        return tools

    def run_fixture(self, args, *, cwd, env, private=False, binary=False):
        import zipfile, shutil
        args = list(map(str, args))
        self.commands.append(args)
        if '-exportcert' in args:
            return self.key_certificate
        if len(args) > 1 and args[1].endswith('/typescript/bin/tsc'):
            self.on_build(pathlib.Path(cwd))
            self.observed_source.append((pathlib.Path(cwd) / 'src/payload.txt').read_bytes())
        elif len(args) > 1 and args[1].endswith('/vite/bin/vite.js'):
            dist = pathlib.Path(cwd) / 'dist'
            dist.mkdir()
            (dist / 'index.html').write_bytes(b'fixture generated web output ' + self.observed_source[-1])
        elif 'compile' in args and pathlib.Path(args[0]).name == 'aapt2.exe':
            pathlib.Path(args[args.index('-o') + 1]).write_bytes(b'fixture resources')
        elif 'link' in args:
            with zipfile.ZipFile(args[args.index('-o') + 1], 'w') as archive:
                archive.writestr('AndroidManifest.xml', b'fixture manifest')
                archive.writestr('resources.arsc', b'fixture compiled resource table')
        elif pathlib.Path(args[0]).name == 'javac.exe' and '-d' in args:
            (pathlib.Path(args[args.index('-d') + 1]) / 'App.class').write_bytes(b'fixture class')
        elif 'com.android.tools.r8.D8' in args and '--output' in args:
            self.on_d8(pathlib.Path(cwd))
            (pathlib.Path(args[args.index('--output') + 1]) / 'classes.dex').write_bytes(b'fixture dex')
        elif pathlib.Path(args[0]).name == 'zipalign.exe' and '-f' in args:
            self.align_fixture(args[-2], args[-1])
        elif 'sign' in args:
            self.on_sign(pathlib.Path(cwd))
            shutil.copyfile(args[-1], args[args.index('--out') + 1])
        elif 'verify' in args:
            return 'Signer #1 certificate SHA-256 digest: ' + self.signer + '\n'
        elif 'badging' in args:
            self.on_badging(pathlib.Path(cwd), pathlib.Path(args[-1]))
            return "package: name='us.pilipia.hermes.prototype' versionCode='1'\n"
        return b'' if binary else 'fixture measured tool version\n'

    def align_fixture(self, source, target):
        # Pure ZIP fixture, not an SDK executable or real APK validation.
        import copy, struct, zipfile
        with zipfile.ZipFile(source) as old, zipfile.ZipFile(target, 'w') as new:
            for info in old.infolist():
                item = copy.copy(info)
                if item.compress_type == zipfile.ZIP_STORED:
                    offset = new.fp.tell() + 30 + len(item.filename.encode('utf-8')) + len(item.extra)
                    padding = (-(offset + 4)) % 4
                    item.extra += struct.pack('<HH', 0xcafe, padding) + b'\0' * padding
                new.writestr(item, old.read(info))

    def test_pipeline_rejects_compressed_table_even_when_fixture_sdk_claims_success(self):
        import zipfile
        tools = self.prepare()
        def bad_layout(cwd):
            aligned = pathlib.Path(cwd).parent / 'output/aligned.apk'
            with zipfile.ZipFile(aligned) as archive:
                entries = {name: archive.read(name) for name in archive.namelist()}
            with zipfile.ZipFile(aligned, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
                for name, data in entries.items():
                    archive.writestr(name, data)
        self.on_sign = bad_layout
        with self.assertRaisesRegex(self.module.BuildError, 'uncompressed|stored'):
            self.module.build_project(self.root, tools, runner=self.run_fixture)
        self.assertFalse((self.root / 'artifacts/accepted-apk.json').exists())

    def test_pipeline_builds_snapshot_and_does_not_touch_root_dist(self):
        tools = self.prepare()
        (self.root / 'dist').mkdir()
        (self.root / 'dist/index.html').write_bytes(b'frontend fixture must stay untouched')
        def aba(cwd):
            original = self.root / 'src/payload.txt'
            original.write_bytes(b'transient B')
            self.assertEqual((cwd / 'src/payload.txt').read_bytes(), b'A')
            original.write_bytes(b'A')
        self.on_build = aba
        apk, manifest = self.module.build_project(self.root, tools, runner=self.run_fixture)
        self.assertEqual(self.observed_source, [b'A'])
        self.assertEqual((self.root / 'dist/index.html').read_bytes(), b'frontend fixture must stay untouched')
        self.assertEqual(manifest['signer']['actual_sha256'], self.signer)
        self.assertIn('node_modules/vite/bin/vite.js', manifest['dependencies']['files'])
        self.assertIn('assets/www/index.html', manifest['packaged_entries'])
        self.assertEqual(manifest['tools']['files']['node']['sha256'], self.module.sha256(tools['node'].read_bytes()))
        self.assertEqual(manifest['tools']['versions']['java'], 'fixture measured tool version')
        self.assertFalse(manifest['source_capture']['temporal_immutability_claimed'])
        self.assertEqual(self.module.read_accepted(self.root)[0], apk)
        signing = next(command for command in self.commands if 'sign' in command)
        self.assertIn('/.cache/apk-build-', signing[signing.index('--out') + 1].replace('\\', '/'))
        self.assertFalse((self.root / 'artifacts' / self.module.APK_NAME).exists())

    def test_changed_source_failure_leaves_old_success_set_untouched(self):
        tools = self.prepare()
        out = self.root / 'artifacts'
        out.mkdir()
        for name in (self.module.APK_NAME, 'build-manifest.json', 'SHA256SUMS'):
            (out / name).write_bytes(b'previous success')
        self.on_sign = lambda cwd: (self.root / 'src/payload.txt').write_bytes(b'changed')
        with self.assertRaisesRegex(self.module.BuildError, 'source inputs changed'):
            self.module.build_project(self.root, tools, runner=self.run_fixture)
        for name in (self.module.APK_NAME, 'build-manifest.json', 'SHA256SUMS'):
            self.assertEqual((out / name).read_bytes(), b'previous success')
        self.assertFalse((out / 'accepted-apk.json').exists())

    def test_rejected_rebuild_keeps_previous_accepted_pointer_and_bytes(self):
        tools = self.prepare()
        old_apk, _ = self.module.build_project(self.root, tools, runner=self.run_fixture)
        old_bytes = old_apk.read_bytes()
        old_pointer = (self.root / 'artifacts/accepted-apk.json').read_bytes()
        self.on_sign = lambda cwd: (self.root / 'src/payload.txt').write_bytes(b'new live source')
        with self.assertRaisesRegex(self.module.BuildError, 'source inputs changed'):
            self.module.build_project(self.root, tools, runner=self.run_fixture)
        self.assertEqual((self.root / 'artifacts/accepted-apk.json').read_bytes(), old_pointer)
        self.assertEqual(self.module.read_accepted(self.root)[0].read_bytes(), old_bytes)

    def test_wrong_candidate_signer_never_publishes(self):
        tools = self.prepare()
        self.signer = 'b' * 64
        with self.assertRaisesRegex(self.module.BuildError, 'signer'):
            self.module.build_project(self.root, tools, runner=self.run_fixture)
        self.assertFalse((self.root / 'artifacts/accepted-apk.json').exists())

    def test_missing_original_identity_fails_before_any_tool_runs(self):
        tools = self.prepare()
        (self.root / '.cache/prototype-debug.keystore').unlink()
        with self.assertRaisesRegex(self.module.BuildError, 'Missing preserved signing identity'):
            self.module.build_project(self.root, tools, runner=self.run_fixture)
        self.assertEqual(self.commands, [])
        self.assertFalse((self.root / '.cache/prototype-debug.keystore').exists())

    def test_captured_pin_must_equal_initial_trusted_pin(self):
        from unittest.mock import patch
        import apk_pipeline
        tools = self.prepare()
        original_capture = apk_pipeline.capture_files
        def changed_pin(root, destination, names):
            (root / 'android/signing-certificate.sha256').write_bytes(('b' * 64 + '\n').encode())
            return original_capture(root, destination, names)
        with patch.object(apk_pipeline, 'capture_files', changed_pin):
            with self.assertRaisesRegex(self.module.BuildError, 'pin|signer'):
                self.module.build_project(self.root, tools, runner=self.run_fixture)
        self.assertFalse((self.root / 'artifacts/accepted-apk.json').exists())

    def test_transient_staged_dist_and_native_replacement_cannot_mislabel_packaged_bytes(self):
        for name in ('dist/index.html', 'android/assets/native.js',
                     'LICENSE.upstream', 'THIRD_PARTY_NOTICES.md'):
            with self.subTest(path=name):
                tools = self.prepare()
                previous = {}
                def mutate(cwd):
                    previous[name] = (cwd / name).read_bytes()
                    (cwd / name).write_bytes(b'transient B packaged without a binding')
                def restore(cwd):
                    (cwd / name).write_bytes(previous[name])
                self.on_d8, self.on_sign = mutate, restore
                with self.assertRaisesRegex(self.module.BuildError, 'binding|captured|output'):
                    self.module.build_project(self.root, tools, runner=self.run_fixture)
                self.assertFalse((self.root / 'artifacts/accepted-apk.json').exists())

    def test_candidate_envelope_cannot_change_after_signature_verification(self):
        import zipfile
        tools = self.prepare()
        def change_envelope(cwd, apk):
            with zipfile.ZipFile(apk, 'a') as archive:
                archive.comment = b'changed whole-file bytes after signing'
        self.on_badging = change_envelope
        with self.assertRaisesRegex(self.module.BuildError, 'candidate|Candidate|signature'):
            self.module.build_project(self.root, tools, runner=self.run_fixture)
        self.assertFalse((self.root / 'artifacts/accepted-apk.json').exists())

    def test_wrong_preserved_identity_fails_before_signing(self):
        tools = self.prepare()
        self.key_certificate = b'different fixture certificate, not a real key'
        with self.assertRaisesRegex(self.module.BuildError, 'keystore certificate'):
            self.module.build_project(self.root, tools, runner=self.run_fixture)
        self.assertFalse(any('sign' in args for args in self.commands))
        self.assertFalse((self.root / 'artifacts/accepted-apk.json').exists())

    def test_missing_public_pin_fails_before_tools(self):
        tools = self.prepare()
        (self.root / 'android/signing-certificate.sha256').unlink()
        with self.assertRaises(self.module.BuildError):
            self.module.build_project(self.root, tools, runner=self.run_fixture)
        self.assertEqual(self.commands, [])

    def test_tool_hashes_are_measured_and_tool_endpoint_changes_rejected(self):
        tools = self.prepare()
        self.on_sign = lambda cwd: tools['aapt2'].write_bytes(b'changed SDK tool')
        with self.assertRaisesRegex(self.module.BuildError, 'tool'):
            self.module.build_project(self.root, tools, runner=self.run_fixture)
        self.assertFalse((self.root / 'artifacts/accepted-apk.json').exists())


class RepackRegression(FixtureCase):
    prepare = PipelineRegression.prepare
    run_fixture = PipelineRegression.run_fixture
    align_fixture = PipelineRegression.align_fixture

    def accepted_fixture(self):
        tools = self.prepare()
        apk, manifest = self.module.build_project(self.root, tools, runner=self.run_fixture)
        pointer = (self.root / 'artifacts/accepted-apk.json').read_bytes()
        self.commands.clear()
        return tools, apk, manifest, pointer

    def test_repack_preserves_compiled_payload_and_records_honest_inherited_receipt(self):
        import json, zipfile
        self.assertTrue(hasattr(self.module, 'repack_accepted'), 'Missing narrow cached-repack production pipeline')
        tools, previous, original, pointer = self.accepted_fixture()
        previous_bytes = previous.read_bytes()
        previous_manifest = (previous.parent / 'build-manifest.json').read_bytes()
        (self.root / 'scripts/apk_build.py').write_bytes(b'new packaging helper, not new app source')
        def change_container(cwd):
            with zipfile.ZipFile(pathlib.Path(cwd).parent / 'output/aligned.apk', 'a') as archive:
                archive.comment = b'new container only'
        self.on_sign = change_container
        apk, manifest = self.module.repack_accepted(self.root, tools, runner=self.run_fixture)
        self.assertNotEqual(apk, previous)
        self.assertNotEqual(apk.read_bytes(), previous_bytes)
        self.assertEqual(previous.read_bytes(), previous_bytes)
        self.assertEqual((previous.parent / 'build-manifest.json').read_bytes(), previous_manifest)
        self.assertEqual(manifest['packaged_entries'], original['packaged_entries'])
        inherited = manifest['inherited_compilation']
        self.assertEqual(inherited['manifest_sha256'], self.module.sha256(previous_manifest))
        for key in ('inputs', 'dependencies', 'dist_outputs', 'generated_native_outputs', 'source_capture', 'tools', 'commands'):
            self.assertEqual(inherited['receipt'][key], original[key])
        self.assertFalse(manifest['source_capture']['original_endpoint_match'])
        self.assertTrue(manifest['packaging']['application_input_endpoint_match'])
        self.assertEqual(manifest['packaging']['changed_helper_paths'], ['scripts/apk_build.py'])
        self.assertEqual(manifest['build_kind'], 'accepted-payload-container-repack')
        self.assertFalse(any('com.android.tools.r8.D8' in c or 'compile' in c or 'javac.exe' in c[0]
                             or any('vite.js' in a or a.endswith('/tsc') for a in c) for c in self.commands))
        self.assertTrue(any('-c' in c and c[0].endswith('zipalign.exe') for c in self.commands))
        self.assertEqual(self.module.read_accepted(self.root)[0], apk)


    def test_cli_exposes_explicit_mutually_exclusive_cached_repack(self):
        import subprocess
        result = subprocess.run([sys.executable, '-B', str(SCRIPTS / 'build-apk.py'), '--help'],
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('--repack-accepted', result.stdout)
        invalid = subprocess.run([sys.executable, '-B', str(SCRIPTS / 'build-apk.py'),
                                  '--show-accepted', '--repack-accepted'],
                                 stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        self.assertEqual(invalid.returncode, 2)

    def test_repack_requires_full_compilation_root_not_recursive_repack(self):
        tools, previous, original, pointer = self.accepted_fixture()
        self.module.repack_accepted(self.root, tools, runner=self.run_fixture)
        pointer = (self.root / 'artifacts/accepted-apk.json').read_bytes()
        self.commands.clear()
        with self.assertRaisesRegex(self.module.BuildError, 'full compilation|full build'):
            self.module.repack_accepted(self.root, tools, runner=self.run_fixture)
        self.assertEqual((self.root / 'artifacts/accepted-apk.json').read_bytes(), pointer)
        self.assertEqual(self.commands, [])

    def test_unknown_prior_payload_namespace_is_not_silently_carried_forward(self):
        import json, zipfile
        tools, previous, original, pointer = self.accepted_fixture()
        with zipfile.ZipFile(previous, 'a') as archive:
            archive.writestr('unknown/extra.bin', b'unreviewed namespace')
        original['packaged_entries']['unknown/extra.bin'] = self.module.sha256(b'unreviewed namespace')
        original['sha256'] = self.module.sha256(previous.read_bytes())
        original['bytes'] = previous.stat().st_size
        manifest_path = previous.parent / 'build-manifest.json'
        manifest_path.write_text(json.dumps(original))
        (previous.parent / 'SHA256SUMS').write_bytes((original['sha256'] + '  ' + self.module.APK_NAME + '\n').encode())
        updated = json.loads(pointer)
        updated['apk_sha256'] = original['sha256']
        updated['manifest_sha256'] = self.module.sha256(manifest_path.read_bytes())
        pointer = json.dumps(updated).encode()
        (self.root / 'artifacts/accepted-apk.json').write_bytes(pointer)
        with self.assertRaisesRegex(self.module.BuildError, 'namespace'):
            self.module.repack_accepted(self.root, tools, runner=self.run_fixture)
        self.assertEqual((self.root / 'artifacts/accepted-apk.json').read_bytes(), pointer)

    def test_changed_application_inputs_or_inventory_require_full_build(self):
        tools, previous, original, pointer = self.accepted_fixture()
        for name in ('src/payload.txt', 'android/src/App.java', 'android/assets/native.js',
                     'package-lock.json', 'vendor/hermes/apps/shared/package.json'):
            path = self.root / name
            before = path.read_bytes()
            path.write_bytes(b'changed application input')
            with self.subTest(path=name):
                with self.assertRaisesRegex(self.module.BuildError, 'source inputs changed|full build'):
                    self.module.repack_accepted(self.root, tools, runner=self.run_fixture)
                self.assertEqual((self.root / 'artifacts/accepted-apk.json').read_bytes(), pointer)
                self.assertEqual(self.commands, [])
            path.write_bytes(before)
        new = self.root / 'tests/new-test.ts'
        new.parent.mkdir(exist_ok=True)
        new.write_bytes(b'new captured input')
        with self.assertRaisesRegex(self.module.BuildError, 'inventory'):
            self.module.repack_accepted(self.root, tools, runner=self.run_fixture)
        self.assertEqual((self.root / 'artifacts/accepted-apk.json').read_bytes(), pointer)
        self.assertEqual(previous.read_bytes(), self.module.read_accepted(self.root)[0].read_bytes())

    def test_changed_pin_or_wrong_signer_keep_previous_pointer(self):
        tools, previous, original, pointer = self.accepted_fixture()
        pin = self.root / 'android/signing-certificate.sha256'
        initial = pin.read_bytes()
        pin.write_bytes(('b' * 64 + '\n').encode())
        with self.assertRaisesRegex(self.module.BuildError, 'pin|signer'):
            self.module.repack_accepted(self.root, tools, runner=self.run_fixture)
        pin.write_bytes(initial)
        self.signer = 'b' * 64
        with self.assertRaisesRegex(self.module.BuildError, 'signer'):
            self.module.repack_accepted(self.root, tools, runner=self.run_fixture)
        self.assertEqual((self.root / 'artifacts/accepted-apk.json').read_bytes(), pointer)
        self.assertFalse(any('sign' in c for c in self.commands))

    def test_missing_or_tampered_prior_apk_or_manifest_fail_closed(self):
        tools, previous, original, pointer = self.accepted_fixture()
        for path in (previous, previous.parent / 'build-manifest.json'):
            before = path.read_bytes()
            for content in (None, b'tampered'):
                with self.subTest(path=path.name, content=content):
                    if content is None:
                        path.unlink()
                    else:
                        path.write_bytes(content)
                    with self.assertRaises((self.module.BuildError, ValueError)):
                        self.module.repack_accepted(self.root, tools, runner=self.run_fixture)
                    self.assertEqual((self.root / 'artifacts/accepted-apk.json').read_bytes(), pointer)
                    self.assertEqual(self.commands, [])
                    path.write_bytes(before)

    def test_source_or_candidate_race_is_rejected_before_publication(self):
        import zipfile
        tools, previous, original, pointer = self.accepted_fixture()
        old_bytes = previous.read_bytes()
        path = self.root / 'src/payload.txt'
        self.on_sign = lambda cwd: path.write_bytes(b'changed while signing')
        with self.assertRaisesRegex(self.module.BuildError, 'source inputs changed'):
            self.module.repack_accepted(self.root, tools, runner=self.run_fixture)
        self.assertEqual((self.root / 'artifacts/accepted-apk.json').read_bytes(), pointer)
        path.write_bytes(b'A')
        self.on_sign = lambda cwd: None
        def change_envelope(cwd, apk):
            with zipfile.ZipFile(apk, 'a') as archive:
                archive.comment = b'changed after verification'
        self.on_badging = change_envelope
        with self.assertRaisesRegex(self.module.BuildError, 'Candidate changed'):
            self.module.repack_accepted(self.root, tools, runner=self.run_fixture)
        self.assertEqual((self.root / 'artifacts/accepted-apk.json').read_bytes(), pointer)
        self.assertEqual(previous.read_bytes(), old_bytes)


    def test_repack_rejects_broken_final_resource_layout_and_preserves_acceptance(self):
        import io, struct, zipfile
        tools, previous, original, pointer = self.accepted_fixture()
        old_bytes = previous.read_bytes()
        def corrupt(cwd):
            path = pathlib.Path(cwd).parent / 'output/aligned.apk'
            with zipfile.ZipFile(path) as archive:
                entries = {info.filename: (info.compress_type, archive.read(info)) for info in archive.infolist()}
            # Resource table first so its local data offset is known exactly.
            stream = io.BytesIO()
            with zipfile.ZipFile(stream, 'w') as archive:
                archive.writestr('resources.arsc', entries.pop('resources.arsc')[1],
                                 compress_type=zipfile.ZIP_DEFLATED if self.compressed else zipfile.ZIP_STORED)
                for name, (method, data) in entries.items():
                    archive.writestr(name, data, compress_type=method)
            data = bytearray(stream.getvalue())
            if not self.compressed:
                struct.pack_into('<H', data, 28, 1)
                data[44:44] = b'X'
                central = data.find(b'PK\x01\x02')
                while data[central:central + 4] == b'PK\x01\x02':
                    local = struct.unpack_from('<I', data, central + 42)[0]
                    if local:
                        struct.pack_into('<I', data, central + 42, local + 1)
                    n, e, c = struct.unpack_from('<HHH', data, central + 28)
                    central += 46 + n + e + c
                eocd = data.rfind(b'PK\x05\x06')
                offset = struct.unpack_from('<I', data, eocd + 16)[0]
                struct.pack_into('<I', data, eocd + 16, offset + 1)
            path.write_bytes(data)
        self.on_sign = corrupt
        for compressed in (True, False):
            self.compressed = compressed
            with self.subTest(compressed=compressed):
                with self.assertRaisesRegex(self.module.BuildError, 'uncompressed|stored|align'):
                    self.module.repack_accepted(self.root, tools, runner=self.run_fixture)
                self.assertEqual((self.root / 'artifacts/accepted-apk.json').read_bytes(), pointer)
                self.assertEqual(previous.read_bytes(), old_bytes)

    def test_repack_unsigned_removes_only_known_signature_metadata_and_binds_all_bytes(self):
        import zipfile
        path, target = self.root / 'prior.apk', self.root / 'new.apk'
        values = {'AndroidManifest.xml': b'manifest', 'resources.arsc': b'table', 'classes.dex': b'dex',
                  'assets/www/index.html': b'page', 'META-INF/MANIFEST.MF': b'old manifest',
                  'META-INF/ANDROIDD.SF': b'old signature', 'META-INF/ANDROIDD.RSA': b'old block'}
        with zipfile.ZipFile(path, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
            for name, data in values.items():
                archive.writestr(name, data)
        expected = {name: self.module.sha256(data) for name, data in values.items()}
        bound = self.module.repack_unsigned(self.root, path, target, expected)
        self.assertEqual(set(bound), {n for n in values if not n.startswith('META-INF/')})
        for name, data in self.module.zip_payload(self.root, target).items():
            self.assertEqual(data, values[name])
        expected['classes.dex'] = 'b' * 64
        with self.assertRaisesRegex(self.module.BuildError, 'entries differ'):
            self.module.repack_unsigned(self.root, path, self.root / 'bad.apk', expected)
        self.assertFalse((self.root / 'bad.apk').exists())
        outside = self.base / 'outside.apk'
        outside.write_bytes(b'preserve')
        (self.root / 'linked.apk').symlink_to(outside)
        expected['classes.dex'] = self.module.sha256(values['classes.dex'])
        with self.assertRaisesRegex(self.module.BuildError, 'link|reparse'):
            self.module.repack_unsigned(self.root, path, self.root / 'linked.apk', expected)
        self.assertEqual(outside.read_bytes(), b'preserve')

    def test_concurrent_pointer_change_is_not_overwritten(self):
        tools, previous, original, pointer = self.accepted_fixture()
        new_pointer = pointer + b'\n'
        def change_pointer(cwd, apk):
            (self.root / 'artifacts/accepted-apk.json').write_bytes(new_pointer)
        self.on_badging = change_pointer
        with self.assertRaisesRegex(self.module.BuildError, 'pointer changed'):
            self.module.repack_accepted(self.root, tools, runner=self.run_fixture)
        self.assertEqual((self.root / 'artifacts/accepted-apk.json').read_bytes(), new_pointer)
        self.assertEqual(self.module.read_accepted(self.root)[0], previous)


class DependencyRegression(FixtureCase):
    def test_known_lockfile_dependency_is_materialized_from_captured_source(self):
        import json
        from apk_pipeline import dependency_snapshot
        target = self.root / 'vendor/hermes/apps/shared'
        target.mkdir(parents=True)
        (target / 'index.ts').write_bytes(b'captured original')
        deps = self.root / 'node_modules/@hermes'
        deps.mkdir(parents=True)
        (deps / 'shared').symlink_to(target, target_is_directory=True)
        (self.root / 'package-lock.json').write_text(json.dumps({'packages': {
            'node_modules/@hermes/shared': {'link': True, 'resolved': 'vendor/hermes/apps/shared'}}}))
        captured = self.root / 'stage/source'
        self.module.capture_files(self.root, captured, ['vendor/hermes/apps/shared/index.ts'])
        (target / 'index.ts').write_bytes(b'new live source, not captured')
        result = dependency_snapshot(self.root, captured)
        copied = captured / 'node_modules/@hermes/shared/index.ts'
        self.assertFalse(copied.parent.is_symlink())
        self.assertEqual(copied.read_bytes(), b'captured original')
        self.assertIn('node_modules/@hermes/shared/index.ts', result['files'])

    def test_unknown_dependency_link_cannot_read_outside(self):
        from apk_pipeline import dependency_snapshot
        deps = self.root / 'node_modules'
        deps.mkdir()
        outside = self.base / 'outside'
        outside.mkdir()
        (outside / 'leaked').write_bytes(b'synthetic external fixture')
        (deps / 'unexpected').symlink_to(outside, target_is_directory=True)
        with self.assertRaisesRegex(self.module.BuildError, 'link|reparse'):
            dependency_snapshot(self.root, self.root / 'stage/source')

    def test_windows_junction_is_not_misclassified_as_safe_directory(self):
        import os, subprocess
        outside = self.base / 'outside'
        outside.mkdir()
        (outside / 'payload').write_bytes(b'external fixture')
        alias = self.root / 'junction'
        if os.name == 'nt':
            result = subprocess.run(['cmd.exe', '/d', '/c', 'mklink', '/J', str(alias), str(outside)],
                                    stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            self.assertEqual(result.returncode, 0, result.stderr.decode(errors='replace'))
            self.assertFalse(alias.is_symlink())
            self.assertTrue(alias.lstat().st_file_attributes & 0x400)
        else:
            alias.symlink_to(outside, target_is_directory=True)
        with self.assertRaisesRegex(self.module.BuildError, 'link|reparse'):
            self.module.read_guarded(self.root, alias / 'payload')


if __name__ == '__main__':
    unittest.main(verbosity=2)
