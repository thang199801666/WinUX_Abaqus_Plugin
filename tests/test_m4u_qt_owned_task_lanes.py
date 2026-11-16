import threading
import time
import unittest
from pathlib import Path

from DearUIQt.core import QThreadPool
from WinUx.runtime.task_manager import BackgroundTaskManager


ROOT = Path(__file__).resolve().parents[1]


class QtOwnedTaskLanesM4uTests(unittest.TestCase):
    def test_task_manager_uses_dearuiqt_pool_not_raw_threads(self):
        source = (ROOT / "WinUx/runtime/task_manager.py").read_text(encoding="utf-8")
        self.assertIn("QThreadPool", source)
        self.assertNotIn("threading.Thread(", source)
        self.assertNotIn("queue.Queue(", source)

    def test_pool_exposes_lazy_owned_thread_count_for_diagnostics(self):
        pool = QThreadPool(maxThreadCount=1, maxPending=2, name="m4u-count")
        self.assertEqual(pool.threadCount(), 0)
        future = pool.start(lambda: 7)
        self.assertEqual(future.result(2.0), 7)
        self.assertEqual(pool.threadCount(), 1)
        pool.close(wait=True)

    def test_coalesce_reuses_active_qt_future_lane_handle(self):
        manager = BackgroundTaskManager(max_workers=1, max_pending=2, name="m4u-coalesce")
        gate = threading.Event()
        first = manager.submit("one", lambda: gate.wait(1.0), key="same")
        second = manager.submit("two", lambda: None, key="same", coalesce=True)
        self.assertIs(first, second)
        gate.set()
        self.assertTrue(first.wait(2.0))
        manager.close()

    def test_close_cancels_queued_handle_without_waiting_for_running_job(self):
        manager = BackgroundTaskManager(max_workers=1, max_pending=2, name="m4u-close")
        gate = threading.Event()
        running = manager.submit("running", lambda: gate.wait(1.5))
        deadline = time.monotonic() + 1.0
        while running.state == "queued" and time.monotonic() < deadline:
            time.sleep(0.005)
        queued = manager.submit("queued", lambda: 2)
        started = time.monotonic()
        manager.close(cancel_pending=True)
        self.assertLess(time.monotonic() - started, 0.25)
        self.assertTrue(queued.wait(1.0))
        self.assertEqual(queued.state, "cancelled")
        gate.set()
        self.assertTrue(running.wait(2.0))
        self.assertEqual(running.state, "cancelled")

    def test_session_scope_cancels_only_owned_tasks(self):
        manager = BackgroundTaskManager(max_workers=1, max_pending=4, name="m4u-scope")
        gate = threading.Event()
        first = manager.submit("session-a-running", lambda: gate.wait(1.0), scope="session:a")
        deadline = time.monotonic() + 1.0
        while first.state == "queued" and time.monotonic() < deadline:
            time.sleep(0.005)
        queued_a = manager.submit("session-a-queued", lambda: 2, scope="session:a")
        queued_b = manager.submit("session-b-queued", lambda: 3, scope="session:b")

        self.assertEqual(manager.scope_count("session:a"), 2)
        self.assertEqual(manager.scope_count("session:b"), 1)
        self.assertEqual(manager.cancel_scope("session:a"), 2)
        self.assertTrue(queued_a.wait(1.0))
        self.assertEqual(queued_a.state, "cancelled")
        self.assertFalse(queued_b.cancel_event.is_set())
        gate.set()
        self.assertTrue(first.wait(2.0))
        self.assertTrue(queued_b.wait(2.0))
        self.assertEqual(queued_b.state, "completed")
        manager.close()

    def test_task_snapshot_reports_scope_counts(self):
        manager = BackgroundTaskManager(max_workers=1, max_pending=2, name="m4u-scope-snapshot")
        gate = threading.Event()
        handle = manager.submit("owned", lambda: gate.wait(1.0), scope="session:42")
        snapshot = manager.snapshot()
        self.assertEqual(snapshot["scope_counts"].get("session:42"), 1)
        self.assertEqual(snapshot["active"][0]["scope"], "session:42")
        gate.set()
        self.assertTrue(handle.wait(2.0))
        manager.close()

    def test_long_lived_migrated_services_do_not_create_raw_threads(self):
        for relative in (
            "WinUx/services/server_cut_monitor.py",
            "WinUx/services/server_notepad/ipc.py",
        ):
            source = (ROOT / relative).read_text(encoding="utf-8")
            self.assertIn("QThread", source, relative)
            self.assertNotIn("threading.Thread(", source, relative)

    def test_ssh_shutdown_cleanup_uses_qthreadpool(self):
        source = (ROOT / "WinUx/services/ssh_server.py").read_text(encoding="utf-8")
        self.assertIn("QThreadPool.globalInstance().start(cleanup)", source)
        self.assertNotIn('name="winux-ssh-shutdown"', source)


if __name__ == "__main__":
    unittest.main()
