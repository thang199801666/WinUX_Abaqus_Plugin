"""
ExplorerListView
================
A reusable Windows-Explorer-style Details view for Dear PyGui.

The widget uses Windows Shell APIs for native file/folder icons and caches each
icon as a Dear PyGui static texture. On non-Windows systems it falls back to
simple transparent placeholders.
"""

from __future__ import annotations

import ctypes
import os
import re
import subprocess
import sys
import time


def _configure_bundled_vendor():
    """Load third-party packages bundled beside this script.

    Expected layout::

        WinUX_Abaqus_Plugin/
        |-- FileListView.py
        `-- vendor/
            |-- dearpygui/
            |-- PIL/
            `-- ...

    This must run before importing Pillow or Dear PyGui.  ``os.add_dll_directory``
    is also used on Windows so CPython can resolve native DLL dependencies of
    ``dearpygui._dearpygui.pyd`` when launched by Abaqus Python.
    """
    script_dir = os.path.dirname(os.path.abspath(__file__))
    package_dir = os.path.dirname(script_dir)
    plugin_dir = os.path.dirname(package_dir)
    candidates = (
        os.path.join(script_dir, "vendor"),
        os.path.join(package_dir, "vendor"),
        os.path.join(plugin_dir, "vendor"),
        os.path.join(plugin_dir, "winux_vendor"),
        os.path.join(plugin_dir, "site-packages"),
    )
    vendor_dir = next((path for path in candidates if os.path.isdir(path)), None)
    if vendor_dir and vendor_dir not in sys.path:
        sys.path.insert(0, vendor_dir)

    # Keep handles alive for the lifetime of the process. Closing a handle can
    # remove the directory from the Windows DLL search path.
    dll_handles = []
    add_dll_directory = getattr(os, "add_dll_directory", None)
    if os.name == "nt" and add_dll_directory is not None:
        candidates = tuple(path for path in (
            vendor_dir,
            os.path.join(vendor_dir, "dearpygui") if vendor_dir else None,
        ) if path)
        for directory in candidates:
            if os.path.isdir(directory):
                try:
                    dll_handles.append(add_dll_directory(directory))
                except OSError:
                    pass

    globals()["_VENDOR_DLL_HANDLES"] = dll_handles
    return vendor_dir


VENDOR_DIR = _configure_bundled_vendor()
from ctypes import wintypes
from datetime import datetime
from typing import Optional, Any, Callable, Iterable

from PIL import Image
import dearpygui.dearpygui as dpg

from .qt_style import QtFusionMetrics, QtFusionPalette
from ..widgets.item_views import QtItemViewState, QtSelectionMode
from .explorer_themes import ListViewTheme, ListViewThemeManager
from .explorer_header_view import ExplorerHeaderView
from .explorer_drag_preview import DragPreviewHelper
from ..platform.windows_cursors import WindowsCursorFile
from .shared_scroller import SharedScrollerMetrics
from .shared_scroller import DpgScrollerArrowOverlay, add_dpg_scroller_style, dpg_window_rect

from .interaction_gate import pointer_input_is_blocked

from ..diagnostics import log_event, log_exception
from .explorer_list_model import (
    DEFAULT_COLUMNS,
    DEFAULT_ITEM_MENU,
    ListViewItem,
    _ALIGN_X,
    _ALIGN_Y,
    human_size,
)
from .tooltip import (
    TOOLTIP_DELAY,
    TOOLTIP_WRAP_WIDTH,
    reset_tooltip_runtime_resources,
    tooltip_theme,
)
from .explorer_rename_textbox import ExplorerRenameTextBox
from .explorer_columns import ExplorerColumnsMixin
from .explorer_rename import ExplorerRenameMixin
from .explorer_file_operations import ExplorerFileOperationsMixin
from .explorer_selection import ExplorerSelectionMixin
from .explorer_context_menu import (
    ExplorerContextMenuMixin, EXPLORER_MENU_TAGS as _EXPLORER_MENU_TAGS,
    normalize_menu_item as _normalize_menu_item,
)
from .explorer_data_view import ExplorerDataViewMixin
from .explorer_item_model import ExplorerItemModel, stable_item_identity
from .explorer_keyboard import ExplorerKeyboardController, ExplorerKeyboardInput
from .explorer_native_hook import ExplorerNativeHook
from .explorer_pointer_capture import ExplorerPointerCaptureMixin
from .explorer_rubber_band import ExplorerRubberBandMixin
from .explorer_drag_drop import ExplorerDragDropMixin
from .explorer_hit_testing import ExplorerHitTestingMixin
from .explorer_pointer_dispatch import ExplorerPointerDispatchMixin
from .explorer_layout import ExplorerLayoutMixin
from .explorer_row_registry import ExplorerRowRegistryMixin
from .explorer_rendering import ExplorerRenderingMixin
from .explorer_input_state import (
    _EXPLORER_MODAL_TAGS, _alt_down, _ctrl_down, _hovered,
    _modal_input_is_blocked, _overlay_window_owns_input, _shift_down,
    _visible_modal_window_exists, _visible_popup_window_exists,
    register_modal_window, unregister_modal_window,
)
from ..platform.windows_icons import (
    BI_RGB,
    BITMAPINFO,
    BITMAPINFOHEADER,
    DIB_RGB_COLORS,
    DI_NORMAL,
    FILE_ATTRIBUTE_DIRECTORY,
    FILE_ATTRIBUTE_NORMAL,
    ICON_SIZE,
    SHFILEINFOW,
    SHGFI_ICON,
    SHGFI_SMALLICON,
    SHGFI_USEFILEATTRIBUTES,
    SHSTOCKICONINFO,
    SHGSI_ICON,
    SHGSI_SMALLICON,
    SIID_DOCNOASSOC,
    SIID_FOLDER,
    WindowsIconRegistry,
    reset_windows_icon_registry,
)


# --------------------------------------------------------------------------- #
# Win32 Shell icon support
# --------------------------------------------------------------------------- #


# --------------------------------------------------------------------------- #
# Helpers & Windows Font Setup
# --------------------------------------------------------------------------- #

_FONT_BOUND = False
# Explorer input ownership/modifier helpers live in explorer_input_state.
# The names below are imported for source/API compatibility with older callers.
_NATIVE_RENAME_ENABLED = True


def apply_windows_font(font_size=15):
    """Load the Windows Explorer UI font into Dear PyGui once."""
    global _FONT_BOUND
    if _FONT_BOUND:
        return

    windir = os.environ.get("WINDIR", "C:\\Windows")
    font_path = os.path.join(windir, "Fonts", "segoeui.ttf")
    if os.path.exists(font_path):
        with dpg.font_registry():
            with dpg.font(font_path, font_size) as default_font:
                pass
        dpg.bind_font(default_font)
        _FONT_BOUND = True


_GLOBAL_THEME_BOUND = False


