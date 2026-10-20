from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MENU = ROOT / "DearUIQt" / "qt" / "menu.py"


def source():
    return MENU.read_text(encoding="utf-8")


def test_qmenu_overrides_dearpygui_100px_default_minimum_height():
    src = source()
    assert "min_size=(self._min_width, 1)" in src
    assert "max_size=(self._max_width, 30000)" in src


def test_qmenu_height_is_derived_from_visible_rows_and_separator_metrics():
    src = source()
    assert "WINDOW_PAD_Y = 3" in src
    assert "SEPARATOR_PAD_Y = 2" in src
    assert "SEPARATOR_HEIGHT = 1" in src
    assert "height = self.WINDOW_PAD_Y * 2" in src
    assert "separator_height = self.SEPARATOR_PAD_Y * 2 + self.SEPARATOR_HEIGHT" in src
    assert 'height += separator_height if spec.get("separator") else self.ROW_HEIGHT' in src


def test_qmenu_separator_uses_compact_vertical_padding():
    src = source()
    assert "b.add_spacer(parent=self.tag, height=self.SEPARATOR_PAD_Y)" in src
    assert "backend.mvStyleVar_WindowPadding, 4, 3" in src
