"""Native Win32 inline-rename editor.

Dear PyGui exposes no API for programmatic text selection or caret placement,
so an Explorer-style rename (basename pre-selected, caret before the dot) is
impossible with ``add_input_text``. This module hosts a genuine Win32 ``EDIT``
control as an owned popup above the Dear PyGui viewport instead.  A popup is
used deliberately: child HWNDs can be visually covered by GLFW/OpenGL swap
buffers on some Dear PyGui builds, which makes the editor look like an ImGui
selection rather than a real Explorer edit box:

- ``EM_SETSEL`` selects exactly the basename, caret included;
- keyboard, clipboard, undo and IME (Vietnamese input included) behave like
  any native text field;
- Enter/Escape are observed without stealing global shortcuts, because the
  control owns keyboard focus while it is active.

All Win32 access is guarded: anything outside Windows reports failure and the
caller is expected to fall back to the Dear PyGui input. No Dear PyGui API is
used here, so this module stays importable on every platform.
"""

from __future__ import annotations

import ctypes
import os
import re


_BASENAME_PATTERN = re.compile(r"^(.*)(\.[^.]+)$", re.DOTALL)

WS_CHILD = 0x40000000
WS_POPUP = 0x80000000
WS_VISIBLE = 0x10000000
WS_BORDER = 0x00800000

WS_EX_TOOLWINDOW = 0x00000080
ES_LEFT = 0x0000
ES_AUTOHSCROLL = 0x0080

WM_SETFONT = 0x0030
WM_SETFOCUS = 0x0007
WM_KEYDOWN = 0x0100
EM_GETSEL = 0x00B0
EM_SETSEL = 0x00B1
EM_SCROLLCARET = 0x00B7
EM_SETMARGINS = 0x00D3
EC_LEFTMARGIN = 0x0001
EC_RIGHTMARGIN = 0x0002
SWP_NOZORDER = 0x0004
SWP_NOACTIVATE = 0x0010
SWP_SHOWWINDOW = 0x0040

VK_RETURN = 0x0D
VK_ESCAPE = 0x1B

FW_NORMAL = 400
DEFAULT_CHARSET = 1


def split_rename_name(text, is_dir=False):
    """Split a label into Explorer's initially editable basename + extension.

    The extension includes the leading dot.  Directories and single-dot
    dotfiles have no protected extension for the initial rename selection.
    """
    text = str(text or "")
    if is_dir:
        return text, ""
    match = _BASENAME_PATTERN.match(text)
    if match and match.start(2) > 0:
        return text[:match.start(2)], text[match.start(2):]
    return text, ""


def basename_select_end(text, is_dir=False):
    """Return the selection end (UTF-16 units) just before the extension.

    Directories select their whole name. A leading dot without a later
    extension (``.gitignore``) also selects everything, matching Explorer.
    """
    selected, _extension = split_rename_name(text, is_dir)
    return len(selected.encode("utf-16-le")) // 2


