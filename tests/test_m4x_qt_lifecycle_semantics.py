from collections import deque
from pathlib import Path
import threading
import time
import unittest
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

from DearUIQt.QtCore import QEvent, QObject, QPointer, QThread
from DearUIQt.core.application import QApplication
from DearUIQt.widgets import QWidget
from test_dearuiqt_layout_cache import Backend


class Scheduler:
    def __init__(self):
        self.callbacks = deque()

    def after(self, _delay, callback, *args):
        self.callbacks.append((callback, args))


class RecordingFilter(QObject):
    def __init__(self, after):
        super().__init__(after=after)
        self.events = []

    def eventFilter(self, watched, event):
        self.events.append((watched, event.type(), threading.get_ident()))
        return False


class EventWindow(QWidget):
    def __init__(self, backend, after):
        super().__init__(backend.add_group(), backend=backend, after=after)
        self.window_events = []

    def changeEvent(self, event):
        if event.type() in (QEvent.WindowActivate, QEvent.WindowDeactivate):
            self.window_events.append(event.type())
        return super().changeEvent(event)


class LifecycleSemanticsM4xTests(unittest.TestCase):
    def tearDown(self):
        app = QApplication.instance()
        if app is not None:
            app.delete()

    def test_destroyed_ignores_signal_block_and_qpointer_is_null_during_callback(self):
        obj = QObject()
        guard = QPointer(obj)
        observed = []
        obj.destroyed.connect(lambda target: observed.append((target, guard.isNull())))
        obj.blockSignals(True)
        obj.delete()
        self.assertEqual(observed, [(obj, True)])

    def test_application_event_filter_is_suspended_after_move_to_worker(self):
        scheduler = Scheduler()
        app = QApplication(after=scheduler.after)
        watched = QObject(after=scheduler.after)
        event_filter = RecordingFilter(scheduler.after)
        app.installEventFilter(event_filter)

        watched.sendEvent(QEvent(QEvent.User))
        self.assertEqual(len(event_filter.events), 1)

        worker = QThread(name="m4x-app-filter")
        event_filter.moveToThread(worker)
        worker.start()
        try:
            deadline = time.time() + 1.0
            while worker.workerThreadId() is None and time.time() < deadline:
                time.sleep(0.005)
            count_after_move = len(event_filter.events)
            watched.sendEvent(QEvent(QEvent.User + 1))
            self.assertEqual(len(event_filter.events), count_after_move)
            self.assertIn(event_filter, app._event_filters)
        finally:
            worker.requestInterruption()
            worker.quit()
            worker.wait(1000)
            event_filter.delete()
            worker.delete()
            watched.delete()

    def test_public_set_active_window_emits_qt_activation_transition_once(self):
        scheduler = Scheduler()
        app = QApplication(after=scheduler.after)
        backend = Backend()
        first = EventWindow(backend, scheduler.after)
        second = EventWindow(backend, scheduler.after)
        try:
            self.assertTrue(app.setActiveWindow(first))
            self.assertIs(app.activeWindow(), first)
            self.assertEqual(first.window_events, [QEvent.WindowActivate])

            self.assertFalse(app.setActiveWindow(first))
            self.assertEqual(first.window_events, [QEvent.WindowActivate])

            self.assertTrue(app.setActiveWindow(second))
            self.assertIs(app.activeWindow(), second)
            self.assertEqual(first.window_events, [QEvent.WindowActivate, QEvent.WindowDeactivate])
            self.assertEqual(second.window_events, [QEvent.WindowActivate])
        finally:
            first.delete()
            second.delete()

    def test_qwidget_activate_window_uses_public_application_state(self):
        scheduler = Scheduler()
        app = QApplication(after=scheduler.after)
        backend = Backend()
        window = EventWindow(backend, scheduler.after)
        child = QWidget(backend.add_group(parent=window.tag), parent=window,
                        backend=backend, after=scheduler.after)
        try:
            self.assertTrue(window.activateWindow())
            self.assertTrue(window.isActiveWindow())
            self.assertIs(app.activeWindow(), window)
            with self.assertRaisesRegex(ValueError, "top-level"):
                app.setActiveWindow(child)
        finally:
            window.delete()

    def test_m4x_version_and_bootstrap_thread_exception_are_documented(self):
        version_source = (ROOT / "DearUIQt" / "__init__.py").read_text(encoding="utf-8")
        architecture = (ROOT / "ARCHITECTURE.md").read_text(encoding="utf-8")
        updater = (ROOT / "winux_runtime" / "update" / "ui.py").read_text(encoding="utf-8")
        import re
        match = re.search(r'__version__\s*=\s*"(\d+)\.(\d+)\.(\d+)"', version_source)
        self.assertIsNotNone(match)
        self.assertGreaterEqual(tuple(map(int, match.groups())), (1, 80, 0))
        self.assertIn("bootstrap boundary", architecture)
        self.assertIn("threading.Thread(", updater)
        self.assertNotIn("from DearUIQt", updater)


if __name__ == "__main__":
    unittest.main()
