from __future__ import annotations

import inspect
import unittest

from DearUIQt.gui import QtFusionPalette
from WinUx.dialogs.folder_browser_style import BrowserListPalette, METRICS
from WinUx.dialogs.local_folder_form import FolderListView


class ExplorerCenteredHeaderTests(unittest.TestCase):
    def test_header_uses_same_palette_as_reference_job_tables(self):
        self.assertEqual(BrowserListPalette.HEADER_BACKGROUND, QtFusionPalette.TABLE_HEADER)
        self.assertEqual(BrowserListPalette.HEADER_BORDER, QtFusionPalette.TABLE_GRID)
        self.assertEqual(BrowserListPalette.HEADER_TEXT, QtFusionPalette.TABLE_HEADER_TEXT)

    def test_details_header_uses_full_width_centerable_button_cells(self):
        source = inspect.getsource(FolderListView._install_centered_details_header)
        self.assertIn("header_row=False", source)
        self.assertIn("add_button(", source)
        self.assertIn("width=-1", source)
        self.assertIn("height=METRICS.header_height", source)
        self.assertIn("move_item(header, before=first_data_row)", source)

    def test_custom_header_keeps_sorting_semantics(self):
        view = FolderListView.__new__(FolderListView)
        view.sort_column = 0
        view.sort_ascending = True
        calls = []
        view.on_sort = calls.append

        FolderListView._details_header_clicked(view, 0)
        self.assertEqual(calls[-1], [(0, -1)])
        self.assertFalse(view.sort_ascending)

        FolderListView._details_header_clicked(view, 1)
        self.assertEqual(calls[-1], [(2, 1)])
        self.assertEqual(view.sort_column, 2)
        self.assertTrue(view.sort_ascending)

        before = list(calls)
        FolderListView._details_header_clicked(view, 2)  # Type remains presentation-only.
        self.assertEqual(calls, before)

        FolderListView._details_header_clicked(view, 3)
        self.assertEqual(calls[-1], [(1, 1)])

    def test_header_is_taller_than_old_native_caption(self):
        self.assertGreaterEqual(METRICS.header_height, 26)


if __name__ == "__main__":
    unittest.main()
