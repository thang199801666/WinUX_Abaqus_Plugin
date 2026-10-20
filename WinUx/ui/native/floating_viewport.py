"""Win32 lifecycle for DPG viewports, including invisible first-frame setup."""
from __future__ import annotations

import ctypes
from ctypes import wintypes
import os

from .native_dialog_host import (
    attach_native_owner, apply_native_qt_chrome, handoff_owner_before_close,
    prepare_owned_dialog_stack,
    GWL_EXSTYLE, WS_EX_TOOLWINDOW, WS_EX_APPWINDOW,
)

WM_CREATE = 0x0001
WM_SHOWWINDOW = 0x0018
WM_CLOSE = 0x0010
WM_NCHITTEST = 0x0084
WM_NCMOUSEMOVE = 0x00A0
WM_NCMOUSELEAVE = 0x02A2
HTCLOSE = 20
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
    def __init__(self, *, hide_taskbar=False):
        self._hide_taskbar = bool(hide_taskbar)
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
        setter = user32.SetWindowLongPtrW if ctypes.sizeof(ctypes.c_void_p) == 8 else user32.SetWindowLongW
        setter.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_ssize_t]
        setter.restype = ctypes.c_ssize_t
        callback_type = ctypes.WINFUNCTYPE(ctypes.c_ssize_t, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM)
        def callback(code, wparam, lparam):
            try:
                if code >= 0:
                    message = ctypes.cast(lparam, ctypes.POINTER(CallWndRet)).contents
                    if message.message == WM_CREATE and self.hwnd is None:
                        style = getter(message.hwnd, -16)
                        if not style & 0x40000000 and style & 0x00c00000:  # top-level caption
                            self.hwnd = int(message.hwnd)
                            if self._hide_taskbar:
                                # DWM cloak hides pixels, not shell identity. Set
                                # this before GLFW's initial ShowWindow so idle
                                # prewarm workers never acquire a taskbar button.
                                ex_style = getter(message.hwnd, GWL_EXSTYLE)
                                setter(message.hwnd, GWL_EXSTYLE,
                                       (ex_style | WS_EX_TOOLWINDOW) & ~WS_EX_APPWINDOW)
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


def wake_native_window(hwnd):
    """Wake GLFW's hidden-window event wait after an IPC close/visibility command."""
    if os.name == "nt" and hwnd:
        user32 = ctypes.windll.user32
        user32.PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
        user32.PostMessageW(hwnd, 0, 0, 0)  # WM_NULL: no input or close side effects.


def window_dpi(hwnd):
    """Return a known native DPI, or zero to select conservative layout."""
    if os.name != "nt" or not hwnd:
        return 0
    function = getattr(ctypes.windll.user32, "GetDpiForWindow", None)
    if function is None:
        return 0
    function.argtypes = [wintypes.HWND]
    function.restype = wintypes.UINT
    return int(function(hwnd))


