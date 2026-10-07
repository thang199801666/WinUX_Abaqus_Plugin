from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STYLE = ROOT / "WinUx" / "dialogs" / "folder_browser_style.py"
FORM = ROOT / "WinUx" / "dialogs" / "local_folder_form.py"


def test_sidebar_branch_indicator_is_geometric_not_font_glyph():
    style = STYLE.read_text(encoding="utf-8")
    form = FORM.read_text(encoding="utf-8")
    assert "def create_branch_indicator" in style
    assert "dpg.draw_triangle" in style
    assert "paint_branch_indicator(indicator, shown)" in form
    assert 'label=chr(GLYPHS["Expanded"])' not in form


def test_sidebar_place_selection_uses_full_row_overlay():
    form = FORM.read_text(encoding="utf-8")
    assert "Full-row background selection/hover" in form
    assert "browser_sidebar_item_container_theme()" in form
    assert 'label="", width=0, height=METRICS.sidebar_row_height' in form
    assert '(METRICS.sidebar_row_height - 16) // 2' in form
    assert 'self._sidebar_text_y(display_label)' in form


def test_sidebar_drive_label_is_separate_from_selection_hit_target():
    form = FORM.read_text(encoding="utf-8")
    assert "label_item = dpg.add_text" in form
    assert "self._set_place_label(label_item, name)" in form
