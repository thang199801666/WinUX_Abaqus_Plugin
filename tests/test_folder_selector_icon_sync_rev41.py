from pathlib import Path

from PIL import Image, ImageChops, ImageOps

ROOT = Path(__file__).resolve().parents[1]
ICONS = ROOT / "WinUx" / "Resources" / "folder_selector_icons"
STYLE = ROOT / "WinUx" / "dialogs" / "folder_browser_style.py"


def test_back_and_forward_assets_are_exact_horizontal_mirrors():
    back = Image.open(ICONS / "back.png").convert("RGBA")
    forward = Image.open(ICONS / "forward.png").convert("RGBA")
    assert back.size == (64, 64)
    assert forward.size == (64, 64)
    mirrored = ImageOps.mirror(back)
    assert ImageChops.difference(mirrored, forward).getbbox() is None


def test_folder_selector_generated_icon_family_is_normalized_to_64px():
    expected = {
        "back.png", "forward.png", "up.png", "folder.png", "chevron.png",
        "refresh.png", "search.png", "new_folder.png", "details.png",
        "list.png",
    }
    for name in expected:
        image = Image.open(ICONS / name)
        assert image.size == (64, 64), name
        assert image.mode in ("RGBA", "LA", "P"), name


def test_address_folder_uses_generated_folder_master():
    source = STYLE.read_text(encoding="utf-8")
    assert '"folder": "folder.png"' in source
    block = source[source.index("def folder_item_texture"):source.index("def new_folder_texture")]
    assert '_generated_folder_selector_icon("folder", size=size)' in block


def test_grid_and_list_are_flat_monochrome_small_toolbar_icons():
    source = STYLE.read_text(encoding="utf-8")
    assert '"details", "list"' in source
    assert '"details": 0.12' in source
    assert '"list": 0.12' in source
