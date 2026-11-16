from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class ApplicationQDialogHostPolicyTests(unittest.TestCase):
    def test_main_window_defaults_application_qdialogs_to_owned_native_host(self):
        source = (ROOT / "WinUx/ui/main_window.py").read_text(encoding="utf-8")
        self.assertIn('os.environ.get("WINUX_NATIVE_QDIALOGS", "1")', source)
        self.assertIn('self._native_qdialog_surfaces', source)

    def test_qdialog_honors_view_surface_policy_but_keeps_explicit_native_override(self):
        source = (ROOT / "DearUIQt/dialogs/qt_dialog.py").read_text(encoding="utf-8")
        self.assertIn('getattr(view, "_native_qdialog_surfaces", True)', source)
        self.assertIn('if native is None else bool(native)', source)

    def test_session_tabs_do_not_force_process_host_fallback(self):
        source = (ROOT / "WinUx/ui/main_window.py").read_text(encoding="utf-8")
        self.assertNotIn('WINUX_DIALOG_PROCESS_FALLBACK', source)
        self.assertIn('zero per-dialog workers', source.lower())


if __name__ == "__main__":
    unittest.main()
