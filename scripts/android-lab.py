#!/usr/bin/env python3
"""Project-owned Android phone/fold lab; never uses the shared ADB servers.

See scripts/android-lab/README.md. Python stdlib only, Windows host.
"""
from pathlib import Path
import os
import ctypes
from ctypes import wintypes
import socket


def process_identity(pid):
    """Read identity without a reusable PID-only authority."""
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.OpenProcess.restype = wintypes.HANDLE
    kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel.GetProcessTimes.argtypes = [wintypes.HANDLE] + [ctypes.POINTER(wintypes.FILETIME)] * 4
    kernel.QueryFullProcessImageNameW.argtypes = [wintypes.HANDLE, wintypes.DWORD,
                                               wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD)]
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    handle = kernel.OpenProcess(0x1000, False, int(pid))
    if not handle:
        return None
    try:
        times = [wintypes.FILETIME() for _ in range(4)]
        if not kernel.GetProcessTimes(handle, *(ctypes.byref(t) for t in times)):
            return None
        if times[1].dwHighDateTime or times[1].dwLowDateTime:
            return None  # An exited process can remain queryable while Popen retains its handle.
        exe = ctypes.create_unicode_buffer(32768)
        count = wintypes.DWORD(len(exe))
        if not kernel.QueryFullProcessImageNameW(handle, 0, exe, ctypes.byref(count)):
            return None
        return {"pid": int(pid), "created": str((times[0].dwHighDateTime << 32) | times[0].dwLowDateTime),
                "exe": str(Path(exe.value).resolve())}
    finally:
        kernel.CloseHandle(handle)


def same_process(identity):
    return bool(identity and process_identity(identity["pid"]) == identity)


def terminate_owned(identity):
    """Check the *opened handle* creation time/exe to reject PID reuse races."""
    if not same_process(identity):
        return None
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.OpenProcess.restype = wintypes.HANDLE
    kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel.GetProcessTimes.argtypes = [wintypes.HANDLE] + [ctypes.POINTER(wintypes.FILETIME)] * 4
    kernel.QueryFullProcessImageNameW.argtypes = [wintypes.HANDLE, wintypes.DWORD,
                                               wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD)]
    kernel.TerminateProcess.argtypes = [wintypes.HANDLE, wintypes.UINT]
    kernel.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    handle = kernel.OpenProcess(0x1000 | 0x0001 | 0x00100000, False, identity["pid"])
    if not handle:
        return None
    try:
        times = [wintypes.FILETIME() for _ in range(4)]
        exe = ctypes.create_unicode_buffer(32768)
        n = wintypes.DWORD(len(exe))
        if not kernel.GetProcessTimes(handle, *(ctypes.byref(t) for t in times)):
            return None
        if times[1].dwHighDateTime or times[1].dwLowDateTime:
            return None  # An exited process can remain queryable while Popen retains its handle.
        if not kernel.QueryFullProcessImageNameW(handle, 0, exe, ctypes.byref(n)):
            return None
        created = str((times[0].dwHighDateTime << 32) | times[0].dwLowDateTime)
        if created != identity["created"] or str(Path(exe.value).resolve()) != identity["exe"]:
            return None
        if not kernel.TerminateProcess(handle, 0):
            raise OSError(ctypes.get_last_error(), "owned process termination failed")
        if kernel.WaitForSingleObject(handle, 10000) != 0:
            raise RuntimeError("owned process did not exit within 10s")
        return identity["pid"]
    finally:
        kernel.CloseHandle(handle)


def require_free_ports(ports):
    held = []
    try:
        for port in ports:
            sock = socket.socket()
            held.append(sock)
            if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
                sock.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
            try:
                sock.bind(("127.0.0.1", int(port)))
            except OSError as exc:
                raise RuntimeError(f"port {port} occupied; will not contact/kill/reuse its owner") from exc
    finally:
        for sock in held:
            sock.close()


def adb_argv(state, *args):
    port, console = state.get("adb_port"), state.get("console_port")
    if port != ADB_PORT or not isinstance(console, int) or console < 6000 or console % 2:
        raise ValueError("not an owned lab port")
    if state.get("serial") != f"emulator-{console}":
        raise ValueError("not the exact owned emulator serial")
    return [str(SDK / "platform-tools" / "adb.exe"), "-H", "127.0.0.1", "-P", str(port),
            "-s", state["serial"], *args]


