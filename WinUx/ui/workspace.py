"""WinUx-styled workspace surfaces for multi-panel tools."""
from __future__ import annotations

from DearUIQt.backends import dpg

from DearUIQt.widgets import QWidget, QToolBar
from DearUIQt.layouts import QGridLayout
from DearUIQt.themes import body_theme, surface_theme
from ..dialogs.folder_browser_style import browser_toolbar_theme, browser_layout_theme
from DearUIQt.backends.dearpygui import dpg_window_rect
from DearUIQt.gui import QtFusionPalette

_CANVAS_FRAME_THEME = None


def style_tool_surface(item, *, padding=(0, 0), spacing=(5, 6), backend=dpg):
    """Apply explicit tool-region margins without stacking dialog body padding."""
    with backend.theme() as theme:
        with backend.theme_component(backend.mvChildWindow):
            backend.add_theme_color(backend.mvThemeCol_ChildBg, QtFusionPalette.WINDOW)
            backend.add_theme_style(backend.mvStyleVar_WindowPadding, *padding)
            backend.add_theme_style(backend.mvStyleVar_ItemSpacing, *spacing)
            backend.add_theme_style(backend.mvStyleVar_ChildBorderSize, 0)
            backend.add_theme_style(backend.mvStyleVar_ChildRounding, 0)
    backend.bind_item_theme(item, theme)
    return theme


class ToolPanel(QWidget):
    def __init__(self, parent, *, scroll=False, padding=None, spacing=(5, 6), after=None, backend=dpg):
        backend, options = self._construction(parent, backend)
        tag = backend.add_child_window(
            width=-1, height=-1, border=False, no_scrollbar=not scroll,
            no_scroll_with_mouse=not scroll, **options)
        super().__init__(tag, parent=parent, after=after, backend=backend)
        if padding is None:
            backend.bind_item_theme(tag, body_theme())
        else:
            style_tool_surface(tag, padding=padding, spacing=spacing, backend=backend)


class ToolWorkspace(QGridLayout):
    """Fixed side panels with a stretching center and shared Qt/Fusion spacing."""

    def __init__(self, parent, *, column_widths, column_gap=8, panel_padding=None,
                 panel_spacing=(5, 6), after=None, backend=dpg):
        super().__init__(len(column_widths), column_widths=column_widths,
                         parent=parent, after=after, backend=backend)
        backend.configure_item(self.tag, height=-1, borders_innerV=panel_padding is None)
        backend.bind_item_theme(self.tag, browser_layout_theme(cell_padding=(max(0, int(column_gap)) // 2, 0)))
        self._panel_padding, self._panel_spacing = panel_padding, panel_spacing
        self.panels = []

    def panel(self, column, *, scroll=False):
        panel = ToolPanel(self.cell(0, column), scroll=scroll,
                           padding=self._panel_padding, spacing=self._panel_spacing,
                          after=self._after, backend=self.backend)
        self.panels.append(panel)
        return panel


class ToolBar(QToolBar):
    """WinUx-themed specialization of the reusable DearUIQt ``QToolBar``."""

    def __init__(self, parent, *, after=None, backend=dpg):
        super().__init__(
            "", parent=parent, after=after, backend=backend,
            movable=False, floatable=False)
        backend.configure_item(self.tag, height=36)
        backend.bind_item_theme(self.tag, browser_toolbar_theme())
        self.box_layout = self.layout()
        self.content = self.box_layout.tag


class ToolCommandRow(QGridLayout):
    """Equal-width command cells, with optional fixed navigation columns."""

    def __init__(self, parent, *, columns=2, column_widths=None, gap=6, after=None, backend=dpg):
        # A command row must fit its buttons. QGridLayout's default height=-1
        # stretches to the remaining panel height, pushing every subsequent
        # control (including View Data's grid) far below the visible viewport.
        super().__init__(columns, column_widths=column_widths, parent=parent,
                         after=after, backend=backend, height=0)
        backend.bind_item_theme(self.tag, browser_layout_theme(cell_padding=(max(0, int(gap)) // 2, 0)))


def style_image_canvas(item, backend=dpg):
    """Give a canvas *frame* a persistent white surface and visible 1px border.

    The target must be an ``mvChildWindow``.  A drawlist cannot display child-window
    background/border theme roles, which is why the previous implementation looked
    invisible before an image was loaded.
    """
    global _CANVAS_FRAME_THEME
    try:
        valid = _CANVAS_FRAME_THEME is not None and backend.does_item_exist(_CANVAS_FRAME_THEME)
    except Exception:
        valid = False
    if not valid:
        with backend.theme() as _CANVAS_FRAME_THEME:
            with backend.theme_component(backend.mvChildWindow):
                backend.add_theme_color(backend.mvThemeCol_ChildBg, QtFusionPalette.BASE)
                backend.add_theme_color(backend.mvThemeCol_Border, QtFusionPalette.BORDER)
                backend.add_theme_style(backend.mvStyleVar_WindowPadding, 0, 0)
                backend.add_theme_style(backend.mvStyleVar_ChildBorderSize, 1)
                backend.add_theme_style(backend.mvStyleVar_ChildRounding, 0)
                backend.add_theme_style(backend.mvStyleVar_ItemSpacing, 0, 0)
    backend.bind_item_theme(item, _CANVAS_FRAME_THEME)


def item_rect(item, backend=dpg):
    """Absolute rectangle, including DPG child windows without rect_min state."""
    try:
        left, top = backend.get_item_rect_min(item)
        width, height = backend.get_item_rect_size(item)
        return left, top, left + width, top + height
    except (KeyError, TypeError, ValueError):
        pass
    return dpg_window_rect(backend, item, clip=False)
