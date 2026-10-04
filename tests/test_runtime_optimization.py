from pathlib import Path
import threading
import time
import unittest

from WinUx.runtime import BackgroundTaskManager, UiDispatcher

ROOT = Path(__file__).resolve().parents[1]


class BackgroundTaskManagerTests(unittest.TestCase):
    def test_coalesced_task_reuses_active_handle(self):
        manager = BackgroundTaskManager(max_workers=1, max_pending=4, name="test-bg")
        release = threading.Event()
        try:
            first = manager.submit("refresh", release.wait, 0.2, key="refresh", coalesce=True)
            second = manager.submit("refresh", lambda: None, key="refresh", coalesce=True)
            self.assertIs(first, second)
        finally:
            release.set()
            manager.close()


    def test_replace_cancels_older_pending_task_with_same_key(self):
        manager = BackgroundTaskManager(max_workers=1, max_pending=8, name="test-replace")
        blocker = threading.Event()
        started = threading.Event()
        ran = []
        try:
            manager.submit("block", lambda: (started.set(), blocker.wait(0.5)))
            self.assertTrue(started.wait(0.2))
            old = manager.submit("nav-old", lambda: ran.append("old"), key="nav", replace=True)
            new = manager.submit("nav-new", lambda: ran.append("new"), key="nav", replace=True)
            self.assertTrue(old.cancel_event.is_set())
            blocker.set()
            self.assertTrue(new.wait(0.5))
            self.assertEqual(ran, ["new"])
        finally:
            blocker.set()
            manager.close()

    def test_close_never_waits_for_blocked_worker(self):
        manager = BackgroundTaskManager(max_workers=1, max_pending=4, name="test-bg")
        release = threading.Event()
        started = threading.Event()

        def worker():
            started.set()
            release.wait(1.0)

        manager.submit("blocked", worker)
        self.assertTrue(started.wait(0.5))
        begin = time.monotonic()
        manager.close(cancel_pending=True)
        elapsed = time.monotonic() - begin
        release.set()
        self.assertLess(elapsed, 0.2)

    def test_worker_count_is_fixed_and_daemonized(self):
        manager = BackgroundTaskManager(max_workers=3, max_pending=8, name="test-fixed")
        try:
            self.assertEqual(len(manager._workers), 3)
            self.assertTrue(all(worker.daemon for worker in manager._workers))
        finally:
            manager.close()


class UiDispatcherOptimizationTests(unittest.TestCase):
    def test_delayed_callbacks_use_one_scheduler_thread(self):
        dispatcher = UiDispatcher()
        fired = []
        try:
            for value in range(20):
                dispatcher.after(10, fired.append, value)
            time.sleep(0.04)
            dispatcher.drain()
            self.assertEqual(sorted(fired), list(range(20)))
            self.assertTrue(dispatcher._scheduler.daemon)
        finally:
            dispatcher.close()

    def test_drain_can_be_bounded_per_frame(self):
        dispatcher = UiDispatcher()
        values = []
        try:
            for value in range(10):
                dispatcher.after(0, values.append, value)
            processed = dispatcher.drain(max_callbacks=3)
            self.assertEqual(processed, 3)
            self.assertEqual(len(values), 3)
            dispatcher.drain()
            self.assertEqual(len(values), 10)
        finally:
            dispatcher.close()


class RuntimeArchitectureTests(unittest.TestCase):
    def test_controller_uses_bounded_pools_for_short_and_transfer_work(self):
        source = (ROOT / "WinUx" / "controller.py").read_text(encoding="utf-8")
        self.assertIn("BackgroundTaskManager", source)
        self.assertIn('name="winux-bg"', source)
        self.assertIn('name="winux-xfer"', source)
        transfer_source = (
            ROOT / "WinUx" / "controllers" / "transfer.py"
        ).read_text(encoding="utf-8")
        self.assertIn('self.app._submit_transfer("file-transfer"', transfer_source)
        # Only intentional long-lived service loops keep dedicated threads.
        # Realtime Job Plots adds one persistent ODB monitor thread per open
        # plot window so it can own a long-lived auxiliary SSH/Abaqus channel.
        self.assertLessEqual(source.count("threading.Thread("), 3)
        plot_source = (ROOT / "WinUx" / "controllers" / "job_plot.py").read_text(encoding="utf-8")
        self.assertEqual(plot_source.count("threading.Thread("), 1)
        self.assertIn('name="winux-job-plot-{}"', plot_source)


    def test_local_navigation_lists_directory_off_render_thread(self):
        source = (ROOT / "WinUx" / "controllers" / "navigation.py").read_text(encoding="utf-8")
        start = source.index("    def open(")
        end = source.index("    def server_loaded", start)
        block = source[start:end]
        self.assertIn("def local_worker():", block)
        self.assertIn("items = self.model.list_directory(path)", block)
        self.assertIn('"local-navigation", local_worker, key="local-navigation"', block)
        self.assertIn("replace=True", block)
        self.assertIn("self.app._local_nav_generation", block)

    def test_view_has_ui_hang_watchdog_and_bounded_callback_drain(self):
        source = (ROOT / "WinUx" / "view.py").read_text(encoding="utf-8")
        watchdog = (ROOT / "WinUx" / "runtime" / "hang_watchdog.py").read_text(encoding="utf-8")
        self.assertIn("UIHangWatchdog", source)
        self.assertIn("time_budget_ms=6.0", source)
        self.assertIn("winux_hang.log", watchdog)
        self.assertIn("sys._current_frames()", watchdog)

    def test_server_path_search_reuses_ui_scheduler(self):
        source = (ROOT / "WinUx" / "dialogs" / "server_path_form.py").read_text(encoding="utf-8")
        self.assertIn("self.view.after", source)
        self.assertNotIn("threading.Timer(", source)

    def test_all_file_transfers_are_off_render_thread(self):
        source = (
            ROOT / "WinUx" / "controllers" / "transfer.py"
        ).read_text(encoding="utf-8")
        start = source.index("    def start_drop_transfer")
        end = source.index("    def cross_panel_conflicts", start)
        block = source[start:end]
        self.assertIn('self.app._submit_transfer(', block)
        self.assertNotIn("else:\n            transfer()", block)


if __name__ == "__main__":
    unittest.main()
