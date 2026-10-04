from __future__ import annotations

from pathlib import Path
import os

import dearpygui.dearpygui as dpg

from ..resources import RESOURCE_DIR, icon_path
from .tooltip import add_styled_tooltip, reset_tooltip_runtime_resources
from .qt_style import QtFusionMetrics, QtFusionPalette
from ..widgets.imgui_qt_style import (
    tool_bar_theme as imgui_tool_bar_theme,
    tool_button_theme as imgui_tool_button_theme,
    path_bar_theme as imgui_path_bar_theme,
    status_bar_theme as imgui_status_bar_theme,
    status_text_theme as imgui_status_text_theme,
    menu_bar_theme as imgui_menu_bar_theme,
    command_button_theme as imgui_command_button_theme,
)
from .interaction_gate import register_pointer_protected_item

_TOOLBAR_ICON_THEME = None
_PATH_BUTTON_THEME = None
_MENU_THEME = None
_TOOLBAR_TABLE_THEME = None
_SEARCH_POPUP_THEME = None
_SEARCH_INPUT_THEME = None
_SEARCH_CLOSE_THEME = None
_PATH_BUTTON_FONT = None

DEFAULT_UI_TEXTURE_SIZE = 32
TOOLBAR_TEXTURE_SIZE = 48



def path_button_font():
    """Return the compact normal Windows UI font for the path selector."""
    global _PATH_BUTTON_FONT
    if _PATH_BUTTON_FONT is not None and dpg.does_item_exist(_PATH_BUTTON_FONT):
        return _PATH_BUTTON_FONT

    windir = Path(os.environ.get("WINDIR", r"C:\\Windows"))
    candidates = (
        windir / "Fonts" / "segoeuib.ttf",
        windir / "Fonts" / "seguisb.ttf",
        windir / "Fonts" / "arialbd.ttf",
    )
    try:
        font_path = next((path for path in candidates if path.is_file()), None)
        if font_path is None:
            return None
        with dpg.font_registry():
            _PATH_BUTTON_FONT = dpg.add_font(str(font_path), 16)
    except Exception:
        _PATH_BUTTON_FONT = None
    return _PATH_BUTTON_FONT


def toolbar_table_theme():
    """Compact QToolBar table: no card-like cell padding around actions."""
    global _TOOLBAR_TABLE_THEME
    if _TOOLBAR_TABLE_THEME is not None and dpg.does_item_exist(_TOOLBAR_TABLE_THEME):
        return _TOOLBAR_TABLE_THEME
    with dpg.theme() as _TOOLBAR_TABLE_THEME:
        with dpg.theme_component(dpg.mvTable):
            dpg.add_theme_style(dpg.mvStyleVar_CellPadding, 0, 5)
    return _TOOLBAR_TABLE_THEME




def search_popup_theme():
    """Qt/Fusion-like inline search surface shared by both file panes."""
    global _SEARCH_POPUP_THEME
    if (_SEARCH_POPUP_THEME is not None
            and dpg.does_item_exist(_SEARCH_POPUP_THEME)):
        return _SEARCH_POPUP_THEME
    p = QtFusionPalette
    with dpg.theme() as _SEARCH_POPUP_THEME:
        with dpg.theme_component(dpg.mvAll):
            dpg.add_theme_color(dpg.mvThemeCol_WindowBg, p.TOOLBAR)
            dpg.add_theme_color(dpg.mvThemeCol_ChildBg, p.TOOLBAR)
            dpg.add_theme_color(dpg.mvThemeCol_Border, p.BORDER)
            dpg.add_theme_color(dpg.mvThemeCol_BorderShadow, p.SHADOW)
            dpg.add_theme_style(dpg.mvStyleVar_WindowPadding, 6, 3)
            dpg.add_theme_style(dpg.mvStyleVar_WindowRounding, 0)
            dpg.add_theme_style(dpg.mvStyleVar_ChildRounding, 0)
            dpg.add_theme_style(dpg.mvStyleVar_WindowBorderSize, 0)
            dpg.add_theme_style(dpg.mvStyleVar_ChildBorderSize, 0)
            dpg.add_theme_style(dpg.mvStyleVar_ItemSpacing, 5, 0)
    return _SEARCH_POPUP_THEME

