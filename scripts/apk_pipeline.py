"""Source-captured APK pipeline. External tool/dependency inputs are read-only.

The runner is injectable only to exercise orchestration with explicitly synthetic
fixtures. The normal CLI always uses CommandRunner and actual SDK/JDK programs.
"""
from pathlib import Path
import ctypes
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import re

from apk_build import (APK_NAME, PACKAGE, BuildError, capture_files, check_fingerprints, check_hashes,
                       fingerprint_files, guard, hash_files, mkdir_guarded, package_unsigned,
                       publish_accepted, read_accepted, read_guarded, read_pin, repack_unsigned,
                       sha256, source_paths, tree_files, verify_signer, verify_zip, verify_layout,
                       write_new)

DEFAULT_SDK = 'C:/Android/Sdk'
DEFAULT_JDK = 'C:/Program Files/Microsoft/jdk-21.0.8.9-hotspot'
DEP_CACHE_EXCLUDES = ('.vite', '.vite-temp', '.cache')
SHARED_LINK = '@hermes/shared'
SHARED_SOURCE = 'vendor/hermes/apps/shared'


def make_tools(sdk, jdk, node):
    sdk, jdk = Path(sdk).absolute(), Path(jdk).absolute()
    bt = sdk / 'build-tools/37.0.0'
    return {'sdk_root': sdk, 'jdk_root': jdk, 'node': Path(node).absolute(),
            'java': jdk / 'bin/java.exe', 'javac': jdk / 'bin/javac.exe',
            'keytool': jdk / 'bin/keytool.exe', 'aapt': bt / 'aapt.exe',
            'aapt2': bt / 'aapt2.exe', 'zipalign': bt / 'zipalign.exe',
            'd8': bt / 'lib/d8.jar', 'apksigner': bt / 'lib/apksigner.jar',
            'platform': sdk / 'platforms/android-36/android.jar'}


def python_executable():
    # Store aliases can execute Python but cannot be opened to measure their bytes.
    if os.name == 'nt':
        buffer = ctypes.create_unicode_buffer(32768)
        if not ctypes.windll.kernel32.GetModuleFileNameW(None, buffer, len(buffer)):
            raise BuildError('Cannot identify running Python executable')
        return Path(buffer.value)
    return Path(sys.executable).resolve()


def clean_environment(stage, tools):
    stage = Path(stage)
    env = {name: value for name, value in os.environ.items()
           if name.upper() in ('SYSTEMROOT', 'WINDIR', 'COMSPEC', 'PATHEXT',
                               'PROCESSOR_ARCHITECTURE', 'NUMBER_OF_PROCESSORS')}
    system32 = Path(env.get('SystemRoot', env.get('SYSTEMROOT', 'C:/Windows'))) / 'System32'
    env.update({'PATH': os.pathsep.join(map(str, (tools['node'].parent, tools['java'].parent, system32))),
                'JAVA_HOME': str(tools['jdk_root']), 'ANDROID_SDK_ROOT': str(tools['sdk_root']),
                'ANDROID_HOME': str(tools['sdk_root']), 'TMPDIR': str(stage / 'tmp'),
                'TMP': str(stage / 'tmp'), 'TEMP': str(stage / 'tmp'),
                'HOME': str(stage / 'home'), 'USERPROFILE': str(stage / 'home'),
                'APPDATA': str(stage / 'home'), 'LOCALAPPDATA': str(stage / 'home'),
                'XDG_CACHE_HOME': str(stage / 'cache'), 'NODE_ENV': 'production',
                'VITE_DEBUG_LOCAL': 'true', 'NO_COLOR': '1'})
    return env


_PHASE_MARK = [time.monotonic()]


def phase(name):
    """Print how long the step that just ended took (so build time is measured, not guessed)."""
    now = time.monotonic()
    print('[phase] %s: %.0f s' % (name, now - _PHASE_MARK[0]), flush=True)
    _PHASE_MARK[0] = now


