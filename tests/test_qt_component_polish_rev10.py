from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WINUX = ROOT / "WinUx"


def read(rel):
    return (WINUX / rel).read_text(encoding="utf-8")


def test_file_panels_use_compact_qtreeview_and_status_metrics():
    panel = read("components/file_panel.py")
    view = read("view.py")
    assert "STATUS_HEIGHT = 20" in panel
    assert "FILE_STATUS_HEIGHT = 20" in view
    assert "row_height=23, header_height=26" in panel


def test_explorer_header_font_and_edges_match_compact_qheaderview():
    rendering = read("components/explorer_rendering.py")
    themes = read("components/explorer_themes.py")
    assert 'fonts["header"] = dpg.add_font(path, 14)' in rendering
    assert '"header_top_line": QtFusionPalette.BASE' in themes
    assert '"header_bottom_line": QtFusionPalette.BORDER_LIGHT' in themes


def test_floating_tool_windows_use_qt_fusion_chrome_not_imgui_rounding():
    src = read("view.py")
    assert "mvThemeCol_TitleBgActive, QtFusionPalette.TITLE_ACTIVE" in src
    assert "mvStyleVar_WindowRounding, 1" in src
    assert "mvStyleVar_WindowPadding, 0, 0" in src
    assert "mvStyleVar_WindowRounding, 8" not in src


def test_settings_groupboxes_are_lightweight_sections_not_heading_cards():
    style = read("widgets/imgui_qt_style.py")
    dialog = read("dialogs/qt_dialog.py")
    block = style.split("def group_box_theme", 1)[1].split("def spin_editor_theme", 1)[0]
    assert "p.BORDER_LIGHT" in block
    assert "mvStyleVar_WindowPadding, 8, 6" in block
    section = dialog.split("def section", 1)[1].split("def invoke_default", 1)[0]
    assert "heading_font" not in section


def test_dock_tabs_use_compact_continuous_qtabbar_geometry():
    src = read("components/dock_manager.py")
    assert "TAB_HEIGHT = 24" in src
    assert "TAB_GAP = 0" in src
    assert "TAB_PADDING_X = 9" in src
    assert "QtFusionPalette.BORDER_LIGHT" in src


def test_statusbar_uses_alternate_qt_surface_and_one_pixel_vertical_padding():
    src = read("widgets/imgui_qt_style.py")
    block = src.split("def status_bar_theme", 1)[1].split("def status_text_theme", 1)[0]
    assert "p.WINDOW_ALT" in block
    assert "mvStyleVar_WindowPadding, 6, 1" in block


def test_product_version_remains_fixed_at_110():
    assert (ROOT / "VERSION").read_text(encoding="utf-8").strip() == "1.1.0"
