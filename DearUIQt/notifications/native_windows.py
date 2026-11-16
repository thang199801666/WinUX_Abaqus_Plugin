"""Lightweight Win32 toast surfaces used by DearUIQt notifications.

Nothing is instantiated at import time.  The host is deliberately independent
of WinUx and DearPyGui: it creates no renderer context, process, socket or event
loop.  A consuming application may construct ``WindowsToastHost`` later and
pump messages through its existing Windows/UI loop.
"""
from __future__ import annotations

import ctypes
import os
import threading
from ctypes import wintypes

from .placement import monitor_work_area
from .theme import QNotificationTheme


WM_PAINT = 0x000F
WM_ERASEBKGND = 0x0014
WM_MOUSEMOVE = 0x0200
WM_MOUSELEAVE = 0x02A3
WM_LBUTTONUP = 0x0202
WM_MOUSEACTIVATE = 0x0021
WM_NCHITTEST = 0x0084
WM_DESTROY = 0x0002
MA_NOACTIVATE = 3
HTCLIENT = 1

SW_HIDE = 0
SW_SHOWNOACTIVATE = 4
SWP_NOSIZE = 0x0001
SWP_NOZORDER = 0x0004
SWP_NOACTIVATE = 0x0010

WS_POPUP = 0x80000000
WS_CLIPCHILDREN = 0x02000000
WS_CLIPSIBLINGS = 0x04000000
WS_EX_TOOLWINDOW = 0x00000080
WS_EX_TOPMOST = 0x00000008
WS_EX_NOACTIVATE = 0x08000000

DT_LEFT = 0x0000
DT_TOP = 0x0000
DT_WORDBREAK = 0x0010
DT_SINGLELINE = 0x0020
DT_END_ELLIPSIS = 0x8000
DT_NOPREFIX = 0x0800
TRANSPARENT = 1

TME_LEAVE = 0x00000002
AW_BLEND = 0x00080000
AW_SLIDE = 0x00040000
AW_VER_NEGATIVE = 0x00000008
AW_HIDE = 0x00010000


class _PaintStruct(ctypes.Structure):
    _fields_ = [
        ("hdc", wintypes.HDC),
        ("fErase", wintypes.BOOL),
        ("rcPaint", wintypes.RECT),
        ("fRestore", wintypes.BOOL),
        ("fIncUpdate", wintypes.BOOL),
        ("rgbReserved", ctypes.c_byte * 32),
    ]


class _TrackMouseEvent(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.DWORD),
        ("dwFlags", wintypes.DWORD),
        ("hwndTrack", wintypes.HWND),
        ("dwHoverTime", wintypes.DWORD),
    ]


def _rgb(value):
    r, g, b = [max(0, min(255, int(v))) for v in value[:3]]
    return r | (g << 8) | (b << 16)


def _loword(value):
    return int(value) & 0xFFFF


def _hiword(value):
    return (int(value) >> 16) & 0xFFFF