ROOT = Path(__file__).resolve().parents[1]
LAB = ROOT / ".cache" / "android-lab"
SDK = Path(os.environ.get("HERMES_ANDROID_LAB_SDK", "C:/Android/Sdk"))
JDK = Path("C:/Program Files/Microsoft/jdk-21.0.8.9-hotspot")
ADB_PORT = 5041


def child_env(base=None):
    env = dict(os.environ if base is None else base)
    for key in ("ANDROID_SERIAL", "ADB_TRACE", "ADB_SERVER_SOCKET", "ADB_VENDOR_KEYS",
                "ANDROID_SDK_HOME", "ANDROID_PREFS_ROOT", "JAVA_OPTS", "AVDMANAGER_OPTS", "_JAVA_OPTIONS"):
        env.pop(key, None)
    env.update(ANDROID_HOME=str(SDK), ANDROID_SDK_ROOT=str(SDK), JAVA_HOME=str(JDK),
               ANDROID_USER_HOME=str(LAB / "user"),
               ANDROID_EMULATOR_HOME=str(LAB / "emulator"),
               ANDROID_AVD_HOME=str(LAB / "avd"),
               ANDROID_ADB_SERVER_PORT=str(ADB_PORT),
               ADB_SERVER_SOCKET=f"tcp:127.0.0.1:{ADB_PORT}",
               ADB_USB="0", ADB_EMU="0", ADB_MDNS="0", ADB_MDNS_AUTO_CONNECT="0",
               TMP=str(LAB / "tmp"), TEMP=str(LAB / "tmp"), TMPDIR=str(LAB / "tmp"),
               ANDROID_LOG_HOME=str(LAB / "logs"))
    return env


# OS tables only: this never probes shared ADB or enumerates its devices.
def listener_bindings(port):
    class Row(ctypes.Structure):
        _fields_ = [(name, wintypes.DWORD) for name in
                    ("state", "local_addr", "local_port", "remote_addr", "remote_port", "pid")]
    api = ctypes.WinDLL("iphlpapi", use_last_error=True)
    size = wintypes.ULONG(0)
    api.GetExtendedTcpTable(None, ctypes.byref(size), False, 2, 5, 0)
    buf = ctypes.create_string_buffer(size.value)
    if api.GetExtendedTcpTable(buf, ctypes.byref(size), False, 2, 5, 0) != 0:
        raise OSError("cannot inspect TCP listener ownership")
    count = ctypes.cast(buf, ctypes.POINTER(wintypes.DWORD)).contents.value
    rows = (Row * count).from_buffer(buf, ctypes.sizeof(wintypes.DWORD))
    return [{"pid": r.pid, "address": socket.inet_ntoa(r.local_addr.to_bytes(4, "little"))}
            for r in rows if r.state == 2 and socket.ntohs(r.local_port & 0xffff) == port]


def listener_pids(port):
    return {row["pid"] for row in listener_bindings(port)}


import argparse
import json
import subprocess
import sys
import time
import threading

sys.path.insert(0, str(ROOT / "scripts" / "android-lab"))
from windows_owned import OwnedJob, lifecycle_lock


def server_argv():
    # ADB 37 rejects a numeric hostname in -L; without -a, tcp:PORT binds loopback.
    return [str(SDK / "platform-tools" / "adb.exe"), "-L", f"tcp:{ADB_PORT}", "server", "nodaemon"]


STATE = LAB / "state.json"
PROFILES = {"phone": ("hermes_android_phone_api36", "pixel_8"),
            "fold": ("hermes_android_fold_api36", "pixel_fold")}


def avdmanager_argv(*args):
    tools = SDK / "cmdline-tools" / "23.0"
    if not tools.is_dir():
        tools = SDK / "cmdline-tools" / "latest"
    return [str(JDK / "bin" / "java.exe"), f"-Dcom.android.sdkmanager.toolsdir={tools}",
            "-classpath", str(tools / "lib" / "avdmanager-classpath.jar"),
            "com.android.sdklib.tool.AvdManagerCli", *args]


