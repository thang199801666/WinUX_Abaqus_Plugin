from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STYLE = ROOT / "WinUx" / "dialogs" / "folder_browser_style.py"
FORM = ROOT / "WinUx" / "dialogs" / "local_folder_form.py"


def test_plain_folder_texture_exists_for_list_rows():
    source = STYLE.read_text(encoding="utf-8")
    assert "def folder_item_texture" in source
    assert 'tag = "native_browser_folder_item_aa"' in source


def test_folder_list_uses_plain_folder_texture_in_name_column():
    source = FORM.read_text(encoding="utf-8")
    assert "folder_item_texture" in source
    assert "texture = folder_item_texture()" in source
