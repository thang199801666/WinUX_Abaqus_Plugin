"""CMD-style SSH console with one protected transcript and inline command line."""
from __future__ import annotations

import ctypes
import os
import re
import time
from ctypes import wintypes

from DearUIQt.backends import dpg

from DearUIQt.dialogs.qt_dialog import QtDialog
from DearUIQt.widgets import QApplication, QCanvas, QFrame, QModelessMenu
from ..ui.components.console_renderer import ConsoleRenderer
from ..runtime.terminal_buffer import TerminalBuffer, clean_output
from DearUIQt.input_gate import unregister_pointer_protected_item
from DearUIQt.backends.dearpygui import DpgScrollerArrowOverlay, dpg_window_rect
from DearUIQt.gui import QPainter, QtFusionPalette, QCursor, QKeyboard, QClipboard
from DearUIQt.themes import (
    ThemeTarget, ThemeColor, ThemeStyle, QTheme, theme_component, theme_spec, with_scrollbar,
)
from DearUIQt.core import Qt, QObject, QEvent, QItemInputBinding, QGlobalInputBinding
from DearUIQt.core import QTimer

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
        return QClipboard(backend=dpg).text()
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
        return bool(QClipboard(backend=dpg).text())
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
        return bool(QClipboard(backend=dpg).setText(value))
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