def apply_white_explorer_theme():
    """Bind the application-wide Qt/Fusion-like Dear PyGui palette once."""
    global _GLOBAL_THEME_BOUND
    if _GLOBAL_THEME_BOUND:
        return

    apply_windows_font(15)
    p = QtFusionPalette
    m = QtFusionMetrics

    def _set(const_name, value):
        const = getattr(dpg, const_name, None)
        if const is not None:
            dpg.add_theme_color(const, value)

    with dpg.theme() as theme:
        with dpg.theme_component(dpg.mvAll):
            _set("mvThemeCol_WindowBg", p.BASE)
            _set("mvThemeCol_ChildBg", p.BASE)
            _set("mvThemeCol_PopupBg", p.MENU)
            _set("mvThemeCol_Text", p.TEXT)
            _set("mvThemeCol_TextDisabled", p.TEXT_DISABLED)
            _set("mvThemeCol_TextSelectedBg", (0, 120, 215, 105))
            _set("mvThemeCol_Border", p.BORDER_LIGHT)
            _set("mvThemeCol_BorderShadow", p.SHADOW)
            _set("mvThemeCol_FrameBg", p.BASE)
            _set("mvThemeCol_FrameBgHovered", p.BASE)
            _set("mvThemeCol_FrameBgActive", p.BASE)
            _set("mvThemeCol_Button", p.BUTTON)
            _set("mvThemeCol_ButtonHovered", p.BUTTON_HOVER)
            _set("mvThemeCol_ButtonActive", p.BUTTON_ACTIVE)
            _set("mvThemeCol_Header", p.HIGHLIGHT_SOFT)
            _set("mvThemeCol_HeaderHovered", p.HIGHLIGHT_HOVER)
            _set("mvThemeCol_HeaderActive", p.HIGHLIGHT_SOFT)
            _set("mvThemeCol_CheckMark", p.HIGHLIGHT)
            _set("mvThemeCol_TitleBg", p.TITLE)
            _set("mvThemeCol_TitleBgActive", p.TITLE_ACTIVE)
            _set("mvThemeCol_TitleBgCollapsed", p.TITLE)
            _set("mvThemeCol_MenuBarBg", p.TOOLBAR)
            _set("mvThemeCol_Separator", p.BORDER_LIGHT)
            _set("mvThemeCol_SeparatorHovered", p.HIGHLIGHT)
            _set("mvThemeCol_SeparatorActive", p.HIGHLIGHT)
            _set("mvThemeCol_Tab", p.BUTTON)
            _set("mvThemeCol_TabHovered", p.BUTTON_HOVER)
            _set("mvThemeCol_TabActive", p.BASE)
            add_dpg_scroller_style(dpg)
            _set("mvThemeCol_ResizeGrip", (0, 0, 0, 0))
            _set("mvThemeCol_ResizeGripHovered", (0, 0, 0, 0))
            _set("mvThemeCol_ResizeGripActive", (0, 0, 0, 0))
            dpg.add_theme_style(dpg.mvStyleVar_FrameRounding, m.FRAME_ROUNDING)
            dpg.add_theme_style(dpg.mvStyleVar_GrabRounding, m.GRAB_ROUNDING)
            dpg.add_theme_style(dpg.mvStyleVar_WindowBorderSize, 1)
            dpg.add_theme_style(dpg.mvStyleVar_FrameBorderSize, 1)
        with dpg.theme_component(dpg.mvButton):
            dpg.add_theme_color(dpg.mvThemeCol_Text, p.TEXT)
            dpg.add_theme_color(dpg.mvThemeCol_Border, p.BORDER)
            dpg.add_theme_style(dpg.mvStyleVar_FrameRounding, m.FRAME_ROUNDING)
            dpg.add_theme_style(dpg.mvStyleVar_FrameBorderSize, 1)
            dpg.add_theme_style(dpg.mvStyleVar_FramePadding, 6, 3)
        with dpg.theme_component(dpg.mvImageButton):
            # Tool icons should look like QToolButton: neutral at rest, blue
            # feedback only on hover/press instead of a permanent blue tile.
            dpg.add_theme_color(dpg.mvThemeCol_Button, (0, 0, 0, 0))
            dpg.add_theme_color(dpg.mvThemeCol_ButtonHovered, p.BUTTON_HOVER)
            dpg.add_theme_color(dpg.mvThemeCol_ButtonActive, p.BUTTON_ACTIVE)
            dpg.add_theme_color(dpg.mvThemeCol_Border, (0, 0, 0, 0))
            dpg.add_theme_style(dpg.mvStyleVar_FrameBorderSize, 0)
            dpg.add_theme_style(dpg.mvStyleVar_FrameRounding, m.FRAME_ROUNDING)
        with dpg.theme_component(dpg.mvCheckbox):
            dpg.add_theme_color(dpg.mvThemeCol_FrameBg, p.BASE)
            dpg.add_theme_color(dpg.mvThemeCol_FrameBgHovered, p.HIGHLIGHT_HOVER)
            dpg.add_theme_color(dpg.mvThemeCol_FrameBgActive, p.HIGHLIGHT_SOFT)
            dpg.add_theme_color(dpg.mvThemeCol_Border, p.BORDER_DARK)
            dpg.add_theme_color(dpg.mvThemeCol_CheckMark, p.HIGHLIGHT)
            dpg.add_theme_style(dpg.mvStyleVar_FramePadding, 1, 1)
            dpg.add_theme_style(dpg.mvStyleVar_FrameBorderSize, 1)
            dpg.add_theme_style(dpg.mvStyleVar_FrameRounding, 1)
    dpg.bind_theme(theme)
    _GLOBAL_THEME_BOUND = True


def reset_explorer_runtime_resources():
    """Forget all tags and flags owned by a destroyed Dear PyGui context."""
    global _FONT_BOUND, _GLOBAL_THEME_BOUND

    reset_windows_icon_registry()
    reset_tooltip_runtime_resources()
    _EXPLORER_MENU_TAGS.clear()
    _EXPLORER_MODAL_TAGS.clear()
    _FONT_BOUND = False
    _GLOBAL_THEME_BOUND = False
    try:
        ExplorerListView._external_cursor_provider = None
    except NameError:
        pass






# --------------------------------------------------------------------------- #
# Public configuration helpers
# --------------------------------------------------------------------------- #

HORIZONTAL_ALIGNMENTS = ("left", "center", "right")
VERTICAL_ALIGNMENTS = ("top", "middle", "bottom")


def _normalize_alignment(value, allowed, default):
    value = str(value or default).lower()
    aliases = {"centre": "center", "mid": "middle"}
    value = aliases.get(value, value)
    if value not in allowed:
        raise ValueError("Unsupported alignment %r. Expected one of %s" % (value, allowed))
    return value



# --------------------------------------------------------------------------- #
# Theme system
# --------------------------------------------------------------------------- #





# --------------------------------------------------------------------------- #
# The Widget Class
# --------------------------------------------------------------------------- #

