from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MENU = ROOT / "DearUIQt" / "qt" / "menu.py"


def test_qmenu_uses_optical_vertical_correction_for_icon_and_text():
    source = MENU.read_text(encoding="utf-8")
    assert "ICON_Y_NUDGE = 2" in source
    assert "TEXT_Y_NUDGE = -4" in source
    assert "(self.ROW_HEIGHT - self.ICON_SIZE) // 2 + self.ICON_Y_NUDGE" in source
    assert "(self.ROW_HEIGHT - text_height) / 2.0" in source
    assert "self.TEXT_Y_NUDGE" in source


def test_qmenu_keeps_icon_and_label_on_explicit_absolute_row_coordinates():
    source = MENU.read_text(encoding="utf-8")
    block = source.split("    def _build_row(self, spec, width):", 1)[1].split("    def _set_row_hover", 1)[0]
    assert "pos=(icon_x, icon_y)" in block
    assert "pos=(label_x, label_y)" in block
    assert "with b.table(" not in block
