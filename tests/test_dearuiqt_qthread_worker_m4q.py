"""M4q contracts: Qt-style QThread worker-object lifecycle and teardown."""
from pathlib import Path
import sys
import threading
import time
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "vendor"))
sys.path.insert(0, str(ROOT))

from DearUIQt.core import QObject, QThread, Signal
from DearUIQt.runtime import StandaloneUiHost
from DearUIQt.widgets import QApplication


class Worker(QObject):
    def __init__(self, after):
        super().__init__(after=after)
        self.finished = Signal(self)
        self.work_ident = None
        self.destroy_ident = None
        self.ran = threading.Event()

    def work(self):
        self.work_ident = threading.get_ident()
        self.ran.set()
        self.finished.emit()


class ExitCodeThread(QThread):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.result = None

    def run(self):
        self.result = self.exec()


class QThreadWorkerM4qTests(unittest.TestCase):
    def setUp(self):
        self.host = StandaloneUiHost(backend=object())
        self.app = QApplication(after=self.host.after)

    def tearDown(self):
        if not self.app._deleted:
            self.app.delete()
        self.host.close()

    def test_finished_delete_later_is_drained_before_native_thread_teardown(self):
        thread = QThread(name="m4q-worker")
        worker = Worker(self.host.after)
        worker.moveToThread(thread)
        destroyed = threading.Event()
        destroyed_on = []
        worker.destroyed.connect(
            lambda _obj: (destroyed_on.append(threading.get_ident()), destroyed.set()))

        thread.started.connect(worker.work, receiver=worker)
        worker.finished.connect(thread.quit)
        thread.finished.connect(worker.deleteLater, receiver=worker)

        self.assertTrue(thread.start())
        deadline = time.monotonic() + 1.0
        while not thread.isRunning() and time.monotonic() < deadline:
            time.sleep(0.001)
        while thread.isRunning() and time.monotonic() < deadline:
            # worker.finished -> thread.quit is an AutoConnection to the QThread
            # object, whose affinity remains the creator/UI thread.
            self.host.pump()
            time.sleep(0.001)

        self.assertTrue(thread.wait(1000))
        self.host.pump()
        self.assertTrue(worker.ran.is_set())
        self.assertTrue(destroyed.is_set())
        self.assertTrue(worker._deleted)
        self.assertEqual(worker.work_ident, destroyed_on[0])
        self.assertNotEqual(worker.work_ident, threading.get_ident())
        thread.delete()

    def test_exit_code_is_returned_from_exec(self):
        thread = ExitCodeThread(name="m4q-exit-code")
        self.assertTrue(thread.start())
        deadline = time.monotonic() + 1.0
        while not thread.isRunning() and time.monotonic() < deadline:
            time.sleep(0.001)
        self.assertTrue(thread.exit(7))
        self.assertTrue(thread.wait(1000))
        self.assertEqual(thread.result, 7)
        thread.delete()

    def test_quit_is_exit_zero(self):
        thread = ExitCodeThread(name="m4q-quit")
        self.assertTrue(thread.start())
        deadline = time.monotonic() + 1.0
        while not thread.isRunning() and time.monotonic() < deadline:
            time.sleep(0.001)
        self.assertTrue(thread.quit())
        self.assertTrue(thread.wait(1000))
        self.assertEqual(thread.result, 0)
        thread.delete()

    def test_interruption_state_is_reset_on_restart(self):
        thread = QThread(name="m4q-interrupt")
        thread.requestInterruption()
        self.assertTrue(thread.isInterruptionRequested())
        self.assertTrue(thread.start())
        deadline = time.monotonic() + 1.0
        while not thread.isRunning() and time.monotonic() < deadline:
            time.sleep(0.001)
        self.assertFalse(thread.isInterruptionRequested())
        thread.requestInterruption()
        self.assertTrue(thread.isInterruptionRequested())
        thread.quit()
        self.assertTrue(thread.wait(1000))
        thread.delete()

    def test_is_current_thread_only_inside_worker(self):
        thread = QThread(name="m4q-current")
        values = []
        done = threading.Event()

        def inspect():
            values.append(thread.isCurrentThread())
            done.set()
            thread.quit()

        thread.started.connect(inspect)
        self.assertFalse(thread.isCurrentThread())
        self.assertTrue(thread.start())
        self.assertTrue(done.wait(1.0))
        self.assertTrue(thread.wait(1000))
        self.assertEqual(values, [True])
        self.assertFalse(thread.isCurrentThread())
        thread.delete()


if __name__ == "__main__":
    unittest.main()
