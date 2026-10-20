"""Qt/Fusion polish guards for folder browser 1.1.12."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FORM = ROOT / "WinUx" / "dialogs" / "local_folder_form.py"
STYLE = ROOT / "WinUx" / "dialogs" / "folder_browser_style.py"


def test_search_field_has_qlineedit_focus_frame_and_inline_clear_button_theme():
    form = FORM.read_text(encoding="utf-8")
    style = STYLE.read_text(encoding="utf-8")
    assert "self._search_focus_theme = browser_field_shell_theme(focused=True)" in form
    assert "def _bind_search_focus" in form
    assert "browser_inline_icon_button_theme" in form
    assert "def browser_inline_icon_button_theme" in style


def test_navigation_icons_have_disabled_qt_palette_variants():
    form = FORM.read_text(encoding="utf-8")
    style = STYLE.read_text(encoding="utf-8")
    assert "def navigation_disabled_texture(name)" in style
    assert 'navigation_disabled_texture("Back")' in form
    assert 'navigation_disabled_texture("Forward")' in form
    assert 'navigation_disabled_texture("Up")' in form


def test_details_view_avoids_imgui_grid_lines():
    form = FORM.read_text(encoding="utf-8")
    assert "borders_innerH=False, borders_innerV=False" in form


def test_folder_dialog_minimum_size_preserves_qt_toolbar_spacing():
    form = FORM.read_text(encoding="utf-8")
    assert "min_size=(700, 430)" in form
