from pathlib import Path
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
ICON_DIR = ROOT / "WinUx" / "Resources" / "folder_selector_icons"
FILES = [
    "back.png", "forward.png", "up.png", "refresh.png", "search.png",
    "new_folder.png", "details.png", "list.png", "drive.png", "chevron.png",
]


def test_folder_selector_hd_icon_assets_exist_and_keep_master_size():
    for name in FILES:
        path = ICON_DIR / name
        assert path.is_file(), name
        img = Image.open(path).convert("RGBA")
        assert img.size == (64, 64), (name, img.size)
        bbox = img.getchannel("A").getbbox()
        assert bbox is not None, name
        # The generated glyph must have useful transparent padding but still
        # fill most of the toolbar texture.
        width = bbox[2] - bbox[0]
        height = bbox[3] - bbox[1]
        assert max(width, height) >= 40, (name, bbox)
