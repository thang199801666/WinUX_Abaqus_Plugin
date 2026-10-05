from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WINUX = ROOT / "WinUx"


def read(rel):
    return (WINUX / rel).read_text(encoding="utf-8")


def test_menu_popup_density_moves_closer_to_qmenu_metrics():
    src = read("widgets/imgui_qt_style.py")
    block = src.split("def menu_bar_theme", 1)[1].split("def command_button_theme", 1)[0]
    assert "mvStyleVar_WindowPadding, 4, 4" in block
    assert "mvStyleVar_ItemSpacing, 4, 1" in block
    assert "mvStyleVar_FramePadding, 8, 3" in block
    assert "mvStyleVar_FramePadding, 6, 3" in block


def test_dock_titlebar_is_compact_qdockwidget_style():
    src = read("components/dock_widget.py")
    assert "TITLE_HEIGHT = 22" in src
    assert "CONTROL_SIZE = 20" in src
    assert "TITLE_TOP_PADDING = 3" in src
    assert "self._title_menu_obj = QMenu(" in src
    assert "min_width=166" in src


def test_plot_panel_uses_shared_flat_panel_header_contract():
    src = read("components/job_plots.py")
    style = read("widgets/imgui_qt_style.py")
    assert "TOOLBAR_HEIGHT = 28" in src
    assert "panel_header_theme(dpg)" in src
    assert "status_text_theme(dpg, muted=True)" in src
    assert "command_button_theme(dpg)" in src
    assert "QtFusionPalette.BORDER_LIGHT" in src
    assert "def panel_header_theme" in style


def test_console_context_menu_and_frame_use_qt_shared_chrome():
    src = read("dialogs/console_form.py")
    assert "from ..widgets import QMenu" in src
    assert "self._create_context_menu()" in src
    assert "QtFusionPalette.BORDER_DARK" in src
    assert "parent=parent, width=-1, height=-1, border=True" in src
    assert "min_width=170" in src


def test_settings_navigation_and_page_header_remain_flat_and_compact():
    theme = read("dialogs/theme.py")
    dialog = read("dialogs/qt_dialog.py")
    assert "mvStyleVar_WindowPadding, 6, 6" in theme
    assert "mvStyleVar_ItemSpacing, 0, 1" in theme
    assert "mvStyleVar_FramePadding, 8, 3" in theme
    assert "dpg.add_spacer(height=2)" in dialog


def test_product_version_remains_fixed_at_110():
    assert (ROOT / "VERSION").read_text(encoding="utf-8").strip() == "1.1.0"
