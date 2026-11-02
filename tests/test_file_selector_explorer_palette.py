from __future__ import annotations

import unittest
from types import SimpleNamespace

from WinUx.dialogs.folder_browser_style import BrowserListPalette
from WinUx.dialogs.local_folder_form import FolderListView


class _Table:
    tag = "details"
    _deleted = False


class _Backend:
    def __init__(self):
        self.highlighted = []
        self.cleared = []

    def highlight_table_row(self, tag, index, color):
        self.highlighted.append((tag, index, color))

    def unhighlight_table_row(self, tag, index):
        self.cleared.append((tag, index))


class ExplorerPaletteTests(unittest.TestCase):
    def _view(self):
        view = FolderListView.__new__(FolderListView)
        view._details_table = _Table()
        view._row_index = {"file": 0}
        view._hovered_row_key = None
        view._row_enabled = {"file": True}
        view._state = SimpleNamespace(selected=set(), current=None, anchor=None)
        view._has_focus = True
        view.backend = _Backend()
        return view

    def test_palette_uses_light_explorer_selection_with_dark_text(self):
        self.assertEqual(BrowserListPalette.HOVER, (229, 243, 255, 255))
        self.assertEqual(BrowserListPalette.SELECTED, (204, 232, 255, 255))
        self.assertEqual(BrowserListPalette.SELECTED_TEXT, (0, 0, 0, 255))
        self.assertNotEqual(BrowserListPalette.HOVER, BrowserListPalette.SELECTED)

    def test_hover_is_quieter_than_selection(self):
        view = self._view()
        view._hovered_row_key = "file"
        FolderListView._paint_row_background(view, "file")
        self.assertEqual(view.backend.highlighted[-1][2], BrowserListPalette.HOVER)

        view._state.selected = {"file"}
        view._hovered_row_key = None
        FolderListView._paint_row_background(view, "file")
        self.assertEqual(view.backend.highlighted[-1][2], BrowserListPalette.SELECTED)

    def test_selected_hover_and_inactive_selection_have_distinct_surfaces(self):
        view = self._view()
        view._state.selected = {"file"}
        view._hovered_row_key = "file"
        FolderListView._paint_row_background(view, "file")
        self.assertEqual(view.backend.highlighted[-1][2], BrowserListPalette.SELECTED_HOVER)

        view._has_focus = False
        view._hovered_row_key = None
        FolderListView._paint_row_background(view, "file")
        self.assertEqual(view.backend.highlighted[-1][2], BrowserListPalette.INACTIVE)


if __name__ == "__main__":
    unittest.main()
