"""Qt/Fusion visual regressions for folder browser 1.1.11."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FORM = ROOT / "WinUx" / "dialogs" / "local_folder_form.py"
STYLE = ROOT / "WinUx" / "dialogs" / "folder_browser_style.py"


def test_toolbar_navigation_uses_dpi_stable_generated_glyphs():
    style = STYLE.read_text(encoding="utf-8")
    assert "def navigation_texture(name):" in style
    assert "dpg.add_image_button(" in style
    assert "navigation_texture(name)" in style


def test_search_is_qlineedit_like_with_embedded_icon_and_clear_action():
    source = FORM.read_text(encoding="utf-8")
    assert 'navigation_texture("search")' in source
    assert 'navigation_texture("clear")' in source
    assert "self.clear_search_button" in source
    assert "def _clear_search" in source
    assert "def _search_changed" in source


def test_selection_bar_has_qframe_like_top_separator():
    source = FORM.read_text(encoding="utf-8")
    assert "selection_separator = dpg.add_separator" in source
    assert "browser_separator_theme()" in source
