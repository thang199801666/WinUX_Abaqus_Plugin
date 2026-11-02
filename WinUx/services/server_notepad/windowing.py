from __future__ import annotations

"""Native placement/activation owner for the standalone Server Notepad window."""

import os
import re

if os.name == "nt":
    import ctypes
    from ctypes import wintypes
else:  # pragma: no cover - Win32 placement is exercised on Windows.
    ctypes = None
    wintypes = None


class ServerNotepadWindowingMixin:
    def _restored_window_size(self):
        geometry = str(self._state.get("geometry") or "")
        match = re.match(r"^\s*(\d+)x(\d+)", geometry)
        width = int(match.group(1)) if match else self.WIDTH
        height = int(match.group(2)) if match else self.HEIGHT
        width = max(self.MIN_WIDTH, width)
        height = max(self.MIN_HEIGHT, height)
        try:
            width = min(width, max(self.MIN_WIDTH, int(self.winfo_screenwidth()) - 32))
            height = min(height, max(self.MIN_HEIGHT, int(self.winfo_screenheight()) - 64))
        except Exception:
            pass
        return width, height

    def _native_hwnd(self):
        if os.name != "nt" or ctypes is None:
            return 0
        try:
            self.update_idletasks()
            hwnd = int(self.winfo_id() or 0)
            if not hwnd:
                return 0
            GA_ROOT = 2
            user32 = ctypes.windll.user32
            user32.GetAncestor.argtypes = [wintypes.HWND, wintypes.UINT]
            user32.GetAncestor.restype = wintypes.HWND
            root = user32.GetAncestor(wintypes.HWND(hwnd), GA_ROOT)
            return int(root or hwnd)
        except Exception:
            return 0

    def _center_over_owner(self):
        """Centre this child-process editor over the fixed WinUx owner HWND."""
        if os.name != "nt" or ctypes is None or not self._owner_hwnd:
            try:
                self.update_idletasks()
                width = max(self.MIN_WIDTH, int(self.winfo_width() or self.WIDTH))
                height = max(self.MIN_HEIGHT, int(self.winfo_height() or self.HEIGHT))
                x = max(0, (int(self.winfo_screenwidth()) - width) // 2)
                y = max(0, (int(self.winfo_screenheight()) - height) // 2)
                self.geometry("{}x{}+{}+{}".format(width, height, x, y))
                return True
            except Exception:
                return False
        try:
            user32 = ctypes.windll.user32
            user32.IsWindow.argtypes = [wintypes.HWND]
            user32.IsWindow.restype = wintypes.BOOL
            user32.GetWindowRect.argtypes = [
                wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
            user32.GetWindowRect.restype = wintypes.BOOL
            user32.MonitorFromWindow.argtypes = [wintypes.HWND, wintypes.DWORD]
            user32.MonitorFromWindow.restype = wintypes.HANDLE
            hwnd = self._native_hwnd()
            if not hwnd or not user32.IsWindow(wintypes.HWND(self._owner_hwnd)):
                return False
            owner_rect = wintypes.RECT()
            window_rect = wintypes.RECT()
            if not user32.GetWindowRect(
                    wintypes.HWND(self._owner_hwnd), ctypes.byref(owner_rect)):
                return False
            if not user32.GetWindowRect(
                    wintypes.HWND(hwnd), ctypes.byref(window_rect)):
                return False

            width = max(1, int(window_rect.right - window_rect.left))
            height = max(1, int(window_rect.bottom - window_rect.top))
            x = int(owner_rect.left +
                    ((owner_rect.right - owner_rect.left - width) // 2))
            y = int(owner_rect.top +
                    ((owner_rect.bottom - owner_rect.top - height) // 2))

            class MONITORINFO(ctypes.Structure):
                _fields_ = [
                    ("cbSize", wintypes.DWORD),
                    ("rcMonitor", wintypes.RECT),
                    ("rcWork", wintypes.RECT),
                    ("dwFlags", wintypes.DWORD),
                ]

            MONITOR_DEFAULTTONEAREST = 2
            monitor = user32.MonitorFromWindow(
                wintypes.HWND(self._owner_hwnd), MONITOR_DEFAULTTONEAREST)
            if monitor:
                info = MONITORINFO()
                info.cbSize = ctypes.sizeof(MONITORINFO)
                if user32.GetMonitorInfoW(monitor, ctypes.byref(info)):
                    work = info.rcWork
                    x = min(max(x, int(work.left)),
                            max(int(work.left), int(work.right) - width))
                    y = min(max(y, int(work.top)),
                            max(int(work.top), int(work.bottom) - height))
            user32.GetMonitorInfoW.argtypes = [
                wintypes.HANDLE, ctypes.POINTER(MONITORINFO)]
            user32.GetMonitorInfoW.restype = wintypes.BOOL
            user32.SetWindowPos.argtypes = [
                wintypes.HWND, wintypes.HWND, ctypes.c_int, ctypes.c_int,
                ctypes.c_int, ctypes.c_int, wintypes.UINT]
            user32.SetWindowPos.restype = wintypes.BOOL
            SWP_NOSIZE = 0x0001
            SWP_NOZORDER = 0x0004
            SWP_SHOWWINDOW = 0x0040
            return bool(user32.SetWindowPos(
                wintypes.HWND(hwnd), None, x, y, 0, 0,
                SWP_NOSIZE | SWP_NOZORDER | SWP_SHOWWINDOW))
        except Exception:
            return False

    def _activate_native_window(self, center=False):
        """Restore/show the editor and recover an off-screen saved window."""
        try:
            self.deiconify()
            self.update_idletasks()
        except Exception:
            pass
        if os.name == "nt" and ctypes is not None:
            try:
                user32 = ctypes.windll.user32
                user32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
                user32.ShowWindow.restype = wintypes.BOOL
                user32.MonitorFromWindow.argtypes = [wintypes.HWND, wintypes.DWORD]
                user32.MonitorFromWindow.restype = wintypes.HANDLE
                user32.SetWindowPos.argtypes = [
                    wintypes.HWND, wintypes.HWND, ctypes.c_int, ctypes.c_int,
                    ctypes.c_int, ctypes.c_int, wintypes.UINT]
                user32.SetWindowPos.restype = wintypes.BOOL
                user32.BringWindowToTop.argtypes = [wintypes.HWND]
                user32.BringWindowToTop.restype = wintypes.BOOL
                user32.SetForegroundWindow.argtypes = [wintypes.HWND]
                user32.SetForegroundWindow.restype = wintypes.BOOL
                hwnd = self._native_hwnd()
                if hwnd:
                    SW_RESTORE = 9
                    MONITOR_DEFAULTTONULL = 0
                    user32.ShowWindow(wintypes.HWND(hwnd), SW_RESTORE)
                    visible_monitor = user32.MonitorFromWindow(
                        wintypes.HWND(hwnd), MONITOR_DEFAULTTONULL)
                    if center or not visible_monitor:
                        self._center_over_owner()
                    SWP_NOMOVE = 0x0002
                    SWP_NOSIZE = 0x0001
                    SWP_SHOWWINDOW = 0x0040
                    HWND_TOP = 0
                    user32.SetWindowPos(
                        wintypes.HWND(hwnd), wintypes.HWND(HWND_TOP),
                        0, 0, 0, 0,
                        SWP_NOMOVE | SWP_NOSIZE | SWP_SHOWWINDOW)
                    user32.BringWindowToTop(wintypes.HWND(hwnd))
                    user32.SetForegroundWindow(wintypes.HWND(hwnd))
            except Exception:
                if center:
                    self._center_over_owner()
        elif center:
            self._center_over_owner()
        try:
            self.lift()
            self.focus_force()
        except Exception:
            pass

