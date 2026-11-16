"""M6l native dialog chrome transaction regressions."""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from DearUIQt.backends.native_windows import NativeWindowBackend


class DialogChromeTransactionTests(unittest.TestCase):
    def test_backend_exposes_combined_chrome_transaction(self):
        self.assertTrue(hasattr(NativeWindowBackend, "configureDialogChrome"))

    def test_combined_transaction_uses_single_framechanged_path(self):
        source = (ROOT / "DearUIQt" / "backends" / "native_windows.py").read_text()
        block = source[source.index("def configureDialogChrome"):
                       source.index("def setResizable")]
        self.assertEqual(block.count("SetWindowPos("), 1)
        self.assertIn("if desired == current:", block)
        self.assertIn("WS_THICKFRAME", block)
        self.assertIn("WS_MINIMIZEBOX", block)
        self.assertIn("WS_MAXIMIZEBOX", block)

    def test_qdialog_prefers_combined_chrome_transaction(self):
        source = (ROOT / "DearUIQt" / "dialogs" / "qt_dialog.py").read_text()
        resize = source[source.index("def _apply_native_resize_policy_once"):
                        source.index("def _modal_parent_tag")]
        hidden = source[source.index("def _prepare_native_hidden"):
                        source.index("def _recover_native_owner_presentation")]
        self.assertIn('configure_chrome = getattr(backend, "configureDialogChrome", None)', resize)
        self.assertIn('configure_chrome = getattr(backend, "configureDialogChrome", None)', hidden)


if __name__ == "__main__":
    unittest.main(verbosity=2)
