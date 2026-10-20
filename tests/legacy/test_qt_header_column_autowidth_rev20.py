from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
COMP = ROOT / "WinUx" / "components"


def read(name):
    return (COMP / name).read_text(encoding="utf-8")


def test_available_width_uses_owner_viewport_not_column_sized_header_canvas():
    columns = read("explorer_columns.py")
    method = columns.split("def _available_width(self):", 1)[1].split("def _ensure_column_widths", 1)[0]
    assert "get_item_rect_size(self.body_window)" in method
    assert "get_item_rect_size(self.header_canvas)" not in method


def test_header_surface_fills_visible_listview_width():
    layout = read("explorer_layout.py")
    assert "header_width = max(total_width, max(1.0, viewport_width - 1.0))" in layout
    assert "int(round(header_width))" in layout


def test_auto_width_still_reacts_to_owner_width_changes():
    layout = read("explorer_layout.py")
    assert "abs(available - self._last_available_width) >= 1.0" in layout
    assert "self._fit_columns_auto_width(available)" in layout
