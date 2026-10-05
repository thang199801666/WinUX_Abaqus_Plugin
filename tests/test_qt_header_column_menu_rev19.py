from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
COMP = ROOT / "WinUx" / "components"


def read(name):
    return (COMP / name).read_text(encoding="utf-8")


def test_header_right_click_exposes_column_visibility_and_auto_width():
    menu = read("explorer_context_menu.py")
    dispatch = read("explorer_pointer_dispatch.py")
    assert 'label="Auto Width"' in menu
    assert "_on_header_column_check" in menu
    assert "self.set_column_visible(key, bool(app_data))" in menu
    assert "self._show_header_context_menu()" in dispatch


def test_auto_width_scales_all_visible_columns_and_keeps_exact_sum():
    columns = read("explorer_columns.py")
    layout = read("explorer_layout.py")
    assert "def set_auto_width" in columns
    assert "def _fit_columns_to_width(self, available)" in columns
    assert "def _fit_columns_auto_width(self, available, locked_key=None)" in columns
    assert "sink = next((k for k in reversed(keys) if k != locked_key), keys[-1])" in columns
    assert "available - used" in columns
    assert "if self.auto_width_enabled:" in layout
    assert "self._fit_columns_auto_width(available)" in layout


def test_manual_resize_and_double_click_preserve_exact_auto_width():
    dispatch = read("explorer_pointer_dispatch.py")
    columns = read("explorer_columns.py")
    assert "locked_key=self._resize_key" in dispatch
    assert "locked_key=key" in columns


def test_header_menu_never_allows_hiding_every_column():
    menu = read("explorer_context_menu.py")
    columns = read("explorer_columns.py")
    assert "visible_count > 1" in menu
    assert "if len(self._visible_columns()) <= 1:" in columns
