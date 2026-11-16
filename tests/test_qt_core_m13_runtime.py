import time
import unittest

from DearUIQt import QApplication
from DearUIQt.core import QCoreApplication, QObject, QThread
from DearUIQt.runtime import QGuiRuntime


class DummyBackend:
    def is_dearpygui_running(self):
        return True


class DummyDispatcher:
    def __init__(self, deadline):
        self.deadline = deadline

    def nextDeadlineMs(self):
        return self.deadline


class QtCoreM13Tests(unittest.TestCase):
    def tearDown(self):
        app = QCoreApplication.instance()
        if app is not None:
            # Disable explicit debug assertion before generic test cleanup.
            app.setShutdownOrphanPolicy(assert_on_quit=False)
            app.delete()

    def test_core_application_has_no_gui_policy_state(self):
        app = QCoreApplication(after=lambda delay, callback, *args: None)
        self.assertFalse(app.isGuiApplication())
        for name in (
            "_focus_widget", "_focus_object", "_active_window",
            "_popup_stack", "_modal_stack", "_input_backend",
            "_pointer_targets", "_shortcuts",
        ):
            self.assertFalse(hasattr(app, name), name)
        self.assertFalse(app.diagnosticsSnapshot()["gui_application"])
        with self.assertRaises(AttributeError):
            app.focusObject()
        child = QObject(app)
        child.delete()  # core QObject cleanup must not require GUI state

    def test_qapplication_owns_gui_policy_state(self):
        app = QApplication(after=lambda delay, callback, *args: None)
        self.assertTrue(app.isGuiApplication())
        self.assertTrue(hasattr(app, "_popup_stack"))
        self.assertTrue(hasattr(app, "_pointer_targets"))
        self.assertIsNone(app.focusObject())
        self.assertTrue(app.diagnosticsSnapshot()["gui_application"])

    def test_shutdown_orphan_policy_is_opt_in_and_type_selective(self):
        app = QCoreApplication(after=lambda delay, callback, *args: None)
        orphan = QObject()
        seen = []
        app.setShutdownOrphanPolicy(["QObject"], callback=seen.append)
        app.quit()
        self.assertEqual(len(seen), 1)
        self.assertGreaterEqual(seen[0]["selected_orphan_count"], 1)
        self.assertIn("QObject", seen[0]["selected_orphan_types"])
        self.assertIsNotNone(app.lastShutdownDiagnostics())
        orphan.delete()

    def test_shutdown_orphan_assertion_only_when_explicitly_enabled(self):
        app = QCoreApplication(after=lambda delay, callback, *args: None)
        orphan = QObject()
        app.setShutdownOrphanPolicy([QObject], assert_on_quit=True)
        with self.assertRaises(AssertionError):
            app.quit()
        self.assertFalse(app._quitting)
        orphan.delete()
        app.setShutdownOrphanPolicy(assert_on_quit=False)
        app.quit()

    def test_qthread_uses_qeventdispatcher_and_preserves_prestart_priority(self):
        thread = QThread(name="m13-worker")
        seen = []
        low = thread.post(seen.append, "low", priority=-5)
        cancelled = thread.post(seen.append, "cancelled", priority=100)
        thread.post(seen.append, "high", priority=5)
        self.assertTrue(thread.after_cancel(cancelled))
        self.assertIsNotNone(thread.nextDeadlineMs())
        self.assertTrue(thread.start())
        # Wait until worker dispatcher exists, then inspect without mutation.
        deadline = time.monotonic() + 1.0
        while time.monotonic() < deadline:
            if thread.diagnosticsSnapshot()["uses_qeventdispatcher"]:
                break
            time.sleep(0.005)
        thread.post(thread.quit, priority=-100)
        self.assertTrue(thread.wait(2000))
        self.assertEqual(seen, ["high", "low"])
        self.assertFalse(thread.after_cancel(low))
        thread.delete()

    def test_runtime_frame_snapshot_combines_deadline_and_dirty_state(self):
        runtime = QGuiRuntime(DummyBackend())
        host = runtime.windowHost()
        snap = runtime.frameSchedulingSnapshot(DummyDispatcher(25.0))
        self.assertFalse(snap["immediate_frame"])
        self.assertEqual(snap["next_deadline_ms"], 25.0)
        self.assertEqual(runtime.nextFrameDelayMs(DummyDispatcher(25.0), default_ms=50), 25.0)
        host.requestUpdate((1, 2, 3, 4))
        snap = runtime.frameSchedulingSnapshot(DummyDispatcher(25.0))
        self.assertTrue(snap["has_dirty_region"])
        self.assertTrue(snap["immediate_frame"])
        self.assertEqual(runtime.nextFrameDelayMs(DummyDispatcher(25.0)), 0.0)
        host.delete()


if __name__ == "__main__":
    unittest.main(verbosity=2)
