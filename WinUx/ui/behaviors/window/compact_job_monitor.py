"""Compact bottom-right Job Viewer window behavior.

Kept separate from the main window composition so WinUXView does not own the
Win32/PiP implementation details.  The mixin intentionally has no standalone
state; all state remains on the owning WinUXView instance.
"""
from __future__ import annotations

import ctypes as _ctypes_stdlib
import os
import sys
from ctypes import wintypes


def _view_ctypes():
    """Honor historical monkey-patches applied through ``WinUx.view.ctypes``."""
    module = sys.modules.get("WinUx.ui.main_window") or sys.modules.get("WinUx.view")
    return getattr(module, "ctypes", _ctypes_stdlib) if module is not None else _ctypes_stdlib

from DearUIQt.input_gate import (
    popup_input_active, popup_input_is_blocked, release_pointer_input,
)
from DearUIQt.widgets import QApplication, QRetainedItem

from ....diagnostics import log_exception


class CompactJobMonitorMixin:
    def _compact_window_rect(self):
        """Return the current native WinUx outer rectangle."""
        if os.name != "nt":
            return None
        hwnd = self._find_main_viewport_hwnd()
        if not hwnd:
            return None
        try:
            user32 = _view_ctypes().windll.user32
            rect = wintypes.RECT()
            user32.GetWindowRect.argtypes = [wintypes.HWND, _view_ctypes().POINTER(wintypes.RECT)]
            user32.GetWindowRect.restype = wintypes.BOOL
            if not user32.GetWindowRect(wintypes.HWND(int(hwnd)), _view_ctypes().byref(rect)):
                return None
            return (int(rect.left), int(rect.top),
                    max(1, int(rect.right - rect.left)),
                    max(1, int(rect.bottom - rect.top)))
        except Exception:
            return None

    def _compact_monitor_work_area(self, hwnd, geometry=None):
        """Return the usable work area of the monitor containing *hwnd*."""
        if os.name != "nt" or not hwnd:
            return None
        try:
            class MONITORINFO(_view_ctypes().Structure):
                _fields_ = [
                    ("cbSize", wintypes.DWORD),
                    ("rcMonitor", wintypes.RECT),
                    ("rcWork", wintypes.RECT),
                    ("dwFlags", wintypes.DWORD),
                ]
            user32 = _view_ctypes().windll.user32
            user32.MonitorFromWindow.argtypes = [wintypes.HWND, wintypes.DWORD]
            user32.MonitorFromWindow.restype = wintypes.HANDLE
            if geometry is not None:
                x, y, width, height = geometry
                rect = wintypes.RECT(x, y, x + width, y + height)
                user32.MonitorFromRect.argtypes = [_view_ctypes().POINTER(wintypes.RECT), wintypes.DWORD]
                user32.MonitorFromRect.restype = wintypes.HANDLE
                monitor = user32.MonitorFromRect(_view_ctypes().byref(rect), 2)
            else:
                monitor = user32.MonitorFromWindow(wintypes.HWND(int(hwnd)), 2)
            if not monitor:
                return None
            info = MONITORINFO()
            info.cbSize = _view_ctypes().sizeof(info)
            user32.GetMonitorInfoW.argtypes = [
                wintypes.HANDLE, _view_ctypes().POINTER(MONITORINFO)]
            user32.GetMonitorInfoW.restype = wintypes.BOOL
            if not user32.GetMonitorInfoW(monitor, _view_ctypes().byref(info)):
                return None
            rc = info.rcWork
            return (int(rc.left), int(rc.top), int(rc.right), int(rc.bottom))
        except Exception:
            return None

    def _ensure_compact_job_monitor(self):
        monitor = getattr(self, "_compact_job_monitor", None)
        if monitor is not None:
            return monitor
        from ...components.compact_jobs_view import CompactJobsView
        monitor = CompactJobsView(
            self._main_window, self.restore_from_job_monitor, self._request_close,
            jobs_view=self._ensure_jobs_view())
        monitor.hide()
        self._compact_job_monitor = monitor
        return monitor

    def _layout_compact_job_monitor(self):
        if not getattr(self, "_compact_job_monitor_active", False):
            return
        monitor = self._ensure_compact_job_monitor()
        try:
            size = self._gui_runtime.viewportSize(client=True)
            width = max(260, int(size.width()))
            height = max(self.COMPACT_JOB_HEIGHT, int(size.height()))
        except Exception:
            width = self.COMPACT_JOB_WIDTH
            height = self.COMPACT_JOB_HEIGHT
        # The bundled renderer retains decorated client dimensions after the
        # native title bar is hidden. Use the real client rectangle, and size
        # the compact root explicitly instead of clipping to that stale size.
        hwnd = self._find_main_viewport_hwnd()
        if hwnd and os.name == "nt":
            rect = wintypes.RECT()
            if _view_ctypes().windll.user32.GetClientRect(
                    wintypes.HWND(int(hwnd)), _view_ctypes().byref(rect)):
                width, height = int(rect.right), int(rect.bottom)
        QRetainedItem(self.primary_window_tag).configure(
            pos=(0, 0), width=width, height=height, min_size=(width, height),
            no_scrollbar=True, no_scroll_with_mouse=True)
        monitor.resize(width, height)
        self._apply_compact_job_monitor_rounding(hwnd)

    def _compact_geometry_store(self):
        store = getattr(self, "_compact_geometry_preferences", None)
        if store is None:
            from ....preferences.dialog_geometry import DialogGeometryPreferences
            store = self._compact_geometry_preferences = DialogGeometryPreferences()
        return store

    def _load_compact_job_monitor_geometry(self):
        """Restore PiP on its saved monitor, clamped if that monitor vanished."""
        saved = self._compact_geometry_store().load("CompactJobMonitor")
        geometry = None if saved is None else tuple(
            saved[key] for key in ("x", "y", "width", "height"))
        hwnd = self._find_main_viewport_hwnd()
        work = self._compact_monitor_work_area(hwnd, geometry)
        width = max(260, geometry[2]) if geometry else self.COMPACT_JOB_WIDTH
        height = max(self.COMPACT_JOB_HEIGHT, geometry[3]) if geometry else self.COMPACT_JOB_HEIGHT
        if work is None:
            return (*geometry[:2], width, height) if geometry else (0, 0, width, height)
        left, top, right, bottom = work
        width, height = min(width, right - left), min(height, bottom - top)
        x, y = geometry[:2] if geometry else (
            right - width - self.COMPACT_JOB_MARGIN, bottom - height - self.COMPACT_JOB_MARGIN)
        return (max(left, min(x, right - width)), max(top, min(y, bottom - height)),
                width, height)

    def _save_compact_job_monitor_geometry(self):
        if not getattr(self, "_compact_job_monitor_active", False):
            return False
        geometry = self._compact_window_rect()
        if geometry is None:
            return False
        hwnd = self._find_main_viewport_hwnd()
        if _view_ctypes().windll.user32.IsIconic(wintypes.HWND(int(hwnd))):
            return False
        self._compact_pip_geometry = geometry
        return self._compact_geometry_store().save(
            "CompactJobMonitor", dict(zip(("x", "y", "width", "height"), geometry)))

    def _finish_compact_geometry_change(self):
        if not getattr(self, "_compact_job_monitor_active", False):
            return
        self._layout_compact_job_monitor()
        self._save_compact_job_monitor_geometry()

    def _apply_compact_job_monitor_rounding(self, hwnd):
        """Use smooth compositor corners, with a region only on older Windows."""
        if os.name != "nt" or not hwnd:
            return False
        if getattr(self, "_compact_corner_mode", None) == (int(hwnd), "native"):
            return True
        try:
            user32 = _view_ctypes().windll.user32
            gdi32 = _view_ctypes().windll.gdi32
            try:
                dwmapi = _view_ctypes().windll.dwmapi
            except Exception:
                dwmapi = None
            if dwmapi is not None:
                # A binary GDI region cuts through DWM's anti-aliased edge.
                # Keep the native resize-frame style, remove its client inset
                # in WM_NCCALCSIZE, and let DWM round all four corners once.
                preference = _view_ctypes().c_int(2)
                try:
                    rounded = dwmapi.DwmSetWindowAttribute(
                        wintypes.HWND(int(hwnd)), 33,
                        _view_ctypes().byref(preference), _view_ctypes().sizeof(preference))
                    if rounded == 0:
                        class MARGINS(_view_ctypes().Structure):
                            _fields_ = [(name, _view_ctypes().c_int) for name in (
                                "left", "right", "top", "bottom")]
                        margins = MARGINS(1, 1, 1, 1)
                        framed = dwmapi.DwmExtendFrameIntoClientArea(
                            wintypes.HWND(int(hwnd)), _view_ctypes().byref(margins))
                        if framed == 0:
                            # No bright native border around the white surface.
                            border = wintypes.DWORD(0xFFFFFFFE)  # DWMWA_COLOR_NONE
                            dwmapi.DwmSetWindowAttribute(
                                wintypes.HWND(int(hwnd)), 34,
                                _view_ctypes().byref(border), _view_ctypes().sizeof(border))
                            user32.SetWindowRgn.argtypes = [wintypes.HWND, wintypes.HANDLE, wintypes.BOOL]
                            user32.SetWindowRgn(wintypes.HWND(int(hwnd)), None, True)
                            self._compact_corner_mode = (int(hwnd), "native")
                            return True
                except Exception:
                    pass
            rect = wintypes.RECT()
            user32.GetWindowRect.argtypes = [wintypes.HWND, _view_ctypes().POINTER(wintypes.RECT)]
            user32.GetWindowRect.restype = wintypes.BOOL
            if not user32.GetWindowRect(wintypes.HWND(int(hwnd)), _view_ctypes().byref(rect)):
                return False
            width = max(1, int(rect.right - rect.left))
            height = max(1, int(rect.bottom - rect.top))
            if getattr(self, "_compact_corner_mode", None) == (int(hwnd), width, height):
                return True
            radius = max(10, int(self.COMPACT_JOB_CORNER_RADIUS))
            gdi32.CreateRoundRectRgn.restype = wintypes.HANDLE
            region = gdi32.CreateRoundRectRgn(
                0, 0, width, height, radius * 2, radius * 2)
            if region:
                user32.SetWindowRgn.argtypes = [wintypes.HWND, wintypes.HANDLE, wintypes.BOOL]
                user32.SetWindowRgn.restype = _view_ctypes().c_int
                if user32.SetWindowRgn(wintypes.HWND(int(hwnd)), region, True):
                    self._compact_corner_mode = (int(hwnd), width, height)
                    return True
                gdi32.DeleteObject.argtypes = [wintypes.HANDLE]
                gdi32.DeleteObject(region)
            return False
        except Exception:
            return False

    def _clear_compact_job_monitor_rounding(self, hwnd):
        """Restore the normal main-window region/corner preference."""
        if os.name != "nt" or not hwnd:
            return False
        self._compact_corner_mode = None
        try:
            user32 = _view_ctypes().windll.user32
            try:
                dwmapi = _view_ctypes().windll.dwmapi
            except Exception:
                dwmapi = None
            if dwmapi is not None:
                # DWMWA_WINDOW_CORNER_PREFERENCE = 33
                # DWMWCP_DEFAULT = 0
                preference = _view_ctypes().c_int(0)
                try:
                    dwmapi.DwmSetWindowAttribute(
                        wintypes.HWND(int(hwnd)), 33,
                        _view_ctypes().byref(preference), _view_ctypes().sizeof(preference))
                    margins = (_view_ctypes().c_int * 4)(0, 0, 0, 0)
                    dwmapi.DwmExtendFrameIntoClientArea(
                        wintypes.HWND(int(hwnd)), _view_ctypes().byref(margins))
                    border = wintypes.DWORD(0xFFFFFFFF)  # DWMWA_COLOR_DEFAULT
                    dwmapi.DwmSetWindowAttribute(
                        wintypes.HWND(int(hwnd)), 34,
                        _view_ctypes().byref(border), _view_ctypes().sizeof(border))
                except Exception:
                    pass
            user32.SetWindowRgn.argtypes = [wintypes.HWND, wintypes.HANDLE, wintypes.BOOL]
            user32.SetWindowRgn.restype = _view_ctypes().c_int
            user32.SetWindowRgn(wintypes.HWND(int(hwnd)), None, True)
            return True
        except Exception:
            return False

    def _position_compact_job_monitor(self):
        """Place PiP at its last saved rectangle, or bottom-right on first use."""
        if not getattr(self, "_compact_job_monitor_active", False):
            return False
        hwnd = self._find_main_viewport_hwnd()
        if not hwnd or os.name != "nt":
            return False
        try:
            x, y, width, height = self._compact_pip_geometry
            user32 = _view_ctypes().windll.user32
            user32.SetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPCWSTR]
            user32.SetWindowTextW(wintypes.HWND(int(hwnd)), "WinUx Job Monitor")
            user32.SetWindowPos.argtypes = [
                wintypes.HWND, wintypes.HWND, _view_ctypes().c_int, _view_ctypes().c_int,
                _view_ctypes().c_int, _view_ctypes().c_int, wintypes.UINT]
            user32.SetWindowPos.restype = wintypes.BOOL
            HWND_TOPMOST = wintypes.HWND(-1)
            SWP_NOACTIVATE = 0x0010
            SWP_SHOWWINDOW = 0x0040
            SWP_FRAMECHANGED = 0x0020
            user32.SetWindowPos(
                wintypes.HWND(int(hwnd)), HWND_TOPMOST,
                int(x), int(y), width, height,
                SWP_NOACTIVATE | SWP_SHOWWINDOW | SWP_FRAMECHANGED)
            self._layout_compact_job_monitor()
            self._apply_compact_job_monitor_rounding(hwnd)
            return True
        except Exception:
            log_exception(
                "Compact Job Monitor placement failed", sys.exc_info(), fatal=False)
            return False

    def _poll_compact_job_monitor_hover(self, serial=None):
        """Reveal PiP Restore/Close controls only while the HWND is hovered."""
        if serial is not None and serial != getattr(self, "_compact_hover_serial", 0):
            return
        if not getattr(self, "_compact_job_monitor_active", False):
            self._compact_hover_polling = False
            monitor = getattr(self, "_compact_job_monitor", None)
            if monitor is not None:
                monitor.set_hovered(False)
            return
        monitor = self._ensure_compact_job_monitor()
        hovered = False
        hwnd = self._find_main_viewport_hwnd()
        if hwnd and os.name == "nt":
            try:
                user32 = _view_ctypes().windll.user32
                point = wintypes.POINT()
                rect = wintypes.RECT()
                user32.GetCursorPos.argtypes = [_view_ctypes().POINTER(wintypes.POINT)]
                user32.GetCursorPos.restype = wintypes.BOOL
                user32.GetWindowRect.argtypes = [wintypes.HWND, _view_ctypes().POINTER(wintypes.RECT)]
                user32.GetWindowRect.restype = wintypes.BOOL
                if (user32.GetCursorPos(_view_ctypes().byref(point))
                        and user32.GetWindowRect(wintypes.HWND(int(hwnd)), _view_ctypes().byref(rect))):
                    hovered = (rect.left <= point.x < rect.right
                               and rect.top <= point.y < rect.bottom)
            except Exception:
                hovered = False
        else:
            try:
                hovered = bool(QRetainedItem(monitor.root).underMouse())
            except Exception:
                hovered = False
        monitor.set_hovered(hovered)
        self.after(70, self._poll_compact_job_monitor_hover, serial)

    def _install_compact_restore_first_click(self):
        """Native PiP move/resize hit targets and first-click Restore delivery."""
        if os.name != "nt":
            return
        hwnd = self._find_main_viewport_hwnd()
        if not hwnd:
            return
        existing = getattr(self, "_compact_restore_mouse_hook", None)
        if existing and existing[0] == int(hwnd):
            return
        self._remove_compact_restore_first_click()
        try:
            user32 = _view_ctypes().windll.user32
            pointer_type = _view_ctypes().c_ssize_t
            getter = (user32.GetWindowLongPtrW if _view_ctypes().sizeof(_view_ctypes().c_void_p) == 8
                      else user32.GetWindowLongW)
            setter = (user32.SetWindowLongPtrW if _view_ctypes().sizeof(_view_ctypes().c_void_p) == 8
                      else user32.SetWindowLongW)
            getter.argtypes = [wintypes.HWND, _view_ctypes().c_int]
            getter.restype = pointer_type
            setter.argtypes = [wintypes.HWND, _view_ctypes().c_int, pointer_type]
            setter.restype = pointer_type
            user32.CallWindowProcW.argtypes = [
                _view_ctypes().c_void_p, wintypes.HWND, wintypes.UINT,
                wintypes.WPARAM, wintypes.LPARAM]
            user32.CallWindowProcW.restype = pointer_type
            user32.DefWindowProcW.argtypes = [
                wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
            user32.DefWindowProcW.restype = pointer_type
            old_proc = getter(wintypes.HWND(int(hwnd)), -4)
            if not old_proc:
                return
            proc_type = _view_ctypes().WINFUNCTYPE(
                pointer_type, wintypes.HWND, wintypes.UINT,
                wintypes.WPARAM, wintypes.LPARAM)

            class MINMAXINFO(_view_ctypes().Structure):
                _fields_ = [(name, wintypes.POINT) for name in (
                    "reserved", "max_size", "max_position", "min_track", "max_track")]

            @proc_type
            def compact_proc(window, message, wparam, lparam):
                try:
                    if self._compact_job_monitor_active:
                        if message == 0x0083:  # WM_NCCALCSIZE: borderless full client area
                            return 0
                        if message == 0x0020:  # WM_SETCURSOR
                            hit = int(lparam) & 0xffff
                            cursor_id = {
                                2: 32646,  # IDC_SIZEALL, drag handle
                                10: 32644, 11: 32644,  # IDC_SIZEWE
                                12: 32645, 15: 32645,  # IDC_SIZENS
                                13: 32642, 17: 32642,  # IDC_SIZENWSE
                                14: 32643, 16: 32643,  # IDC_SIZENESW
                            }.get(hit)
                            if cursor_id is not None:
                                user32.LoadCursorW.argtypes = [wintypes.HINSTANCE, _view_ctypes().c_void_p]
                                user32.LoadCursorW.restype = wintypes.HANDLE
                                cursor = user32.LoadCursorW(None, _view_ctypes().c_void_p(cursor_id))
                                user32.SetCursor.argtypes = [wintypes.HANDLE]
                                user32.SetCursor.restype = wintypes.HANDLE
                                if cursor:
                                    user32.SetCursor(cursor)
                                    return 1
                        if message == 0x00A1 and int(wparam) in (2, 10, 11, 12, 13, 14, 15, 16, 17):
                            # GLFW deliberately ignores non-client dragging on
                            # an undecorated viewport. Give our explicit native
                            # hit targets to Windows' normal move/size loop.
                            return user32.DefWindowProcW(window, message, wparam, lparam)
                        if message == 0x0084:  # WM_NCHITTEST, signed desktop coordinates
                            # Outside clicks belong to QMenu while it has the
                            # popup grab; they must dismiss it, not drag PiP.
                            if popup_input_active():
                                return 1  # HTCLIENT
                            x = _view_ctypes().c_short(int(lparam) & 0xffff).value
                            y = _view_ctypes().c_short((int(lparam) >> 16) & 0xffff).value
                            rect = wintypes.RECT()
                            monitor = self._compact_job_monitor
                            if monitor is not None and user32.GetWindowRect(window, _view_ctypes().byref(rect)):
                                hit = monitor.native_hit_test(
                                    x - rect.left, y - rect.top,
                                    rect.right - rect.left, rect.bottom - rect.top)
                                if hit is not None:
                                    return hit
                        if message == 0x0024 and lparam:  # WM_GETMINMAXINFO
                            result = user32.CallWindowProcW(
                                _view_ctypes().c_void_p(old_proc), window, message, wparam, lparam)
                            info = _view_ctypes().cast(lparam, _view_ctypes().POINTER(MINMAXINFO)).contents
                            info.min_track.x = 260
                            info.min_track.y = self.COMPACT_JOB_HEIGHT
                            return result
                        if message == 0x0005 and wparam != 1:  # WM_SIZE, not SIZE_MINIMIZED
                            # The native size loop can run between render turns.
                            # Keep the rounded region in sync without calling DPG
                            # recursively from a Win32 message callback.
                            self._apply_compact_job_monitor_rounding(int(window))
                        if message == 0x0232:  # WM_EXITSIZEMOVE: persist once per gesture
                            self.after(0, self._finish_compact_geometry_change)
                        if message == 0x0021:  # WM_MOUSEACTIVATE
                            # MA_ACTIVATE: do not discard first mouse-down.
                            return 1
                        if message == 0x0201:  # WM_LBUTTONDOWN
                            x = _view_ctypes().c_short(int(lparam) & 0xffff).value
                            y = _view_ctypes().c_short((int(lparam) >> 16) & 0xffff).value
                            monitor = getattr(self, "_compact_job_monitor", None)
                            self._compact_native_restore_armed = bool(
                                monitor is not None and not popup_input_active()
                                and monitor.is_restore_target(x, y))
                        if message == 0x0202:  # WM_LBUTTONUP
                            # lParam contains *signed* client coordinates.
                            x = _view_ctypes().c_short(int(lparam) & 0xffff).value
                            y = _view_ctypes().c_short((int(lparam) >> 16) & 0xffff).value
                            monitor = getattr(self, "_compact_job_monitor", None)
                            armed = getattr(self, "_compact_native_restore_armed", False)
                            self._compact_native_restore_armed = False
                            if (armed and monitor is not None and not popup_input_active()
                                    and monitor.is_restore_target(x, y)):
                                # Defer mutation of HWND styles until the
                                # current native message has been dispatched.
                                if not getattr(self, "_compact_restore_click_queued", False):
                                    self._compact_restore_click_queued = True
                                    self.after(0, self._complete_compact_restore_click,
                                               getattr(self, "_compact_transition_serial", 0))
                                # GLFW/ImGui must also observe this button-up.
                                # Swallowing it leaves MouseDown/ActiveId latched
                                # after restore and can block every later click.
                except Exception:
                    pass
                return user32.CallWindowProcW(
                    _view_ctypes().c_void_p(old_proc), window, message, wparam, lparam)

            setter(wintypes.HWND(int(hwnd)), -4,
                   _view_ctypes().cast(compact_proc, _view_ctypes().c_void_p).value)
            self._compact_restore_mouse_hook = (int(hwnd), old_proc, compact_proc)
        except Exception:
            log_exception("PiP first-click hook failed", sys.exc_info(), fatal=False)

    def _complete_compact_restore_click(self, serial=None):
        if serial is not None and serial != getattr(self, "_compact_transition_serial", 0):
            return
        self._compact_restore_click_queued = False
        if (getattr(self, "_compact_job_monitor_active", False)
                and not popup_input_is_blocked()):
            self.restore_from_job_monitor()

    def _remove_compact_restore_first_click(self):
        entry = getattr(self, "_compact_restore_mouse_hook", None)
        if not entry:
            return
        hwnd, old_proc, callback = entry
        if os.name != "nt":
            self._compact_restore_mouse_hook = None
            return
        try:
            user32 = _view_ctypes().windll.user32
            if user32.IsWindow(wintypes.HWND(hwnd)):
                getter = (user32.GetWindowLongPtrW if _view_ctypes().sizeof(_view_ctypes().c_void_p) == 8
                          else user32.GetWindowLongW)
                getter.argtypes = [wintypes.HWND, _view_ctypes().c_int]
                getter.restype = _view_ctypes().c_ssize_t
                if int(getter(wintypes.HWND(hwnd), -4)) != _view_ctypes().cast(callback, _view_ctypes().c_void_p).value:
                    # Another native hook is above ours. It may still call our
                    # procedure, so neither unchain it nor free its callback.
                    return
                setter = (user32.SetWindowLongPtrW if _view_ctypes().sizeof(_view_ctypes().c_void_p) == 8
                          else user32.SetWindowLongW)
                setter.argtypes = [wintypes.HWND, _view_ctypes().c_int, _view_ctypes().c_ssize_t]
                setter.restype = _view_ctypes().c_ssize_t
                setter(wintypes.HWND(hwnd), -4, old_proc)
            self._compact_restore_mouse_hook = None
        except Exception:
            log_exception("PiP first-click hook removal failed", sys.exc_info(), fatal=False)

    def _start_compact_job_monitor_hover(self):
        if self._compact_hover_polling:
            return
        self._compact_hover_polling = True
        self._compact_hover_serial = getattr(self, "_compact_hover_serial", 0) + 1
        self.after(40, self._poll_compact_job_monitor_hover, self._compact_hover_serial)

    @staticmethod
    def _compact_native_window_styles(hwnd):
        """Snapshot the GLFW-created style, rather than guessing Win32 flags."""
        if os.name != "nt" or not hwnd:
            return None
        try:
            user32 = _view_ctypes().windll.user32
            getter = (user32.GetWindowLongPtrW if _view_ctypes().sizeof(_view_ctypes().c_void_p) == 8
                      else user32.GetWindowLongW)
            getter.argtypes = [wintypes.HWND, _view_ctypes().c_int]
            getter.restype = _view_ctypes().c_ssize_t
            window = wintypes.HWND(int(hwnd))
            return (int(hwnd), int(getter(window, -16)), int(getter(window, -20)))
        except Exception:
            return None

    def _set_compact_native_borderless(self):
        """Temporarily remove GLFW's caption without changing DPG decoration.

        Dear PyGui's decorated toggle is not reliably reversible on the
        bundled GLFW renderer. Keep its viewport configuration untouched and
        apply the PiP-only style to the actual primary HWND instead.
        """
        saved = getattr(self, "_compact_saved_native_styles", None)
        if os.name != "nt" or not saved:
            return False
        hwnd = self._find_main_viewport_hwnd()
        if not hwnd or int(hwnd) != saved[0]:
            return False
        try:
            user32 = _view_ctypes().windll.user32
            setter = (user32.SetWindowLongPtrW if _view_ctypes().sizeof(_view_ctypes().c_void_p) == 8
                      else user32.SetWindowLongW)
            setter.argtypes = [wintypes.HWND, _view_ctypes().c_int, _view_ctypes().c_ssize_t]
            setter.restype = _view_ctypes().c_ssize_t
            # Keep WS_THICKFRAME for native DWM anti-aliased corners/shadow;
            # WM_NCCALCSIZE removes its visible frame/client-area insets.
            # Preserve unrelated flags (visibility, clipping, system state).
            style = (saved[1] & ~(0x00C00000 | 0x00040000 | 0x00800000 |
                                    0x00020000 | 0x00010000 | 0x00400000 |
                                    0x00080000)) | 0x80000000 | 0x00040000
            setter(wintypes.HWND(int(hwnd)), -16, style)
            return self._refresh_compact_native_frame(hwnd)
        except Exception:
            return False

    @staticmethod
    def _refresh_compact_native_frame(hwnd):
        if not hwnd or os.name != "nt":
            return False
        user32 = _view_ctypes().windll.user32
        user32.SetWindowPos.argtypes = [
            wintypes.HWND, wintypes.HWND, _view_ctypes().c_int, _view_ctypes().c_int,
            _view_ctypes().c_int, _view_ctypes().c_int, wintypes.UINT]
        user32.SetWindowPos.restype = wintypes.BOOL
        # NOZORDER | NOMOVE | NOSIZE | NOACTIVATE | FRAMECHANGED
        return bool(user32.SetWindowPos(
            wintypes.HWND(int(hwnd)), None, 0, 0, 0, 0, 0x37))

    def _restore_compact_native_frame(self):
        """Restore the exact original GLFW HWND styles, never guessed flags."""
        saved = getattr(self, "_compact_saved_native_styles", None)
        if not saved or os.name != "nt" or self._compact_job_monitor_active:
            return False
        hwnd = self._find_main_viewport_hwnd()
        if not hwnd or int(hwnd) != saved[0]:
            return False
        if self._compact_native_window_styles(hwnd) == saved:
            # Settling callbacks should not repeatedly issue FRAMECHANGED once
            # Full mode already has its original frame (visible titlebar flash).
            return True
        try:
            user32 = _view_ctypes().windll.user32
            setter = (user32.SetWindowLongPtrW if _view_ctypes().sizeof(_view_ctypes().c_void_p) == 8
                      else user32.SetWindowLongW)
            setter.argtypes = [wintypes.HWND, _view_ctypes().c_int, _view_ctypes().c_ssize_t]
            setter.restype = _view_ctypes().c_ssize_t
            handle = wintypes.HWND(int(hwnd))
            setter(handle, -16, saved[1])
            setter(handle, -20, saved[2])
            return self._refresh_compact_native_frame(hwnd)
        except Exception:
            return False

    def _prepare_job_monitor_transition(self):
        """Cancel workspace gestures only; never reset live dialog/modal gates."""
        self._cancel_splitter_interactions()
        lists = [getattr(panel, "listview", None) for panel in getattr(self, "panels", ())]
        for surface in (getattr(self, "jobs_view", None),
                        getattr(self, "_compact_job_monitor", None)):
            lists.append(getattr(surface, "listview", None))
        for listview in lists:
            if listview is not None:
                try:
                    listview._hide_context_menus()
                    listview.cancel_pointer_gesture(suppress_release=True)
                    listview.use_primary_pointer_overlays()
                except Exception:
                    log_exception("Job monitor gesture cleanup failed", sys.exc_info(), fatal=False)
                finally:
                    release_pointer_input(listview)
        menu = getattr(self, "_menu_bar_wrapper", None)
        if menu is not None:
            menu.closeActiveMenu()
        for name in ("_file_panel_splitter_owner", "_horizontal_splitter_owner",
                     "_plot_splitter_owner", "_console_splitter_owner",
                     "_console_dock_drag_owner"):
            owner = getattr(self, name, None)
            if owner is not None:
                release_pointer_input(owner)
        application = QApplication.instance()
        if application is not None:
            grabber = application.mouseGrabberObject()
            current = grabber
            workspace_tags = {getattr(self, "layout_root", None)}
            monitor = getattr(self, "_compact_job_monitor", None)
            if monitor is not None:
                workspace_tags.add(monitor.root)
            workspace_tags.discard(None)
            while current is not None:
                if getattr(current, "tag", None) in workspace_tags:
                    application.releaseMouseGrabberObject(grabber)
                    break
                current = getattr(current, "parent", None)
        hwnd = self._find_main_viewport_hwnd()
        if os.name == "nt" and hwnd:
            user32 = _view_ctypes().windll.user32
            user32.GetCapture.restype = wintypes.HWND
            if int(user32.GetCapture() or 0) == int(hwnd):
                # This HWND may own a native move/resize capture. Do not touch
                # captures belonging to a modal, editor or detached tool window.
                user32.ReleaseCapture()
        self._compact_native_restore_armed = False
        self._compact_restore_click_queued = False

    def _finish_job_monitor_transition(self, serial, compact):
        if (serial != getattr(self, "_compact_transition_serial", 0)
                or bool(self._compact_job_monitor_active) != compact):
            return
        if compact:
            self._layout_compact_job_monitor()
        else:
            self._restore_compact_native_frame()
            self._apply_split_layout(True)

    def collapse_to_job_monitor(self):
        """Collapse WinUx into a small always-on-top bottom-right job monitor."""
        if getattr(self, "_compact_job_monitor_active", False):
            return True
        self._prepare_job_monitor_transition()
        self._compact_transition_serial = getattr(self, "_compact_transition_serial", 0) + 1
        serial = self._compact_transition_serial
        self._compact_saved_native_styles = self._compact_native_window_styles(
            self._find_main_viewport_hwnd())
        self._compact_saved_window_rect = self._compact_window_rect()
        viewport_options = self._gui_runtime.backend.get_viewport_configuration(0)
        self._compact_saved_viewport_options = {
            key: viewport_options[key]
            for key in ("decorated", "min_width", "min_height")
        }
        main_options = self._gui_runtime.backend.get_item_configuration(
            self.primary_window_tag)
        self._compact_saved_main_options = {
            key: main_options[key]
            for key in ("min_size", "no_scrollbar", "no_scroll_with_mouse")
        }
        self._compact_job_monitor_active = True
        self._compact_pip_geometry = self._load_compact_job_monitor_geometry()
        monitor = self._ensure_compact_job_monitor()
        try:
            QRetainedItem(self.menu_bar).setVisible(False)
            QRetainedItem(self.layout_root).setVisible(False)
        except Exception:
            pass
        monitor.show()
        monitor.set_hovered(False)
        self._start_compact_job_monitor_hover()
        try:
            monitor.display(tuple(getattr(self, "_compact_last_jobs", ()) or ()))
        except Exception:
            pass
        try:
            self._gui_runtime.configureViewport(
                min_width=260, min_height=self.COMPACT_JOB_HEIGHT,
                width=self._compact_pip_geometry[2],
                height=self._compact_pip_geometry[3])
        except Exception:
            pass
        self._install_compact_restore_first_click()
        self._set_compact_native_borderless()
        self.after(0, self._position_compact_job_monitor)
        self.after(50, self._finish_job_monitor_transition, serial, True)
        return True

    def restore_from_job_monitor(self):
        """Restore the full WinUx window and return it to the normal Z-order."""
        if not getattr(self, "_compact_job_monitor_active", False):
            return True
        self._prepare_job_monitor_transition()
        self._compact_transition_serial = getattr(self, "_compact_transition_serial", 0) + 1
        serial = self._compact_transition_serial
        self._save_compact_job_monitor_geometry()
        self._compact_job_monitor_active = False
        # Keep the native hook installed but inert in Full mode. Reusing it
        # avoids tearing down a live WNDPROC chain during mouse-up dispatch.
        self._compact_restore_click_queued = False
        QRetainedItem(self.primary_window_tag).configure(
            **self._compact_saved_main_options)
        monitor = getattr(self, "_compact_job_monitor", None)
        self._compact_hover_polling = False
        self._compact_hover_serial = getattr(self, "_compact_hover_serial", 0) + 1
        if monitor is not None:
            monitor.set_hovered(False)
            monitor.hide()
        try:
            QRetainedItem(self.menu_bar).setVisible(True)
            QRetainedItem(self.layout_root).setVisible(True)
        except Exception:
            pass
        rect = self._compact_saved_window_rect
        width = int(rect[2]) if rect else int(self.WIDTH)
        height = int(rect[3]) if rect else int(self.HEIGHT)
        try:
            self._gui_runtime.configureViewport(
                width=width, height=height,
                **getattr(self, "_compact_saved_viewport_options", {
                    "decorated": True, "min_width": 250, "min_height": 250}))
        except Exception:
            pass
        hwnd = self._find_main_viewport_hwnd()
        if hwnd and os.name == "nt":
            try:
                self._clear_compact_job_monitor_rounding(hwnd)
                self._restore_compact_native_frame()
                user32 = _view_ctypes().windll.user32
                user32.SetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPCWSTR]
                user32.SetWindowTextW(wintypes.HWND(int(hwnd)), "WinUX")
                user32.SetWindowPos.argtypes = [
                    wintypes.HWND, wintypes.HWND, _view_ctypes().c_int, _view_ctypes().c_int,
                    _view_ctypes().c_int, _view_ctypes().c_int, wintypes.UINT]
                user32.SetWindowPos.restype = wintypes.BOOL
                HWND_NOTOPMOST = wintypes.HWND(-2)
                SWP_SHOWWINDOW = 0x0040
                if rect:
                    x, y, width, height = map(int, rect)
                else:
                    x, y = 80, 80
                user32.SetWindowPos(
                    wintypes.HWND(int(hwnd)), HWND_NOTOPMOST,
                    x, y, width, height, SWP_SHOWWINDOW)
            except Exception:
                log_exception(
                    "Compact Job Monitor restore failed", sys.exc_info(), fatal=False)
        try:
            self._ensure_jobs_view().display(tuple(self._compact_last_jobs))
        except Exception:
            pass
        self._layout_dirty = True
        # Reassert after the viewport size has settled, without ever toggling
        # GLFW's decorated flag (which caused the missing-titlebar regression).
        self.after(0, self._finish_job_monitor_transition, serial, False)
        self.after(80, self._finish_job_monitor_transition, serial, False)
        return True
