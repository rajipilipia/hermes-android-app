"""Compile/exercise NativeNotifications only: JVM fixtures, NOT OS/device proof.

SDK/JDK and the existing org.json dependency are read-only. All generated output
is isolated to .cache/notification-tests. No Gradle/APK/device operations occur.
Set JSON_JAR, JAVA_HOME or ANDROID_JAR to override the read-only inputs.
"""
from pathlib import Path
import os
import runpy
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / '.cache/notification-tests'
SRC = ROOT / 'android/src/us/pilipia/hermes/prototype/NativeNotifications.java'
JDK = Path(os.environ.get('JAVA_HOME', 'C:/Program Files/Microsoft/jdk-21.0.8.9-hotspot')) / 'bin'
SDK = Path(os.environ.get('ANDROID_JAR', 'C:/Android/Sdk/platforms/android-36/android.jar'))
JSON = Path(os.environ.get('JSON_JAR', str(Path.home() / '.gradle/caches/modules-2/files-2.1/org.json/json/20250517/d67181bbd819ccceb929b580a4e2fcb0c8b17cd8/json-20250517.jar')))


def run(args, label):
    env = os.environ.copy()
    env.update({key: str(OUT / 'tmp') for key in ['TMP', 'TEMP', 'TMPDIR']})
    result = subprocess.run(list(map(str, args)), cwd=ROOT, env=env, text=True,
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=60)
    (OUT / (label + '.log')).write_text(result.stdout, encoding='utf-8')
    print(result.stdout, end='')
    if result.returncode:
        raise SystemExit(result.returncode)


def main():
    for path in [JDK / 'javac.exe', JDK / 'java.exe', JSON, SDK]:
        if not path.is_file():
            raise SystemExit('Missing read-only test input: ' + str(path))
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / 'tmp').mkdir(exist_ok=True)
    classes = OUT / 'classes'
    if classes.exists():
        shutil.rmtree(classes)
    classes.mkdir()
    stubs = runpy.run_path(str(ROOT / 'android/tests/notification-stubs.py'))['STUBS']
    for name, content in stubs.items():
        target = OUT / 'fakes' / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content.strip() + '\n', encoding='utf-8')
    # Reflection makes API absence a focused assertion failure, not a javac typo.
    sources = ([SRC] if SRC.exists() else []) + [ROOT / 'android/tests/NativeNotificationsHostTest.java']
    run([JDK / 'javac.exe', '--release', '8', '-Xlint:-options', '-cp', JSON, '-d', classes,
         *sorted((OUT / 'fakes').rglob('*.java')), *sources], 'compile')
    run([JDK / 'java.exe', '-Djava.io.tmpdir=' + str(OUT / 'tmp'), '-cp', str(classes) + os.pathsep + str(JSON),
         'us.pilipia.hermes.prototype.NativeNotificationsHostTest', *sys.argv[1:]], 'behavior')
    if SRC.exists():
        sdk_classes = OUT / 'sdk-classes'
        sdk_classes.mkdir(exist_ok=True)
        run([JDK / 'javac.exe', '--release', '8', '-Xlint:-options', '-cp', SDK, '-d', sdk_classes,
             OUT / 'fakes/us/pilipia/hermes/prototype/MainActivity.java', SRC], 'sdk-compile')
        print('PASS NativeNotifications source compiles against android-36 (no APK).')


if __name__ == '__main__':
    main()
