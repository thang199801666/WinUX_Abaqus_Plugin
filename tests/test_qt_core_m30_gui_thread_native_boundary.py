from pathlib import Path
import sys
import threading
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "vendor"))
sys.path.insert(0, str(ROOT))

from DearUIQt.runtime import StandaloneUiHost, QGuiRuntime
from DearUIQt.widgets import QApplication


class GuiThreadNativeBoundaryTests(unittest.TestCase):
    def tearDown(self):
        app = QApplication.instance()
        if app is not None:
            app.delete()

    def test_gui_thread_violation_is_bounded_and_counted_only_on_failure(self):
        host = StandaloneUiHost(backend=object())
        app = QApplication(after=host.after)
        before = app.guiThreadDiagnosticsSnapshot()
        self.assertEqual(before["violation_count"], 0)
        self.assertEqual(before["recent_violations"], [])
        errors = []

        def worker():
            for index in range(20):
                try:
                    app.assertGuiThread("worker mutation {}".format(index))
                except RuntimeError as exc:
                    errors.append(str(exc))

        thread = threading.Thread(target=worker)
        thread.start(); thread.join()
        snapshot = app.guiThreadDiagnosticsSnapshot()
        self.assertEqual(len(errors), 20)
        self.assertEqual(snapshot["violation_count"], 20)
        self.assertEqual(len(snapshot["recent_violations"]), 16)
        self.assertIn("worker mutation 19", snapshot["recent_violations"][-1]["operation"])
        app.delete(); host.close()

    def test_native_dialog_snapshot_does_not_create_tk_host(self):
        import WinUx.ui.native.native_dialog_host as native
        original = native._NATIVE_TK_HOST
        native._NATIVE_TK_HOST = None
        try:
            snapshot = native.native_dialog_compatibility_snapshot()
            self.assertFalse(snapshot["created"])
            self.assertFalse(snapshot["alive"])
            self.assertEqual(snapshot["error_count"], 0)
            self.assertIsNone(native._NATIVE_TK_HOST)
        finally:
            native._NATIVE_TK_HOST = original

    def test_resources_module_does_not_eagerly_import_tkinter(self):
        source = (ROOT / "WinUx" / "platform" / "resources.py").read_text(encoding="utf-8")
        prefix = source.split("def apply_tk_app_icon", 1)[0]
        self.assertNotIn("import tkinter", prefix)
        self.assertIn("import tkinter as tk", source.split("def apply_tk_app_icon", 1)[1])

    def test_qdialog_latest_queue_is_lazy_and_canonical_path_is_present(self):
        source = (ROOT / "DearUIQt" / "dialogs" / "qt_dialog.py").read_text(encoding="utf-8")
        self.assertIn("self._latest_updates = None", source)
        self.assertIn("postCallLatest", source)
        self.assertIn("def _legacy_latest_update_queue", source)


if __name__ == "__main__":
    unittest.main(verbosity=2)
