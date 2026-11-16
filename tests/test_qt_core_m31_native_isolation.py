from pathlib import Path
import sys
import threading
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "vendor"))
sys.path.insert(0, str(ROOT))

from DearUIQt.runtime import StandaloneUiHost, QGuiRuntime
from DearUIQt.widgets import QApplication


class NativeIsolationM31Tests(unittest.TestCase):
    def tearDown(self):
        app = QApplication.instance()
        if app is not None:
            app.delete()

    def test_post_call_after_uses_canonical_dispatcher_and_coalesces(self):
        host = StandaloneUiHost(backend=object())
        app = QApplication(after=host.after)
        received = []
        first = app.postCallAfter(0, received.append, 1, key="same")
        second = app.postCallAfter(0, received.append, 2, key="same")
        self.assertIsNotNone(first)
        self.assertIsNone(second)
        self.assertEqual(host.dispatcher.pendingCount(), 1)
        self.assertEqual(host.pump(), 1)
        self.assertEqual(received, [1])
        app.delete(); host.close()

    def test_gui_thread_acceptance_requires_zero_violations(self):
        host = StandaloneUiHost(backend=object())
        app = QApplication(after=host.after)
        self.assertTrue(app.guiThreadAcceptanceSnapshot()["accepted"])

        def worker():
            try:
                app.assertGuiThread("m31 worker mutation")
            except RuntimeError:
                pass

        thread = threading.Thread(target=worker)
        thread.start(); thread.join()
        acceptance = app.guiThreadAcceptanceSnapshot()
        self.assertFalse(acceptance["accepted"])
        self.assertEqual(acceptance["violation_count"], 1)
        app.delete(); host.close()

    def test_crash_snapshot_exposes_gui_thread_acceptance(self):
        host = StandaloneUiHost(backend=object())
        app = QApplication(after=host.after)
        runtime = QGuiRuntime(backend=object())
        snapshot = runtime.crashDiagnosticsSnapshot(host.dispatcher)
        self.assertIn("gui_thread_acceptance", snapshot)
        self.assertTrue(snapshot["gui_thread_acceptance"]["accepted"])
        app.delete(); host.close()

    def test_normal_runtime_tk_compatibility_acceptance_requires_no_host(self):
        import WinUx.ui.native.native_dialog_host as native
        original = native._NATIVE_TK_HOST
        native._NATIVE_TK_HOST = None
        try:
            snapshot = native.native_dialog_compatibility_acceptance_snapshot()
            self.assertTrue(snapshot["accepted"])
            self.assertFalse(snapshot["host_created"])
            self.assertIsNone(native._NATIVE_TK_HOST)
        finally:
            native._NATIVE_TK_HOST = original

    def test_native_owner_restore_routes_delayed_calls_through_application(self):
        source = (ROOT / "WinUx" / "ui" / "native" / "native_dialog_host.py").read_text(encoding="utf-8")
        block = source.split("def _queue_owner_restore", 1)[1].split("def restore_owner_focus_async", 1)[0]
        self.assertIn("postCallAfter", block)
        self.assertIn("postCallLatest", block)
        self.assertIn("Standalone/legacy host fallback only", block)

    def test_native_controller_has_no_normal_runtime_consumers(self):
        offenders = []
        for path in (ROOT / "WinUx").rglob("*.py"):
            if path.name == "native_dialog_host.py":
                continue
            text = path.read_text(encoding="utf-8", errors="ignore")
            if "NativeDialogController(" in text:
                offenders.append(str(path.relative_to(ROOT)))
        self.assertEqual(offenders, [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
