"""CMD-style SSH console with one protected transcript and inline command line."""
from __future__ import annotations

import ctypes
import os
import re
import time
from ctypes import wintypes

import dearpygui.dearpygui as dpg

from .qt_dialog import QtDialog
from ..components.console_renderer import ConsoleRenderer
from ..runtime.terminal_buffer import TerminalBuffer, clean_output
from ..components.interaction_gate import unregister_pointer_protected_item
from ..components.shared_scroller import add_dpg_scroller_style, DpgScrollerArrowOverlay
from ..components.qt_style import QtFusionPalette
from ..widgets.imgui_qt_style import button_theme

BLACK = (12, 12, 12, 255)
TEXT = (212, 212, 212, 255)
PROMPT = (160, 160, 160, 255)
COMMAND = (113, 205, 138, 255)
COMMAND_PENDING = (93, 164, 110, 255)
WARNING = (224, 195, 92, 255)
ERROR = (232, 106, 106, 255)
SUCCESS = (109, 201, 119, 255)
CURRENT_LINE = (24, 24, 24, 255)
SELECTION = (38, 79, 120, 180)
FIND_MATCH = (111, 86, 18, 190)
FIND_CURRENT = (180, 112, 20, 230)
FIND_BG = (28, 28, 28, 245)
FIND_BORDER = (92, 92, 92, 255)
FIND_TEXT = (235, 235, 235, 255)
FIND_MUTED = (170, 170, 170, 255)


# Use the native Windows text clipboard for the terminal.  DPG's clipboard
# bridge is safe for ordinary UI callbacks, but it can re-enter GLFW/Win32
# message dispatch when a context-menu action has just closed.  Keeping the
# terminal clipboard path entirely in Win32 avoids that native re-entry.
_CF_UNICODETEXT = 13
_GMEM_MOVEABLE = 0x0002
_GMEM_ZEROINIT = 0x0040

def _win_clipboard_text_get():
    if os.name != "nt":
        try:
            return str(dpg.get_clipboard_text() or "")
        except Exception:
            return ""
    user32 = ctypes.windll.user32
    kernel32 = ctypes.windll.kernel32
    user32.OpenClipboard.argtypes = [wintypes.HWND]
    user32.OpenClipboard.restype = wintypes.BOOL
    user32.CloseClipboard.argtypes = []
    user32.CloseClipboard.restype = wintypes.BOOL
    user32.GetClipboardData.argtypes = [wintypes.UINT]
    user32.GetClipboardData.restype = wintypes.HANDLE
    user32.IsClipboardFormatAvailable.argtypes = [wintypes.UINT]
    user32.IsClipboardFormatAvailable.restype = wintypes.BOOL
    kernel32.GlobalLock.argtypes = [wintypes.HGLOBAL]
    kernel32.GlobalLock.restype = ctypes.c_void_p
    kernel32.GlobalUnlock.argtypes = [wintypes.HGLOBAL]
    kernel32.GlobalUnlock.restype = wintypes.BOOL
    if not user32.IsClipboardFormatAvailable(_CF_UNICODETEXT):
        return ""
    opened = False
    for _ in range(20):
        if user32.OpenClipboard(None):
            opened = True
            break
        time.sleep(0.005)
    if not opened:
        return ""
    try:
        handle = user32.GetClipboardData(_CF_UNICODETEXT)
        if not handle:
            return ""
        pointer = kernel32.GlobalLock(handle)
        if not pointer:
            return ""
        try:
            return str(ctypes.wstring_at(pointer) or "")
        finally:
            kernel32.GlobalUnlock(handle)
    finally:
        user32.CloseClipboard()

def _win_clipboard_has_text():
    """Cheap availability probe used while opening the context menu.

    Do not open/lock the clipboard merely to decide whether Paste should be
    enabled.  On Windows this avoids the retry loop in ``_win_clipboard_text_get``
    and keeps RMB menu presentation immediate even when another process has
    the clipboard temporarily open.
    """
    if os.name != "nt":
        try:
            return bool(dpg.get_clipboard_text())
        except Exception:
            return False
    try:
        user32 = ctypes.windll.user32
        user32.IsClipboardFormatAvailable.argtypes = [wintypes.UINT]
        user32.IsClipboardFormatAvailable.restype = wintypes.BOOL
        return bool(user32.IsClipboardFormatAvailable(_CF_UNICODETEXT))
    except Exception:
        return False


def _win_clipboard_text_set(value):
    value = str(value or "")
    if os.name != "nt":
        try:
            dpg.set_clipboard_text(value)
            return True
        except Exception:
            return False
    user32 = ctypes.windll.user32
    kernel32 = ctypes.windll.kernel32
    user32.OpenClipboard.argtypes = [wintypes.HWND]
    user32.OpenClipboard.restype = wintypes.BOOL
    user32.CloseClipboard.argtypes = []
    user32.CloseClipboard.restype = wintypes.BOOL
    user32.EmptyClipboard.argtypes = []
    user32.EmptyClipboard.restype = wintypes.BOOL
    user32.SetClipboardData.argtypes = [wintypes.UINT, wintypes.HANDLE]
    user32.SetClipboardData.restype = wintypes.HANDLE
    kernel32.GlobalAlloc.argtypes = [wintypes.UINT, ctypes.c_size_t]
    kernel32.GlobalAlloc.restype = wintypes.HGLOBAL
    kernel32.GlobalLock.argtypes = [wintypes.HGLOBAL]
    kernel32.GlobalLock.restype = ctypes.c_void_p
    kernel32.GlobalUnlock.argtypes = [wintypes.HGLOBAL]
    kernel32.GlobalUnlock.restype = wintypes.BOOL
    kernel32.GlobalFree.argtypes = [wintypes.HGLOBAL]
    kernel32.GlobalFree.restype = wintypes.HGLOBAL
    payload = (value + "\0").encode("utf-16-le")
    opened = False
    for _ in range(20):
        if user32.OpenClipboard(None):
            opened = True
            break
        time.sleep(0.005)
    if not opened:
        return False
    handle = None
    try:
        if not user32.EmptyClipboard():
            return False
        handle = kernel32.GlobalAlloc(_GMEM_MOVEABLE | _GMEM_ZEROINIT, len(payload))
        if not handle:
            return False
        pointer = kernel32.GlobalLock(handle)
        if not pointer:
            kernel32.GlobalFree(handle)
            return False
        try:
            ctypes.memmove(pointer, payload, len(payload))
        finally:
            kernel32.GlobalUnlock(handle)
        if not user32.SetClipboardData(_CF_UNICODETEXT, handle):
            kernel32.GlobalFree(handle)
            return False
        handle = None  # ownership transferred to Windows
        return True
    finally:
        if handle:
            try:
                kernel32.GlobalFree(handle)
            except Exception:
                pass
        user32.CloseClipboard()


STYLE_COLORS = {
    "output": TEXT,
    "prompt": PROMPT,
    "command": COMMAND,
    "command_pending": COMMAND_PENDING,
    "warning": WARNING,
    "error": ERROR,
    "success": SUCCESS,
}


