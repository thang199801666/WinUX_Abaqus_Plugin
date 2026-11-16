"""M32 native popup owner activation stability regressions."""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


class PopupOwnerActivationGuardTests(unittest.TestCase):
    def test_popup_installs_owner_nonclient_guard(self):
        source = (ROOT / "DearUIQt" / "backends" / "native_presentation.py").read_text()
        block = source[source.index("def _ensure_popup_owner_guard"):
                       source.index("def pin_popup")]
        self.assertIn("NativeCaptionHoverGuard", source)
        self.assertIn("self.popup_geometry", block)
        self.assertIn("activation_guard.suppress", block)
        self.assertIn("message) == 0x0086", block)
        self.assertIn("CallWindowProcW", block)

    def test_popup_owner_guard_is_restored_on_shutdown(self):
        source = (ROOT / "DearUIQt" / "backends" / "native_presentation.py").read_text()
        close = source[source.index("def close(self):"): ]
        self.assertIn("_popup_owner_procs", close)
        self.assertIn("setter(wintypes.HWND(hwnd), -4, old_proc)", close)
        self.assertIn("self._popup_owner_procs.clear()", close)

    def test_release_is_m32_or_newer(self):
        import DearUIQt
        version = tuple(int(part) for part in DearUIQt.__version__.split("."))
        self.assertGreaterEqual(version, (1, 156, 0))


if __name__ == "__main__":
    unittest.main(verbosity=2)
