from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STYLE = ROOT / "WinUx" / "dialogs" / "folder_browser_style.py"
ICONS = ROOT / "WinUx" / "platform" / "windows_icons.py"


def test_generated_toolbar_icons_bypass_legacy_16px_shell_uploader():
    style = STYLE.read_text(encoding="utf-8")
    icons = ICONS.read_text(encoding="utf-8")
    assert "def _add_native_texture" in icons
    assert "width=width" in icons
    assert "height=height" in icons
    assert "WindowsIconRegistry._add_native_texture(image, tag)" in style
    assert "WindowsIconRegistry._add_texture(image, tag)" not in style[
        style.index("def _generated_folder_selector_icon"):style.index("def address_location_texture")
    ]


def test_generated_toolbar_icons_are_rasterized_to_final_draw_size_once():
    style = STYLE.read_text(encoding="utf-8")
    assert "def _resize_rgba_for_toolbar" in style
    assert 'resize((size, size), resampling)' in style
    assert 'size=20' in style
    assert 'def address_location_texture(path, size=18):' in style
    assert 'folder_selector_generated_{}_{}_{}px' in style
