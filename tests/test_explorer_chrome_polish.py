import unittest

from DearUIQt.gui import QtFusionPalette, QtFusionMetrics
from WinUx.ui.components.explorer.themes import ListViewThemeManager


class ExplorerChromePolishTests(unittest.TestCase):
    def test_explorer_header_uses_table_chrome(self):
        theme = ListViewThemeManager._themes["Explorer"]
        self.assertEqual(theme["header_bg"], QtFusionPalette.TABLE_HEADER)
        self.assertEqual(theme["separator"], QtFusionPalette.TABLE_GRID)
        self.assertEqual(theme["header_bottom_line"], QtFusionPalette.TABLE_BORDER)

    def test_shared_rounding_remains_compact(self):
        self.assertEqual(QtFusionMetrics.FRAME_ROUNDING, 5)


if __name__ == "__main__":
    unittest.main()
