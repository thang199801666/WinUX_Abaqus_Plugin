from pathlib import Path

from WinUx.widgets import ImGuiHeaderView, QHeaderView

ROOT = Path(__file__).resolve().parents[1]
WIDGETS = ROOT / "WinUx" / "widgets"


def test_qheader_alias_is_dear_imgui_facade():
    assert QHeaderView is ImGuiHeaderView


def test_item_rows_distinguish_current_active_and_inactive_selection():
    source = (WIDGETS / "item_views.py").read_text(encoding="utf-8")
    for token in (
        "current=False, active=True",
        "p.SELECTION_INACTIVE",
        "current=(key == self.current)",
        "active=self._has_focus",
        "mvStyleVar_FrameBorderSize, 1 if current else 0",
        "def hasFocus",
        "def setFocus",
    ):
        assert token in source


def test_item_views_share_qt_scroller_skin():
    source = (WIDGETS / "item_views.py").read_text(encoding="utf-8")
    assert "from ..components.shared_scroller import add_dpg_scroller_style" in source
    assert source.count("add_dpg_scroller_style(") >= 2


def test_grid_exposes_qheaderview_like_properties():
    source = (WIDGETS / "item_views.py").read_text(encoding="utf-8")
    for token in (
        "class ImGuiHeaderView",
        "def horizontalHeader",
        "def setStretchLastSection",
        "def setSectionsMovable",
        "def setSectionsClickable",
        "def setSectionResizeMode",
        "def resizeSection",
        "QHeaderView = ImGuiHeaderView",
    ):
        assert token in source


def test_grid_exposes_qtable_visual_properties():
    source = (WIDGETS / "item_views.py").read_text(encoding="utf-8")
    for token in (
        "def setAlternatingRowColors",
        "def setShowGrid",
        "def setHeaderVisible",
        "def setSortingEnabled",
        "def selectionMode",
        "def setSelectionMode",
    ):
        assert token in source


def test_selected_grid_rows_recolor_all_display_cells():
    source = (WIDGETS / "item_views.py").read_text(encoding="utf-8")
    for token in (
        "def qt_item_text_theme",
        "p.HIGHLIGHT_TEXT",
        "self._cell_text_items",
        "for text_item in self._cell_text_items.get(key, ())",
    ):
        assert token in source


def test_item_view_refresh_preserves_scroll_offsets():
    source = (WIDGETS / "item_views.py").read_text(encoding="utf-8")
    assert source.count("get_y_scroll(self.tag)") >= 2
    assert source.count("set_y_scroll(self.tag, old_scroll_y)") >= 2
    assert "get_x_scroll(self.tag)" in source
    assert "set_x_scroll(self.tag, old_scroll_x)" in source
