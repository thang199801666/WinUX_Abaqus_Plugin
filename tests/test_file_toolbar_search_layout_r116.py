"""Regression checks for the file-toolbar inline search reflow."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TOOLBAR = ROOT / "WinUx/ui/components/toolbar.py"


def _source():
    return TOOLBAR.read_text(encoding="utf-8")


def test_navigation_grid_keeps_collapsed_height_when_search_row_opens():
    source = _source()
    block = source.split("class FileToolbar", 1)[1]
    assert "TOOLBAR_GRID_HEIGHT = COLLAPSED_HEIGHT - 4 - TOOLBAR_VERTICAL_OFFSET" in block
    grid = block.split("self._toolbar_grid = QGridLayout(", 1)[1].split("self.table =", 1)[0]
    assert "height=self.TOOLBAR_GRID_HEIGHT" in grid
    assert "height=-1" not in grid


def test_search_expands_only_outer_toolbar_and_file_panel_reflows_once():
    source = _source()
    show = source.split("    def _show_search(self):", 1)[1].split("    def _close_search", 1)[0]
    assert "self._search_popup_frame.show()" in show
    assert "self._container_frame.resize(-1, self.height)" in show
    assert "self.panel.toolbar_height_changed()" in show
    height = source.split("    @property\n    def height(self):", 1)[1].split("    # QToolBar-like", 1)[0]
    assert "self.COLLAPSED_HEIGHT" in height
    assert "self.SEARCH_ROW_HEIGHT if self.search_visible else 0" in height
