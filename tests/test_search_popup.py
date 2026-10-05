"""Regression checks for the compact file-toolbar search popup."""

from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
TOOLBAR = ROOT / "WinUx" / "components" / "toolbar.py"


class SearchPopupTests(unittest.TestCase):
    def test_search_is_anchored_beneath_toolbar(self):
        source = TOOLBAR.read_text(encoding="utf-8")
        self.assertIn("self.search_popup = dpg.add_child_window", source)
        self.assertIn("parent=self.container", source)
        self.assertIn("SEARCH_ROW_HEIGHT = 32", source)
        self.assertIn("self.panel.toolbar_height_changed()", source)
        self.assertNotIn("_search_popup_position", source)


    def test_close_button_callback_has_only_dpg_callback_arguments(self):
        source = TOOLBAR.read_text(encoding="utf-8")
        self.assertIn(
            "def _hide_search(self, sender=None, app_data=None, user_data=None):",
            source,
        )
        self.assertNotIn(
            "def _hide_search(self, sender=None, app_data=None, user_data=None, clear=True):",
            source,
        )
        self.assertIn("def _close_search(self, clear=True):", source)

    def test_search_focus_is_deferred_for_visible_caret(self):
        source = TOOLBAR.read_text(encoding="utf-8")
        self.assertIn("dpg.focus_item(self.search_input)", source)
        self.assertIn("dpg.set_frame_callback", source)
        self.assertIn("frame + 1", source)
        self.assertIn("frame + 2", source)

    def test_search_popup_has_dedicated_compact_theme(self):
        source = TOOLBAR.read_text(encoding="utf-8")
        self.assertIn("def search_popup_theme", source)
        self.assertIn("mvStyleVar_WindowRounding", source)
        self.assertIn("def search_input_theme", source)
        self.assertIn("mvStyleVar_FrameRounding", source)
        self.assertIn('label="x"', source)
        self.assertNotIn('×', source)


if __name__ == "__main__":
    unittest.main()
