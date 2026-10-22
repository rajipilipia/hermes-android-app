"""Lifecycle tracer bullets; fixtures are local bytes and cache-owned subprocesses."""
import asyncio
import contextvars
import io
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch
from pc.addon import Downloads
from pc.catalog import CapabilityError
from pc.policy import Owner

ROOT = Path(__file__).resolve().parents[2]

class Transport:
    closed = False

class LifecycleRepairs(unittest.TestCase):
    def test_expiry_and_disconnect_close_without_more_client_traffic(self):
        with tempfile.TemporaryDirectory(dir=ROOT / '.cache') as directory:
            store = Downloads(directory)
            owner = Owner('lab', 'alice', 'default', 'A', (), frozenset({'read'}))
            transport = Transport()
            stream = io.BytesIO(b'fixture')
            try:
                store.put(owner, stream, 7, 'text/plain', transport)
                transport.closed = True
                deadline = time.monotonic() + 1
                while not stream.closed and time.monotonic() < deadline:
                    time.sleep(.01)
                self.assertTrue(stream.closed, 'disconnect retained stream without future traffic')
                transport.closed = False
                stream2 = io.BytesIO(b'expiry')
                with patch('pc.addon.DOWNLOAD_TTL', .03):
                    store.put(owner, stream2, 6, 'text/plain', transport)
                deadline = time.monotonic() + 1
                while not stream2.closed and time.monotonic() < deadline:
                    time.sleep(.01)
                self.assertTrue(stream2.closed, 'expiry retained stream without future traffic')
            finally:
                store.close()

    def test_pending_downloads_consume_quota_and_shutdown_refuses_late_put(self):
        with tempfile.TemporaryDirectory(dir=ROOT / '.cache') as directory:
            store = Downloads(directory)
            transport = Transport()
            owner = Owner('lab', 'alice', 'default', 'A', (), frozenset({'read'}))
            try:
                self.assertTrue(callable(getattr(store, 'reserve', None)), 'inflight spool reservation missing')
                reservations = [store.reserve(owner, transport) for _ in range(8)]
                with self.assertRaises(CapabilityError):
                    store.reserve(owner, transport)
                store.cancel(reservations.pop())
                store.reserve(owner, transport)
            finally:
                store.close()
            late = io.BytesIO(b'late')
            with self.assertRaises(CapabilityError):
                store.put(owner, late, 4, 'text/plain', transport)
            self.assertTrue(late.closed)

    def test_cancelled_blocking_work_settles_before_its_task_releases(self):
        import threading
        import pc.addon as addon
        self.assertTrue(callable(getattr(addon, 'settled_thread', None)), 'tracked blocking-service helper missing')
        async def scenario():
            started, finish = threading.Event(), threading.Event()
            def worker():
                started.set()
                finish.wait(2)
                return 'settled'
            task = asyncio.create_task(addon.settled_thread(worker))
            await asyncio.to_thread(started.wait, 1)
            task.cancel()
            await asyncio.sleep(.03)
            self.assertFalse(task.done(), 'cancelled task released while writer still executing')
            finish.set()
            with self.assertRaises(asyncio.CancelledError):
                await task
        asyncio.run(scenario())

    def test_concurrent_duplicate_write_refuses_while_uncertain_writer_settles(self):
        import threading
        from pc.addon import Adapter, settled_thread
        from pc.catalog import validate_call
        async def scenario():
            adapter = Adapter.__new__(Adapter)
            adapter._tasks = set()
            adapter._closed = False
            adapter._write_barrier = threading.Lock()
            adapter._slots = threading.BoundedSemaphore(8)
            adapter._admission_deadline = contextvars.ContextVar('fixture-admission', default=None)
            started, finish = threading.Event(), threading.Event()
            mutations = []
            def worker():
                started.set()
                finish.wait(2)
                mutations.append('one durable write')
            async def invoke(*args):
                await settled_thread(worker)
                return {'status': 200, 'body': {}}
            adapter.invoke = invoke
            call = validate_call({'operation': 'POST /api/fs/write-text', 'profile': 'default', 'body': {'path': 'a.txt', 'content': 'fixture'}})
            transport = Transport()
            owner = Owner('lab', 'alice', 'default', 'A', (), frozenset({'read'}))
            adapter._slots.acquire()
            first = asyncio.create_task(adapter._run_admitted(call, owner, transport))
            await asyncio.to_thread(started.wait, 1)
            first.cancel()
            await asyncio.sleep(.02)
            adapter._slots.acquire()
            with self.assertRaises(CapabilityError) as caught:
                await adapter._run_admitted(call, owner, transport)
            self.assertEqual(caught.exception.status, 409)
            self.assertTrue(adapter._write_barrier.locked())
            self.assertEqual(mutations, [])
            finish.set()
            with self.assertRaises(asyncio.CancelledError):
                await first
            self.assertEqual(mutations, ['one durable write'])
            self.assertFalse(adapter._write_barrier.locked())
            self.assertEqual(adapter._tasks, set())
            self.assertTrue(all(adapter._slots.acquire(False) for _ in range(8)))
        asyncio.run(scenario())

    def test_cancelled_asgi_stream_closes_inflight_spool(self):
        from pc.addon import Adapter
        from types import SimpleNamespace
        async def scenario(directory):
            entered = asyncio.Event()
            async def app(scope, receive, send):
                await send({'type': 'http.response.start', 'status': 200, 'headers': []})
                await send({'type': 'http.response.body', 'body': b'partial fixture', 'more_body': True})
                entered.set()
                await asyncio.Event().wait()
            adapter = Adapter.__new__(Adapter)
            adapter.app = app
            app.state = SimpleNamespace(bound_host='127.0.0.1')
            adapter.provider = SimpleNamespace(name='fixture')
            adapter.downloads = SimpleNamespace(spool_dir=Path(directory))
            spool = io.BytesIO()
            with patch('pc.addon.tempfile.SpooledTemporaryFile', return_value=spool):
                task = asyncio.create_task(adapter._asgi('/api/fs/download', 'GET', {}, None, 'fixture-nonce', binary=True))
                await entered.wait()
                task.cancel()
                with self.assertRaises(asyncio.CancelledError):
                    await task
            self.assertTrue(spool.closed)
        with tempfile.TemporaryDirectory(dir=ROOT / '.cache') as directory:
            asyncio.run(scenario(directory))

    def test_disconnect_cancels_admitted_async_work_without_future_traffic(self):
        import threading
        from pc.addon import Adapter
        from pc.catalog import validate_call
        async def scenario():
            adapter = Adapter.__new__(Adapter)
            adapter._tasks = set(); adapter._closed = False
            adapter._write_barrier = threading.Lock()
            adapter._slots = threading.BoundedSemaphore(8)
            adapter._admission_deadline = contextvars.ContextVar('fixture-admission', default=None)
            entered, cancelled = asyncio.Event(), asyncio.Event()
            async def invoke(*args):
                entered.set()
                try:
                    await asyncio.Event().wait()
                finally:
                    cancelled.set()
            adapter.invoke = invoke
            transport = Transport()
            adapter._slots.acquire()
            task = asyncio.create_task(adapter._run_admitted(validate_call({'operation':'GET /api/profiles','profile':'default'}), None, transport))
            await asyncio.wait_for(entered.wait(), 1)
            transport.closed = True
            with self.assertRaises(asyncio.CancelledError):
                await asyncio.wait_for(task, 1)
            self.assertTrue(cancelled.is_set())
            self.assertEqual(adapter._tasks, set())
        asyncio.run(scenario())

    def test_request_deadline_cancels_async_service_and_releases_admission(self):
        import threading
        from pc.addon import Adapter
        from pc.catalog import validate_call
        async def scenario():
            adapter = Adapter.__new__(Adapter)
            adapter._tasks = set(); adapter._closed = False
            adapter._write_barrier = threading.Lock()
            adapter._slots = threading.BoundedSemaphore(8)
            adapter._admission_deadline = contextvars.ContextVar('fixture-admission', default=None)
            cancelled = asyncio.Event()
            async def invoke(*args):
                try:
                    await asyncio.Event().wait()
                finally:
                    cancelled.set()
            adapter.invoke = invoke
            transport = Transport()
            adapter._slots.acquire()
            with patch('pc.addon.REQUEST_TIMEOUT', .03, create=True):
                task = asyncio.create_task(adapter._run_admitted(validate_call({'operation':'GET /api/profiles','profile':'default'}), None, transport))
                done, pending = await asyncio.wait({task}, timeout=.3)
                if not done:
                    task.cancel()
                    await asyncio.gather(task, return_exceptions=True)
                self.assertTrue(done, 'configured deadline did not reach admitted service')
                self.assertTrue(task.cancelled())
                self.assertTrue(cancelled.is_set())
                self.assertEqual(adapter._tasks, set())
        asyncio.run(scenario())

    def test_exact_profile_at_policy_and_request_ingress(self):
        from pc.catalog import validate_call
        from pc.policy import Policy
        for name in ('all', 'current', 'Default', 'a' * 65):
            with self.subTest(name=name), self.assertRaises(CapabilityError):
                validate_call({'operation': 'GET /api/profiles', 'profile': name})
            with self.subTest(grant=name), self.assertRaises(CapabilityError):
                Policy({('lab', 'alice', name): ((), frozenset({'read'}))}, ())

if __name__ == '__main__':
    unittest.main()