def emulator_argv(profile, console, gpu):
    if profile not in PROFILES or console < 6000 or console % 2:
        raise ValueError("invalid owned emulator profile/port")
    return [str(SDK / "emulator" / "emulator.exe"), "-avd", PROFILES[profile][0],
            "-ports", f"{console},{console + 1}", "-accel", "on", "-gpu", gpu,
            "-memory", "4096", "-cores", "4", "-no-snapshot", "-no-metrics",
            "-crash-report-mode", "disabled", "-camera-back", "none", "-camera-front", "none",
            "-adb-path", str(SDK / "platform-tools" / "adb.exe"), "-no-boot-anim"]


def save_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + f".{os.getpid()}.{threading.get_ident()}.writing")
    tmp.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)


def load_state():
    state = json.loads(STATE.read_text(encoding="utf-8"))
    if state.get("root") != str(ROOT) or state.get("adb_port") != ADB_PORT:
        raise RuntimeError("state is not owned by this repository")
    adb_argv(state, "get-state")
    return state


def run(cmd, timeout=30, check=True, input=None):
    result = subprocess.run(cmd, env=child_env(), cwd=ROOT, input=input,
                            capture_output=True, text=True, encoding="utf-8", errors="replace",
                            timeout=timeout)
    if check and result.returncode:
        raise RuntimeError(f"command failed ({result.returncode}): {result.stderr[-1500:]}")
    return result


def prepare():
    for name in ("user", "emulator", "avd", "tmp", "logs", "evidence"):
        (LAB / name).mkdir(parents=True, exist_ok=True)
    for tool in (SDK / "platform-tools" / "adb.exe", SDK / "emulator" / "emulator.exe",
                 SDK / "system-images" / "android-36" / "google_apis" / "x86_64" / "system.img",
                 JDK / "bin" / "java.exe"):
        if not tool.is_file():
            raise RuntimeError(f"missing read-only prerequisite: {tool}")
    manifest = LAB / "prepared.json"
    records = json.loads(manifest.read_text(encoding="utf-8")) if manifest.exists() else {}
    for profile, (name, device_name) in PROFILES.items():
        avd = LAB / "avd" / f"{name}.avd"
        ini = LAB / "avd" / f"{name}.ini"
        if avd.exists() or ini.exists():
            if records.get(profile, {}).get("avd") != str(avd) or not (avd / "config.ini").is_file():
                raise RuntimeError(f"existing unowned/incomplete AVD; refusing overwrite: {name}")
            continue
        result = run(avdmanager_argv("create", "avd", "--name", name, "--package",
                                    "system-images;android-36;google_apis;x86_64", "--device",
                                    device_name, "--path", str(avd)), timeout=120, input="no\n")
        (LAB / "logs" / f"prepare-{profile}.log").write_text(result.stdout + result.stderr,
                                                            encoding="utf-8")
        config = avd / "config.ini"
        original = config.read_text(encoding="utf-8")
        pairs = dict(line.split("=", 1) for line in original.splitlines() if "=" in line)
        pairs.update({"hw.ramSize": "4096", "hw.cpu.ncore": "4", "hw.keyboard": "no" if profile == "phone" else "yes",
                      "hw.camera.back": "none", "hw.camera.front": "none",
                      "hw.audioInput": "yes", "hw.audioOutput": "yes",
                      "fastboot.forceColdBoot": "yes"})
        config.write_text("".join(f"{k}={v}\n" for k, v in pairs.items()), encoding="utf-8")
        records[profile] = {"avd": str(avd), "name": name, "device": device_name,
                            "api": 36, "abi": "x86_64", "sdk_read_only": str(SDK)}
        save_json(manifest, records)
    return records


def assert_server_owned(state):
    identity = state.get("adb")
    rows = listener_bindings(ADB_PORT)
    if not same_process(identity) or {r["pid"] for r in rows} != {identity["pid"]} or any(
            r["address"] != "127.0.0.1" for r in rows):
        raise RuntimeError("dedicated ADB identity/listener changed; refusing any ADB command")