class CommandRunner:
    def __init__(self, root, log):
        # Windows consoles default to cp1252; Vite prints a check mark and crashed the build (10/17).
        for stream in (sys.stdout, sys.stderr):
            if hasattr(stream, 'reconfigure'):
                stream.reconfigure(encoding='utf-8', errors='replace')
        self.root, self.log = Path(root), Path(log)
        write_new(root, log, b'')

    def __call__(self, args, *, cwd, env, private=False, binary=False):
        guard(self.root, cwd, kind='dir')
        guard(self.root, self.log, kind='file')
        command = subprocess.list2cmdline(args)
        print('+ ' + command, flush=True)
        result = subprocess.run(args, cwd=cwd, env=env, stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE)
        output = '<private certificate output suppressed>\n' if private else (
            result.stdout + result.stderr).decode('utf-8', errors='replace')
        with self.log.open('ab') as log:
            log.write(('+ ' + command + '\n' + output + '\n').encode('utf-8'))
            log.flush()
        if not private:
            print(output, flush=True)
        if result.returncode:
            raise BuildError('Build command failed (exit ' + str(result.returncode) + '): ' + command)
        return result.stdout if binary else (result.stdout + result.stderr).decode('utf-8', errors='replace')


def dependency_snapshot(root, source):
    """Physically copy dependencies; materialize only the lockfile's known local link.

    Arbitrary junctions/symlinks are rejected. No live root node_modules symlink is
    mounted in the captured build, including Vite's explicit asset-read paths.
    """
    root, source = Path(root), Path(source)
    deps = guard(root, root / 'node_modules', kind='dir')
    link = deps / SHARED_LINK
    materialized = {}
    if link.exists() or link.is_symlink():
        info = link.lstat()
        if info.st_mode & 0o170000 == 0o120000 or getattr(info, 'st_file_attributes', 0) & 0x400:
            target = guard(root, root / SHARED_SOURCE, kind='dir')
            if link.resolve() != target.resolve():
                raise BuildError('Unexpected local dependency link target')
            lock = json.loads(read_guarded(root, root / 'package-lock.json'))
            entry = lock.get('packages', {}).get('node_modules/' + SHARED_LINK, {})
            if entry.get('link') is not True or entry.get('resolved') != SHARED_SOURCE:
                raise BuildError('Local dependency link is not pinned by lockfile')
            materialized[SHARED_LINK] = SHARED_SOURCE
    excludes = DEP_CACHE_EXCLUDES + ((SHARED_LINK,) if materialized else ())
    paths = [file.relative_to(root).as_posix() for file in tree_files(root, deps, exclude=excludes)]
    # Rebuildable copy: no per-file fsync and no second read of the originals. The build's
    # endpoint check uses size/mtime fingerprints (full re-hash with APK_BUILD_FULL_VERIFY=1).
    files = capture_files(root, source, paths, durable=False, verify=False)
    if materialized:
        origin = source / SHARED_SOURCE
        for file in tree_files(root, origin):
            relative = file.relative_to(origin)
            destination = source / 'node_modules' / SHARED_LINK / relative
            data = read_guarded(root, file)
            write_new(root, destination, data)
            files[destination.relative_to(source).as_posix()] = sha256(data)
    return {'files': dict(sorted(files.items())), 'materialized_links': materialized,
            'excluded_generated_caches': list(DEP_CACHE_EXCLUDES)}


def tool_file_hashes(tools):
    """Hash implementation bytes, not only executable shims or literal version labels."""
    files = {}
    for prefix, directory in (('jdk', tools['jdk_root']),
                              ('build_tools', tools['aapt2'].parent)):
        for file in tree_files(directory, directory):
            files[prefix + '/' + file.relative_to(directory).as_posix()] = {
                'path': file.as_posix(), 'sha256': sha256(read_guarded(directory, file))}
    for label, file, scope in (('platform/android.jar', tools['platform'], tools['sdk_root']),
                               ('platform/source.properties', tools['platform'].parent / 'source.properties', tools['sdk_root']),
                               ('node', tools['node'], tools['node'].parent),
                               ('python', python_executable(), python_executable().parent)):
        files[label] = {'path': file.as_posix(), 'sha256': sha256(read_guarded(scope, file))}
    for name, file in tools.items():
        if name.endswith('_root'):
            continue
        scope = tools['jdk_root'] if name in ('java', 'javac', 'keytool') else (
            tools['node'].parent if name == 'node' else tools['sdk_root'])
        guard(scope, file, kind='file')
    return files