class _ConsoleContextMenu:
    """Qt/QMenu-like *modeless* context surface for the terminal.

    This deliberately remains an ordinary DPG window rather than an ImGui
    popup or a Win32 TrackPopupMenu loop.  The menu therefore cannot hold the
    application's popup/modal stack after it closes.  Keyboard current-row
    state is rendered locally and never steals focus from the terminal.
    """

    WIDTH = 202
    ROW_HEIGHT = 25
    SEPARATOR_HEIGHT = 7
    SEPARATORS_AFTER = frozenset(("paste", "find"))
    ACTIONS = (
        ("copy", "Copy", "Ctrl+C"),
        ("paste", "Paste", "Ctrl+V"),
        ("select_all", "Select All", "Ctrl+A"),
        ("find", "Find", "Ctrl+F"),
        ("clear", "Clear", ""),
    )

    def __init__(self, owner):
        self.owner = owner
        self.tag = dpg.generate_uuid()
        self._items = {}
        self._enabled = {}
        self._shortcuts = {}
        self._handler_registry = None
        self._row_handler_registries = []
        self._visible = False
        self._current_action = None
        self._last_open_time = 0.0
        self._last_open_position = None
        self._themes = []

        self._normal_theme = self._make_row_theme(
            QtFusionPalette.MENU, QtFusionPalette.MENU_HOVER,
            QtFusionPalette.MENU_ACTIVE, QtFusionPalette.TEXT)
        self._current_theme = self._make_row_theme(
            QtFusionPalette.MENU_ACTIVE, QtFusionPalette.MENU_ACTIVE,
            QtFusionPalette.MENU_ACTIVE, QtFusionPalette.TEXT)
        self._disabled_theme = self._make_row_theme(
            QtFusionPalette.MENU, QtFusionPalette.MENU,
            QtFusionPalette.MENU, QtFusionPalette.TEXT_DISABLED)

        height = (
            6 + self.ROW_HEIGHT * len(self.ACTIONS)
            + self.SEPARATOR_HEIGHT * len(self.SEPARATORS_AFTER) + 8
        )
        with dpg.window(
                tag=self.tag,
                show=False,
                width=self.WIDTH,
                height=height,
                no_title_bar=True,
                no_resize=True,
                no_move=True,
                no_saved_settings=True,
                no_scrollbar=True,
                no_scroll_with_mouse=True,
                no_bring_to_front_on_focus=False):
            for action, label, shortcut in self.ACTIONS:
                self._add_item(action, label, shortcut)
                if action in self.SEPARATORS_AFTER:
                    separator = dpg.add_separator()
                    dpg.bind_item_theme(separator, self._separator_theme())

        with dpg.theme() as self._window_theme:
            with dpg.theme_component(dpg.mvWindowAppItem):
                dpg.add_theme_color(dpg.mvThemeCol_WindowBg, QtFusionPalette.MENU)
                dpg.add_theme_color(dpg.mvThemeCol_Border, QtFusionPalette.BORDER)
                dpg.add_theme_color(dpg.mvThemeCol_Separator, QtFusionPalette.BORDER_LIGHT)
                dpg.add_theme_style(dpg.mvStyleVar_WindowBorderSize, 1)
                dpg.add_theme_style(dpg.mvStyleVar_WindowRounding, 1)
                dpg.add_theme_style(dpg.mvStyleVar_WindowPadding, 3, 3)
                dpg.add_theme_style(dpg.mvStyleVar_ItemSpacing, 0, 1)
        dpg.bind_item_theme(self.tag, self._window_theme)

        # Deliberately do NOT bind RMB to the draw-list.  A global release
        # observer defers the DPG hover test/menu open until after input
        # dispatch, avoiding the old canvas ActiveId/blocking regression.  LMB
        # and MMB remain item-scoped to the terminal canvas.
        with dpg.item_handler_registry() as self._handler_registry:
            dpg.add_item_clicked_handler(
                button=dpg.mvMouseButton_Left,
                callback=owner._canvas_left_click,
            )
            dpg.add_item_clicked_handler(
                button=dpg.mvMouseButton_Middle,
                callback=owner._middle_click,
            )
            # Direct canvas fallback for RMB.  This handler only arms a
            # deferred open; it never mutates the menu/item tree while the
            # physical right button is down.
            dpg.add_item_clicked_handler(
                button=dpg.mvMouseButton_Right,
                callback=owner._canvas_right_click,
            )
        dpg.bind_item_handler_registry(owner.canvas, self._handler_registry)

    def _separator_theme(self):
        with dpg.theme() as theme:
            with dpg.theme_component(dpg.mvSeparator):
                dpg.add_theme_color(dpg.mvThemeCol_Separator, QtFusionPalette.BORDER_LIGHT)
                dpg.add_theme_color(dpg.mvThemeCol_SeparatorHovered, QtFusionPalette.BORDER_LIGHT)
                dpg.add_theme_color(dpg.mvThemeCol_SeparatorActive, QtFusionPalette.BORDER_LIGHT)
        self._themes.append(theme)
        return theme

    def _make_row_theme(self, face, hover, active, text):
        with dpg.theme() as theme:
            with dpg.theme_component(dpg.mvButton):
                dpg.add_theme_color(dpg.mvThemeCol_Button, face)
                dpg.add_theme_color(dpg.mvThemeCol_ButtonHovered, hover)
                dpg.add_theme_color(dpg.mvThemeCol_ButtonActive, active)
                dpg.add_theme_color(dpg.mvThemeCol_Text, text)
                dpg.add_theme_color(dpg.mvThemeCol_Border, (0, 0, 0, 0))
                dpg.add_theme_style(dpg.mvStyleVar_FrameBorderSize, 0)
                dpg.add_theme_style(dpg.mvStyleVar_FrameRounding, 0)
                dpg.add_theme_style(dpg.mvStyleVar_FramePadding, 7, 3)
                align = getattr(dpg, "mvStyleVar_ButtonTextAlign", None)
                if align is not None:
                    dpg.add_theme_style(align, 0.0, 0.5)
        self._themes.append(theme)
        return theme

    @staticmethod
    def _row_label(label, shortcut):
        # DPG buttons do not expose Qt's independent shortcut column.  Keep a
        # compact, deterministic visual gap while retaining one full-row hit
        # target.  The width is fixed, so this reads like a QMenu shortcut
        # column without introducing a second non-clickable widget.
        if not shortcut:
            return label
        gap = max(2, 22 - len(label) - len(shortcut))
        return "{}{}{}".format(label, " " * gap, shortcut)

    def _add_item(self, action, label, shortcut):
        tag = dpg.add_button(
            label=self._row_label(label, shortcut),
            width=self.WIDTH - 8,
            height=self.ROW_HEIGHT,
            callback=self._clicked,
            user_data=action,
        )
        self._items[action] = tag
        self._shortcuts[action] = shortcut
        self._enabled[action] = True
        dpg.bind_item_theme(tag, self._normal_theme)
        # QMenu tracks the current action under the pointer.  Keep this local
        # to each row; no global mouse capture/focus is involved.
        try:
            with dpg.item_handler_registry() as registry:
                dpg.add_item_hover_handler(callback=self._hovered, user_data=action)
            dpg.bind_item_handler_registry(tag, registry)
            self._row_handler_registries.append(registry)
        except Exception:
            pass

    def _hovered(self, sender=None, app_data=None, user_data=None):
        if not self._visible:
            return
        action = str(user_data or "")
        if self._enabled.get(action, False):
            self._set_current(action)
        elif self._current_action == action:
            self._set_current(None)

    def _clicked(self, sender=None, app_data=None, user_data=None):
        action = str(user_data or "")
        if not self._enabled.get(action, True):
            return
        self._set_current(action)
        # Let Dear ImGui finish this physical click before terminal state or
        # the Windows clipboard is mutated.
        try:
            self.owner.view.after(
                0, self.owner._context_menu_triggered, action, self.owner)
        except Exception:
            self.owner._context_menu_triggered(action, self.owner)

    def _apply_theme(self, action):
        item = self._items.get(action)
        if item is None:
            return
        if not self._enabled.get(action, True):
            theme = self._disabled_theme
        elif action == self._current_action:
            theme = self._current_theme
        else:
            theme = self._normal_theme
        try:
            if dpg.does_item_exist(item):
                # Keep the widget technically enabled so DPG cannot replace
                # our left-aligned menu palette/metrics with disabled-button
                # defaults.  Logical enablement is enforced in _clicked().
                dpg.configure_item(item, enabled=True)
                dpg.bind_item_theme(item, theme)
        except Exception:
            pass

    def _set_current(self, action):
        action = str(action) if action is not None else None
        if action is not None and not self._enabled.get(action, False):
            action = None
        old = self._current_action
        self._current_action = action
        if old is not None:
            self._apply_theme(old)
        if action is not None:
            self._apply_theme(action)

    def _enabled_actions(self):
        return [action for action, _label, _shortcut in self.ACTIONS
                if self._enabled.get(action, True)]

    def setActionEnabled(self, action, enabled):
        action = str(action)
        enabled = bool(enabled)
        self._enabled[action] = enabled
        if not enabled and self._current_action == action:
            self._current_action = None
        self._apply_theme(action)
        return action in self._items

    def move_current(self, delta):
        if not self._visible:
            return False
        actions = self._enabled_actions()
        if not actions:
            self._set_current(None)
            return False
        try:
            index = actions.index(self._current_action)
        except ValueError:
            index = -1 if delta >= 0 else 0
        index = (index + (1 if delta >= 0 else -1)) % len(actions)
        self._set_current(actions[index])
        return True

    def activate_current(self):
        return self.trigger(self._current_action)

    def trigger(self, action):
        """Activate one logical menu action without relying on button focus."""
        if not self._visible:
            return False
        action = str(action or "")
        if action not in self._items or not self._enabled.get(action, False):
            return False
        self._set_current(action)
        try:
            self.owner.view.after(
                0, self.owner._context_menu_triggered, action, self.owner)
        except Exception:
            self.owner._context_menu_triggered(action, self.owner)
        return True

    @property
    def is_open(self):
        return bool(self._visible)

    def _clamp_position(self, position):
        try:
            x, y = map(int, position)
        except Exception:
            x, y = 0, 0
        try:
            viewport_w = int(dpg.get_viewport_client_width() or 0)
            viewport_h = int(dpg.get_viewport_client_height() or 0)
        except Exception:
            viewport_w = viewport_h = 0
        try:
            _width, height = dpg.get_item_rect_size(self.tag)
            height = int(height or 0)
        except Exception:
            height = 0
        if height <= 0:
            height = (
            6 + self.ROW_HEIGHT * len(self.ACTIONS)
            + self.SEPARATOR_HEIGHT * len(self.SEPARATORS_AFTER) + 8
        )
        if viewport_w > self.WIDTH + 8:
            x = max(4, min(x, viewport_w - self.WIDTH - 4))
        if viewport_h > height + 8:
            y = max(4, min(y, viewport_h - height - 4))
        return x, y

    def popup(self, position=None, *, context=None):
        """Open/reposition without entering any popup/modal stack."""
        try:
            if position is None:
                position = dpg.get_mouse_pos(local=False)
            position = self._clamp_position(position)
            now = time.monotonic()
            # Native interception and the release fallback can observe the same
            # physical gesture on unusual backend/window-hook paths.  Treat a
            # near-identical open as one event rather than rebuilding state.
            duplicate = (
                self._visible
                and self._last_open_position == position
                and now - self._last_open_time < 0.12
            )
            self._last_open_time = now
            self._last_open_position = position
            if duplicate:
                return True
            dpg.set_item_pos(self.tag, position)
            dpg.configure_item(self.tag, show=True)
            self._visible = True
            enabled = self._enabled_actions()
            self._set_current(enabled[0] if enabled else None)
            return True
        except Exception:
            self._visible = False
            return False

    def hide(self):
        self._visible = False
        self._set_current(None)
        try:
            dpg.configure_item(self.tag, show=False)
            return True
        except Exception:
            return False

    def delete(self):
        self._visible = False
        self._current_action = None
        items = [
            self.tag, self._handler_registry, *self._row_handler_registries,
            self._window_theme, *self._themes
        ]
        seen = set()
        for item in items:
            if not item or item in seen:
                continue
            seen.add(item)
            try:
                if dpg.does_item_exist(item):
                    dpg.delete_item(item)
            except Exception:
                pass



