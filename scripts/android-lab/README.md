# Isolated Android lab (Windows, Python stdlib)

This launcher owns only this repository's phone/fold AVDs, one dedicated loopback
ADB server, and the processes it starts. It does not install an APK, contact a
physical phone, enumerate shared ADB devices, or modify the SDK/JDK/virtualization.

From the repository root:

```bash
python3 scripts/android-lab.py prepare
python3 -u scripts/android-lab.py start --profile phone --console-port 6000 --gpu auto
# Keep start running in an owned terminal/background process. Wait for LAB_READY.
python3 scripts/android-lab.py status
python3 scripts/android-lab.py readiness
python3 scripts/android-lab.py stop
python3 -m unittest discover -s scripts/android-lab -v
```

`start` is deliberately foreground: it supervises its own ADB/emulator children.
Under Hermes use terminal(background=true, notify=['LAB_READY','LAB_ERROR']). A
subagent must hand off that tracked process to the parent before finishing. The
supervisor's control socket blocks while idle; boot polling has a 300-second
monotonic deadline (configurable 30..600), and individual commands have timeouts.
`stop` also cancels boot. A competing start fails the lifecycle lock; occupied
ports are an error, never permission to kill or reuse another process.

`prepare` creates both `pixel_8` and `pixel_fold` definitions without `--force`.
It reuses only definitions recorded in the private prepared manifest. An existing
unrecorded/incomplete AVD fails closed. Only one AVD runs at a time; stop the phone
before `start --profile fold`. Do not run both heavy devices when memory is high.
For an actual graphics failure, stop owned resources and retry `--gpu software`;
no host security/virtualization changes are needed or authorized.

## Boundaries and identity

- Read-only inputs: SDK `<android-sdk>` (API36 google_apis/x86_64),
  JDK `C:/Program Files/Microsoft/jdk-21.0.8.9-hotspot`. Inherited SDK variables are
  overridden in child environments, not globally.
- Private AVDs, preferences, temporary files, logs, state and evidence all live in
  ignored `.cache/android-lab/`. `state.json` records exact process creation times,
  executable paths, serial, ports, logs and the readiness evidence path.
- ADB server uses `-L tcp:5041 server nodaemon`, **without `-a`**. This ADB version
  rejects `-L tcp:127.0.0.1:5041` as an unsupported listener hostname, not a bind or
  privilege failure. OS TCP tables must independently prove the actual listener
  is `127.0.0.1:5041` and belongs to the captured foreground server.
- Every device command is explicitly `-H 127.0.0.1 -P 5041 -s emulator-6000`
  (or the exact selected console-port serial), after checking both server and
  console listener ownership. Servers5037/5038 are never contacted or killed.
- Child environment sets `ADB_USB=0`, `ADB_EMU=0`, `ADB_MDNS=0`,
  `ADB_MDNS_AUTO_CONNECT=0`. Discovery/scanning remain disabled.
- `ANDROID_USER_HOME` does **not** fully isolate Windows ADB identity. ADB can use
  the existing account `.android/adbkey`; this launcher never overwrites,
  displays, or copies that key and does not claim separate ADB keys.
- A Windows Job Object receives each child while suspended, before execution;
  all descendants are job-owned and killed on supervisor/job closure. PID snapshots
  do not establish kill authority. Fallback stale-state cleanup verifies creation
  time and executable again on an opened process handle. No name-based/taskkill
  sweep is used. A lifecycle lock excludes competing ownership/state writes.
- `ANDROID_PREFS_ROOT` is removed: setting it equal to `ANDROID_USER_HOME` is
  incorrect in avdmanager23 because its deprecated semantics add `.android`, causing
  preference-path conflict and AVD creation failure. Use `ANDROID_USER_HOME` alone.

## Readiness versus application acceptance

`LAB_READY` proves an actual boot, exact AVD, API36/x86_64, display metrics, active
keyboard identifier, current WebView provider, and a resolved browser activity.
The JSON in `.cache/android-lab/evidence/` contains actual device output. It does
not prove an APK, authentication, WebView application rendering, browser navigation,
voice, or feature parity. Browser navigation/keyboard screenshots may be recorded
separately in the same private evidence directory.

Audio remains enabled (`-no-audio` is intentionally absent); both cameras are off.
Readiness does not request RECORD_AUDIO or capture the host microphone. A later
synthetic audio fixture proves only fixture transport/playback, not live Android
microphone capture. Explicit consent and observed native/browser permission flow
are still needed for actual capture tests. No personal content is used here.
