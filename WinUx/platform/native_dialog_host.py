"""Single-thread native top-level dialog hosting for WinUX.

Dear PyGui exposes one native viewport.  ``dpg.window`` objects therefore live
inside that viewport and can never behave like normal desktop dialogs.  WinUX
hosts its desktop dialogs with Tk, but *all* Tk objects must live on the same
Tk thread.  Creating one ``Tk()`` interpreter per dialog on different threads
is unsafe in an embedded host such as Abaqus and can hard-crash Tcl/Tk when a
confirmation is destroyed while another native window (for example Transfer
Center) is still alive.

This module owns exactly one hidden Tk root on one daemon UI thread.  Dialogs
are real ``Toplevel`` windows created on that shared thread.  Application
callbacks are marshalled back to the Dear PyGui thread by the dialog classes
through ``view.after(...)``.
"""

from __future__ import annotations

import ctypes
import gc
import os
import queue
import threading
from ctypes import wintypes

from ..preferences.dialog_geometry import DialogGeometryPreferences
from ..resources import apply_tk_app_icon


GWLP_HWNDPARENT = -8
GA_ROOT = 2
GW_OWNER = 4
SW_RESTORE = 9
SWP_NOSIZE = 0x0001
SWP_NOMOVE = 0x0002
SWP_NOZORDER = 0x0004
SWP_NOACTIVATE = 0x0010
SWP_SHOWWINDOW = 0x0040
HWND_TOP = 0
MONITOR_DEFAULTTONEAREST = 2
DIALOG_GEOMETRY_MARGIN = 8
DIALOG_GEOMETRY_SAVE_DELAY_MS = 350

# Windows 11 / Qt-like top-level chrome.  The values are documented DWM
# attributes and degrade harmlessly on Windows 10 or older builds.
DWMWA_WINDOW_CORNER_PREFERENCE = 33
DWMWA_BORDER_COLOR = 34
DWMWA_CAPTION_COLOR = 35
DWMWA_TEXT_COLOR = 36
DWMWCP_ROUND = 2
GWL_STYLE = -16
GWL_EXSTYLE = -20
WS_CHILD = 0x40000000
WS_CAPTION = 0x00C00000
WS_SYSMENU = 0x00080000
WS_THICKFRAME = 0x00040000
WS_MINIMIZEBOX = 0x00020000
WS_MAXIMIZEBOX = 0x00010000
WS_EX_TOOLWINDOW = 0x00000080
WS_EX_APPWINDOW = 0x00040000
SW_SHOWMINIMIZED = 2
SW_SHOWMAXIMIZED = 3
SW_SHOWNORMAL = 1
SWP_FRAMECHANGED = 0x0020

_MODAL_OWNER_LOCK = threading.RLock()
_MODAL_OWNER_COUNTS = {}
_NATIVE_TK_HOST_LOCK = threading.RLock()
_NATIVE_TK_HOST = None


