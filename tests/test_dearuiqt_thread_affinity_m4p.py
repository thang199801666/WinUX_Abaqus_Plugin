"""M4p contracts: queued work follows QObject thread affinity."""
from pathlib import Path
import sys
import threading
import time
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "vendor"))
sys.path.insert(0, str(ROOT))

from DearUIQt.core import QObject, QEvent, QMetaObject, QThread, QTimer, Qt, Signal
from DearUIQt.runtime import StandaloneUiHost
from DearUIQt.widgets import QApplication, QWidget


class Receiver(QObject):
    def __init__(self, after):
        super().__init__(after=after)
        self.called = threading.Event()
        self.ident = None
        self.values = []

    def record(self, value=None):
        self.ident = threading.get_ident()
        self.values.append(value)
        self.called.set()


class EventReceiver(Receiver):
    EVENT_TYPE = 1901

    def event(self, event):
        if event.type() == self.EVENT_TYPE:
            self.record("event")
            return True
        return super().event(event)


class DummyWidget(QWidget):
    def __init__(self, after):
        QObject.__init__(self, after=after)


def cleanup_thread(thread, *objects):
    for obj in objects:
        if obj is not None and not getattr(obj, "_deleted", False):
            try:
                thread.post(obj.delete)
            except Exception:
                pass
    thread.quit()
    thread.wait(1000)
    if not thread._deleted:
        thread.delete()


class ThreadAffinityM4pTests(unittest.TestCase):
    def setUp(self):
        self.host = StandaloneUiHost(backend=object())

    def tearDown(self):
        self.host.close()

    def test_queued_signal_follows_receiver_moved_after_emit(self):
        sender = QObject(after=self.host.after)
        sender.changed = Signal(sender)
        receiver = Receiver(self.host.after)
        worker = QThread(name="m4p-signal")
        sender.changed.connect(receiver.record, receiver=receiver, queued=True)

        sender.changed.emit("queued-before-move")
        receiver.moveToThread(worker)
        worker.start()
        try:
            # This executes the stale GUI wake token. It must forward to worker.
            self.host.pump()
            self.assertTrue(receiver.called.wait(1.0))
            self.assertEqual(receiver.values, ["queued-before-move"])
            self.assertEqual(receiver.ident, worker.workerThreadId())
        finally:
            cleanup_thread(worker, receiver)
            sender.delete()

    def test_invoke_method_follows_receiver_moved_before_delivery(self):
        receiver = Receiver(self.host.after)
        worker = QThread(name="m4p-invoke")
        self.assertTrue(QMetaObject.invokeMethod(
            receiver, "record", Qt.QueuedConnection, "invoke-before-move"))
        receiver.moveToThread(worker)
        worker.start()
        try:
            self.host.pump()
            self.assertTrue(receiver.called.wait(1.0))
            self.assertEqual(receiver.values, ["invoke-before-move"])
            self.assertEqual(receiver.ident, worker.workerThreadId())
        finally:
            cleanup_thread(worker, receiver)

    def test_qapplication_posted_event_follows_moved_receiver(self):
        app = QApplication(after=self.host.after)
        receiver = EventReceiver(self.host.after)
        worker = QThread(name="m4p-posted-event")
        try:
            self.assertTrue(app.postEvent(receiver, QEvent(EventReceiver.EVENT_TYPE)))
            receiver.moveToThread(worker)
            worker.start()
            self.host.pump()
            self.assertTrue(receiver.called.wait(1.0))
            self.assertEqual(receiver.values, ["event"])
            self.assertEqual(receiver.ident, worker.workerThreadId())
        finally:
            cleanup_thread(worker, receiver)
            app.delete()

    def test_delete_later_follows_moved_receiver(self):
        app = QApplication(after=self.host.after)
        receiver = Receiver(self.host.after)
        worker = QThread(name="m4p-delete-later")
        destroyed_on = []
        done = threading.Event()
        receiver.destroyed.connect(
            lambda _obj: (destroyed_on.append(threading.get_ident()), done.set()))
        try:
            receiver.deleteLater()
            receiver.moveToThread(worker)
            worker.start()
            self.host.pump()
            self.assertTrue(done.wait(1.0))
            self.assertTrue(receiver._deleted)
            self.assertEqual(destroyed_on, [worker.workerThreadId()])
        finally:
            cleanup_thread(worker)
            app.delete()

    def test_active_timer_restarts_on_target_affinity(self):
        timer = QTimer(after=self.host.after)
        timer.setSingleShot(True)
        fired = threading.Event()
        fired_on = []
        timer.timeout.connect(lambda: (fired_on.append(threading.get_ident()), fired.set()))
        timer.start(0)
        worker = QThread(name="m4p-timer")
        timer.moveToThread(worker)
        worker.start()
        try:
            self.assertTrue(fired.wait(1.0))
            self.assertEqual(fired_on, [worker.workerThreadId()])
            self.assertFalse(timer.isActive())
        finally:
            cleanup_thread(worker, timer)

    def test_qwidget_is_gui_thread_only(self):
        widget = DummyWidget(self.host.after)
        worker = QThread(name="m4p-widget")
        try:
            with self.assertRaisesRegex(RuntimeError, "QWidget objects cannot be moved"):
                widget.moveToThread(worker)
        finally:
            QObject.delete(widget)
            worker.delete()


if __name__ == "__main__":
    unittest.main()
