"""Windows process ownership helpers (stdlib only; no PID-tree kill)."""
import contextlib
import ctypes
from ctypes import wintypes as W
import msvcrt
from pathlib import Path
import subprocess


@contextlib.contextmanager
def lifecycle_lock(path):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a+b") as stream:
        if stream.seek(0, 2) == 0:
            stream.write(b"\0")
            stream.flush()
        stream.seek(0)
        try:
            msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
        except OSError as exc:
            raise RuntimeError("lab lifecycle is already owned; refusing competing start/prepare") from exc
        try:
            yield
        finally:
            stream.seek(0)
            msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)


class Limits(ctypes.Structure):
    _fields_ = [("ProcessMemoryLimit", ctypes.c_size_t), ("JobMemoryLimit", ctypes.c_size_t),
                ("PeakProcessMemoryUsed", ctypes.c_size_t), ("PeakJobMemoryUsed", ctypes.c_size_t)]


class BasicLimits(ctypes.Structure):
    _fields_ = [("PerProcessUserTimeLimit", ctypes.c_longlong), ("PerJobUserTimeLimit", ctypes.c_longlong),
                ("LimitFlags", W.DWORD), ("MinimumWorkingSetSize", ctypes.c_size_t),
                ("MaximumWorkingSetSize", ctypes.c_size_t), ("ActiveProcessLimit", W.DWORD),
                ("Affinity", ctypes.c_size_t), ("PriorityClass", W.DWORD), ("SchedulingClass", W.DWORD)]


class IO(ctypes.Structure):
    _fields_ = [(name, ctypes.c_ulonglong) for name in ("ReadOperationCount", "WriteOperationCount",
                "OtherOperationCount", "ReadTransferCount", "WriteTransferCount", "OtherTransferCount")]


class ExtendedLimits(ctypes.Structure):
    _fields_ = [("BasicLimitInformation", BasicLimits), ("IoInfo", IO), ("Memory", Limits)]


class ThreadEntry(ctypes.Structure):
    _fields_ = [(name, W.DWORD) for name in ("dwSize", "cntUsage", "th32ThreadID", "th32OwnerProcessID")] + [
        ("tpBasePri", W.LONG), ("tpDeltaPri", W.LONG), ("dwFlags", W.DWORD)]


class OwnedJob:
    """Assign suspended children before execution; all descendants remain job-owned.

    KILL_ON_JOB_CLOSE also cleans grandchildren when the supervisor is interrupted.
    The handle is not inherited; no CIM snapshot or reusable PID establishes authority.
    """
    def __init__(self):
        self.api = ctypes.WinDLL("kernel32", use_last_error=True)
        for name in ("CreateJobObjectW", "CreateToolhelp32Snapshot", "OpenThread"):
            getattr(self.api, name).restype = W.HANDLE
        self.api.CreateJobObjectW.argtypes = [ctypes.c_void_p, W.LPCWSTR]
        self.api.CloseHandle.argtypes = [W.HANDLE]
        self.api.SetInformationJobObject.argtypes = [W.HANDLE, ctypes.c_int, ctypes.c_void_p, W.DWORD]
        self.api.AssignProcessToJobObject.argtypes = [W.HANDLE, W.HANDLE]
        self.api.QueryInformationJobObject.argtypes = [W.HANDLE, ctypes.c_int, ctypes.c_void_p,
                                                       W.DWORD, ctypes.c_void_p]
        self.api.TerminateJobObject.argtypes = [W.HANDLE, W.UINT]
        self.api.CreateToolhelp32Snapshot.argtypes = [W.DWORD, W.DWORD]
        self.api.Thread32First.argtypes = [W.HANDLE, ctypes.POINTER(ThreadEntry)]
        self.api.Thread32Next.argtypes = [W.HANDLE, ctypes.POINTER(ThreadEntry)]
        self.api.OpenThread.argtypes = [W.DWORD, W.BOOL, W.DWORD]
        self.api.ResumeThread.argtypes = [W.HANDLE]
        self.api.ResumeThread.restype = W.DWORD
        self.handle = self.api.CreateJobObjectW(None, None)
        if not self.handle:
            raise ctypes.WinError(ctypes.get_last_error())
        info = ExtendedLimits()
        info.BasicLimitInformation.LimitFlags = 0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        if not self.api.SetInformationJobObject(self.handle, 9, ctypes.byref(info), ctypes.sizeof(info)):
            self.close()
            raise ctypes.WinError(ctypes.get_last_error())

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()

    def close(self):
        if self.handle:
            self.api.CloseHandle(self.handle)
            self.handle = None

    def terminate(self):
        if not self.api.TerminateJobObject(self.handle, 0):
            raise ctypes.WinError(ctypes.get_last_error())

    def pids(self):
        # JOBOBJECT_BASIC_PROCESS_ID_LIST: two DWORDs then ULONG_PTR entries.
        buf = ctypes.create_string_buffer(65536)
        if not self.api.QueryInformationJobObject(self.handle, 3, buf, len(buf), None):
            raise ctypes.WinError(ctypes.get_last_error())
        count = W.DWORD.from_buffer(buf, 4).value
        return list((ctypes.c_size_t * count).from_buffer(buf, 8))

    def spawn(self, argv, **kwargs):
        child = subprocess.Popen(argv, creationflags=0x00000004, **kwargs)  # CREATE_SUSPENDED
        try:
            if not self.api.AssignProcessToJobObject(self.handle, int(child._handle)):
                raise ctypes.WinError(ctypes.get_last_error())
            snapshot = self.api.CreateToolhelp32Snapshot(4, 0)  # TH32CS_SNAPTHREAD
            if snapshot == ctypes.c_void_p(-1).value:
                raise ctypes.WinError(ctypes.get_last_error())
            try:
                entry = ThreadEntry()
                entry.dwSize = ctypes.sizeof(entry)
                found = self.api.Thread32First(snapshot, ctypes.byref(entry))
                resumed = False
                while found:
                    if entry.th32OwnerProcessID == child.pid:
                        thread = self.api.OpenThread(2, False, entry.th32ThreadID)
                        if not thread:
                            raise ctypes.WinError(ctypes.get_last_error())
                        try:
                            if self.api.ResumeThread(thread) == 0xffffffff:
                                raise ctypes.WinError(ctypes.get_last_error())
                            resumed = True
                        finally:
                            self.api.CloseHandle(thread)
                        break
                    found = self.api.Thread32Next(snapshot, ctypes.byref(entry))
                if not resumed:
                    raise RuntimeError("owned suspended child has no primary thread")
            finally:
                self.api.CloseHandle(snapshot)
            return child
        except BaseException:
            child.kill()  # Exact live Popen handle, still suspended or job-owned.
            child.wait(timeout=10)
            raise
