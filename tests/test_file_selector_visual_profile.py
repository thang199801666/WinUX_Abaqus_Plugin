from __future__ import annotations

import inspect
import unittest

from WinUx.dialogs import folder_browser_style as style
from WinUx.dialogs.local_folder_form import LocalPathDialog


class FileSelectorVisualProfileTests(unittest.TestCase):
    def test_win11_density_profile(self):
        metrics = style.METRICS
        self.assertEqual(metrics.control_height, 26)
        self.assertGreaterEqual(metrics.sidebar_width, 184)
        self.assertEqual(metrics.sidebar_row_height, 26)
        self.assertEqual(metrics.row_height, 28)
        self.assertEqual(metrics.header_height, 26)
        self.assertEqual(metrics.selection_height, 74)

    def test_selection_palette_is_quiet_and_readable(self):
        palette = style.BrowserListPalette
        self.assertEqual(palette.SELECTED_TEXT, (0, 0, 0, 255))
        self.assertGreater(palette.HOVER[0], palette.SELECTED[0])
        self.assertGreater(palette.HOVER[1], palette.SELECTED[1])
        self.assertNotEqual(palette.SIDEBAR_BACKGROUND, palette.BACKGROUND)

    def test_controls_use_soft_rounding(self):
        for func in (
            style.browser_field_shell_theme,
            style.browser_action_theme,
            style.browser_sidebar_row_theme,
            style.browser_tool_button_theme,
        ):
            source = inspect.getsource(func)
            self.assertIn('ROUNDING', source)
            self.assertRegex(source, r'ROUNDING:\s*[45]')

    def test_dialog_minimum_size_supports_wider_navigation_pane(self):
        source = inspect.getsource(LocalPathDialog.__init__)
        self.assertIn('setMinimumSize(680, 420)', source)

    def test_explorer_visual_balance_profile(self):
        metrics = style.METRICS
        self.assertEqual(metrics.toolbar_height, 36)
        self.assertEqual(metrics.scrollbar_width, 10)
        self.assertGreaterEqual(metrics.size_column_width, 84)
        self.assertGreaterEqual(metrics.type_column_width, 152)
        self.assertGreaterEqual(metrics.date_column_width, 132)
        self.assertLess(style.BrowserListPalette.SIDEBAR_BACKGROUND[0], 250)

    def test_default_dialog_is_roomier_than_minimum(self):
        source = inspect.getsource(LocalPathDialog.__init__)
        self.assertIn('760, 480', source)
        self.assertIn('preferred_size = (760, 480)', source)


if __name__ == '__main__':
    unittest.main()