class ExplorerListView(
        ExplorerColumnsMixin, ExplorerRenameMixin, ExplorerContextMenuMixin,
        ExplorerDataViewMixin, ExplorerFileOperationsMixin, ExplorerSelectionMixin,
        ExplorerPointerCaptureMixin, ExplorerRubberBandMixin, ExplorerDragDropMixin,
        ExplorerHitTestingMixin, ExplorerPointerDispatchMixin, ExplorerLayoutMixin,
        ExplorerRowRegistryMixin, ExplorerRenderingMixin):
    """Lightweight Explorer details view rendered without ``dpg.table``.

    The header and all rows are drawn on two drawlists. Column resizing,
    sorting, selection and cell alignment are handled with pixel coordinates.
    This avoids the high widget count and layout overhead of a table.
    """

    _counter = 0
    _resize_cursor_owner = None
    # A top-level owner (currently WinUXView's horizontal splitter) can supply
    # a cursor handle that takes priority in every ListView WNDPROC hook.
    _external_cursor_provider = None
    # Shell file drops stashed by the native WM_DROPFILES handler. They are
    # routed on the UI thread by the per-frame layout watch, because neither
    # item rectangles nor coordinate systems are reliable inside a WNDPROC.
    _PENDING_EXTERNAL_DROPS = []
    _EXTERNAL_DROP_TTL_SECONDS = 5.0
    HEADER_HEIGHT = QtFusionMetrics.HEADER_HEIGHT
    ROW_HEIGHT = QtFusionMetrics.ROW_HEIGHT
    BODY_FONT_PX = 15
    # Fallback only. Native rename is fitted to the measured DPG body-text
    # render height at runtime; the same numeric font size does not map 1:1
    # between ImGui/FreeType and Win32 GDI.
    RENAME_FONT_PX = BODY_FONT_PX
    RENAME_EDITOR_HEIGHT = 20
    CELL_PADDING = 6
    # Radius of the invisible grab area around a one-pixel header divider.
    # A 16 px-wide target is substantially easier to acquire on HiDPI displays
    # while remaining narrow enough not to interfere with header sorting.
    SEPARATOR_HIT = 8.0
    SCROLLBAR_HIT_SIZE = float(SharedScrollerMetrics.HIT_THICKNESS)
    MIN_COLUMN_WIDTH = 56
    ELLIPSIS = "…"
    DRAG_THRESHOLD = 4.0
    ITEM_MOVE_HOLD_DELAY = 0.28
    QUICK_RUBBER_MAX_DELAY = 0.28
    AUTO_SCROLL_MARGIN = 24.0
    AUTO_SCROLL_STEP = 18.0
    # Keep small directories on the historical full-render path. Large
    # directories only materialize visible rows plus overscan.
    VIRTUALIZATION_THRESHOLD = 240
    VIRTUALIZATION_OVERSCAN_ROWS = 8
    VIRTUALIZATION_FALLBACK_ROWS = 64
    RENAME_SELECTION_COLOR = (0, 120, 215, 255)
    RENAME_TEXT_AND_CARET_COLOR = (0, 0, 0, 255)

    def __init__(self, parent, items=None, columns=None, width=-1, height=-1,
                 item_menu=None, on_selection_change=None, on_activate=None,
                 on_item_menu_action=None, on_items_moved=None, on_move_error=None,
                 on_open_error=None, on_rename_commit=None, on_drag_start=None,
                 on_drag_motion=None, on_drop=None, on_context_menu_open=None,
                 on_external_drop=None, on_external_drop_missed=None,
                 on_shell_drag=None, path=None,
                 on_sort_change=None,
                 theme=None, show_status_bar=True, open_files_on_double_click=True,
                 show_column_separators=True, single_selection=False, tag=None,
                 horizontal_scrollbar=True, auto_fit_column_key=None,
                 auto_fit_min_width=None,
                 preserve_column_widths_on_startup=False):
        ExplorerListView._counter += 1
        self.uid = tag or f"elv_{ExplorerListView._counter}"
        self.parent = parent
        self.width, self.height = width, height
        self.current_path = os.path.abspath(os.path.expanduser(path)) if path else None
        self.show_status_bar = bool(show_status_bar)
        self.columns = [dict(c) for c in (columns or DEFAULT_COLUMNS)]
        self.item_menu_spec = [_normalize_menu_item(x) for x in (item_menu if item_menu is not None else DEFAULT_ITEM_MENU)]
        self.theme_name, self.theme_config = ListViewThemeManager.resolve(theme or ListViewTheme.EXPLORER)
        self._cell_styles = {}
        self._cell_values = {}
        self._item_icons = {}
        self._custom_textures = {}
        self.on_selection_change = on_selection_change
        self.on_activate = on_activate
        self.on_item_menu_action = on_item_menu_action
        self.on_items_moved = on_items_moved
        self.on_move_error = on_move_error
        self.on_open_error = on_open_error
        self.on_rename_commit = on_rename_commit
        self.on_drag_start = on_drag_start
        self.on_drag_motion = on_drag_motion
        self.on_drop = on_drop
        self.on_context_menu_open = on_context_menu_open
        self.on_external_drop = on_external_drop
        self.on_external_drop_missed = on_external_drop_missed
        self.on_shell_drag = on_shell_drag
        self.on_sort_change = on_sort_change
        self.open_files_on_double_click = bool(open_files_on_double_click)
        self.show_column_separators = bool(show_column_separators)
        self.single_selection = bool(single_selection)
        self.horizontal_scrollbar = bool(horizontal_scrollbar)
        self.auto_fit_column_key = (
            str(auto_fit_column_key) if auto_fit_column_key is not None else None
        )
        self.auto_fit_min_width = (
            max(1.0, float(auto_fit_min_width))
            if auto_fit_min_width is not None else None
        )
        self.preserve_column_widths_on_startup = bool(
            preserve_column_widths_on_startup
        )

        # File operation state. Clipboard entries are absolute paths so copy/cut
        # remains valid after sorting or reloading the current directory.
        self._clipboard_paths = []
        self._clipboard_mode = None  # "copy" | "cut" | None
        self._rename_active = False
        self._rename_index = None
        # Keep rename behavior in one reusable textbox instead of spreading
        # native/DPG focus, selection and cleanup state through ListView.
        self._rename_textbox = ExplorerRenameTextBox(
            f"{self.uid}_inline_rename",
            bind_font=self._bind_font,
            native_enabled=_NATIVE_RENAME_ENABLED,
        )
        self._rename_window_tag = self._rename_textbox.window_tag
        self._rename_input_tag = self._rename_textbox.input_tag
        self._rename_theme_tag = self._rename_textbox.theme_tag

        self._keyboard = ExplorerKeyboardController(self, dpg, ExplorerKeyboardInput(
            ctrl=_ctrl_down, shift=_shift_down, alt=_alt_down,
            overlay_owns_input=_overlay_window_owns_input,
            pointer_blocked=pointer_input_is_blocked))
        self._item_model = ExplorerItemModel()
        self.items = []
        self.selected = set()
        self.last_clicked_index = None
        # Share QAbstractItemView selection/current-index semantics with the
        # generic QtDataGridView/QtListView widgets.  Explorer still renders
        # through its optimized draw-list backend because file panels need
        # Shell icons, virtualization, drag/drop and inline rename, but the
        # interaction model is no longer a separate implementation.
        self._qt_selection = QtItemViewState(multiple=not self.single_selection)
        self.sort_key = "name"
        self.sort_ascending = True
        self._context_item_index = None
        self._context_menu_group_tags = {}
        self._context_menu_group_rows = {}
        self._context_submenu_tags = {}
        self._context_menu_action_controls = {}
        self._context_menu_row_controls = {}
        self._context_keyboard_id = None
        self._active_context_submenu_group = None
        self._context_menu_button_theme = None
        self._context_menu_keyboard_button_theme = None
        self._context_menu_disabled_button_theme = None
        self._context_menu_disabled_icon_theme = None
        self._context_menu_action_controls = {}
        # Consume the release paired with a click handled by a popup. DPG may
        # auto-hide the popup before the global release handler runs.
        self._suppress_next_left_release = False
        # Qt-like gesture ownership: once a press is accepted by this view,
        # global pollers (notably layout splitters) must not steal the same
        # physical drag even if the pointer later crosses their hit area.
        self._pointer_input_owned = False
        self._header_gesture = False

        self._column_widths = {}
        self._last_available_width = 0
        self._resize_key = None
        self._resize_start_x = 0.0
        self._resize_start_width = 0.0
        self._resize_start_mouse_x = 0.0
        self._resize_next_key = None
        self._resize_next_start_width = 0.0
        self._hover_separator_key = None
        self._current_mouse_cursor = None

        # Native Win32 WM_SETCURSOR hook. Dear PyGui uses GLFW, which resets
        # cursors during its backend frame. Handling WM_SETCURSOR at the native
        # window level is the reliable way to obtain the same IDC_SIZEWE cursor
        # used by Windows Explorer.
        self._native_hook = ExplorerNativeHook(self, dpg, ExplorerListView)

        self._mouse_down = False
        self._rubber_active = False
        self._drag_started = False
        self._pending_click_index = None
        self._mouse_down_screen = (0.0, 0.0)
        self._mouse_down_time = 0.0
        self._rubber_start = (0.0, 0.0)
        self._rubber_current = (0.0, 0.0)
        # Screen-space anchor is kept separately from the scrollable content
        # coordinate.  The selection rectangle is rendered on a viewport
        # overlay, so a mouse-down in the blank area below the final row is an
        # equally valid and exact origin.
        self._rubber_start_screen = (0.0, 0.0)
        self._rubber_base_selection = set()
        self._rubber_ctrl = False
        self._rubber_shift = False
        self._rubber_layer_tag = f"{self.uid}_rubber_layer"
        self._rubber_rect_tag = None

        # File/folder drag-and-drop state. Dragging starts from an item;
        # rubberband selection starts from empty body space.
        self._item_drag_active = False
        self._drag_source_index = None
        self._drag_source_items = []
        self._drag_origin_on_item = False
        self._drop_target_index = None
        self._drop_target_pinned = False
        self._external_drop_target_index = None
        self._external_drop_target_pinned = False
        self._external_drop_target_name = None
        self._drag_cursor_active = False
        self._shell_drag_handoff_active = False

        self.hover_index = None
        self._alternating_row_colors = False
        self._show_grid = False
        self._header_visible = True
        self._header_sections_clickable = True
        self._header_view = ExplorerHeaderView(self)
        # QAbstractItemView distinguishes the current index (keyboard focus)
        # from selection.  Keeping a separate current row enables Ctrl+Arrow
        # navigation and a real focus outline without changing selection.
        self._current_index = None
        self._has_focus = False
        self._header_hover_key = None
        self._header_pressed_key = None
        self._header_dragged = False
        self._separator_click_candidate_key = None
        self._last_header_separator_click_time = 0.0
        self._last_header_separator_click_key = None
        self._last_header_separator_click_screen = None
        self._last_click_time = 0.0
        self._last_click_index = None
        self._last_click_screen = None
        self._double_click_gesture = False
        self._rename_click_candidate = None
        self._rename_schedule_serial = 0
        self._pending_slow_rename = None
        self._text_fit_cache = {}
        self._resize_layout_pending = False
        self._body_item_tooltip = None
        self._pinned_item_tooltip = None

        # Optional sticky row rendered between the header and the scrollable
        # body.  It is intentionally outside body_window, so it remains visible
        # while the normal rows scroll.  WinUX uses this for the parent-folder
        # entry ("..").
        self._pinned_item = None
        self._pinned_command = None
        self._pinned_hovered = False
        self._pinned_last_click_time = 0.0
        self._pinned_background = None
        self._pinned_texts = {}
        self._pinned_icon = None

        self._header_items = {}
        self._header_top_line = None
        self._header_bottom_line = None
        self._row_items = []
        self._row_registry = {}
        self._row_render_window_cache = None
        self._fonts = self._load_fonts()
        self._drag_preview = DragPreviewHelper(self.uid, self._fonts.get("body"))
        self._drag_preview.set_theme(self.theme_config)

        apply_windows_font(15)
        self._build_theme()
        self._build_ui()
        self._scroller_arrow_overlay = DpgScrollerArrowOverlay(
            dpg, self.body_window, f"{self.uid}_scroller",
            vertical=True, horizontal=self.horizontal_scrollbar,
            rect_provider=self._body_viewport_rect,
            content_item=self.body_canvas,
            content_size_provider=self._scroller_content_size,
        )
        self._build_item_context_menu()
        self._install_global_handlers()

        if self.current_path is not None:
            self.set_path(self.current_path)
        elif items:
            self.set_items(items)
        else:
            self._rebuild_draw_items()
            self._update_status_bar()
        self._install_layout_watch()
        self._install_native_cursor_hook()

    # ------------------------------ public API ------------------------------
    @staticmethod
    def _default_theme_config():
        """Backward-compatible accessor for the Explorer preset."""
        return ListViewThemeManager.resolve(ListViewTheme.EXPLORER)[1]

    @classmethod
    def register_theme(cls, name, config, base=ListViewTheme.EXPLORER, replace=False):
        return ListViewThemeManager.register(name, config, base=base, replace=replace)

    @classmethod
    def unregister_theme(cls, name):
        ListViewThemeManager.unregister(name)

    @classmethod
    def available_themes(cls):
        return ListViewThemeManager.available()

    def get_theme(self):
        return self.theme_name

    # QAbstractItemView/QTreeView compatibility facade ---------------------
    def horizontalHeader(self):
        return self._header_view

    def setAlternatingRowColors(self, enabled):
        self._alternating_row_colors = bool(enabled)
        self._update_selection_draws()
        return self

    def alternatingRowColors(self):
        return bool(self._alternating_row_colors)

    def setShowGrid(self, enabled):
        self._show_grid = bool(enabled)
        self.theme_config["show_row_lines"] = self._show_grid
        for row in self._row_items:
            line = row.get("bottom")
            if line and dpg.does_item_exist(line):
                dpg.configure_item(line, show=self._show_grid)
        return self

    def showGrid(self):
        return bool(self._show_grid)

    def setHeaderVisible(self, visible):
        self._header_visible = bool(visible)
        if dpg.does_item_exist(self.header_canvas):
            dpg.configure_item(self.header_canvas, show=self._header_visible)
        return self

    def isHeaderVisible(self):
        return bool(self._header_visible)

    def selectionMode(self):
        return (QtSelectionMode.SingleSelection if self.single_selection
                else QtSelectionMode.ExtendedSelection)

    def setSelectionMode(self, mode):
        single = str(mode) == QtSelectionMode.SingleSelection
        self.single_selection = bool(single)
        self._qt_selection.multiple = not self.single_selection
        if self.single_selection and len(self.selected) > 1:
            keep = self._current_index if self._current_index in self.selected else min(self.selected)
            self.selected = {keep}
            self._sync_qt_selection_from_fields()
            self._update_selection_draws()
        return self

    def currentIndex(self):
        return self._current_index

    def setCurrentIndex(self, index, *, select=False):
        if index is None:
            self._current_index = None
            self._sync_qt_selection_from_fields()
            self._update_selection_draws()
            return True
        try:
            index = int(index)
        except (TypeError, ValueError):
            return False
        if not 0 <= index < len(self.items):
            return False
        self._current_index = index
        if select:
            self.select_indices([index], replace=True)
        else:
            self._sync_qt_selection_from_fields()
            self._update_selection_draws()
        return True

    def set_path(self, path, preserve_selection=False):
        """Load a directory and make it the current path."""
        normalized = os.path.abspath(os.path.expanduser(os.fspath(path)))
        if not os.path.isdir(normalized):
            raise NotADirectoryError(normalized)
        selected_paths = {i.path for i in self.get_selected()} if preserve_selection else set()
        self.current_path = normalized
        entries = []
        try:
            for entry in os.scandir(normalized):
                entries.append(ListViewItem.from_path(entry.path))
        except OSError as exc:
            if self.on_move_error:
                self.on_move_error(exc)
            raise
        self.set_items(entries)
        if selected_paths:
            self.selected = {i for i, item in enumerate(self.items) if item.path in selected_paths}
            if self.selected:
                self._current_index = min(self.selected)
                self.last_clicked_index = self._current_index
            self._sync_qt_selection_from_fields()
            self._update_selection_draws()
            self._update_status_bar()
        return self

    def set_pinned_item(self, item, command=None):
        """Display *item* as a non-scrolling row immediately below the header."""
        self._pinned_item = item
        self._pinned_command = command
        self._pinned_hovered = False
        self._rebuild_pinned_row()
        self._queue_layout()
        return self

    def clear_pinned_item(self):
        self._pinned_item = None
        self._pinned_command = None
        self._pinned_hovered = False
        self._rebuild_pinned_row()
        self._queue_layout()
        return self

    def get_path(self):
        return self.current_path

    def open_item(self, item_or_index):
        """Open a folder in this view or a file with the OS default app.

        ``item_or_index`` may be a :class:`ListViewItem` or its current row index.
        On Windows, files are opened through ``os.startfile`` so the registered
        default application is used, exactly like double-clicking in Explorer.
        """
        item = self.items[item_or_index] if isinstance(item_or_index, int) else item_or_index
        path = os.path.abspath(os.path.expanduser(os.fspath(item.path)))

        if not os.path.exists(path):
            exc = FileNotFoundError(path)
            if self.on_open_error:
                self.on_open_error(exc, item)
                return False
            raise exc

        try:
            if item.is_dir or os.path.isdir(path):
                self.set_path(path)
            elif os.name == "nt":
                os.startfile(path)
            elif sys.platform == "darwin":
                subprocess.Popen(["open", path])
            else:
                subprocess.Popen(["xdg-open", path])
            return True
        except (OSError, ValueError) as exc:
            if self.on_open_error:
                self.on_open_error(exc, item)
                return False
            raise

    def activate_item(self, item_or_index):
        """Activate an item and perform the default double-click action.

        The optional ``on_activate`` callback is called first. Returning
        ``False`` from that callback cancels the built-in open/navigation action.
        """
        item = self.items[item_or_index] if isinstance(item_or_index, int) else item_or_index
        proceed = True
        if self.on_activate:
            proceed = self.on_activate(item) is not False
        if proceed and (item.is_dir or self.open_files_on_double_click):
            return self.open_item(item)
        return False

    def go_parent(self):
        if not self.current_path:
            return self
        parent = os.path.dirname(self.current_path)
        if parent and parent != self.current_path:
            self.set_path(parent)
        return self

    def reload_path(self, preserve_selection=True):
        if self.current_path:
            self.set_path(self.current_path, preserve_selection=preserve_selection)
        else:
            self.refresh()
        return self

    @property
    def items(self):
        return self._item_model.items

    @items.setter
    def items(self, value):
        self._item_model.items = value

    @staticmethod
    def _stable_item_identity(item):
        return stable_item_identity(item)

    def set_items(self, items):
        state = self._item_model.replace(
            items, self.selected, self.last_clicked_index, self._current_index,
            self.sort_key, self.sort_ascending)
        self.hover_index = None
        self._pinned_hovered = False
        self._hide_item_tooltips()
        self.selected = state.selected
        self.last_clicked_index = state.anchor
        self._current_index = state.current
        sync_qt_selection = getattr(self, "_sync_qt_selection_from_fields", None)
        if callable(sync_qt_selection):
            sync_qt_selection()
        can_reuse_rows = self._row_registry_can_reuse(
            state.old_topology, state.new_topology)

        # Polling/refresh frequently replaces row objects while keeping the
        # same paths/job IDs. Reuse the existing DPG draw primitives in that
        # common case; only metadata/textures are updated.
        if can_reuse_rows:
            self._rebuild_pinned_row()
            self._refresh_row_content()
            self._layout_all()
        elif self._header_items and dpg.does_item_exist(self.body_canvas):
            self._rebuild_pinned_row()
            self._rebuild_body_rows()
        else:
            self._rebuild_draw_items()
        self._update_status_bar()
        return self

    def add_item(self, item, refresh=True):
        self.items.append(item)
        self._sync_qt_selection_from_fields()
        if refresh:
            self._sort_items(); self._rebuild_draw_items(); self._update_status_bar()
        return item

    def remove_item(self, item_or_index, refresh=True):
        index = item_or_index if isinstance(item_or_index, int) else self.items.index(item_or_index)
        removed = self.items.pop(index)
        if refresh:
            self.selected.clear()
            self._current_index = None
            self.last_clicked_index = None
            self._sync_qt_selection_from_fields()
            self._rebuild_draw_items(); self._update_status_bar()
        return removed

    def update_item(self, item_or_index, **changes):
        item = self.items[item_or_index] if isinstance(item_or_index, int) else item_or_index
        for name, value in changes.items():
            if not hasattr(item, name):
                raise AttributeError(name)
            setattr(item, name, value)
        if "name" in changes:
            item.extension = os.path.splitext(item.name)[1]
        if any(key in changes for key in ("name", "size", "mtime", "item_type", "is_dir")):
            refresh_cache = getattr(item, "refresh_display_cache", None)
            if callable(refresh_cache):
                refresh_cache()
        self.refresh()
        return item

    def get_items(self):
        return list(self.items)















    def set_item_icon(self, item_or_index, icon):
        item = self.items[item_or_index] if isinstance(item_or_index, int) else item_or_index
        self._item_icons[id(item)] = self._resolve_icon_texture(icon)
        self._refresh_row_content(); return self

    def set_theme(self, theme):
        """Apply a registered fixed theme by name at runtime."""
        self.theme_name, self.theme_config = ListViewThemeManager.resolve(theme)
        self._drag_preview.set_theme(self.theme_config)
        self._build_theme(replace=True)
        dpg.bind_item_theme(self.window_tag, self.theme_pane)
        dpg.bind_item_theme(self.body_window, self.theme_pane)
        if dpg.does_item_exist(self.itemmenu_tag):
            dpg.bind_item_theme(self.itemmenu_tag, self.theme_popup)
        for tag in self._context_submenu_tags.values():
            if dpg.does_item_exist(tag):
                dpg.bind_item_theme(tag, self.theme_popup)
        for tag in (self.status_items_tag, self.status_sel_tag):
            if dpg.does_item_exist(tag):
                dpg.configure_item(tag, color=self.theme_config["status_text"])
        self._rebuild_draw_items()
        return self








    def set_metrics(self, row_height=None, header_height=None, cell_padding=None, min_column_width=None):
        if row_height is not None: self.ROW_HEIGHT = max(16, int(row_height))
        if header_height is not None: self.HEADER_HEIGHT = max(18, int(header_height))
        if cell_padding is not None: self.CELL_PADDING = max(0, int(cell_padding))
        if min_column_width is not None: self.MIN_COLUMN_WIDTH = max(20, int(min_column_width))
        self._ensure_column_widths(force=True); self._rebuild_draw_items(); return self

    def set_sort(self, key, ascending=True):
        self.sort_key = key; self.sort_ascending = bool(ascending); self._sort_and_refresh_in_place(); return self

    def refresh(self):
        self._sort_and_refresh_in_place(); self._update_status_bar(); return self




    def destroy(self):
        self._release_pointer_gesture()
        self.cancel_inline_rename()
        self._hide_rubber_rect()
        if dpg.does_item_exist(self._rubber_layer_tag):
            dpg.delete_item(self._rubber_layer_tag)
        self._rubber_rect_tag = None
        self._drag_preview.destroy()
        overlay = getattr(self, "_scroller_arrow_overlay", None)
        if overlay is not None:
            overlay.destroy()
        self._delete_context_menu_windows()
        self._uninstall_native_cursor_hook()
        if ExplorerListView._resize_cursor_owner is self:
            ExplorerListView._resize_cursor_owner = None
            self._set_mouse_cursor("mvMouseCursor_Arrow")
        for tag in (self._handler_reg, f"{self.uid}_root"):
            if dpg.does_item_exist(tag): dpg.delete_item(tag)


    # ------------------------------- fonts ---------------------------------


    # ------------------------------- layout --------------------------------












    @property
    def _native_hwnd(self):
        return self._native_hook._native_hwnd

    @_native_hwnd.setter
    def _native_hwnd(self, value):
        self._native_hook._native_hwnd = value

    @property
    def _native_old_wndproc(self):
        return self._native_hook._native_old_wndproc

    @_native_old_wndproc.setter
    def _native_old_wndproc(self, value):
        self._native_hook._native_old_wndproc = value

    @property
    def _native_wndproc_callback(self):
        return self._native_hook._native_wndproc_callback

    @_native_wndproc_callback.setter
    def _native_wndproc_callback(self, value):
        self._native_hook._native_wndproc_callback = value

    @property
    def _native_cursor_sizewe(self):
        return self._native_hook._native_cursor_sizewe

    @_native_cursor_sizewe.setter
    def _native_cursor_sizewe(self, value):
        self._native_hook._native_cursor_sizewe = value

    @property
    def _native_cursor_move(self):
        return self._native_hook._native_cursor_move

    @_native_cursor_move.setter
    def _native_cursor_move(self, value):
        self._native_hook._native_cursor_move = value

    @property
    def _native_cursor_copy(self):
        return self._native_hook._native_cursor_copy

    @_native_cursor_copy.setter
    def _native_cursor_copy(self, value):
        self._native_hook._native_cursor_copy = value

    @property
    def _native_cursor_no(self):
        return self._native_hook._native_cursor_no

    @_native_cursor_no.setter
    def _native_cursor_no(self, value):
        self._native_hook._native_cursor_no = value

    @property
    def _native_cursor_arrow(self):
        return self._native_hook._native_cursor_arrow

    @_native_cursor_arrow.setter
    def _native_cursor_arrow(self, value):
        self._native_hook._native_cursor_arrow = value

    @property
    def _native_header_screen_rect(self):
        return self._native_hook._native_header_screen_rect

    @_native_header_screen_rect.setter
    def _native_header_screen_rect(self, value):
        self._native_hook._native_header_screen_rect = value

    @property
    def _native_separator_screen_x(self):
        return self._native_hook._native_separator_screen_x

    @_native_separator_screen_x.setter
    def _native_separator_screen_x(self, value):
        self._native_hook._native_separator_screen_x = value

    @property
    def _native_cursor_hook_active(self):
        return self._native_hook._native_cursor_hook_active

    @_native_cursor_hook_active.setter
    def _native_cursor_hook_active(self, value):
        self._native_hook._native_cursor_hook_active = value

    @property
    def _native_drop_enabled(self):
        return self._native_hook._native_drop_enabled

    @_native_drop_enabled.setter
    def _native_drop_enabled(self, value):
        self._native_hook._native_drop_enabled = value

    def _find_own_top_level_hwnd(self):
        return self._native_hook._find_own_top_level_hwnd()

    def _install_native_cursor_hook(self):
        return self._native_hook._install_native_cursor_hook()

    def _uninstall_native_cursor_hook(self):
        return self._native_hook._uninstall_native_cursor_hook()

    def _update_native_cursor_geometry(self):
        return self._native_hook._update_native_cursor_geometry()

    def _set_mouse_cursor(self, cursor_name):
        """Request a cursor through DPG; Win32 WM_SETCURSOR is authoritative."""
        cursor = getattr(dpg, cursor_name, None)
        setter = getattr(dpg, "set_mouse_cursor", None)
        if cursor is not None and setter is not None:
            try:
                setter(cursor)
            except Exception:
                pass



    def _update_header_cell_visuals(self):
        """Paint QHeaderView-like hover/pressed feedback for header sections."""
        cfg = self.theme_config
        hover_fill = cfg.get("header_hover", QtFusionPalette.HEADER_HOVER)
        pressed_fill = cfg.get("header_pressed", QtFusionPalette.HEADER_PRESSED)
        for key, parts in self._header_items.items():
            background = parts.get("background")
            if not background or not dpg.does_item_exist(background):
                continue
            if key == self._header_pressed_key:
                fill = pressed_fill
            elif key == self._header_hover_key:
                fill = hover_fill
            else:
                fill = (0, 0, 0, 0)
            dpg.configure_item(
                background, fill=fill, color=(0, 0, 0, 0), thickness=0.0)

    def _update_header_hover_state(self):
        """Track the header cell under the pointer without fighting splitters."""
        if (self._rename_active or self._context_menu_is_visible()
                or _overlay_window_owns_input()):
            key = None
        else:
            inside, local_x = self._header_mouse_position()
            if not inside or self._separator_at(local_x) is not None:
                key = None
            else:
                key = self._column_at(local_x)
        if key != self._header_hover_key:
            self._header_hover_key = key
            self._update_header_cell_visuals()

    def _set_separator_hover_state(self, separator_key):
        """Highlight only the separator currently available for resizing."""
        for key, parts in self._header_items.items():
            separator = parts.get("separator")
            if not separator or not dpg.does_item_exist(separator):
                continue
            hovered = key == separator_key
            dpg.configure_item(
                separator,
                color=self.theme_config["drop_border"] if hovered else self.theme_config["separator"],
                thickness=2.0 if hovered else 1.0,
            )

    def _update_resize_cursor(self):
        """Update splitter feedback with the platform horizontal-resize cursor."""
        blocked = (
            self._rename_active
            or self._context_menu_is_visible()
            or _overlay_window_owns_input()
        )
        inside, local_x = (
            (False, 0.0) if blocked else self._header_mouse_position()
        )
        separator = self._separator_at(local_x) if inside else None
        active_separator = self._resize_key or separator

        if separator != self._hover_separator_key:
            self._hover_separator_key = separator

        # A splitter is visually highlighted only while it is actively being
        # dragged. Hover is communicated by the horizontal-resize cursor, so
        # releasing the mouse cannot leave a blue/thick "selected" divider.
        self._set_separator_hover_state(self._resize_key)

        if active_separator:
            # All ExplorerListViews install global mouse handlers. Track the
            # owner so an inactive sibling cannot immediately restore the arrow
            # after this view has selected ResizeEW.
            ExplorerListView._resize_cursor_owner = self
            self._set_mouse_cursor("mvMouseCursor_ResizeEW")

            # The viewport does not exist during widget construction. A real
            # mouse movement is a reliable opportunity to retry the hook.
            if not self._native_cursor_hook_active:
                self._install_native_cursor_hook()

            # Apply the native horizontal-resize cursor immediately. Waiting
            # only for WM_SETCURSOR is unreliable when the pointer moves from
            # the header cell into a splitter while remaining in HTCLIENT.
            if os.name == "nt" and self._native_cursor_sizewe:
                try:
                    user32 = ctypes.windll.user32
                    user32.SetCursor.argtypes = [wintypes.HANDLE]
                    user32.SetCursor.restype = wintypes.HANDLE
                    user32.SetCursor(self._native_cursor_sizewe)

                    # Force Windows to re-run the subclassed WM_SETCURSOR path.
                    # GLFW may restore its arrow later in the same frame, so a
                    # direct SetCursor call alone is not persistent enough.
                    if self._native_hwnd:
                        WM_SETCURSOR = 0x0020
                        HTCLIENT = 1
                        WM_MOUSEMOVE = 0x0200
                        lparam = (WM_MOUSEMOVE << 16) | HTCLIENT
                        user32.SendMessageW(
                            wintypes.HWND(self._native_hwnd),
                            WM_SETCURSOR,
                            wintypes.WPARAM(self._native_hwnd),
                            wintypes.LPARAM(lparam),
                        )
                except Exception:
                    pass
        else:
            self._set_separator_hover_state(None)
            if ExplorerListView._resize_cursor_owner is self:
                ExplorerListView._resize_cursor_owner = None
                self._set_mouse_cursor("mvMouseCursor_Arrow")

        self._update_native_cursor_geometry()


















    # ------------------------------- drawing -------------------------------







































    # ------------------------------ interaction ----------------------------
    def _install_global_handlers(self):
        self._handler_reg = f"{self.uid}_handlers"
        with dpg.handler_registry(tag=self._handler_reg):
            dpg.add_mouse_click_handler(
                button=dpg.mvMouseButton_Left,
                callback=self._on_left_down,
            )
            dpg.add_mouse_drag_handler(
                button=dpg.mvMouseButton_Left,
                threshold=0.0,
                callback=self._on_left_drag,
            )
            dpg.add_mouse_release_handler(
                button=dpg.mvMouseButton_Left,
                callback=self._on_left_release,
            )
            dpg.add_mouse_click_handler(
                button=dpg.mvMouseButton_Right,
                callback=self._on_right_click,
            )
            mouse_move_handler = getattr(dpg, "add_mouse_move_handler", None)
            if mouse_move_handler is not None:
                mouse_move_handler(callback=self._on_mouse_move)

            # Escape cancels whichever transient mouse operation is active:
            # column resize, item drag, rubber-band selection, or pending click.
            key_press_handler = getattr(dpg, "add_key_press_handler", None)
            escape_key = getattr(dpg, "mvKey_Escape", None)
            if key_press_handler is not None and escape_key is not None:
                key_press_handler(
                    key=escape_key,
                    callback=self._on_escape_pressed,
                )

            if key_press_handler is not None:
                for key_name, callback in (
                    ("mvKey_A", self._on_select_all_shortcut),
                    ("mvKey_C", self._on_copy_shortcut),
                    ("mvKey_X", self._on_cut_shortcut),
                    ("mvKey_V", self._on_paste_shortcut),
                    ("mvKey_F2", self._on_rename_shortcut),
                    ("mvKey_F4", self._on_edit_shortcut),
                    ("mvKey_F5", self._on_transfer_shortcut),
                    ("mvKey_F7", self._on_new_folder_shortcut),
                    ("mvKey_R", self._on_refresh_shortcut),
                    ("mvKey_Up", self._on_parent_shortcut),
                    ("mvKey_Delete", self._on_delete_shortcut),
                    # Dear PyGui names the main Enter key mvKey_Return in
                    # current releases; retain mvKey_Enter for older builds.
                    ("mvKey_Return", self._on_enter_pressed),
                    ("mvKey_Enter", self._on_enter_pressed),
                    ("mvKey_Spacebar", self._on_space_pressed),
                    ("mvKey_Space", self._on_space_pressed),
                ):
                    key = getattr(dpg, key_name, None)
                    if key is not None:
                        key_press_handler(key=key, callback=callback)

                # QAbstractItemView-style current-index navigation.  These
                # handlers are global in Dear PyGui but only the focused view
                # accepts them, so Local/Server/Job views remain independent.
                for key_name, command in (
                    ("mvKey_Up", "up"),
                    ("mvKey_Down", "down"),
                    ("mvKey_Home", "home"),
                    ("mvKey_End", "end"),
                    ("mvKey_PageUp", "page_up"),
                    ("mvKey_PageDown", "page_down"),
                ):
                    key = getattr(dpg, key_name, None)
                    if key is not None:
                        key_press_handler(
                            key=key, callback=self._on_navigation_key,
                            user_data=command)

                for key_name, command in (
                    ("mvKey_Up", "up"),
                    ("mvKey_Down", "down"),
                    ("mvKey_Left", "left"),
                    ("mvKey_Right", "right"),
                    ("mvKey_Return", "activate"),
                    ("mvKey_Enter", "activate"),
                ):
                    key = getattr(dpg, key_name, None)
                    if key is not None:
                        key_press_handler(
                            key=key, callback=self._on_context_menu_key,
                            user_data=command)









    def _clear_hover(self):
        """Remove the current row hover immediately."""
        self._hide_tooltip_parts(
            getattr(self, "_body_item_tooltip", None))
        old_hover = self.hover_index
        if old_hover is None:
            return
        self.hover_index = None
        self._update_row_visual(old_hover)





    def _cancel_current_operation(self):
        """Cancel every transient interaction without committing its result."""
        self._header_gesture = False
        self._header_pressed_key = None
        self._header_dragged = False
        self._separator_click_candidate_key = None
        self._update_header_cell_visuals()
        self._release_pointer_gesture()
        was_resizing = self._resize_key is not None
        was_rubber = self._rubber_active
        was_item_drag = self._item_drag_active

        # Restore widths captured at the beginning of a column resize.
        if was_resizing:
            self._column_widths[self._resize_key] = self._resize_start_width
            if self._resize_next_key:
                self._column_widths[self._resize_next_key] = self._resize_next_start_width
            self._queue_layout()

        # Escape is a full cancel command for this ListView. It cancels the
        # transient interaction and clears the current selection as requested.
        # Do not restore the rubber-band base selection; Escape leaves no item
        # selected regardless of which operation was active.

        old_target = self._drop_target_index
        self._mouse_down = False
        self._mouse_down_time = 0.0
        self._drag_started = False
        self._rubber_active = False
        self._pending_click_index = None
        self._drag_origin_on_item = False
        self._double_click_gesture = False
        self._drag_source_index = None
        self._drag_source_items = []
        self._item_drag_active = False
        self._drop_target_index = None
        self._drag_cursor_active = False

        self._resize_key = None
        self._resize_next_key = None
        self._resize_next_start_width = 0.0
        self._hover_separator_key = None

        self._hide_rubber_rect()
        self._drag_preview.end()
        self._set_separator_hover_state(None)
        self._update_row_visual(old_target)
        self._set_mouse_cursor("mvMouseCursor_Arrow")
        self._update_resize_cursor()
        self._clear_hover()

        # Clear persistent selection too. clear_selection() also refreshes row
        # visuals, status text, and emits on_selection_change exactly once.
        self.clear_selection()

    def _on_escape_pressed(self, sender=None, app_data=None, user_data=None):
        return self._keyboard._on_escape_pressed(sender, app_data, user_data)


    def _on_select_all_shortcut(self, sender=None, app_data=None, user_data=None):
        return self._keyboard._on_select_all_shortcut(sender, app_data, user_data)

    def _dispatch_clipboard_command(self, action):
        return self._keyboard._dispatch_clipboard_command(action)

    def _on_copy_shortcut(self, sender=None, app_data=None, user_data=None):
        return self._keyboard._on_copy_shortcut(sender, app_data, user_data)

    def _on_cut_shortcut(self, sender=None, app_data=None, user_data=None):
        return self._keyboard._on_cut_shortcut(sender, app_data, user_data)

    def _on_paste_shortcut(self, sender=None, app_data=None, user_data=None):
        return self._keyboard._on_paste_shortcut(sender, app_data, user_data)

    def _on_rename_shortcut(self, sender=None, app_data=None, user_data=None):
        return self._keyboard._on_rename_shortcut(sender, app_data, user_data)

    def _dispatch_winscp_command(self, action, require_selection=False):
        return self._keyboard._dispatch_winscp_command(action, require_selection)

    def _on_edit_shortcut(self, sender=None, app_data=None, user_data=None):
        return self._keyboard._on_edit_shortcut(sender, app_data, user_data)

    def _on_transfer_shortcut(self, sender=None, app_data=None, user_data=None):
        return self._keyboard._on_transfer_shortcut(sender, app_data, user_data)

    def _on_new_folder_shortcut(self, sender=None, app_data=None, user_data=None):
        return self._keyboard._on_new_folder_shortcut(sender, app_data, user_data)

    def _on_refresh_shortcut(self, sender=None, app_data=None, user_data=None):
        return self._keyboard._on_refresh_shortcut(sender, app_data, user_data)

    def _on_parent_shortcut(self, sender=None, app_data=None, user_data=None):
        return self._keyboard._on_parent_shortcut(sender, app_data, user_data)

    def _on_delete_shortcut(self, sender=None, app_data=None, user_data=None):
        return self._keyboard._on_delete_shortcut(sender, app_data, user_data)

    def _keyboard_item_view_ready(self):
        return self._keyboard._keyboard_item_view_ready()

    def _keyboard_current_index(self):
        return self._keyboard._keyboard_current_index()

    def _ensure_index_visible(self, index):
        return self._keyboard._ensure_index_visible(index)

    def _apply_keyboard_current(self, target):
        return self._keyboard._apply_keyboard_current(target)

    def _on_navigation_key(self, sender=None, app_data=None, user_data=None):
        return self._keyboard._on_navigation_key(sender, app_data, user_data)

    def _on_space_pressed(self, sender=None, app_data=None, user_data=None):
        return self._keyboard._on_space_pressed(sender, app_data, user_data)

    def _on_enter_pressed(self, sender=None, app_data=None, user_data=None):
        return self._keyboard._on_enter_pressed(sender, app_data, user_data)






































    # ------------------------------ data -----------------------------------





