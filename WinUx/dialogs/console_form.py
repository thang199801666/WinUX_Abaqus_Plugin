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
from ..components.interaction_gate import register_pointer_protected_item, unregister_pointer_protected_item
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


class _NativeConsoleContextMenu:
    """Win32 popup menu used by the Windows terminal.

    TrackPopupMenuEx owns its own native modal message loop and returns the
    chosen command id.  No Dear PyGui item is created and no DPG callback is
    invoked while the popup is active, which removes the crash-prone re-entry
    path seen with both retained QMenu rows and DPG button popups.
    """

    _COMMANDS = ((1001, "copy", "Copy"), (1002, "paste", "Paste"),
                 (1003, "select_all", "Select All"), (1004, "find", "Find"),
                 (1005, "clear", "Clear"))

    def __init__(self, owner):
        self.owner = owner
        self.tag = None
        self._enabled = {action: True for _cid, action, _label in self._COMMANDS}
        self.is_open = False

    def setActionEnabled(self, action, enabled):
        self._enabled[str(action)] = bool(enabled)
        return True

    def popup(self, position=None, *, context=None):
        if os.name != "nt":
            return None
        user32 = ctypes.windll.user32
        user32.CreatePopupMenu.restype = wintypes.HMENU
        user32.AppendMenuW.argtypes = [wintypes.HMENU, wintypes.UINT, ctypes.c_size_t, wintypes.LPCWSTR]
        user32.AppendMenuW.restype = wintypes.BOOL
        user32.TrackPopupMenuEx.argtypes = [wintypes.HMENU, wintypes.UINT, ctypes.c_int, ctypes.c_int, wintypes.HWND, ctypes.c_void_p]
        user32.TrackPopupMenuEx.restype = wintypes.UINT
        user32.DestroyMenu.argtypes = [wintypes.HMENU]
        user32.DestroyMenu.restype = wintypes.BOOL
        user32.GetCursorPos.argtypes = [ctypes.POINTER(wintypes.POINT)]
        user32.GetCursorPos.restype = wintypes.BOOL
        user32.GetForegroundWindow.restype = wintypes.HWND
        user32.SetForegroundWindow.argtypes = [wintypes.HWND]
        user32.SetForegroundWindow.restype = wintypes.BOOL
        user32.PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
        user32.PostMessageW.restype = wintypes.BOOL

        menu = user32.CreatePopupMenu()
        if not menu:
            return None
        MF_STRING, MF_GRAYED, MF_SEPARATOR = 0x0000, 0x0001, 0x0800
        TPM_RIGHTBUTTON, TPM_RETURNCMD, TPM_NONOTIFY = 0x0002, 0x0100, 0x0080
        WM_NULL = 0x0000
        try:
            for index, (cid, action, label) in enumerate(self._COMMANDS):
                if action == "clear":
                    user32.AppendMenuW(menu, MF_SEPARATOR, 0, None)
                flags = MF_STRING | (0 if self._enabled.get(action, True) else MF_GRAYED)
                user32.AppendMenuW(menu, flags, cid, label)

            hwnd = 0
            finder = getattr(self.owner.view, "_find_main_viewport_hwnd", None)
            if callable(finder):
                try:
                    hwnd = int(finder() or 0)
                except Exception:
                    hwnd = 0
            if not hwnd:
                try:
                    hwnd = int(user32.GetForegroundWindow() or 0)
                except Exception:
                    hwnd = 0
            point = wintypes.POINT()
            if not user32.GetCursorPos(ctypes.byref(point)):
                return None
            if hwnd:
                user32.SetForegroundWindow(wintypes.HWND(hwnd))
            self.is_open = True
            command = int(user32.TrackPopupMenuEx(
                menu, TPM_RIGHTBUTTON | TPM_RETURNCMD | TPM_NONOTIFY,
                int(point.x), int(point.y), wintypes.HWND(hwnd or 0), None) or 0)
            if hwnd:
                user32.PostMessageW(wintypes.HWND(hwnd), WM_NULL, 0, 0)
            for cid, action, _label in self._COMMANDS:
                if command == cid:
                    return action
            return None
        finally:
            self.is_open = False
            user32.DestroyMenu(menu)

    def hide(self):
        return True

    def delete(self):
        return None

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
    """Small DPG-native context menu dedicated to the terminal.

    The generic retained QMenu uses child-window row hit handlers.  On the
    Windows/Dear PyGui combination used by WinUx those rows can hover normally
    while their click handlers are never delivered.  The console menu uses
    real ``mvButton`` rows instead, so mouse actions are handled by Dear ImGui
    directly and do not depend on child-window click handlers.
    """

    WIDTH = 170
    ROW_HEIGHT = 24

    def __init__(self, owner):
        self.owner = owner
        self.tag = dpg.generate_uuid()
        self._buttons = {}
        self._enabled = {}
        with dpg.window(
                tag=self.tag, show=False, width=self.WIDTH, height=136,
                no_title_bar=True, no_resize=True, no_move=True,
                no_saved_settings=True, no_scrollbar=True,
                no_scroll_with_mouse=True):
            for action, label in (("copy", "Copy"), ("paste", "Paste"),
                                  ("select_all", "Select All"),
                                  ("find", "Find")):
                self._add_button(action, label)
            dpg.add_separator()
            self._add_button("clear", "Clear")

        with dpg.theme() as self._window_theme:
            with dpg.theme_component(dpg.mvWindowAppItem):
                dpg.add_theme_color(dpg.mvThemeCol_WindowBg, QtFusionPalette.WINDOW)
                dpg.add_theme_color(dpg.mvThemeCol_Border, QtFusionPalette.BORDER)
                dpg.add_theme_style(dpg.mvStyleVar_WindowBorderSize, 1)
                dpg.add_theme_style(dpg.mvStyleVar_WindowRounding, 0)
                dpg.add_theme_style(dpg.mvStyleVar_WindowPadding, 3, 3)
                dpg.add_theme_style(dpg.mvStyleVar_ItemSpacing, 0, 1)
        dpg.bind_item_theme(self.tag, self._window_theme)

    def _add_button(self, action, label):
        tag = dpg.add_button(
            label=label, width=self.WIDTH - 8, height=self.ROW_HEIGHT,
            callback=self._clicked, user_data=action)
        self._buttons[action] = tag
        self._enabled[action] = True
        try:
            dpg.bind_item_theme(tag, button_theme(dpg, role="flat"))
        except Exception:
            pass

    def _clicked(self, sender=None, app_data=None, user_data=None):
        action = str(user_data or "")
        if not self._enabled.get(action, True):
            return
        # Defer the terminal operation one UI turn.  This lets Dear ImGui finish
        # the button activation before clipboard/selection/output state mutates.
        try:
            self.owner.view.after(0, self.owner._context_menu_triggered, action, self.owner)
        except Exception:
            self.owner._context_menu_triggered(action, self.owner)

    def setActionEnabled(self, action, enabled):
        action = str(action)
        enabled = bool(enabled)
        self._enabled[action] = enabled
        button = self._buttons.get(action)
        if button is None:
            return False
        try:
            dpg.configure_item(button, enabled=enabled)
            dpg.bind_item_theme(
                button, button_theme(dpg, role="flat", disabled=not enabled))
        except Exception:
            pass
        return True

    def popup(self, position=None, *, context=None):
        if position is not None:
            try:
                dpg.set_item_pos(self.tag, tuple(map(int, position)))
            except Exception:
                pass
        try:
            dpg.configure_item(self.tag, show=True)
            dpg.focus_item(self.tag)
            return True
        except Exception:
            return False

    def hide(self):
        try:
            dpg.configure_item(self.tag, show=False)
            return True
        except Exception:
            return False

    def delete(self):
        try:
            if dpg.does_item_exist(self.tag):
                dpg.delete_item(self.tag)
        except Exception:
            pass
        try:
            if dpg.does_item_exist(self._window_theme):
                dpg.delete_item(self._window_theme)
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
            dpg.add_mouse_click_handler(button=dpg.mvMouseButton_Right, callback=self._right_click)
            dpg.add_mouse_click_handler(button=dpg.mvMouseButton_Middle, callback=self._middle_click)
            # Dear PyGui 2.3.1 can reject mvClickedHandler when an
            # item_handler_registry is bound to mvChildWindow during floating
            # dialog prewarm (Error 1000: handler is inapplicable).  Mouse
            # handlers in a normal handler_registry are global and work for
            # every item type, so filter the click by hover instead of binding
            # a click registry directly to the child window.
            dpg.add_mouse_click_handler(button=dpg.mvMouseButton_Left, callback=self._mouse_click)
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

    def _mouse_click(self, sender=None, app_data=None, user_data=None):
        if not self.winfo_exists():
            return
        if time.monotonic() < float(getattr(self, "_suppress_left_click_until", 0.0) or 0.0):
            return
        # The terminal uses a global left-click handler.  When a QMenu is open,
        # that handler is dispatched for clicks on the menu as well.  Do not
        # hide the popup before QMenu's own row-click handler has a chance to
        # emit the selected action; otherwise rows highlight on hover but every
        # menu command appears dead.
        if self._mouse_over_context_menu():
            return
        if self._over_terminal():
            self.focus_input(follow_tail=False)
            self._hide_context_menu()
            cell = self._cell_from_mouse()
            if cell is None:
                return
            now = time.monotonic()
            same_row = self._last_click_row == cell[0]
            self._click_count = self._click_count + 1 if same_row and now - self._last_click_time <= 0.45 else 1
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

    def _mouse_over_context_menu(self):
        """Return True while the pointer is inside the visible console menu."""
        menu = getattr(self, "_context_menu_obj", None)
        if bool(getattr(menu, "is_open", False)):
            return True
        tag = getattr(menu, "tag", None)
        if tag is None:
            return False
        try:
            if not dpg.does_item_exist(tag) or not dpg.is_item_shown(tag):
                return False
            mx, my = map(float, dpg.get_mouse_pos(local=False))
            x0, y0 = map(float, dpg.get_item_rect_min(tag))
            width, height = map(float, dpg.get_item_rect_size(tag))
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
        """Create one shared QMenu-style terminal context menu.

        ConsoleDialog and the embedded ConsoleDockPanel used to maintain two
        hand-written popup windows.  Reuse the retained QMenu renderer so row
        height, separators, keyboard navigation and disabled states match the
        rest of WinUx.
        """
        menu = _NativeConsoleContextMenu(self) if os.name == "nt" else _ConsoleContextMenu(self)
        self._context_menu_obj = menu
        self._context_menu = menu.tag
        if self._context_menu is not None:
            register_pointer_protected_item(self._context_menu)

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

    def _right_click(self, sender=None, app_data=None, user_data=None):
        """Queue RMB handling until Dear PyGui has completed input/render dispatch.

        This callback is registered in a global handler registry.  Calling any
        DPG item/query API from here can re-enter the native Dear ImGui/GLFW
        dispatch path on Windows.  In particular, hover queries and popup
        creation from this callback have caused process-level crashes that
        Python ``try/except`` cannot catch.  Keep this callback DPG-free and
        defer the entire hit-test/menu operation until a future rendered frame.
        """
        if self._context_menu_pending:
            return
        self._context_menu_pending = True
        try:
            self.view.after_render(self._show_context_menu_after_render)
        except Exception:
            self._context_menu_pending = False

    def _show_context_menu_after_render(self):
        self._context_menu_pending = False
        if not self.winfo_exists():
            return
        # All DPG queries are intentionally delayed until this future frame.
        # If the RMB was outside the terminal, do nothing.
        if not self._over_terminal():
            return
        try:
            mx, my = map(int, dpg.get_mouse_pos(local=False))
            menu = getattr(self, "_context_menu_obj", None)
            if menu is None:
                return
            self.focus_input(follow_tail=False)
            menu.setActionEnabled("copy", bool(self._selected_text()))
            # Do not touch the OS/DPG clipboard while opening the menu.  Paste
            # remains available and validates/reads the clipboard only if the
            # user actually chooses Paste, outside the RMB dispatch path.
            menu.setActionEnabled("paste", True)
            chosen = menu.popup((mx, my), context=self)
            if chosen:
                # The mouse-up that selected a native menu row can be observed
                # by Dear PyGui after TrackPopupMenuEx returns.  Ignore left
                # clicks for a very short interval so it cannot alter terminal
                # selection or focus before the action executes.
                self._suppress_left_click_until = time.monotonic() + 0.20
                self.view.after(0, self._context_menu_triggered, chosen, self)
        except Exception:
            try:
                self._hide_context_menu()
            except Exception:
                pass

    def _hide_context_menu(self):
        try:
            menu = getattr(self, "_context_menu_obj", None)
            if menu is not None:
                menu.hide()
        except Exception:
            pass

    def _menu_action(self, callback):
        # A native Windows menu is already destroyed before this runs.  Do not
        # touch DPG popup state here; execute only the terminal action.  This
        # keeps menu selection out of Dear ImGui's callback stack.
        if os.name != "nt":
            self._hide_context_menu()
        callback()
        self._last_paint = None

    def invoke_default(self):
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
            value = _win_clipboard_text_get().replace("\r", " ").replace("\n", " ")
            if self._find_active:
                self._find_query += value
                self._find_changed()
            else:
                self.buffer.paste(value)
                self._edited()

    def _control_c(self):
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
        if self._find_active:
            self._find_next(-1)
        else:
            self._recall(-1)

    def _down_key(self):
        if self._find_active:
            self._find_next(1)
        else:
            self._recall(1)

    def _find_shortcut(self, sender=None, app_data=None, user_data=None):
        if self._ctrl_down():
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
            dpg.add_mouse_click_handler(
                button=dpg.mvMouseButton_Right, callback=self._right_click)
            dpg.add_mouse_click_handler(
                button=dpg.mvMouseButton_Middle, callback=self._middle_click)
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

    def _mouse_click(self, sender=None, app_data=None, user_data=None):
        if not self.winfo_exists():
            return
        if time.monotonic() < float(getattr(self, "_suppress_left_click_until", 0.0) or 0.0):
            return
        if self._over_terminal():
            return super()._mouse_click(sender, app_data, user_data)
        setter = getattr(self.view, "_set_console_keyboard_active", None)
        if callable(setter):
            setter(False, self)

    def _dock_key_callback(self, sender=None, app_data=None, user_data=None):
        if self.keyboard_active() and callable(user_data):
            self.view.after(0, user_data)

    def _dock_return_callback(self, sender=None, app_data=None, user_data=None):
        if self.keyboard_active():
            self.invoke_default()

    def _dock_escape_callback(self, sender=None, app_data=None, user_data=None):
        if not self.keyboard_active():
            return
        if self._find_active:
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
        if self._find_active:
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