def search_input_theme():
    """Compact QLineEdit-like search field."""
    global _SEARCH_INPUT_THEME
    if (_SEARCH_INPUT_THEME is not None
            and dpg.does_item_exist(_SEARCH_INPUT_THEME)):
        return _SEARCH_INPUT_THEME
    p = QtFusionPalette
    with dpg.theme() as _SEARCH_INPUT_THEME:
        with dpg.theme_component(dpg.mvInputText):
            dpg.add_theme_color(dpg.mvThemeCol_FrameBg, p.BASE)
            dpg.add_theme_color(dpg.mvThemeCol_FrameBgHovered, p.BASE)
            dpg.add_theme_color(dpg.mvThemeCol_FrameBgActive, p.BASE)
            dpg.add_theme_color(dpg.mvThemeCol_Text, p.TEXT)
            dpg.add_theme_color(dpg.mvThemeCol_TextDisabled, p.TEXT_DISABLED)
            dpg.add_theme_color(dpg.mvThemeCol_TextSelectedBg, (0, 120, 215, 105))
            dpg.add_theme_color(dpg.mvThemeCol_Border, p.BORDER)
            dpg.add_theme_style(dpg.mvStyleVar_FramePadding, 6, 3)
            dpg.add_theme_style(dpg.mvStyleVar_FrameRounding, QtFusionMetrics.FRAME_ROUNDING)
            dpg.add_theme_style(dpg.mvStyleVar_FrameBorderSize, 1)
    return _SEARCH_INPUT_THEME

def search_close_theme():
    global _SEARCH_CLOSE_THEME
    if (_SEARCH_CLOSE_THEME is not None
            and dpg.does_item_exist(_SEARCH_CLOSE_THEME)):
        return _SEARCH_CLOSE_THEME
    p = QtFusionPalette
    with dpg.theme() as _SEARCH_CLOSE_THEME:
        with dpg.theme_component(dpg.mvButton):
            dpg.add_theme_color(dpg.mvThemeCol_Button, (0, 0, 0, 0))
            dpg.add_theme_color(dpg.mvThemeCol_ButtonHovered, p.BUTTON_HOVER)
            dpg.add_theme_color(dpg.mvThemeCol_ButtonActive, p.BUTTON_ACTIVE)
            dpg.add_theme_color(dpg.mvThemeCol_Text, p.TEXT)
            dpg.add_theme_color(dpg.mvThemeCol_Border, (0, 0, 0, 0))
            dpg.add_theme_style(dpg.mvStyleVar_FramePadding, 3, 2)
            dpg.add_theme_style(dpg.mvStyleVar_FrameRounding, QtFusionMetrics.FRAME_ROUNDING)
            dpg.add_theme_style(dpg.mvStyleVar_FrameBorderSize, 0)
    return _SEARCH_CLOSE_THEME

def toolbar_icon_theme():
    global _TOOLBAR_ICON_THEME
    if _TOOLBAR_ICON_THEME is not None and dpg.does_item_exist(_TOOLBAR_ICON_THEME):
        return _TOOLBAR_ICON_THEME
    _TOOLBAR_ICON_THEME = imgui_tool_button_theme(dpg)
    return _TOOLBAR_ICON_THEME

def path_button_theme():
    global _PATH_BUTTON_THEME
    if _PATH_BUTTON_THEME is not None and dpg.does_item_exist(_PATH_BUTTON_THEME):
        return _PATH_BUTTON_THEME
    _PATH_BUTTON_THEME = imgui_path_bar_theme(dpg)
    return _PATH_BUTTON_THEME


def file_toolbar_surface_theme():
    return imgui_tool_bar_theme(dpg)


def file_status_bar_theme():
    return imgui_status_bar_theme(dpg)


def file_status_text_theme(muted=False):
    return imgui_status_text_theme(dpg, muted=bool(muted))


