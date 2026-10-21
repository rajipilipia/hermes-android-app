# Build and local checks

## Exercised environment

Windows with Git Bash, Node **26**, npm, Python **3.11+**, JDK **21**, Android SDK
build-tools **37.0.0** and platform **android-36**. The current manual native builder
uses Windows tool names; Linux/macOS APK builds are not claimed. No Android Studio
or Gradle wrapper is required. SDK/JDK inputs are read-only.

For the full tests, set `JAVA_HOME` to JDK 21, `JSON_JAR` to the org.json jar
described below, and `ANDROID_JAR` to your SDK's `platforms/android-36/android.jar`.
These are read-only test inputs. JVM compilation can exceed Vitest's five-second
default; the command below bounds worker concurrency and allows 30 seconds per test.

Run from this exported source directory, not the private development checkout:

```bash
npm ci --ignore-scripts
npm run typecheck
npm run build
npm run test -- --maxWorkers=2 --testTimeout=30000
```

`--ignore-scripts` avoids installing an Electron runtime; Electron is a development
type dependency, not the Android runtime. Build before test because a bootstrap test
reads `dist/index.html`. Dependencies are pinned in `package-lock.json`, including the
local `vendor/hermes/apps/shared` dependency. Browser fixtures are not phone acceptance.

## Native host tests

Set `JAVA_HOME` to your JDK 21 and `JSON_JAR` to a read-only
`org.json:json:20250517` jar, then run:

```bash
npm run test:native
```

The jar is available from Maven Central at
https://repo.maven.apache.org/maven2/org/json/json/20250517/json-20250517.jar .
Android host runners under `android/tests/` have their own documented SDK/JAR inputs;
some retain Windows-first defaults. Override their inputs rather than copying
machine-specific example directories. Optional PC proofs need a compatible separate
Hermes checkout and their own dependencies; they are not Android build prerequisites.

## Signing and APK build

The export intentionally contains **no signing key**. In your own checkout, generate
your own development key at `.cache/prototype-debug.keystore`. The debug builder
expects alias `androiddebugkey` and conventional Android debug passwords `android`.
Set `android/signing-certificate.sha256` to the lowercase SHA-256 of your key's DER
certificate. The included fingerprint is a public reference, not a usable private key.
Do not replace the private development project's key or certificate pin.

With your own local key/pin and explicit SDK/JDK paths:

```bash
python -B scripts/build-apk.py --sdk '<your-sdk>' --jdk '<your-jdk-21>'
python -B scripts/build-apk.py --show-accepted
```

The builder fails closed if the key is absent or its certificate differs. It compiles
physical source/dependency copies and publishes an immutable local bundle with a
build manifest only after integrity/signature checks. It never installs an APK.
This export preparation does not build or distribute a new APK.

A different signing key cannot update another publisher's installed package. Never
uninstall or clear someone else's data to hide that mismatch. Device installation,
public APK distribution and production signing require separate review.