def find_process_window(title="WinUX"):
    """Return this process' visible top-level window, preferring *title*."""
    if os.name != "nt":
        return None
    try:
        user32 = ctypes.windll.user32
        kernel32 = ctypes.windll.kernel32

        kernel32.GetCurrentProcessId.argtypes = []
        kernel32.GetCurrentProcessId.restype = wintypes.DWORD
        pid = kernel32.GetCurrentProcessId()

        WNDENUMPROC = ctypes.WINFUNCTYPE(
            wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
        user32.EnumWindows.argtypes = [WNDENUMPROC, wintypes.LPARAM]
        user32.EnumWindows.restype = wintypes.BOOL
        user32.GetWindowThreadProcessId.argtypes = [
            wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
        user32.GetWindowThreadProcessId.restype = wintypes.DWORD
        user32.IsWindowVisible.argtypes = [wintypes.HWND]
        user32.IsWindowVisible.restype = wintypes.BOOL
        user32.GetWindowTextLengthW.argtypes = [wintypes.HWND]
        user32.GetWindowTextLengthW.restype = ctypes.c_int
        user32.GetWindowTextW.argtypes = [
            wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
        user32.GetWindowTextW.restype = ctypes.c_int

        matches = []

        def enum_proc(hwnd, _lparam):
            found_pid = wintypes.DWORD()
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(found_pid))
            if found_pid.value != pid or not user32.IsWindowVisible(hwnd):
                return True
            length = user32.GetWindowTextLengthW(hwnd)
            buffer = ctypes.create_unicode_buffer(length + 1)
            user32.GetWindowTextW(hwnd, buffer, length + 1)
            matches.append((int(hwnd), buffer.value))
            return True

        user32.EnumWindows(WNDENUMPROC(enum_proc), 0)
        if not matches:
            return None
        if title:
            for hwnd, window_title in matches:
                if window_title == title:
                    return hwnd
        return matches[0][0]
    except Exception:
        return None


def resolve_native_dialog_parent(owner_hwnd=None):
    """Capture the WinUx top-level that owns a newly-created dialog.

    This is intentionally a *construction-time* decision.  A QDialog keeps
    the parent passed to it; it does not silently adopt whichever sibling
    happens to become foreground later.  Re-resolving the foreground HWND on
    every ``show()`` made WinUx dialogs appear to drift between the main
    window, Transfer Center, and other native dialogs.
    """
    owner_hwnd = int(owner_hwnd or find_process_window("WinUX") or 0)
    if os.name != "nt" or not owner_hwnd:
        return owner_hwnd or None
    try:
        user32 = ctypes.windll.user32
        kernel32 = ctypes.windll.kernel32
        user32.GetForegroundWindow.argtypes = []
        user32.GetForegroundWindow.restype = wintypes.HWND
        user32.GetWindow.argtypes = [wintypes.HWND, ctypes.c_uint]
        user32.GetWindow.restype = wintypes.HWND
        user32.GetWindowThreadProcessId.argtypes = [
            wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
        user32.GetWindowThreadProcessId.restype = wintypes.DWORD
        kernel32.GetCurrentProcessId.argtypes = []
        kernel32.GetCurrentProcessId.restype = wintypes.DWORD

        foreground = int(user32.GetForegroundWindow() or 0)
        if not foreground:
            return owner_hwnd
        pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(
            wintypes.HWND(foreground), ctypes.byref(pid))
        if int(pid.value) != int(kernel32.GetCurrentProcessId()):
            return owner_hwnd
        if foreground == owner_hwnd:
            return owner_hwnd

        # Only accept a top-level whose owner chain reaches the WinUx main
        # window. This excludes unrelated same-process windows from Abaqus or
        # helper toolkits while still supporting nested QDialog-like dialogs.
        current = foreground
        seen = set()
        for _ in range(16):
            if not current or current in seen:
                break
            seen.add(current)
            parent = int(user32.GetWindow(
                wintypes.HWND(current), GW_OWNER) or 0)
            if parent == owner_hwnd:
                return foreground
            current = parent
        return owner_hwnd
    except Exception:
        return owner_hwnd


def _is_native_window(hwnd):
    """Return whether *hwnd* is still a live Win32 window."""
    if os.name != "nt" or not hwnd:
        return False
    try:
        user32 = ctypes.windll.user32
        user32.IsWindow.argtypes = [wintypes.HWND]
        user32.IsWindow.restype = wintypes.BOOL
        return bool(user32.IsWindow(wintypes.HWND(int(hwnd))))
    except Exception:
        return False


def _tk_root_hwnd(window):
    if os.name != "nt":
        return None
    try:
        user32 = ctypes.windll.user32
        user32.GetAncestor.argtypes = [wintypes.HWND, wintypes.UINT]
        user32.GetAncestor.restype = wintypes.HWND
        hwnd = int(window.winfo_id())
        root = user32.GetAncestor(wintypes.HWND(hwnd), GA_ROOT)
        return int(root or hwnd)
    except Exception:
        return None


def _colorref(rgb):
    """Return a Win32 COLORREF from an RGB tuple."""
    r, g, b = [max(0, min(255, int(v))) for v in rgb[:3]]
    return r | (g << 8) | (b << 16)


def apply_native_qt_chrome(
        window, window_role="dialog", allow_minimize=None, allow_maximize=None):
    """Give one Tk ``Toplevel`` Qt/QWidget-like native Windows chrome.

    ``window_role`` mirrors the useful part of Qt's top-level flags:
    ``dialog`` keeps standard QDialog chrome, while ``tool`` produces an owned
    palette/tool window that stays out of the taskbar and has no independent
    minimize/maximize actions.  The window always remains a real top-level
    HWND, never a child clipped to the Dear PyGui viewport.

    On Windows 11 we also request rounded corners and restrained Fusion-like
    caption/border colours.  Older Windows versions simply ignore unsupported
    DWM attributes.
    """
    if os.name != "nt" or window is None:
        return None
    try:
        window.update_idletasks()
        dialog_hwnd = int(_tk_root_hwnd(window) or 0)
        if not dialog_hwnd:
            return None

        user32 = ctypes.windll.user32
        dwmapi = ctypes.windll.dwmapi
        hwnd = wintypes.HWND(dialog_hwnd)

        # A Tk Toplevel should already be an overlapped top-level window, but
        # clear WS_CHILD defensively.  This guarantees the dialog is never
        # clipped to the Dear PyGui/GLFW client rectangle.
        getter = (
            user32.GetWindowLongPtrW
            if ctypes.sizeof(ctypes.c_void_p) == 8
            else user32.GetWindowLongW
        )
        setter = (
            user32.SetWindowLongPtrW
            if ctypes.sizeof(ctypes.c_void_p) == 8
            else user32.SetWindowLongW
        )
        getter.argtypes = [wintypes.HWND, ctypes.c_int]
        getter.restype = ctypes.c_ssize_t
        setter.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_ssize_t]
        setter.restype = ctypes.c_ssize_t
        style = int(getter(hwnd, GWL_STYLE))
        desired = (style & ~WS_CHILD) | WS_CAPTION | WS_SYSMENU
        role = str(window_role or "dialog").strip().lower()
        if role not in ("dialog", "tool", "window"):
            role = "dialog"

        try:
            horizontal, vertical = window.resizable()
            native_resizable = bool(horizontal or vertical)
        except Exception:
            native_resizable = True

        # QDialog-like defaults: no minimize button; a resizable dialog can
        # maximize. ``window`` is available for future standalone top-levels.
        if allow_minimize is None:
            allow_minimize = role == "window"
        if allow_maximize is None:
            allow_maximize = native_resizable and role != "tool"
        allow_minimize = bool(allow_minimize) and role != "tool"
        allow_maximize = bool(allow_maximize) and native_resizable and role != "tool"

        if native_resizable:
            desired |= WS_THICKFRAME
        else:
            desired &= ~WS_THICKFRAME
        if allow_minimize:
            desired |= WS_MINIMIZEBOX
        else:
            desired &= ~WS_MINIMIZEBOX
        if allow_maximize:
            desired |= WS_MAXIMIZEBOX
        else:
            desired &= ~WS_MAXIMIZEBOX

        # Qt::Tool windows are owned palette windows: no taskbar button and no
        # independent app identity.  For ordinary dialogs/windows preserve Tk's
        # extended style verbatim.  Tk may use WS_EX_TOOLWINDOW/other private
        # wrapper flags for a transient Toplevel; clearing those flags after the
        # HWND has been created can leave the wrapper visually mapped while its
        # client controls no longer receive mouse activation correctly.
        ex_style = int(getter(hwnd, GWL_EXSTYLE))
        desired_ex = ex_style
        if role == "tool":
            desired_ex = (desired_ex | WS_EX_TOOLWINDOW) & ~WS_EX_APPWINDOW
        elif role == "dialog" and bool(
                getattr(window, "_winux_force_normal_caption", False)):
            # GLFW can inherit a tool/app-window extended style depending on
            # how its hidden bootstrap viewport was created.  Normal dialogs
            # should never use the small tool-window caption; ownership keeps
            # them out of the taskbar, so clear both identity overrides and
            # let USER32 draw the standard Windows dialog caption/Close button.
            desired_ex &= ~(WS_EX_TOOLWINDOW | WS_EX_APPWINDOW)

        changed = False
        if desired != style:
            setter(hwnd, GWL_STYLE, desired)
            changed = True
        if desired_ex != ex_style:
            setter(hwnd, GWL_EXSTYLE, desired_ex)
            changed = True
        if changed:
            user32.SetWindowPos(
                hwnd, None, 0, 0, 0, 0,
                SWP_NOMOVE | SWP_NOSIZE | SWP_NOZORDER |
                SWP_NOACTIVATE | SWP_FRAMECHANGED,
            )

        def set_dwm(attr, value):
            try:
                value_obj = ctypes.c_int(int(value))
                return int(dwmapi.DwmSetWindowAttribute(
                    hwnd, int(attr), ctypes.byref(value_obj),
                    ctypes.sizeof(value_obj))) == 0
            except Exception:
                return False

        set_dwm(DWMWA_WINDOW_CORNER_PREFERENCE, DWMWCP_ROUND)
        set_dwm(DWMWA_BORDER_COLOR, _colorref((171, 171, 171)))
        set_dwm(DWMWA_CAPTION_COLOR, _colorref((240, 240, 240)))
        set_dwm(DWMWA_TEXT_COLOR, _colorref((32, 32, 32)))
        return dialog_hwnd
    except Exception:
        return None


def attach_native_owner(window, owner_hwnd=None):
    """Make a Tk top-level an owned WinUX window without making it a child."""
    if os.name != "nt":
        return None
    owner_hwnd = int(owner_hwnd or find_process_window() or 0)
    if not owner_hwnd:
        return None
    try:
        window.update_idletasks()
        dialog_hwnd = int(_tk_root_hwnd(window) or 0)
        if not dialog_hwnd:
            return None
        user32 = ctypes.windll.user32
        setter = (
            user32.SetWindowLongPtrW
            if ctypes.sizeof(ctypes.c_void_p) == 8
            else user32.SetWindowLongW
        )
        setter.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_void_p]
        setter.restype = ctypes.c_void_p
        setter(
            wintypes.HWND(dialog_hwnd),
            GWLP_HWNDPARENT,
            ctypes.c_void_p(owner_hwnd),
        )
        return owner_hwnd
    except Exception:
        return None


def ensure_native_dialog_interactive(window):
    """Ensure the dialog HWND itself remains enabled and accepts mouse input.

    WinUx implements window modality by disabling only the owner HWND.  Tk
    Toplevel wrappers must stay enabled.  Reassert that invariant after native
    owner/style changes because some embedded Tcl/Tk builds can mirror an
    owner's disabled activation state onto a transient wrapper.  This is the
    native equivalent of keeping a QDialog enabled while its parent is blocked.
    """
    if os.name != "nt" or window is None:
        return False
    try:
        hwnd = int(_tk_root_hwnd(window) or 0)
        if not hwnd:
            return False
        user32 = ctypes.windll.user32
        user32.IsWindowEnabled.argtypes = [wintypes.HWND]
        user32.IsWindowEnabled.restype = wintypes.BOOL
        user32.EnableWindow.argtypes = [wintypes.HWND, wintypes.BOOL]
        user32.EnableWindow.restype = wintypes.BOOL
        native = wintypes.HWND(hwnd)
        if not user32.IsWindowEnabled(native):
            user32.EnableWindow(native, True)
        return bool(user32.IsWindowEnabled(native))
    except Exception:
        return False


class _WindowPlacement(ctypes.Structure):
    _fields_ = [
        ("length", wintypes.UINT),
        ("flags", wintypes.UINT),
        ("showCmd", wintypes.UINT),
        ("ptMinPosition", wintypes.POINT),
        ("ptMaxPosition", wintypes.POINT),
        ("rcNormalPosition", wintypes.RECT),
    ]


def _native_window_placement(window):
    """Return the Win32 normal rectangle plus current top-level state.

    Tk's ``winfo_width``/``winfo_height`` describe the *maximized* rectangle
    while a window is zoomed. Qt's saveGeometry instead remembers the normal
    restore rectangle. ``GetWindowPlacement`` provides exactly that data.
    """
    if os.name != "nt" or window is None:
        return None
    try:
        hwnd = int(_tk_root_hwnd(window) or 0)
        if not hwnd:
            return None
        placement = _WindowPlacement()
        placement.length = ctypes.sizeof(placement)
        user32 = ctypes.windll.user32
        user32.GetWindowPlacement.argtypes = [
            wintypes.HWND, ctypes.POINTER(_WindowPlacement)]
        user32.GetWindowPlacement.restype = wintypes.BOOL
        if not user32.GetWindowPlacement(
                wintypes.HWND(hwnd), ctypes.byref(placement)):
            return None
        rect = placement.rcNormalPosition
        width = max(1, int(rect.right - rect.left))
        height = max(1, int(rect.bottom - rect.top))
        show_cmd = int(placement.showCmd)
        state = "zoomed" if show_cmd == SW_SHOWMAXIMIZED else "normal"
        return {
            "x": int(rect.left),
            "y": int(rect.top),
            "width": width,
            "height": height,
            "state": state,
            "show_cmd": show_cmd,
        }
    except Exception:
        return None


class _MonitorInfo(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.DWORD),
        ("rcMonitor", wintypes.RECT),
        ("rcWork", wintypes.RECT),
        ("dwFlags", wintypes.DWORD),
    ]


