"""Compile every native source against real Android framework classes (no SDK needed).

The APK build needs the Android SDK, which a cloud session lacks; this catches framework API
mistakes earlier. ANDROID_ALL_JAR points to a Robolectric android-all jar for API 36
(org.robolectric:android-all:16-robolectric-13921718 from Maven Central, about 200 MB). It is a
read-only external input: keep it outside the repository. Not a replacement for the APK build.
"""
from pathlib import Path
import os
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
JDK = Path(os.environ.get('JAVA_HOME', 'C:/Program Files/Microsoft/jdk-21.0.8.9-hotspot')) / 'bin'
jar = os.environ.get('ANDROID_ALL_JAR')
if not jar or not Path(jar).is_file():
    sys.exit('Set ANDROID_ALL_JAR to an android-all API 36 jar (see this file).')
out = ROOT / '.cache/android-compile-check'
out.mkdir(parents=True, exist_ok=True)
sources = sorted((ROOT / 'android/src').rglob('*.java'))
result = subprocess.run([str(JDK / 'javac.exe'), '--release', '8', '-Xlint:-options', '-nowarn', '-cp', jar, '-d', str(out), *map(str, sources)], cwd=ROOT)
if result.returncode:
    sys.exit(result.returncode)
print(f'PASS android compile check: {len(sources)} native sources against Android framework classes')
