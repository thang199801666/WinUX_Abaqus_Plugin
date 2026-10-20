"""Opt-in native multi-window ABI; no Qt, worker processes or IPC involved."""
from __future__ import annotations

import ctypes
import os
from ctypes import wintypes
from dataclasses import dataclass

from . import get_backend
from .api import BackendCapabilityError




@dataclass(frozen=True)
class _OwnerCloseLease:
    """Win32 state captured while an owned native dialog is still alive.

    The child HWND can disappear during the next ImGui platform render.  Keep
    the owner and last-input snapshot independently so focus/visibility can be
    verified *after* that platform teardown without re-resolving ownership from
    whichever desktop window happens to be foreground at that later time.
    """

    child_hwnd: int
    owner_hwnd: int
    owner_was_visible: bool
    return_foreground: bool
    last_input_tick: int | None
    process_id: int


class _MonitorInfo(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.DWORD),
        ("rcMonitor", wintypes.RECT),
        ("rcWork", wintypes.RECT),
        ("dwFlags", wintypes.DWORD),
    ]


def _owner_monitor_work_area(user32, owner_hwnd):
    """Nearest monitor's usable bounds, or None on old/mock Windows APIs."""
    monitor_from = getattr(user32, "MonitorFromWindow", None)
    get_monitor = getattr(user32, "GetMonitorInfoW", None)
    if monitor_from is None or get_monitor is None:
        return None
    try:
        monitor_from.argtypes = [wintypes.HWND, wintypes.DWORD]
        monitor_from.restype = wintypes.HMONITOR if hasattr(wintypes, "HMONITOR") else wintypes.HANDLE
        monitor = monitor_from(wintypes.HWND(int(owner_hwnd)), 2)  # MONITOR_DEFAULTTONEAREST
        if not monitor:
            return None
        get_monitor.argtypes = [wintypes.HANDLE, ctypes.POINTER(_MonitorInfo)]
        get_monitor.restype = wintypes.BOOL
        info = _MonitorInfo()
        info.cbSize = ctypes.sizeof(info)
        if not get_monitor(monitor, ctypes.byref(info)):
            return None
        work = info.rcWork
        return (work.left, work.top, work.right - work.left, work.bottom - work.top)
    except Exception:
        return None


class _LastInputInfo(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.UINT), ("dwTime", wintypes.DWORD)]


def _last_input_tick(user32):
    getter = getattr(user32, "GetLastInputInfo", None)
    if getter is None:
        return None
    try:
        getter.argtypes = [ctypes.POINTER(_LastInputInfo)]
        getter.restype = wintypes.BOOL
        info = _LastInputInfo()
        info.cbSize = ctypes.sizeof(info)
        if getter(ctypes.byref(info)):
            return int(info.dwTime)
    except Exception:
        pass
    return None


def _window_process_id(user32, hwnd):
    getter = getattr(user32, "GetWindowThreadProcessId", None)
    if getter is None or not hwnd:
        return 0
    try:
        getter.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
        getter.restype = wintypes.DWORD
        pid = wintypes.DWORD()
        getter(wintypes.HWND(int(hwnd)), ctypes.byref(pid))
        return int(pid.value or 0)
    except Exception:
        return 0

def _windows_user32():
    """Return user32 only on Windows; isolated for deterministic unit tests."""
    if os.name != "nt":
        return None
    try:
        return ctypes.windll.user32
    except Exception:
        return None


