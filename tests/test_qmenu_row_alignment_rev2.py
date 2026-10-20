from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MENU = ROOT / "DearUIQt" / "widgets" / "menu.py"


def source():
    return MENU.read_text(encoding="utf-8")


def row_block():
    src = source()
    return src.split("    def _build_row(self, spec, width):", 1)[1].split(
        "    def _set_row_hover", 1)[0]


def test_qmenu_rows_use_one_pixel_coordinate_system_not_imgui_table_cells():
    block = row_block()
    assert "with b.table(" not in block
    assert "pos=(check_x, 0)" in block
    assert "pos=(icon_x, icon_y)" in block
    assert "pos=(label_x, label_y)" in block
    assert "pos=(0, 0)" in block
    assert "self._arrow_offsets[arrow_item] = float(arrow_x)" in block


def test_qmenu_icon_and_text_share_a_centered_row_axis():
    src = source()
    assert "ROW_HEIGHT = 23" in src
    assert "ICON_SIZE = 16" in src
    assert "ICON_SLOT = 22" in src
    assert "ICON_Y_NUDGE = 2" in src
    assert "TEXT_Y_NUDGE = -4" in src
    assert "(self.ROW_HEIGHT - self.ICON_SIZE) // 2 + self.ICON_Y_NUDGE" in src
    assert "(self.ROW_HEIGHT - text_height) / 2.0" in src


def test_qmenu_labels_keep_a_fixed_x_axis_without_separate_check_gutter():
    src = source()
    assert "CHECK_SLOT = 0" in src
    assert "check_slot = 0" in src
    assert "label_x = self.ROW_PAD_X + check_slot + self.ICON_SLOT + self.LABEL_PAD" in src
    assert '"icon": icon_item' in src
    assert "width=self.ICON_SLOT" in src
    assert "show=not checked" in src


def test_qmenu_width_uses_real_font_metrics_when_available():
    src = source()
    assert 'self.backend.get_text_size(text or "Ag")' in src
    assert "fixed + longest" in src
