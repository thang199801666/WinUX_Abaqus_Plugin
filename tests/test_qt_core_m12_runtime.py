import unittest

from DearUIQt.core import QCoreApplication, QEvent, QObject
from DearUIQt import QApplication


class Recorder(QObject):
    EVENT_TYPE = 2901

    def __init__(self, log, name, parent=None):
        super().__init__(parent)
        self.log = log
        self.name = name

    def event(self, event):
        if event.type() in (self.EVENT_TYPE, QEvent.LayoutRequest):
            self.log.append(self.name)
            return True
        return super().event(event)


class QtCoreM12Tests(unittest.TestCase):
    def tearDown(self):
        app = QCoreApplication.instance()
        if app is not None:
            app.delete()

    def test_core_application_does_not_construct_gui_style_policy(self):
        app = QCoreApplication(after=lambda delay, callback, *args: None)
        self.assertFalse(hasattr(app, "_style"))
        self.assertFalse(hasattr(app, "_palette"))
        # M14 physically removes GUI-only APIs from QCoreApplication.
        with self.assertRaises(AttributeError):
            app.style()
        with self.assertRaises(AttributeError):
            app.palette()

    def test_qapplication_constructs_gui_style_policy(self):
        app = QApplication(after=lambda delay, callback, *args: None)
        self.assertIsNotNone(app.style())
        self.assertIsNotNone(app.palette())
        self.assertTrue(hasattr(app, "styleChanged"))
        self.assertTrue(hasattr(app, "paletteChanged"))

    def test_posted_events_use_priority_then_fifo(self):
        app = QCoreApplication(after=lambda delay, callback, *args: None)
        log = []
        low1 = Recorder(log, "low1", app)
        high1 = Recorder(log, "high1", app)
        high2 = Recorder(log, "high2", app)
        low2 = Recorder(log, "low2", app)
        app.postEvent(low1, QEvent(Recorder.EVENT_TYPE), priority=-1)
        app.postEvent(high1, QEvent(Recorder.EVENT_TYPE), priority=5)
        app.postEvent(high2, QEvent(Recorder.EVENT_TYPE), priority=5)
        app.postEvent(low2, QEvent(Recorder.EVENT_TYPE), priority=-1)
        self.assertEqual(app.processEvents(), 4)
        self.assertEqual(log, ["high1", "high2", "low1", "low2"])

    def test_layout_compression_keeps_highest_priority(self):
        app = QCoreApplication(after=lambda delay, callback, *args: None)
        log = []
        target = Recorder(log, "layout", app)
        other = Recorder(log, "other", app)
        app.postEvent(target, QEvent(QEvent.LayoutRequest), priority=-10)
        app.postEvent(target, QEvent(QEvent.LayoutRequest), priority=20)
        app.postEvent(other, QEvent(Recorder.EVENT_TYPE), priority=0)
        self.assertEqual(app.processEvents(), 2)
        self.assertEqual(log, ["layout", "other"])

    def test_lifecycle_diagnostics_detect_and_clear_parentless_object(self):
        app = QCoreApplication(after=lambda delay, callback, *args: None)
        orphan = QObject()
        snapshot = app.lifecycleDiagnostics()
        self.assertGreaterEqual(snapshot["orphan_object_count"], 1)
        self.assertIn("QObject", snapshot["orphan_types"])
        with self.assertRaises(AssertionError):
            app.assertNoOrphanObjects()
        orphan.delete()
        self.assertTrue(app.assertNoOrphanObjects())


if __name__ == "__main__":
    unittest.main()
