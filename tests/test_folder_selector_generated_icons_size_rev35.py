from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STYLE = ROOT / "WinUx" / "dialogs" / "folder_browser_style.py"
FORM = ROOT / "WinUx" / "dialogs" / "local_folder_form.py"


def test_navigation_toolbar_buttons_render_generated_icons_at_toolbar_size():
    source = STYLE.read_text(encoding="utf-8")
    assert 'width=20, height=20' in source


def test_folder_browser_uses_hd_generated_icons_for_toolbar_controls():
    source = FORM.read_text(encoding="utf-8")
    assert 'navigation_texture("search"), parent=search_icon_slot, width=20, height=20' in source
    assert 'new_folder_texture(), parent=location_row, width=20, height=20' in source
    assert 'view_mode_texture("details"), parent=location_row, width=20, height=20' in source
    assert 'view_mode_texture("list"), parent=location_row, width=20, height=20' in source
    assert 'dpg.add_image(new_folder_texture(), parent=new_folder_row, width=20, height=20)' in source
