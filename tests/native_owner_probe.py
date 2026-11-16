"""Observe primary-HWND transitions inside a render, not just after frames."""
import ctypes
from ctypes import wintypes
from unittest.mock import patch


class _Message(ctypes.Structure):
    _fields_ = [('lparam', wintypes.LPARAM), ('wparam', wintypes.WPARAM),
                ('message', wintypes.UINT), ('hwnd', wintypes.HWND)]


class _WindowPos(ctypes.Structure):
    _fields_ = [('hwnd', wintypes.HWND), ('after', wintypes.HWND),
                ('x', ctypes.c_int), ('y', ctypes.c_int),
                ('cx', ctypes.c_int), ('cy', ctypes.c_int), ('flags', wintypes.UINT)]


class NativeOwnerProbe:
    """Thread-local observation only: never suppress or change window messages."""
    def __init__(self, hwnd):
        self.hwnd = int(hwnd)
        self.events = []
        self._hook = None
        self._patch = None

    def start(self):
        user32 = ctypes.windll.user32
        rect = wintypes.RECT()
        assert user32.GetWindowRect(wintypes.HWND(self.hwnd), ctypes.byref(rect))
        original_rect = (rect.left, rect.top, rect.right - rect.left, rect.bottom - rect.top)
        callback_type = ctypes.WINFUNCTYPE(
            ctypes.c_ssize_t, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM)
        user32.SetWindowsHookExW.argtypes = [
            ctypes.c_int, ctypes.c_void_p, wintypes.HINSTANCE, wintypes.DWORD]
        user32.SetWindowsHookExW.restype = wintypes.HANDLE
        user32.CallNextHookEx.argtypes = [
            wintypes.HANDLE, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM]
        user32.CallNextHookEx.restype = ctypes.c_ssize_t

        @callback_type
        def observe(code, wparam, lparam):
            if code >= 0:
                message = ctypes.cast(lparam, ctypes.POINTER(_Message)).contents
                if int(message.hwnd or 0) == self.hwnd:
                    if message.message == 0x0018 and not message.wparam:
                        self.events.append(('hide', int(message.lparam)))
                    elif message.message == 0x0046 and message.lparam:
                        pos = ctypes.cast(message.lparam, ctypes.POINTER(_WindowPos)).contents
                        if pos.flags & 0x80:
                            self.events.append(('hide-position', pos.flags))
                        if not pos.flags & 0x02 and (pos.x, pos.y) != original_rect[:2]:
                            self.events.append(('move', pos.x, pos.y))
                        if not pos.flags & 0x01 and (pos.cx, pos.cy) != original_rect[2:]:
                            self.events.append(('resize', pos.cx, pos.cy))
                        if pos.flags & 0x20:
                            self.events.append(('frame-changed', pos.flags))
            return user32.CallNextHookEx(self._hook, code, wparam, lparam)

        self._callback = observe
        self._hook = user32.SetWindowsHookExW(
            4, observe, None, ctypes.windll.kernel32.GetCurrentThreadId())
        assert self._hook, 'Could not observe primary HWND transitions'
        original_set = ctypes.windll.dwmapi.DwmSetWindowAttribute

        def set_attribute(hwnd, attribute, value, size):
            handle = int(getattr(hwnd, 'value', hwnd) or 0)
            if handle == self.hwnd and attribute == 13:
                state = ctypes.cast(value, ctypes.POINTER(wintypes.BOOL)).contents.value
                if state:
                    self.events.append(('cloak',))
            return original_set(hwnd, attribute, value, size)

        self._patch = patch('ctypes.windll.dwmapi.DwmSetWindowAttribute', side_effect=set_attribute)
        self._patch.start()
        return self

    def close(self):
        if self._patch is not None:
            self._patch.stop()
            self._patch = None
        if self._hook:
            user32 = ctypes.windll.user32
            user32.UnhookWindowsHookEx.argtypes = [wintypes.HANDLE]
            user32.UnhookWindowsHookEx(self._hook)
            self._hook = None
