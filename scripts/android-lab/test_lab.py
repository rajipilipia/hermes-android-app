"""Run with python3 -m unittest discover -s scripts/android-lab -v."""
import importlib.util
import os
from pathlib import Path
import unittest
from contextlib import contextmanager

SCRIPT = Path(__file__).resolve().parents[1] / "android-lab.py"


class LabTests(unittest.TestCase):
    def load(self):
        self.assertTrue(SCRIPT.is_file(), "isolated lab tooling is not implemented")
        spec = importlib.util.spec_from_file_location("android_lab", SCRIPT)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        (module.LAB / "tmp").mkdir(parents=True, exist_ok=True)
        return module

    def test_atomic_save_retries_a_real_windows_reader_and_counts_it(self):
        lab = self.load()
        import io
        import json
        import tempfile
        from contextlib import redirect_stderr
        from unittest.mock import patch
        with tempfile.TemporaryDirectory(dir=lab.LAB / "tmp") as folder:
            path = Path(folder) / "state.json"
            path.write_text('{"generation": "old"}', encoding="utf-8")
            reader = path.open("r", encoding="utf-8")
            diagnostics = io.StringIO()
            try:
                def release_reader(delay):
                    self.assertEqual(json.loads(reader.read()), {"generation": "old"})
                    reader.close()
                with redirect_stderr(diagnostics), patch.object(lab.time, "sleep", side_effect=release_reader):
                    retries = lab.save_json(path, {"generation": "new"})
                self.assertEqual(retries, 1)
                self.assertEqual(json.loads(path.read_text()), {"generation": "new"})
                events = [json.loads(line) for line in diagnostics.getvalue().splitlines()]
                self.assertEqual(len(events), 1)
                self.assertEqual(events[0]["event"], "state_replace_retry")
                self.assertEqual(events[0]["retry"], 1)
                self.assertIn(os.getpid(), [p["pid"] for p in events[0]["holders"]["processes"]])
                self.assertFalse(list(Path(folder).glob("*.writing")))
            finally:
                reader.close()

    def test_state_reader_serializes_publication_until_closed(self):
        lab = self.load()
        import json
        import tempfile
        import threading
        with tempfile.TemporaryDirectory(dir=lab.LAB / "tmp") as folder:
            path = Path(folder) / "state.json"
            path.write_text('{"generation": "old"}', encoding="utf-8")
            started, finished = threading.Event(), threading.Event()
            result, errors = [], []
            def publish():
                started.set()
                try:
                    result.append(lab.save_json(path, {"generation": "new"}))
                except Exception as exc:
                    errors.append(exc)
                finally:
                    finished.set()
            with lab.state_reader(path) as reader:
                writer = threading.Thread(target=publish)
                writer.start()
                self.assertTrue(started.wait(1))
                self.assertFalse(finished.wait(0.1))
                self.assertEqual(json.load(reader), {"generation": "old"})
            writer.join(timeout=5)
            self.assertFalse(writer.is_alive())
            self.assertEqual(errors, [])
            self.assertEqual(result, [0])
            self.assertEqual(json.loads(path.read_text()), {"generation": "new"})

    def test_atomic_save_persistent_reader_fails_with_exact_retry_count(self):
        lab = self.load()
        import io
        import json
        import tempfile
        from contextlib import redirect_stderr
        from unittest.mock import patch
        with tempfile.TemporaryDirectory(dir=lab.LAB / "tmp") as folder:
            path = Path(folder) / "state.json"
            path.write_text('{"generation": "old"}', encoding="utf-8")
            diagnostics = io.StringIO()
            with path.open("r", encoding="utf-8"), redirect_stderr(diagnostics), patch.object(lab.time, "sleep"):
                with self.assertRaises(PermissionError):
                    lab.save_json(path, {"generation": "new"})
            events = [json.loads(line) for line in diagnostics.getvalue().splitlines()]
            self.assertEqual([e["retry"] for e in events if e["event"] == "state_replace_retry"], [1, 2, 3, 4, 5])
            self.assertEqual(events[-1]["event"], "state_replace_failed")
            self.assertEqual(json.loads(path.read_text()), {"generation": "old"})
            self.assertFalse(list(Path(folder).glob("*.writing")))

    def test_atomic_save_does_not_retry_other_errors(self):
        lab = self.load()
        import tempfile
        from unittest.mock import patch
        wrong_permission = PermissionError("not an eligible Windows sharing error")
        wrong_permission.winerror = 123
        for error in (OSError("disk full"), wrong_permission):
            with self.subTest(error=type(error).__name__), tempfile.TemporaryDirectory(dir=lab.LAB / "tmp") as folder:
                path = Path(folder) / "state.json"
                with patch.object(lab.os, "replace", side_effect=error) as replace, patch.object(
                        lab.time, "sleep") as sleep, patch.object(lab, "file_holders") as holders:
                    with self.assertRaises(type(error)):
                        lab.save_json(path, {"value": 1})
                    replace.assert_called_once()
                    sleep.assert_not_called()
                    holders.assert_not_called()
                self.assertFalse(path.exists())
                self.assertFalse(list(Path(folder).glob("*.writing")))

    def test_state_access_coordinates_separate_cli_processes(self):
        lab = self.load()
        import json
        import subprocess
        import sys
        import tempfile
        with tempfile.TemporaryDirectory(dir=lab.LAB / "tmp") as folder:
            path = Path(folder) / "state.json"
            path.write_text('{"generation": "old"}', encoding="utf-8")
            code = ("import runpy,sys; from pathlib import Path; "
                    "lab=runpy.run_path(sys.argv[1],run_name='reader_fixture'); "
                    "reader=lab['state_reader'](Path(sys.argv[2])); reader.__enter__(); "
                    "print('READY',flush=True); sys.stdin.read(); reader.__exit__(None,None,None)")
            child = subprocess.Popen([sys.executable, "-B", "-c", code, str(SCRIPT), str(path)],
                                     stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
            try:
                self.assertEqual(child.stdout.readline().strip(), "READY")
                with self.assertRaisesRegex(RuntimeError, "state access lock failed or timed out"):
                    lab.save_json(path, {"generation": "new"})
                self.assertEqual(json.loads(path.read_text()), {"generation": "old"})
                child.stdin.close()
                child.wait(timeout=5)
                self.assertEqual(child.returncode, 0)
                self.assertEqual(lab.save_json(path, {"generation": "new"}), 0)
                self.assertEqual(json.loads(path.read_text()), {"generation": "new"})
            finally:
                if child.poll() is None:
                    child.kill()
                    child.wait(timeout=5)
                child.stdin.close()
                child.stdout.close()

    def test_child_environment_isolates_discovery_and_storage(self):
        lab = self.load()
        env = lab.child_env({"ANDROID_HOME": "wrong", "ANDROID_SERIAL": "physical",
                             "ADB_TRACE": "all", "PATH": os.environ["PATH"]})
        self.assertEqual(env["ANDROID_HOME"], str(lab.SDK))
        for key in ("ADB_USB", "ADB_EMU", "ADB_MDNS", "ADB_MDNS_AUTO_CONNECT"):
            self.assertEqual(env[key], "0")
        self.assertNotIn("ANDROID_SERIAL", env)
        self.assertNotIn("ADB_TRACE", env)
        for key in ("ANDROID_USER_HOME", "ANDROID_EMULATOR_HOME", "ANDROID_AVD_HOME",
                    "TMP", "TEMP", "TMPDIR"):
            self.assertTrue(Path(env[key]).is_relative_to(lab.LAB))

    def test_rejects_shared_ports_and_foreign_device(self):
        lab = self.load()
        for port in (5037, 5038, 5040):
            with self.assertRaises(ValueError):
                lab.adb_argv({"adb_port": port, "console_port": 6000,
                              "serial": "emulator-6000"}, "get-state")
        for serial in ("physical", "emulator-5554", "127.0.0.1:6001"):
            with self.assertRaises(ValueError):
                lab.adb_argv({"adb_port": 5041, "console_port": 6000,
                              "serial": serial}, "get-state")
        cmd = lab.adb_argv({"adb_port": 5041, "console_port": 6000,
                            "serial": "emulator-6000"}, "get-state")
        self.assertEqual(cmd[1:], ["-H", "127.0.0.1", "-P", "5041", "-s",
                                  "emulator-6000", "get-state"])

    def test_busy_port_is_rejected_without_connecting(self):
        lab = self.load()
        import socket
        with socket.socket() as listener:
            listener.bind(("127.0.0.1", 0))
            listener.listen()
            port = listener.getsockname()[1]
            with self.assertRaises(RuntimeError):
                lab.require_free_ports([port])
        lab.require_free_ports([port])

    def test_pid_reuse_or_foreign_executable_cannot_be_terminated(self):
        lab = self.load()
        mine = lab.process_identity(os.getpid())
        self.assertTrue(lab.same_process(mine))
        self.assertFalse(lab.same_process({**mine, "created": "not-my-creation"}))
        self.assertFalse(lab.same_process({**mine, "exe": "C:/foreign.exe"}))
        self.assertIsNone(lab.terminate_owned({**mine, "created": "wrong"}))

    def test_emulator_command_preserves_audio_and_local_avd(self):
        lab = self.load()
        cmd = lab.emulator_argv("phone", 6000, "auto")
        self.assertIn("-no-metrics", cmd)
        self.assertIn("-no-snapshot", cmd)
        self.assertNotIn("-no-audio", cmd)
        self.assertEqual(cmd[cmd.index("-ports") + 1], "6000,6001")
        self.assertEqual(cmd[cmd.index("-camera-back") + 1], "none")
        self.assertEqual(cmd[cmd.index("-crash-report-mode") + 1], "disabled")
        self.assertEqual(cmd[cmd.index("-memory") + 1], "4096")
        self.assertNotIn("--force", lab.avdmanager_argv("create", "avd"))
        self.assertIn("com.android.sdklib.tool.AvdManagerCli", lab.avdmanager_argv("list", "device"))

    def test_listener_ownership_observed_from_os(self):
        lab = self.load()
        import socket
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            sock.listen()
            port = sock.getsockname()[1]
            self.assertIn(os.getpid(), lab.listener_pids(port))

    def test_owned_child_cleanup_and_repeat_are_safe(self):
        lab = self.load()
        import subprocess
        import sys
        child = subprocess.Popen([sys.executable, "-c", "import sys; sys.stdin.read()"],
                                 stdin=subprocess.PIPE)
        try:
            identity = lab.process_identity(child.pid)
            self.assertTrue(lab.same_process(identity))
            self.assertEqual(lab.terminate_owned(identity), child.pid)
            child.wait(timeout=10)
            self.assertFalse(lab.same_process(identity))
            self.assertIsNone(lab.terminate_owned(identity))
        finally:
            if child.poll() is None:
                child.kill()
                child.wait(timeout=10)
            child.stdin.close()

    def test_job_owns_grandchild_and_does_not_kill_unrelated_process(self):
        lab = self.load()
        import subprocess
        import sys
        unrelated = subprocess.Popen([sys.executable, "-c", "import sys;sys.stdin.read()"], stdin=subprocess.PIPE)
        code = ("import subprocess,sys; p=subprocess.Popen([sys.executable,'-c',"
                "'import sys;sys.stdin.read()'],stdin=subprocess.PIPE);"
                "print(p.pid,flush=True);sys.stdin.read()")
        try:
            with lab.OwnedJob() as job:
                child = job.spawn([sys.executable, "-u", "-c", code],
                                  stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
                try:
                    grandchild_pid = int(child.stdout.readline())
                    self.assertIn(grandchild_pid, job.pids())
                    grandchild = lab.process_identity(grandchild_pid)
                    job.terminate()
                    child.wait(timeout=10)
                    self.assertFalse(lab.same_process(grandchild))
                    self.assertIsNone(unrelated.poll())
                finally:
                    child.stdin.close()
                    child.stdout.close()
        finally:
            unrelated.stdin.close()
            unrelated.wait(timeout=10)

    @contextmanager
    def status_fixture(self, status="ready"):
        """Synthetic identities/listeners; never query or change the retained live lab."""
        lab = self.load()
        import json
        import tempfile
        from types import SimpleNamespace
        from unittest.mock import patch
        state = {"root": str(lab.ROOT), "run_id": "status-fixture", "status": status,
                 "serial": "emulator-6000", "console_port": 6000, "adb_port": 5041,
                 "supervisor": {"pid": 101, "created": "1", "exe": "fixture-python.exe"},
                 "adb": {"pid": 102, "created": "2", "exe": "fixture-adb.exe"},
                 "emulator_processes": [{"pid": 103, "created": "3", "exe": "fixture-qemu.exe"}]}
        identities = {i["pid"]: dict(i) for i in
                      [state["supervisor"], state["adb"], *state["emulator_processes"]]}
        bindings = {5041: [{"pid": 102, "address": "127.0.0.1"}],
                    6000: [{"pid": 103, "address": "127.0.0.1"}]}
        def response(cmd, **kwargs):
            return SimpleNamespace(stdout="1\n" if cmd[-1] == "sys.boot_completed" else "device\n")
        with tempfile.TemporaryDirectory(dir=lab.LAB / "tmp") as folder:
            path = Path(folder) / "state.json"
            before = (json.dumps(state, indent=2) + "\n").encode("utf-8")
            path.write_bytes(before)
            with patch.object(lab, "STATE", path), patch.object(
                    lab, "process_identity", side_effect=identities.get), patch.object(
                    lab, "listener_bindings", side_effect=lambda port: bindings.get(port, [])), patch.object(
                    lab, "run", side_effect=response) as run, patch.object(
                    lab, "save_json", side_effect=AssertionError("status must not write state")), patch.object(
                    lab, "cleanup", side_effect=AssertionError("status must not clean up")), patch.object(
                    lab, "terminate_owned", side_effect=AssertionError("status must not terminate")):
                try:
                    yield lab, state, identities, bindings, run
                finally:
                    self.assertEqual(path.read_bytes(), before, "status changed persisted owned state")

    def test_status_rejects_ready_when_supervisor_is_dead_even_without_probe(self):
        for probe in (False, True):
            with self.subTest(probe=probe), self.status_fixture() as (lab, state, identities, bindings, run):
                identities.pop(state["supervisor"]["pid"])
                result = lab.status(probe=probe)
                self.assertEqual(result["status"], "unhealthy")
                self.assertFalse(result["supervisor_alive"])
                run.assert_not_called()

    def test_status_requires_live_identity_and_listener_ownership_without_probe(self):
        cases = ("adb-dead", "emulator-dead", "adb-pid-reused", "emulator-pid-reused",
                 "adb-missing", "adb-foreign", "adb-extra", "adb-nonloopback",
                 "console-missing", "console-foreign", "console-extra")
        for case in cases:
            with self.subTest(case=case), self.status_fixture() as (lab, state, identities, bindings, run):
                if case.endswith("dead"):
                    identities.pop(102 if case.startswith("adb") else 103)
                elif case.endswith("pid-reused"):
                    identities[102 if case.startswith("adb") else 103]["created"] = "reused"
                else:
                    port = 5041 if case.startswith("adb") else 6000
                    if case.endswith("missing"):
                        bindings[port] = []
                    elif case.endswith("foreign"):
                        bindings[port] = [{"pid": 999, "address": "127.0.0.1"}]
                    elif case.endswith("extra"):
                        bindings[port].append({"pid": 999, "address": "127.0.0.1"})
                    else:
                        bindings[port][0]["address"] = "0.0.0.0"
                result = lab.status(probe=False)
                self.assertEqual(result["status"], "unhealthy")
                self.assertEqual(result["stored_status"], "ready")
                run.assert_not_called()

    def test_status_requires_successful_live_boot_and_device_state(self):
        from types import SimpleNamespace
        for boot, device_state in (("0", "device"), ("", "device"), ("1", "offline"),
                                   ("1", "unauthorized"), ("1", "")):
            with self.subTest(boot=boot, device_state=device_state), self.status_fixture() as (
                    lab, state, identities, bindings, run):
                run.side_effect = lambda cmd, **kwargs: SimpleNamespace(
                    stdout=boot if cmd[-1] == "sys.boot_completed" else device_state)
                result = lab.status(probe=True)
                self.assertEqual(result["status"], "unhealthy")
                self.assertEqual(result["stored_status"], "ready")
                self.assertEqual(result["live_boot_completed"], boot)
                self.assertEqual(result["live_device_state"], device_state)
                self.assertIn("live_probe_error", result)

    def test_status_keeps_ready_with_owned_listeners_and_optional_successful_probe(self):
        from unittest.mock import call
        for probe in (False, True):
            with self.subTest(probe=probe), self.status_fixture() as (lab, state, identities, bindings, run):
                result = lab.status(probe=probe)
                self.assertEqual(result["status"], "ready")
                self.assertEqual(result["stored_status"], "ready")
                self.assertNotIn("live_probe_error", result)
                if probe:
                    self.assertEqual(result["live_boot_completed"], "1")
                    self.assertEqual(result["live_device_state"], "device")
                    self.assertEqual(run.call_args_list, [
                        call(lab.adb_argv(state, "shell", "getprop", "sys.boot_completed"), timeout=5, check=True),
                        call(lab.adb_argv(state, "get-state"), timeout=5, check=True)])
                else:
                    run.assert_not_called()
                    self.assertNotIn("live_boot_completed", result)

    def test_status_preserves_nonready_lifecycle_states(self):
        for stored_status in ("starting", "stopped"):
            for probe in (False, True):
                with self.subTest(status=stored_status, probe=probe), self.status_fixture(stored_status) as (
                        lab, state, identities, bindings, run):
                    identities.clear()
                    bindings.clear()
                    result = lab.status(probe=probe)
                    self.assertEqual(result["status"], stored_status)
                    self.assertEqual(result["stored_status"], stored_status)
                    run.assert_not_called()

    def test_status_reports_ready_probe_errors_without_writing_state(self):
        import subprocess
        for error in (RuntimeError("device offline"), subprocess.TimeoutExpired(["fixture-adb"], 5)):
            with self.subTest(error=type(error).__name__), self.status_fixture() as (
                    lab, state, identities, bindings, run):
                run.side_effect = error
                result = lab.status(probe=True)
                self.assertEqual(result["status"], "unhealthy")
                self.assertEqual(result["stored_status"], "ready")
                self.assertEqual(result["live_probe_error"], str(error))

    def test_status_not_started_never_probes_or_publishes(self):
        lab = self.load()
        import tempfile
        from unittest.mock import patch
        with tempfile.TemporaryDirectory(dir=lab.LAB / "tmp") as folder:
            path = Path(folder) / "missing-state.json"
            with patch.object(lab, "STATE", path), patch.object(lab, "run") as run, patch.object(
                    lab, "save_json") as save, patch.object(lab, "cleanup") as cleanup:
                self.assertEqual(lab.status(probe=True), {"status": "not-started", "state": str(path)})
                run.assert_not_called()
                save.assert_not_called()
                cleanup.assert_not_called()
                self.assertFalse(path.exists())

    def test_status_reports_offline_probe_instead_of_hiding_owned_state(self):
        lab = self.load()
        from unittest.mock import patch
        state = {"status": "starting", "serial": "emulator-6000", "console_port": 6000,
                 "supervisor": lab.process_identity(os.getpid()), "adb_port": 5041}
        with patch.object(lab, "STATE", Path(__file__)), patch.object(lab, "load_state", return_value=state), patch.object(
                lab, "device", side_effect=RuntimeError("device offline")):
            result = lab.status(probe=True)
        self.assertEqual(result["status"], "starting")
        self.assertEqual(result["live_probe_error"], "device offline")

    def test_stale_stop_cannot_overwrite_a_new_run(self):
        lab = self.load()
        from unittest.mock import patch
        from contextlib import nullcontext
        stale = {"run_id": "A"}
        new = {"run_id": "B"}
        with patch.object(lab, "STATE", Path(__file__)), patch.object(
                lab, "load_state", side_effect=[stale, new]), patch.object(
                lab, "same_process", return_value=False), patch.object(
                lab, "cleanup") as cleanup, patch.object(lab, "status", return_value={}), patch.object(
                lab, "lifecycle_lock", return_value=nullcontext()) as lock:
            with self.assertRaisesRegex(RuntimeError, "generation changed"):
                lab.stop()
            cleanup.assert_not_called()
            lock.assert_called_once()

    def test_cleanup_verifies_owned_job_empty_and_records_stopped(self):
        lab = self.load()
        from unittest.mock import patch
        import subprocess
        import sys
        import tempfile
        import json
        with tempfile.TemporaryDirectory(dir=lab.LAB / "tmp") as folder, lab.OwnedJob() as job:
            child = job.spawn([sys.executable, "-c", "import sys;sys.stdin.read()"], stdin=subprocess.PIPE)
            state = {"status": "starting", "emulator_processes": [lab.process_identity(child.pid)]}
            try:
                path = Path(folder) / "state.json"
                with patch.object(lab, "STATE", path), patch.object(
                        lab, "device", side_effect=RuntimeError("not an emulator fixture")):
                    lab.cleanup(state, job)
                child.wait(timeout=10)
                self.assertEqual(job.pids(), [])
                stored = json.loads(path.read_text())
                self.assertEqual(stored["status"], "stopped")
                self.assertEqual(stored["cleanup_remaining_pids"], [])
            finally:
                child.stdin.close()

    def test_cleanup_waits_for_exit_identity_and_keeps_failure_visible(self):
        lab = self.load()
        from unittest.mock import Mock, patch
        import itertools
        import json
        import tempfile
        identity = {"pid": 424242, "created": "fixture", "exe": "fixture"}
        job = Mock()
        job.pids.return_value = []
        with tempfile.TemporaryDirectory(dir=lab.LAB / "tmp") as folder:
            path = Path(folder) / "state.json"
            with self.subTest("process exit record can lag the empty job"):
                state = {"status": "starting", "emulator_processes": [identity]}
                with patch.object(lab, "STATE", path), patch.object(
                        lab, "device", side_effect=RuntimeError("fixture only")), patch.object(
                        lab, "same_process", side_effect=[True, False]), patch.object(lab.time, "sleep") as sleep:
                    lab.cleanup(state, job)
                    sleep.assert_called_once_with(0.05)
                stored = json.loads(path.read_text())
                self.assertEqual(stored["status"], "stopped")
                self.assertEqual(stored["cleanup_remaining_pids"], [])
            with self.subTest("a persistent process must still fail"):
                state = {"status": "starting", "emulator_processes": [identity]}
                with patch.object(lab, "STATE", path), patch.object(
                        lab, "device", side_effect=RuntimeError("fixture only")), patch.object(
                        lab, "same_process", return_value=True), patch.object(
                        lab.time, "monotonic", side_effect=itertools.count(0, 11)):
                    with self.assertRaisesRegex(RuntimeError, "some owned processes remain"):
                        lab.cleanup(state, job)
                stored = json.loads(path.read_text())
                self.assertNotEqual(stored["status"], "stopped")
                self.assertEqual(stored["cleanup_remaining_pids"], [identity["pid"]])

    def test_stop_uses_exact_owned_control_listener(self):
        lab = self.load()
        from unittest.mock import patch
        import socket
        import threading
        received = []
        with socket.socket() as server:
            server.bind(("127.0.0.1", 0))
            server.listen(1)
            server.settimeout(5)
            state = {"supervisor": lab.process_identity(os.getpid()),
                     "control_port": server.getsockname()[1]}
            def serve():
                conn, _ = server.accept()
                with conn:
                    conn.settimeout(5)
                    received.append(conn.recv(64))
                    conn.sendall(b"STOPPED\n")
            thread = threading.Thread(target=serve)
            thread.start()
            try:
                with patch.object(lab, "STATE", Path(__file__)), patch.object(
                        lab, "load_state", return_value=state), patch.object(
                        lab, "status", return_value={"status": "stopped"}), patch.object(lab, "cleanup") as cleanup:
                    self.assertEqual(lab.stop()["status"], "stopped")
                    cleanup.assert_not_called()
            finally:
                thread.join(timeout=10)
            self.assertEqual(received, [b"stop\n"])

    def test_stop_recovers_when_owned_supervisor_exits_before_ack(self):
        lab = self.load()
        from unittest.mock import patch
        from contextlib import nullcontext
        state = {"supervisor": {"pid": 123}, "control_port": 60000, "run_id": "A"}
        class Connection:
            def __enter__(self): return self
            def __exit__(self, *args): pass
            def settimeout(self, value): pass
            def sendall(self, data): pass
            def recv(self, count): return b""
        with patch.object(lab, "STATE", Path(__file__)), patch.object(
                lab, "load_state", return_value=state), patch.object(
                lab, "same_process", side_effect=[True, False, False]), patch.object(
                lab, "listener_pids", return_value={123}), patch.object(
                lab.socket, "create_connection", return_value=Connection()), patch.object(
                lab, "lifecycle_lock", return_value=nullcontext()), patch.object(
                lab, "cleanup") as cleanup, patch.object(lab, "status", return_value={"status": "stopped"}):
            self.assertEqual(lab.stop()["status"], "stopped")
            cleanup.assert_called_once_with(state)

    def test_server_listener_uses_supported_port_only_and_no_all_interfaces(self):
        lab = self.load()
        self.assertEqual(lab.server_argv()[1:], ["-L", "tcp:5041", "server", "nodaemon"])
        self.assertNotIn("-a", lab.server_argv())

    def test_windows_job_cleans_owned_processes(self):
        lab = self.load()
        import subprocess
        import sys
        with lab.OwnedJob() as job:
            child = job.spawn([sys.executable, "-c", "import sys;sys.stdin.read()"],
                              env=os.environ.copy(), cwd=lab.ROOT, stdin=subprocess.PIPE)
            try:
                self.assertIn(child.pid, job.pids())
                self.assertTrue(lab.same_process(lab.process_identity(child.pid)))
                job.terminate()
                child.wait(timeout=10)
                self.assertEqual(job.pids(), [])
            finally:
                child.stdin.close()

    def test_lifecycle_lock_excludes_competing_starts(self):
        lab = self.load()
        import tempfile
        with tempfile.TemporaryDirectory(dir=lab.LAB / "tmp") as folder:
            path = Path(folder) / "lock"
            with lab.lifecycle_lock(path):
                with self.assertRaises(RuntimeError):
                    with lab.lifecycle_lock(path):
                        self.fail("second owner acquired lifecycle lock")
            with lab.lifecycle_lock(path):
                pass


if __name__ == "__main__":
    unittest.main()
