from __future__ import annotations

import inspect
import unittest
from unittest.mock import Mock, MagicMock
from types import SimpleNamespace

from WinUx.dialogs.local_folder_form import FolderListView
from WinUx.dialogs import folder_browser_style
from WinUx.dialogs.folder_browser_style import METRICS
from WinUx.dialogs.folder_browser_style import BrowserListPalette


class ExplorerFlatHeaderTests(unittest.TestCase):
    def _view(self, column=0, ascending=True):
        view = FolderListView.__new__(FolderListView)
        view.sort_column = column
        view.sort_ascending = ascending
        view._details_header_cells = []
        return view

    def test_sort_indicator_is_visible_on_active_column(self):
        view = self._view(0, True)
        self.assertEqual(view._details_header_label(0, "Name"), "Name  ▲")
        self.assertEqual(view._details_header_label(1, "Size"), "Size")
        view.sort_ascending = False
        self.assertEqual(view._details_header_label(0, "Name"), "Name  ▼")

    def test_size_and_date_sort_mapping_keep_indicator(self):
        view = self._view(2, True)
        self.assertEqual(view._details_header_label(1, "Size"), "Size  ▲")
        self.assertEqual(view._details_header_label(3, "Date modified"), "Date modified")
        view.sort_column = 1
        self.assertEqual(view._details_header_label(3, "Date modified"), "Date modified  ▲")

    def test_header_click_does_not_repaint_before_sort_callback(self):
        view = self._view(0, True)
        calls = []
        refreshes = []
        view.on_sort = calls.append
        view._refresh_details_header_labels = lambda: refreshes.append(True)
        FolderListView._details_header_clicked(view, 0)
        self.assertEqual(refreshes, [])
        self.assertEqual(calls, [[(0, -1)]])

    def test_header_theme_is_flat_not_four_raised_buttons(self):
        source = inspect.getsource(folder_browser_style.browser_details_theme)
        self.assertIn("ThemeStyle.FRAME_BORDER_SIZE: 0", source)
        self.assertIn("ThemeStyle.BUTTON_TEXT_ALIGN, 0.5, 0.5", source)
        self.assertIn("ThemeColor.BORDER: (0, 0, 0, 0)", source)

    def test_header_separators_are_inside_table_cells_not_behind_table(self):
        view = self._view()
        view.tag = "host"
        view.backend = MagicMock()
        table = Mock(tag="table")
        table.nativeRow.return_value = None
        view.backend.add_drawlist.side_effect = ["first", "second", "third"]

        view._install_centered_details_header(
            table, ["Name", "Size", "Type", "Date modified"])

        self.assertEqual(view.backend.group.call_count, 4)
        self.assertEqual(view._details_header_separators, ["first", "second", "third"])
        self.assertEqual(view.backend.draw_line.call_count, 3)
        for call in view.backend.add_drawlist.call_args_list:
            self.assertNotIn("parent", call.kwargs)  # inherits the header cell group
            self.assertNotIn("pos", call.kwargs)  # native layout follows resizing
            self.assertEqual(call.kwargs["width"], METRICS.details_cell_padding_x + 2)
        for call in view.backend.draw_line.call_args_list:
            self.assertEqual(call.kwargs["thickness"], 1.0)
            self.assertEqual(call.args[0][0], METRICS.details_cell_padding_x)
        for call in view.backend.add_button.call_args_list:
            self.assertEqual(call.kwargs["width"], -1)

    def test_hover_selection_and_clear_account_for_native_header_row(self):
        view = self._view()
        view.backend = Mock()
        view._details_table = SimpleNamespace(tag="table", _deleted=False)
        view._details_header_row = "header"
        view.details_mode = True
        view._row_index = {"first": 0, "third": 2}
        view._row_enabled = {}
        view._state = SimpleNamespace(selected=set())
        view._has_focus = True
        view._hovered_row_key = "third"
        view._paint_row_background("third")
        view.backend.highlight_table_row.assert_called_with(
            "table", 3, BrowserListPalette.HOVER)

        view._state.selected = {"third"}
        view._paint_row_background("third")
        view.backend.highlight_table_row.assert_called_with(
            "table", 3, BrowserListPalette.SELECTED_HOVER)

        view._state.selected.clear()
        view._hovered_row_key = None
        view._paint_row_background("third")
        view.backend.unhighlight_table_row.assert_called_with("table", 3)

        view._hovered_row_key = "first"
        view._paint_row_background("first")
        view.backend.highlight_table_row.assert_called_with(
            "table", 1, BrowserListPalette.HOVER)


if __name__ == "__main__":
    unittest.main()
