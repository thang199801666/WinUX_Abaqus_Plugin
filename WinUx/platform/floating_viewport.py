"""Win32 lifecycle for DPG viewports, including invisible first-frame setup."""
from __future__ import annotations

import ctypes
from ctypes import wintypes
import os

from .native_dialog_host import (
    attach_native_owner, apply_native_qt_chrome, handoff_owner_before_close,
    prepare_owned_dialog_stack,
)

WM_CREATE = 0x0001
WM_SHOWWINDOW = 0x0018
WM_CLOSE = 0x0010
DWMWA_CLOAK = 13
DWMWA_CLOAKED = 14
SW_HIDE = 0
SW_SHOWNOACTIVATE = 4


def window_rect(hwnd):
    if os.name != "nt" or not hwnd:
        return None
    user32 = ctypes.windll.user32
    user32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
    user32.GetWindowRect.restype = wintypes.BOOL
    rect = wintypes.RECT()
    if not user32.GetWindowRect(hwnd, ctypes.byref(rect)):
        return None
    return rect.left, rect.top, rect.right, rect.bottom


def work_area(owner_hwnd):
    if os.name != "nt":
        return None
    class MonitorInfo(ctypes.Structure):
        _fields_ = [("cbSize", wintypes.DWORD), ("monitor", wintypes.RECT),
                    ("work", wintypes.RECT), ("flags", wintypes.DWORD)]
    user32 = ctypes.windll.user32
    user32.MonitorFromWindow.argtypes = [wintypes.HWND, wintypes.DWORD]
    user32.MonitorFromWindow.restype = wintypes.HANDLE
    user32.GetMonitorInfoW.argtypes = [wintypes.HANDLE, ctypes.POINTER(MonitorInfo)]
    user32.GetMonitorInfoW.restype = wintypes.BOOL
    info = MonitorInfo()
    info.cbSize = ctypes.sizeof(info)
    if user32.GetMonitorInfoW(user32.MonitorFromWindow(owner_hwnd or None, 2), ctypes.byref(info)):
        return info.work.left, info.work.top, info.work.right, info.work.bottom
    return None


def centered_position(owner_rect, size, monitor_rect=None):
    """Center the actual outer rectangle, preserving negative monitor origins."""
    rect = owner_rect or monitor_rect
    if rect is None:
        return 100, 100
    left, top, right, bottom = rect
    width, height = size
    x, y = left + (right-left-width)//2, top + (bottom-top-height)//2
    if monitor_rect:
        left, top, right, bottom = monitor_rect
        x = max(left, min(x, right-width))
        y = max(top, min(y, bottom-height))
    return x, y


def cloaked(hwnd):
    if os.name != "nt" or not hwnd:
        return False
    value = wintypes.DWORD()
    result = ctypes.windll.dwmapi.DwmGetWindowAttribute(
        wintypes.HWND(hwnd), DWMWA_CLOAKED, ctypes.byref(value), ctypes.sizeof(value))
    return result == 0 and bool(value.value)


def set_cloaked(hwnd, hidden):
    value = wintypes.BOOL(bool(hidden))
    result = ctypes.windll.dwmapi.DwmSetWindowAttribute(
        wintypes.HWND(hwnd), DWMWA_CLOAK, ctypes.byref(value), ctypes.sizeof(value))
    if result != 0:
        raise OSError("Could not prepare the floating viewport invisibly (DWM {}).".format(result))


def set_native_window_visible(hwnd, visible):
    """Show/hide one viewport without implicitly activating it."""
    if os.name != "nt" or not hwnd:
        return False
    try:
        user32 = ctypes.windll.user32
        user32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
        user32.ShowWindow.restype = wintypes.BOOL
        user32.ShowWindow(
            wintypes.HWND(int(hwnd)),
            SW_SHOWNOACTIVATE if bool(visible) else SW_HIDE,
        )
        return True
    except Exception:
        return False


