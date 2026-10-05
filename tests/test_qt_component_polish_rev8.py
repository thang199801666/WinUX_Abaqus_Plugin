from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WINUX = ROOT / "WinUx"


def read(rel):
    return (WINUX / rel).read_text(encoding="utf-8")


def test_tabs_use_flat_shared_edge_qt_chrome():
    src = read("widgets/imgui_qt_style.py")
    block = src.split("def tab_widget_theme", 1)[1].split("def tool_bar_theme", 1)[0]
    assert "mvStyleVar_FrameRounding, 0" in block
    assert "mvStyleVar_FrameBorderSize, 1" in block
    assert "mvStyleVar_ItemSpacing, 0, 0" in block
    assert "mvThemeCol_NavHighlight" in block


def test_settings_navigation_is_flat_qlistview_like():
    theme = read("dialogs/theme.py")
    settings = read("dialogs/settings_form.py")
    block = theme.split("def navigation_theme", 1)[1]
    assert "p.WINDOW)" in block
    assert "p.BORDER_LIGHT" in block
    assert "mvStyleVar_FrameRounding, 0" in block
    assert "width=-1, height=27" in settings
    assert "if key not in self.pages" in settings


def test_path_bar_uses_normal_application_font_instead_of_bold_heading():
    src = read("components/toolbar.py")
    assert 'windir / "Fonts" / "segoeui.ttf"' in src
    assert "dpg.add_font(str(font_path), 14)" in src
    assert "height=26" in src


def test_generic_item_headers_and_context_menus_are_lighter_and_denser():
    src = read("widgets/item_views.py")
    assert "mvThemeCol_TableBorderStrong, p.BORDER" in src
    assert "mvStyleVar_CellPadding, 6, 3" in src
    assert "mvStyleVar_WindowPadding, 4, 3" in src
    assert "mvStyleVar_ItemSpacing, 5, 2" in src
    menu = read("widgets/menu.py")
    assert "ROW_HEIGHT = 23" in menu


def test_dock_title_controls_are_compact_and_glyphs_center_from_control_rect():
    src = read("components/dock_widget.py")
    assert "CONTROL_SIZE = 20" in src
    assert "half = self.CONTROL_SIZE / 2.0" in src
    assert "close_cx = close_x + half" in src
    assert "cy = fy + half" in src


def test_product_version_remains_fixed_at_110():
    assert (ROOT / "VERSION").read_text(encoding="utf-8").strip() == "1.1.0"
