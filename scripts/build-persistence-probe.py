"""Compile source, or prepare a SEPARATE UNSIGNED instrumentation APK for its sole build owner.
No signing-key access, ADB, device operations, dependency downloads or live HTTP.
Default is compile-only. Generated files stay under ignored .cache.
"""
from pathlib import Path
import argparse
import hashlib
import json
import os
import subprocess
import zipfile

ROOT = Path(__file__).resolve().parents[1]

def main():
    parser = argparse.ArgumentParser(__doc__)
    parser.add_argument('--sdk', default='C:/Android/Sdk')
    parser.add_argument('--jdk', default='C:/Program Files/Microsoft/jdk-21.0.8.9-hotspot')
    parser.add_argument('--unsigned-apk', action='store_true', help='Build owner only; no signing/install')
    args = parser.parse_args()
    sdk, jdk = Path(args.sdk), Path(args.jdk)
    tools, java = sdk / 'build-tools/37.0.0', jdk / 'bin'
    jar = sdk / 'platforms/android-36/android.jar'
    out = ROOT / '.cache/persistent-login-probe'
    out.mkdir(parents=True, exist_ok=True)
    native = ROOT / 'android/src/us/pilipia/hermes/prototype'
    sources = [native / name for name in ['NativeAuth.java', 'EncryptedRefreshStore.java', 'AndroidRefreshStore.java']]
    probe = ROOT / 'android/instrumentation/PersistentLoginProbe.java'
    manifest = ROOT / 'android/instrumentation/AndroidManifest.xml'
    before = {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest() for p in sources + [probe, manifest]}
    production, tests = out / 'production', out / 'tests'
    production.mkdir(exist_ok=True); tests.mkdir(exist_ok=True)
    def run(command, label):
        completed = subprocess.run(list(map(str, command)), cwd=ROOT, capture_output=True, text=True, timeout=120)
        (out / (label + '.log')).write_text(completed.stdout + completed.stderr, encoding='utf-8')
        print(completed.stdout + completed.stderr, end='')
        if completed.returncode:
            raise SystemExit(completed.returncode)
    run([java / 'javac.exe', '--release', '8', '-Xlint:-options', '-classpath', jar, '-d', production, *sources], 'production-compile')
    run([java / 'javac.exe', '--release', '8', '-Xlint:-options', '-classpath', os.pathsep.join(map(str, [jar, production])), '-d', tests, probe], 'probe-compile')
    if args.unsigned_apk:
        dex = out / 'dex'; dex.mkdir(exist_ok=True)
        # Same production implementation, but packaged in the self-targeting probe UID.
        classfiles = sorted(production.rglob('*.class')) + sorted(tests.rglob('*.class'))
        run([java / 'java.exe', '-cp', tools / 'lib/d8.jar', 'com.android.tools.r8.D8', '--lib', jar, '--classpath', production, '--min-api', '26', '--output', dex, *classfiles], 'probe-dex')
        base = out / 'probe-unaligned.apk'
        run([tools / 'aapt2.exe', 'link', '-I', jar, '--manifest', manifest, '-o', base], 'probe-package')
        with zipfile.ZipFile(base, 'a', compression=zipfile.ZIP_DEFLATED) as apk:
            for item in sorted(dex.glob('classes*.dex')):
                apk.write(item, item.name)
        run([tools / 'zipalign.exe', '-f', '4', base, out / 'probe-unsigned-aligned.apk'], 'probe-align')
    after = {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest() for p in sources + [probe, manifest]}
    if before != after:
        raise SystemExit('Source changed during compilation; reject evidence')
    report = {'source_sha256': after, 'api': 36, 'compile_passed': True, 'apk_built': args.unsigned_apk, 'signed': False, 'device_exercised': False}
    (out / 'source-compile.json').write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    print('PASS API36 production native encrypted-store and separate instrumentation source compilation; NOT device/Keystore runtime proof')
    if args.unsigned_apk:
        print(str(out / 'probe-unsigned-aligned.apk'))

if __name__ == '__main__':
    main()