def _monitor_work_area(window=None, owner_hwnd=None, point=None):
    """Return the nearest monitor work area as ``(l, t, r, b)``.

    Saved dialog positions can outlive a docking station or second monitor.
    Qt restores those windows onto a valid screen; do the same here rather
    than reopening a dialog entirely off-screen.
    """
    if os.name == "nt":
        try:
            user32 = ctypes.windll.user32
            monitor = None
            if point is not None:
                px, py = map(int, point)
                user32.MonitorFromPoint.argtypes = [wintypes.POINT, wintypes.DWORD]
                user32.MonitorFromPoint.restype = wintypes.HANDLE
                monitor = user32.MonitorFromPoint(
                    wintypes.POINT(px, py), MONITOR_DEFAULTTONEAREST)
            if not monitor and owner_hwnd:
                user32.MonitorFromWindow.argtypes = [wintypes.HWND, wintypes.DWORD]
                user32.MonitorFromWindow.restype = wintypes.HANDLE
                monitor = user32.MonitorFromWindow(
                    wintypes.HWND(int(owner_hwnd)), MONITOR_DEFAULTTONEAREST)
            if not monitor and window is not None:
                hwnd = int(_tk_root_hwnd(window) or 0)
                if hwnd:
                    user32.MonitorFromWindow.argtypes = [wintypes.HWND, wintypes.DWORD]
                    user32.MonitorFromWindow.restype = wintypes.HANDLE
                    monitor = user32.MonitorFromWindow(
                        wintypes.HWND(hwnd), MONITOR_DEFAULTTONEAREST)
            if monitor:
                info = _MonitorInfo()
                info.cbSize = ctypes.sizeof(info)
                user32.GetMonitorInfoW.argtypes = [
                    wintypes.HANDLE, ctypes.POINTER(_MonitorInfo)]
                user32.GetMonitorInfoW.restype = wintypes.BOOL
                if user32.GetMonitorInfoW(monitor, ctypes.byref(info)):
                    work = info.rcWork
                    return (
                        int(work.left), int(work.top),
                        int(work.right), int(work.bottom),
                    )
        except Exception:
            pass
    try:
        width = int(window.winfo_screenwidth()) if window is not None else 1280
        height = int(window.winfo_screenheight()) if window is not None else 720
    except Exception:
        width, height = 1280, 720
    return (0, 0, max(1, width), max(1, height))


def _window_resizable(window):
    try:
        horizontal, vertical = window.resizable()
        return bool(horizontal), bool(vertical)
    except Exception:
        return True, True


def _window_minsize(window):
    try:
        width, height = window.minsize()
        return max(1, int(width)), max(1, int(height))
    except Exception:
        return 1, 1


def _fit_dialog_content_minimum(window, work_area):
    """Honor Tk's layout size hint without requiring a window larger than the screen."""
    window.update_idletasks()
    min_width, min_height = _window_minsize(window)
    available_width = max(1, int(work_area[2]) - int(work_area[0])
                          - 2 * DIALOG_GEOMETRY_MARGIN)
    available_height = max(1, int(work_area[3]) - int(work_area[1])
                           - 2 * DIALOG_GEOMETRY_MARGIN)
    width = min(available_width, max(min_width, int(window.winfo_reqwidth())))
    height = min(available_height, max(min_height, int(window.winfo_reqheight())))
    if (width, height) != (min_width, min_height):
        window.minsize(width, height)
    return width, height


def resize_native_dialog_to_minimum(window, owner_hwnd=None):
    """Resize *window* to its smallest content-safe launch rectangle.

    A Qt ``QDialog`` opened with ``adjustSize()`` starts at its size hint (while
    still respecting ``minimumSize``) instead of inheriting an arbitrary old
    user resize.  WinUx dialogs use the same rule: the effective minimum is the
    larger of the dialog's declared ``minsize`` and Tk's requested layout size.
    The rectangle is clamped to the owner's monitor so a high-DPI layout can
    never open partly off-screen.  Position is intentionally left for the
    parent-centering pass that follows.
    """
    if window is None:
        return None
    try:
        window.update_idletasks()
        work_area = _monitor_work_area(window, owner_hwnd=owner_hwnd)
        width, height = _fit_dialog_content_minimum(window, work_area)
        x = int(window.winfo_x())
        y = int(window.winfo_y())
        x, y, width, height = _clamp_dialog_geometry(
            x, y, width, height, work_area, (width, height))
        window.geometry("{}x{}+{}+{}".format(width, height, x, y))
        window.update_idletasks()
        return width, height
    except Exception:
        return None


def _clamp_dialog_geometry(x, y, width, height, work_area, min_size=(1, 1)):
    """Clamp one client rectangle to a monitor's usable work area."""
    left, top, right, bottom = map(int, work_area)
    margin = DIALOG_GEOMETRY_MARGIN
    min_width, min_height = map(int, min_size)
    available_width = max(1, right - left - 2 * margin)
    available_height = max(1, bottom - top - 2 * margin)
    effective_min_width = min(max(1, min_width), available_width)
    effective_min_height = min(max(1, min_height), available_height)
    width = max(effective_min_width, min(int(width), available_width))
    height = max(effective_min_height, min(int(height), available_height))
    min_x = left + margin
    max_x = max(min_x, right - margin - width)
    min_y = top + margin
    max_y = max(min_y, bottom - margin - height)
    x = min(max(int(x), min_x), max_x)
    y = min(max(int(y), min_y), max_y)
    return x, y, width, height


def restore_native_dialog_geometry(
        window, geometry_key, owner_hwnd=None, preferences=None,
        restore_position=True, restore_state=True):
    """Restore a native dialog like ``QWidget::restoreGeometry``.

    Fixed-size dialogs remember only their position. Resizable dialogs also
    remember their normal width/height. ``restore_position=False`` restores
    only the remembered size so callers can deliberately center the dialog over
    its current parent. If the remembered monitor is gone, any restored
    rectangle is moved onto the nearest current monitor work area.
    """
    if window is None:
        return None
    preferences = preferences or DialogGeometryPreferences()
    saved = preferences.load(geometry_key) if geometry_key else None
    try:
        window.update_idletasks()
        current_x = int(window.winfo_x())
        current_y = int(window.winfo_y())
        current_width = max(1, int(window.winfo_width()))
        current_height = max(1, int(window.winfo_height()))
    except Exception:
        return None

    horizontal, vertical = _window_resizable(window)
    if saved:
        width = int(saved["width"]) if horizontal else current_width
        height = int(saved["height"]) if vertical else current_height
        if restore_position:
            x = int(saved["x"])
            y = int(saved["y"])
            monitor_point = (
                x + max(1, width) // 2,
                y + max(1, height) // 2,
            )
            work_area = _monitor_work_area(
                window, owner_hwnd=owner_hwnd, point=monitor_point)
        else:
            x, y = current_x, current_y
            work_area = _monitor_work_area(window, owner_hwnd=owner_hwnd)
    else:
        x, y = current_x, current_y
        width, height = current_width, current_height
        work_area = _monitor_work_area(window, owner_hwnd=owner_hwnd)

    min_width, min_height = _fit_dialog_content_minimum(window, work_area)
    x, y, width, height = _clamp_dialog_geometry(
        x, y, width, height, work_area, (min_width, min_height))
    try:
        window.geometry("{}x{}+{}+{}".format(width, height, x, y))
        window.update_idletasks()
    except Exception:
        return None

    if (restore_state and saved and saved.get("state") == "zoomed"
            and horizontal and vertical):
        try:
            window.after_idle(lambda: window.state("zoomed"))
        except Exception:
            pass
    return {
        "x": x, "y": y, "width": width, "height": height,
        "state": str((saved or {}).get("state") or "normal"),
    }


