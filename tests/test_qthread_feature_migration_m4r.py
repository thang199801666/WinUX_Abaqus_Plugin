"""M4r contracts: long-lived WinUx workers use QObject + QThread."""
from pathlib import Path
import inspect
import tempfile
import time
import unittest

from DearUIQt.core import QThread
from DearUIQt.runtime import StandaloneUiHost
from DearUIQt.widgets import QApplication
from WinUx.controllers.jobs.polling import JobPollingController
from WinUx.controllers.explorer.local_watch import LocalWatchController
from WinUx.services.local_file_watcher import LocalFileSystemWatcher


class _Server:
    connected = False


class _View:
    def __init__(self, after):
        self.after = after
        self._dispatcher = None


class _App:
    def __init__(self, after):
        self.view = _View(after)
        self.server = _Server()
        self._closing = True
        self._job_poll_cancel = None
        self._job_poll_policy = None
        self._job_poll_wakeup = None
        self._job_poll_force_fast = None
        self._job_poll_thread = None
        self._job_poll_worker = None


class QThreadFeatureMigrationM4rTests(unittest.TestCase):
    def setUp(self):
        self.host = StandaloneUiHost(backend=object())
        self.qtapp = QApplication(after=self.host.after)

    def tearDown(self):
        if not self.qtapp._deleted:
            self.qtapp.delete()
        self.host.close()

    def test_job_poller_uses_qthread_worker_object(self):
        app = _App(self.host.after)
        controller = JobPollingController(app, adopt_existing=True)
        controller.start()
        thread = app._job_poll_thread
        worker = app._job_poll_worker
        self.assertIsInstance(thread, QThread)
        self.assertIs(worker.thread(), thread)
        controller.stop()
        deadline = time.monotonic() + 1.0
        while thread.isRunning() and time.monotonic() < deadline:
            self.host.pump()
            time.sleep(0.001)
        self.assertTrue(thread.wait(1000))
        self.host.pump()
        self.assertTrue(worker._deleted)

    def test_job_poller_source_has_no_raw_thread_creation(self):
        source = inspect.getsource(JobPollingController.start)
        self.assertNotIn("threading.Thread", source)
        self.assertIn("QThread(", source)
        self.assertIn("moveToThread", source)
        self.assertIn("requestInterruption", inspect.getsource(JobPollingController.stop))

    def test_local_watcher_uses_qthread_and_wait_contract(self):
        with tempfile.TemporaryDirectory() as folder:
            watcher = LocalFileSystemWatcher(polling_interval=0.20)
            watcher.watch(folder)
            thread = watcher._thread
            worker = watcher._worker
            self.assertIsInstance(thread, QThread)
            self.assertIs(worker.thread(), thread)
            deadline = time.monotonic() + 1.0
            while not thread.isRunning() and time.monotonic() < deadline:
                time.sleep(0.001)
            watcher.stop(wait=True, timeout=1.0)
            self.assertTrue(thread.wait(1000))
            self.assertFalse(thread.isRunning())
            self.assertTrue(worker._deleted)

    def test_local_watcher_source_has_no_raw_thread_creation_or_join(self):
        source = inspect.getsource(LocalFileSystemWatcher.watch)
        stop_source = inspect.getsource(LocalFileSystemWatcher.stop)
        self.assertNotIn("threading.Thread", source)
        self.assertIn("QThread(", source)
        self.assertNotIn(".join(", stop_source)
        self.assertIn("requestInterruption", stop_source)
        self.assertIn(".wait(", stop_source)

    def test_local_watch_controller_marshals_worker_notifications_to_dispatcher(self):
        changed = inspect.getsource(LocalWatchController.changed)
        report = inspect.getsource(LocalWatchController.report_error)
        self.assertIn("_post_ui", changed)
        self.assertNotIn("view.after", changed)
        self.assertIn("_post_ui", report)

    def test_local_watch_refresh_worker_uses_event_posted_completion(self):
        source = inspect.getsource(LocalWatchController.begin_refresh)
        self.assertIn("on_done=completed", source)
        worker_source = source.split("def worker():", 1)[1].split("def completed", 1)[0]
        self.assertNotIn("view.after", worker_source)


if __name__ == "__main__":
    unittest.main()