class ViewportCreationGuard:
    """Cloak the HWND during WM_CREATE, before DPG's first ShowWindow call.

    A current-thread hook is scoped to show_viewport only; no desktop-wide hook
    is installed. DPG can render its warm-up frames while DWM hides the window.
    """
    def __init__(self):
        self.hwnd = None
        self.events = []
        self._hook = None
        self._activation_hook = None
        self._error = None

    def __enter__(self):
        if os.name != "nt":
            return self
        class CallWndRet(ctypes.Structure):
            _fields_ = [("result", ctypes.c_ssize_t), ("lparam", wintypes.LPARAM),
                        ("wparam", wintypes.WPARAM), ("message", wintypes.UINT), ("hwnd", wintypes.HWND)]
        user32 = ctypes.windll.user32
        kernel32 = ctypes.windll.kernel32
        user32.SetWindowsHookExW.argtypes = [ctypes.c_int, ctypes.c_void_p, wintypes.HINSTANCE, wintypes.DWORD]
        user32.SetWindowsHookExW.restype = wintypes.HANDLE
        user32.CallNextHookEx.argtypes = [wintypes.HANDLE, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM]
        user32.CallNextHookEx.restype = ctypes.c_ssize_t
        getter = user32.GetWindowLongPtrW if ctypes.sizeof(ctypes.c_void_p) == 8 else user32.GetWindowLongW
        getter.argtypes = [wintypes.HWND, ctypes.c_int]
        getter.restype = ctypes.c_ssize_t
        callback_type = ctypes.WINFUNCTYPE(ctypes.c_ssize_t, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM)
        def callback(code, wparam, lparam):
            try:
                if code >= 0:
                    message = ctypes.cast(lparam, ctypes.POINTER(CallWndRet)).contents
                    if message.message == WM_CREATE and self.hwnd is None:
                        style = getter(message.hwnd, -16)
                        if not style & 0x40000000 and style & 0x00c00000:  # top-level caption
                            self.hwnd = int(message.hwnd)
                            set_cloaked(self.hwnd, True)
                            self.events.append({"stage": "created", "cloaked": cloaked(self.hwnd)})
                    elif message.message == WM_SHOWWINDOW and message.wparam and message.hwnd == self.hwnd:
                        self.events.append({"stage": "initial_show", "cloaked": cloaked(self.hwnd),
                                            "rect": window_rect(self.hwnd)})
            except Exception as exc:
                self._error = exc
            return user32.CallNextHookEx(self._hook, code, wparam, lparam)
        self._callback = callback_type(callback)
        kernel32.GetCurrentThreadId.restype = wintypes.DWORD
        self._hook = user32.SetWindowsHookExW(12, self._callback, None, kernel32.GetCurrentThreadId())
        if not self._hook:
            raise ctypes.WinError()
        def activation(code, wparam, lparam):
            if code in (5, 9) and self.hwnd and int(wparam) == self.hwnd:
                return 1  # HCBT_ACTIVATE / HCBT_SETFOCUS while startup is invisible
            return user32.CallNextHookEx(self._activation_hook, code, wparam, lparam)
        self._activation_callback = callback_type(activation)
        self._activation_hook = user32.SetWindowsHookExW(5, self._activation_callback, None, kernel32.GetCurrentThreadId())
        if not self._activation_hook:
            user32.UnhookWindowsHookEx.argtypes = [wintypes.HANDLE]
            user32.UnhookWindowsHookEx(self._hook)
            self._hook = None
            raise ctypes.WinError()
        return self

    def __exit__(self, *args):
        if self._activation_hook:
            user32 = ctypes.windll.user32
            user32.UnhookWindowsHookEx.argtypes = [wintypes.HANDLE]
            user32.UnhookWindowsHookEx(self._activation_hook)
            self._activation_hook = None
        if self._hook:
            user32 = ctypes.windll.user32
            user32.UnhookWindowsHookEx.argtypes = [wintypes.HANDLE]
            user32.UnhookWindowsHookEx(self._hook)
            self._hook = None
        if self._error:
            raise self._error
        if os.name == "nt" and not self.hwnd:
            raise RuntimeError("DPG did not create a top-level viewport during startup.")


