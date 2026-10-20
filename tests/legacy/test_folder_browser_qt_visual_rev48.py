"""Visual-alignment guards for the Qt-like folder selector in WinUx 1.1.24."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STYLE = ROOT / "WinUx" / "dialogs" / "folder_browser_style.py"
FORM = ROOT / "WinUx" / "dialogs" / "local_folder_form.py"
ADDRESS = ROOT / "WinUx" / "dialogs" / "folder_browser_address.py"


def test_address_dropdown_has_real_chevron_instead_of_square_fallback():
    source = STYLE.read_text(encoding="utf-8")
    assert 'key in ("edit_address", "address_menu")' in source
    assert "QComboBox/QFileDialog-style down chevron" in source


def test_toolbar_icons_use_antialiased_cached_textures():
    source = STYLE.read_text(encoding="utf-8")
    assert "def _downsample_icon" in source
    assert 'native_browser_nav_{}_{}_aa' in source
    assert 'native_browser_view_{}_aa' in source
    assert 'native_browser_new_folder_aa' in source


def test_address_and_search_icons_use_centered_slots():
    style = STYLE.read_text(encoding="utf-8")
    form = FORM.read_text(encoding="utf-8")
    address = ADDRESS.read_text(encoding="utf-8")
    assert "def browser_icon_slot_theme" in style
    assert "search_icon_slot = dpg.add_child_window" in form
    assert "clear_slot = dpg.add_child_window" in form
    assert "icon_slot = dpg.add_child_window" in address


def test_sidebar_text_is_centered_from_real_font_metrics():
    source = FORM.read_text(encoding="utf-8")
    assert "def _sidebar_text_y" in source
    assert "dpg.get_text_size" in source
    assert "self._sidebar_text_y(display_label)" in source


def test_qfiledialog_empty_folder_does_not_draw_custom_center_banner():
    source = FORM.read_text(encoding="utf-8")
    assert 'self.empty_text != "This folder is empty."' in source
