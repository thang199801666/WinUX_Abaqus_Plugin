"""Monitor work-area selection and deterministic toast stacking."""
from __future__ import annotations

from dataclasses import dataclass
import ctypes
import os
from ctypes import wintypes


@dataclass(frozen=True)
class WorkArea:
    left: int
    top: int
    right: int
    bottom: int
    dpi: int = 96

    @property
    def width(self):
        return max(0, self.right - self.left)

    @property
    def height(self):
        return max(0, self.bottom - self.top)


class _MonitorInfo(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.DWORD),
        ("rcMonitor", wintypes.RECT),
        ("rcWork", wintypes.RECT),
        ("dwFlags", wintypes.DWORD),
    ]


def _user32():
    if os.name != "nt":
        return None
    try:
        return ctypes.windll.user32
    except Exception:
        return None


def _monitor_dpi(hwnd=0, monitor=0):
    user32 = _user32()
    if user32 is None:
        return 96
    try:
        get_dpi_for_window = getattr(user32, "GetDpiForWindow", None)
        if get_dpi_for_window is not None and hwnd:
            get_dpi_for_window.argtypes = [wintypes.HWND]
            get_dpi_for_window.restype = wintypes.UINT
            value = int(get_dpi_for_window(wintypes.HWND(int(hwnd))) or 0)
            if value:
                return value
    except Exception:
        pass
    if monitor:
        try:
            shcore = ctypes.windll.shcore
            get_dpi = getattr(shcore, "GetDpiForMonitor", None)
            if get_dpi is not None:
                x, y = wintypes.UINT(), wintypes.UINT()
                get_dpi.argtypes = [wintypes.HANDLE, ctypes.c_int,
                                    ctypes.POINTER(wintypes.UINT), ctypes.POINTER(wintypes.UINT)]
                if int(get_dpi(wintypes.HANDLE(int(monitor)), 0, ctypes.byref(x), ctypes.byref(y))) == 0:
                    if x.value:
                        return int(x.value)
        except Exception:
            pass
    return 96


def monitor_work_area(owner_hwnd=0, point=None):
    """Return the nearest monitor's usable desktop rectangle.

    The Windows taskbar and app bars are excluded through ``rcWork``.  When an
    owner is supplied its monitor wins; otherwise an optional cursor/global
    point is used.  The non-Windows fallback deliberately returns a conventional
    1920x1080 work area so placement policy is unit-testable.
    """
    user32 = _user32()
    if user32 is None:
        return WorkArea(0, 0, 1920, 1040, 96)
    try:
        monitor = 0
        if owner_hwnd:
            user32.MonitorFromWindow.argtypes = [wintypes.HWND, wintypes.DWORD]
            user32.MonitorFromWindow.restype = wintypes.HANDLE
            monitor = int(user32.MonitorFromWindow(wintypes.HWND(int(owner_hwnd)), 2) or 0)
        if not monitor and point is not None:
            user32.MonitorFromPoint.argtypes = [wintypes.POINT, wintypes.DWORD]
            user32.MonitorFromPoint.restype = wintypes.HANDLE
            monitor = int(user32.MonitorFromPoint(
                wintypes.POINT(int(point[0]), int(point[1])), 2) or 0)
        if not monitor:
            user32.MonitorFromPoint.argtypes = [wintypes.POINT, wintypes.DWORD]
            user32.MonitorFromPoint.restype = wintypes.HANDLE
            cursor = wintypes.POINT()
            user32.GetCursorPos(ctypes.byref(cursor))
            monitor = int(user32.MonitorFromPoint(cursor, 2) or 0)
        if monitor:
            info = _MonitorInfo()
            info.cbSize = ctypes.sizeof(info)
            user32.GetMonitorInfoW.argtypes = [wintypes.HANDLE, ctypes.POINTER(_MonitorInfo)]
            user32.GetMonitorInfoW.restype = wintypes.BOOL
            if user32.GetMonitorInfoW(wintypes.HANDLE(monitor), ctypes.byref(info)):
                rc = info.rcWork
                return WorkArea(
                    int(rc.left), int(rc.top), int(rc.right), int(rc.bottom),
                    _monitor_dpi(owner_hwnd, monitor),
                )
    except Exception:
        pass
    return WorkArea(0, 0, 1920, 1040, 96)


def stack_positions(work_area, sizes, *, margin=14, gap=10):
    """Return bottom-right positions, ordered from newest/lower to older/upper."""
    x_right = int(work_area.right) - int(margin)
    y = int(work_area.bottom) - int(margin)
    positions = []
    for width, height in sizes:
        width, height = int(width), int(height)
        y -= height
        positions.append((x_right - width, y))
        y -= int(gap)
    return positions


__all__ = ["WorkArea", "monitor_work_area", "stack_positions"]