def device(state, *args, timeout=30, check=True):
    assert_server_owned(state)
    ids = state.get("emulator_processes", [])
    owners = listener_pids(state["console_port"])
    if not owners or not owners.issubset({i["pid"] for i in ids if same_process(i)}):
        raise RuntimeError("emulator listener identity changed; refusing any device command")
    return run(adb_argv(state, *args), timeout=timeout, check=check)


def refresh_job(state, job):
    # Membership is kernel-established before execution, not inferred from PID ancestry.
    state["emulator_processes"] = [identity for pid in job.pids()
        if pid != state.get("adb", {}).get("pid")
        and (identity := process_identity(pid)) is not None and pid in job.pids()]
    save_json(STATE, state)


def status(probe=False):
    if not STATE.exists():
        return {"status": "not-started", "state": str(STATE)}
    state = load_state()
    adb_listeners = listener_bindings(ADB_PORT)
    result = {"status": state.get("status"), "stored_status": state.get("status"), "serial": state["serial"],
              "state": str(STATE), "adb_port": ADB_PORT, "console_port": state["console_port"],
              "supervisor_alive": same_process(state.get("supervisor")),
              "adb_owned": same_process(state.get("adb")),
              "emulator_pids_alive": [i["pid"] for i in state.get("emulator_processes", []) if same_process(i)],
              "adb_listener_pids": sorted({row["pid"] for row in adb_listeners}),
              "console_listener_pids": sorted(listener_pids(state["console_port"])),
              "logs": state.get("logs"), "readiness": state.get("readiness")}
    # Persisted readiness is historical; derive current health without publishing state.
    if result["status"] == "ready" and (
            not result["supervisor_alive"] or not result["adb_owned"]
            or result["adb_listener_pids"] != [(state.get("adb") or {}).get("pid")]
            or any(row["address"] != "127.0.0.1" for row in adb_listeners)
            or not result["console_listener_pids"]
            or not set(result["console_listener_pids"]).issubset(result["emulator_pids_alive"])):
        result["status"] = "unhealthy"
    if probe and result["supervisor_alive"]:
        try:
            result["live_boot_completed"] = device(state, "shell", "getprop", "sys.boot_completed", timeout=5).stdout.strip()
            result["live_device_state"] = device(state, "get-state", timeout=5).stdout.strip()
            if result["live_boot_completed"] != "1" or result["live_device_state"] != "device":
                raise RuntimeError("live boot/device state is not ready")
        except (RuntimeError, subprocess.TimeoutExpired) as exc:
            result["live_probe_error"] = str(exc)
            if result["status"] == "ready":
                result["status"] = "unhealthy"
    return result


def readiness(state):
    fields = {"boot_completed": ("getprop", "sys.boot_completed"),
              "api": ("getprop", "ro.build.version.sdk"),
              "android_version": ("getprop", "ro.build.version.release"),
              "abi": ("getprop", "ro.product.cpu.abi"),
              "model": ("getprop", "ro.product.model"),
              "display_size": ("wm", "size"), "display_density": ("wm", "density"),
              "keyboard": ("settings", "get", "secure", "default_input_method"),
              "show_ime_with_hard_keyboard": ("settings", "get", "secure", "show_ime_with_hard_keyboard"),
              "webview": ("dumpsys", "webviewupdate"),
              "browser": ("cmd", "package", "resolve-activity", "--brief", "-a",
                          "android.intent.action.VIEW", "-d", "https://example.com")}
    evidence = {key: device(state, "shell", *args).stdout.strip() for key, args in fields.items()}
    evidence["emulator_avd"] = device(state, "emu", "avd", "name").stdout.strip()
    evidence["audio_capture"] = "NOT RUN: no host microphone/personal content recorded; audio enabled for later explicit tests"
    evidence["apk_install"] = "NOT RUN: source freeze/independent review required"
    if evidence["boot_completed"] != "1" or evidence["api"] != "36" or evidence["abi"] != "x86_64":
        raise RuntimeError("device identity/API/ABI readiness failed")
    if PROFILES[state["profile"]][0] not in evidence["emulator_avd"]:
        raise RuntimeError("emulator AVD identity did not match the owned definition")
    if "Current WebView package" not in evidence["webview"] or "No activity found" in evidence["browser"]:
        raise RuntimeError("WebView/browser readiness failed")
    path = LAB / "evidence" / f"readiness-{state['run_id']}.json"
    save_json(path, evidence)
    return str(path)


