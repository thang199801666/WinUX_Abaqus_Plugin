"""Additional QFileDialog visual hierarchy guards for 1.1.13."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FORM = ROOT / "WinUx" / "dialogs" / "local_folder_form.py"
STYLE = ROOT / "WinUx" / "dialogs" / "folder_browser_style.py"


def test_empty_and_loading_states_have_dedicated_qt_surface():
    form = FORM.read_text(encoding="utf-8")
    style = STYLE.read_text(encoding="utf-8")
    assert "def _add_empty_state" in form
    assert "browser_empty_state_theme" in form
    assert "def browser_empty_state_theme" in style


def test_footer_status_uses_information_vs_error_palette():
    form = FORM.read_text(encoding="utf-8")
    style = STYLE.read_text(encoding="utf-8")
    assert "def _set_status" in form
    assert "self._status_error_theme" in form
    assert "def browser_status_text_theme" in style
    assert "browser_footer_theme" in form


def test_sidebar_no_longer_depends_on_home_font_glyph():
    form = FORM.read_text(encoding="utf-8")
    assert 'chr(GLYPHS["Home"])' not in form
    assert "image = dpg.add_image(" in form
