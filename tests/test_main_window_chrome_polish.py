from DearUIQt.gui.palette import QtFusionPalette
from DearUIQt.ribbon.bar import RibbonBar
from WinUx.ui.components.explorer.themes import ListViewThemeManager


def test_job_viewer_uses_shared_table_chrome():
    _, theme = ListViewThemeManager.resolve("Job Viewer")
    assert theme["header_bg"] == QtFusionPalette.TABLE_HEADER
    assert theme["header_text"] == QtFusionPalette.TABLE_HEADER_TEXT
    assert theme["separator"] == QtFusionPalette.TABLE_GRID
    assert theme["header_bottom_line"] == QtFusionPalette.TABLE_BORDER
    assert theme["status_bg"] == QtFusionPalette.WINDOW_ALT


def test_ribbon_spacing_keeps_compact_but_separated_groups():
    assert RibbonBar.GROUP_GAP == 3
    assert RibbonBar.COMMAND_GAP == 3
    assert RibbonBar.GROUP_HORIZONTAL_PADDING == 4
    assert RibbonBar.CONTROLS_HORIZONTAL_PADDING == 3
    assert RibbonBar.SURFACE_SPACING_X == 3


def test_dock_palette_has_dedicated_chrome_roles():
    assert QtFusionPalette.TITLE_BORDER != QtFusionPalette.BORDER_DARK
    assert QtFusionPalette.DOCK_BUTTON_HOVER != QtFusionPalette.DOCK_BUTTON_ACTIVE
