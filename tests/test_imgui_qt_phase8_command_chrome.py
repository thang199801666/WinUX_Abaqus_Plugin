from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STYLE = ROOT / "WinUx" / "widgets" / "imgui_qt_style.py"
VIEW = ROOT / "WinUx" / "view.py"
TOOLBAR = ROOT / "WinUx" / "components" / "toolbar.py"
DOCK = ROOT / "WinUx" / "components" / "dock_widget.py"
PLOTS = ROOT / "WinUx" / "components" / "job_plots.py"


def test_application_theme_centralizes_global_focus_hover_pressed_palette():
    source = STYLE.read_text(encoding="utf-8")
    for token in (
        "def application_theme", "mvThemeCol_NavHighlight", "p.FOCUS",
        "mvThemeCol_ButtonHovered", "p.BUTTON_HOVER",
        "mvThemeCol_ButtonActive", "p.BUTTON_ACTIVE",
        "mvThemeCol_MenuBarBg", "p.TOOLBAR",
    ):
        assert token in source


def test_main_menu_uses_shared_theme_with_pre_migration_command_row_geometry():
    style = STYLE.read_text(encoding="utf-8")
    view = VIEW.read_text(encoding="utf-8")
    toolbar = TOOLBAR.read_text(encoding="utf-8")
    assert "def menu_bar_theme" in style
    assert "imgui_menu_bar_theme" in toolbar
    assert "def resource_menu_theme" in toolbar
    assert "menu_theme = resource_menu_theme()" in view
    assert "dpg.bind_item_theme(menu_bar, menu_theme)" in view
    assert "horizontal_spacing=6" in view
    assert "width=190" in view


def test_dock_controls_and_popup_use_shared_command_chrome():
    source = DOCK.read_text(encoding="utf-8")
    assert "dock_control_theme(dpg, close=False)" in source
    assert "dock_control_theme(dpg, close=True)" in source
    assert "menu_bar_theme(dpg)" in source


def test_job_plot_toolbar_uses_shared_qt_style_controls():
    source = PLOTS.read_text(encoding="utf-8")
    for token in (
        "tool_bar_theme(dpg)", "line_edit_theme(dpg)",
        "command_button_theme(dpg)",
    ):
        assert token in source


def test_main_ui_command_chrome_remains_dear_imgui_only():
    combined = "\n".join(
        path.read_text(encoding="utf-8") for path in (STYLE, VIEW, TOOLBAR, DOCK, PLOTS)
    )
    assert "PyQt" not in combined
    assert "PySide" not in combined
    assert "tkinter" not in combined
