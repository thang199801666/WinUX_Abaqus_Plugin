"""Regression: auto-height dialog rows must not amplify their own scroll extent.

A Dear PyGui table with height=-1 fills all remaining viewport height.
Putting that table inside an auto-resizing child window can make the child's
computed height grow every frame, causing an endlessly shrinking scrollbar.
"""
from pathlib import Path
from unittest.mock import Mock, patch

from DearUIQt.widgets import QFrame
from DearUIQt.layouts import QVBoxLayout, QGridLayout


ROOT = Path(__file__).resolve().parents[1]


def _build_grid(*, auto_height=False, grid_height=-1, fixed_nested=False):
    backend = Mock()
    backend.add_child_window.side_effect = (i for i in range(100, 120))
    backend.add_group.side_effect = (i for i in range(200, 220))
    backend.add_table.side_effect = (i for i in range(300, 320))
    with patch.object(QFrame, "_refresh_style", lambda self: None):
        outer = QFrame(backend=backend, height=0 if auto_height else 200,
                       auto_resize_y=auto_height)
        parent = outer
        if fixed_nested:
            parent = QFrame(backend=backend, parent=outer, height=100)
        layout = QVBoxLayout(parent=parent)
        grid = QGridLayout(2, parent=layout, height=grid_height)
    return backend, outer, grid


def test_auto_height_frame_uses_intrinsic_height_for_descendant_grid():
    backend, outer, grid = _build_grid(auto_height=True)
    assert outer._auto_resize_y is True
    assert grid.parent.parent is outer
    assert backend.add_table.call_args.kwargs["height"] == 0


def test_fixed_height_frame_still_fills_remaining_space():
    backend, outer, grid = _build_grid(auto_height=False)
    assert outer._auto_resize_y is False
    assert backend.add_table.call_args.kwargs["height"] == -1


def test_fixed_inner_frame_breaks_auto_height_propagation():
    backend, _, _ = _build_grid(auto_height=True, fixed_nested=True)
    assert backend.add_table.call_args.kwargs["height"] == -1


def test_explicit_grid_height_is_preserved_inside_auto_height_frame():
    for height in (0, 30, 120):
        backend, _, _ = _build_grid(auto_height=True, grid_height=height)
        assert backend.add_table.call_args.kwargs["height"] == height


def test_transfer_rows_use_intrinsic_height_without_disabling_scroll_on_host():
    src = (ROOT / "WinUx/dialogs/transfer_center_form.py").read_text(encoding="utf-8")
    row = src.split("def _add_row(", 1)[1].split("def _flush_row_creations(", 1)[0]
    assert "auto_resize_y=True" in row
    grid = row.split("controls_grid = QGridLayout(", 1)[1].split("progress_cell =", 1)[0]
    assert "height=0" in grid
    assert "no_scrollbar=True" in row  # Individual cards must not scroll.
    host = src.split("self._rows_host_frame = QFrame(", 1)[1].split("self.rows_host =", 1)[0]
    assert "no_scrollbar=False" in host  # Many transfers must still scroll.


def test_other_content_height_forms_do_not_use_stretch_to_end_grids():
    dialog = (ROOT / "DearUIQt/dialogs/qt_dialog.py").read_text(encoding="utf-8")
    form = dialog.split("def labeled_widget(", 1)[1].split("def _focus_text_editor_now(", 1)[0]
    assert "height=0" in form
    extract = (ROOT / "WinUx/dialogs/odb_extract_form.py").read_text(encoding="utf-8")
    axes = extract.split("axes_layout = QGridLayout(", 1)[1].split("self.own_widget(axes_layout)", 1)[0]
    assert "height=0" in axes