class NativeWindowBackend:
    """Bridge to DearUIQt's custom renderer, never emulate native windows."""

    def __init__(self, backend=None):
        self.backend = get_backend() if backend is None else backend
        self.extension = getattr(self.backend, "internal_dpg", self.backend)
        # Native ownership is a structural property, not per-frame state.  The
        # original C++ bridge rewrote GWLP_HWNDPARENT on every rendered frame;
        # USER32 treats that as a non-client relationship update and can reset
        # the caption hot state while the pointer is over Close.  Keep the
        # desired owner here and commit it only when the secondary HWND exists
        # and its actual owner differs.
        self._configured_item_tag = 0
        self._configured_owner_tag = 0
        self._configured_owner_hwnd = 0
        # Original non-client resize bits per HWND.  Keeping the snapshot lets
        # a retained dialog restore its native frame if a future caller makes
        # it resizable again without guessing the host's original style.
        self._native_resize_style_bits = {}
        # Keep Python WNDPROC callbacks alive for the lifetime of each native
        # dialog HWND. These hooks normalize WM_MOUSEACTIVATE so USER32/GLFW
        # cannot consume the first client click merely to activate a modal.
        self._mouse_activate_hooks = {}
        self._first_client_click_callbacks = {}
        self._first_client_click_armed = set()

    def available(self):
        return all(callable(getattr(self.extension, name, None)) for name in (
            "dearuiqt_enable_native_windows", "dearuiqt_native_windows_enabled",
            "dearuiqt_configure_native_window", "dearuiqt_native_window_handle"))

    def require(self):
        if not self.available():
            raise BackendCapabilityError(
                "Native windows require the DearUIQt multi-viewport build. "
                "Stock Dear PyGui cannot provide independent in-process windows.")

    def enable(self):
        self.require()
        return bool(self.extension.dearuiqt_enable_native_windows())

    def isEnabled(self):
        return bool(self.available() and self.extension.dearuiqt_native_windows_enabled())

    def configure(self, item, *, owner=None, modal=False, owner_hwnd=0):
        self.require()
        tag = int(getattr(item, "tag", item))
        owner_tag = 0 if owner is None else int(getattr(owner, "tag", owner))
        self._configured_item_tag = tag
        self._configured_owner_tag = owner_tag
        try:
            self._configured_owner_hwnd = int(owner_hwnd or 0)
        except (TypeError, ValueError, OverflowError):
            self._configured_owner_hwnd = 0
        return self.extension.dearuiqt_configure_native_window(tag, owner_tag, bool(modal))

    def _rawWinId(self, item):
        return int(self.extension.dearuiqt_native_window_handle(
            int(getattr(item, "tag", item))) or 0)

    def _desiredOwnerHwnd(self, item_tag):
        if int(item_tag) != int(self._configured_item_tag or 0):
            return 0
        if self._configured_owner_tag:
            try:
                owner = int(self.extension.dearuiqt_native_window_handle(
                    int(self._configured_owner_tag)) or 0)
            except Exception:
                owner = 0
            if owner:
                return owner
        return int(self._configured_owner_hwnd or 0)

    def synchronizeOwner(self, item):
        """Commit the Win32 owner only when the relationship actually changes.

        This is intentionally idempotent.  A secondary ImGui viewport does not
        have an HWND until after its first platform render, so callers may retry
        this method for a few frames without generating any non-client traffic.
        """
        self.require()
        tag = int(getattr(item, "tag", item))
        hwnd = self._rawWinId(tag)
        owner_hwnd = self._desiredOwnerHwnd(tag)
        if not hwnd or not owner_hwnd or hwnd == owner_hwnd:
            return False
        user32 = _windows_user32()
        if user32 is None:
            return False
        try:
            user32.GetWindow.argtypes = [wintypes.HWND, wintypes.UINT]
            user32.GetWindow.restype = wintypes.HWND
            current = int(user32.GetWindow(wintypes.HWND(hwnd), 4) or 0)  # GW_OWNER
            if current == owner_hwnd:
                return True
            setter = (user32.SetWindowLongPtrW if ctypes.sizeof(ctypes.c_void_p) == 8
                      else user32.SetWindowLongW)
            setter.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_ssize_t]
            setter.restype = ctypes.c_ssize_t
            setter(wintypes.HWND(hwnd), -8, int(owner_hwnd))  # GWLP_HWNDPARENT
            return int(user32.GetWindow(wintypes.HWND(hwnd), 4) or 0) == owner_hwnd
        except Exception:
            return False

    def winId(self, item):
        self.require()
        hwnd = self._rawWinId(item)
        if hwnd:
            self.synchronizeOwner(item)
        return hwnd


    def preserveFirstClientClick(self, item, click_callback=None):
        """Ensure an inactive native dialog does not eat its first mouse click.

        Win32 sends ``WM_MOUSEACTIVATE`` before the client button message when
        an inactive top-level is clicked.  GLFW/platform viewport handling can
        return an ``*ANDEAT`` result on some activation paths, which makes the
        first press activate the dialog without reaching ImGui.  Subclass the
        secondary HWND and force ``MA_ACTIVATE``: activate the window but keep
        the original mouse message.

        Returns ``None`` until the HWND exists, otherwise a boolean.
        """
        self.require()
        hwnd = int(self._rawWinId(item) or 0)
        if not hwnd:
            return None
        if click_callback is not None:
            self._first_client_click_callbacks[hwnd] = click_callback
            self._first_client_click_armed.add(hwnd)
        if hwnd in self._mouse_activate_hooks:
            return True
        user32 = _windows_user32()
        if user32 is None:
            return True
        try:
            GWL_WNDPROC = -4
            WM_MOUSEACTIVATE = 0x0021
            MA_ACTIVATE = 1
            getter = (user32.GetWindowLongPtrW if ctypes.sizeof(ctypes.c_void_p) == 8
                      else user32.GetWindowLongW)
            setter = (user32.SetWindowLongPtrW if ctypes.sizeof(ctypes.c_void_p) == 8
                      else user32.SetWindowLongW)
            getter.argtypes = [wintypes.HWND, ctypes.c_int]
            getter.restype = ctypes.c_ssize_t
            setter.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_ssize_t]
            setter.restype = ctypes.c_ssize_t
            old_proc = int(getter(wintypes.HWND(hwnd), GWL_WNDPROC) or 0)
            if not old_proc:
                return False

            proc_type = getattr(ctypes, "WINFUNCTYPE", ctypes.CFUNCTYPE)(
                ctypes.c_ssize_t, wintypes.HWND, wintypes.UINT,
                wintypes.WPARAM, wintypes.LPARAM)
            call_proc = user32.CallWindowProcW
            call_proc.argtypes = [ctypes.c_void_p, wintypes.HWND, wintypes.UINT,
                                  wintypes.WPARAM, wintypes.LPARAM]
            call_proc.restype = ctypes.c_ssize_t

            @proc_type
            def wndproc(window, message, wparam, lparam):
                message = int(message)
                if message == WM_MOUSEACTIVATE:
                    return MA_ACTIVATE
                result = call_proc(ctypes.c_void_p(old_proc), window, message, wparam, lparam)
                # DPG/GLFW can still lose the very first client click on a newly
                # shown secondary HWND even when WM_MOUSEACTIVATE is preserved.
                # Observe that first left-button release at Win32 level and let
                # QDialog recover it only if the normal DPG path did not already
                # activate a button.  The callback is deliberately one-shot.
                if message == 0x0202 and int(hwnd) in self._first_client_click_armed:  # WM_LBUTTONUP
                    self._first_client_click_armed.discard(int(hwnd))
                    callback = self._first_client_click_callbacks.get(int(hwnd))
                    if callable(callback):
                        try:
                            x = ctypes.c_short(int(lparam) & 0xFFFF).value
                            y = ctypes.c_short((int(lparam) >> 16) & 0xFFFF).value
                            point = wintypes.POINT(int(x), int(y))
                            converter = getattr(user32, "ClientToScreen", None)
                            if callable(converter):
                                try:
                                    converter.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.POINT)]
                                    converter.restype = wintypes.BOOL
                                    converter(wintypes.HWND(int(hwnd)), ctypes.byref(point))
                                except Exception:
                                    pass
                            callback((float(point.x), float(point.y)))
                        except Exception:
                            pass
                return result

            proc_ptr = int(ctypes.cast(wndproc, ctypes.c_void_p).value or 0)
            if not proc_ptr:
                return False
            previous = int(setter(
                wintypes.HWND(hwnd), GWL_WNDPROC,
                ctypes.c_ssize_t(proc_ptr).value) or 0)
            # SetWindowLongPtr may legally return zero if the previous value is
            # zero, but WNDPROC cannot be null here because we just read it.
            # Require the observed previous proc to match our snapshot when the
            # API reports it, otherwise avoid claiming the hook is installed.
            if previous not in (0, old_proc):
                return False
            self._mouse_activate_hooks[hwnd] = (wndproc, old_proc)
            return True
        except Exception:
            return False

    def activateOwnedWindow(self, item):
        """Activate a newly presented owned HWND without stealing desktop focus.

        ImGui focus is not sufficient for secondary platform viewports: the
        first physical click may otherwise be consumed by USER32 purely to
        activate the HWND.  Activate only when the current foreground window
        is this child or its configured owner.  If another application already
        owns foreground, leave it alone.

        Returns ``None`` while the native HWND is not created yet, ``False``
        when activation is intentionally refused, and ``True`` when the child
        is ready/active.
        """
        self.require()
        tag = int(getattr(item, "tag", item))
        hwnd = int(self._rawWinId(tag) or 0)
        if not hwnd:
            return None
        user32 = _windows_user32()
        if user32 is None:
            return True
        try:
            valid, visible = self._window_valid_visible(user32, hwnd)
            if not valid or not visible:
                return None
            owner_hwnd = int(self._desiredOwnerHwnd(tag) or 0)
            if not owner_hwnd:
                owner_hwnd = int(self._owner_from_child(user32, hwnd) or 0)
            user32.GetForegroundWindow.restype = wintypes.HWND
            foreground = int(user32.GetForegroundWindow() or 0)
            if foreground not in tuple(value for value in (hwnd, owner_hwnd) if value):
                return False
            handle = wintypes.HWND(hwnd)
            if foreground != hwnd:
                user32.BringWindowToTop.argtypes = [wintypes.HWND]
                user32.BringWindowToTop.restype = wintypes.BOOL
                user32.SetForegroundWindow.argtypes = [wintypes.HWND]
                user32.SetForegroundWindow.restype = wintypes.BOOL
                user32.BringWindowToTop(handle)
                user32.SetForegroundWindow(handle)
            user32.SetActiveWindow.argtypes = [wintypes.HWND]
            user32.SetActiveWindow.restype = wintypes.HWND
            user32.SetFocus.argtypes = [wintypes.HWND]
            user32.SetFocus.restype = wintypes.HWND
            user32.SetActiveWindow(handle)
            user32.SetFocus(handle)
            return True
        except Exception:
            return False

    def setResizable(self, item, resizable=True):
        """Set the resize capability of a rendered Win32 native viewport.

        Dear ImGui's ``NoResize`` flag governs the client window only. DearUIQt
        native dialogs are separate decorated GLFW HWNDs, so Windows' resize
        frame and maximize command must be updated explicitly as well.
        """
        self.require()
        hwnd = int(self._rawWinId(item) or 0)
        if not hwnd:
            return False
        user32 = _windows_user32()
        if user32 is None:
            # Non-Windows test/runtime: the retained renderer policy is still
            # authoritative; there is no OS frame to modify.
            return True
        try:
            GWL_STYLE = -16
            WS_THICKFRAME = 0x00040000
            WS_MAXIMIZEBOX = 0x00010000
            mask = WS_THICKFRAME | WS_MAXIMIZEBOX
            getter = (user32.GetWindowLongPtrW if ctypes.sizeof(ctypes.c_void_p) == 8
                      else user32.GetWindowLongW)
            setter = (user32.SetWindowLongPtrW if ctypes.sizeof(ctypes.c_void_p) == 8
                      else user32.SetWindowLongW)
            getter.argtypes = [wintypes.HWND, ctypes.c_int]
            getter.restype = ctypes.c_ssize_t
            setter.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_ssize_t]
            setter.restype = ctypes.c_ssize_t
            current = int(getter(wintypes.HWND(hwnd), GWL_STYLE)) & 0xFFFFFFFF
            if hwnd not in self._native_resize_style_bits:
                self._native_resize_style_bits[hwnd] = current & mask
            if resizable:
                desired = (current & ~mask) | self._native_resize_style_bits.get(hwnd, mask)
            else:
                desired = current & ~mask
            if desired == current:
                return True
            setter(wintypes.HWND(hwnd), GWL_STYLE, ctypes.c_long(desired).value)

            # Notify USER32 that non-client metrics changed without moving,
            # resizing or activating the dialog.
            user32.SetWindowPos.argtypes = [
                wintypes.HWND, wintypes.HWND, ctypes.c_int, ctypes.c_int,
                ctypes.c_int, ctypes.c_int, wintypes.UINT]
            user32.SetWindowPos.restype = wintypes.BOOL
            SWP_NOSIZE = 0x0001
            SWP_NOMOVE = 0x0002
            SWP_NOZORDER = 0x0004
            SWP_NOACTIVATE = 0x0010
            SWP_FRAMECHANGED = 0x0020
            flags = (SWP_NOSIZE | SWP_NOMOVE | SWP_NOZORDER |
                     SWP_NOACTIVATE | SWP_FRAMECHANGED)
            return bool(user32.SetWindowPos(
                wintypes.HWND(hwnd), wintypes.HWND(0), 0, 0, 0, 0, flags))
        except Exception:
            return False


    def setCaptionButtons(self, item, *, allow_minimize=False, allow_maximize=None):
        """Apply Qt-like minimize/maximize caption policy to a native viewport.

        Owned QDialogs should not expose an independent minimize command by
        default: Windows removes owned windows from the taskbar, so minimizing
        one can make a modal dialog effectively undiscoverable. Explicit tool
        windows may opt back in with ``ALLOW_MINIMIZE=True``.
        """
        self.require()
        hwnd = int(self._rawWinId(item) or 0)
        if not hwnd:
            return False
        user32 = _windows_user32()
        if user32 is None:
            return True
        try:
            GWL_STYLE = -16
            WS_MINIMIZEBOX = 0x00020000
            WS_MAXIMIZEBOX = 0x00010000
            getter = (user32.GetWindowLongPtrW if ctypes.sizeof(ctypes.c_void_p) == 8
                      else user32.GetWindowLongW)
            setter = (user32.SetWindowLongPtrW if ctypes.sizeof(ctypes.c_void_p) == 8
                      else user32.SetWindowLongW)
            getter.argtypes = [wintypes.HWND, ctypes.c_int]
            getter.restype = ctypes.c_ssize_t
            setter.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_ssize_t]
            setter.restype = ctypes.c_ssize_t
            current = int(getter(wintypes.HWND(hwnd), GWL_STYLE)) & 0xFFFFFFFF
            desired = current
            if allow_minimize:
                desired |= WS_MINIMIZEBOX
            else:
                desired &= ~WS_MINIMIZEBOX
            if allow_maximize is not None:
                if allow_maximize:
                    desired |= WS_MAXIMIZEBOX
                else:
                    desired &= ~WS_MAXIMIZEBOX
            if desired == current:
                return True
            setter(wintypes.HWND(hwnd), GWL_STYLE, ctypes.c_long(desired).value)
            user32.SetWindowPos.argtypes = [
                wintypes.HWND, wintypes.HWND, ctypes.c_int, ctypes.c_int,
                ctypes.c_int, ctypes.c_int, wintypes.UINT]
            user32.SetWindowPos.restype = wintypes.BOOL
            flags = 0x0001 | 0x0002 | 0x0004 | 0x0010 | 0x0020
            return bool(user32.SetWindowPos(
                wintypes.HWND(hwnd), wintypes.HWND(0), 0, 0, 0, 0, flags))
        except Exception:
            return False

    def centerBeforeShow(self, item, *, width, height, owner=None, owner_hwnd=0):
        """Position an unshown ImGui window using its future native frame.

        ImGui positions describe the client origin. Centering only the client
        rectangle then moving the decorated HWND after render exposes two
        different positions. Calculate the caption/borders before first Begin
        instead, using the same decorated/resizable style as ImGui's GLFW host.
        """
        user32 = _windows_user32()
        if user32 is None or not self.isEnabled():
            return None
        try:
            if owner is not None:
                owner_hwnd = int(self.winId(owner) or owner_hwnd or 0)
            if not owner_hwnd:
                return None
            owner_handle = wintypes.HWND(int(owner_hwnd))
            user32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
            user32.GetWindowRect.restype = wintypes.BOOL
            owner_rect = wintypes.RECT()
            if not user32.GetWindowRect(owner_handle, ctypes.byref(owner_rect)):
                return None
            frame = wintypes.RECT(0, 0, int(width), int(height))
            # GLFW: CLIPSIBLINGS|CLIPCHILDREN|CAPTION|SYSMENU|MINIMIZEBOX|
            # MAXIMIZEBOX|THICKFRAME, EX_APPWINDOW. No desktop focus heuristics.
            style, ex_style = 0x06CF0000, 0x00040000
            adjust = getattr(user32, "AdjustWindowRectExForDpi", None)
            get_dpi = getattr(user32, "GetDpiForWindow", None)
            if adjust is not None and get_dpi is not None:
                get_dpi.argtypes = [wintypes.HWND]
                get_dpi.restype = wintypes.UINT
                adjust.argtypes = [ctypes.POINTER(wintypes.RECT), wintypes.DWORD,
                                   wintypes.BOOL, wintypes.DWORD, wintypes.UINT]
                adjust.restype = wintypes.BOOL
                adjusted = adjust(ctypes.byref(frame), style, False, ex_style,
                                  int(get_dpi(owner_handle) or 96))
            else:
                adjust = user32.AdjustWindowRectEx
                adjust.argtypes = [ctypes.POINTER(wintypes.RECT), wintypes.DWORD,
                                   wintypes.BOOL, wintypes.DWORD]
                adjust.restype = wintypes.BOOL
                adjusted = adjust(ctypes.byref(frame), style, False, ex_style)
            if not adjusted:
                return None
            from ..dialogs.placement import centered_over
            left, top = centered_over(
                (owner_rect.left, owner_rect.top,
                 owner_rect.right - owner_rect.left, owner_rect.bottom - owner_rect.top),
                (frame.right - frame.left, frame.bottom - frame.top),
                _owner_monitor_work_area(user32, owner_hwnd))
            position = (left - frame.left, top - frame.top)
            self.backend.set_item_pos(getattr(item, "tag", item), position)
            return position
        except Exception:
            return None

    def centerOverOwner(self, item, *, owner_hwnd=0):
        """Center a rendered native modal over its real Win32 owner frame.

        The HWND does not exist until the platform-viewport render. Using
        GetWindowRect also includes title bars/DPI-scaled non-client chrome,
        unlike the provisional renderer item dimensions. No activation, owner
        change, or second message loop is involved.
        """
        user32 = _windows_user32()
        if user32 is None or not self.isEnabled():
            return False
        try:
            child = int(self.winId(item) or 0)
            if not child:
                return False
            owner = int(owner_hwnd or 0) or self._owner_from_child(user32, child)
            if not owner or owner == child:
                return False
            user32.IsWindow.argtypes = [wintypes.HWND]
            user32.IsWindow.restype = wintypes.BOOL
            if not user32.IsWindow(wintypes.HWND(owner)):
                return False
            user32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
            user32.GetWindowRect.restype = wintypes.BOOL
            owner_rect, child_rect = wintypes.RECT(), wintypes.RECT()
            if (not user32.GetWindowRect(wintypes.HWND(owner), ctypes.byref(owner_rect))
                    or not user32.GetWindowRect(wintypes.HWND(child), ctypes.byref(child_rect))):
                return False
            from ..dialogs.placement import centered_over
            point = centered_over(
                (owner_rect.left, owner_rect.top,
                 owner_rect.right - owner_rect.left, owner_rect.bottom - owner_rect.top),
                (child_rect.right - child_rect.left, child_rect.bottom - child_rect.top),
                _owner_monitor_work_area(user32, owner),
            )
            if point == (child_rect.left, child_rect.top):
                return True
            user32.SetWindowPos.argtypes = [
                wintypes.HWND, wintypes.HWND, ctypes.c_int, ctypes.c_int,
                ctypes.c_int, ctypes.c_int, wintypes.UINT]
            user32.SetWindowPos.restype = wintypes.BOOL
            # SWP_NOSIZE | SWP_NOZORDER | SWP_NOACTIVATE: don't disturb focus.
            return bool(user32.SetWindowPos(
                wintypes.HWND(child), wintypes.HWND(0),
                point[0], point[1], 0, 0, 0x0001 | 0x0004 | 0x0010))
        except Exception:
            return False

    def containsGlobalPoint(self, item, point):
        """Native z-order hit test, including child HWNDs, without activation."""
        user32 = _windows_user32()
        if user32 is None:
            return False
        try:
            hwnd = int(self.winId(item) or 0)
            if not hwnd:
                return False
            user32.WindowFromPoint.argtypes = [wintypes.POINT]
            user32.WindowFromPoint.restype = wintypes.HWND
            user32.GetAncestor.argtypes = [wintypes.HWND, wintypes.UINT]
            user32.GetAncestor.restype = wintypes.HWND
            hit = user32.WindowFromPoint(wintypes.POINT(int(point[0]), int(point[1])))
            return bool(hit and int(user32.GetAncestor(hit, 2) or hit) == hwnd)
        except Exception:
            return False

    @staticmethod
    def _owner_from_child(user32, child_hwnd):
        try:
            user32.GetWindow.argtypes = [wintypes.HWND, wintypes.UINT]
            user32.GetWindow.restype = wintypes.HWND
            return int(user32.GetWindow(wintypes.HWND(child_hwnd), 4) or 0)  # GW_OWNER
        except Exception:
            return 0

    @staticmethod
    def _window_valid_visible(user32, hwnd):
        try:
            user32.IsWindow.argtypes = [wintypes.HWND]
            user32.IsWindow.restype = wintypes.BOOL
            user32.IsWindowVisible.argtypes = [wintypes.HWND]
            user32.IsWindowVisible.restype = wintypes.BOOL
            handle = wintypes.HWND(int(hwnd))
            return bool(user32.IsWindow(handle)), bool(user32.IsWindowVisible(handle))
        except Exception:
            return False, False

    @staticmethod
    def _activate_owner(user32, owner_hwnd, *, raise_z_order=True):
        """Activate one already-enabled owner without TOPMOST side effects."""
        owner = wintypes.HWND(int(owner_hwnd))
        try:
            if raise_z_order:
                user32.BringWindowToTop.argtypes = [wintypes.HWND]
                user32.BringWindowToTop.restype = wintypes.BOOL
                user32.BringWindowToTop(owner)
            user32.SetForegroundWindow.argtypes = [wintypes.HWND]
            user32.SetForegroundWindow.restype = wintypes.BOOL
            user32.SetActiveWindow.argtypes = [wintypes.HWND]
            user32.SetActiveWindow.restype = wintypes.HWND
            user32.SetFocus.argtypes = [wintypes.HWND]
            user32.SetFocus.restype = wintypes.HWND
            user32.SetForegroundWindow(owner)
            user32.SetActiveWindow(owner)
            user32.SetFocus(owner)
            return True
        except Exception:
            return False

    def disarmModalBeforeHide(self, item, *, enable_owner=True):
        """Stop this native window from keeping its Win32 owner disabled.

        Native modality is renderer-owned: ``synchronizeOwners()`` disables an
        owner while a configured modal secondary window remains visible.  A
        QDialog close happens inside an input callback, before the next platform
        render can reconcile that bookkeeping.  Mark this window non-modal
        immediately, then (when no sibling modal is active) re-enable its actual
        owner HWND.  This mirrors Qt's synchronous modality release and prevents
        a closed dialog from leaving the main WinUx window unclickable.
        """
        if not self.isEnabled():
            return False
        tag = int(getattr(item, "tag", item))
        if not tag:
            return False

        owner_tag = (int(self._configured_owner_tag or 0)
                     if tag == int(self._configured_item_tag or 0) else 0)
        try:
            # Update the renderer-side registry *before* the next render.
            # Otherwise synchronizeOwners() can disable the owner again after
            # Python has already begun the close transaction.
            self.extension.dearuiqt_configure_native_window(tag, owner_tag, False)
        except Exception:
            return False

        if not enable_owner:
            return True
        user32 = _windows_user32()
        if user32 is None:
            return True
        try:
            child_hwnd = int(self._rawWinId(tag) or 0)
            owner_hwnd = self._owner_from_child(user32, child_hwnd) if child_hwnd else 0
            if not owner_hwnd:
                owner_hwnd = self._desiredOwnerHwnd(tag)
            if not owner_hwnd or owner_hwnd == child_hwnd:
                return True
            owner = wintypes.HWND(int(owner_hwnd))
            user32.IsWindow.argtypes = [wintypes.HWND]
            user32.IsWindow.restype = wintypes.BOOL
            if not user32.IsWindow(owner):
                return True
            user32.IsWindowEnabled.argtypes = [wintypes.HWND]
            user32.IsWindowEnabled.restype = wintypes.BOOL
            user32.EnableWindow.argtypes = [wintypes.HWND, wintypes.BOOL]
            user32.EnableWindow.restype = wintypes.BOOL
            if not user32.IsWindowEnabled(owner):
                user32.EnableWindow(owner, True)
            return True
        except Exception:
            return False

    def beginOwnerClose(self, item):
        """Capture and perform the pre-hide half of native owner restoration.

        ImGui/GLFW destroys a secondary viewport during the *following render*;
        activating the owner only before ``hide_item`` is therefore insufficient
        because platform-window teardown can change desktop foreground again.
        The returned lease is later consumed by :meth:`repairOwnerAfterHide`.

        When another application already owns foreground this captures only a
        visibility-repair lease and never activates WinUx.
        """
        user32 = _windows_user32()
        if user32 is None or not self.isEnabled():
            return None
        try:
            child_hwnd = int(self.winId(item) or 0)
            if not child_hwnd:
                return None
            owner_hwnd = self._owner_from_child(user32, child_hwnd)
            if not owner_hwnd or owner_hwnd == child_hwnd:
                return None

            owner_live, owner_visible = self._window_valid_visible(user32, owner_hwnd)
            if not owner_live:
                return None

            user32.GetForegroundWindow.argtypes = []
            user32.GetForegroundWindow.restype = wintypes.HWND
            foreground = int(user32.GetForegroundWindow() or 0)
            return_foreground = foreground in (child_hwnd, owner_hwnd)
            lease = _OwnerCloseLease(
                child_hwnd=child_hwnd,
                owner_hwnd=owner_hwnd,
                owner_was_visible=bool(owner_visible),
                return_foreground=bool(return_foreground),
                last_input_tick=_last_input_tick(user32),
                process_id=int(os.getpid()),
            )

            if foreground != child_hwnd:
                # Owner already active, or the user moved to another app.  The
                # post-render phase may still repair accidental owner hiding but
                # will not steal foreground in the latter case.
                return lease

            owner = wintypes.HWND(owner_hwnd)
            user32.IsWindowEnabled.argtypes = [wintypes.HWND]
            user32.IsWindowEnabled.restype = wintypes.BOOL
            user32.EnableWindow.argtypes = [wintypes.HWND, wintypes.BOOL]
            user32.EnableWindow.restype = wintypes.BOOL
            if not user32.IsWindowEnabled(owner):
                # No message pump/render occurs between this enable and the
                # immediate hide request. The renderer reconciles modal-disable
                # bookkeeping in the same following frame.
                user32.EnableWindow(owner, True)
            self._activate_owner(user32, owner_hwnd, raise_z_order=True)
            return lease
        except Exception:
            return None

    def repairOwnerAfterHide(self, lease):
        """Verify owner visibility/activation after the child viewport is gone.

        Return ``None`` while the native child is still visibly tearing down so
        the caller can retry on a later rendered frame. Any boolean result is
        terminal.  Foreground is restored only when the close started while the
        dialog/owner owned foreground *and* no newer physical input occurred.
        This distinguishes Windows/GLFW's automatic fallback to another app
        from a real Alt-Tab/click performed by the user after pressing OK/Cancel.
        """
        if not isinstance(lease, _OwnerCloseLease):
            return False
        user32 = _windows_user32()
        if user32 is None or not self.isEnabled():
            return False
        try:
            child_live, child_visible = self._window_valid_visible(
                user32, lease.child_hwnd)
            if child_live and child_visible:
                return None

            owner_live, owner_visible = self._window_valid_visible(
                user32, lease.owner_hwnd)
            if not owner_live:
                return False

            owner = wintypes.HWND(lease.owner_hwnd)
            # A secondary viewport teardown can occasionally hide the primary
            # GLFW viewport. Restore the visibility it had before the dialog,
            # without activation, even if the user has switched applications.
            if lease.owner_was_visible and not owner_visible:
                show = getattr(user32, "ShowWindow", None)
                if show is not None:
                    show.argtypes = [wintypes.HWND, ctypes.c_int]
                    show.restype = wintypes.BOOL
                    show(owner, 4)  # SW_SHOWNOACTIVATE
                    owner_live, owner_visible = self._window_valid_visible(
                        user32, lease.owner_hwnd)

            if not lease.return_foreground:
                return True

            # Any input newer than the OK/Cancel/close gesture means the user
            # explicitly interacted elsewhere. Never fight that choice.
            current_tick = _last_input_tick(user32)
            if (lease.last_input_tick is not None and current_tick is not None
                    and current_tick != lease.last_input_tick):
                return True

            user32.IsWindowEnabled.argtypes = [wintypes.HWND]
            user32.IsWindowEnabled.restype = wintypes.BOOL
            if not user32.IsWindowEnabled(owner):
                # Modal bookkeeping may need one more platform frame. Do not
                # force-enable here because another modal may legitimately own
                # the same parent.
                return None

            user32.GetForegroundWindow.argtypes = []
            user32.GetForegroundWindow.restype = wintypes.HWND
            foreground = int(user32.GetForegroundWindow() or 0)
            if foreground == lease.owner_hwnd:
                # Foreground is correct; repair keyboard focus only, avoiding an
                # unnecessary Z-order raise/desktop flash.
                self._activate_owner(user32, lease.owner_hwnd, raise_z_order=False)
                return True

            if foreground and foreground != lease.child_hwnd:
                foreground_pid = _window_process_id(user32, foreground)
                if foreground_pid == lease.process_id:
                    # A new same-process dialog/tool became active during this
                    # close transaction. It supersedes returning to the owner.
                    return True

            # With no new physical input, a foreign foreground here is the
            # Windows/GLFW teardown fallback that triggered the reported bug.
            # Return activation to the captured owner, not to a foreground-
            # re-resolved arbitrary window.
            if owner_visible:
                self._activate_owner(user32, lease.owner_hwnd, raise_z_order=True)
            return True
        except Exception:
            return False

    def handoffOwnerBeforeHide(self, item):
        """Backward-compatible immediate owner hand-off API.

        New QDialog lifecycle code keeps the returned lease from
        :meth:`beginOwnerClose` and verifies it after the native render.
        """
        lease = self.beginOwnerClose(item)
        if lease is None or not lease.return_foreground:
            return False
        user32 = _windows_user32()
        if user32 is None:
            return False
        try:
            user32.GetForegroundWindow.argtypes = []
            user32.GetForegroundWindow.restype = wintypes.HWND
            return int(user32.GetForegroundWindow() or 0) == lease.owner_hwnd
        except Exception:
            return False

    begin_owner_close = beginOwnerClose
    repair_owner_after_hide = repairOwnerAfterHide
    handoff_owner_before_hide = handoffOwnerBeforeHide
