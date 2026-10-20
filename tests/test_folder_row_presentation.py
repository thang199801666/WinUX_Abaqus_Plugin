"""Directory changes reuse laid-out rows and never expose origin text."""
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from WinUx.ui.components.explorer_layout import ExplorerLayoutMixin
from WinUx.ui.components.explorer_rendering import ExplorerRenderingMixin
from WinUx.ui.components.explorer_row_registry import ExplorerRowRegistryMixin
from WinUx.ui.components.file_panel import FilePanel


class RowView(ExplorerRenderingMixin, ExplorerRowRegistryMixin):
    def __init__(self):
        self.items = []
        self._text_fit_cache = {}
        self._body_canvas_widget = Mock()
        self._visible_columns = lambda: [{"key": "name"}]
        self._layout_all = Mock()
        self._destroy_body_row = Mock()
        self.created = 0
        self._reset_row_registry()

    def _create_body_row(self, index):
        self.created += 1
        return {"index": index, "texts": {"name": object()}, "value": self.items[index]}

    def _bind_body_row(self, row, index, preserve_geometry=False):
        row["index"] = index
        row["value"] = self.items[index]


class FolderRowPresentationTests(unittest.TestCase):
    def test_panel_does_not_repeat_full_layout_after_set_items(self):
        panel = SimpleNamespace(_pinned_parent=None, current_path="folder", listview=Mock())
        rows = [object()]
        with patch("WinUx.ui.components.file_panel.QRetainedItem"):
            FilePanel._render_items(panel, rows)
        panel.listview.set_items.assert_called_once_with(rows)
        panel.listview._layout_all.assert_not_called()

    def test_folder_swap_rebinds_slots_without_clearing_canvas(self):
        view = RowView()
        view.items = ["a", "b", "c"]
        view._rebuild_body_rows()
        old_rows = list(view._row_items)
        view.items = ["x", "y", "z"]
        view._rebuild_body_rows()
        self.assertEqual(view.created, 3)
        for old, current in zip(old_rows, view._row_items):
            self.assertIs(old, current)
        self.assertEqual([row["value"] for row in view._row_items], view.items)
        view._body_canvas_widget.clear.assert_not_called()

    def test_only_growth_allocates_and_shrink_removes_excess(self):
        view = RowView()
        for count in (3, 5, 2, 0):
            view.items = list(range(count))
            view._rebuild_body_rows()
            self.assertEqual(len(view._row_items), count)
        self.assertEqual(view.created, 5)
        self.assertEqual(view._destroy_body_row.call_count, 5)
        view._body_canvas_widget.clear.assert_not_called()

    def test_first_layout_publishes_position_but_later_layout_preserves_visibility(self):
        row = {"index": 1, "background": "bg", "bottom": "line",
               "texts": {"name": "text"}, "icon": "icon", "pending_layout": True}
        item = object()
        view = SimpleNamespace(
            body_canvas="canvas", _row_items=[row], items=[object(), item], ROW_HEIGHT=24,
            CELL_PADDING=6, _fonts={}, _cell_styles={},
            _visible_columns=lambda: [{"key": "name"}],
            _available_width=lambda: 200, _column_geometry=lambda: {"name": (0, 200)},
            _display_cell_value=lambda *args: "filename.txt",
            _fit_text=lambda text, *args: text, _measure_text=lambda *args: (60, 15),
            _update_selection_draws=Mock(), _update_hover_state=Mock())
        retained = {tag: Mock() for tag in ("canvas", "bg", "line", "text", "icon")}
        with patch("WinUx.ui.components.explorer_layout.QRetainedItem", side_effect=retained.__getitem__):
            ExplorerLayoutMixin._layout_materialized_rows(view)
            first = retained["text"].configure.call_args.kwargs
            self.assertTrue(first["show"])
            self.assertGreaterEqual(first["pos"][1], 24)
            self.assertFalse(row["pending_layout"])
            ExplorerLayoutMixin._layout_materialized_rows(view)
            self.assertNotIn("show", retained["text"].configure.call_args.kwargs)
