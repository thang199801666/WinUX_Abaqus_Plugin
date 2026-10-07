from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STYLE = ROOT / "WinUx" / "dialogs" / "folder_browser_style.py"
ADDRESS = ROOT / "WinUx" / "dialogs" / "folder_browser_address.py"
FORM = ROOT / "WinUx" / "dialogs" / "local_folder_form.py"


def test_folder_selector_prefers_hd_generated_toolbar_icons_in_code():
    source = STYLE.read_text(encoding="utf-8")
    assert "def _generated_folder_selector_icon" in source
    assert "FOLDER_SELECTOR_MASTER_SIZE = 64" in source
    assert "generated = _generated_folder_selector_icon(key, disabled=disabled, size=20)" in source
    assert "if generated:" in source
    assert "return generated" in source
    assert 'return (_generated_folder_selector_icon("new_folder", size=20)' in source
    assert 'or _crisp_toolbar_icon("new_folder")' in source


def test_folder_selector_uses_generated_drive_icon_for_address_roots():
    style = STYLE.read_text(encoding="utf-8")
    address = ADDRESS.read_text(encoding="utf-8")
    form = FORM.read_text(encoding="utf-8")
    assert "def address_location_texture(path, size=18):" in style
    assert '_generated_folder_selector_icon("drive", size=size)' in style
    assert "address_location_texture(dialog._current_path, size=18)" in address
    assert "texture_tag=address_location_texture(candidate, size=18)" in form
