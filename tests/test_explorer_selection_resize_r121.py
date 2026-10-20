from types import SimpleNamespace
from unittest.mock import Mock, patch

from WinUx.ui.components.explorer_layout import ExplorerLayoutMixin


def _retained_map(*tags):
    items = {}
    for tag in tags:
        item = Mock()
        item.exists.return_value = True
        items[tag] = item
    return items


def test_resize_repaints_selected_rows_even_when_selection_set_is_unchanged():
    width = [220]
    row = {
        "index": 0,
        "background": "bg",
        "bottom": "line",
        "texts": {"name": "text"},
        "icon": None,
        "pending_layout": False,
        "bounds": None,
    }
    view = SimpleNamespace(
        body_canvas="canvas",
        _row_items=[row],
        items=[SimpleNamespace(data={})],
        selected={0},
        ROW_HEIGHT=24,
        CELL_PADDING=6,
        _fonts={},
        _cell_styles={},
        _visible_columns=lambda: [{"key": "name"}],
        _available_width=lambda: width[0],
        _column_geometry=lambda: {"name": (0, 1000)},
        _display_cell_value=lambda *args: "selected.odb",
        _fit_text=lambda text, *args: text,
        _measure_text=lambda *args: (80, 15),
        _update_selection_draws=Mock(),
        _update_hover_state=Mock(),
    )
    retained = _retained_map("canvas", "bg", "line", "text")

    with patch("WinUx.ui.components.explorer_layout.QRetainedItem", side_effect=retained.__getitem__):
        ExplorerLayoutMixin._layout_materialized_rows(view)
        assert view._update_selection_draws.call_args.kwargs["indices"] == {0}
        first_bounds = row["bounds"]

        view._update_selection_draws.reset_mock()
        width[0] = 480
        ExplorerLayoutMixin._layout_materialized_rows(view)
        assert row["bounds"] != first_bounds
        assert row["bounds"][2] == 480
        assert view._update_selection_draws.call_args.kwargs["indices"] == {0}


def test_resize_does_not_force_geometry_refresh_for_unselected_rows():
    width = [220]
    row = {
        "index": 0,
        "background": "bg",
        "bottom": "line",
        "texts": {"name": "text"},
        "icon": None,
        "pending_layout": False,
        "bounds": None,
    }
    view = SimpleNamespace(
        body_canvas="canvas",
        _row_items=[row],
        items=[SimpleNamespace(data={})],
        selected=set(),
        ROW_HEIGHT=24,
        CELL_PADDING=6,
        _fonts={},
        _cell_styles={},
        _visible_columns=lambda: [{"key": "name"}],
        _available_width=lambda: width[0],
        _column_geometry=lambda: {"name": (0, 1000)},
        _display_cell_value=lambda *args: "normal.odb",
        _fit_text=lambda text, *args: text,
        _measure_text=lambda *args: (80, 15),
        _update_selection_draws=Mock(),
        _update_hover_state=Mock(),
    )
    retained = _retained_map("canvas", "bg", "line", "text")

    with patch("WinUx.ui.components.explorer_layout.QRetainedItem", side_effect=retained.__getitem__):
        ExplorerLayoutMixin._layout_materialized_rows(view)
        assert view._update_selection_draws.call_args.kwargs["indices"] == set()
