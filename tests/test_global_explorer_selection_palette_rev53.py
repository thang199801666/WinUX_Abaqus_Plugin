from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PALETTE = ROOT / "WinUx" / "components" / "qt_style.py"
ITEMS = ROOT / "WinUx" / "widgets" / "item_views.py"
THEMES = ROOT / "WinUx" / "components" / "explorer_themes.py"
FOLDER = ROOT / "WinUx" / "dialogs" / "folder_browser_style.py"


def test_shared_palette_has_light_explorer_selection_roles():
    source = PALETTE.read_text(encoding="utf-8")
    assert "SELECTION_ACTIVE = (204, 232, 255, 255)" in source
    assert "SELECTION_TEXT = (32, 32, 32, 255)" in source
    assert "SELECTION_ACTIVE_HOVER" in source
    assert "SELECTION_ACTIVE_PRESSED" in source


def test_generic_item_views_use_selection_roles_not_primary_button_blue():
    source = ITEMS.read_text(encoding="utf-8")
    assert "selected_fill = p.SELECTION_ACTIVE" in source
    assert "hover = p.SELECTION_ACTIVE_HOVER" in source
    assert "pressed = p.SELECTION_ACTIVE_PRESSED" in source
    assert "text = p.SELECTION_TEXT" in source


def test_main_explorer_jobviewer_and_winscp_themes_share_selection_palette():
    source = THEMES.read_text(encoding="utf-8")
    assert source.count('"selected_fill": QtFusionPalette.SELECTION_ACTIVE') >= 3
    assert source.count('"selected_text": QtFusionPalette.SELECTION_TEXT') >= 3


def test_folder_sidebar_uses_light_selection_roles():
    source = FOLDER.read_text(encoding="utf-8")
    assert "p.SELECTION_ACTIVE" in source
    assert "p.SELECTION_ACTIVE_HOVER" in source
    assert "p.SELECTION_TEXT if selected else p.TEXT" in source
