from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STYLE = (ROOT / "WinUx" / "dialogs" / "folder_browser_style.py").read_text(encoding="utf-8")
FORM = (ROOT / "WinUx" / "dialogs" / "local_folder_form.py").read_text(encoding="utf-8")


def test_name_selectable_owns_hover_and_selected_surface():
    block = FORM.split("def _sync_selection_visuals", 1)[1].split("def _sorted", 1)[0]
    assert "highlight_table_row" not in block
    assert "unhighlight_table_row" not in block
    assert "spans all table columns" in block


def test_name_selectable_has_identical_outer_geometry_in_all_states():
    block = STYLE.split("def browser_name_item_theme", 1)[1].split("def browser_selected_text_theme", 1)[0]
    assert "ThemeStyle.SELECTABLE_TEXT_ALIGN: (0.0, 0.5)" in block
    assert "ThemeStyle.FRAME_PADDING: (5, 2)" in block
    assert "ThemeStyle.FRAME_BORDER_SIZE: 0" in block


def test_active_selection_uses_explorer_light_palette_and_dark_text():
    block = STYLE.split("def browser_name_item_theme", 1)[1].split("def browser_selected_text_theme", 1)[0]
    assert "fill = p.SELECTION_ACTIVE" in block
    assert "text = p.SELECTION_TEXT" in block
    selected_text = STYLE.split("def browser_selected_text_theme", 1)[1].split("def browser_sidebar_item_text_theme", 1)[0]
    assert "QtFusionPalette.SELECTION_TEXT if active" in selected_text


def test_icon_and_label_share_true_row_center():
    assert "icon_y = max(0, (METRICS.row_height - 16) // 2)" in FORM
    assert "// 2 + 1" not in FORM
    assert "height=METRICS.row_height" in FORM