class _ConsoleContextMenu(QModelessMenu):
    """Terminal-specialized modeless menu built on DearUIQt.

    The modeless window/row/theme/geometry lifecycle now belongs to DearUIQt.
    WinUx only supplies terminal actions and defers their callbacks until the
    physical menu click has completed.
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
        super().__init__(
            self.ACTIONS, separators_after=self.SEPARATORS_AFTER,
            width=self.WIDTH, row_height=self.ROW_HEIGHT,
            separator_height=self.SEPARATOR_HEIGHT, backend=dpg,
            after=owner.view.after, parent=owner,
        )
        self.triggered.connect(self._dispatch_action)
        # Pointer ownership stays item-scoped to the terminal canvas but the
        # DearPyGui registry itself is now owned by DearUIQt.
        self._canvas_input = QItemInputBinding(
            owner._canvas_widget, backend=dpg, parent=self)
        self._canvas_input.onClick(Qt.LeftButton, owner._canvas_left_click)
        self._canvas_input.onClick(Qt.MiddleButton, owner._middle_click)
        self._canvas_input.onClick(Qt.RightButton, owner._canvas_right_click)
        self._canvas_input.activate()

    def _dispatch_action(self, action, _context=None):
        try:
            self.owner.view.after(
                0, self.owner._context_menu_triggered, str(action), self.owner)
        except Exception:
            self.owner._context_menu_triggered(str(action), self.owner)

    # Compatibility hook retained for focused action-routing tests and older
    # integrations that invoked the row callback directly.
    def _clicked(self, sender=None, app_data=None, user_data=None):
        action = str(user_data or "")
        if not self._enabled.get(action, True):
            return False
        self._set_current(action)
        dispatcher = getattr(self, "_dispatch_action", None)
        if callable(dispatcher):
            dispatcher(action, self.owner)
        else:
            # Compatibility for detached action routers that invoke this
            # method without constructing the full QModelessMenu object.
            self.owner.view.after(
                0, self.owner._context_menu_triggered, action, self.owner)
        return True

def terminal_theme(*, parent=None, backend=None):
    base = with_scrollbar(theme_component(
        ThemeTarget.ALL,
        colors={
            ThemeColor.WINDOW_BACKGROUND: BLACK,
            ThemeColor.CHILD_BACKGROUND: BLACK,
            ThemeColor.TEXT: TEXT,
            ThemeColor.BORDER: QtFusionPalette.BORDER_DARK,
        },
        styles={
            ThemeStyle.WINDOW_PADDING: (4, 4),
            ThemeStyle.ITEM_SPACING: (0, 0),
            ThemeStyle.WINDOW_BORDER_SIZE: 0,
            ThemeStyle.CHILD_BORDER_SIZE: 0,
        },
    ))
    window = theme_component(
        ThemeTarget.WINDOW,
        styles={ThemeStyle.WINDOW_PADDING: (0, 0)},
    )
    return QTheme(theme_spec(base, window), backend=backend, parent=parent)


class ConsoleDialog(QtDialog):
    REUSABLE_HOST = True
    clean_output = staticmethod(clean_output)
    updated_history = TerminalBuffer.updated_history

    def __init__(self, view, output_callback, command_callback, interrupt_callback, error_callback=None, *, footer=False, completion_callback=None, completion_list_callback=None):
        self.output_callback, self.command_callback = output_callback, command_callback
        self.interrupt_callback, self.error_callback = interrupt_callback, error_callback
        self.completion_callback = completion_callback
        self.completion_list_callback = completion_list_callback
        self.buffer = TerminalBuffer()
        self._last_output = None
        self._follow_tail = True
        self._scroll_pending = False
        self._cursor_scroll_pending = False
        self._manual_scroll_until = 0.0
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
        self._completion_request_serial = 0
        self._completion_pending = None
        self._completion_state = None
        self._completion_applying = False
        self._completion_queued_directions = []
        super().__init__(view, "SSH Console", 760, 440, modal=False, footer=footer)
        self.preferred_size = (760, 440)
        self._theme = terminal_theme(parent=self, backend=dpg)
        self.setTheme(self._theme)
        self._content_surface = self.contentWidget()
        self._content_surface.setTheme(self._theme)
        self._scroller_arrow_overlay = DpgScrollerArrowOverlay(
            dpg, self.content, f"{self.tag}_scroller", vertical=True, horizontal=False)
        self._canvas_widget = QCanvas(
            width=600, height=20, parent=self.content, backend=dpg)
        self.canvas = self._canvas_widget.tag
        # Keep terminal rows under our own pixel control instead of relying
        # on Dear PyGui's multiline draw_text layout. That makes the caret
        # track the active row exactly and avoids the visible vertical drift
        # seen on some Windows builds when the console is resized.
        self._line_items = []
        painter = QPainter(self._canvas_widget)
        self._current_line_fill = painter.drawRect(
            (0, 0), (0, 0), color=CURRENT_LINE, fill=CURRENT_LINE)
        self._caret = painter.drawRect(
            (0, 0), (7, 2), color=COMMAND, fill=COMMAND)
        self._create_context_menu()
        # Compatibility: one terminal owns both output and editable command.
        self.output = self.input = self.canvas
        self.setShortcut(Qt.Key_Up, lambda: self.view.after(0, self._up_key))
        self.setShortcut(Qt.Key_Down, lambda: self.view.after(0, self._down_key))
        self.setShortcut(Qt.Key_Home, lambda: self.view.after(0, self._home))
        self.setShortcut(Qt.Key_End, lambda: self.view.after(0, self._end))
        self.setShortcut(Qt.Key_Delete, lambda: self.view.after(0, self._delete))
        self.setShortcut(Qt.Key_Delete, lambda: self.view.after(0, self._delete_word_right), ctrl=True)
        self.setShortcut(Qt.Key_Home, lambda: self.view.after(0, self._delete_to_start), ctrl=True)
        self.setShortcut(Qt.Key_End, lambda: self.view.after(0, self._delete_to_end), ctrl=True)
        self.setShortcut(Qt.Key_C, lambda: self.view.after(0, self._control_c), ctrl=True)
        # SSH terminals conventionally use readline/emacs bindings. Keep the
        # existing CMD-style Home/End/F8 behavior, but make the standard Ctrl
        # chords available as well so the embedded console feels like a real
        # shell instead of a GUI textbox. Ctrl+Shift+A retains Select All.
        self.setShortcut(Qt.Key_A, lambda: self.view.after(0, self._control_a), ctrl=True)
        self.setShortcut(Qt.Key_E, lambda: self.view.after(0, self._line_end), ctrl=True)
        self.setShortcut(Qt.Key_B, lambda: self.view.after(0, self._line_left), ctrl=True)
        self.setShortcut(Qt.Key_P, lambda: self.view.after(0, self._up_key), ctrl=True)
        self.setShortcut(Qt.Key_N, lambda: self.view.after(0, self._down_key), ctrl=True)
        self.setShortcut(Qt.Key_R, lambda: self.view.after(0, self._history_contains), ctrl=True)
        self.setShortcut(Qt.Key_W, lambda: self.view.after(0, self._kill_word_left), ctrl=True)
        self.setShortcut(Qt.Key_U, lambda: self.view.after(0, self._kill_to_start), ctrl=True)
        self.setShortcut(Qt.Key_K, lambda: self.view.after(0, self._kill_to_end), ctrl=True)
        self.setShortcut(Qt.Key_Y, lambda: self.view.after(0, self._yank), ctrl=True)
        self.setShortcut(Qt.Key_D, lambda: self.view.after(0, self._line_delete), ctrl=True)
        self.setShortcut(Qt.Key_H, lambda: self.view.after(0, self._line_backspace), ctrl=True)
        self.setShortcut(Qt.Key_L, lambda: self.view.after(0, self._clear_console), ctrl=True)
        # DOSKEY template keys: F1 copies one character from the previous
        # command, F3 copies its remainder from the current column and F5
        # recalls the complete template. F8 remains prefix-history search.
        self.setShortcut(Qt.Key_F1, lambda: self.view.after(0, self._template_char))
        self.setShortcut(Qt.Key_F5, lambda: self.view.after(0, self._template_full))
        self.setShortcut(Qt.Key_F8, lambda: self.view.after(0, self._history_prefix))
        self.setShortcut(Qt.Key_Insert, lambda: self.view.after(0, self._toggle_overwrite))
        self._terminal_handlers = QGlobalInputBinding(
            backend=dpg, parent=self, after=self.view.after)
        for key, callback in (
                (Qt.Key_Backspace, self._backspace), (Qt.Key_V, self._paste),
                (Qt.Key_Tab, self._tab), (Qt.Key_Left, self._left),
                (Qt.Key_Right, self._right)):
            self._terminal_handlers.onKeyPress(
                key, lambda s, a, u: self._queue_key(u), user_data=callback)
        self._terminal_handlers.onKeyPress(Qt.Key_F, self._find_shortcut)
        self._terminal_handlers.onKeyPress(Qt.Key_F3, self._f3_shortcut)
        self._terminal_handlers.onMouseWheel(self._wheel)
        self._terminal_handlers.onMouseDrag(
            Qt.LeftButton, self._mouse_drag, threshold=1.0)
        self._terminal_handlers.onMouseRelease(Qt.LeftButton, self._mouse_release)
        self._terminal_handlers.onMouseRelease(
            Qt.RightButton, self._right_release_fallback)
        # Keep one lightweight global LMB observer to route the console's
        # WM_CHAR ownership, including clicks in blank terminal space. All
        # terminal click/selection work itself is item-scoped to the canvas.
        self._terminal_handlers.onMouseClick(Qt.LeftButton, self._mouse_click)
        self._terminal_handlers.activate()
        self.focus_input()
        self._refresh()
        self._paint_tick()
        self._refresh_timer = self.create_timer(100, self._refresh)
        self._paint_timer = self.create_timer(33, self._paint_tick)

    def focus_input(self, follow_tail=True, focus_window=True):
        if self.winfo_exists():
            self._caret_blink_started = time.monotonic()
            if follow_tail:
                self._follow_tail = True
                self._scroll_pending = True
                self._manual_scroll_until = 0.0
            # Avoid re-focusing an already-active window. Repeated focus_item()
            # calls can reset ImGui navigation/scroll state, especially while
            # the terminal child is being wheel-scrolled.
            if focus_window and not self.isActiveWindow():
                self.activateWindow()

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
                position = QCursor.pos(backend=dpg).toTuple()
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
        surface = getattr(self, "_content_surface", None)
        if surface is not None:
            try:
                return surface.containsGlobalPoint(position, clipped=True)
            except Exception:
                pass
        # Transitional compatibility for detached/legacy hosts that only keep
        # the native content id. New runtime surfaces always take the QWidget
        # path above.
        try:
            left, top, right, bottom = dpg_window_rect(dpg, self.content, clip=True)
            x, y = map(float, position)
            return float(left) <= x < float(right) and float(top) <= y < float(bottom)
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
            position = QCursor.pos(backend=dpg).toTuple()
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
                position = QCursor.pos(backend=dpg).toTuple()
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
            position = QCursor.pos(backend=dpg).toTuple()
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
            down = QCursor.isButtonDown(Qt.RightButton, backend=dpg)
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
        cell = self._cell_from_mouse()
        # The physical click already focuses its window. Calling focus_item()
        # again changes ImGui navigation/scroll state before hit-testing.
        self.focus_input(follow_tail=False, focus_window=False)
        self._scroll_pending = False
        self._cursor_scroll_pending = False
        self._follow_tail = False
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
        """Capture keyboard ownership from the physical LMB event.

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
            try:
                position = tuple(map(float, QCursor.pos(backend=dpg).toTuple()))
            except Exception:
                position = tuple(map(float, dpg.get_mouse_pos(local=False)))
            inside = self._terminal_rect_contains(position)
            if inside and self._over_terminal():
                # Also activate clicks in blank space below a short transcript.
                self.focus_input(follow_tail=False, focus_window=False)
            self.view.after(0, self._deactivate_keyboard_if_pointer_outside, inside)
        except Exception:
            pass

    def _deactivate_keyboard_if_pointer_outside(self, inside=None):
        if not self.winfo_exists():
            return
        if self._mouse_over_context_menu():
            return
        # The menu is an ordinary modeless window.  This callback itself is
        # queued with view.after(0); clicks inside the menu were filtered on
        # mouse-down. Outside controls retain their physical click when this
        # overlay is dismissed.
        self._hide_context_menu()
        # Use the mouse-down decision, not wherever the pointer moved while
        # this callback waited in the UI queue.
        if inside is True or (inside is None and self._over_terminal()):
            return
        setter = getattr(self.view, "_set_console_keyboard_active", None)
        if callable(setter):
            setter(False, self)

    def _mouse_over_context_menu(self):
        """Hit-test the menu without relying on stale hidden-window geometry."""
        menu = getattr(self, "_context_menu_obj", None)
        if menu is None or not bool(getattr(menu, "is_open", False)):
            return False
        contains = getattr(menu, "containsGlobalPoint", None)
        if callable(contains):
            try:
                return bool(contains(QCursor.pos(backend=dpg)))
            except Exception:
                pass
        # Transitional compatibility for old menu objects that expose only a
        # native retained tag. QModelessMenu never takes this path.
        tag = getattr(menu, "tag", None)
        try:
            if tag and dpg.is_item_hovered(tag):
                return True
            mx, my = map(float, dpg.get_mouse_pos(local=False))
            x, y = map(float, dpg.get_item_pos(tag))
            width, height = dpg.get_item_rect_size(tag)
            if not width or not height:
                config = dpg.get_item_configuration(tag) or {}
                width = width or config.get("width", 0)
                height = height or config.get("height", 0)
            return x <= mx < x + float(width) and y <= my < y + float(height)
        except Exception:
            return False

    def _over_terminal(self):
        try:
            return self._content_surface.underMouse() or self._canvas_widget.underMouse()
        except Exception:
            return False

    def _cell_from_mouse(self):
        if not self._render_rows:
            return None
        try:
            mx, my = map(float, QCursor.pos(backend=dpg).toTuple())
            origin = self._canvas_widget.globalPos()
            x0, y0 = float(origin.x()), float(origin.y())
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
            columns = getattr(self, "_render_columns", None)
            if columns and cell is not None and not self._find_active:
                self.buffer.move_cursor_to_cell(columns, *cell)
            self._selection_anchor = self._selection_focus = None
        self._caret_blink_started = time.monotonic()
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
        keyboard_active = getattr(self, "keyboard_active", None)
        if callable(keyboard_active) and not keyboard_active():
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
        if not getattr(self, "_completion_applying", False):
            # Any ordinary edit invalidates a pending/cycling completion. A
            # late SSH result is ignored by its serial + draft/cursor guard.
            self._completion_request_serial = getattr(
                self, "_completion_request_serial", 0) + 1
            self._completion_pending = None
            self._completion_state = None
            self._completion_queued_directions = []
        self._caret_blink_started = time.monotonic()
        self._selection_dragging = False
        self._clear_selection()
        # Editing owns the viewport: even if the user previously scrolled up,
        # the next typed character/caret move must reveal the live input row.
        self._manual_scroll_until = 0.0
        self._follow_tail = True
        self._scroll_pending = False
        self._cursor_scroll_pending = True
        self._last_paint = None

    def _backspace(self):
        if self._find_active:
            if self._find_query:
                self._find_query = self._find_query[:-1]
                self._find_changed()
            return
        if self._ctrl_down():
            self.buffer.delete_word_left()
        else:
            self.buffer.backspace()
        self._edited()

    def _ctrl_down(self):
        override = getattr(self, "_ctrl_key_override", None)
        if override is not None:
            return bool(override)
        return bool(QKeyboard.modifiers(backend=dpg) & Qt.ControlModifier)

    def _shift_down(self):
        override = getattr(self, "_shift_key_override", None)
        if override is not None:
            return bool(override)
        return bool(QKeyboard.modifiers(backend=dpg) & Qt.ShiftModifier)

    def _run_key_with_modifiers(self, callback, ctrl=False, shift=False):
        previous_ctrl = getattr(self, "_ctrl_key_override", None)
        previous_shift = getattr(self, "_shift_key_override", None)
        self._ctrl_key_override = bool(ctrl)
        self._shift_key_override = bool(shift)
        try:
            callback()
        finally:
            self._ctrl_key_override = previous_ctrl
            self._shift_key_override = previous_shift

    def _queue_key(self, callback):
        ctrl = self._ctrl_down()
        shift = self._shift_down()
        self.view.after(0, self._run_key_with_modifiers, callback, ctrl, shift)

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

    def _line_left(self):
        if self._find_active:
            return
        self.buffer.move_cursor(-1)
        self._edited()

    def _line_home(self):
        if self._find_active:
            return
        self.buffer.move_home()
        self._edited()

    def _line_end(self):
        if self._find_active:
            return
        self.buffer.move_end()
        self._edited()

    def _control_a(self):
        # Preserve the transcript-wide Select All accelerator on Ctrl+Shift+A
        # while giving plain Ctrl+A the conventional readline beginning-of-line
        # behavior used by SSH shells. A visible context menu keeps priority.
        if self._context_menu_key_action("select_all"):
            return
        if self._shift_down():
            self._select_all()
        else:
            self._line_home()

    def _home(self):
        if self._find_active:
            return
        if self._ctrl_down():
            # cmd.exe line editing: Ctrl+Home removes everything before caret.
            self.buffer.delete_to_start()
        else:
            self.buffer.move_home()
        self._edited()

    def _end(self):
        if self._find_active:
            return
        if self._ctrl_down():
            # cmd.exe line editing: Ctrl+End removes everything after caret.
            self.buffer.delete_to_end()
        else:
            self.buffer.move_end()
        self._edited()

    def _line_backspace(self):
        if self._find_active:
            if self._find_query:
                self._find_query = self._find_query[:-1]
                self._find_changed()
            return
        self.buffer.backspace()
        self._edited()

    def _line_delete(self):
        if self._find_active:
            return
        self.buffer.delete()
        self._edited()

    def _delete(self):
        if self._find_active:
            return
        if self._ctrl_down():
            self.buffer.delete_word_right()
        else:
            self.buffer.delete()
        self._edited()

    def _delete_word_left(self):
        if self._find_active:
            return
        self.buffer.delete_word_left()
        self._edited()

    def _delete_word_right(self):
        if self._find_active:
            return
        self.buffer.delete_word_right()
        self._edited()

    def _delete_to_start(self):
        if self._find_active:
            return
        self.buffer.delete_to_start()
        self._edited()

    def _delete_to_end(self):
        if self._find_active:
            return
        self.buffer.delete_to_end()
        self._edited()

    def _kill_word_left(self):
        if self._find_active:
            return
        self.buffer.kill_word_left()
        self._edited()

    def _kill_to_start(self):
        if self._find_active:
            return
        self.buffer.kill_to_start()
        self._edited()

    def _kill_to_end(self):
        if self._find_active:
            return
        self.buffer.kill_to_end()
        self._edited()

    def _yank(self):
        if self._find_active:
            return
        if self.buffer.yank():
            self._edited()

    def _toggle_overwrite(self):
        if self._find_active:
            return
        self.buffer.toggle_overwrite()
        self._caret_blink_started = time.monotonic()
        self._last_paint = None

    def _template_char(self):
        if self._find_active or self.buffer.pending is not None:
            return
        if self.buffer.copy_template_char():
            self._edited()

    def _template_remainder(self):
        if self._find_active or self.buffer.pending is not None:
            return
        if self.buffer.copy_template_remainder():
            self._edited()

    def _template_full(self):
        if self._find_active or self.buffer.pending is not None:
            return
        if self.buffer.copy_template():
            self._edited()

    def _history_prefix(self):
        if self._find_active or self.buffer.pending is not None:
            return
        if self.buffer.recall_prefix(-1):
            self._edited()

    def _history_contains(self):
        if self._find_active or self.buffer.pending is not None:
            return
        if self.buffer.recall_contains(-1):
            self._edited()

    def _clear_command_line(self):
        if self._find_active or self.buffer.pending is not None:
            return False
        if not self.buffer.draft:
            return False
        self.buffer.clear_draft()
        self._edited()
        return True

    def _tab(self):
        if self._find_active or self.buffer.pending is not None:
            return
        callback = getattr(self, "completion_callback", None)
        if not callable(callback):
            return

        # _shift_down() resolves both left/right Shift through QKeyboard.
        # honors a queued modifier snapshot when the key callback is deferred.
        direction = -1 if self._shift_down() else 1
        state = self._completion_state
        if (state is not None
                and self.buffer.draft == state.get("current_draft")
                and self.buffer.cursor == state.get("current_cursor")
                and len(state.get("candidates", ())) > 1):
            # CMD-style ambiguous completion: the first Tab has already
            # expanded the safe shared prefix.  Repeated Tab/Shift+Tab then
            # walks the matching token values without touching the rest of the
            # command line.  This is intentionally different from readline's
            # double-Tab listing and mirrors cmd.exe filename completion.
            self._cycle_completion_state(state, direction)
            return

        draft, cursor = self.buffer.draft, self.buffer.cursor
        pending = self._completion_pending
        if pending is not None and pending[:2] == (draft, cursor):
            # Preserve extra Tab presses while the remote lookup is in flight.
            # Once candidates arrive the first physical Tab expands the shared
            # prefix and each queued direction advances one CMD-style match.
            self._completion_queued_directions.append(direction)
            return
        self._completion_request_serial += 1
        serial = self._completion_request_serial
        self._completion_pending = (draft, cursor, serial, direction)
        self._completion_state = None
        self._completion_queued_directions = []

        def completed(result):
            try:
                self.view.after(0, self._completion_result,
                                serial, draft, cursor, direction, result)
            except Exception:
                pass

        try:
            accepted = callback(draft, cursor, completed)
        except Exception:
            self._completion_pending = None
            return
        if accepted is False:
            self._completion_pending = None

    def _completion_columns(self):
        """Approximate the terminal width for readline-style candidate grids."""
        try:
            width = int(self._content_surface.globalGeometry(clipped=True).width())
        except Exception:
            width = 640
        char_width = max(1, int(getattr(self, "_char_width", 8) or 8))
        return max(20, (max(160, width) - 16) // char_width)

    def _show_completion_candidates(self, candidates):
        callback = getattr(self, "completion_list_callback", None)
        if not callable(callback):
            return False
        values = [str(value) for value in candidates if str(value)]
        if not values:
            return False
        try:
            accepted = callback(
                self.buffer.draft, values, self._completion_columns())
        except Exception:
            return False
        if accepted is False:
            return False
        # The model appends the list + a fresh prompt to visible scrollback.
        # Force a refresh immediately so the user sees the double-Tab result
        # without waiting for the regular 100 ms polling tick.
        try:
            self._set_output(self.output_callback())
        except Exception:
            pass
        self._follow_tail = True
        self._manual_scroll_until = 0.0
        self._scroll_pending = True
        self._cursor_scroll_pending = True
        self._last_paint = None
        return True

    def _completion_result(self, serial, draft, cursor, direction, result):
        if not self.winfo_exists():
            return
        pending = self._completion_pending
        if (pending is None or pending[2] != serial
                or serial != self._completion_request_serial):
            return
        self._completion_pending = None
        queued_directions = list(self._completion_queued_directions)
        self._completion_queued_directions = []
        if self.buffer.draft != draft or self.buffer.cursor != cursor:
            return
        if not isinstance(result, dict):
            return
        try:
            start = max(0, min(len(draft), int(result.get("start", cursor))))
            end = max(start, min(len(draft), int(result.get("end", cursor))))
        except (TypeError, ValueError):
            return
        raw_candidates = list(result.get("candidates", ()))
        raw_display = list(result.get("display_candidates", ()))
        candidates = []
        display_candidates = []
        seen = set()
        for index, raw_value in enumerate(raw_candidates):
            value = str(raw_value)
            if value in seen:
                continue
            seen.add(value)
            candidates.append(value)
            if index < len(raw_display):
                display_candidates.append(str(raw_display[index]))
            else:
                display_candidates.append(value)
        if not candidates:
            return

        current = draft[start:end]
        typed_prefix = draft[start:cursor]
        state = {
            "prefix": draft[:start], "suffix": draft[end:],
            "candidates": candidates, "candidate_index": -1,
            "display_candidates": display_candidates, "applied_value": current,
            "typed_prefix": typed_prefix,
            "current_draft": draft, "current_cursor": cursor,
        }
        self._completion_state = state

        if len(candidates) == 1:
            replacement = str(result.get("replacement", "") or candidates[0])
            if replacement == current:
                self._completion_state = None
                return
            self._apply_completion_value(state, replacement)
            # An unambiguous completion is complete; the next Tab should query
            # the next command/path segment instead of reusing stale state.
            self._completion_state = None
            return

        # Both Tab and Shift+Tab use conservative readline-style ambiguity
        # handling.  Menu/cycle completion is intentionally not enabled by
        # default because it silently changes the command when several matches
        # exist.
        common_prefix = str(result.get("common_prefix", "") or "")
        if (common_prefix.startswith(typed_prefix)
                and len(common_prefix) > len(typed_prefix)):
            self._apply_completion_value(state, common_prefix)
        # If the user pressed Tab again before the async query completed,
        # replay those presses now.  The first physical Tab owns the common
        # prefix expansion; every additional press advances a concrete match.
        for queued_direction in queued_directions:
            self._cycle_completion_state(state, queued_direction)

    def _cycle_completion_state(self, state, direction):
        candidates = list(state.get("candidates", ()))
        if not candidates:
            return False
        try:
            index = int(state.get("candidate_index", -1))
        except (TypeError, ValueError):
            index = -1
        step = -1 if int(direction or 1) < 0 else 1
        if index < 0:
            index = len(candidates) - 1 if step < 0 else 0
        else:
            index = (index + step) % len(candidates)
        state["candidate_index"] = index
        self._apply_completion_value(state, candidates[index])
        return True

    def _apply_completion_value(self, state, candidate):
        candidate = str(candidate)
        prefix, suffix = state["prefix"], state["suffix"]
        draft = prefix + candidate + suffix
        self._completion_applying = True
        try:
            self.buffer.draft = draft[:self.buffer.COMMAND_LIMIT]
            self.buffer.cursor = min(
                len(self.buffer.draft), len(prefix) + len(candidate))
            self.buffer.history_index = len(self.buffer.history)
            self._edited()
        finally:
            self._completion_applying = False
        state["applied_value"] = candidate
        state["current_draft"] = self.buffer.draft
        state["current_cursor"] = self.buffer.cursor

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
        if QKeyboard.modifiers(backend=dpg) & Qt.ShiftModifier:
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

    def _f3_shortcut(self, sender=None, app_data=None, user_data=None):
        # Preserve F3/Shift+F3 transcript-search repeat while Find is active;
        # otherwise use the native CMD/DOSKEY F3 template operation.
        if self._find_active:
            direction = -1 if self._shift_down() else 1
            self.view.after(0, self._find_next, direction)
        else:
            self.view.after(0, self._template_remainder)

    def _find_repeat_shortcut(self, sender=None, app_data=None, user_data=None):
        direction = -1 if (QKeyboard.modifiers(backend=dpg) & Qt.ShiftModifier) else 1
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
            columns = max(8, int(max(40, self._content_surface.globalGeometry(clipped=True).width() - 24) / self._char_width))
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
        # CMD-compatible Escape clears the active input line first. An empty
        # floating console keeps the historical Escape-to-close behavior.
        if self._clear_command_line():
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
        if not self.winfo_exists():
            return
        surface = getattr(self, "_content_surface", None)
        if surface is not None:
            if not surface.underMouse():
                return
        else:
            try:
                if not dpg.is_item_hovered(self.content):
                    return
            except Exception:
                return
        # Wheel motion always means the user owns scroll position for a short
        # quiet period. Background SSH output may grow the canvas during that
        # time, but must not move the viewport. Once interaction settles, the
        # renderer may re-enable follow-tail only if the viewport is genuinely
        # back at the bottom.
        self._manual_scroll_until = time.monotonic() + 0.35
        self._follow_tail = False
        self._scroll_pending = False
        self._cursor_scroll_pending = False

    def _refresh(self):
        if not self.winfo_exists():
            return
        try:
            self._set_output(self.output_callback())
        except Exception as exc:
            self.buffer.set_output("Console unavailable: {}".format(exc))
            if callable(self.error_callback):
                self.error_callback(str(exc))

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
            handlers = getattr(self, "_terminal_handlers", None)
            if handlers is not None and hasattr(handlers, "delete"):
                handlers.delete()
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
                 interrupt_callback, error_callback=None, completion_callback=None,
                 completion_list_callback=None):
        # ConsoleDockPanel intentionally reuses ConsoleDialog's terminal/editor
        # implementation without constructing a top-level QtDialog. Since
        # QtDialog now participates in QObject ownership, initialize only the
        # QObject side here so bound-method signal connections (QTimer, etc.)
        # have a valid receiver lifecycle.
        QObject.__init__(self, after=view.after)
        self.view = view
        self.output_callback, self.command_callback = output_callback, command_callback
        self.interrupt_callback, self.error_callback = interrupt_callback, error_callback
        self.completion_callback = completion_callback
        self.completion_list_callback = completion_list_callback
        self.buffer = TerminalBuffer()
        self._last_output = None
        self._follow_tail = True
        self._scroll_pending = False
        self._cursor_scroll_pending = False
        self._manual_scroll_until = 0.0
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
        self._completion_request_serial = 0
        self._completion_pending = None
        self._completion_state = None
        self._completion_applying = False
        self._completion_queued_directions = []
        self._destroyed = False
        self.preferred_size = (760, 220)
        self.shortcuts = {}

        self._theme = terminal_theme(parent=self, backend=dpg)
        self._content_frame = QFrame(
            parent=parent, width=-1, height=-1, frame_shape=QFrame.StyledPanel,
            no_scrollbar=False, no_scroll_with_mouse=False, backend=dpg)
        self.tag = self.content = self._content_frame.tag
        self._content_surface = self._content_frame
        self._content_surface.setTheme(self._theme)
        self._scroller_arrow_overlay = DpgScrollerArrowOverlay(
            dpg, self.content, f"{self.tag}_scroller", vertical=True, horizontal=False)
        self._canvas_widget = QCanvas(
            width=600, height=20, parent=self.content, backend=dpg)
        self.canvas = self._canvas_widget.tag
        self._line_items = []
        painter = QPainter(self._canvas_widget)
        self._current_line_fill = painter.drawRect(
            (0, 0), (0, 0), color=CURRENT_LINE, fill=CURRENT_LINE)
        self._caret = painter.drawRect(
            (0, 0), (7, 2), color=COMMAND, fill=COMMAND)

        self._create_context_menu()
        self.output = self.input = self.canvas

        self._terminal_handlers = QGlobalInputBinding(
            backend=dpg, parent=self, after=self.view.after)
        for key, callback in (
                (Qt.Key_Backspace, self._backspace),
                (Qt.Key_V, self._paste),
                (Qt.Key_Tab, self._tab),
                (Qt.Key_Left, self._left),
                (Qt.Key_Right, self._right),
                (Qt.Key_Up, self._up_key),
                (Qt.Key_Down, self._down_key),
                (Qt.Key_Home, self._home),
                (Qt.Key_End, self._end),
                (Qt.Key_Delete, self._delete),
        ):
            self._terminal_handlers.onKeyPress(
                key, self._dock_key_callback, user_data=callback)
        self._terminal_handlers.onKeyPress(
            Qt.Key_Insert, self._dock_key_callback, user_data=self._toggle_overwrite)
        self._terminal_handlers.onKeyPress(
            Qt.Key_F1, self._dock_key_callback, user_data=self._template_char)
        self._terminal_handlers.onKeyPress(
            Qt.Key_F5, self._dock_key_callback, user_data=self._template_full)
        self._terminal_handlers.onKeyPress(
            Qt.Key_F8, self._dock_key_callback, user_data=self._history_prefix)
        for key, callback in (
                (Qt.Key_E, self._line_end),
                (Qt.Key_B, self._line_left),
                (Qt.Key_P, self._up_key),
                (Qt.Key_N, self._down_key),
                (Qt.Key_R, self._history_contains),
                (Qt.Key_W, self._kill_word_left),
                (Qt.Key_U, self._kill_to_start),
                (Qt.Key_K, self._kill_to_end),
                (Qt.Key_Y, self._yank),
                (Qt.Key_D, self._line_delete),
                (Qt.Key_H, self._line_backspace),
                (Qt.Key_L, self._clear_console)):
            self._terminal_handlers.onKeyPress(
                key, self._dock_ctrl_edit_callback, user_data=callback)
        self._terminal_handlers.onKeyPress(Qt.Key_Return, self._dock_return_callback)
        self._terminal_handlers.onKeyPress(Qt.Key_Escape, self._dock_escape_callback)
        self._terminal_handlers.onKeyPress(Qt.Key_C, self._dock_ctrl_c_callback)
        self._terminal_handlers.onKeyPress(Qt.Key_A, self._dock_ctrl_a_callback)
        self._terminal_handlers.onKeyPress(Qt.Key_F, self._dock_find_callback)
        self._terminal_handlers.onKeyPress(Qt.Key_F3, self._dock_find_repeat_callback)
        self._terminal_handlers.onMouseWheel(self._wheel)
        self._terminal_handlers.onMouseDrag(
            Qt.LeftButton, self._mouse_drag, threshold=1.0)
        self._terminal_handlers.onMouseRelease(Qt.LeftButton, self._mouse_release)
        self._terminal_handlers.onMouseRelease(
            Qt.RightButton, self._right_release_fallback)
        self._terminal_handlers.onMouseClick(Qt.LeftButton, self._mouse_click)
        self._terminal_handlers.activate()

        self._refresh()
        self._paint_tick()
        self._refresh_timer = QTimer(self)
        self._refresh_timer.setInterval(100)
        self._refresh_timer.timeout.connect(self._refresh)
        self._refresh_timer.start()
        self._paint_timer = QTimer(self)
        self._paint_timer.setInterval(33)
        self._paint_timer.timeout.connect(self._paint_tick)
        self._paint_timer.start()

    def winfo_exists(self):
        return (not self._destroyed) and self._content_frame.exists()

    def keyboard_active(self):
        # This predicate is also queried from the native WM_CHAR hook.  Keep it
        # free of Dear PyGui calls so the WNDPROC never re-enters the item
        # registry while GLFW/Dear ImGui is dispatching a Windows message.
        return bool(
            not self._destroyed
            and getattr(self.view, "_console_keyboard_panel", None) is self
            and getattr(self.view, "_console_dock_visible", False)
            and getattr(self.view, "_console_dock_mode", "docked") == "docked"
        )

    def event(self, event):
        """Consume QApplication keyboard routing while the terminal owns input.

        The docked terminal already has Dear PyGui key handlers for editing and
        Enter submission, plus the Win32 WM_CHAR bridge for text.  QApplication
        must still see the Console as the logical focus object so the same
        physical Enter cannot bubble into a previously focused Explorer view.
        Do not execute the key here: consuming it prevents background widgets
        from receiving it without submitting the terminal command twice.
        """
        if (self.keyboard_active()
                and event.type() in (
                    QEvent.KeyPress, QEvent.KeyRelease,
                    QEvent.ShortcutOverride)):
            return True
        return QObject.event(self, event)

    def focus_input(self, follow_tail=True, focus_window=True):
        if not self.winfo_exists():
            return
        self._caret_blink_started = time.monotonic()
        was_active = self.keyboard_active()
        setter = getattr(self.view, "_set_console_keyboard_active", None)
        if callable(setter):
            setter(True, self)
        if follow_tail:
            self._follow_tail = True
            self._scroll_pending = True
            self._manual_scroll_until = 0.0
        # The physical click already focuses the docked surface. Only issue a
        # DPG focus request when keyboard ownership is actually being acquired;
        # repeating it while already active is a common source of scroll jumps.
        if focus_window and not was_active:
            frame = getattr(self, "_content_frame", None)
            if frame is not None:
                frame.setFocus()
            else:
                # Compatibility with embedded hosts created before QFrame was
                # retained as an object; current ConsoleDockPanel owns a frame.
                dpg.focus_item(self.tag)

    def _dock_key_callback(self, sender=None, app_data=None, user_data=None):
        if self.keyboard_active() and callable(user_data):
            # Keep the queued callback contract deliberately one-argument: the
            # second ownership check in _run_dock_key prevents a stale key from
            # editing the console after focus has moved to another widget.
            self.view.after(0, self._run_dock_key, user_data)

    def _run_dock_key(self, callback):
        if self.keyboard_active():
            callback()

    def _dock_ctrl_edit_callback(self, sender=None, app_data=None, user_data=None):
        if self.keyboard_active() and self._ctrl_down() and callable(user_data):
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
        elif self.buffer.draft:
            self.view.after(0, self._clear_command_line)

    def _dock_ctrl_c_callback(self, sender=None, app_data=None, user_data=None):
        if self.keyboard_active() and self._ctrl_down():
            self.view.after(0, self._control_c)

    def _dock_ctrl_a_callback(self, sender=None, app_data=None, user_data=None):
        if self.keyboard_active() and self._ctrl_down():
            self.view.after(0, self._control_a)

    def _dock_find_callback(self, sender=None, app_data=None, user_data=None):
        if self.keyboard_active() and self._ctrl_down():
            self.view.after(0, self._open_find)

    def _dock_find_repeat_callback(self, sender=None, app_data=None, user_data=None):
        if not self.keyboard_active():
            return
        if self._find_active:
            direction = -1 if (QKeyboard.modifiers(backend=dpg) & Qt.ShiftModifier) else 1
            self.view.after(0, self._find_next, direction)
        else:
            self.view.after(0, self._template_remainder)

    def _close_from_escape(self):
        menu = getattr(self, "_context_menu_obj", None)
        if menu is not None and bool(getattr(menu, "is_open", False)):
            menu.hide()
        elif self._find_active:
            self._close_find()
        else:
            self._clear_command_line()

    def destroy(self):
        if self._destroyed:
            return
        self._destroyed = True
        for timer_name in ("_refresh_timer", "_paint_timer"):
            timer = getattr(self, timer_name, None)
            if timer is not None:
                try:
                    timer.delete()
                except Exception:
                    pass
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
        handlers = getattr(self, "_terminal_handlers", None)
        if handlers is not None and hasattr(handlers, "delete"):
            try:
                handlers.delete()
            except Exception:
                pass
        frame = getattr(self, "_content_frame", None)
        if frame is not None:
            try:
                frame.delete()
            except Exception:
                pass
        # Match the QObject lifetime initialized above. Call the base QObject
        # implementation explicitly because QtDialog.delete() delegates back to
        # destroy(), which would recurse for this embedded panel.
        QObject.delete(self)

    def close(self, wait=True, timeout=1.0):
        self.destroy()
        return not self.winfo_exists()
