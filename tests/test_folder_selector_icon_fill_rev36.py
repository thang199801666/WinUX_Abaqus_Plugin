from pathlib import Path
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
ICON_DIR = ROOT / "WinUx" / "Resources" / "folder_selector_icons"
STYLE = ROOT / "WinUx" / "dialogs" / "folder_browser_style.py"
FORM = ROOT / "WinUx" / "dialogs" / "local_folder_form.py"

MIN_SIZES = {
    "back.png": (28, 46),
    "forward.png": (46, 30),
    "up.png": (40, 46),
    "refresh.png": (44, 46),
    "search.png": (46, 44),
    "new_folder.png": (50, 40),
    "details.png": (50, 48),
    "list.png": (50, 30),
}



def test_folder_selector_icon_assets_fill_more_of_the_canvas():
    for name, (min_w, min_h) in MIN_SIZES.items():
        img = Image.open(ICON_DIR / name).convert("RGBA")
        assert img.size == (64, 64), (name, img.size)
        bbox = img.getchannel("A").getbbox()
        assert bbox is not None, name
        width = bbox[2] - bbox[0]
        height = bbox[3] - bbox[1]
        assert width >= min_w, (name, width, min_w)
        assert height >= min_h, (name, height, min_h)


def test_folder_selector_toolbar_uses_larger_icon_render_sizes():
    style_source = STYLE.read_text(encoding="utf-8")
    form_source = FORM.read_text(encoding="utf-8")
    assert 'width=20, height=20,' in style_source
    assert 'navigation_texture("search"), parent=search_icon_slot, width=20, height=20' in form_source
    assert 'new_folder_texture(), parent=location_row, width=20, height=20' in form_source
    assert 'view_mode_texture("details"), parent=location_row, width=20, height=20' in form_source
    assert 'view_mode_texture("list"), parent=location_row, width=20, height=20' in form_source
    assert 'dpg.add_image(new_folder_texture(), parent=new_folder_row, width=20, height=20)' in form_source
