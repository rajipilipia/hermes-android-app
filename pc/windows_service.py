"""Fail-closed, one-shot adapter watchdog. Never stops any process.

CLI: python -B -m pc.windows_service --config FILE ensure|status
Only the approved project runtime can be started; original Dashboard discovery
continues to use the upstream working directory. Config/state/log contain no
credentials, and backend output is never captured. The operator must own and
protect config/source and their parent directories against concurrent mutation.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

from .catalog import SOURCE_COMMIT
from .production_policy import _canonical_path, _closed_json, _invalid_constant, _unlinked


def source_digest(projectRoot):
    """SHA256 of sorted top-level pc/*.py and pc/*.json names and bytes.

    Each record is uint64 big-endian name length, UTF-8 relative POSIX name,
    uint64 big-endian content length, then raw content. No tests/cache traversal.
    Links/reparse source files and directories are refused, not followed.
    """
    root = _canonical_path(str(projectRoot))
    folder = _canonical_path(str(root / 'pc'))
    digest = hashlib.sha256()
    files = sorted((p for p in folder.iterdir() if p.suffix.casefold() in {'.py', '.json'}),
                   key=lambda p: p.name)
    if not files:
        raise ValueError('source unavailable')
    for path in files:
        _unlinked(path)
        if not path.is_file():
            raise ValueError('source unavailable')
        name = path.relative_to(root).as_posix().encode('utf-8')
        data = path.read_bytes()
        digest.update(len(name).to_bytes(8, 'big'))
        digest.update(name)
        digest.update(len(data).to_bytes(8, 'big'))
        digest.update(data)
    return digest.hexdigest()


_REQUIRED = frozenset('schemaVersion projectRoot upstream manifest python pythonPath argv port '
                      'bindHost home stateFile logFile updateMarker sourceDigest sourceCommit'.split())
_OPTIONAL = frozenset({'startupGraceSeconds', 'readyTimeoutSeconds'})
_ESSENTIAL_ENV = frozenset('PATH PATHEXT SYSTEMROOT WINDIR COMSPEC TEMP TMP TMPDIR USERPROFILE '
    'HOMEDRIVE HOMEPATH APPDATA LOCALAPPDATA PROGRAMDATA PROGRAMFILES PROGRAMFILES(X86) '
    'ALLUSERSPROFILE USERNAME USERDOMAIN'.split())


UPDATE_MARKER_NAME = '.hermes-update-in-progress'
_MANAGED_PARTS = ('installs', '[0-9a-f]{16}', 'environments', '[0-9a-f]{32}',
                  'venv', 'Lib', 'site-packages')


def _managed_site_packages(home, folder):
    """True only for home/installs/<16 hex>/environments/<32 hex>/venv/Lib/site-packages."""
    parts = Path(folder).relative_to(home).parts
    return (len(parts) == len(_MANAGED_PARTS)
            and all(re.fullmatch(pattern, part, re.IGNORECASE) is not None
                    for pattern, part in zip(_MANAGED_PARTS, parts)))


@dataclass(frozen=True)
class Config:
    schemaVersion: int
    projectRoot: str
    upstream: str
    manifest: str
    python: str
    pythonPath: tuple[str, ...]
    argv: tuple[str, ...]
    port: int
    bindHost: str
    home: str
    stateFile: str
    logFile: str
    updateMarker: str
    sourceDigest: str
    sourceCommit: str
    startupGraceSeconds: int = 300
    readyTimeoutSeconds: int = 120

    @property
    def lockFile(self):
        return self.stateFile + '.lock'


def _json_file(path, maximum=65536):
    _unlinked(Path(path))
    with Path(path).open('rb') as stream:
        raw = stream.read(maximum + 1)
    if len(raw) > maximum:
        raise ValueError('oversize metadata')
    return json.loads(raw.decode('utf-8'), object_pairs_hook=_closed_json,
                      parse_constant=_invalid_constant)


def _hex(value, length):
    return isinstance(value, str) and re.fullmatch('[0-9a-f]{' + str(length) + '}', value) is not None


def _argv(value, config):
    if not isinstance(value, list) or any(not isinstance(v, str) for v in value):
        raise ValueError('exact argv required')
    # No arbitrary Python flags, scripts, abbreviated arguments or duplicate flags.
    if not value or value[0] != config['python']:
        raise ValueError('exact executable required')
    index = 1
    flags = []
    while index < len(value) and value[index] in {'-B', '-u'}:
        flags.append(value[index])
        index += 1
    if '-B' not in flags or len(set(flags)) != len(flags) or value[index:index + 2] != ['-m', 'pc.production_runtime']:
        raise ValueError('only no-bytecode production runtime required')
    index += 2
    seen = {}
    while index < len(value):
        key = value[index]
        if key in seen:
            raise ValueError('duplicate argument')
        if key in {'--isolated', '--skip-build'}:
            seen[key] = True
            index += 1
        elif key in {'--upstream', '--manifest', '--mode', '--host', '--port'} and index + 1 < len(value):
            seen[key] = value[index + 1]
            index += 2
        else:
            raise ValueError('unapproved runtime argument')
    expected = {'--upstream': config['upstream'], '--manifest': config['manifest'],
                '--host': config['bindHost'], '--port': str(config['port']), '--isolated': True}
    if (seen.get('--mode') not in {'serve', 'dashboard'}
            or any(seen.get(k) != v for k, v in expected.items())
            or set(seen) - set(expected) - {'--mode', '--skip-build'}):
        raise ValueError('runtime arguments differ from config')
    return tuple(value)


def load_config(path):
    """Closed, bounded JSON configuration. Never loads profile/auth/history data.

    Mutable control files must be under projectRoot/.cache, with existing parent
    directories, JSON state and a .log diagnostic sink. They cannot alias config,
    policy, source, upstream or the original home. updateMarker must be exactly
    home/.hermes-update-in-progress (read only, never created or removed here).
    Paths use exact canonical native spelling; Python search dirs are ordered,
    explicit, begin with projectRoot, include upstream and may add the one exact
    managed site-packages directory under home (see _managed_site_packages).
    """
    try:
        path = _canonical_path(str(path), directory=False)
        value = _json_file(path)
        if (not isinstance(value, dict) or not _REQUIRED <= set(value)
                or set(value) - _REQUIRED - _OPTIONAL):
            raise ValueError('closed service config required')
        if type(value['schemaVersion']) is not int or value['schemaVersion'] != 1:
            raise ValueError('schemaVersion must be integer 1')
        if type(value['port']) is not int or not 1 <= value['port'] <= 65535:
            raise ValueError('fixed port required')
        if value['bindHost'] not in {'127.0.0.1', '0.0.0.0'}:
            raise ValueError('IPv4 local health capable bind required')
        if not _hex(value['sourceDigest'], 64) or value['sourceCommit'] != SOURCE_COMMIT:
            raise ValueError('approved source pin required')
        for key, default in (('startupGraceSeconds', 300), ('readyTimeoutSeconds', 120)):
            value.setdefault(key, default)
            if type(value[key]) is not int or not 1 <= value[key] <= (3600 if key == 'startupGraceSeconds' else 300):
                raise ValueError('bounded startup timeout required')
        if value['readyTimeoutSeconds'] > value['startupGraceSeconds']:
            raise ValueError('readiness exceeds startup grace')
        for key in ('projectRoot', 'upstream', 'home'):
            _canonical_path(value[key])
        for key in ('python', 'manifest'):
            _canonical_path(value[key], directory=False)
        project, upstream, home = (Path(value[k]) for k in ('projectRoot', 'upstream', 'home'))
        if any(a.is_relative_to(b) or b.is_relative_to(a)
               for a, b in ((project, upstream), (project, home), (upstream, home))):
            raise ValueError('project, upstream and home must be disjoint')
        paths = value['pythonPath']
        if (not isinstance(paths, list) or not paths or paths[0] != str(project)
                or str(upstream) not in paths or any(not isinstance(p, str) for p in paths)
                or len(set(paths)) != len(paths)):
            raise ValueError('explicit ordered Python search directories required')
        for item in paths:
            folder = _canonical_path(item)
            if ';' in item:
                raise ValueError('unsafe Python search directory')
            # Only the exact managed dependency directory may live under the original
            # home; profiles, sessions, secrets and every other home path stay refused.
            if folder.is_relative_to(home) and not _managed_site_packages(home, folder):
                raise ValueError('unsafe Python search directory')
        if sum(1 for item in paths if Path(item).is_relative_to(home)) > 1:
            raise ValueError('at most one managed dependency directory')
        value['argv'] = _argv(value['argv'], value)
        value['pythonPath'] = tuple(paths)
        # The REAL native-update marker; it is only read, never written.
        if value['updateMarker'] != str(home / UPDATE_MARKER_NAME):
            raise ValueError('real home update marker required')
        _canonical_path(value['updateMarker'], directory=False, existing=Path(value['updateMarker']).exists())
        controls = [Path(value[key]) for key in ('stateFile', 'logFile')]
        lock = Path(value['stateFile'] + '.lock')
        reserved = {path, Path(value['manifest']), Path(value['python'])}
        if len(set(controls + [lock])) != 3 or reserved.intersection(controls + [lock]):
            raise ValueError('control paths must be distinct')
        if Path(value['stateFile']).suffix != '.json' or Path(value['logFile']).suffix != '.log':
            raise ValueError('JSON state and static .log control files required')
        for item in controls + [lock]:
            _canonical_path(str(item), directory=False, existing=item.exists())
            _canonical_path(str(item.parent))
            if not item.is_relative_to(project / '.cache'):
                raise ValueError('control files must remain in project .cache')
        return Config(**value)
    except (OSError, TypeError, UnicodeError, RecursionError, RuntimeError):
        raise ValueError('service config cannot be verified') from None


def child_environment(config, generation, digest, inherited=None):
    """Allowlist OS essentials, not arbitrary inherited profile/safety/provider env."""
    inherited = os.environ if inherited is None else inherited
    env = {key.upper(): value for key, value in inherited.items() if key.upper() in _ESSENTIAL_ENV}
    env.update(PYTHONPATH=';'.join(config.pythonPath), HERMES_HOME=config.home,
               HERMES_DISABLE_LAZY_INSTALLS='1', PYTHONDONTWRITEBYTECODE='1', PYTHONUNBUFFERED='1',
               HERMES_ANDROID_ADAPTER_GENERATION=generation,
               HERMES_ANDROID_ADAPTER_SOURCE_SHA256=digest)
    return env


# These categories, not exception messages/health bodies, are the only diagnostics.
STATUSES = frozenset({'healthy', 'updating', 'locked', 'missing', 'foreign', 'degraded',
    'booting', 'stalled', 'source-drift', 'invalid-state', 'inspection-failed',
    'launch-failed', 'child-exited', 'control-error', 'invalid-config'})


@dataclass(frozen=True)
class Result:
    status: str
    exit_code: int


@dataclass(frozen=True)
class ProcessIdentity:
    pid: int
    created: float
    executable: str
    argv: tuple[str, ...]


class LockBusy(Exception):
    pass


def _control_file(path):
    path = _canonical_path(str(path), directory=False, existing=Path(path).exists())
    _canonical_path(str(path.parent))
    if path.exists() and path.stat().st_nlink != 1:
        raise ValueError('linked control file forbidden')
    return path


@contextmanager
def supervisor_lock(path):
    """Nonblocking cross-process check/start/readiness lock; never unlink it."""
    path = _control_file(path)
    with path.open('a+b') as stream:
        if stream.tell() == 0:
            stream.write(b'0')
            stream.flush()
        stream.seek(0)
        try:
            if os.name == 'nt':
                import msvcrt
                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            raise LockBusy() from None
        try:
            yield stream
        finally:
            stream.seek(0)
            if os.name == 'nt':
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(stream.fileno(), fcntl.LOCK_UN)


def _state(config):
    import math
    path = _control_file(config.stateFile)
    if not path.exists():
        return None
    value = _json_file(path)
    required = {'schemaVersion', 'pid', 'created', 'generation', 'sourceDigest'}
    if (not isinstance(value, dict) or not required <= set(value)
            or set(value) - required - {'lastStatus'}
            or type(value['schemaVersion']) is not int or value['schemaVersion'] != 1
            or type(value['pid']) is not int or not 0 < value['pid'] <= 0xffffffff
            or type(value['created']) not in {int, float} or not math.isfinite(value['created'])
            or value['created'] <= 0 or not _hex(value['sourceDigest'], 64)
            or ('lastStatus' in value and value['lastStatus'] not in STATUSES)):
        raise ValueError('invalid state')
    if not _hex(value['generation'], 32):
        raise ValueError('invalid generation')
    return value


def _write_state(config, value):
    import tempfile
    path = _control_file(config.stateFile)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=path.parent,
                                         prefix=path.name + '.', suffix='.tmp', delete=False) as stream:
            temporary = Path(stream.name)
            json.dump(value, stream, sort_keys=True, allow_nan=False)
            stream.write('\n')
            stream.flush()
            os.fsync(stream.fileno())
        _control_file(path)
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def _record(config, status, state, backend):
    """One timestamp + fixed category per transition; never backend/raw output."""
    from datetime import datetime, timezone
    if status not in STATUSES:
        raise ValueError('unknown status')
    path = _control_file(config.logFile)
    previous = None
    if path.exists():
        with path.open('rb') as stream:
            stream.seek(max(0, path.stat().st_size - 1024))
            lines = stream.read(1024).splitlines()
        if lines:
            try:
                previous = json.loads(lines[-1]).get('status')
            except (ValueError, AttributeError):
                pass
    if previous != status:
        record = {'timestamp': datetime.fromtimestamp(backend.wall_time(), timezone.utc).isoformat(),
                  'status': status}
        with path.open('a', encoding='utf-8', newline='\n') as stream:
            stream.write(json.dumps(record, sort_keys=True) + '\n')
    if state is not None and state.get('lastStatus') != status:
        state['lastStatus'] = status
        _write_state(config, state)


def _owned(config, state, process):
    return (state is not None and process is not None and process.pid == state['pid']
            and process.created == state['created'] and process.executable == config.python
            and tuple(process.argv) == config.argv)


def _healthy(config, state, body):
    if not isinstance(body, dict) or body.get('ok') is not True or body.get('auth_required') is not True:
        return False
    meta = body.get('androidAdapter')
    return (isinstance(meta, dict) and type(meta.get('schemaVersion')) is int
            and meta.get('schemaVersion') == 1 and meta.get('ready') is True
            and meta.get('generation') == state['generation']
            and meta.get('sourceCommit') == config.sourceCommit
            and meta.get('sourceDigest') == config.sourceDigest)


def _observe(config, state, backend, health_timeout=2):
    """Return category. Port, PID/creation and generation all need independent proof."""
    pids = backend.listeners(config.port)
    process = backend.process(state['pid']) if state is not None else None
    if process is not None and process.created != state['created']:
        # The recorded PID now belongs to a different (reused) process: the
        # recorded incarnation is demonstrably gone, so it is not "foreign".
        # A listener, if any, still fails the identity checks below.
        if not pids:
            process = None
    if pids:
        if state is None or pids != {state['pid']} or not _owned(config, state, process):
            return 'foreign'
        if state['sourceDigest'] != config.sourceDigest:
            return 'degraded'
        body = backend.health(config.port, health_timeout)
        # Re-observe after HTTP so PID reuse/listener replacement cannot pass.
        if (backend.listeners(config.port) != {state['pid']}
                or not _owned(config, state, backend.process(state['pid']))):
            return 'foreign'
        return 'healthy' if _healthy(config, state, body) else 'degraded'
    if process is not None:
        if not _owned(config, state, process):
            return 'foreign'
        if state['sourceDigest'] != config.sourceDigest:
            return 'degraded'
        age = backend.wall_time() - state['created']
        return 'booting' if 0 <= age <= config.startupGraceSeconds else 'stalled'
    return 'missing'


_FENCE = re.compile(rb'pending ([0-9a-f]{32}) ([0-9]+(?:\.[0-9]+)?)')
_FENCE_SKEW = 2.0


def _recover_fence(config, raw, backend):
    """Decide what a durable launch fence means. Returns (action, state).

    The fence is written BEFORE spawn, so it proves only "a launch may have
    happened". It is cleared when no process with the exact approved
    executable and argv started at or after the fence time exists (the old
    process is demonstrably gone: crash, reboot or failed spawn). Exactly one
    such process is adopted under the fenced generation; health still has to
    prove that generation. More than one, or unreadable inspection, holds.
    """
    match = _FENCE.fullmatch(raw.strip())
    generation, since = (match[1].decode('ascii'), float(match[2])) if match else (None, 0.0)
    found = [p for p in backend.find(config) if p.created >= since - _FENCE_SKEW]
    if not found:
        return 'clear', None
    if len(found) == 1 and generation is not None:
        child = found[0]
        return 'adopt', dict(schemaVersion=1, pid=child.pid, created=child.created,
                             generation=generation, sourceDigest=config.sourceDigest)
    return 'hold', None


def operate(config, command='ensure', *, backend=None):
    """One safe tick. No retries/restarts inside a tick, never terminate a process.

    status is read-only except acquiring/creating the retained lock file.
    An uncertain launch is fenced durably in the lock; a crash between spawn and
    state persistence cannot cause a duplicate launch. A later tick resolves the
    fence from process facts (see _recover_fence) instead of waiting for an
    operator, so a reboot or a vanished child never blocks recovery forever.
    """
    import uuid
    if command not in {'ensure', 'status'}:
        raise ValueError('unknown command')
    backend = SystemBackend() if backend is None else backend
    state = None

    def finish(status):
        if command == 'ensure':
            try:
                _record(config, status, state, backend)
            except (OSError, ValueError, OverflowError):
                return Result('control-error', 2)
        return Result(status, 0 if status in {'healthy', 'updating'} else 2)

    try:
        with supervisor_lock(config.lockFile) as lock:
            if Path(config.updateMarker).exists():
                return finish('updating')
            if source_digest(config.projectRoot) != config.sourceDigest:
                return finish('source-drift')
            try:
                state = _state(config)
            except (OSError, ValueError, TypeError, RecursionError, OverflowError):
                return finish('invalid-state')
            lock.seek(1)
            raw = lock.read()
            if raw:
                try:
                    action, adopted = _recover_fence(config, raw, backend)
                except (OSError, ValueError):
                    return finish('inspection-failed')
                if action == 'hold':
                    return finish('launch-failed')
                if action == 'adopt':
                    state = adopted
                if command == 'ensure':
                    try:
                        if action == 'adopt':
                            _write_state(config, state)
                        lock.seek(1)
                        lock.truncate()
                        lock.flush()
                        os.fsync(lock.fileno())
                    except (OSError, ValueError):
                        return finish('control-error')
            try:
                status = _observe(config, state, backend)
            except (OSError, ValueError):
                return finish('inspection-failed')
            if status != 'missing' or command == 'status':
                return finish(status)
            # Recheck source, marker, paths and listeners immediately before spawn.
            _control_file(config.stateFile)
            _control_file(config.logFile)
            if Path(config.updateMarker).exists():
                return finish('updating')
            if source_digest(config.projectRoot) != config.sourceDigest:
                return finish('source-drift')
            for name in ('projectRoot', 'upstream', 'home'):
                _canonical_path(getattr(config, name))
            for name in ('python', 'manifest'):
                _canonical_path(getattr(config, name), directory=False)
            for folder in config.pythonPath:
                _canonical_path(folder)
            if backend.listeners(config.port):
                return finish('foreign')
            generation = uuid.uuid4().hex
            # Fixed, credential-free crash fence. Clear only after durable PID state.
            lock.seek(1)
            lock.truncate()
            lock.write(b'pending %s %.6f' % (generation.encode('ascii'), backend.wall_time()))
            lock.flush()
            os.fsync(lock.fileno())
            try:
                child = backend.spawn(config, child_environment(config, generation, config.sourceDigest))
                state = dict(schemaVersion=1, pid=child.pid, created=child.created,
                             generation=generation, sourceDigest=config.sourceDigest)
                _write_state(config, state)
            except (OSError, ValueError):
                return finish('launch-failed')
            lock.seek(1)
            lock.truncate()
            lock.flush()
            os.fsync(lock.fileno())
            deadline = backend.monotonic() + config.readyTimeoutSeconds
            while True:
                if Path(config.updateMarker).exists():
                    return finish('updating')
                if source_digest(config.projectRoot) != config.sourceDigest:
                    return finish('source-drift')
                remaining = max(0, deadline - backend.monotonic())
                try:
                    status = _observe(config, state, backend, min(2, remaining) or 0.001)
                except (OSError, ValueError):
                    return finish('inspection-failed')
                if status not in {'booting', 'degraded'}:
                    return finish('child-exited' if status == 'missing' else status)
                remaining = deadline - backend.monotonic()
                if remaining <= 0:
                    return finish(status)
                backend.sleep(min(1, remaining))
    except LockBusy:
        return Result('locked', 2)
    except (OSError, ValueError):
        return Result('control-error', 2)


class SystemBackend:
    """Only process metadata and local health; no profile/environment inspection."""
    def listeners(self, port):
        import psutil
        try:
            # Include all interfaces/families: a different binding still blocks us.
            return {item.pid for item in psutil.net_connections(kind='tcp')
                    if item.status == psutil.CONN_LISTEN and item.laddr.port == port}
        except psutil.Error:
            raise OSError('listener inspection unavailable') from None

    def process(self, pid):
        import psutil
        try:
            process = psutil.Process(pid)
            created = process.create_time()
            executable, argv = process.exe(), tuple(process.cmdline())
            if not process.is_running() or process.create_time() != created:
                raise OSError('process changed')
            return ProcessIdentity(pid, created, executable, argv)
        except psutil.NoSuchProcess:
            return None
        except psutil.Error:
            raise OSError('process inspection unavailable') from None

    def find(self, config):
        """Live processes with the exact approved executable and argv (metadata only).

        A process of the same executable name that cannot be inspected fails
        closed (OSError); one that vanished mid-scan is simply gone.
        """
        import psutil
        name = Path(config.python).name.casefold()
        found = []
        for item in psutil.process_iter(['name']):
            try:
                if (item.info.get('name') or '').casefold() != name:
                    continue
                created = item.create_time()
                executable, argv = item.exe(), tuple(item.cmdline())
                if not item.is_running() or item.create_time() != created:
                    continue
            except psutil.NoSuchProcess:
                continue
            except psutil.Error:
                raise OSError('process inspection unavailable') from None
            if executable == config.python and argv == config.argv:
                found.append(ProcessIdentity(item.pid, created, executable, argv))
        return found

    def health(self, port, timeout):
        """Direct HTTPConnection, no proxies/redirects/auth, 64KiB + total deadline.

        A finite timer shuts down the connected socket, bounding slow header/body
        drips as well as ordinary blocking reads. It is cancelled/joined each call,
        not a lifetime supervision thread.
        """
        import http.client
        import socket
        import threading
        import time
        if timeout <= 0:
            return None
        timeout = min(timeout, 5)
        connection = http.client.HTTPConnection('127.0.0.1', port, timeout=timeout)
        timer, response = None, None
        deadline = time.monotonic() + timeout
        try:
            connection.connect()
            connected = connection.sock
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return None
            def expire():
                try:
                    connected.shutdown(socket.SHUT_RDWR)
                except OSError:
                    pass
            timer = threading.Timer(remaining, expire)
            timer.daemon = True
            timer.start()
            connection.request('GET', '/api/health', headers={'Connection': 'close', 'Accept': 'application/json'})
            response = connection.getresponse()
            if response.status != 200 or (response.length is not None and response.length > 65536):
                return None
            raw = response.read(65537)
            if len(raw) > 65536 or time.monotonic() > deadline:
                return None
            body = json.loads(raw.decode('utf-8'), object_pairs_hook=_closed_json,
                              parse_constant=_invalid_constant)
            return body if isinstance(body, dict) else None
        except (OSError, ValueError, http.client.HTTPException, UnicodeError, RecursionError):
            return None
        finally:
            if timer is not None:
                timer.cancel()
                timer.join()
            if response is not None:
                response.close()
            connection.close()

    def spawn(self, config, env):
        import psutil
        import subprocess
        options = dict(cwd=config.upstream, env=env, stdin=subprocess.DEVNULL,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, close_fds=True)
        if os.name == 'nt':
            options['creationflags'] = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
        else:
            options['start_new_session'] = True
        child = subprocess.Popen(list(config.argv), **options)
        try:
            created = psutil.Process(child.pid).create_time()
        except psutil.Error:
            # The durable pending fence blocks a second launch if observation fails.
            raise OSError('child creation time unavailable') from None
        return ProcessIdentity(child.pid, created, config.python, config.argv)

    @staticmethod
    def wall_time():
        import time
        return time.time()

    @staticmethod
    def monotonic():
        import time
        return time.monotonic()

    @staticmethod
    def sleep(seconds):
        import time
        time.sleep(seconds)


def main(argv=None):
    import argparse
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    parser.add_argument('--config', required=True)
    parser.add_argument('command', choices=('ensure', 'status'))
    args = parser.parse_args(argv)
    try:
        config = load_config(args.config)
    except (ValueError, OSError):
        result = Result('invalid-config', 2)
    else:
        try:
            result = operate(config, args.command)
        except ImportError:
            result = Result('inspection-failed', 2)
    print(json.dumps({'schemaVersion': 1, 'status': result.status}, sort_keys=True))
    return result.exit_code


if __name__ == '__main__':
    raise SystemExit(main())