class WindowsToastWindow:
    def __init__(self, host, request, theme, *, owner_hwnd=0):
        self.host = host
        self.request = request
        self.theme = theme
        self.owner_hwnd = int(owner_hwnd or 0)
        self.hwnd = 0
        self.width = int(theme.width)
        self.height = self._measure_height()
        self.hovered = False
        self._font_title = 0
        self._font_body = 0
        self._close_hover = False

    def _measure_height(self):
        lines = max(1, min(4, (len(self.request.message or "") + 46) // 47))
        desired = self.theme.padding_y * 2 + max(self.theme.icon_box, 22 + lines * (self.theme.body_font_px + 4))
        return max(self.theme.min_height, min(self.theme.max_height, desired))

    @property
    def size(self):
        return self.width, self.height

    def create(self):
        self.host._require_thread()
        if self.hwnd:
            return self.hwnd
        self.hwnd = self.host._create_hwnd(self)
        return self.hwnd

    def update(self, request):
        self.request = request
        self.height = self._measure_height()
        if self.hwnd:
            self.host.user32.InvalidateRect(wintypes.HWND(self.hwnd), None, True)
        return self

    def move(self, x, y):
        if not self.hwnd:
            return False
        return bool(self.host.user32.SetWindowPos(
            wintypes.HWND(self.hwnd), wintypes.HWND(-1), int(x), int(y),
            self.width, self.height, SWP_NOACTIVATE))

    def show(self, animate=True):
        if not self.hwnd:
            self.create()
        shown = False
        if animate:
            try:
                shown = bool(self.host.user32.AnimateWindow(
                    wintypes.HWND(self.hwnd), 120, AW_SLIDE | AW_VER_NEGATIVE))
            except Exception:
                shown = False
        if not shown:
            self.host.user32.ShowWindow(wintypes.HWND(self.hwnd), SW_SHOWNOACTIVATE)
        self.host.user32.SetWindowPos(
            wintypes.HWND(self.hwnd), wintypes.HWND(-1), 0, 0, 0, 0,
            SWP_NOSIZE | SWP_NOZORDER | SWP_NOACTIVATE)
        return True

    def hide(self, animate=True):
        if not self.hwnd:
            return False
        if animate:
            try:
                self.host.user32.AnimateWindow(wintypes.HWND(self.hwnd), 90, AW_BLEND | AW_HIDE)
            except Exception:
                pass
        self.host.user32.ShowWindow(wintypes.HWND(self.hwnd), SW_HIDE)
        return True

    def destroy(self):
        hwnd, self.hwnd = self.hwnd, 0
        if hwnd:
            try:
                self.host.user32.DestroyWindow(wintypes.HWND(hwnd))
            except Exception:
                pass
        return bool(hwnd)

    def _close_rect(self):
        size = self.theme.close_box
        return (self.width - self.theme.padding_x - size, self.theme.padding_y - 4,
                self.width - self.theme.padding_x, self.theme.padding_y - 4 + size)

    def _hit_close(self, x, y):
        l, t, r, b = self._close_rect()
        return l <= x < r and t <= y < b

    def _paint(self):
        hwnd = wintypes.HWND(self.hwnd)
        ps = _PaintStruct()
        hdc = self.host.user32.BeginPaint(hwnd, ctypes.byref(ps))
        if not hdc:
            return
        gdi32 = self.host.gdi32
        try:
            rect = wintypes.RECT(0, 0, self.width, self.height)
            bg = gdi32.CreateSolidBrush(_rgb(self.theme.background))
            self.host.user32.FillRect(hdc, ctypes.byref(rect), bg)
            gdi32.DeleteObject(bg)

            accent = gdi32.CreateSolidBrush(_rgb(self.theme.accent_for(self.request.kind)))
            strip = wintypes.RECT(0, 0, max(4, self.theme.corner_radius // 2), self.height)
            self.host.user32.FillRect(hdc, ctypes.byref(strip), accent)
            gdi32.DeleteObject(accent)

            border_pen = gdi32.CreatePen(0, 1, _rgb(self.theme.border))
            old_pen = gdi32.SelectObject(hdc, border_pen)
            old_brush = gdi32.SelectObject(hdc, gdi32.GetStockObject(5))  # NULL_BRUSH
            gdi32.RoundRect(hdc, 0, 0, self.width - 1, self.height - 1,
                            self.theme.corner_radius * 2, self.theme.corner_radius * 2)
            gdi32.SelectObject(hdc, old_brush)
            gdi32.SelectObject(hdc, old_pen)
            gdi32.DeleteObject(border_pen)

            if self._close_hover:
                l, t, r, b = self._close_rect()
                brush = gdi32.CreateSolidBrush(_rgb(self.theme.close_hover))
                hover_rect = wintypes.RECT(l, t, r, b)
                self.host.user32.FillRect(hdc, ctypes.byref(hover_rect), brush)
                gdi32.DeleteObject(brush)

            gdi32.SetBkMode(hdc, TRANSPARENT)
            x = self.theme.padding_x + self.theme.icon_box
            right = self.width - self.theme.padding_x - self.theme.close_box - 4
            title_rect = wintypes.RECT(x, self.theme.padding_y, right,
                                      self.theme.padding_y + self.theme.title_font_px + 8)
            body_rect = wintypes.RECT(x, title_rect.bottom + 4,
                                     self.width - self.theme.padding_x, self.height - self.theme.padding_y)

            title_font = self._ensure_font(True)
            body_font = self._ensure_font(False)
            old_font = gdi32.SelectObject(hdc, title_font)
            gdi32.SetTextColor(hdc, _rgb(self.theme.foreground))
            self.host.user32.DrawTextW(hdc, self.request.title, -1, ctypes.byref(title_rect),
                                       DT_LEFT | DT_TOP | DT_SINGLELINE | DT_END_ELLIPSIS | DT_NOPREFIX)
            gdi32.SelectObject(hdc, body_font)
            gdi32.SetTextColor(hdc, _rgb(self.theme.secondary))
            self.host.user32.DrawTextW(hdc, self.request.message, -1, ctypes.byref(body_rect),
                                       DT_LEFT | DT_TOP | DT_WORDBREAK | DT_NOPREFIX)

            gdi32.SetTextColor(hdc, _rgb(self.theme.secondary))
            close_rect = wintypes.RECT(*self._close_rect())
            self.host.user32.DrawTextW(hdc, "×", -1, ctypes.byref(close_rect),
                                       0x0001 | 0x0004 | DT_SINGLELINE | DT_NOPREFIX)  # center/vcenter

            glyph = {"success": "✓", "warning": "!", "error": "×"}.get(
                getattr(self.request.kind, "value", "info"), "i")
            icon_rect = wintypes.RECT(self.theme.padding_x,
                                     self.theme.padding_y + 3,
                                     self.theme.padding_x + self.theme.icon_box,
                                     self.theme.padding_y + 3 + self.theme.icon_box)
            gdi32.SetTextColor(hdc, _rgb(self.theme.accent_for(self.request.kind)))
            self.host.user32.DrawTextW(hdc, glyph, -1, ctypes.byref(icon_rect),
                                       0x0001 | 0x0004 | DT_SINGLELINE | DT_NOPREFIX)
            gdi32.SelectObject(hdc, old_font)
        finally:
            self.host.user32.EndPaint(hwnd, ctypes.byref(ps))

    def _ensure_font(self, title):
        attr = "_font_title" if title else "_font_body"
        font = getattr(self, attr)
        if font:
            return font
        px = self.theme.title_font_px if title else self.theme.body_font_px
        weight = 600 if title else 400
        height = -int(round(px * 96.0 / 72.0))
        font = self.host.gdi32.CreateFontW(
            height, 0, 0, 0, weight, 0, 0, 0, 1, 0, 0, 5, 0, "Segoe UI")
        setattr(self, attr, font)
        return font

    def _dispose_fonts(self):
        for attr in ("_font_title", "_font_body"):
            font = getattr(self, attr, 0)
            if font:
                try:
                    self.host.gdi32.DeleteObject(font)
                except Exception:
                    pass
                setattr(self, attr, 0)


class WindowsToastHost:
    """Own lightweight, non-activating Win32 toast HWNDs.

    Callbacks are intentionally injected by ``QNotificationManager`` rather
    than importing any application service.  The host itself has no timer,
    background worker or global singleton.
    """

    CLASS_NAME = "DearUIQt.NotificationToast.v1"
    _class_atom = 0
    _wndproc = None
    _windows = {}

    def __init__(self, *, theme=None, owner_hwnd=0):
        if os.name != "nt":
            raise RuntimeError("WindowsToastHost requires Windows")
        self.user32 = ctypes.windll.user32
        self.gdi32 = ctypes.windll.gdi32
        self.kernel32 = ctypes.windll.kernel32
        self.theme = theme or QNotificationTheme()
        self.owner_hwnd = int(owner_hwnd or 0)
        self.thread_id = threading.get_ident()
        self.on_hover = None
        self.on_close = None
        self.on_click = None
        self._ensure_class()

    def _require_thread(self):
        if threading.get_ident() != self.thread_id:
            raise RuntimeError("notification native windows must be accessed on their UI thread")

    def _ensure_class(self):
        cls = type(self)
        if cls._class_atom:
            return
        WNDPROC = ctypes.WINFUNCTYPE(ctypes.c_ssize_t, wintypes.HWND, wintypes.UINT,
                                     wintypes.WPARAM, wintypes.LPARAM)

        def wndproc(hwnd, msg, wparam, lparam):
            window = cls._windows.get(int(hwnd))
            if msg == WM_MOUSEACTIVATE:
                return MA_NOACTIVATE
            if window is None:
                return ctypes.windll.user32.DefWindowProcW(hwnd, msg, wparam, lparam)
            if msg == WM_ERASEBKGND:
                return 1
            if msg == WM_PAINT:
                window._paint()
                return 0
            if msg == WM_MOUSEMOVE:
                x, y = _loword(lparam), _hiword(lparam)
                close_hover = window._hit_close(x, y)
                if close_hover != window._close_hover:
                    window._close_hover = close_hover
                    window.host.user32.InvalidateRect(hwnd, None, False)
                if not window.hovered:
                    window.hovered = True
                    track = _TrackMouseEvent(ctypes.sizeof(_TrackMouseEvent), TME_LEAVE, hwnd, 0)
                    window.host.user32.TrackMouseEvent(ctypes.byref(track))
                    if callable(window.host.on_hover):
                        window.host.on_hover(window, True)
                return 0
            if msg == WM_MOUSELEAVE:
                window.hovered = False
                window._close_hover = False
                if callable(window.host.on_hover):
                    window.host.on_hover(window, False)
                window.host.user32.InvalidateRect(hwnd, None, False)
                return 0
            if msg == WM_LBUTTONUP:
                x, y = _loword(lparam), _hiword(lparam)
                callback = window.host.on_close if window._hit_close(x, y) else window.host.on_click
                if callable(callback):
                    callback(window)
                return 0
            if msg == WM_NCHITTEST:
                return HTCLIENT
            if msg == WM_DESTROY:
                cls._windows.pop(int(hwnd), None)
                window._dispose_fonts()
                return 0
            return window.host.user32.DefWindowProcW(hwnd, msg, wparam, lparam)

        cls._wndproc = WNDPROC(wndproc)

        class WNDCLASSW(ctypes.Structure):
            _fields_ = [
                ("style", wintypes.UINT), ("lpfnWndProc", WNDPROC),
                ("cbClsExtra", ctypes.c_int), ("cbWndExtra", ctypes.c_int),
                ("hInstance", wintypes.HINSTANCE), ("hIcon", wintypes.HICON),
                ("hCursor", wintypes.HANDLE), ("hbrBackground", wintypes.HBRUSH),
                ("lpszMenuName", wintypes.LPCWSTR), ("lpszClassName", wintypes.LPCWSTR),
            ]
        wc = WNDCLASSW()
        wc.lpfnWndProc = cls._wndproc
        wc.hInstance = self.kernel32.GetModuleHandleW(None)
        wc.hCursor = self.user32.LoadCursorW(None, ctypes.c_void_p(32512))
        wc.lpszClassName = self.CLASS_NAME
        self.user32.RegisterClassW.argtypes = [ctypes.POINTER(WNDCLASSW)]
        self.user32.RegisterClassW.restype = wintypes.ATOM
        atom = int(self.user32.RegisterClassW(ctypes.byref(wc)) or 0)
        if not atom:
            # ERROR_CLASS_ALREADY_EXISTS is fine for module reloads.
            atom = 1
        cls._class_atom = atom

    def create(self, request):
        self._require_thread()
        area = monitor_work_area(self.owner_hwnd)
        theme = self.theme.scaled(area.dpi)
        window = WindowsToastWindow(self, request, theme, owner_hwnd=self.owner_hwnd)
        window.create()
        return window

    def _create_hwnd(self, window):
        self.user32.CreateWindowExW.argtypes = [
            wintypes.DWORD, wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.DWORD,
            ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
            wintypes.HWND, wintypes.HMENU, wintypes.HINSTANCE, wintypes.LPVOID]
        self.user32.CreateWindowExW.restype = wintypes.HWND
        hwnd = self.user32.CreateWindowExW(
            WS_EX_TOOLWINDOW | WS_EX_TOPMOST | WS_EX_NOACTIVATE,
            self.CLASS_NAME, "", WS_POPUP | WS_CLIPCHILDREN | WS_CLIPSIBLINGS,
            0, 0, window.width, window.height,
            wintypes.HWND(window.owner_hwnd or 0), None,
            self.kernel32.GetModuleHandleW(None), None)
        value = int(hwnd or 0)
        if not value:
            raise OSError("could not create notification popup window")
        type(self)._windows[value] = window
        region = self.gdi32.CreateRoundRectRgn(
            0, 0, window.width + 1, window.height + 1,
            window.theme.corner_radius * 2, window.theme.corner_radius * 2)
        if region:
            self.user32.SetWindowRgn(wintypes.HWND(value), region, True)
        return value

    def workArea(self):
        return monitor_work_area(self.owner_hwnd)

    def pumpMessages(self, limit=64):
        """Optional non-blocking pump for standalone hosts.

        Main applications with their own native message/render loop generally do
        not need this.  It is provided so DearUIQt remains reusable outside WinUx.
        """
        self._require_thread()
        msg = wintypes.MSG()
        count = 0
        PM_REMOVE = 0x0001
        while count < max(0, int(limit)) and self.user32.PeekMessageW(
                ctypes.byref(msg), None, 0, 0, PM_REMOVE):
            self.user32.TranslateMessage(ctypes.byref(msg))
            self.user32.DispatchMessageW(ctypes.byref(msg))
            count += 1
        return count


__all__ = ["WindowsToastHost", "WindowsToastWindow"]
