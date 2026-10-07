from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STYLE = ROOT / "WinUx" / "dialogs" / "folder_browser_style.py"
FORM = ROOT / "WinUx" / "dialogs" / "local_folder_form.py"


def test_navigation_icons_use_subtle_alpha_thinning_without_shrinking_footprint():
    source = STYLE.read_text(encoding="utf-8")
    assert "thin_strength=0.0" in source
    assert "ImageFilter.MinFilter(3)" in source
    assert "Image.blend(glyph_alpha, eroded, thin_strength)" in source
    assert '"back": 0.18' in source
    assert '"forward": 0.18' in source
    assert '"up": 0.18' in source
    assert '"refresh": 0.14' in source
    assert '"search": 0.10' in source


def test_toolbar_divider_is_one_pixel_short_and_vertically_centered():
    source = STYLE.read_text(encoding="utf-8")
    block = source[source.index("def create_toolbar_divider"):source.index("def browser_inline_icon_button_theme")]
    assert "dpg.add_drawlist" in block
    assert "line_height = 14" in block
    assert "(height - line_height) * 0.5" in block
    assert "color=(218, 218, 218, 255)" in block
    assert "thickness=1.0" in block


def test_folder_form_uses_drawn_toolbar_divider_not_one_pixel_child_window():
    source = FORM.read_text(encoding="utf-8")
    assert "tool_divider = create_toolbar_divider(location_row)" in source
    assert "parent=location_row, width=1, height=20" not in source