PACKAGING_HELPERS = ('scripts/apk_build.py', 'scripts/apk_pipeline.py', 'scripts/build-apk.py')


def repack_accepted(root, tools, *, runner=None):
    """Re-containerize only an accepted full compilation with identical app inputs.

    No compiler or dependency copy runs here. Compilation evidence is inherited
    verbatim through the hash-validated old bundle, not relabeled as a new build.
    """
    root = Path(root).absolute()
    guard(root, root, kind='dir')
    key = guard(root, root / '.cache/prototype-debug.keystore', kind='file')
    expected_pin = read_pin(root, root / 'android/signing-certificate.sha256')
    cache = mkdir_guarded(root, root / '.cache')
    lock = cache / 'apk-builder.lock'
    write_new(root, lock, (str(os.getpid()) + '\n').encode())
    try:
        old_pointer = read_guarded(root, root / 'artifacts/accepted-apk.json')
        old_apk, old = read_accepted(root)
        old_manifest_bytes = read_guarded(root, old_apk.parent / 'build-manifest.json')
        old_manifest_hash = sha256(old_manifest_bytes)
        if (old.get('build_kind') is not None or 'inherited_compilation' in old
                or old.get('source_capture', {}).get('mode') != 'physical source and dependency copies used as compiler cwd'
                or old.get('source_capture', {}).get('original_endpoint_match') is not True
                or old.get('source_capture', {}).get('captured_endpoint_match') is not True
                or not all(name in old for name in ('inputs', 'dependencies', 'dist_outputs',
                                                    'generated_native_outputs', 'tools', 'commands', 'environment'))):
            raise BuildError('Cached repack requires an accepted full compilation root; full build required')
        snapshot = old['source_capture'].get('path', '')
        if not re.fullmatch(r'\.cache/apk-build-[a-zA-Z0-9_-]+/source', snapshot):
            raise BuildError('Noncanonical inherited compilation snapshot path; full build required')
        guard(root, root / snapshot, kind='dir')
        if old['signer']['expected_sha256'] != expected_pin:
            raise BuildError('Accepted signer differs from current trusted pin; full build required')
        names = source_paths(root)
        current_inputs = hash_files(root, names)
        if names != sorted(old['inputs']):
            raise BuildError('Application input inventory changed; full build required')
        changed = sorted(name for name in names if current_inputs[name] != old['inputs'][name])
        if any(name not in PACKAGING_HELPERS for name in changed):
            raise BuildError('Application source inputs changed; full build required: ' + ', '.join(changed[:12]))
        stage = Path(tempfile.mkdtemp(prefix='apk-repack-', dir=cache))
        guard(root, stage, kind='dir')
        for name in ('tmp', 'home', 'cache', 'work', 'output', 'candidate'):
            mkdir_guarded(root, stage / name)
        work, output, candidate = stage / 'work', stage / 'output', stage / 'candidate'
        original = write_new(root, output / 'accepted-input.apk', read_guarded(root, old_apk))
        if sha256(read_guarded(root, original)) != old['sha256']:
            raise BuildError('Prior accepted APK changed before private copy')
        env = clean_environment(stage, tools)
        run = runner if runner is not None else CommandRunner(root, stage / 'build.log')
        commands = []
        def invoke(args, *, private=False, binary=False, outputs=()):
            for target in outputs:
                target = guard(root, target)
                if target.exists():
                    raise BuildError('Refusing existing tool output destination: ' + str(target))
                mkdir_guarded(root, target.parent)
            args = [arg.as_posix() if isinstance(arg, Path) else str(arg) for arg in args]
            commands.append(args)
            result = run(args, cwd=work, env=env, private=private, binary=binary)
            for target in outputs:
                guard(root, target, kind='file')
            return result
        tool_hashes = tool_file_hashes(tools)
        versions = {'java': invoke([tools['java'], '-version']).strip(),
                    'apksigner': invoke([tools['java'], '-jar', tools['apksigner'], 'version']).strip(),
                    'aapt': invoke([tools['aapt'], 'version']).strip(), 'python': sys.version}
        verify_signer(invoke([tools['java'], '-jar', tools['apksigner'], 'verify',
                              '--verbose', '--print-certs', original], private=True), expected_pin)
        if sha256(read_guarded(root, original)) != old['sha256']:
            raise BuildError('Prior APK changed during signature verification')
        certificate = invoke([tools['keytool'], '-exportcert', '-alias', 'androiddebugkey',
                              '-keystore', key, '-storepass', 'android'], private=True, binary=True)
        if sha256(certificate) != expected_pin:
            raise BuildError('Preserved keystore certificate differs from trusted signer pin')
        unsigned = output / 'unsigned.apk'
        entries = repack_unsigned(root, original, unsigned, old['packaged_entries'])
        aligned = output / 'aligned.apk'
        invoke([tools['zipalign'], '-f', '4', unsigned, aligned], outputs=[aligned])
        apk = candidate / APK_NAME
        invoke([tools['java'], '-jar', tools['apksigner'], 'sign', '--ks', key,
                '--ks-key-alias', 'androiddebugkey', '--ks-pass', 'pass:android', '--key-pass', 'pass:android',
                '--v4-signing-enabled', 'false', '--out', apk, aligned], outputs=[apk], private=True)
        verified_hash = sha256(read_guarded(root, apk))
        actual_signer = verify_signer(invoke([tools['java'], '-jar', tools['apksigner'], 'verify',
                                             '--verbose', '--print-certs', apk], private=True), expected_pin)
        invoke([tools['zipalign'], '-c', '4', apk])
        layout = verify_layout(root, apk)
        badging = invoke([tools['aapt'], 'dump', 'badging', apk])
        if "package: name='" + PACKAGE + "'" not in badging:
            raise BuildError('Candidate package ID mismatch')
        packaged_entries = verify_zip(root, apk, entries)
        def endpoint_guard():
            if sha256(read_guarded(root, apk)) != verified_hash:
                raise BuildError('Candidate changed after signature verification')
            if source_paths(root) != names or hash_files(root, names) != current_inputs:
                raise BuildError('source inputs changed during cached repack')
            if read_guarded(root, root / 'artifacts/accepted-apk.json') != old_pointer:
                raise BuildError('Accepted pointer changed during cached repack')
            accepted_path, accepted_manifest = read_accepted(root)
            if accepted_path != old_apk or sha256(read_guarded(root, old_apk.parent / 'build-manifest.json')) != old_manifest_hash:
                raise BuildError('Accepted compilation receipt changed during cached repack')
            if sha256(read_guarded(root, original)) != old['sha256']:
                raise BuildError('Private prior APK changed during cached repack')
            if tool_file_hashes(tools) != tool_hashes:
                raise BuildError('External tool inputs changed during cached repack')
            verify_zip(root, apk, entries)
            verify_layout(root, apk)
        endpoint_guard()
        receipt_keys = ('inputs', 'dependencies', 'dist_outputs', 'generated_native_outputs',
                        'source_capture', 'tools', 'commands', 'environment')
        manifest = {'schema': 2, 'apk': APK_NAME, 'sha256': verified_hash,
                    'bytes': len(read_guarded(root, apk)), 'package': PACKAGE,
                    'build_kind': 'accepted-payload-container-repack',
                    'build': 'debug cached container rebuild; no compilation or installation performed',
                    'signer': {'expected_sha256': expected_pin, 'actual_sha256': actual_signer,
                               'trusted_pin_source': 'android/signing-certificate.sha256'},
                    'packaged_entries': packaged_entries, 'layout': layout,
                    'inherited_compilation': {
                        'manifest_path': (old_apk.parent / 'build-manifest.json').relative_to(root).as_posix(),
                        'manifest_sha256': old_manifest_hash, 'apk_sha256': old['sha256'],
                        'receipt': {name: old[name] for name in receipt_keys},
                        'evidence': 'Inherited accepted receipt; snapshot/dependencies not copied or remeasured'},
                    'source_capture': {'mode': 'inherited accepted compilation; no compiler invoked',
                                       'path': old['source_capture']['path'],
                                       'original_endpoint_match': not changed,
                                       'captured_endpoint_match': False,
                                       'temporal_immutability_claimed': False},
                    'packaging': {'scope': 'identical unsigned payload; ZIP storage/alignment and same-key signatures only',
                                  'application_input_endpoint_match': True,
                                  'changed_helper_paths': changed,
                                  'helper_inputs': {name: current_inputs[name] for name in PACKAGING_HELPERS},
                                  'application_inputs': {name: digest for name, digest in current_inputs.items()
                                                         if name not in PACKAGING_HELPERS},
                                  'tools': {'versions': versions, 'files': tool_hashes},
                                  'commands': commands, 'environment': env,
                                  'outputs': {p.relative_to(output).as_posix(): sha256(read_guarded(root, p))
                                              for p in tree_files(root, output)}}}
        write_new(root, candidate / 'build-manifest.json', (json.dumps(manifest, indent=2) + '\n').encode())
        write_new(root, candidate / 'SHA256SUMS', (verified_hash + '  ' + APK_NAME + '\n').encode())
        publish_accepted(root, candidate, endpoint_guard)
        return read_accepted(root)
    finally:
        guard(root, lock).unlink(missing_ok=True)


