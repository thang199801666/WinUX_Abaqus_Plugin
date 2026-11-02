from __future__ import annotations

import inspect
import unittest

from WinUx.dialogs import folder_browser_style
from WinUx.dialogs.local_folder_form import FolderListView


class ExplorerHeaderPolishTests(unittest.TestCase):
    def test_header_background_is_owned_by_full_table_cells(self):
        source = inspect.getsource(FolderListView._install_centered_details_header)
        self.assertIn('highlight_table_cell', source)
        self.assertIn('BrowserListPalette.HEADER_BACKGROUND', source)

    def test_header_buttons_are_transparent_at_rest(self):
        source = inspect.getsource(folder_browser_style.browser_details_theme)
        self.assertIn('ThemeColor.BUTTON: (0, 0, 0, 0)', source)
        self.assertIn('ThemeStyle.BUTTON_TEXT_ALIGN, 0.5, 0.5', source)


if __name__ == '__main__':
    unittest.main()
