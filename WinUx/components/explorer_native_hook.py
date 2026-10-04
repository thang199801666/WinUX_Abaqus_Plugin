"""Explorer viewport WNDPROC chain, cursor geometry and shell-drop lifetime."""
from __future__ import annotations
import ctypes
from ctypes import wintypes
import os
import sys
import time
from ..diagnostics import log_event, log_exception
from ..platform.windows_cursors import WindowsCursorFile


class ExplorerNativeHook:
    _drop_owners = {}

    def __init__(self, view, backend, registry):
        self.view, self.backend, self.registry = view, backend, registry
        self._native_hwnd = None
        self._native_old_wndproc = None
        self._native_wndproc_callback = None
        self._native_cursor_sizewe = None
        self._native_cursor_move = None
        self._native_cursor_copy = None
        self._native_cursor_no = None
        self._native_cursor_arrow = None
        self._native_header_screen_rect = None
        self._native_separator_screen_x = ()
        self._native_cursor_hook_active = False
        self._native_drop_enabled = False

    def _find_own_top_level_hwnd(self):
        """Locate this process's GLFW-created top-level window handle.

        Different Dear PyGui releases expose different (or no) getters for
        the native window handle, so don't depend on one. Instead, enumerate
        top-level windows and keep the ones owned by our own process -- this
        works the same way regardless of which DPG version is installed.
        """
        user32 = ctypes.windll.user32
        kernel32 = ctypes.windll.kernel32

        kernel32.GetCurrentProcessId.argtypes = []
        kernel32.GetCurrentProcessId.restype = wintypes.DWORD

        WNDENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
        user32.EnumWindows.argtypes = [WNDENUMPROC, wintypes.LPARAM]
        user32.EnumWindows.restype = wintypes.BOOL

        user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
        user32.GetWindowThreadProcessId.restype = wintypes.DWORD
        user32.IsWindowVisible.argtypes = [wintypes.HWND]
        user32.IsWindowVisible.restype = wintypes.BOOL
        user32.GetWindowTextLengthW.argtypes = [wintypes.HWND]
        user32.GetWindowTextLengthW.restype = ctypes.c_int
        user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
        user32.GetWindowTextW.restype = ctypes.c_int

        pid = kernel32.GetCurrentProcessId()

        title = None
        try:
            title = self.backend.get_viewport_title()
        except Exception:
            title = None

        candidates = []

        def enum_proc(hwnd, lparam):
            found_pid = wintypes.DWORD()
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(found_pid))
            if found_pid.value == pid and user32.IsWindowVisible(hwnd):
                length = user32.GetWindowTextLengthW(hwnd)
                buf = ctypes.create_unicode_buffer(length + 1)
                user32.GetWindowTextW(hwnd, buf, length + 1)
                candidates.append((hwnd, buf.value))
            return True

        user32.EnumWindows(WNDENUMPROC(enum_proc), 0)

        if not candidates:
            return None
        if title:
            for hwnd, text in candidates:
                if text == title:
                    return hwnd
        # Fall back to the first visible top-level window owned by this process.
        return candidates[0][0]

    def _install_native_cursor_hook(self):
        """Install a Win32 ``WM_SETCURSOR`` handler on the DPG viewport.

        Calling ``SetCursor`` from a normal Dear PyGui callback is temporary:
        GLFW selects its own arrow cursor later in the same frame. Returning
        non-zero from ``WM_SETCURSOR`` prevents that default processing and
        keeps the genuine Windows ``IDC_SIZEWE`` cursor visible.
        """
        if os.name != "nt" or self._native_wndproc_callback is not None:
            return

        try:
            hwnd = int(self._find_own_top_level_hwnd() or 0)
        except Exception:
            return
        if not hwnd:
            return

        user32 = ctypes.windll.user32
        shell32 = ctypes.windll.shell32
        is_64bit = ctypes.sizeof(ctypes.c_void_p) == 8
        set_window_long = user32.SetWindowLongPtrW if is_64bit else user32.SetWindowLongW
        set_window_long.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_void_p]
        set_window_long.restype = ctypes.c_void_p

        # ctypes.wintypes never defines LRESULT (unlike LPARAM/WPARAM). It's
        # documented as a signed, pointer-sized integer (LONG_PTR), which
        # c_ssize_t matches on both 32- and 64-bit builds.
        LRESULT = ctypes.c_ssize_t

        user32.CallWindowProcW.argtypes = [
            ctypes.c_void_p, wintypes.HWND, wintypes.UINT,
            wintypes.WPARAM, wintypes.LPARAM,
        ]
        user32.CallWindowProcW.restype = LRESULT
        user32.LoadCursorW.argtypes = [wintypes.HINSTANCE, ctypes.c_void_p]
        # ctypes.wintypes also never defines HCURSOR. It's just a HANDLE
        # (opaque pointer-sized value) like every other Windows handle type.
        HCURSOR = wintypes.HANDLE

        user32.LoadCursorW.restype = HCURSOR
        user32.SetCursor.argtypes = [HCURSOR]
        user32.SetCursor.restype = HCURSOR

        WM_SETCURSOR = 0x0020
        WM_DROPFILES = 0x0233
        HTCLIENT = 1
        GWL_WNDPROC = -4
        IDC_ARROW = 32512
        IDC_SIZEWE = 32644
        IDC_SIZEALL = 32646
        IDC_NO = 32648

        self._native_cursor_arrow = user32.LoadCursorW(None, ctypes.c_void_p(IDC_ARROW))

        # Use the user's current Windows Horizontal Resize cursor.  The cursor
        # scheme stores it in HKCU\Control Panel\Cursors under ``SizeWE``.
        # If the scheme entry is empty/missing, fall back to the standard
        # IDC_SIZEWE cursor supplied by Windows.
        horizontal_resize_cursor = None
        try:
            import winreg
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Control Panel\Cursors") as key:
                cursor_value, _ = winreg.QueryValueEx(key, "SizeWE")
            cursor_value = os.path.expandvars(str(cursor_value or "").strip())
            if cursor_value:
                horizontal_resize_cursor = WindowsCursorFile.load(cursor_value)
        except (ImportError, OSError, ValueError):
            horizontal_resize_cursor = None

        self._native_cursor_sizewe = (
            horizontal_resize_cursor
            or user32.LoadCursorW(None, ctypes.c_void_p(IDC_SIZEWE))
        )
        self._native_cursor_move = user32.LoadCursorW(None, ctypes.c_void_p(IDC_SIZEALL))
        self._native_cursor_no = user32.LoadCursorW(None, ctypes.c_void_p(IDC_NO))
        # Native Windows Move cursor: MAKEINTRESOURCE(32646) / IDC_SIZEALL.
        # Keep it separate from the horizontal resize cursor used by headers.
        self._native_cursor_copy = None
        self._native_hwnd = hwnd

        # Accept legacy shell file drops. Explorer sends WM_DROPFILES to
        # windows registered with DragAcceptFiles; this keeps the receive path
        # dependency-free while the existing CF_HDROP clipboard path handles
        # copy/paste and outbound Explorer interoperability.
        shell32.DragAcceptFiles.argtypes = [wintypes.HWND, wintypes.BOOL]
        shell32.DragAcceptFiles.restype = None
        shell32.DragQueryFileW.argtypes = [wintypes.HANDLE, wintypes.UINT,
                                           wintypes.LPWSTR, wintypes.UINT]
        shell32.DragQueryFileW.restype = wintypes.UINT
        shell32.DragQueryPoint.argtypes = [wintypes.HANDLE,
                                           ctypes.POINTER(wintypes.POINT)]
        shell32.DragQueryPoint.restype = wintypes.BOOL
        shell32.DragFinish.argtypes = [wintypes.HANDLE]
        shell32.DragFinish.restype = None
        shell32.DragAcceptFiles(wintypes.HWND(hwnd), True)
        self._native_drop_enabled = True
        # Allow the drop message through UIPI when this process runs at a
        # higher integrity level (e.g. elevated) than Windows Explorer.
        # Without this, Explorer drops are silently blocked.
        try:
            user32.ChangeWindowMessageFilterEx.argtypes = [
                wintypes.HWND, wintypes.UINT, wintypes.DWORD,
                ctypes.c_void_p,
            ]
            user32.ChangeWindowMessageFilterEx.restype = wintypes.BOOL
            user32.ChangeWindowMessageFilterEx(
                wintypes.HWND(hwnd), WM_DROPFILES, 1, None)
            user32.ChangeWindowMessageFilterEx(
                wintypes.HWND(hwnd), 0x0049, 1, None)
        except Exception:
            try:
                user32.ChangeWindowMessageFilter.argtypes = [
                    wintypes.UINT, wintypes.DWORD]
                user32.ChangeWindowMessageFilter.restype = wintypes.BOOL
                user32.ChangeWindowMessageFilter(WM_DROPFILES, 1)
                user32.ChangeWindowMessageFilter(0x0049, 1)
            except Exception:
                pass

        WNDPROC = ctypes.WINFUNCTYPE(
            LRESULT, wintypes.HWND, wintypes.UINT,
            wintypes.WPARAM, wintypes.LPARAM,
        )

        def dispatch_wndproc(window, message, wparam, lparam):
            if message == WM_DROPFILES:
                # Never call Dear PyGui from inside the native message handler:
                # stash the shell file list with its screen drop point and let
                # the per-frame layout watch route it on the UI thread, where
                # item rectangles and coordinate variants are reliable.
                try:
                    paths, drop_point = self._read_shell_drop(
                        shell32, wintypes.HANDLE(wparam))
                    if paths:
                        self.registry._PENDING_EXTERNAL_DROPS.append({
                            "paths": paths,
                            "x": float(drop_point.x),
                            "y": float(drop_point.y),
                            "at": time.monotonic(),
                        })
                        log_event(
                            "WM_DROPFILES received by {}: {} file(s) at "
                            "screen ({}, {})".format(
                                self.view.uid, len(paths),
                                int(drop_point.x), int(drop_point.y)))
                except Exception:
                    pass
                return 0

            if message == WM_SETCURSOR and (int(lparam) & 0xFFFF) == HTCLIENT:
                provider = self.registry._external_cursor_provider
                if callable(provider):
                    external_cursor = provider()
                    if external_cursor:
                        user32.SetCursor(external_cursor)
                        return 1

                if self.view._item_drag_active:
                    # Keep the normal Windows arrow while dragging items.
                    # Target validity is communicated by row highlighting and
                    # the drag preview instead of replacing/hiding the cursor.
                    cursor = self._native_cursor_arrow
                    if cursor:
                        user32.SetCursor(cursor)
                        return 1

                # Keep the resize cursor while the pointer is captured, even if
                # the user drags above or below the header.
                if self.view._resize_key is not None and self._native_cursor_sizewe:
                    user32.SetCursor(self._native_cursor_sizewe)
                    return 1

                point = wintypes.POINT()
                if user32.GetCursorPos(ctypes.byref(point)):
                    rect = self._native_header_screen_rect
                    if rect is not None:
                        x0, y0, x1, y1 = rect
                        in_header = x0 <= point.x <= x1 and y0 <= point.y <= y1
                        if in_header:
                            hit = max(8.0, float(self.view.SEPARATOR_HIT))
                            hovering = any(
                                abs(float(point.x) - float(separator_x)) <= hit
                                for separator_x in self._native_separator_screen_x
                            )
                            if hovering:
                                user32.SetCursor(self._native_cursor_sizewe)
                                return 1

            return user32.CallWindowProcW(
                self._native_old_wndproc, window, message, wparam, lparam
            )

        def wndproc(window, message, wparam, lparam):
            # A Python exception must never cross a ctypes WNDPROC boundary.
            # Doing so can terminate the process before sys.excepthook runs.
            try:
                return dispatch_wndproc(window, message, wparam, lparam)
            except BaseException:
                log_exception(
                    "Explorer native cursor WNDPROC callback failed",
                    sys.exc_info(),
                    fatal=False,
                )
                try:
                    return user32.CallWindowProcW(
                        self._native_old_wndproc,
                        window,
                        message,
                        wparam,
                        lparam,
                    )
                except BaseException:
                    return 0

        callback = WNDPROC(wndproc)
        ctypes.set_last_error(0)
        old_proc = set_window_long(hwnd, GWL_WNDPROC, ctypes.cast(callback, ctypes.c_void_p))
        if not old_proc and ctypes.get_last_error():
            if not self._drop_owners.get(hwnd):
                shell32.DragAcceptFiles(wintypes.HWND(hwnd), False)
            self._native_drop_enabled = False
            self._native_hwnd = None
            log_event(
                "Explorer native hook install failed for {}".format(self.view.uid))
            return

        self._native_old_wndproc = old_proc
        self._native_wndproc_callback = callback  # Keep callback alive.
        self._native_cursor_hook_active = True
        self._drop_owners.setdefault(hwnd, set()).add(self)
        log_event(
            "Explorer native hook installed for {} on hwnd={} "
            "(drop accept={})".format(
                self.view.uid, int(hwnd), bool(self._native_drop_enabled)))

    def _read_shell_drop(self, shell32, drop_handle):
        try:
            drop_point = wintypes.POINT()
            if not shell32.DragQueryPoint(
                    drop_handle, ctypes.byref(drop_point)):
                drop_point.x, drop_point.y = 0, 0
            paths = []
            count = int(shell32.DragQueryFileW(
                drop_handle, 0xFFFFFFFF, None, 0))
            for index in range(count):
                length = int(shell32.DragQueryFileW(
                    drop_handle, index, None, 0))
                if length <= 0:
                    continue
                buffer = ctypes.create_unicode_buffer(length + 1)
                if shell32.DragQueryFileW(
                        drop_handle, index, buffer, length + 1):
                    paths.append(buffer.value)
            return paths, drop_point
        finally:
            shell32.DragFinish(drop_handle)

    def _uninstall_native_cursor_hook(self):
        """Restore the WNDPROC when this instance is the active hook.

        Several ListViews subclass the same viewport window. The view destroys
        them in reverse creation order so each hook can restore the preceding
        link in the chain safely.
        """
        if (
            not self._native_cursor_hook_active
            or not self._native_hwnd
            or not self._native_old_wndproc
            or self._native_wndproc_callback is None
        ):
            return False

        try:
            user32 = ctypes.windll.user32
            user32.IsWindow.argtypes = [wintypes.HWND]
            user32.IsWindow.restype = wintypes.BOOL
            if not user32.IsWindow(self._native_hwnd):
                self._forget_native_hook()
                return True
            is_64bit = ctypes.sizeof(ctypes.c_void_p) == 8
            get_window_long = (
                user32.GetWindowLongPtrW
                if is_64bit
                else user32.GetWindowLongW
            )
            set_window_long = (
                user32.SetWindowLongPtrW
                if is_64bit
                else user32.SetWindowLongW
            )
            get_window_long.argtypes = [wintypes.HWND, ctypes.c_int]
            get_window_long.restype = ctypes.c_void_p
            set_window_long.argtypes = [
                wintypes.HWND,
                ctypes.c_int,
                ctypes.c_void_p,
            ]
            set_window_long.restype = ctypes.c_void_p

            GWL_WNDPROC = -4
            current = get_window_long(self._native_hwnd, GWL_WNDPROC)
            callback_address = ctypes.cast(
                self._native_wndproc_callback,
                ctypes.c_void_p,
            ).value
            if int(current or 0) != int(callback_address or 0):
                log_event(
                    "Explorer native cursor hook was not the top WNDPROC; "
                    "restoration was deferred")
                return False

            ctypes.set_last_error(0)
            set_window_long(
                self._native_hwnd,
                GWL_WNDPROC,
                ctypes.c_void_p(int(self._native_old_wndproc)),
            )
            error = ctypes.get_last_error()
            if error:
                raise ctypes.WinError(error)
            owners = self._drop_owners.get(self._native_hwnd, set())
            owners.discard(self)
            if not owners:
                self._drop_owners.pop(self._native_hwnd, None)
                if self._native_drop_enabled:
                    ctypes.windll.shell32.DragAcceptFiles(
                        wintypes.HWND(self._native_hwnd), False)
            self._native_drop_enabled = False
        except Exception:
            log_exception(
                "Failed to restore Explorer native cursor WNDPROC",
                sys.exc_info(),
                fatal=False,
            )
            return False

        self._forget_native_hook()
        return True

    def _forget_native_hook(self):
        owners = self._drop_owners.get(self._native_hwnd)
        if owners is not None:
            owners.discard(self)
            if not owners:
                self._drop_owners.pop(self._native_hwnd, None)
        self._native_cursor_hook_active = False
        self._native_drop_enabled = False
        self._native_wndproc_callback = None
        self._native_old_wndproc = None
        self._native_hwnd = None

    def _update_native_cursor_geometry(self):
        """Cache header and splitter coordinates in physical screen pixels."""
        rect = self.view._safe_item_rect(self.view.header_canvas)
        if rect is None:
            self._native_header_screen_rect = None
            self._native_separator_screen_x = ()
            return

        x0, y0, x1, y1 = rect
        header_width = max(0.0, float(x1) - float(x0))
        header_height = max(0.0, float(y1) - float(y0))

        # Dear PyGui reports item coordinates in viewport-client coordinates,
        # while GetCursorPos() used by the native hook returns screen
        # coordinates. Convert the header origin to screen coordinates before
        # caching the hit-test rectangle; otherwise the splitter is never hit
        # whenever the viewport is not located at screen origin (0, 0).
        if os.name == "nt" and self._native_hwnd:
            try:
                client_origin = wintypes.POINT(int(round(x0)), int(round(y0)))
                if ctypes.windll.user32.ClientToScreen(
                    wintypes.HWND(self._native_hwnd), ctypes.byref(client_origin)
                ):
                    x0 = float(client_origin.x)
                    y0 = float(client_origin.y)
            except Exception:
                pass

        pane_rect = self.view._safe_item_rect(self.view.window_tag)
        pane_w = (
            max(1.0, float(pane_rect[2]) - float(pane_rect[0]))
            if pane_rect is not None else header_width
        )
        total_w = sum(
            self.view._column_widths.get(column["key"], self.view.MIN_COLUMN_WIDTH)
            for column in self.view._visible_columns()
        )
        active_w = min(float(total_w), float(pane_w), header_width)
        self._native_header_screen_rect = (
            float(x0), float(y0), float(x0) + active_w,
            float(y0) + min(header_height, float(self.view.HEADER_HEIGHT)),
        )

        separator_x = []
        running_x = float(x0)
        visible = self.view._visible_columns()
        for column in visible:
            running_x += float(self.view._column_widths.get(column["key"], self.view.MIN_COLUMN_WIDTH))
            # Include every visible divider, including the right edge of the
            # last column, because this implementation allows that edge to grow
            # the total canvas width.
            if running_x <= float(x0) + active_w + self.view.SEPARATOR_HIT:
                separator_x.append(running_x)
        self._native_separator_screen_x = tuple(separator_x)
