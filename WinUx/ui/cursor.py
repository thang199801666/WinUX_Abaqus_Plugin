"""Canvas cursor ownership with a cached, GUI-free native cursor provider."""
import ctypes
from ctypes import wintypes
import os

from ..platform.tool_cursor import ToolCursorHandles


class CanvasCursor:
    def __init__(self, view, *, window=None):
        self.view = view
        self.mode = None
        self._screen_rect = None
        self._capture = False
        self._handles = ToolCursorHandles()
        self._handle = None
        self._window = window
        self._hook_hwnd = None
        self._hook_proc = None
        self._old_proc = None
        view._tool_cursor = self

    def update(self, mode, rect=None, *, capture=False, screen_coordinates=False):
        previous_handle = self._handle
        self.mode = mode
        self._capture = bool(capture)
        self._handle = self._handles.get(mode)
        self._screen_rect = None
        if os.name == 'nt' and rect is not None:
            if screen_coordinates:
                self._screen_rect = tuple(rect)
                self._install_window_hook()
            else:
                hwnd = getattr(self.view, '_native_hwnd', 0)
                if hwnd:
                    point = wintypes.POINT(int(rect[0]), int(rect[1]))
                    user32 = ctypes.windll.user32
                    user32.ClientToScreen.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.POINT)]
                    if user32.ClientToScreen(hwnd, ctypes.byref(point)):
                        self._screen_rect = (point.x, point.y, point.x + rect[2] - rect[0], point.y + rect[3] - rect[1])
        self.apply()
        if previous_handle and self._handle is None and os.name == 'nt':
            user32 = ctypes.windll.user32
            user32.SetCursor.argtypes = [wintypes.HANDLE]
            user32.SetCursor(self._handles.get('arrow'))

    def _install_window_hook(self):
        """Keep a secondary native viewport's cursor stable across GLFW updates."""
        if self._hook_hwnd or self._window is None or os.name != 'nt':
            return
        from DearUIQt.backends.native_windows import NativeWindowBackend
        try:
            hwnd = NativeWindowBackend().winId(self._window)
            if not hwnd:
                return
            user32 = ctypes.windll.user32
            setter = user32.SetWindowLongPtrW if ctypes.sizeof(ctypes.c_void_p) == 8 else user32.SetWindowLongW
            setter.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_void_p]
            setter.restype = ctypes.c_void_p
            user32.CallWindowProcW.argtypes = [ctypes.c_void_p, wintypes.HWND, wintypes.UINT,
                                             wintypes.WPARAM, wintypes.LPARAM]
            user32.CallWindowProcW.restype = ctypes.c_ssize_t
            procedure_type = ctypes.WINFUNCTYPE(ctypes.c_ssize_t, wintypes.HWND, wintypes.UINT,
                                               wintypes.WPARAM, wintypes.LPARAM)

            def procedure(window, message, wparam, lparam):
                try:
                    if message == 0x0020 and (int(lparam) & 0xffff) == 1:
                        handle = self.native_handle()
                        if handle:
                            user32.SetCursor(wintypes.HANDLE(handle))
                            return 1
                except Exception:
                    pass
                return user32.CallWindowProcW(self._old_proc, window, message, wparam, lparam)

            callback = procedure_type(procedure)
            old_proc = setter(wintypes.HWND(hwnd), -4, ctypes.cast(callback, ctypes.c_void_p))
            if old_proc:
                self._hook_hwnd, self._hook_proc, self._old_proc = hwnd, callback, old_proc
        except Exception:
            pass

    def native_handle(self):
        # Called from WM_SETCURSOR. Only cached fields and Win32 APIs are used;
        # never re-enter Dear PyGui's item registry from a native window message.
        if not self._handle or os.name != 'nt':
            return None
        if self._hook_hwnd:
            user32 = ctypes.windll.user32
            hwnd = wintypes.HWND(self._hook_hwnd)
            if not user32.IsWindowVisible(hwnd) or not user32.IsWindowEnabled(hwnd):
                return None
        if self._capture:
            return self._handle
        if self._screen_rect is None:
            return None
        point = wintypes.POINT()
        if ctypes.windll.user32.GetCursorPos(ctypes.byref(point)):
            x0, y0, x1, y1 = self._screen_rect
            if x0 <= point.x < x1 and y0 <= point.y < y1:
                return self._handle
        return None

    def apply(self):
        handle = self.native_handle()
        if handle:
            user32 = ctypes.windll.user32
            user32.SetCursor.argtypes = [wintypes.HANDLE]
            user32.SetCursor(handle)

    def close(self):
        if self._hook_hwnd and os.name == 'nt':
            user32 = ctypes.windll.user32
            if user32.IsWindow(wintypes.HWND(self._hook_hwnd)):
                setter = user32.SetWindowLongPtrW if ctypes.sizeof(ctypes.c_void_p) == 8 else user32.SetWindowLongW
                setter(wintypes.HWND(self._hook_hwnd), -4, self._old_proc)
        self._hook_hwnd = self._hook_proc = self._old_proc = None
        if getattr(self.view, '_tool_cursor', None) is self:
            self.view._tool_cursor = None
        self.mode = None
        if self._handle and os.name == 'nt':
            ctypes.windll.user32.SetCursor(wintypes.HANDLE(self._handles.get('arrow')))
        self._handle = None
        self._handles.close()


def apply_tool_cursor(view):
    cursor = getattr(view, '_tool_cursor', None)
    if cursor is not None:
        cursor.apply()