class NativeRenameEditor:
    """One-shot Win32 EDIT control used for a single rename gesture."""

    def __init__(self):
        self._hwnd_edit = None
        self._hwnd_parent = None
        self._font = None
        self._old_proc = None
        self._proc_callback = None
        self._pending_action = None
        self._initial_selection = (0, 0)
        self._popup_mode = False

    def is_active(self):
        return self._hwnd_edit is not None

    @staticmethod
    def _create_font_matching_height(gdi32, user32, hwnd, target_height, font_face):
        """Create a GDI font whose rendered line height matches *target_height*.

        ``CreateFontW(-N)`` and Dear ImGui's ``add_font(..., N)`` do not have
        identical visible metrics.  Measure candidate Segoe UI fonts on the
        actual EDIT-window DC and choose the one whose ``GetTextExtentPoint32``
        height for a representative glyph pair is closest to the DPG line
        height supplied by the list view.
        """
        from ctypes import wintypes

        target_height = max(8, int(round(target_height or 0)))
        face = str(font_face or "Segoe UI")
        hdc = None
        best_font = None
        best_score = None
        try:
            user32.GetDC.argtypes = [wintypes.HWND]
            user32.GetDC.restype = wintypes.HDC
            user32.ReleaseDC.argtypes = [wintypes.HWND, wintypes.HDC]
            user32.ReleaseDC.restype = ctypes.c_int
            gdi32.SelectObject.argtypes = [wintypes.HDC, wintypes.HGDIOBJ]
            gdi32.SelectObject.restype = wintypes.HGDIOBJ
            gdi32.GetTextExtentPoint32W.argtypes = [
                wintypes.HDC, wintypes.LPCWSTR, ctypes.c_int,
                ctypes.POINTER(wintypes.SIZE),
            ]
            gdi32.GetTextExtentPoint32W.restype = wintypes.BOOL

            hdc = user32.GetDC(wintypes.HWND(hwnd))
            if not hdc:
                return None

            # GDI's measured line is typically a few pixels taller than the
            # negative lfHeight used to create it. Search a small bounded range
            # instead of baking in a DPI-specific magic subtraction.
            low = max(6, target_height - 8)
            high = max(low, target_height + 4)
            sample = "Ag"
            for logical_height in range(low, high + 1):
                font = gdi32.CreateFontW(
                    -int(logical_height), 0, 0, 0, FW_NORMAL,
                    0, 0, 0, DEFAULT_CHARSET, 0, 0, 0, 0, face,
                )
                if not font:
                    continue
                old = gdi32.SelectObject(hdc, font)
                size = wintypes.SIZE()
                ok = bool(gdi32.GetTextExtentPoint32W(
                    hdc, sample, len(sample), ctypes.byref(size)))
                if old:
                    gdi32.SelectObject(hdc, old)
                if not ok:
                    gdi32.DeleteObject(font)
                    continue

                score = abs(int(size.cy) - target_height)
                # Prefer the smaller candidate on an exact tie.  Oversized
                # rename text is more visually disruptive than a 1 px undershoot.
                rank = (score, int(size.cy) > target_height, logical_height)
                if best_score is None or rank < best_score:
                    if best_font:
                        gdi32.DeleteObject(best_font)
                    best_font = font
                    best_score = rank
                else:
                    gdi32.DeleteObject(font)
            return best_font
        except Exception:
            if best_font:
                try:
                    gdi32.DeleteObject(best_font)
                except Exception:
                    pass
            return None
        finally:
            if hdc:
                try:
                    user32.ReleaseDC(wintypes.HWND(hwnd), hdc)
                except Exception:
                    pass

    def begin(self, hwnd_parent, x, y, width, height, text,
              select_end, font_px, font_face="Segoe UI"):
        """Create, position and focus the editor. Return True on success."""
        self.destroy()
        if os.name != "nt" or not hwnd_parent:
            return False
        try:
            from ctypes import wintypes
            user32 = ctypes.windll.user32
            gdi32 = ctypes.windll.gdi32
            kernel32 = ctypes.windll.kernel32

            user32.CreateWindowExW.argtypes = [
                wintypes.DWORD, wintypes.LPCWSTR, wintypes.LPCWSTR,
                wintypes.DWORD, ctypes.c_int, ctypes.c_int,
                ctypes.c_int, ctypes.c_int, wintypes.HWND,
                wintypes.HMENU, wintypes.HINSTANCE, wintypes.LPVOID,
            ]
            user32.CreateWindowExW.restype = wintypes.HWND
            user32.DestroyWindow.argtypes = [wintypes.HWND]
            user32.DestroyWindow.restype = wintypes.BOOL
            user32.SetFocus.argtypes = [wintypes.HWND]
            user32.SetFocus.restype = wintypes.HWND
            user32.SetWindowPos.argtypes = [
                wintypes.HWND, wintypes.HWND, ctypes.c_int, ctypes.c_int,
                ctypes.c_int, ctypes.c_int, wintypes.UINT,
            ]
            user32.SetWindowPos.restype = wintypes.BOOL
            user32.ClientToScreen.argtypes = [
                wintypes.HWND, ctypes.POINTER(wintypes.POINT),
            ]
            user32.ClientToScreen.restype = wintypes.BOOL
            user32.PostMessageW.argtypes = [
                wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM,
            ]
            user32.PostMessageW.restype = wintypes.BOOL
            user32.SendMessageW.argtypes = [
                wintypes.HWND, wintypes.UINT,
                wintypes.WPARAM, wintypes.LPARAM,
            ]
            user32.SendMessageW.restype = ctypes.c_ssize_t
            user32.CallWindowProcW.argtypes = [
                ctypes.c_void_p, wintypes.HWND, wintypes.UINT,
                wintypes.WPARAM, wintypes.LPARAM,
            ]
            user32.CallWindowProcW.restype = ctypes.c_ssize_t
            gdi32.CreateFontW.argtypes = [
                ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                ctypes.c_int, wintypes.DWORD, wintypes.DWORD,
                wintypes.DWORD, wintypes.DWORD, wintypes.DWORD,
                wintypes.DWORD, wintypes.DWORD, wintypes.DWORD,
                wintypes.LPCWSTR,
            ]
            gdi32.CreateFontW.restype = wintypes.HANDLE
            gdi32.DeleteObject.argtypes = [wintypes.HANDLE]
            gdi32.DeleteObject.restype = wintypes.BOOL
            kernel32.GetModuleHandleW.argtypes = [wintypes.LPCWSTR]
            kernel32.GetModuleHandleW.restype = wintypes.HMODULE

            is_64bit = ctypes.sizeof(ctypes.c_void_p) == 8
            if is_64bit:
                set_long = user32.SetWindowLongPtrW
                get_long = user32.GetWindowLongPtrW
            else:
                set_long = user32.SetWindowLongW
                get_long = user32.GetWindowLongW
            set_long.argtypes = [
                wintypes.HWND, ctypes.c_int, ctypes.c_void_p]
            set_long.restype = ctypes.c_void_p
            get_long.argtypes = [wintypes.HWND, ctypes.c_int]
            get_long.restype = ctypes.c_void_p

            hwnd_parent = wintypes.HWND(int(hwnd_parent))
            text = str(text or "")
            width = max(24, int(width))
            height = max(16, int(height))
            select_end = max(0, min(
                len(text.encode("utf-16-le")) // 2, int(select_end)))

            # Do not use a child EDIT directly over the GLFW/OpenGL client
            # area.  On affected Dear PyGui builds the next OpenGL buffer swap
            # can paint over child controls, leaving only the ImGui row/selection
            # visible.  Explorer itself effectively presents the label editor
            # above the item view; an owned popup gives us the same reliable
            # z-order while still being owned/focused by the application.
            origin = wintypes.POINT(int(x), int(y))
            if not user32.ClientToScreen(hwnd_parent, ctypes.byref(origin)):
                return False

            hwnd_edit = user32.CreateWindowExW(
                WS_EX_TOOLWINDOW, "EDIT", text,
                WS_POPUP | WS_VISIBLE | WS_BORDER | ES_LEFT | ES_AUTOHSCROLL,
                int(origin.x), int(origin.y), width, height,
                hwnd_parent, None,
                kernel32.GetModuleHandleW(None), None,
            )
            if not hwnd_edit:
                return False

            # Explicitly place/show the owned popup above its owner without
            # making it globally top-most.  This is the key difference from the
            # previous child-HWND implementation.
            user32.SetWindowPos(
                hwnd_edit, None, int(origin.x), int(origin.y), width, height,
                SWP_NOZORDER | SWP_NOACTIVATE | SWP_SHOWWINDOW,
            )

            # ``font_px`` is the DPG-rendered body-text height, not a raw GDI
            # lfHeight. Fit a GDI font to that visible height so rename text
            # matches the row label instead of appearing enlarged.
            font = self._create_font_matching_height(
                gdi32, user32, hwnd_edit, font_px, font_face)
            if font is None:
                font = gdi32.CreateFontW(
                    -max(8, int(font_px) - 3), 0, 0, 0, FW_NORMAL,
                    0, 0, 0, DEFAULT_CHARSET, 0, 0, 0, 0,
                    str(font_face or "Segoe UI"),
                )
            if font:
                user32.SendMessageW(hwnd_edit, WM_SETFONT, font, True)

            # Small horizontal inset makes the label editor read like
            # Explorer instead of a raw Win32 field glued to the icon.
            margins = (2 & 0xFFFF) | ((2 & 0xFFFF) << 16)
            user32.SendMessageW(
                hwnd_edit, EM_SETMARGINS,
                EC_LEFTMARGIN | EC_RIGHTMARGIN, margins)

            # Swallow Return/Escape here so the edit control neither beeps
            # nor inserts anything; the resulting action is consumed on the
            # UI thread, never inside this native callback.
            editor = self

            def edit_wndproc(window, message, wparam, lparam):
                try:
                    if message == WM_KEYDOWN:
                        if int(wparam) == VK_RETURN:
                            editor._pending_action = "commit"
                            return 0
                        if int(wparam) == VK_ESCAPE:
                            editor._pending_action = "cancel"
                            return 0

                    # The standard Win32 EDIT control can change its selection
                    # while processing WM_SETFOCUS.  Applying EM_SETSEL *before*
                    # or immediately after SetFocus() is therefore not sufficient
                    # on every GLFW/DPG message ordering: the default proc may
                    # subsequently replace our basename range with select-all.
                    # Let the EDIT finish its native focus handling first, then
                    # restore the Explorer basename selection from inside the
                    # same focus message.
                    if message == WM_SETFOCUS:
                        result = user32.CallWindowProcW(
                            editor._old_proc, window, message, wparam, lparam)
                        start, end = editor._initial_selection
                        user32.SendMessageW(window, EM_SETSEL, start, end)
                        user32.SendMessageW(window, EM_SCROLLCARET, 0, 0)
                        return result
                except Exception:
                    pass
                try:
                    return user32.CallWindowProcW(
                        editor._old_proc, window, message, wparam, lparam)
                except Exception:
                    return 0

            WNDPROC = ctypes.WINFUNCTYPE(
                ctypes.c_ssize_t, wintypes.HWND, wintypes.UINT,
                wintypes.WPARAM, wintypes.LPARAM,
            )
            callback = WNDPROC(edit_wndproc)
            GWL_WNDPROC = -4
            old_proc = set_long(
                hwnd_edit, GWL_WNDPROC, ctypes.cast(callback, ctypes.c_void_p))
            if not old_proc:
                try:
                    user32.DestroyWindow(hwnd_edit)
                except Exception:
                    pass
                if font:
                    try:
                        gdi32.DeleteObject(font)
                    except Exception:
                        pass
                return False

            self._hwnd_edit = hwnd_edit
            self._hwnd_parent = hwnd_parent
            self._font = font or None
            self._old_proc = old_proc
            self._proc_callback = callback  # Keep alive while active.
            self._user32 = user32
            self._gdi32 = gdi32
            self._pending_action = None
            self._initial_selection = (0, select_end)
            self._popup_mode = True

            # WM_SETFOCUS is intercepted by our subclass above and restores
            # the basename range *after* the standard EDIT focus handling.
            # Keep a direct EM_SETSEL too for the already-focused edge case.
            user32.SetFocus(hwnd_edit)
            user32.SendMessageW(hwnd_edit, EM_SETSEL, 0, select_end)
            user32.SendMessageW(hwnd_edit, EM_SCROLLCARET, 0, 0)
            return True
        except Exception:
            self.destroy()
            return False

    def set_selection(self, start, end):
        """Set the edit selection using UTF-16 character offsets."""
        if not self.is_active() or os.name != "nt":
            return False
        try:
            user32 = ctypes.windll.user32
            start = max(0, int(start))
            end = max(start, int(end))
            user32.SendMessageW(self._hwnd_edit, EM_SETSEL, start, end)
            user32.SendMessageW(self._hwnd_edit, EM_SCROLLCARET, 0, 0)
            return True
        except Exception:
            return False

    def get_selection(self):
        """Return ``(start, end)`` selection offsets, or ``None``."""
        if not self.is_active() or os.name != "nt":
            return None
        try:
            from ctypes import wintypes
            start = wintypes.DWORD(0)
            end = wintypes.DWORD(0)
            ctypes.windll.user32.SendMessageW(
                self._hwnd_edit, EM_GETSEL,
                ctypes.addressof(start), ctypes.addressof(end))
            return int(start.value), int(end.value)
        except Exception:
            return None

    def set_bounds(self, x, y, width, height):
        """Move/resize using coordinates relative to the Dear PyGui client."""
        if not self.is_active() or os.name != "nt":
            return False
        try:
            from ctypes import wintypes
            user32 = ctypes.windll.user32
            px, py = int(x), int(y)
            if self._popup_mode and self._hwnd_parent:
                point = wintypes.POINT(px, py)
                user32.ClientToScreen(
                    wintypes.HWND(self._hwnd_parent), ctypes.byref(point))
                px, py = int(point.x), int(point.y)
            return bool(user32.SetWindowPos(
                self._hwnd_edit, None, px, py,
                max(24, int(width)), max(16, int(height)),
                SWP_NOZORDER | SWP_NOACTIVATE | SWP_SHOWWINDOW,
            ))
        except Exception:
            return False

    def consume_pending(self):
        """Return 'commit'/'cancel' requested by the edit control, if any."""
        action, self._pending_action = self._pending_action, None
        return action

    def get_text(self):
        """Return the current editor text without destroying the control."""
        if not self.is_active() or os.name != "nt":
            return ""
        try:
            from ctypes import wintypes
            user32 = ctypes.windll.user32
            user32.GetWindowTextLengthW.argtypes = [wintypes.HWND]
            user32.GetWindowTextLengthW.restype = ctypes.c_int
            user32.GetWindowTextW.argtypes = [
                wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
            user32.GetWindowTextW.restype = ctypes.c_int
            length = int(user32.GetWindowTextLengthW(self._hwnd_edit))
            buffer = ctypes.create_unicode_buffer(length + 1)
            user32.GetWindowTextW(self._hwnd_edit, buffer, length + 1)
            return buffer.value
        except Exception:
            return ""

    def refocus(self):
        """Return keyboard focus to the editor. Return True on success."""
        if not self.is_active() or os.name != "nt":
            return False
        try:
            ctypes.windll.user32.SetFocus(self._hwnd_edit)
            return True
        except Exception:
            return False

    def destroy(self):
        """Remove the control and release native resources. Never raises."""
        try:
            user32 = getattr(self, "_user32", None)
            gdi32 = getattr(self, "_gdi32", None)
            if user32 is None and os.name == "nt":
                try:
                    user32 = ctypes.windll.user32
                    gdi32 = ctypes.windll.gdi32
                except Exception:
                    user32 = None
            hwnd_edit, self._hwnd_edit = self._hwnd_edit, None
            hwnd_parent, self._hwnd_parent = self._hwnd_parent, None
            font, self._font = self._font, None
            self._old_proc = None
            self._proc_callback = None
            self._pending_action = None
            self._initial_selection = (0, 0)
            self._popup_mode = False
            if hwnd_edit:
                try:
                    if user32 is not None:
                        user32.DestroyWindow(hwnd_edit)
                except Exception:
                    pass
                if font:
                    try:
                        if gdi32 is not None:
                            gdi32.DeleteObject(font)
                    except Exception:
                        pass
            if hwnd_parent and user32 is not None:
                try:
                    user32.SetFocus(hwnd_parent)
                except Exception:
                    pass
        except Exception:
            pass