def cleanup(state, job=None):
    # Exact-serial graceful shutdown first. Never kill-server and never PID-only kill.
    try:
        if state.get("emulator_processes"):
            device(state, "emu", "kill", timeout=10, check=False)
    except (RuntimeError, subprocess.TimeoutExpired):
        pass
    if job is not None:
        job.terminate()
        deadline = time.monotonic() + 10
        while job.pids() and time.monotonic() < deadline:
            time.sleep(0.05)
        if job.pids():
            raise RuntimeError("owned job did not become empty")
    else:
        for identity in reversed(state.get("emulator_processes", [])):
            terminate_owned(identity)
        terminate_owned(state.get("adb"))
    state["status"] = "stopped"
    state["cleanup_remaining_pids"] = [i["pid"] for i in state.get("emulator_processes", []) +
                                       ([state["adb"]] if state.get("adb") else []) if same_process(i)]
    save_json(STATE, state)
    if state["cleanup_remaining_pids"]:
        raise RuntimeError("some owned processes remain after cleanup")


def start(profile, console, gpu, boot_timeout):
    with lifecycle_lock(LAB / "lifecycle.lock"), OwnedJob() as job:
        _start(profile, console, gpu, boot_timeout, job)


def _start(profile, console, gpu, boot_timeout, job):
    prepare()
    if STATE.exists():
        previous = load_state()
        if same_process(previous.get("supervisor")) or same_process(previous.get("adb")) or any(
                same_process(i) for i in previous.get("emulator_processes", [])):
            raise RuntimeError("lab already running or owned resources remain; inspect status/stop")
    require_free_ports([ADB_PORT, console, console + 1])
    accel = run([str(SDK / "emulator" / "emulator-check.exe"), "accel"], timeout=30)
    (LAB / "logs" / "accel.log").write_text(accel.stdout + accel.stderr, encoding="utf-8")
    control = socket.socket()
    control.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
    control.bind(("127.0.0.1", 0))
    control.listen(1)
    run_id = str(time.time_ns())
    state = {"root": str(ROOT), "run_id": run_id, "profile": profile, "status": "starting",
             "adb_port": ADB_PORT, "console_port": console, "serial": f"emulator-{console}",
             "control_port": control.getsockname()[1], "supervisor": process_identity(os.getpid()),
             "emulator_processes": [], "logs": {"adb": str(LAB / "logs" / f"adb-{run_id}.log"),
                                               "emulator": str(LAB / "logs" / f"emulator-{run_id}.log")}}
    save_json(STATE, state)
    adb_log = open(state["logs"]["adb"], "wb")
    emu_log = open(state["logs"]["emulator"], "wb")
    adb_process = None
    emulator_process = None
    stop_requested, cleanup_done = threading.Event(), threading.Event()

    def control_server():
        while not cleanup_done.is_set():
            try:
                conn, _ = control.accept()
            except OSError:
                return
            with conn:
                conn.settimeout(5)
                try:
                    request = conn.recv(64)
                    if request == b"stop\n":
                        stop_requested.set()
                        if cleanup_done.wait(45):
                            conn.sendall(b"STOPPED\n")
                        return
                    conn.sendall(b"INVALID\n")
                except OSError:
                    continue

    control_thread = threading.Thread(target=control_server, daemon=True)
    control_thread.start()
    try:
        adb_process = job.spawn(server_argv(), env=child_env(), cwd=ROOT,
                                stdin=subprocess.DEVNULL, stdout=adb_log, stderr=subprocess.STDOUT)
        state["adb"] = process_identity(adb_process.pid)
        save_json(STATE, state)
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            if adb_process.poll() is not None:
                raise RuntimeError("dedicated ADB foreground server exited; inspect private log")
            if listener_pids(ADB_PORT) == {adb_process.pid}:
                break
            time.sleep(0.25)
        assert_server_owned(state)
        require_free_ports([console, console + 1])
        if stop_requested.is_set():
            return
        emulator_process = job.spawn(emulator_argv(profile, console, gpu), env=child_env(),
                                     cwd=ROOT, stdin=subprocess.DEVNULL,
                                     stdout=emu_log, stderr=subprocess.STDOUT)
        identity = process_identity(emulator_process.pid)
        if identity:
            state["emulator_processes"] = [identity]
            save_json(STATE, state)
        deadline = time.monotonic() + boot_timeout
        while time.monotonic() < deadline:
            if stop_requested.is_set():
                return
            refresh_job(state, job)
            if not any(same_process(i) for i in state["emulator_processes"]):
                raise RuntimeError("owned emulator exited; inspect private log")
            try:
                boot = device(state, "shell", "getprop", "sys.boot_completed", timeout=5, check=False)
                if boot.returncode == 0 and boot.stdout.strip() == "1":
                    break
            except (RuntimeError, subprocess.TimeoutExpired):
                pass
            time.sleep(2)
        else:
            raise RuntimeError(f"emulator boot deadline exceeded ({boot_timeout}s)")
        state["readiness"] = readiness(state)
        state["status"] = "ready"
        save_json(STATE, state)
        print(f"LAB_READY serial={state['serial']} adb=127.0.0.1:{ADB_PORT} state={STATE}", flush=True)
        # The control thread also services cancellation while the emulator is booting.
        stop_requested.wait()
    finally:
        try:
            if state.get("status") != "stopped":
                cleanup(state, job)
        finally:
            cleanup_done.set()
            control_thread.join(timeout=2)
            control.close()
            if emulator_process:
                try:
                    emulator_process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    pass
            if adb_process:
                adb_process.wait(timeout=10)
            adb_log.close()
            emu_log.close()


