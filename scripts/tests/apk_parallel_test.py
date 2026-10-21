"""Real filesystem regressions for bounded APK dependency I/O; not APK acceptance."""
import hashlib
import pathlib
import sys
import tempfile
import threading
import time
import unittest
from unittest import mock

SCRIPTS = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SCRIPTS))
import apk_build


class ParallelCaptureRegression(unittest.TestCase):
    def test_failed_capture_settles_admitted_writes_before_raising(self):
        with tempfile.TemporaryDirectory(prefix='apk-parallel-', dir=SCRIPTS.parent / '.cache') as tmp:
            root = pathlib.Path(tmp)
            names = [str(i).zfill(2) + '.js' for i in range(24)]
            for name in names:
                if name != '02.js':
                    (root / name).write_bytes(b'dependency')
            original = apk_build.write_new
            lock = threading.Lock()
            active = 0

            def observed_write(*args):
                nonlocal active
                with lock:
                    active += 1
                try:
                    time.sleep(0.02)
                    return original(*args)
                finally:
                    with lock:
                        active -= 1

            with mock.patch.object(apk_build, 'write_new', side_effect=observed_write):
                with self.assertRaisesRegex(apk_build.BuildError, 'Missing/nonregular input'):
                    apk_build.capture_files(root, root / 'snapshot', names)
                self.assertEqual(active, 0, 'A failed capture left background writers running')

    def test_hash_reads_overlap_with_same_guards_and_ordered_receipt(self):
        with tempfile.TemporaryDirectory(prefix='apk-parallel-', dir=SCRIPTS.parent / '.cache') as tmp:
            root = pathlib.Path(tmp)
            names = [str(i).zfill(2) + '.js' for i in range(24)]
            for name in names:
                (root / name).write_bytes(('dependency ' + name).encode())
            expected = {name: hashlib.sha256((root / name).read_bytes()).hexdigest() for name in names}
            original = apk_build.read_guarded
            lock = threading.Lock()
            active = peak = 0

            def observed_read(*args):
                nonlocal active, peak
                with lock:
                    active += 1
                    peak = max(peak, active)
                try:
                    time.sleep(0.02)
                    return original(*args)
                finally:
                    with lock:
                        active -= 1

            with mock.patch.object(apk_build, 'read_guarded', side_effect=observed_read):
                hashes = apk_build.hash_files(root, list(reversed(names)))
            self.assertGreater(peak, 1, 'Dependency verification still reads every file serially')
            self.assertLessEqual(peak, 8)
            self.assertEqual(active, 0)
            self.assertEqual(list(hashes), names)
            self.assertEqual(hashes, expected)

    def test_capture_overlaps_guarded_writes_with_at_most_eight_workers(self):
        with tempfile.TemporaryDirectory(prefix='apk-parallel-', dir=SCRIPTS.parent / '.cache') as tmp:
            root = pathlib.Path(tmp)
            names = ['input/' + str(i).zfill(2) + '.js' for i in range(24)]
            (root / 'input').mkdir()
            for name in names:
                (root / name).write_bytes(('dependency ' + name).encode())
            expected = {name: hashlib.sha256((root / name).read_bytes()).hexdigest() for name in names}
            original = apk_build.write_new
            lock = threading.Lock()
            active = peak = 0

            def observed_write(*args):
                nonlocal active, peak
                with lock:
                    active += 1
                    peak = max(peak, active)
                try:
                    time.sleep(0.02)  # Stand in for blocking Windows filesystem latency.
                    return original(*args)
                finally:
                    with lock:
                        active -= 1

            with mock.patch.object(apk_build, 'write_new', side_effect=observed_write):
                captured = apk_build.capture_files(root, root / 'snapshot', list(reversed(names)))
            self.assertGreater(peak, 1, 'Dependency capture still serializes every file')
            self.assertLessEqual(peak, 8)
            self.assertEqual(active, 0, 'Capture returned before its writes settled')
            self.assertEqual(list(captured), names)
            self.assertEqual(captured, expected)
            for name in names:
                self.assertEqual((root / 'snapshot' / name).read_bytes(), (root / name).read_bytes())


if __name__ == '__main__':
    unittest.main()
