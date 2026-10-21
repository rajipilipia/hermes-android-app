"""Focused native host policy/lease tests; no APK, network, device or credentials."""
from pathlib import Path
import os
import shutil
import subprocess

ROOT = Path(__file__).resolve().parents[2]
JAVA = Path(os.environ.get('JAVA_HOME', 'C:/Program Files/Microsoft/jdk-21.0.8.9-hotspot')) / 'bin'
OUT = ROOT / 'build/native-host-tests'
if OUT.exists():
    shutil.rmtree(OUT)
OUT.mkdir(parents=True, exist_ok=True)
SRC = ROOT / 'android/src/us/pilipia/hermes/prototype'
sources = [p for name in ['NativeHostPolicy.java', 'ServerOrigin.java', 'CallbackLease.java', 'BoundedStreams.java', 'BundledDocument.java'] if (p := SRC / name).exists()]
tests = sorted((ROOT / 'android/tests').glob('NativeHost*Test.java'))
subprocess.run([str(JAVA / 'javac.exe'), '--release', '8', '-Xlint:-options', '-d', str(OUT), *map(str, sources + tests)], check=True, cwd=ROOT)
for test in tests:
    extra = [str(OUT / 'prepared-index.html')] if test.stem == 'NativeHostDocumentTest' else []
    subprocess.run([str(JAVA / 'java.exe'), '-cp', str(OUT), test.stem, *extra], check=True, cwd=ROOT)