def save_native_dialog_geometry(
        window, geometry_key, preferences=None):
    """Persist the current native dialog rectangle."""
    if window is None or not geometry_key:
        return False
    preferences = preferences or DialogGeometryPreferences()
    try:
        window.update_idletasks()
        state = str(window.state() or "normal").lower()
        # Never overwrite a useful normal/maximized placement with the
        # transient iconified state. This matches QWidget::saveGeometry.
        if state == "iconic":
            return False

        placement = _native_window_placement(window)
        if placement is not None:
            geometry = {
                "x": int(placement["x"]),
                "y": int(placement["y"]),
                "width": max(1, int(placement["width"])),
                "height": max(1, int(placement["height"])),
                "state": str(placement.get("state") or "normal"),
            }
        else:
            geometry = {
                "x": int(window.winfo_x()),
                "y": int(window.winfo_y()),
                "width": max(1, int(window.winfo_width())),
                "height": max(1, int(window.winfo_height())),
                "state": "zoomed" if state == "zoomed" else "normal",
            }
        return bool(preferences.save(geometry_key, geometry))
    except Exception:
        return False


def center_native_dialog_over_owner(window, owner_hwnd=None):
    """Center a mapped native dialog over its fixed owner HWND.

    Tk ``geometry()`` positions the client area, while Qt/Win32 top-level
    placement is based on the complete native frame.  After a Toplevel is
    mapped Windows can add its caption/border metrics, so centering only before
    mapping leaves a visible offset that changes with DPI.  This helper uses
    the final HWND rectangles and moves the frame with ``SetWindowPos``.

    The owner is never re-selected from the foreground window here.  That
    stable parent relationship is the key QDialog behaviour WinUx requires.
    """
    if window is None:
        return False
    owner_hwnd = int(owner_hwnd or find_process_window("WinUX") or 0)
    if os.name != "nt" or not owner_hwnd:
        return False
    try:
        window.update_idletasks()
        dialog_hwnd = int(_tk_root_hwnd(window) or 0)
        if not dialog_hwnd or dialog_hwnd == owner_hwnd:
            return False
        user32 = ctypes.windll.user32
        user32.GetWindowRect.argtypes = [
            wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
        user32.GetWindowRect.restype = wintypes.BOOL
        user32.SetWindowPos.argtypes = [
            wintypes.HWND, wintypes.HWND, ctypes.c_int, ctypes.c_int,
            ctypes.c_int, ctypes.c_int, wintypes.UINT]
        user32.SetWindowPos.restype = wintypes.BOOL

        owner_rect = wintypes.RECT()
        dialog_rect = wintypes.RECT()
        if not user32.GetWindowRect(
                wintypes.HWND(owner_hwnd), ctypes.byref(owner_rect)):
            return False
        if not user32.GetWindowRect(
                wintypes.HWND(dialog_hwnd), ctypes.byref(dialog_rect)):
            return False

        width = max(1, int(dialog_rect.right - dialog_rect.left))
        height = max(1, int(dialog_rect.bottom - dialog_rect.top))
        x = int(owner_rect.left +
                ((owner_rect.right - owner_rect.left - width) // 2))
        y = int(owner_rect.top +
                ((owner_rect.bottom - owner_rect.top - height) // 2))
        work_area = _monitor_work_area(window, owner_hwnd=owner_hwnd)
        x, y, _width, _height = _clamp_dialog_geometry(
            x, y, width, height, work_area, (1, 1))
        return bool(user32.SetWindowPos(
            wintypes.HWND(dialog_hwnd), None, x, y, 0, 0,
            SWP_NOSIZE | SWP_NOZORDER | SWP_NOACTIVATE))
    except Exception:
        return False


def center_over_owner(window, width, height, owner_hwnd=None):
    """Center a top-level over WinUX and keep it on the owner's monitor."""
    window.update_idletasks()
    width = max(220, int(width))
    height = max(120, int(height))
    owner_hwnd = int(owner_hwnd or find_process_window() or 0)
    x = y = None
    if os.name == "nt" and owner_hwnd:
        try:
            rect = wintypes.RECT()
            user32 = ctypes.windll.user32
            user32.GetWindowRect.argtypes = [
                wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
            user32.GetWindowRect.restype = wintypes.BOOL
            if user32.GetWindowRect(
                    wintypes.HWND(owner_hwnd), ctypes.byref(rect)):
                x = rect.left + max(0, (rect.right - rect.left - width) // 2)
                y = rect.top + max(0, (rect.bottom - rect.top - height) // 2)
        except Exception:
            x = y = None
    if x is None or y is None:
        try:
            x = (window.winfo_screenwidth() - width) // 2
            y = (window.winfo_screenheight() - height) // 2
        except Exception:
            x, y = 40, 40
    work_area = _monitor_work_area(window, owner_hwnd=owner_hwnd)
    min_size = _fit_dialog_content_minimum(window, work_area)
    x, y, width, height = _clamp_dialog_geometry(
        x, y, width, height, work_area, min_size)
    window.geometry("{}x{}+{}+{}".format(width, height, x, y))


def _restore_owner_only_if_minimized(user32, owner_hwnd):
    """Restore *owner_hwnd* only when Windows reports it as minimized.

    ``SW_RESTORE`` is not a harmless focus operation: when used against a
    maximized GLFW/Dear PyGui top-level it restores the window to its saved
    normal rectangle.  That made WinUx jump back to its original size every
    time a native dialog closed.  Preserve normal/maximized placement and use
    ``SW_RESTORE`` exclusively for an actually iconic window.
    """
    try:
        user32.IsIconic.argtypes = [wintypes.HWND]
        user32.IsIconic.restype = wintypes.BOOL
        user32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
        user32.ShowWindow.restype = wintypes.BOOL
        hwnd = wintypes.HWND(int(owner_hwnd))
        if user32.IsIconic(hwnd):
            user32.ShowWindow(hwnd, SW_RESTORE)
            return True
    except Exception:
        pass
    return False


def set_owner_enabled(owner_hwnd, enabled):
    """Enable/disable the native owner without changing its placement/state."""
    if os.name != "nt" or not owner_hwnd:
        return
    try:
        user32 = ctypes.windll.user32
        user32.EnableWindow.argtypes = [wintypes.HWND, wintypes.BOOL]
        user32.EnableWindow.restype = wintypes.BOOL
        user32.EnableWindow(
            wintypes.HWND(int(owner_hwnd)), bool(enabled))
        if enabled:
            _restore_owner_only_if_minimized(user32, owner_hwnd)
    except Exception:
        pass


def ensure_owner_visible(owner_hwnd):
    """Reveal a live WinUx owner only when it became unexpectedly hidden.

    This helper is deliberately separate from :func:`restore_owner_focus`.
    Generic dialog teardown must never re-show a deliberately hidden window;
    explicit modal workflows such as a successful Login opt into this recovery
    path only when the dialog still owned the user's foreground focus.
    """
    if os.name != "nt" or not owner_hwnd:
        return False
    try:
        owner_hwnd = int(owner_hwnd)
        user32 = ctypes.windll.user32
        hwnd = wintypes.HWND(owner_hwnd)
        user32.IsWindow.argtypes = [wintypes.HWND]
        user32.IsWindow.restype = wintypes.BOOL
        user32.IsWindowVisible.argtypes = [wintypes.HWND]
        user32.IsWindowVisible.restype = wintypes.BOOL
        user32.IsIconic.argtypes = [wintypes.HWND]
        user32.IsIconic.restype = wintypes.BOOL
        user32.IsZoomed.argtypes = [wintypes.HWND]
        user32.IsZoomed.restype = wintypes.BOOL
        user32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
        user32.ShowWindow.restype = wintypes.BOOL
        if not user32.IsWindow(hwnd):
            return False
        if user32.IsWindowVisible(hwnd):
            return True
        # Preserve the owner's prior native state instead of always restoring
        # to a normal rectangle. SW_SHOWNOACTIVATE avoids an intermediate
        # activation; the deferred focus policy activates exactly once later.
        if user32.IsZoomed(hwnd):
            command = SW_SHOWMAXIMIZED
        elif user32.IsIconic(hwnd):
            command = SW_RESTORE
        else:
            command = 4  # SW_SHOWNOACTIVATE
        user32.ShowWindow(hwnd, command)
        return bool(user32.IsWindowVisible(hwnd))
    except Exception:
        return False


def _restore_owner_activation(owner_hwnd, raise_z_order=False):
    """Activate *owner_hwnd* while preserving placement and visibility.

    ``raise_z_order`` is reserved for a genuine dialog-to-owner hand-off: the
    dialog must have owned the foreground immediately before it disappeared.
    In that case Windows is expected to return the owner to the same desktop
    Z-order slot.  A transient ``BringWindowToTop`` repairs the cases where
    GLFW/Win32 instead leaves WinUx behind another application.  It never marks
    the window TOPMOST and never changes its size, position or show state.
    """
    if os.name != "nt" or not owner_hwnd:
        return False
    owner_hwnd = int(owner_hwnd)
    attached = []
    try:
        user32 = ctypes.windll.user32
        kernel32 = ctypes.windll.kernel32

        user32.IsWindow.argtypes = [wintypes.HWND]
        user32.IsWindow.restype = wintypes.BOOL
        if not user32.IsWindow(wintypes.HWND(owner_hwnd)):
            return False

        user32.IsWindowVisible.argtypes = [wintypes.HWND]
        user32.IsWindowVisible.restype = wintypes.BOOL
        if not user32.IsWindowVisible(wintypes.HWND(owner_hwnd)):
            # Activation must never turn a deliberately hidden viewport back on.
            return False

        user32.GetForegroundWindow.argtypes = []
        user32.GetForegroundWindow.restype = wintypes.HWND
        user32.GetWindowThreadProcessId.argtypes = [
            wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
        user32.GetWindowThreadProcessId.restype = wintypes.DWORD
        user32.AttachThreadInput.argtypes = [
            wintypes.DWORD, wintypes.DWORD, wintypes.BOOL]
        user32.AttachThreadInput.restype = wintypes.BOOL
        user32.BringWindowToTop.argtypes = [wintypes.HWND]
        user32.BringWindowToTop.restype = wintypes.BOOL
        user32.SetForegroundWindow.argtypes = [wintypes.HWND]
        user32.SetForegroundWindow.restype = wintypes.BOOL
        user32.SetActiveWindow.argtypes = [wintypes.HWND]
        user32.SetActiveWindow.restype = wintypes.HWND
        user32.SetFocus.argtypes = [wintypes.HWND]
        user32.SetFocus.restype = wintypes.HWND
        kernel32.GetCurrentThreadId.argtypes = []
        kernel32.GetCurrentThreadId.restype = wintypes.DWORD

        current_tid = int(kernel32.GetCurrentThreadId())
        owner_tid = int(user32.GetWindowThreadProcessId(
            wintypes.HWND(owner_hwnd), None))
        foreground = int(user32.GetForegroundWindow() or 0)
        foreground_tid = int(user32.GetWindowThreadProcessId(
            wintypes.HWND(foreground), None)) if foreground else 0

        for target_tid in (owner_tid, foreground_tid):
            if (target_tid and target_tid != current_tid and
                    target_tid not in attached):
                if user32.AttachThreadInput(
                        wintypes.DWORD(current_tid),
                        wintypes.DWORD(target_tid), True):
                    attached.append(target_tid)

        # Enabling/focusing must not alter the user's current window size or
        # maximized state. ``set_owner_enabled`` restores only a truly minimized
        # owner; normal and maximized windows remain untouched.
        set_owner_enabled(owner_hwnd, True)
        hwnd = wintypes.HWND(owner_hwnd)
        if raise_z_order:
            # This is deliberately *not* HWND_TOPMOST.  The raise is a one-shot
            # repair of the normal owned-dialog hand-off after the child HWND is
            # gone, so WinUx remains a normal desktop window afterwards.
            user32.BringWindowToTop(hwnd)
        user32.SetForegroundWindow(hwnd)
        user32.SetActiveWindow(hwnd)
        user32.SetFocus(hwnd)
        return int(user32.GetForegroundWindow() or 0) == owner_hwnd
    except Exception:
        return False
    finally:
        if os.name == "nt" and attached:
            try:
                user32 = ctypes.windll.user32
                kernel32 = ctypes.windll.kernel32
                current_tid = int(kernel32.GetCurrentThreadId())
                for target_tid in reversed(attached):
                    user32.AttachThreadInput(
                        wintypes.DWORD(current_tid),
                        wintypes.DWORD(target_tid), False)
            except Exception:
                pass


def handoff_owner_before_close(owner_hwnd, closing_hwnd=None):
    """Transfer foreground to an owner *before* its owned dialog disappears.

    This mirrors the close ordering used by native GUI frameworks.  The owned
    dialog is still visible while its owner becomes the foreground window, so
    Windows never needs to choose an unrelated desktop window for an
    intermediate frame.  Because an owned top-level remains above its owner,
    the visual dialog stays on top until the subsequent Hide/DestroyWindow.

    The hand-off is intentionally refused when another application already
    owns foreground; background/programmatic closes must not steal focus.
    """
    if os.name != "nt" or not owner_hwnd:
        return False
    try:
        owner_hwnd = int(owner_hwnd)
        closing_hwnd = int(closing_hwnd or 0)
        user32 = ctypes.windll.user32
        user32.GetForegroundWindow.argtypes = []
        user32.GetForegroundWindow.restype = wintypes.HWND
        current = int(user32.GetForegroundWindow() or 0)
        if current == owner_hwnd:
            return True
        if closing_hwnd and current != closing_hwnd:
            return False
        return _restore_owner_activation(owner_hwnd, raise_z_order=False)
    except Exception:
        return False


def restore_owner_focus(owner_hwnd):
    """Restore owner keyboard activation without intentionally raising Z-order."""
    return _restore_owner_activation(owner_hwnd, raise_z_order=False)


def restore_owner_foreground(owner_hwnd):
    """Return a foreground dialog's owner to the foreground/Z-order slot."""
    return _restore_owner_activation(owner_hwnd, raise_z_order=True)


def is_native_window_foreground(window):
    """Return True when *window* currently owns the Windows foreground slot."""
    if os.name != "nt":
        return False
    try:
        hwnd = int(_tk_root_hwnd(window) or 0)
        if not hwnd:
            return False
        user32 = ctypes.windll.user32
        user32.GetForegroundWindow.argtypes = []
        user32.GetForegroundWindow.restype = wintypes.HWND
        return int(user32.GetForegroundWindow() or 0) == hwnd
    except Exception:
        return False


def _acquire_modal_owner(owner_hwnd):
    """Disable an owner once even when native modal dialogs are nested."""
    if os.name != "nt" or not owner_hwnd:
        return False
    owner_hwnd = int(owner_hwnd)
    with _MODAL_OWNER_LOCK:
        count = int(_MODAL_OWNER_COUNTS.get(owner_hwnd, 0))
        _MODAL_OWNER_COUNTS[owner_hwnd] = count + 1
        if count == 0:
            set_owner_enabled(owner_hwnd, False)
    return True


def _release_modal_owner(owner_hwnd, restore_focus=True):
    """Balance ``_acquire_modal_owner`` and reactivate at count zero."""
    if os.name != "nt" or not owner_hwnd:
        return
    owner_hwnd = int(owner_hwnd)
    should_enable = False
    with _MODAL_OWNER_LOCK:
        count = int(_MODAL_OWNER_COUNTS.get(owner_hwnd, 0))
        if count <= 1:
            _MODAL_OWNER_COUNTS.pop(owner_hwnd, None)
            should_enable = True
        else:
            _MODAL_OWNER_COUNTS[owner_hwnd] = count - 1
    if should_enable:
        set_owner_enabled(owner_hwnd, True)
        if restore_focus:
            restore_owner_focus(owner_hwnd)


class _NativeTkHost:
    """One hidden Tk interpreter shared by every WinUX native dialog."""

    POLL_MS = 10

    def __init__(self):
        self._queue = queue.Queue()
        self._ready = threading.Event()
        self._stopped = threading.Event()
        self._thread_ident = None
        self.root = None
        # Destroyed Tk widgets can contain Python reference cycles.  If those
        # cycles are later collected by an arbitrary transfer/job worker,
        # tkinter may run Tcl finalizers on the wrong thread and abort the
        # embedded SMAPython process (Tcl_AsyncDelete).  Keep retired windows
        # reachable until the Tk thread explicitly reaps them.
        self._retired_windows = []
        self._thread = threading.Thread(
            target=self._thread_main,
            name="winux-native-ui",
            daemon=True,
        )
        self._thread.start()
        self._ready.wait(timeout=3.0)

    @property
    def alive(self):
        return bool(
            self._ready.is_set()
            and not self._stopped.is_set()
            and self.root is not None
        )

    def _thread_main(self):
        root = None
        try:
            import tkinter as tk

            root = tk.Tk(className="WinUxNativeHost")
            root.withdraw()
            self.root = root
            self._thread_ident = threading.get_ident()
            self._ready.set()

            def drain():
                if self._stopped.is_set():
                    try:
                        root.quit()
                    except Exception:
                        pass
                    return
                while True:
                    try:
                        callback, args = self._queue.get_nowait()
                    except queue.Empty:
                        break
                    try:
                        callback(*args)
                    except Exception:
                        # Native UI errors must never terminate the embedded
                        # Abaqus/WinUX process. Controllers surface their own
                        # error state where appropriate.
                        pass
                try:
                    root.after(self.POLL_MS, drain)
                except Exception:
                    self._stopped.set()

            root.after(self.POLL_MS, drain)
            root.mainloop()
        except Exception:
            self._ready.set()
        finally:
            self._stopped.set()
            self.root = None
            self._thread_ident = None
            if root is not None:
                try:
                    root.destroy()
                except Exception:
                    pass

    def _retire_window(self, window):
        if window is None:
            return
        self._retired_windows.append(window)
        root = self.root
        if root is not None:
            try:
                root.after(250, self._reap_retired_windows)
            except Exception:
                pass

    def _reap_retired_windows(self):
        if not self._retired_windows:
            return
        retired, self._retired_windows = self._retired_windows, []
        # Ensure cyclic Tk widget finalizers execute on the Tk owner thread.
        was_enabled = gc.isenabled()
        try:
            if was_enabled:
                gc.disable()
            for window in retired:
                try:
                    # Break the most common controller/window cycle after the
                    # native HWND has already been destroyed.
                    if hasattr(window, "owner"):
                        window.owner = None
                    if hasattr(window, "_owner"):
                        window._owner = None
                except Exception:
                    pass
            retired.clear()
            gc.collect()
        finally:
            if was_enabled:
                gc.enable()

    def submit(self, callback, *args):
        if not callable(callback) or self._stopped.is_set():
            return False
        if threading.get_ident() == self._thread_ident:
            try:
                callback(*args)
            except Exception:
                pass
            return True
        self._queue.put((callback, args))
        return True


def _native_tk_host():
    global _NATIVE_TK_HOST
    with _NATIVE_TK_HOST_LOCK:
        if _NATIVE_TK_HOST is None or not _NATIVE_TK_HOST.alive:
            _NATIVE_TK_HOST = _NativeTkHost()
        return _NATIVE_TK_HOST


class NativeDialogController:
    """Own one native ``Toplevel`` on the shared WinUX Tk UI thread.

    Native dialog geometry is persisted centrally, mirroring Qt's
    ``saveGeometry``/``restoreGeometry`` contract. Subclasses can opt out by
    setting ``PERSIST_GEOMETRY = False`` or override ``DIALOG_GEOMETRY_KEY``
    when several controller classes intentionally share one geometry profile.
    """

    PERSIST_GEOMETRY = True
    DIALOG_GEOMETRY_KEY = None
    # Match QDialog/QWidget launch behaviour: a newly shown dialog is centered
    # over the window that launched it. Geometry persistence therefore keeps
    # useful size information while the position is deliberately recomputed.
    CENTER_ON_PARENT = True
    CENTER_ON_SHOW = True
    # Open like QDialog::adjustSize(): use the smallest content-safe size, then
    # center that final native frame over the captured parent.  Old persisted
    # resize data must not make a newly opened dialog appear oversized/off-center.
    OPEN_AT_MINIMUM_SIZE = True
    # Qt-style top-level role. ``tool`` maps to a palette/tool HWND, while
    # ``dialog`` remains the default owned QDialog-like window.
    WINDOW_ROLE = "dialog"
    ALLOW_MINIMIZE = None
    ALLOW_MAXIMIZE = None
    PERSIST_WINDOW_STATE = True

    def __init__(self, view, thread_name=None, modal=False):
        # ``thread_name`` remains accepted for source compatibility.  Native
        # dialogs no longer create per-dialog threads; all of them share the
        # single winux-native-ui thread above.
        del thread_name
        self.view = view
        self.modal = bool(modal)
        self._closed = threading.Event()
        self._ready = threading.Event()
        self._owner_hwnd = find_process_window("WinUX")
        self._parent_hwnd = resolve_native_dialog_parent(self._owner_hwnd)
        self._window = None
        self._modal_owner_hwnd = None
        self._owner_acquired = False
        self._native_input_hwnd = None
        self._native_modal_input_acquired = False
        self._finalized = False
        self._return_foreground_on_finalize = False
        # Monotonic token used to invalidate stale deferred owner-focus repairs.
        # A newly shown dialog increments this token before it can become visible.
        self._owner_focus_generation = 0
        self._geometry_after_id = None
        self._geometry_preferences = DialogGeometryPreferences()
        explicit_geometry_key = getattr(self, "DIALOG_GEOMETRY_KEY", None)
        self._geometry_key = str(
            explicit_geometry_key
            or "{}.{}".format(self.__class__.__module__, self.__class__.__name__)
        )
        self._host = _native_tk_host()
        if not self._host.submit(self._host_create_window):
            self._closed.set()
            self._ready.set()

    @property
    def native_master(self):
        return self._host.root

    def _create_window(self):
        raise NotImplementedError

    def _refresh_parent_for_show(self, window):
        """Validate, but never dynamically replace, the dialog's Qt parent.

        The logical parent is captured once in ``__init__``.  Foreground-window
        based re-parenting is deliberately forbidden because focus can move
        between WinUx-owned top-levels while a command is being dispatched.
        If the original parent was destroyed, fall back to the main WinUx HWND.
        """
        if window is None or self._owner_acquired:
            return self._parent_hwnd
        parent = self._parent_hwnd
        if parent and _is_native_window(parent):
            return parent
        fallback = int(self._owner_hwnd or find_process_window("WinUX") or 0) or None
        if fallback != self._parent_hwnd:
            self._parent_hwnd = fallback
            if fallback:
                try:
                    attach_native_owner(window, fallback)
                except Exception:
                    pass
        return self._parent_hwnd

    def _set_modal_owner_active(self, active):
        """Acquire/release window modality in lock-step with visibility."""
        if not self.modal:
            return False
        active = bool(active)
        if active:
            if self._owner_acquired:
                return True
            owner_hwnd = int(self._parent_hwnd or self._owner_hwnd or 0)
            if not owner_hwnd:
                return False
            self._modal_owner_hwnd = owner_hwnd
            self._owner_acquired = _acquire_modal_owner(owner_hwnd)
            return bool(self._owner_acquired)
        if not self._owner_acquired:
            return False
        owner_hwnd = self._modal_owner_hwnd
        self._owner_acquired = False
        _release_modal_owner(owner_hwnd, restore_focus=False)
        return True

    def _register_native_input_surface(self, window):
        """Expose this real top-level HWND to the DPG input-isolation gate."""
        try:
            hwnd = int(_tk_root_hwnd(window) or 0)
        except Exception:
            hwnd = 0
        if not hwnd:
            return False
        try:
            from ..components.interaction_gate import register_native_pointer_surface
            register_native_pointer_surface(hwnd)
            self._native_input_hwnd = hwnd
            return True
        except Exception:
            return False

    def _unregister_native_input_surface(self):
        hwnd = getattr(self, "_native_input_hwnd", None)
        self._native_input_hwnd = None
        if not hwnd:
            return False
        try:
            from ..components.interaction_gate import unregister_native_pointer_surface
            unregister_native_pointer_surface(hwnd)
            return True
        except Exception:
            return False

    def _set_native_modal_input(self, active):
        """Mirror QDialog modality into Dear PyGui's global input dispatcher."""
        if not self.modal:
            return False
        active = bool(active)
        acquired = bool(getattr(self, "_native_modal_input_acquired", False))
        if active == acquired:
            return active
        try:
            from ..components.interaction_gate import (
                acquire_native_modal_input, release_native_modal_input,
            )
            if active:
                self._native_modal_input_acquired = bool(
                    acquire_native_modal_input(self))
            else:
                release_native_modal_input(self)
                self._native_modal_input_acquired = False
            return self._native_modal_input_acquired
        except Exception:
            if not active:
                self._native_modal_input_acquired = False
            return False

    @staticmethod
    def _window_focus_target(window):
        resolver = getattr(window, "qt_focus_target", None)
        if callable(resolver):
            try:
                return resolver()
            except Exception:
                return None
        return None

    def _focus_window_after_show(self, window, force=False):
        """Apply predictable QDialog-like activation after Tk has mapped it."""
        if window is None:
            return

        def apply_focus():
            if self._closed.is_set():
                return
            try:
                if force:
                    window.focus_force()
                else:
                    window.focus_set()
            except Exception:
                pass
            target = self._window_focus_target(window)
            if target is not None and target is not window:
                try:
                    target.focus_set()
                except Exception:
                    pass
            hook = getattr(window, "qt_after_focus", None)
            if callable(hook):
                try:
                    hook()
                except Exception:
                    pass

        try:
            window.after_idle(apply_focus)
        except Exception:
            apply_focus()

    def _handle_window_lifecycle(self, window, command):
        """Handle show/activate/focus/hide uniformly for every native dialog."""
        name = str(command or "").strip().lower()
        if name not in (
                "show", "activate", "focus", "hide",
                "minimize", "maximize", "restore", "toggle_maximize"):
            return False

        try:
            entry_state = str(window.state() or "normal").lower()
        except Exception:
            entry_state = "normal"

        if name in ("minimize", "maximize", "restore", "toggle_maximize"):
            try:
                current_state = str(window.state() or "normal").lower()
            except Exception:
                current_state = "normal"
            if name == "toggle_maximize":
                name = "restore" if current_state == "zoomed" else "maximize"
            if name == "minimize":
                # Persist the restore rectangle before the transient iconic
                # state appears; geometry tracking intentionally ignores iconic.
                self._save_geometry_now()
                try:
                    window.iconify()
                except Exception:
                    try:
                        window.state("iconic")
                    except Exception:
                        pass
                return True
            if name == "maximize":
                horizontal, vertical = _window_resizable(window)
                if not (horizontal and vertical):
                    return True
                try:
                    window.state("zoomed")
                except Exception:
                    pass
                self._schedule_geometry_save()
                return True
            # restore
            try:
                window.state("normal")
            except Exception:
                try:
                    window.deiconify()
                except Exception:
                    pass
            self._schedule_geometry_save()
            self._focus_window_after_show(window, force=True)
            return True

        if name == "hide":
            had_focus = is_native_window_foreground(window)
            owner_hwnd = int(self._parent_hwnd or self._owner_hwnd or 0)
            # Persist the normal restore rectangle/state before Tk changes the
            # window to ``withdrawn``. This makes hide/show behave like a
            # long-lived QWidget rather than resetting its native state.
            self._save_geometry_now()
            if self.modal:
                try:
                    window.grab_release()
                except Exception:
                    pass

            # When the dialog owns foreground, make the Win32 owner eligible
            # for activation *before* withdrawing the owned HWND.  If the owner
            # stays disabled until afterwards Windows has to choose another
            # foreground window first, which produces the visible one-frame
            # drop/raise flash.  The DPG modal-input gate intentionally remains
            # active until after withdraw, so no click-through is introduced.
            if had_focus and self.modal:
                self._set_modal_owner_active(False)
            if had_focus and owner_hwnd:
                handoff_owner_before_close(owner_hwnd, _tk_root_hwnd(window))
            try:
                window.withdraw()
            except Exception:
                pass
            if self.modal:
                if self._owner_acquired:
                    self._set_modal_owner_active(False)
                self._set_native_modal_input(False)
            hook = getattr(window, "qt_after_hide", None)
            if callable(hook):
                try:
                    hook()
                except Exception:
                    pass
            if had_focus and owner_hwnd:
                # Normal path is Win32's own atomic owned-window hand-off.
                # Only schedule the stronger Z-order repair if that hand-off
                # did not happen.
                try:
                    user32 = ctypes.windll.user32
                    user32.GetForegroundWindow.argtypes = []
                    user32.GetForegroundWindow.restype = wintypes.HWND
                    owner_is_foreground = int(user32.GetForegroundWindow() or 0) == owner_hwnd
                except Exception:
                    owner_is_foreground = False
                if not owner_is_foreground:
                    self.restore_owner_foreground_async()
            return True

        self._owner_focus_generation = int(
            getattr(self, "_owner_focus_generation", 0)) + 1
        self._refresh_parent_for_show(window)
        # Dear PyGui uses global handler registries and can still observe the
        # physical mouse while its HWND is disabled. Acquire the application
        # input gate as well as Win32 owner modality before mapping the dialog.
        self._set_native_modal_input(True)
        self._set_modal_owner_active(True)
        # The modal owner is disabled, never the dialog itself.  Keep this
        # explicit because embedded Tk/Win32 transient wrappers occasionally
        # inherit a disabled activation state after owner/style changes.
        ensure_native_dialog_interactive(window)
        # A dialog that is being shown from the withdrawn state always starts
        # from its minimum content-safe size.  Do this before mapping so the
        # first visible frame is already the correct size (no resize flash).
        if name == "show" or entry_state == "withdrawn":
            self._apply_minimum_launch_size(window)
        try:
            window.deiconify()
            window.update_idletasks()
        except Exception:
            pass
        # Recheck after mapping as well.  On some embedded Tk builds the native
        # wrapper receives its final enabled/activation state only at map time.
        ensure_native_dialog_interactive(window)
        try:
            window.lift()
        except Exception:
            pass
        # The native caption/border is final only after deiconify/map.  Center
        # again now (and once more on idle) so the visible frame is exactly
        # centered over its fixed Qt parent instead of drifting with DPI/chrome.
        if (self._center_on_parent_enabled()
                and bool(getattr(self, "CENTER_ON_SHOW", True))
                and (name == "show" or entry_state == "withdrawn")):
            self._center_window_on_parent(window)
            self._center_window_after_map(window)
        if self.modal:
            try:
                window.grab_set()
            except Exception:
                pass
        self._focus_window_after_show(
            window, force=name in ("activate", "focus"))
        hook = getattr(window, "qt_after_show", None)
        if callable(hook):
            try:
                hook(name)
            except Exception:
                pass
        return True

    def _handle_window_command(self, window, command, args, kwargs):
        if self._handle_window_lifecycle(window, command):
            return
        handler = getattr(window, "handle_command", None)
        if callable(handler):
            handler(command, *args, **kwargs)

    def _center_on_parent_enabled(self):
        return bool(getattr(self, "CENTER_ON_PARENT", True))

    def _open_at_minimum_size_enabled(self):
        return bool(getattr(self, "OPEN_AT_MINIMUM_SIZE", True))

    def _apply_minimum_launch_size(self, window=None):
        window = window or self._window
        if window is None or not self._open_at_minimum_size_enabled():
            return False
        parent = self._refresh_parent_for_show(window)
        return resize_native_dialog_to_minimum(window, parent) is not None

    def _center_window_on_parent(self, window=None):
        window = window or self._window
        if window is None or not self._center_on_parent_enabled():
            return False
        parent = self._refresh_parent_for_show(window)
        try:
            window.update_idletasks()
            # Prefer the mapped Win32 frame, which includes the final caption
            # and DPI-dependent border metrics.  Fall back to Tk geometry only
            # while the HWND is not ready yet.
            if center_native_dialog_over_owner(window, parent):
                window.update_idletasks()
                return True
            width = max(1, int(window.winfo_width()))
            height = max(1, int(window.winfo_height()))
            center_over_owner(
                window, width, height, owner_hwnd=parent)
            window.update_idletasks()
            return True
        except Exception:
            return False

    def _center_window_after_map(self, window):
        """Re-center once Windows has applied the final top-level frame."""
        if window is None or not self._center_on_parent_enabled():
            return
        try:
            window.after_idle(lambda: self._center_window_on_parent(window))
        except Exception:
            self._center_window_on_parent(window)

    def _persist_geometry_enabled(self):
        return bool(getattr(self, "PERSIST_GEOMETRY", True))

    def _persist_window_state_enabled(self):
        if not bool(getattr(self, "PERSIST_WINDOW_STATE", True)):
            return False
        role = str(getattr(self, "WINDOW_ROLE", "dialog") or "dialog").lower()
        if role == "tool":
            return False
        return getattr(self, "ALLOW_MAXIMIZE", None) is not False

    def _restore_geometry_for_show(self, window):
        if (not self._persist_geometry_enabled() or window is None
                or self._open_at_minimum_size_enabled()):
            return False
        restored = restore_native_dialog_geometry(
            window, self._geometry_key,
            owner_hwnd=(self._parent_hwnd or self._owner_hwnd),
            preferences=self._geometry_preferences,
            restore_position=not self._center_on_parent_enabled(),
            restore_state=self._persist_window_state_enabled(),
        )
        return restored is not None

    def _cancel_geometry_save(self):
        window = self._window
        after_id = self._geometry_after_id
        self._geometry_after_id = None
        if window is not None and after_id is not None:
            try:
                window.after_cancel(after_id)
            except Exception:
                pass

    def _save_geometry_now(self):
        self._geometry_after_id = None
        if not self._persist_geometry_enabled():
            return False
        window = getattr(self, "_window", None)
        if window is None:
            return False
        return save_native_dialog_geometry(
            window, self._geometry_key, self._geometry_preferences)

    def _schedule_geometry_save(self, _event=None):
        if not self._persist_geometry_enabled() or self._closed.is_set():
            return
        window = self._window
        if window is None:
            return
        self._cancel_geometry_save()
        try:
            self._geometry_after_id = window.after(
                DIALOG_GEOMETRY_SAVE_DELAY_MS, self._save_geometry_now)
        except Exception:
            self._geometry_after_id = None

    def _install_geometry_tracking(self, window):
        if not self._persist_geometry_enabled() or window is None:
            return
        try:
            window.bind("<Configure>", self._schedule_geometry_save, add="+")
        except Exception:
            pass

    def _host_create_window(self):
        if self._closed.is_set():
            self._ready.set()
            return
        try:
            window = self._create_window()
            self._window = window
            if window is None:
                self._finalize_window()
                return
            try:
                apply_tk_app_icon(window)
            except Exception:
                pass
            try:
                window.update_idletasks()
            except Exception:
                pass
            parent_hwnd = self._parent_hwnd or self._owner_hwnd
            owner = attach_native_owner(window, parent_hwnd)
            # Apply native Qt/QDialog-like chrome only after the final HWND and
            # owner relationship exist. The window remains a top-level owned
            # HWND and is never constrained to the Dear PyGui viewport.
            apply_native_qt_chrome(
                window,
                window_role=getattr(self, "WINDOW_ROLE", "dialog"),
                allow_minimize=getattr(self, "ALLOW_MINIMIZE", None),
                allow_maximize=getattr(self, "ALLOW_MAXIMIZE", None),
            )
            self._register_native_input_surface(window)
            ensure_native_dialog_interactive(window)
            if (self._persist_geometry_enabled()
                    and not self._open_at_minimum_size_enabled()):
                # Geometry restore remains available to specialist tool windows
                # that explicitly opt out of the default minimum-size launch
                # policy. Normal dialogs intentionally ignore old resize state.
                restore_native_dialog_geometry(
                    window, self._geometry_key,
                    owner_hwnd=(owner or parent_hwnd),
                    preferences=self._geometry_preferences,
                    restore_position=not self._center_on_parent_enabled(),
                    restore_state=self._persist_window_state_enabled(),
                )
            if self._open_at_minimum_size_enabled():
                self._apply_minimum_launch_size(window)
            if self._center_on_parent_enabled():
                self._center_window_on_parent(window)
            if self._persist_geometry_enabled():
                self._install_geometry_tracking(window)
            # Window modality follows visibility. ``show`` acquires the owner
            # and ``hide`` releases it, matching QDialog semantics and avoiding
            # a hidden modal window leaving WinUx disabled.
            self._ready.set()
        except Exception:
            self._finalize_window()

    def _host_command(self, command, args, kwargs):
        if self._closed.is_set():
            return
        window = self._window
        if window is None:
            return
        try:
            command_name = str(command or "").lower()
            try:
                state = str(window.state() or "").lower()
            except Exception:
                state = ""
            hidden_show = (
                command_name in ("show", "activate") and state == "withdrawn")
            if hidden_show:
                self._refresh_parent_for_show(window)
                # Specialist windows may opt back into persisted launch size.
                # Normal dialogs are resized to their content-safe minimum by
                # ``_handle_window_lifecycle`` immediately before mapping.
                self._restore_geometry_for_show(window)
            self._handle_window_command(window, command, args, kwargs)
        except Exception:
            pass

    def _host_destroy_window(self):
        if self._finalized:
            return
        window = self._window
        self._return_foreground_on_finalize = bool(
            window is not None and is_native_window_foreground(window))
        # As with hide(), a foreground owned dialog must not disappear while
        # its Win32 owner is still disabled.  Enable only the native owner here
        # and retain the DPG modal-input gate until _finalize_window(); Windows
        # can then transfer activation directly as DestroyWindow unwinds.
        if self._return_foreground_on_finalize and self._owner_acquired:
            self._set_modal_owner_active(False)
        if self._return_foreground_on_finalize and window is not None:
            handoff_owner_before_close(
                int(self._parent_hwnd or self._owner_hwnd or 0),
                _tk_root_hwnd(window),
            )
        if window is not None:
            self._cancel_geometry_save()
            if self._persist_geometry_enabled():
                self._save_geometry_now()
            try:
                window.destroy()
            except Exception:
                pass
            finally:
                self._unregister_native_input_surface()
                # Do not let a later network worker become the thread that
                # garbage-collects Tcl/Tk widget cycles.
                self._host._retire_window(window)
        self._finalize_window()

    def _finalize_window(self):
        if self._finalized:
            return
        self._finalized = True
        self._cancel_geometry_save()
        self._window = None
        self._unregister_native_input_surface()
        # Re-enable the native owner before reporting this dialog as closed,
        # and always release the companion Dear PyGui modal gate. Win32
        # EnableWindow alone is insufficient because DPG global handlers poll
        # physical mouse state even while their owner HWND is disabled.
        self._set_native_modal_input(False)
        if self._owner_acquired:
            self._set_modal_owner_active(False)
        # A foreground close normally hands activation back to an already
        # enabled owner atomically during native destruction.  Avoid a second
        # unconditional BringWindowToTop/SetForegroundWindow because that is
        # the visible flash fixed in 1.6.15.  Keep the strong restore only as a
        # bounded fallback when Windows did not perform the expected hand-off.
        if getattr(self, "_return_foreground_on_finalize", False):
            owner_hwnd = int(self._parent_hwnd or self._owner_hwnd or 0)
            owner_is_foreground = False
            if owner_hwnd and os.name == "nt":
                try:
                    user32 = ctypes.windll.user32
                    user32.GetForegroundWindow.argtypes = []
                    user32.GetForegroundWindow.restype = wintypes.HWND
                    owner_is_foreground = int(user32.GetForegroundWindow() or 0) == owner_hwnd
                except Exception:
                    pass
            if owner_hwnd and not owner_is_foreground:
                self.restore_owner_foreground_async()
        self._closed.set()
        self._ready.set()

    def post(self, command, *args, **kwargs):
        if self._closed.is_set():
            return False
        return self._host.submit(
            self._host_command, command, args, kwargs)

    def winfo_exists(self):
        return not self._closed.is_set()

    def show(self):
        # Acquire the DPG-side modal gate synchronously on the caller thread.
        # This prevents the remainder of the same Dear PyGui callback batch
        # from acting on widgets behind a dialog that has just been requested.
        self._set_native_modal_input(True)
        accepted = self.post("show")
        if not accepted:
            self._set_native_modal_input(False)
        return accepted

    def hide(self):
        return self.post("hide")

    def lift(self):
        self._set_native_modal_input(True)
        accepted = self.post("activate")
        if not accepted:
            self._set_native_modal_input(False)
        return accepted

    def minimize(self):
        return self.post("minimize")

    def maximize(self):
        return self.post("maximize")

    def restore(self):
        return self.post("restore")

    def toggle_maximize(self):
        return self.post("toggle_maximize")

    def _queue_owner_restore(self, callback, delay=0):
        owner_hwnd = self._parent_hwnd or self._owner_hwnd
        if not owner_hwnd:
            return False
        self._owner_focus_generation = int(
            getattr(self, "_owner_focus_generation", 0)) + 1
        generation = self._owner_focus_generation

        def deliver():
            # If this controller showed/activated another window after the close
            # request, this callback is stale and must not steal focus back.
            if generation != int(getattr(self, "_owner_focus_generation", 0)):
                return
            callback(owner_hwnd)

        try:
            self.view.after(max(0, int(delay or 0)), deliver)
            return True
        except Exception:
            return False

    def restore_owner_focus_async(self, delay=0):
        """Queue a coalesced keyboard-focus return to the WinUx owner."""
        return self._queue_owner_restore(restore_owner_focus, delay)

    def restore_owner_foreground_async(self, delay=0):
        """Queue one coalesced foreground/Z-order hand-off after dialog close."""
        return self._queue_owner_restore(restore_owner_foreground, delay)

    def destroy(self, wait=False, timeout=1.0):
        if not self._closed.is_set():
            self._host.submit(self._host_destroy_window)
        if wait and threading.get_ident() != self._host._thread_ident:
            self._closed.wait(timeout=max(0.0, float(timeout)))

    close = destroy