def build_project(root, tools, *, runner=None):
    root = Path(root).absolute()
    guard(root, root, kind='dir')
    key = root / '.cache/prototype-debug.keystore'
    if not guard(root, key).is_file():
        raise BuildError('Missing preserved signing identity; restore the original keystore. Key generation is disabled.')
    guard(root, key, kind='file')
    expected_pin = read_pin(root, root / 'android/signing-certificate.sha256')
    cache = mkdir_guarded(root, root / '.cache')
    lock = cache / 'apk-builder.lock'
    write_new(root, lock, (str(os.getpid()) + '\n').encode())
    try:
        stage = Path(tempfile.mkdtemp(prefix='apk-build-', dir=cache))
        guard(root, stage, kind='dir')
        for name in ('tmp', 'home', 'cache', 'output', 'candidate'):
            mkdir_guarded(root, stage / name)
        source, output, candidate = stage / 'source', stage / 'output', stage / 'candidate'
        names = source_paths(root)
        inputs = capture_files(root, source, names)
        if read_pin(root, source / 'android/signing-certificate.sha256') != expected_pin:
            raise BuildError('Captured trusted signer pin changed before source capture')
        if source_paths(root) != names:
            raise BuildError('source inputs changed while capturing inventory')
        phase('source captured')
        dependencies = dependency_snapshot(root, source)
        phase('dependencies copied (%d files)' % len(dependencies['files']))
        dep_prints = fingerprint_files(source, dependencies['files'])
        phase('dependency fingerprints')
        env = clean_environment(stage, tools)
        run = runner if runner is not None else CommandRunner(root, stage / 'build.log')
        commands = []
        def invoke(args, *, private=False, binary=False, outputs=()):
            guard(root, source, kind='dir')
            for target in outputs:
                target = guard(root, target)
                if target.exists():
                    raise BuildError('Refusing existing tool output destination: ' + str(target))
                mkdir_guarded(root, target.parent)
            args = [arg.as_posix() if isinstance(arg, Path) else str(arg) for arg in args]
            commands.append(args)
            result = run(args, cwd=source, env=env, private=private, binary=binary)
            for target in outputs:
                guard(root, target, kind='file')
            return result
        tool_hashes = tool_file_hashes(tools)
        versions = {'java': invoke([tools['java'], '-version']).strip(),
                    'javac': invoke([tools['javac'], '-version']).strip(),
                    'node': invoke([tools['node'], '--version']).strip(),
                    'aapt': invoke([tools['aapt'], 'version']).strip(),
                    'aapt2': invoke([tools['aapt2'], 'version']).strip(),
                    'd8': invoke([tools['java'], '-cp', tools['d8'], 'com.android.tools.r8.D8', '--version']).strip(),
                    'apksigner': invoke([tools['java'], '-jar', tools['apksigner'], 'version']).strip(),
                    'python': sys.version}
        def check_identity():
            guard(root, key, kind='file')
            certificate = invoke([tools['keytool'], '-exportcert', '-alias', 'androiddebugkey',
                                  '-keystore', key, '-storepass', 'android'], private=True, binary=True)
            if sha256(certificate) != expected_pin:
                raise BuildError('Preserved keystore certificate differs from trusted signer pin')
        check_identity()
        # Direct node entrypoints preserve the package build gates without npm lifecycle,
        # global npm config, PATH shims, or writes to root dist/dependency caches.
        invoke([tools['node'], source / 'node_modules/typescript/bin/tsc', '--noEmit'])
        invoke([tools['node'], source / 'node_modules/vite/bin/vite.js', 'build',
                '--outDir', source / 'dist', '--emptyOutDir'])
        phase('tsc + vite build')
        dist = {file.relative_to(source / 'dist').as_posix(): sha256(read_guarded(root, file))
                for file in tree_files(root, source / 'dist')}
        resources, base = output / 'resources.zip', output / 'base.apk'
        invoke([tools['aapt2'], 'compile', '--dir', source / 'android/res', '-o', resources], outputs=[resources])
        invoke([tools['aapt2'], 'link', '-o', base, '--manifest', source / 'android/AndroidManifest.xml',
                '-I', tools['platform'], resources, '--min-sdk-version', '26', '--target-sdk-version', '36'], outputs=[base])
        classes = mkdir_guarded(root, output / 'classes')
        dex = mkdir_guarded(root, output / 'dex')
        java_sources = [p for p in tree_files(root, source / 'android/src') if p.suffix == '.java']
        if not java_sources:
            raise BuildError('Missing captured Java sources')
        invoke([tools['javac'], '--release', '8', '-classpath', tools['platform'], '-d', classes, *java_sources])
        class_files = [p for p in tree_files(root, classes) if p.suffix == '.class']
        if not class_files:
            raise BuildError('No compiled native classes')
        invoke([tools['java'], '-Xmx512m', '-Djava.io.tmpdir=' + str(stage / 'tmp'),
                '-Duser.home=' + str(stage / 'home'), '-cp', tools['d8'], 'com.android.tools.r8.D8',
                '--lib', tools['platform'], '--min-api', '26', '--output', dex, *class_files])
        unsigned = output / 'unsigned.apk'
        entries = package_unsigned(root, source, base, dex, unsigned,
                                   expected_inputs=inputs, expected_dist=dist)
        aligned = output / 'aligned.apk'
        invoke([tools['zipalign'], '-f', '4', unsigned, aligned], outputs=[aligned])
        check_identity()
        apk = candidate / APK_NAME
        invoke([tools['java'], '-jar', tools['apksigner'], 'sign', '--ks', key,
                '--ks-key-alias', 'androiddebugkey', '--ks-pass', 'pass:android', '--key-pass', 'pass:android',
                '--v4-signing-enabled', 'false', '--out', apk, aligned], outputs=[apk], private=True)
        verified_candidate_hash = sha256(read_guarded(root, apk))
        actual_signer = verify_signer(invoke([tools['java'], '-jar', tools['apksigner'], 'verify',
                                             '--verbose', '--print-certs', apk], private=True), expected_pin)
        if sha256(read_guarded(root, apk)) != verified_candidate_hash:
            raise BuildError('Candidate changed during signature verification')
        invoke([tools['zipalign'], '-c', '4', apk])
        layout = verify_layout(root, apk)
        badging = invoke([tools['aapt'], 'dump', 'badging', apk])
        if "package: name='" + PACKAGE + "'" not in badging:
            raise BuildError('Candidate package ID mismatch')
        packaged_entries = verify_zip(root, apk, entries)
        phase('native compile, package, sign, verify')
        def validate_sources():
            if sha256(read_guarded(root, apk)) != verified_candidate_hash:
                raise BuildError('Candidate changed after signature verification')
            if source_paths(root) != names or hash_files(root, names) != inputs:
                raise BuildError('source inputs changed during build; unpublished candidate rejected')
            check_hashes(source, inputs)
            if os.environ.get('APK_BUILD_FULL_VERIFY') == '1':
                check_hashes(source, dependencies['files'])
            else:
                check_fingerprints(source, dep_prints)
            snapshot_names = source_paths(source)
            if snapshot_names != names:
                raise BuildError('Captured source inventory changed')
            expected_deps = sorted(dependencies['files'])
            actual_deps = sorted(p.relative_to(source).as_posix() for p in tree_files(
                root, source / 'node_modules', exclude=DEP_CACHE_EXCLUDES))
            if actual_deps != expected_deps:
                raise BuildError('Captured dependency inventory changed')
            if tool_file_hashes(tools) != tool_hashes:
                raise BuildError('External tool inputs changed at endpoint; candidate rejected')
            current_dist = {p.relative_to(source / 'dist').as_posix(): sha256(read_guarded(root, p))
                            for p in tree_files(root, source / 'dist')}
            if current_dist != dist:
                raise BuildError('Generated dist changed after captured packaging')
            verify_zip(root, apk, entries)
        validate_sources()
        phase('endpoint validation')
        apk_bytes = read_guarded(root, apk)
        manifest = {'schema': 2, 'apk': APK_NAME, 'sha256': sha256(apk_bytes), 'bytes': len(apk_bytes),
                    'package': PACKAGE, 'build': 'debug; no installation performed',
                    'signer': {'expected_sha256': expected_pin, 'actual_sha256': actual_signer,
                               'trusted_pin_source': 'android/signing-certificate.sha256'},
                    'inputs': inputs, 'dependencies': dependencies, 'dist_outputs': dist,
                    'packaged_entries': packaged_entries, 'layout': layout,
                    'generated_native_outputs': {p.relative_to(output).as_posix(): sha256(read_guarded(root, p))
                                                 for p in tree_files(root, output)},
                    'tools': {'versions': versions, 'files': tool_hashes}, 'commands': commands,
                    'source_capture': {'mode': 'physical source and dependency copies used as compiler cwd',
                                       'path': source.relative_to(root).as_posix(),
                                       'scan_scope': 'captured source directories and explicit root files only',
                                       'original_endpoint_match': True, 'captured_endpoint_match': True,
                                       'temporal_immutability_claimed': False,
                                       'external_tools_evidence': 'measured files and endpoint equality, not frozen external tools'},
                    'environment': env}
        write_new(root, candidate / 'build-manifest.json', (json.dumps(manifest, indent=2) + '\n').encode())
        write_new(root, candidate / 'SHA256SUMS', (manifest['sha256'] + '  ' + APK_NAME + '\n').encode())
        # Every expensive/source validation completes BEFORE the accepted pointer can change.
        def publication_guard():
            if sha256(read_guarded(root, apk)) != verified_candidate_hash:
                raise BuildError('Candidate changed before publication')
            verify_layout(root, apk)
            if source_paths(root) != names or hash_files(root, names) != inputs:
                raise BuildError('source inputs changed before publication')
        publish_accepted(root, candidate, publication_guard)
        phase('publish')
        return read_accepted(root)
    finally:
        guard(root, lock).unlink(missing_ok=True)
