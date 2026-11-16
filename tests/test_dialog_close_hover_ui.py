"""Physical caption hover: abaqus python tests/test_dialog_close_hover_ui.py.

Run alone; the test temporarily moves the desktop cursor.
"""
import ctypes
from ctypes import wintypes
from collections import Counter
import os
from pathlib import Path
import sys
import tempfile
import time
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import run_winux
run_winux._configure_bundled_dependencies(str(ROOT))

from WinUx.controllers.callbacks import REQUIRED_CALLBACK_KEYS
from WinUx.dialogs.native_reference_tools import ReferenceChartDialog
from WinUx.view import WinUXView


def main():
    user32 = ctypes.windll.user32
    user32.GetForegroundWindow.restype = wintypes.HWND
    user32.SendMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
    user32.SendMessageW.restype = ctypes.c_ssize_t
    user32.GetDC.argtypes = [wintypes.HWND]
    user32.GetDC.restype = wintypes.HDC
    user32.ReleaseDC.argtypes = [wintypes.HWND, wintypes.HDC]
    gdi32 = ctypes.windll.gdi32
    gdi32.GetPixel.argtypes = [wintypes.HDC, ctypes.c_int, ctypes.c_int]
    gdi32.GetPixel.restype = wintypes.DWORD
    cursor = wintypes.POINT()
    user32.GetCursorPos(ctypes.byref(cursor))
    temp = Path(os.environ['LOCALAPPDATA']) / 'Temp' / 'opencode'
    with tempfile.TemporaryDirectory(prefix='close-hover-', dir=temp) as profile, \
            patch.dict(os.environ, {'APPDATA': profile}):
        view = WinUXView({key: lambda *a, **kw: None for key in REQUIRED_CALLBACK_KEYS})
        view._gui_runtime.show()

        def pump(count=1):
            for _ in range(count):
                view.update()
                time.sleep(.016)

        try:
            pump(10)
            for name, factory in (
                    ('Reference Chart', lambda: ReferenceChartDialog(view, [], lambda result: None)),
                    ('Settings', view.show_settings)):
                dialog = factory()
                dialog.show()
                pump(30)
                hwnd = dialog._native_window_backend.winId(dialog.tag)
                thread = user32.GetWindowThreadProcessId(user32.GetForegroundWindow(), None)
                current = ctypes.windll.kernel32.GetCurrentThreadId()
                attached = user32.AttachThreadInput(current, thread, True)
                try:
                    user32.SetForegroundWindow(wintypes.HWND(hwnd))
                finally:
                    if attached:
                        user32.AttachThreadInput(current, thread, False)
                user32.SetWindowPos(wintypes.HWND(hwnd), wintypes.HWND(-1),
                                    0, 0, 0, 0, 0x0013)
                pump(5)
                assert int(user32.GetForegroundWindow() or 0) == hwnd, (name, 'Not foreground')
                rect = wintypes.RECT()
                user32.GetWindowRect(wintypes.HWND(hwnd), ctypes.byref(rect))
                close = None
                for y in range(rect.top + 8, rect.top + 45, 2):
                    for x in range(rect.right - 18, rect.right - 60, -2):
                        packed = (x & 0xffff) | ((y & 0xffff) << 16)
                        if user32.SendMessageW(hwnd, 0x0084, 0, packed) == 20:
                            close = (x, y + 4)
                            break
                    if close:
                        break
                assert close, (name, 'Close hit target not found')
                user32.SetCursorPos(rect.left + 30, rect.bottom - 30)
                pump(5)
                user32.SetCursorPos(*close)
                # Deliver actual caption motion after activation settles, then
                # let DWM finish its hot-state transition before sampling.
                for frame in range(15):
                    user32.SetCursorPos(close[0] - (frame % 3), close[1])
                    pump()
                actual = wintypes.POINT()
                user32.GetCursorPos(ctypes.byref(actual))
                user32.WindowFromPoint.argtypes = [wintypes.POINT]
                user32.WindowFromPoint.restype = wintypes.HWND
                assert int(user32.WindowFromPoint(actual) or 0) == hwnd, (name, 'Close is obscured')
                dc = user32.GetDC(None)
                colors = []
                try:
                    for frame in range(120):
                        # Exercise both a stationary cursor and motion within Close.
                        if frame >= 60:
                            user32.SetCursorPos(close[0] - (frame % 3), close[1])
                        pump()
                        ctypes.windll.dwmapi.DwmFlush()
                        color = int(gdi32.GetPixel(dc, *close))
                        colors.append((color & 255, (color >> 8) & 255, (color >> 16) & 255))
                finally:
                    user32.ReleaseDC(None, dc)
                red = [r > 160 and r > g * 1.5 and r > b * 1.5 for r, g, b in colors]
                print(name, 'red frames:', sum(red), '/', len(red), 'colors:', Counter(colors).most_common(8), flush=True)
                user32.SetCursorPos(rect.left + 30, rect.bottom - 30)
                pump(12)
                assert all(red), (name, 'Close hover flashed or never became hot')
                dc = user32.GetDC(None)
                try:
                    color = int(gdi32.GetPixel(dc, *close))
                    r, g, b = color & 255, (color >> 8) & 255, (color >> 16) & 255
                    assert not (r > 160 and r > g * 1.5 and r > b * 1.5), (name, 'Hover stuck after departure')
                finally:
                    user32.ReleaseDC(None, dc)
                dialog.reject()
                pump(12)
            print('PASS: Close stays red while hovering both dialogs', flush=True)
        finally:
            user32.SetCursorPos(cursor.x, cursor.y)
            view.request_shutdown()
            view._gui_runtime.destroy()


if __name__ == '__main__':
    main()
