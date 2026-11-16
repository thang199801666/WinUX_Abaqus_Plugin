"""M6r dialog caption hover stability regressions."""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


class DialogCaptionHoverStabilityTests(unittest.TestCase):
    def test_stable_guard_does_not_schedule_timer_polling(self):
        source = (ROOT / "DearUIQt" / "dialogs" / "qt_dialog.py").read_text()
        start = source.index("def _guard_native_modal_owner_visibility")
        end = source.index("def _synchronize_native_owner_once", start)
        block = source[start:end]
        self.assertNotIn("schedule(120", block)
        self.assertNotIn('schedule = getattr(self.view, "after", None)', block)
        self.assertIn('schedule = getattr(self.view, "after_render", None)', block)
        self.assertIn("if not stable:", block)

    def test_native_repair_is_still_rearmed_from_show_path(self):
        source = (ROOT / "DearUIQt" / "dialogs" / "qt_dialog.py").read_text()
        show_start = source.index("def _show_now")
        show_end = source.index("def show", show_start) if "def show" in source[show_start+1:] else len(source)
        block = source[show_start:show_end]
        self.assertIn("_guard_native_modal_owner_visibility", block)

    def test_release_includes_m6r_or_newer(self):
        import DearUIQt
        version = tuple(int(part) for part in DearUIQt.__version__.split("."))
        self.assertGreaterEqual(version, (1, 126, 0))


if __name__ == "__main__":
    unittest.main(verbosity=2)