def terminal_theme():
    with dpg.theme() as theme:
        with dpg.theme_component(dpg.mvAll):
            dpg.add_theme_color(dpg.mvThemeCol_WindowBg, BLACK)
            dpg.add_theme_color(dpg.mvThemeCol_ChildBg, BLACK)
            dpg.add_theme_color(dpg.mvThemeCol_Text, TEXT)
            dpg.add_theme_color(dpg.mvThemeCol_Border, QtFusionPalette.BORDER_DARK)
            add_dpg_scroller_style(dpg)
            dpg.add_theme_style(dpg.mvStyleVar_WindowPadding, 4, 4)
            dpg.add_theme_style(dpg.mvStyleVar_ItemSpacing, 0, 0)
            dpg.add_theme_style(dpg.mvStyleVar_WindowBorderSize, 0)
            dpg.add_theme_style(dpg.mvStyleVar_ChildBorderSize, 0)
        with dpg.theme_component(dpg.mvWindowAppItem):
            dpg.add_theme_style(dpg.mvStyleVar_WindowPadding, 0, 0)
    return theme


class ConsoleDialog(QtDialog):
    clean_output = staticmethod(clean_output)
    updated_history = TerminalBuffer.updated_history

    def __init__(self, view, output_callback, command_callback, interrupt_callback, error_callback=None):
        self.output_callback, self.command_callback = output_callback, command_callback
        self.interrupt_callback, self.error_callback = interrupt_callback, error_callback
        self.buffer = TerminalBuffer()
        self._last_output = None
        self._follow_tail = True
        self._scroll_pending = False
        self._surrogate = None
        self._last_paint = None
        self._line_height = 17
        self._char_width = 8
        self._font = getattr(view, "terminal_font", None)
        self._selection_anchor = None
        self._selection_focus = None
        self._selection_dragging = False
        self._selection_items = []
        self._find_items = []
        self._find_match_items = []
        self._render_rows = []
        self._clear_base = None
        self._clear_prompt = ""
        self._last_known_prompt = ""
        self._find_active = False
        self._find_query = ""
        self._find_matches = []
        self._find_index = -1
        self._find_dirty = True
        self._find_columns = None
        self._find_pending_scroll = False
        self._last_click_time = 0.0
        self._last_click_row = None
        self._click_count = 0
        self._context_menu_pending = False
        self._suppress_left_click_until = 0.0
        super().__init__(view, "SSH Console", 760, 440, modal=False, footer=False)
        self.preferred_size = (760, 440)
        self._theme = terminal_theme()
        dpg.bind_item_theme(self.tag, self._theme)
        dpg.bind_item_theme(self.content, self._theme)
        self._scroller_arrow_overlay = DpgScrollerArrowOverlay(
            dpg, self.content, f"{self.tag}_scroller", vertical=True, horizontal=False)
        with dpg.drawlist(parent=self.content, width=600, height=20) as self.canvas:
            # Keep terminal rows under our own pixel control instead of relying
            # on Dear PyGui's multiline draw_text layout. That makes the caret
            # track the active row exactly and avoids the visible vertical drift
            # seen on some Windows builds when the console is resized.
            self._line_items = []
            self._current_line_fill = dpg.draw_rectangle((0, 0), (0, 0), color=CURRENT_LINE, fill=CURRENT_LINE)
            self._caret = dpg.draw_rectangle((0, 0), (7, 2), color=COMMAND, fill=COMMAND)
        self._create_context_menu()
        # Compatibility: one terminal owns both output and editable command.
        self.output = self.input = self.canvas
        self.shortcuts[(dpg.mvKey_Up, False)] = lambda: self.view.after(0, self._up_key)
        self.shortcuts[(dpg.mvKey_Down, False)] = lambda: self.view.after(0, self._down_key)
        self.shortcuts[(dpg.mvKey_Home, False)] = lambda: self.view.after(0, self._home)
        self.shortcuts[(dpg.mvKey_End, False)] = lambda: self.view.after(0, self._end)
        self.shortcuts[(dpg.mvKey_Delete, False)] = lambda: self.view.after(0, self._delete)
        self.shortcuts[(dpg.mvKey_C, True)] = lambda: self.view.after(0, self._control_c)
        self.shortcuts[(dpg.mvKey_A, True)] = lambda: self.view.after(0, self._select_all)
        with dpg.handler_registry() as self._terminal_handlers:
            for key, callback in ((dpg.mvKey_Back, self._backspace), (dpg.mvKey_V, self._paste),
                                  (dpg.mvKey_Tab, self._tab), (dpg.mvKey_Left, self._left),
                                  (dpg.mvKey_Right, self._right)):
                dpg.add_key_press_handler(key=key, callback=lambda s,a,u: self.view.after(0, u), user_data=callback)
            dpg.add_key_press_handler(key=dpg.mvKey_F, callback=self._find_shortcut)
            dpg.add_key_press_handler(key=dpg.mvKey_F3, callback=self._find_repeat_shortcut)
            dpg.add_mouse_wheel_handler(callback=self._wheel)
            dpg.add_mouse_drag_handler(button=dpg.mvMouseButton_Left, threshold=1.0, callback=self._mouse_drag)
            dpg.add_mouse_release_handler(button=dpg.mvMouseButton_Left, callback=self._mouse_release)
            dpg.add_mouse_release_handler(
                button=dpg.mvMouseButton_Right, callback=self._right_release_fallback)
            # Keep one lightweight global LMB observer only to relinquish the
            # console's WM_CHAR ownership after the user clicks elsewhere. All
            # terminal click/selection work itself is item-scoped to the
            # draw-list above; this callback only schedules a deferred focus
            # check and never mutates the destination widget in this batch.
            dpg.add_mouse_click_handler(
                button=dpg.mvMouseButton_Left, callback=self._mouse_click)
        self.focus_input()
        self._refresh()
        self.view.after(0, self._paint_tick)

    def focus_input(self, follow_tail=True):
        if self.winfo_exists():
            if follow_tail:
                self._follow_tail = True
                self._scroll_pending = True
            # Focus the dialog window rather than the child scrolling region.
            # This keeps QtDialog shortcut dispatch and native WM_CHAR routing
            # aligned with the console while still rendering the terminal in
            # the child area.
            dpg.focus_item(self.tag)

    def native_right_click(self, x=None, y=None):
        """Open the modeless context surface after Win32 RMB dispatch ends.

        The global RMB release observer defers this callback until after the
        Dear PyGui callback batch has completed, so it may safely update the
        modeless menu without entering a native/ImGui popup loop.
        """
        if not self.winfo_exists():
            return False
        menu = getattr(self, "_context_menu_obj", None)
        if menu is None:
            return False
        self._prepare_context_menu_state()
        try:
            if x is None or y is None:
                position = tuple(map(int, dpg.get_mouse_pos(local=False)))
            else:
                position = (int(x), int(y))
            opened = bool(menu.popup(position, context=self))
        except Exception:
            opened = False
        if opened:
            setter = getattr(self.view, "_set_console_keyboard_active", None)
            if callable(setter):
                try:
                    setter(True, self)
                except Exception:
                    pass
        self._context_menu_pending = False
        return opened

    def _terminal_rect_contains(self, position):
        """Hit-test the visible Console viewport using DPG geometry.

        Capture this while the RMB release callback is still being dispatched.
        ``is_item_hovered`` is intentionally avoided here: for a drawlist inside
        a scrolling child window its hover flag can already be false by the next
        deferred callback/frame even though the physical RMB happened over the
        Console.
        """
        try:
            mx, my = map(float, position)
            x0, y0 = map(float, dpg.get_item_rect_min(self.content))
            width, height = map(float, dpg.get_item_rect_size(self.content))
            return width > 0 and height > 0 and x0 <= mx < x0 + width and y0 <= my < y0 + height
        except Exception:
            return False

    def _right_release_fallback(self, sender=None, app_data=None, user_data=None):
        """Open the terminal menu from the global RMB release observer.

        The decisive hit-test is performed *now*, while this physical release is
        still associated with the pointer position.  Only the menu mutation is
        deferred.  This prevents the old failure mode where a next-frame
        ``is_item_hovered`` query returned False and silently discarded the RMB.
        """
        if not self.winfo_exists():
            return
        menu = getattr(self, "_context_menu_obj", None)
        if menu is None:
            return
        try:
            position = tuple(map(int, dpg.get_mouse_pos(local=False)))
        except Exception:
            return
        if bool(getattr(menu, "is_open", False)):
            # QMenu-like dismissal is deferred so the target of an outside RMB
            # still receives that physical click.
            if not self._mouse_over_context_menu():
                try:
                    self.view.after(0, self._hide_context_menu)
                except Exception:
                    pass
            return
        if self._context_menu_pending or not self._terminal_rect_contains(position):
            return
        self._context_menu_pending = True
        try:
            # Do not alter the item tree inside the physical RMB callback.
            # Reuse the position/hit decision captured above after this callback
            # batch has completed.
            self.view.after(0, self._open_context_menu_fallback, position)
        except Exception:
            self._context_menu_pending = False

    def _open_context_menu_fallback(self, position=None):
        try:
            if not self.winfo_exists():
                return
            menu = getattr(self, "_context_menu_obj", None)
            if menu is None or bool(getattr(menu, "is_open", False)):
                return
            # The RMB was already hit-tested in _right_release_fallback. Never
            # re-query hover here; that delayed hover query was the root cause
            # of the menu apparently doing nothing on the dock Console.
            if position is None:
                position = tuple(map(int, dpg.get_mouse_pos(local=False)))
            self.native_right_click(*position)
        finally:
            # Never let a lost/failed open leave RMB permanently suppressed.
            self._context_menu_pending = False

    def _canvas_right_click(self, sender=None, app_data=None, user_data=None):
        """Arm a safe RMB open from the terminal drawlist itself.

        Some DearPyGui/GLFW builds do not reliably enqueue the global mouse
        release handler for a scrolling child window.  The drawlist item-click
        path is already proven for LMB/MMB, so use it as a second source.  The
        context surface is still opened only *after* RMB is released.
        """
        if not self.winfo_exists():
            return
        menu = getattr(self, "_context_menu_obj", None)
        if menu is None or bool(getattr(menu, "is_open", False)):
            return
        try:
            position = tuple(map(int, dpg.get_mouse_pos(local=False)))
        except Exception:
            return
        self._queue_context_menu_after_right_release(position)

    def _queue_context_menu_after_right_release(self, position):
        if self._context_menu_pending:
            return
        self._context_menu_pending = True
        started = time.monotonic()
        try:
            self.view.after(0, self._wait_context_menu_right_release, position, started)
        except Exception:
            self._context_menu_pending = False

    def _wait_context_menu_right_release(self, position, started):
        if not self.winfo_exists():
            self._context_menu_pending = False
            return
        try:
            down = bool(dpg.is_mouse_button_down(dpg.mvMouseButton_Right))
        except Exception:
            down = False
        if down and time.monotonic() - float(started) < 1.0:
            try:
                self.view.after(10, self._wait_context_menu_right_release, position, started)
                return
            except Exception:
                pass
        # One rendered frame after release guarantees ImGui has cleared any
        # transient RMB ActiveId before the modeless menu becomes visible.
        after_render = getattr(self.view, "after_render", None)
        try:
            if callable(after_render):
                after_render(self._open_context_menu_fallback, position)
            else:
                self.view.after(0, self._open_context_menu_fallback, position)
        except Exception:
            self._context_menu_pending = False

    def _canvas_left_click(self, sender=None, app_data=None, user_data=None):
        """Handle selection only for a click that belongs to the canvas.

        This callback is bound through an item handler registry, so toolbar,
        menu and sibling-window clicks never enter terminal selection logic.
        """
        if not self.winfo_exists():
            return
        if time.monotonic() < float(
                getattr(self, "_suppress_left_click_until", 0.0) or 0.0):
            return
        if self._mouse_over_context_menu():
            return
        self.focus_input(follow_tail=False)
        cell = self._cell_from_mouse()
        if cell is None:
            return
        now = time.monotonic()
        same_row = self._last_click_row == cell[0]
        self._click_count = (
            self._click_count + 1
            if same_row and now - self._last_click_time <= 0.45 else 1
        )
        self._last_click_time, self._last_click_row = now, cell[0]
        if self._click_count >= 3:
            self._select_line_at(cell)
            self._click_count = 0
            self._selection_dragging = False
        elif self._click_count == 2:
            self._select_word_at(cell)
            self._selection_dragging = False
        else:
            self._selection_anchor = cell
            self._selection_focus = cell
            self._selection_dragging = True
        self._last_paint = None

    def _mouse_click(self, sender=None, app_data=None, user_data=None):
        """Global LMB callback used only to relinquish console keyboard input.

        Check menu ownership now, but defer focus changes and dismissal so a
        menu button remains visible until its mouse-release activation.
        """
        if not self.winfo_exists():
            return
        # Capture menu ownership on mouse-down. Buttons activate on release;
        # dismissing their window between those events cancels the action.
        if self._mouse_over_context_menu():
            return
        try:
            self.view.after(0, self._deactivate_keyboard_if_pointer_outside)
        except Exception:
            pass

    def _deactivate_keyboard_if_pointer_outside(self):
        if not self.winfo_exists():
            return
        if self._mouse_over_context_menu():
            return
        # The menu is an ordinary modeless window.  This callback itself is
        # queued with view.after(0); clicks inside the menu were filtered on
        # mouse-down. Outside controls retain their physical click when this
        # overlay is dismissed.
        self._hide_context_menu()
        if self._over_terminal():
            return
        setter = getattr(self.view, "_set_console_keyboard_active", None)
        if callable(setter):
            setter(False, self)

    def _mouse_over_context_menu(self):
        """Hit-test the menu without relying on stale hidden-window geometry."""
        menu = getattr(self, "_context_menu_obj", None)
        if menu is None or not bool(getattr(menu, "is_open", False)):
            return False
        tag = getattr(menu, "tag", None)
        if tag is None:
            return False
        try:
            if not dpg.does_item_exist(tag) or not dpg.is_item_shown(tag):
                return False
            if dpg.is_item_hovered(tag):
                return True
        except Exception:
            pass
        try:
            mx, my = map(float, dpg.get_mouse_pos(local=False))
            x0, y0 = map(float, dpg.get_item_pos(tag))
            config = dpg.get_item_configuration(tag) or {}
            try:
                width, height = map(float, dpg.get_item_rect_size(tag))
            except Exception:
                width = height = 0
            if width <= 1:
                width = float(config.get("width") or 0)
            if height <= 1:
                height = float(config.get("height") or 0)
            return x0 <= mx < x0 + width and y0 <= my < y0 + height
        except Exception:
            return False

    def _over_terminal(self):
        try:
            return dpg.is_item_hovered(self.content) or dpg.is_item_hovered(self.canvas)
        except Exception:
            return False

    def _cell_from_mouse(self):
        if not self._render_rows:
            return None
        try:
            mx, my = map(float, dpg.get_mouse_pos(local=False))
            x0, y0 = map(float, dpg.get_item_rect_min(self.canvas))
        except Exception:
            return None
        row = max(0, min(len(self._render_rows) - 1, int((my - y0) // self._line_height)))
        column = max(0, int((mx - x0) // self._char_width))
        column = min(len(self._render_rows[row]), column)
        return row, column

    def _select_word_at(self, cell):
        row, column = cell
        if not (0 <= row < len(self._render_rows)):
            return
        start, end = TerminalBuffer.word_bounds(self._render_rows[row], column)
        self._selection_anchor = (row, start)
        self._selection_focus = (row, end)

    def _select_line_at(self, cell):
        row, _column = cell
        if not (0 <= row < len(self._render_rows)):
            return
        self._selection_anchor = (row, 0)
        self._selection_focus = (row, len(self._render_rows[row]))

    def _middle_click(self, sender=None, app_data=None, user_data=None):
        if self.winfo_exists() and self._over_terminal():
            self.focus_input(follow_tail=False)
            self._paste_clipboard()

    def _mouse_drag(self, sender=None, app_data=None, user_data=None):
        if not self._selection_dragging or not self.winfo_exists():
            return
        cell = self._cell_from_mouse()
        if cell is not None and cell != self._selection_focus:
            self._selection_focus = cell
            self._last_paint = None

    def _mouse_release(self, sender=None, app_data=None, user_data=None):
        if not self._selection_dragging:
            return
        self._selection_dragging = False
        cell = self._cell_from_mouse()
        if cell is not None:
            self._selection_focus = cell
        if self._selection_anchor == self._selection_focus:
            self._selection_anchor = self._selection_focus = None
        self._last_paint = None

    def _selection_bounds(self):
        if self._selection_anchor is None or self._selection_focus is None:
            return None
        a, b = self._selection_anchor, self._selection_focus
        return (a, b) if a <= b else (b, a)

    def _selected_text(self):
        bounds = self._selection_bounds()
        if bounds is None or not self._render_rows:
            return ""
        (r0, c0), (r1, c1) = bounds
        r0 = max(0, min(r0, len(self._render_rows) - 1))
        r1 = max(0, min(r1, len(self._render_rows) - 1))
        if r0 == r1:
            return self._render_rows[r0][c0:c1]
        parts = [self._render_rows[r0][c0:]]
        parts.extend(self._render_rows[row] for row in range(r0 + 1, r1))
        parts.append(self._render_rows[r1][:c1])
        return "\n".join(parts)

    def _copy_selection(self):
        text = self._selected_text()
        if text:
            _win_clipboard_text_set(text)

    def _paste_clipboard(self):
        value = _win_clipboard_text_get().replace("\r", " ").replace("\n", " ")
        if self._find_active:
            self._find_query += value
            self._find_changed()
        else:
            self.buffer.paste(value)
            self._edited()

    def _select_all(self):
        if self._context_menu_key_action("select_all"):
            return
        if not self._render_rows:
            return
        self._selection_anchor = (0, 0)
        self._selection_focus = (len(self._render_rows) - 1, len(self._render_rows[-1]))
        self._last_paint = None

    def _clear_selection(self):
        self._selection_anchor = self._selection_focus = None
        self._last_paint = None

    @staticmethod
    def _base_prompt_from_output(output):
        """Return the newest bracketed shell prompt from terminal output.

        The protected base line is the actual shell prompt that carries the
        current directory, e.g. ``[thannguyen@ohpcvn Batch-3]$``.  ANSI colour
        sequences must be stripped before matching; otherwise Clear can lose
        the prompt and leave only the user's editable draft visible.
        """
        plain = clean_output(str(output or "")).replace("\r", "\n")
        if not plain:
            return ""
        # Keep only real prompt-shaped lines.  Search all lines and choose the
        # newest one so Clear still works when a command printed text after an
        # older prompt or the PTY delivered prompt/output in separate chunks.
        prompt_re = re.compile(
            r"(?m)^\s*(\[[^\r\n\]]+\]\s*[$#>])\s*$"
        )
        matches = list(prompt_re.finditer(plain))
        if matches:
            return matches[-1].group(1).rstrip()
        return ""

    def _clear_console(self):
        raw = str(self._last_output or "")
        self._clear_base = raw
        detected_prompt = self._base_prompt_from_output(raw)
        if detected_prompt:
            self._last_known_prompt = detected_prompt
        self._clear_prompt = detected_prompt or self._last_known_prompt
        # Clear only scrollback.  Always keep the latest real bracketed shell
        # prompt (the line that displays the current folder) as the terminal
        # base line; never substitute arbitrary command text/draft for it.
        self.buffer.set_output(self._clear_prompt)
        self._clear_selection()
        self._last_paint = None
        self._find_dirty = True
        self._scroll_pending = True

    def _create_context_menu(self):
        """Create one item-scoped, modeless context surface for the terminal.

        The RMB trigger is native-preempted on Windows with a deferred release
        fallback.  The menu is neither a Win32 menu nor an ImGui popup,
        so no nested/native loop or popup stack can retain pointer activation.
        """
        menu = _ConsoleContextMenu(self)
        self._context_menu_obj = menu
        self._context_menu = menu.tag
        # Do not register this surface with WinUx's global pointer gate.  It is
        # intentionally modeless; only its own rectangle receives its clicks,
        # while an outside click remains available to the destination widget.

    def _context_menu_triggered(self, action, _context=None):
        callback = {
            "copy": self._copy_selection,
            "paste": self._paste_clipboard,
            "select_all": self._select_all,
            "find": self._open_find,
            "clear": self._clear_console,
        }.get(str(action))
        if callback is not None:
            self._menu_action(callback)

    def _prepare_context_menu_state(self):
        """Synchronize QMenu-like action state after native RMB dispatch."""
        menu = getattr(self, "_context_menu_obj", None)
        if menu is None:
            return
        has_rows = bool(self._render_rows)
        menu.setActionEnabled("copy", bool(self._selected_text()))
        menu.setActionEnabled("paste", _win_clipboard_has_text())
        menu.setActionEnabled("select_all", has_rows)
        menu.setActionEnabled("find", has_rows)
        menu.setActionEnabled("clear", bool(self._last_output or self.buffer.output or self.buffer.draft))

    def _hide_context_menu(self):
        try:
            menu = getattr(self, "_context_menu_obj", None)
            if menu is not None:
                menu.hide()
        except Exception:
            pass

    def _context_menu_key_action(self, action):
        """Route a keyboard accelerator through the visible QMenu surface.

        Returning True means a menu is open and the underlying terminal
        shortcut must not run, even if that action is currently disabled.
        """
        menu = getattr(self, "_context_menu_obj", None)
        if menu is None or not bool(getattr(menu, "is_open", False)):
            return False
        menu.trigger(action)
        return True

    def _menu_action(self, callback):
        # Hide first, then mutate terminal/clipboard state only after the menu
        # button click has finished.  The short suppression window prevents the
        # same LMB gesture from becoming a terminal selection if the modeless
        # menu overlaps the console canvas.
        self._hide_context_menu()
        self._suppress_left_click_until = time.monotonic() + 0.12
        callback()
        self._last_paint = None
        try:
            self.focus_input(follow_tail=False)
        except Exception:
            pass

    def invoke_default(self):
        menu = getattr(self, "_context_menu_obj", None)
        if menu is not None and bool(getattr(menu, "is_open", False)):
            if menu.activate_current():
                return
        if self._find_active:
            self.view.after(0, self._find_next, 1)
            return
        # WM_CHAR events are queued before Enter; consume typed characters
        # before submitting so fast typing cannot lose the final character.
        self.view.after(0, self._submit)

    def native_character(self, code):
        if not self.winfo_exists():
            return
        if 0xd800 <= code <= 0xdbff:
            self._surrogate = code
            return
        if 0xdc00 <= code <= 0xdfff and self._surrogate is not None:
            code = 0x10000 + ((self._surrogate-0xd800) << 10) + code-0xdc00
        self._surrogate = None
        if code >= 32 and code != 127:
            if self._find_active:
                self._find_query += chr(code)
                self._find_changed()
            else:
                self.buffer.type_text(chr(code))
                self._edited()

    def _edited(self):
        self._follow_tail = True
        self._scroll_pending = True
        self._last_paint = None

    def _backspace(self):
        if self._find_active:
            if self._find_query:
                self._find_query = self._find_query[:-1]
                self._find_changed()
            return
        self.buffer.backspace()
        self._edited()

    @staticmethod
    def _ctrl_down():
        return dpg.is_key_down(dpg.mvKey_LControl) or dpg.is_key_down(dpg.mvKey_RControl)

    def _left(self):
        if self._find_active:
            return
        self.buffer.move_cursor(-1, by_word=self._ctrl_down())
        self._edited()

    def _right(self):
        if self._find_active:
            return
        self.buffer.move_cursor(1, by_word=self._ctrl_down())
        self._edited()

    def _home(self):
        if self._find_active:
            return
        self.buffer.move_home()
        self._edited()

    def _end(self):
        if self._find_active:
            return
        self.buffer.move_end()
        self._edited()

    def _delete(self):
        if self._find_active:
            return
        self.buffer.delete()
        self._edited()

    def _tab(self):
        if self._find_active:
            return
        self.buffer.type_text("\t")
        self._edited()

    def _paste(self):
        if self._ctrl_down():
            if self._context_menu_key_action("paste"):
                return
            value = _win_clipboard_text_get().replace("\r", " ").replace("\n", " ")
            if self._find_active:
                self._find_query += value
                self._find_changed()
            else:
                self.buffer.paste(value)
                self._edited()

    def _control_c(self):
        if self._context_menu_key_action("copy"):
            return
        selected = self._selected_text()
        if selected:
            _win_clipboard_text_set(selected)
            return
        if self._find_active:
            return
        if dpg.is_key_down(dpg.mvKey_LShift) or dpg.is_key_down(dpg.mvKey_RShift):
            _win_clipboard_text_set(self.buffer.output + self.buffer.draft)
        else:
            self._interrupt()

    def _up_key(self):
        menu = getattr(self, "_context_menu_obj", None)
        if menu is not None and bool(getattr(menu, "is_open", False)):
            menu.move_current(-1)
        elif self._find_active:
            self._find_next(-1)
        else:
            self._recall(-1)

    def _down_key(self):
        menu = getattr(self, "_context_menu_obj", None)
        if menu is not None and bool(getattr(menu, "is_open", False)):
            menu.move_current(1)
        elif self._find_active:
            self._find_next(1)
        else:
            self._recall(1)

    def _find_shortcut(self, sender=None, app_data=None, user_data=None):
        if self._ctrl_down():
            if self._context_menu_key_action("find"):
                return
            self.view.after(0, self._open_find)

    def _find_repeat_shortcut(self, sender=None, app_data=None, user_data=None):
        direction = -1 if (dpg.is_key_down(dpg.mvKey_LShift) or dpg.is_key_down(dpg.mvKey_RShift)) else 1
        self.view.after(0, self._find_next, direction)

    def _open_find(self):
        selected = self._selected_text().replace("\r", " ").replace("\n", " ")
        if selected and len(selected) <= 120:
            self._find_query = selected
        self._find_active = True
        self._find_changed()
        self.focus_input(follow_tail=False)

    def _close_find(self):
        self._find_active = False
        self._find_matches = []
        self._find_index = -1
        self._find_dirty = True
        self._find_pending_scroll = False
        self._last_paint = None
        self.focus_input(follow_tail=False)

    def _find_changed(self):
        self._find_dirty = True
        self._find_index = -1
        self._find_pending_scroll = bool(self._find_query)
        self._last_paint = None

    def _rebuild_find_matches(self, columns):
        self._find_matches = TerminalBuffer.find_matches(self._render_rows, self._find_query) if self._find_active else []
        self._find_columns = columns
        self._find_dirty = False
        if self._find_matches:
            self._find_index = max(0, min(self._find_index if self._find_index >= 0 else 0, len(self._find_matches) - 1))
        else:
            self._find_index = -1

    def _find_next(self, direction=1):
        if not self._find_active:
            self._open_find()
            return
        if self._find_dirty and self._render_rows:
            columns = max(8, int(max(40, dpg.get_item_width(self.content) - 24) / self._char_width))
            self._rebuild_find_matches(columns)
        if not self._find_matches:
            self._last_paint = None
            return
        self._find_index = (self._find_index + (1 if direction >= 0 else -1)) % len(self._find_matches)
        self._find_pending_scroll = True
        self._last_paint = None

    def _close_from_escape(self):
        menu = getattr(self, "_context_menu_obj", None)
        if menu is not None and bool(getattr(menu, "is_open", False)):
            menu.hide()
            return
        if self._find_active:
            self._close_find()
            return
        super()._close_from_escape()

    def _recall(self, direction):
        self.buffer.recall(direction)
        self._edited()

    def _submit(self):
        command = self.buffer.begin_submit()
        if command is None:
            return
        try:
            accepted = self.command_callback(command)
        except Exception:
            self.buffer.command_result(command, False)
            raise
        if accepted is not None:
            self.buffer.command_result(command, bool(accepted))
        self._edited()

    def _interrupt(self):
        accepted = self.interrupt_callback()
        if accepted is not None:
            self.buffer.interrupt_result(bool(accepted))
        self._edited()

    def _wheel(self, sender, delta):
        if not self.winfo_exists() or not dpg.is_item_hovered(self.content):
            return
        if delta > 0:
            self._follow_tail = False

    def _refresh(self):
        if not self.winfo_exists():
            return
        try:
            self._set_output(self.output_callback())
        except Exception as exc:
            self.buffer.set_output("Console unavailable: {}".format(exc))
            if callable(self.error_callback):
                self.error_callback(str(exc))
        self.view.after(100, self._refresh)

    def _set_output(self, output):
        raw = str(output or "")
        if raw != self._last_output:
            self._last_output = raw
            current_prompt = self._base_prompt_from_output(raw)
            if current_prompt:
                self._last_known_prompt = current_prompt
            visible = raw
            if self._clear_base is not None:
                if raw.startswith(self._clear_base):
                    # Preserve exactly one protected current prompt after a
                    # visual Clear, then append only new terminal output.
                    delta = raw[len(self._clear_base):]
                    visible = (self._clear_prompt or "") + delta
                else:
                    # The transcript was rebuilt/replaced externally.  Leave
                    # clear mode cleanly rather than resurrecting stale state.
                    self._clear_base = None
                    self._clear_prompt = ""
            if self.buffer.set_output(visible):
                self._last_paint = None
                self._find_dirty = True
                self._scroll_pending = self._follow_tail

    def _paint_tick(self):
        if not self.winfo_exists():
            return
        self._paint()
        self.view.after(33, self._paint_tick)

    def _paint(self):
        renderer = getattr(self, "_renderer", None)
        if renderer is None:
            renderer = ConsoleRenderer(self, dpg, globals())
            self._renderer = renderer
        return renderer.paint()

    def handle_command(self, command, *args):
        if command == "focus":
            self.focus_input()
        elif command == "output":
            self._set_output(args[0])
        elif command == "command_result":
            self.buffer.command_result(*args)
            self._edited()
        elif command == "interrupt_result":
            self.buffer.interrupt_result(bool(args[0]))
            self._edited()

    def destroy(self):
        unregister_pointer_protected_item(getattr(self, "_context_menu", None))
        menu = getattr(self, "_context_menu_obj", None)
        if menu is not None:
            try:
                menu.delete()
            except Exception:
                pass
            self._context_menu_obj = None
        overlay = getattr(self, "_scroller_arrow_overlay", None)
        if overlay is not None:
            overlay.destroy()
        super().destroy()
        def cleanup():
            for item in (getattr(self, "_terminal_handlers", None), getattr(self, "_theme", None)):
                if item and dpg.does_item_exist(item):
                    dpg.delete_item(item)
        self.view.after(0, cleanup)

    def close(self, wait=True, timeout=1.0):
        self.destroy()
        return not self.winfo_exists()


class ConsoleDockPanel(ConsoleDialog):
    """Embedded SSH terminal surface used by the main-window dock widget.

    The terminal renderer/editor is intentionally shared with ``ConsoleDialog``
    so ANSI colours, inline editing, selection, search and context-menu
    behaviour stay identical.  Only the hosting/lifecycle and keyboard routing
    differ: this version lives in the main Dear PyGui viewport instead of a
    process-isolated floating dialog.
    """

    def __init__(self, view, parent, output_callback, command_callback,
                 interrupt_callback, error_callback=None):
        self.view = view
        self.output_callback, self.command_callback = output_callback, command_callback
        self.interrupt_callback, self.error_callback = interrupt_callback, error_callback
        self.buffer = TerminalBuffer()
        self._last_output = None
        self._follow_tail = True
        self._scroll_pending = False
        self._surrogate = None
        self._last_paint = None
        self._line_height = 17
        self._char_width = 8
        self._font = getattr(view, "terminal_font", None)
        self._selection_anchor = None
        self._selection_focus = None
        self._selection_dragging = False
        self._selection_items = []
        self._find_items = []
        self._find_match_items = []
        self._render_rows = []
        self._clear_base = None
        self._clear_prompt = ""
        self._last_known_prompt = ""
        self._find_active = False
        self._find_query = ""
        self._find_matches = []
        self._find_index = -1
        self._find_dirty = True
        self._find_columns = None
        self._find_pending_scroll = False
        self._last_click_time = 0.0
        self._last_click_row = None
        self._click_count = 0
        self._context_menu_pending = False
        self._suppress_left_click_until = 0.0
        self._destroyed = False
        self.preferred_size = (760, 220)
        self.shortcuts = {}

        self._theme = terminal_theme()
        self.tag = self.content = dpg.add_child_window(
            parent=parent, width=-1, height=-1, border=True,
            no_scrollbar=False, no_scroll_with_mouse=False,
        )
        dpg.bind_item_theme(self.content, self._theme)
        self._scroller_arrow_overlay = DpgScrollerArrowOverlay(
            dpg, self.content, f"{self.tag}_scroller", vertical=True, horizontal=False)
        with dpg.drawlist(parent=self.content, width=600, height=20) as self.canvas:
            self._line_items = []
            self._current_line_fill = dpg.draw_rectangle(
                (0, 0), (0, 0), color=CURRENT_LINE, fill=CURRENT_LINE)
            self._caret = dpg.draw_rectangle(
                (0, 0), (7, 2), color=COMMAND, fill=COMMAND)

        self._create_context_menu()
        self.output = self.input = self.canvas

        with dpg.handler_registry() as self._terminal_handlers:
            for key, callback in (
                    (dpg.mvKey_Back, self._backspace),
                    (dpg.mvKey_V, self._paste),
                    (dpg.mvKey_Tab, self._tab),
                    (dpg.mvKey_Left, self._left),
                    (dpg.mvKey_Right, self._right),
                    (dpg.mvKey_Up, self._up_key),
                    (dpg.mvKey_Down, self._down_key),
                    (dpg.mvKey_Home, self._home),
                    (dpg.mvKey_End, self._end),
                    (dpg.mvKey_Delete, self._delete),
            ):
                dpg.add_key_press_handler(
                    key=key, callback=self._dock_key_callback,
                    user_data=callback)
            dpg.add_key_press_handler(
                key=dpg.mvKey_Return, callback=self._dock_return_callback)
            dpg.add_key_press_handler(
                key=dpg.mvKey_Escape, callback=self._dock_escape_callback)
            dpg.add_key_press_handler(
                key=dpg.mvKey_C, callback=self._dock_ctrl_c_callback)
            dpg.add_key_press_handler(
                key=dpg.mvKey_A, callback=self._dock_ctrl_a_callback)
            dpg.add_key_press_handler(
                key=dpg.mvKey_F, callback=self._dock_find_callback)
            dpg.add_key_press_handler(
                key=dpg.mvKey_F3, callback=self._dock_find_repeat_callback)
            dpg.add_mouse_wheel_handler(callback=self._wheel)
            dpg.add_mouse_drag_handler(
                button=dpg.mvMouseButton_Left, threshold=1.0,
                callback=self._mouse_drag)
            dpg.add_mouse_release_handler(
                button=dpg.mvMouseButton_Left, callback=self._mouse_release)
            dpg.add_mouse_release_handler(
                button=dpg.mvMouseButton_Right, callback=self._right_release_fallback)
            dpg.add_mouse_click_handler(
                button=dpg.mvMouseButton_Left, callback=self._mouse_click)

        self._refresh()
        self.view.after(0, self._paint_tick)

    def winfo_exists(self):
        return (not self._destroyed) and dpg.does_item_exist(self.tag)

    def keyboard_active(self):
        # This predicate is also queried from the native WM_CHAR hook.  Keep it
        # free of Dear PyGui calls so the WNDPROC never re-enters the item
        # registry while GLFW/Dear ImGui is dispatching a Windows message.
        return bool(
            not self._destroyed
            and getattr(self.view, "_console_keyboard_panel", None) is self
            and getattr(self.view, "_console_dock_visible", False)
        )

    def focus_input(self, follow_tail=True):
        if not self.winfo_exists():
            return
        setter = getattr(self.view, "_set_console_keyboard_active", None)
        if callable(setter):
            setter(True, self)
        if follow_tail:
            self._follow_tail = True
            self._scroll_pending = True
        try:
            dpg.focus_item(self.tag)
        except Exception:
            pass

    def _dock_key_callback(self, sender=None, app_data=None, user_data=None):
        if self.keyboard_active() and callable(user_data):
            self.view.after(0, user_data)

    def _dock_return_callback(self, sender=None, app_data=None, user_data=None):
        if self.keyboard_active():
            self.invoke_default()

    def _dock_escape_callback(self, sender=None, app_data=None, user_data=None):
        if not self.keyboard_active():
            return
        menu = getattr(self, "_context_menu_obj", None)
        if menu is not None and bool(getattr(menu, "is_open", False)):
            self.view.after(0, menu.hide)
        elif self._find_active:
            self.view.after(0, self._close_find)

    def _dock_ctrl_c_callback(self, sender=None, app_data=None, user_data=None):
        if self.keyboard_active() and self._ctrl_down():
            self.view.after(0, self._control_c)

    def _dock_ctrl_a_callback(self, sender=None, app_data=None, user_data=None):
        if self.keyboard_active() and self._ctrl_down():
            self.view.after(0, self._select_all)

    def _dock_find_callback(self, sender=None, app_data=None, user_data=None):
        if self.keyboard_active() and self._ctrl_down():
            self.view.after(0, self._open_find)

    def _dock_find_repeat_callback(self, sender=None, app_data=None, user_data=None):
        if not self.keyboard_active():
            return
        direction = -1 if (
            dpg.is_key_down(dpg.mvKey_LShift)
            or dpg.is_key_down(dpg.mvKey_RShift)) else 1
        self.view.after(0, self._find_next, direction)

    def _close_from_escape(self):
        menu = getattr(self, "_context_menu_obj", None)
        if menu is not None and bool(getattr(menu, "is_open", False)):
            menu.hide()
        elif self._find_active:
            self._close_find()

    def destroy(self):
        if self._destroyed:
            return
        self._destroyed = True
        setter = getattr(self.view, "_set_console_keyboard_active", None)
        if callable(setter):
            setter(False, self)
        unregister_pointer_protected_item(getattr(self, "_context_menu", None))
        menu = getattr(self, "_context_menu_obj", None)
        if menu is not None:
            try:
                menu.delete()
            except Exception:
                pass
            self._context_menu_obj = None
        overlay = getattr(self, "_scroller_arrow_overlay", None)
        if overlay is not None:
            overlay.destroy()
        for item in (
                getattr(self, "_terminal_handlers", None),
                getattr(self, "tag", None),
                getattr(self, "_theme", None)):
            try:
                if item and dpg.does_item_exist(item):
                    dpg.delete_item(item)
            except Exception:
                pass

    def close(self, wait=True, timeout=1.0):
        self.destroy()
        return not self.winfo_exists()
