"""Keep native caption hover stable across GLFW's spurious leave messages."""
from __future__ import annotations

import ctypes
from ctypes import wintypes


class _TrackMouseEvent(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.DWORD), ("dwFlags", wintypes.DWORD),
                ("hwndTrack", wintypes.HWND), ("dwHoverTime", wintypes.DWORD)]


class NativeCaptionHoverGuard:
    """Filter only stale Close-button leaves; USER32 still paints the caption."""

    def __init__(self, user32):
        self.user32 = user32
        self._close_hover = False

    def suppress(self, hwnd, message, wparam):
        if message == 0x00A0:  # WM_NCMOUSEMOVE / HTCLOSE
            self._close_hover = int(wparam) == 20
        elif message == 0x02A2:  # WM_NCMOUSELEAVE
            if self._close_hover and self._still_over_close(hwnd):
                # A leave consumes the tracking registration. Re-arm it so a
                # later genuine departure also clears the native hot state.
                try:
                    track = _TrackMouseEvent(ctypes.sizeof(_TrackMouseEvent),
                                             0x12, hwnd, 0)  # TME_LEAVE | TME_NONCLIENT
                    function = self.user32.TrackMouseEvent
                    function.argtypes = [ctypes.POINTER(_TrackMouseEvent)]
                    function.restype = wintypes.BOOL
                    if function(ctypes.byref(track)):
                        return True
                except Exception:
                    pass
            self._close_hover = False
        elif message == 0x0086 and not wparam:  # WM_NCACTIVATE(FALSE)
            # Some GLFW/native-viewport maintenance paths transiently send a
            # non-client deactivation even though this HWND is still the real
            # foreground window. Letting DefWindowProc paint that false state
            # and then immediately paint active again flashes the title bar and
            # Close-button hot state. Suppress only the provably stale case; a
            # genuine foreground handoff (Alt-Tab, another app/dialog, etc.) is
            # forwarded unchanged.
            if self._still_foreground(hwnd):
                return True
            self._close_hover = False
        elif (message in (0x0018, 0x000A) and not wparam
              or message == 0x0082):  # hide, disable, destroy
            self._close_hover = False
        return False

    def _still_foreground(self, hwnd):
        try:
            self.user32.GetForegroundWindow.argtypes = []
            self.user32.GetForegroundWindow.restype = wintypes.HWND
            return int(self.user32.GetForegroundWindow() or 0) == int(hwnd)
        except Exception:
            return False

    def _still_over_close(self, hwnd):
        try:
            user32 = self.user32
            point = wintypes.POINT()
            user32.GetCursorPos.argtypes = [ctypes.POINTER(wintypes.POINT)]
            user32.GetCursorPos.restype = wintypes.BOOL
            if not user32.GetCursorPos(ctypes.byref(point)):
                return False
            user32.GetForegroundWindow.argtypes = []
            user32.GetForegroundWindow.restype = wintypes.HWND
            user32.IsWindowEnabled.argtypes = [wintypes.HWND]
            user32.IsWindowEnabled.restype = wintypes.BOOL
            user32.WindowFromPoint.argtypes = [wintypes.POINT]
            user32.WindowFromPoint.restype = wintypes.HWND
            if (int(user32.GetForegroundWindow() or 0) != int(hwnd)
                    or not user32.IsWindowEnabled(hwnd)
                    or int(user32.WindowFromPoint(point) or 0) != int(hwnd)):
                return False
            packed = (int(point.x) & 0xffff) | ((int(point.y) & 0xffff) << 16)
            user32.SendMessageW.argtypes = [wintypes.HWND, wintypes.UINT,
                                           wintypes.WPARAM, wintypes.LPARAM]
            user32.SendMessageW.restype = ctypes.c_ssize_t
            return int(user32.SendMessageW(hwnd, 0x0084, 0, packed)) == 20
        except Exception:
            # Never prevent a genuine leave if native state cannot be verified.
            return False