class ResourceTextures:
    _textures: dict[str, str | None] = {}

    @classmethod
    def get(cls, name: str, pixel_size: int = DEFAULT_UI_TEXTURE_SIZE):
        requested_size = max(1, int(pixel_size or 0)) if pixel_size else 0
        base_key = str(name).casefold()
        key = (base_key if requested_size == DEFAULT_UI_TEXTURE_SIZE
               else "{}@{}".format(base_key, requested_size or "source"))
        if key in cls._textures:
            cached = cls._textures[key]
            if cached is None or dpg.does_item_exist(cached):
                return cached
            # A Dear PyGui context was destroyed and recreated in the same
            # Python process. Never return a texture ID from the old context.
            cls._textures.pop(key, None)

        path = icon_path(name)
        if not path.is_file():
            cls._textures[key] = None
            return None
        if requested_size:
            optimized = (
                RESOURCE_DIR / "ui" / "{}px".format(requested_size)
                / path.name
            )
            if optimized.is_file():
                path = optimized

        try:
            width, height, _channels, data = dpg.load_image(str(path))
            if not dpg.does_item_exist("winux_texture_registry"):
                dpg.add_texture_registry(tag="winux_texture_registry", show=False)
            tag = f"winux_texture_{len(cls._textures)}"
            dpg.add_static_texture(width, height, data, parent="winux_texture_registry", tag=tag)
            cls._textures[key] = tag
            return tag
        except Exception:
            cls._textures[key] = None
            return None

    @classmethod
    def reset(cls):
        """Forget tags owned by the current Dear PyGui context."""
        cls._textures.clear()


def reset_toolbar_runtime_resources():
    """Reset module caches after ``dpg.destroy_context()``."""
    global _MENU_THEME, _PATH_BUTTON_FONT, _PATH_BUTTON_THEME
    global _TOOLBAR_ICON_THEME, _TOOLBAR_TABLE_THEME
    global _SEARCH_POPUP_THEME, _SEARCH_INPUT_THEME, _SEARCH_CLOSE_THEME

    ResourceTextures.reset()
    reset_tooltip_runtime_resources()
    _TOOLBAR_ICON_THEME = None
    _PATH_BUTTON_THEME = None
    _MENU_THEME = None
    _TOOLBAR_TABLE_THEME = None
    _SEARCH_POPUP_THEME = None
    _SEARCH_INPUT_THEME = None
    _SEARCH_CLOSE_THEME = None
    _PATH_BUTTON_FONT = None


def resource_menu_theme():
    """Shared QMenuBar/QMenu theme for legacy and main command menus."""
    global _MENU_THEME
    if _MENU_THEME is not None and dpg.does_item_exist(_MENU_THEME):
        return _MENU_THEME
    _MENU_THEME = imgui_menu_bar_theme(dpg)
    return _MENU_THEME


def command_button_theme(checked=False, disabled=False):
    return imgui_command_button_theme(
        dpg, checked=bool(checked), disabled=bool(disabled))

class ResourceMenuBar:
    """Text-only top-level menus with PNG icons in each command row."""

    def __init__(self, menus):
        self.popups = []
        with dpg.group(horizontal=True) as self.container:
            for title, entries in menus:
                button = dpg.add_button(label=title, height=26)
                popup = self._build_popup(entries)
                self.popups.append(popup)
                dpg.configure_item(
                    button,
                    callback=lambda _s=None, _a=None, _u=None, data=(popup, button):
                    self._show(data[0], data[1]),
                )
        dpg.bind_item_theme(self.container, resource_menu_theme())
        for popup in self.popups:
            dpg.bind_item_theme(popup, resource_menu_theme())

    @staticmethod
    def _build_popup(entries):
        popup = dpg.add_window(
            popup=True, show=False, width=230, no_saved_settings=True,
        )
        register_pointer_protected_item(popup)
        for entry in entries:
            if entry is None:
                dpg.add_separator(parent=popup)
                continue
            label, icon_name, command = entry
            with dpg.group(parent=popup, horizontal=True):
                texture = ResourceTextures.get(icon_name)
                if texture:
                    dpg.add_image(texture, width=16, height=16)
                dpg.add_selectable(
                    label=label, width=185,
                    callback=lambda _s=None, _a=None, _u=None, data=(popup, command):
                    ResourceMenuBar._run(data[0], data[1]),
                )
        return popup

    @staticmethod
    def _show(popup, button):
        try:
            x, y = dpg.get_item_rect_min(button)
            _width, height = dpg.get_item_rect_size(button)
            dpg.set_item_pos(popup, (x, y + height))
            dpg.configure_item(popup, show=True)
            dpg.focus_item(popup)
        except Exception:
            pass

    @staticmethod
    def _run(popup, command):
        dpg.configure_item(popup, show=False)
        command()