class NativeViewport:
    """Owned HWND adapter. Configure/center while cloaked, then reveal once."""
    def __init__(self, hwnd, resizable):
        self.hwnd, self._resizable = int(hwnd or 0), bool(resizable)
        self.visible = False
        self._published = False
        self._owner_hwnd = 0
        self._old_proc = None
        self.reveal_count = 0

    def winfo_id(self):
        return self.hwnd

    def update_idletasks(self):
        pass

    def resizable(self):
        return self._resizable, self._resizable

    def configure(self, owner_hwnd):
        self._owner_hwnd = int(owner_hwnd or 0)
        if self._owner_hwnd:
            attach_native_owner(self, self._owner_hwnd)
        # Process-isolated DPG viewports must use the full normal dialog
        # caption rather than WS_EX_TOOLWINDOW.  This gives the Close button
        # the native Windows states automatically: neutral at rest, red on
        # hover, darker red while pressed, and the standard hit target.
        self._winux_force_normal_caption = True
        apply_native_qt_chrome(
            self, window_role="dialog", allow_minimize=False, allow_maximize=False)

    def center(self, owner_hwnd):
        rect = window_rect(self.hwnd)
        if rect:
            x, y = centered_position(window_rect(owner_hwnd), (rect[2]-rect[0], rect[3]-rect[1]), work_area(owner_hwnd))
            user32 = ctypes.windll.user32
            user32.SetWindowPos.argtypes = [wintypes.HWND, wintypes.HWND, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, wintypes.UINT]
            user32.SetWindowPos(self.hwnd, None, x, y, 0, 0, 0x0001 | 0x0004 | 0x0010)

    def stage_publish(self, visible):
        """Map the viewport while it is still DWM-cloaked.

        Hidden GLFW/DPG windows may stop presenting their swap chain.  Revealing
        such a window and uncloaking it in the same call lets DWM briefly compose
        an old/empty surface.  Stage the native ShowWindow first, keep DWM cloak
        active, then let the runtime render the final frame before commit.
        """
        if self._published or os.name != "nt" or not self.hwnd:
            return
        if bool(visible):
            user32 = ctypes.windll.user32
            user32.IsWindowVisible.argtypes = [wintypes.HWND]
            user32.IsWindowVisible.restype = wintypes.BOOL
            if not bool(user32.IsWindowVisible(self.hwnd)):
                self._show(True)

    def flush_compositor(self):
        """Best-effort DWM barrier used only while the viewport is cloaked."""
        if os.name != "nt" or not self.hwnd:
            return False
        try:
            dwmapi = ctypes.windll.dwmapi
            dwmapi.DwmFlush.argtypes = []
            dwmapi.DwmFlush.restype = ctypes.c_long
            return int(dwmapi.DwmFlush()) == 0
        except Exception:
            return False

    def commit_publish(self, visible):
        """Atomically expose the already-rendered viewport to the desktop."""
        if self._published:
            return
        visible = bool(visible)
        if os.name == "nt":
            user32 = ctypes.windll.user32
            user32.IsWindowVisible.argtypes = [wintypes.HWND]
            user32.IsWindowVisible.restype = wintypes.BOOL
            if bool(user32.IsWindowVisible(self.hwnd)) != visible:
                self._show(visible)
            set_cloaked(self.hwnd, False)
        self._published = True
        self.visible = visible
        self.reveal_count += int(visible)

    def publish(self, visible):
        """Compatibility wrapper for callers without a staged render phase."""
        self.stage_publish(visible)
        self.commit_publish(visible)

    def _show(self, visible):
        # Visibility and activation are separate operations. SW_SHOW also
        # activates the viewport, after which ``activate()`` did it again. That
        # double transition can briefly move focus/Z-order through the owner and
        # make WinUx appear to blink. Reveal without activation; the runtime
        # performs one explicit activation after publication.
        set_native_window_visible(self.hwnd, visible)

    def set_visible(self, visible):
        visible = bool(visible)
        if self.visible == visible:
            return False
        self._show(visible)
        self.visible = visible
        self.reveal_count += int(visible)
        return True

    def is_foreground(self):
        if os.name != "nt":
            return False
        user32 = ctypes.windll.user32
        user32.GetForegroundWindow.restype = wintypes.HWND
        return int(user32.GetForegroundWindow() or 0) == self.hwnd

    def handoff_to_owner(self, owner_hwnd):
        """Give foreground to the owner while this owned HWND is still visible."""
        return handoff_owner_before_close(owner_hwnd, self.hwnd)

    def activate(self):
        if os.name == "nt" and self.hwnd:
            # Keep the cross-process owned-window pair in the same normal
            # Z-order group before activation.  This is a no-op if some other
            # application owns foreground, so background work never raises WinUx.
            if self._owner_hwnd:
                prepare_owned_dialog_stack(self._owner_hwnd, self.hwnd)
            user32 = ctypes.windll.user32
            user32.SetForegroundWindow.argtypes = [wintypes.HWND]
            user32.SetForegroundWindow(self.hwnd)

    def install_close_handler(self, view, callback, character_callback=None):
        if os.name != "nt" or not self.hwnd:
            return
        user32 = ctypes.windll.user32
        setter = user32.SetWindowLongPtrW if ctypes.sizeof(ctypes.c_void_p) == 8 else user32.SetWindowLongW
        setter.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_ssize_t]
        setter.restype = ctypes.c_ssize_t
        user32.CallWindowProcW.argtypes = [ctypes.c_void_p, wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
        user32.CallWindowProcW.restype = ctypes.c_ssize_t
        proc_type = ctypes.WINFUNCTYPE(ctypes.c_ssize_t, wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM)
        def procedure(hwnd, message, wparam, lparam):
            if message == WM_CLOSE:
                view.after(0, callback)
                return 0
            if message == 0x0102 and character_callback is not None:  # WM_CHAR
                view.after(0, character_callback, int(wparam))
                return 0
            return user32.CallWindowProcW(self._old_proc, hwnd, message, wparam, lparam)
        self._procedure = proc_type(procedure)
        self._old_proc = setter(self.hwnd, -4, ctypes.cast(self._procedure, ctypes.c_void_p).value)

    def restore_close_handler(self):
        if os.name == "nt" and self._old_proc:
            user32 = ctypes.windll.user32
            setter = user32.SetWindowLongPtrW if ctypes.sizeof(ctypes.c_void_p) == 8 else user32.SetWindowLongW
            setter.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_ssize_t]
            setter.restype = ctypes.c_ssize_t
            setter(self.hwnd, -4, self._old_proc)
            self._old_proc = None