def cleanup_stale(state):
    with lifecycle_lock(LAB / "lifecycle.lock"):
        current = load_state()
        if current.get("run_id") != state.get("run_id") or same_process(current.get("supervisor")):
            raise RuntimeError("lab generation changed during stop; refusing stale cleanup/publication")
        cleanup(current)


def stop():
    if not STATE.exists():
        return {"status": "not-started"}
    state = load_state()
    supervisor = state.get("supervisor")
    if same_process(supervisor):
        if listener_pids(state["control_port"]) != {supervisor["pid"]}:
            raise RuntimeError("control socket owner changed; refusing stop")
        with socket.create_connection(("127.0.0.1", state["control_port"]), timeout=10) as sock:
            sock.settimeout(60)
            sock.sendall(b"stop\n")
            if sock.recv(64) != b"STOPPED\n":
                # An older/interrupted supervisor may exit after terminating its job but
                # before acknowledging. Never trust EOF as proof: recheck exact death,
                # then reacquire lifecycle ownership and reconcile that same generation.
                deadline = time.monotonic() + 10
                while same_process(supervisor) and time.monotonic() < deadline:
                    time.sleep(0.05)
                cleanup_stale(state)  # refuses a live or replacement generation
    else:
        cleanup_stale(state)
    return status()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("prepare", "start", "status", "stop", "readiness"))
    parser.add_argument("--profile", choices=PROFILES, default="phone")
    parser.add_argument("--console-port", type=int, default=6000)
    parser.add_argument("--gpu", choices=("auto", "software", "swiftshader"), default="auto")
    parser.add_argument("--boot-timeout", type=int, default=300)
    args = parser.parse_args()
    if args.console_port < 6000 or args.console_port > 65000 or args.console_port % 2:
        parser.error("console port must be even and in 6000..65000")
    if not 30 <= args.boot_timeout <= 600:
        parser.error("boot timeout must be in 30..600 seconds")
    if args.action == "start":
        start(args.profile, args.console_port, args.gpu, args.boot_timeout)
        return
    if args.action == "prepare":
        with lifecycle_lock(LAB / "lifecycle.lock"):
            result = prepare()
    elif args.action == "stop":
        result = stop()
    elif args.action == "readiness":
        result = {"readiness": readiness(load_state())}
    else:
        result = status(probe=True)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    try:
        main()
    except (OSError, RuntimeError, ValueError, subprocess.TimeoutExpired) as exc:
        print(f"LAB_ERROR: {exc}", file=sys.stderr, flush=True)
        sys.exit(1)