def add_resource_button(parent, icon_name, callback, tooltip, width=32, height=30):
    texture = ResourceTextures.get(
        icon_name, pixel_size=TOOLBAR_TEXTURE_SIZE)
    if texture:
        tag = dpg.add_image_button(
            texture,
            parent=parent,
            width=20,
            height=20,
            callback=callback,
            tint_color=(70, 70, 70, 255) if icon_name == "Search" else (255, 255, 255, 255),
        )
    else:
        tag = dpg.add_button(
            label=tooltip,
            parent=parent,
            width=width,
            height=height,
            callback=callback,
        )

    dpg.bind_item_theme(tag, toolbar_icon_theme())
    add_styled_tooltip(tag, tooltip)
    return tag


class FileToolbar:
    """Navigation toolbar shared by Local and Server file views."""

    COLLAPSED_HEIGHT = 38
    SEARCH_ROW_HEIGHT = 36

    def __init__(self, parent, panel, callbacks, initial_path_label: str):
        self.panel = panel
        self.callbacks = callbacks
        self.search_visible = False

        self.container = dpg.add_child_window(
            parent=parent,
            border=False,
            width=-1,
            height=self.COLLAPSED_HEIGHT,
            no_scrollbar=True,
            no_scroll_with_mouse=True,
        )
        dpg.bind_item_theme(self.container, file_toolbar_surface_theme())
        self.table = dpg.add_table(
            parent=self.container,
            header_row=False,
            borders_innerH=False,
            borders_outerH=False,
            borders_innerV=False,
            borders_outerV=False,
            policy=dpg.mvTable_SizingStretchProp,
            pad_outerX=False,
            width=-1,
            height=self.COLLAPSED_HEIGHT,
        )
        dpg.bind_item_theme(self.table, toolbar_table_theme())
        for _ in range(5):
            dpg.add_table_column(parent=self.table, width_fixed=True, init_width_or_weight=34)
        dpg.add_table_column(parent=self.table, width_stretch=True, init_width_or_weight=1.0)
        dpg.add_table_column(parent=self.table, width_fixed=True, init_width_or_weight=34)

        navigation_items = (
            ("Left_Arrow", "back", "Back"),
            ("Right_Arrow", "forward", "Forward"),
            ("Open_Folder", "parent", "Parent folder"),
            ("Home", "home", "Home"),
            ("Refresh", "refresh", "Refresh"),
        )
        with dpg.table_row(parent=self.table) as row:
            for icon_name, action, tooltip in navigation_items:
                button = add_resource_button(
                    row, icon_name, self._on_navigate, tooltip, width=30, height=28,
                )
                dpg.configure_item(button, user_data=action)

            self.path_button = dpg.add_button(
                label=initial_path_label,
                parent=row,
                width=-1,
                height=28,
                callback=lambda _sender=None, _app_data=None, _user_data=None:
                    callbacks["choose_path"](panel),
            )
            dpg.bind_item_theme(self.path_button, path_button_theme())
            path_font = path_button_font()
            if path_font is not None:
                dpg.bind_item_font(self.path_button, path_font)
            add_styled_tooltip(self.path_button, "Choose path")

            self.search_button = add_resource_button(
                row, "Search", self._toggle_search, "Search / filter",
                width=30, height=28,
            )

        # Keep search anchored to the top of the file pane, directly beneath
        # the navigation toolbar.  Unlike the floating popup, this can never
        # drift over the file list or cover rows when the pane is resized.
        self.search_popup = dpg.add_child_window(
            parent=self.container,
            show=False,
            width=-1,
            height=self.SEARCH_ROW_HEIGHT,
            border=False,
            no_scrollbar=True,
            no_scroll_with_mouse=True,
        )
        dpg.bind_item_theme(self.search_popup, search_popup_theme())
        with dpg.group(parent=self.search_popup, horizontal=True):
            search_texture = ResourceTextures.get("Search", pixel_size=32)
            if search_texture:
                dpg.add_image(search_texture, width=16, height=16,
                              tint_color=(70, 70, 70, 255))
            self.search_input = dpg.add_input_text(
                width=-46,
                hint="Search this folder",
                callback=self._on_search,
                on_enter=False,
                auto_select_all=False,
            )
            dpg.bind_item_theme(self.search_input, search_input_theme())
            self.search_close = dpg.add_button(
                label="x", width=20, height=20, callback=self._hide_search)
            dpg.bind_item_theme(self.search_close, search_close_theme())
        add_styled_tooltip(
            self.search_input, "Filter the visible items in this folder")

    @property
    def height(self):
        return self.COLLAPSED_HEIGHT + (
            self.SEARCH_ROW_HEIGHT if self.search_visible else 0)

    # QToolBar-like retained properties.  These are behavior/style semantics
    # only; Dear PyGui remains the renderer.
    def setIconSize(self, size):
        if isinstance(size, (tuple, list)):
            size = min(int(size[0]), int(size[1]))
        self._icon_size = max(12, int(size))

    def iconSize(self):
        return int(getattr(self, "_icon_size", 20))

    def setMovable(self, movable):
        self._movable = bool(movable)

    def isMovable(self):
        return bool(getattr(self, "_movable", False))

    def setFloatable(self, floatable):
        self._floatable = bool(floatable)

    def isFloatable(self):
        return bool(getattr(self, "_floatable", False))

    def _focus_search_input(self):
        if not self.search_visible:
            return
        try:
            if dpg.does_item_exist(self.search_input):
                dpg.focus_item(self.search_input)
        except Exception:
            pass

    def _schedule_search_focus(self):
        # Focusing in the same frame that a hidden window becomes visible can
        # be ignored by Dear ImGui.  Focus again on the next rendered frame;
        # once active, ImGui supplies its normal blinking text caret.
        self._focus_search_input()
        try:
            frame = int(dpg.get_frame_count())
            dpg.set_frame_callback(
                frame + 1, lambda *_args, **_kwargs: self._focus_search_input())
            dpg.set_frame_callback(
                frame + 2, lambda *_args, **_kwargs: self._focus_search_input())
        except Exception:
            pass

    def _show_search(self):
        self.search_visible = True
        try:
            dpg.configure_item(self.search_popup, show=True)
            dpg.configure_item(self.container, height=self.height)
            self.panel.toolbar_height_changed()
        except Exception:
            pass
        self._schedule_search_focus()

    def _close_search(self, clear=True):
        """Hide the search strip from application code.

        This helper is deliberately *not* registered as a Dear PyGui callback,
        so it may safely accept application-only options such as ``clear``.
        Dear PyGui's callback runner indexes the callback tuple based on the
        function signature and only supplies sender/app_data/user_data.
        """
        self.search_visible = False
        try:
            dpg.configure_item(self.search_popup, show=False)
            dpg.configure_item(self.container, height=self.height)
            self.panel.toolbar_height_changed()
        except Exception:
            pass
        if clear:
            self.clear_search(apply=True)

    def _hide_search(self, sender=None, app_data=None, user_data=None):
        """Dear PyGui callback for the search-strip close button."""
        del sender, app_data, user_data
        self._close_search(clear=True)

    def _toggle_search(self, sender=None, app_data=None, user_data=None):
        del sender, app_data, user_data
        if self.search_visible:
            self._close_search(clear=True)
        else:
            self._show_search()

    def _on_navigate(self, sender=None, app_data=None, user_data=None):
        action = str(user_data or "")
        callback = self.callbacks.get("navigate")
        if callback is not None and action:
            callback(self.panel, action)

    def _on_search(self, sender=None, app_data=None, user_data=None):
        value = app_data
        if value is None and dpg.does_item_exist(self.search_input):
            value = dpg.get_value(self.search_input)
        self.panel.apply_filter(str(value or ""))

    def clear_search(self, apply=False):
        if dpg.does_item_exist(self.search_input):
            dpg.set_value(self.search_input, "")
        if apply:
            self.panel.apply_filter("")

    def set_path_text(self, text: str):
        if dpg.does_item_exist(self.path_button):
            dpg.configure_item(self.path_button, label=str(text))