class NativeViewport:
    """Owned HWND adapter. Configure/center while cloaked, then reveal once."""
    def __init__(self, hwnd, resizable):
        self.hwnd, self._resizable = int(hwnd or 0), bool(resizable)
        self.visible = False
        self._published = False
        self._owner_hwnd = 0
        self._old_proc = None
        # Win32 owns the non-client Close button.  GLFW can occasionally emit
        # a stale WM_NCMOUSELEAVE while its per-frame event pump is running,
        # even though the cursor is still physically over HTCLOSE.  If that
        # leave reaches DefWindowProc, DWM clears the red hover state and the
        # next WM_NCMOUSEMOVE paints it again, producing a continuous blink.
        # Keep only the tiny bit of state needed to reject that stale leave.
        self._caption_close_hover = False
        self.reveal_count = 0

    def winfo_id(self):
        return self.hwnd

    def update_idletasks(self):
        pass

    def resizable(self):
        return self._resizable, self._resizable

    def configure(self, owner_hwnd, *, hide_taskbar=False, allow_minimize=False, allow_maximize=False):
        self._owner_hwnd = int(owner_hwnd or 0)
        if self._owner_hwnd:
            attach_native_owner(self, self._owner_hwnd)
        # Claimed DPG viewports use the full normal dialog caption. Idle
        # workers keep WS_EX_TOOLWINDOW so the shell ignores their mapped HWND.
        # The normal caption gives the Close button
        # the native Windows states automatically: neutral at rest, red on
        # hover, darker red while pressed, and the standard hit target.
        self._winux_force_normal_caption = not hide_taskbar
        apply_native_qt_chrome(
            self, window_role="tool" if hide_taskbar else "dialog",
            allow_minimize=bool(allow_minimize) and not hide_taskbar,
            allow_maximize=bool(allow_maximize) and not hide_taskbar)

    def center(self, owner_hwnd):
        rect = window_rect(self.hwnd)
        if rect:
            x, y = centered_position(window_rect(owner_hwnd), (rect[2]-rect[0], rect[3]-rect[1]), work_area(owner_hwnd))
            user32 = ctypes.windll.user32
            user32.SetWindowPos.argtypes = [wintypes.HWND, wintypes.HWND, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, wintypes.UINT]
            user32.SetWindowPos(self.hwnd, None, x, y, 0, 0, 0x0001 | 0x0004 | 0x0010)

    def prepare_rendering(self):
        """Resume a warm swap-chain under its cloak without activating it."""
        if self._published or os.name != "nt" or not self.hwnd or not cloaked(self.hwnd):
            return False
        # A SW_HIDE worker can incur the driver's hidden-window presentation
        # throttle on each settle frame. Mapping it under DWM cloak avoids that
        # delay while keeping both its pixels and keyboard activation private.
        self.stage_publish(True)
        return True

    def position_for_tearoff(self, anchor):
        """Place the cloaked dock's native caption under the grabbed point."""
        from .native_dock_gesture import cursor_position
        point, rect = cursor_position(), window_rect(self.hwnd)
        if not point or not rect or not isinstance(anchor, (list, tuple)) or len(anchor) != 2:
            return False
        try:
            ax = max(0, min(int(anchor[0]), rect[2] - rect[0] - 24))
            ay = max(4, min(int(anchor[1]), 24))
        except (TypeError, ValueError, OverflowError):
            return False
        user32 = ctypes.windll.user32
        user32.SetWindowPos.argtypes = [wintypes.HWND, wintypes.HWND, ctypes.c_int,
                                      ctypes.c_int, ctypes.c_int, ctypes.c_int, wintypes.UINT]
        user32.SetWindowPos(self.hwnd, None, point[0] - ax, point[1] - ay, 0, 0,
                            0x0001 | 0x0004 | 0x0010)
        return True

    def begin_dock_move(self):
        """Continue a tear-off only while the physical initiating press is held."""
        from .native_dock_gesture import cursor_position
        if os.name != "nt" or not self.visible or not self.is_foreground():
            return False
        user32 = ctypes.windll.user32
        user32.GetAsyncKeyState.argtypes = [ctypes.c_int]
        user32.GetAsyncKeyState.restype = ctypes.c_short
        if not (int(user32.GetAsyncKeyState(1)) & 0x8000):
            return False
        point = cursor_position()
        if point is None:
            return False
        user32.PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
        packed = (point[0] & 0xffff) | ((point[1] & 0xffff) << 16)
        return bool(user32.PostMessageW(self.hwnd, 0x00A1, 2, packed))

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
            user32 = ctypes.windll.user32
            user32.IsWindowEnabled.argtypes = [wintypes.HWND]
            user32.IsWindowEnabled.restype = wintypes.BOOL
            if not user32.IsWindowEnabled(self.hwnd):
                # A nested native dialog owns activation until it releases this
                # viewport. Never raise/restore/focus its disabled parent.
                return
            # Keep the cross-process owned-window pair in the same normal
            # Z-order group before activation.  This is a no-op if some other
            # application owns foreground, so background work never raises WinUx.
            if self._owner_hwnd:
                prepare_owned_dialog_stack(self._owner_hwnd, self.hwnd)
            user32.IsIconic.argtypes = [wintypes.HWND]
            user32.IsIconic.restype = wintypes.BOOL
            if user32.IsIconic(self.hwnd):
                user32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
                user32.ShowWindow(self.hwnd, 9)  # SW_RESTORE for an explicitly reactivated tool.
            user32.SetForegroundWindow.argtypes = [wintypes.HWND]
            user32.SetForegroundWindow(self.hwnd)
            # Foreground/Z-order alone does not establish this UI thread's
            # input focus, especially when claiming a cloaked prewarm window.
            # GLFW must receive WM_SETFOCUS before it forwards pointer/keyboard
            # input to ImGui. Do not activate over another foreground app.
            user32.GetForegroundWindow.argtypes = []
            user32.GetForegroundWindow.restype = wintypes.HWND
            foreground = int(user32.GetForegroundWindow() or 0)
            if foreground in (0, self.hwnd):
                user32.SetActiveWindow.argtypes = [wintypes.HWND]
                user32.SetActiveWindow.restype = wintypes.HWND
                user32.SetFocus.argtypes = [wintypes.HWND]
                user32.SetFocus.restype = wintypes.HWND
                user32.SetActiveWindow(self.hwnd)
                user32.SetFocus(self.hwnd)

    def install_close_handler(self, view, callback, character_callback=None, pointer_callback=None,
                              dock_callback=None):
        if os.name != "nt" or not self.hwnd:
            return
        user32 = ctypes.windll.user32
        setter = user32.SetWindowLongPtrW if ctypes.sizeof(ctypes.c_void_p) == 8 else user32.SetWindowLongW
        setter.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_ssize_t]
        setter.restype = ctypes.c_ssize_t
        user32.CallWindowProcW.argtypes = [ctypes.c_void_p, wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
        user32.CallWindowProcW.restype = ctypes.c_ssize_t
        proc_type = ctypes.WINFUNCTYPE(ctypes.c_ssize_t, wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM)

        def _cursor_is_still_over_native_close(hwnd):
            """Verify HTCLOSE at the current cursor without trusting a stale leave."""
            try:
                point = wintypes.POINT()
                user32.GetCursorPos.argtypes = [ctypes.POINTER(wintypes.POINT)]
                user32.GetCursorPos.restype = wintypes.BOOL
                if not user32.GetCursorPos(ctypes.byref(point)):
                    return False
                user32.GetForegroundWindow.argtypes = []
                user32.GetForegroundWindow.restype = wintypes.HWND
                if int(user32.GetForegroundWindow() or 0) != int(hwnd):
                    return False
                user32.IsWindowEnabled.argtypes = [wintypes.HWND]
                user32.IsWindowEnabled.restype = wintypes.BOOL
                if not user32.IsWindowEnabled(hwnd):
                    return False
                packed = ((int(point.x) & 0xffff) |
                          ((int(point.y) & 0xffff) << 16))
                user32.SendMessageW.argtypes = [
                    wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
                user32.SendMessageW.restype = ctypes.c_ssize_t
                return int(user32.SendMessageW(
                    hwnd, WM_NCHITTEST, 0, packed)) == HTCLOSE
            except Exception:
                return False

        def procedure(hwnd, message, wparam, lparam):
            # Let USER32/DWM keep ownership of the caption Close-button visual
            # state.  Some GLFW/Windows combinations generate an extra
            # WM_NCMOUSELEAVE during the render/event pump.  Suppressing only a
            # leave that hit-testing proves is stale prevents the native red
            # hover from alternating on/off every frame, while a real pointer
            # departure, deactivation or disable still flows to the original
            # GLFW window procedure unchanged.
            if message == WM_NCMOUSEMOVE:
                self._caption_close_hover = int(wparam) == HTCLOSE
            elif message == WM_NCMOUSELEAVE:
                if (self._caption_close_hover and
                        _cursor_is_still_over_native_close(hwnd)):
                    return 0
                self._caption_close_hover = False

            if dock_callback is not None:
                if message == 0x00A3 and int(wparam) == 2:  # WM_NCLBUTTONDBLCLK / HTCAPTION
                    view.after(0, dock_callback, "toggle", None)
                    return 0
                if message == 0x0112 and (int(wparam) & 0xfff0) in (0xf010, 0xf000):
                    # DefWindowProc runs a nested OS move/size loop. Publish its
                    # mode as an HWND property so the parent can draw preview
                    # while this child's ordinary DPG/IPC drain is paused.
                    from .native_dock_gesture import set_gesture, cursor_position
                    # Keyboard system-menu Move does not represent a pointer
                    # drop. Mouse caption move has HTCAPTION in the low nibble.
                    moving = (int(wparam) & 0xfff0) == 0xf010 and (int(wparam) & 0xf) == 2
                    origin = window_rect(hwnd)
                    set_gesture(hwnd, 1 if moving else 2)
                    try:
                        return user32.CallWindowProcW(self._old_proc, hwnd, message, wparam, lparam)
                    finally:
                        set_gesture(hwnd, 0)
                        # Escape restores the original rectangle. A cancelled
                        # or stationary move must never be interpreted as drop.
                        if moving and origin and window_rect(hwnd) != origin:
                            position = cursor_position()
                            view.after(0, dock_callback, "drop", position)
            if message == 0x0201 and pointer_callback is not None:  # WM_LBUTTONDOWN
                # Snapshot the press, not GetCursorPos at deferred delivery:
                # GLFW/ImGui can still hold the previous lease's mouse position
                # on the first click after a focus handoff.
                x = ctypes.c_short(int(lparam) & 0xffff).value
                y = ctypes.c_short((int(lparam) >> 16) & 0xffff).value
                view.after(0, pointer_callback, "mouse-down", (x, y))
            if message == 0x0020 and (int(lparam) & 0xffff) == 1:  # WM_SETCURSOR / HTCLIENT
                cursor = getattr(view, "_tool_cursor", None)
                handle = cursor.native_handle() if cursor is not None else None
                if handle:
                    user32.SetCursor.argtypes = [wintypes.HANDLE]
                    user32.SetCursor(handle)
                    return 1
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
        from .native_dock_gesture import set_gesture
        if self.hwnd:
            set_gesture(self.hwnd, 0)
        if os.name == "nt" and self._old_proc:
            user32 = ctypes.windll.user32
            setter = user32.SetWindowLongPtrW if ctypes.sizeof(ctypes.c_void_p) == 8 else user32.SetWindowLongW
            setter.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_ssize_t]
            setter.restype = ctypes.c_ssize_t
            setter(self.hwnd, -4, self._old_proc)
            self._old_proc = None
        self._caption_close_hover = False