if __name__ == "__main__":

    def build_items_for(path):
        entries = []
        try:
            for name in os.listdir(path):
                entries.append(ListViewItem.from_path(os.path.join(path, name)))
        except PermissionError:
            pass
        return entries

    def on_activate(item):
        if item.is_dir:
            view.set_items(build_items_for(item.path))
            dpg.set_value("demo_path", item.path)

    def on_menu_action(action, items):
        names = ", ".join(i.name for i in items)
        print(f"[context menu] {action} -> {names}")

    def on_items_moved(moves):
        for item, new_path, target_dir in moves:
            print(f"[moved] {item.path} -> {new_path}")

    try:
        dpg.destroy_context()
    except Exception:
        pass

    dpg.create_context()
    dpg.create_viewport(title="ExplorerListView Demo", width=980, height=640)
    start_dir = os.path.expanduser("~")

    try:
        with dpg.window(tag="primary", label="ExplorerListView Demo"):
            dpg.add_text(start_dir, tag="demo_path", color=(120, 120, 120))
            view = ExplorerListView(
                parent="primary", items=build_items_for(start_dir),
                width=-1, height=-1, on_activate=on_activate,
                on_item_menu_action=on_menu_action,
                on_items_moved=on_items_moved
            )
        dpg.setup_dearpygui()
        dpg.show_viewport()
        dpg.set_primary_window("primary", True)
        dpg.start_dearpygui()
    finally:
        dpg.destroy_context()
