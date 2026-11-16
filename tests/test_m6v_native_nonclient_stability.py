"""M6v Win32 non-client hover stability regressions."""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


class NativeNonClientStabilityTests(unittest.TestCase):
    def test_dialog_hook_filters_redundant_framechanged_after_chrome_commit(self):
        source = (ROOT / "DearUIQt" / "backends" / "native_windows.py").read_text()
        hook = source[source.index("def preserveFirstClientClick"):
                      source.index("def _recordOwnedInteraction")]
        chrome = source[source.index("def configureDialogChrome"):
                        source.index("def setResizable")]
        self.assertIn("WM_WINDOWPOSCHANGING", hook)
        self.assertIn("_stable_dialog_chrome", hook)
        self.assertIn("pos.flags &= ~SWP_FRAMECHANGED", hook)
        self.assertIn("self._stable_dialog_chrome.discard(hwnd)", chrome)
        self.assertIn("self._stable_dialog_chrome.add(hwnd)", chrome)

    def test_native_popup_is_noactivate_at_wndproc_boundary(self):
        source = (ROOT / "DearUIQt" / "backends" / "native_presentation.py").read_text()
        block = source[source.index("def pin_popup"):
                       source.index("def after_frame")]
        self.assertIn("WM_MOUSEACTIVATE", block)
        self.assertIn("MA_NOACTIVATE", block)
        self.assertIn("return 3", block)
        self.assertIn("pos.flags &= ~0x0020", block)
        # Geometry must be normalized before the renderer WNDPROC sees it.
        self.assertLess(block.index("WM_WINDOWPOSCHANGING"),
                        block.index("CallWindowProcW(\n                ctypes.c_void_p(old_proc)"))

    def test_release_includes_m6v_or_newer(self):
        import DearUIQt
        version = tuple(int(part) for part in DearUIQt.__version__.split("."))
        self.assertGreaterEqual(version, (1, 130, 0))


if __name__ == "__main__":
    unittest.main(verbosity=2)
