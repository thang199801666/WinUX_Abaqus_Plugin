"""Native PiP corner/frame geometry: abaqus python tests/test_pip_corners.py.

Uses native geometry messages, not physical mouse input.
"""
import ctypes
import os
import sys
import tempfile
import time
from ctypes import wintypes
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import run_winux
run_winux._configure_bundled_dependencies(str(ROOT))

from DearUIQt.backends import dpg
from WinUx.controllers.callbacks import REQUIRED_CALLBACK_KEYS
from WinUx.preferences.dialog_geometry import DialogGeometryPreferences
from WinUx.view import WinUXView


def main():
    temp_root = Path(os.environ['LOCALAPPDATA']) / 'Temp' / 'opencode'
    with tempfile.TemporaryDirectory(prefix='winux-pip-corners-', dir=temp_root) as profile:
        view = WinUXView({key: lambda *a, **k: None for key in REQUIRED_CALLBACK_KEYS})
        view._compact_geometry_preferences = DialogGeometryPreferences(root=profile)
        view._gui_runtime.show()
        user32, gdi32 = ctypes.windll.user32, ctypes.windll.gdi32
        gdi32.CreateRectRgn.restype = wintypes.HANDLE
        user32.GetWindowRgn.argtypes = [wintypes.HWND, wintypes.HANDLE]
        gdi32.DeleteObject.argtypes = [wintypes.HANDLE]

        def pump(frames=8):
            for _ in range(frames):
                view.update()
                time.sleep(.01)

        def verify(width, height):
            actual = view._compact_window_rect()
            assert actual[2:] == (width, height), actual
            client = wintypes.RECT()
            user32.GetClientRect(hwnd, ctypes.byref(client))
            assert (client.right, client.bottom) == (width, height), (
                'Native rounding introduced a white client/frame inset', client.right, client.bottom)
            assert tuple(dpg.get_item_rect_size(view.primary_window_tag)) == (width, height)
            region = gdi32.CreateRectRgn(0, 0, 0, 0)
            try:
                result = user32.GetWindowRgn(hwnd, region)
                if sys.getwindowsversion().build >= 22000:
                    assert view._compact_corner_mode == (hwnd.value, 'native')
                    assert result == 0, 'Binary GDI clipping is overriding smooth DWM corners'
                    corner = ctypes.c_int()
                    assert ctypes.windll.dwmapi.DwmGetWindowAttribute(
                        hwnd, 33, ctypes.byref(corner), ctypes.sizeof(corner)) == 0
                    assert corner.value == 2
                else:
                    assert result != 0
                    bounds = wintypes.RECT()
                    gdi32.GetRgnBox.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.RECT)]
                    gdi32.GetRgnBox(region, ctypes.byref(bounds))
                    assert (bounds.left, bounds.top, bounds.right, bounds.bottom) == (0, 0, width, height)
            finally:
                gdi32.DeleteObject(region)

        try:
            pump()
            original_styles = view._compact_native_window_styles(view._find_main_viewport_hwnd())
            view.collapse_to_job_monitor()
            pump(16)
            hwnd = wintypes.HWND(view._find_main_viewport_hwnd())
            for width, height in ((360, 130), (523, 147), (382, 261)):
                x, y, _, _ = view._compact_window_rect()
                user32.SetWindowPos(hwnd, None, x, y, width, height, 0x0014)
                pump()
                verify(width, height)
            view.restore_from_job_monitor()
            pump(16)
            assert view._compact_corner_mode is None
            assert view._compact_native_window_styles(hwnd.value) == original_styles
            print('PASS: native PiP corners, no GDI double-clipping/frame insets, '
                  'odd-size resize and original frame restoration', flush=True)
        finally:
            view.request_shutdown()
            view._gui_runtime.destroy()


if __name__ == '__main__':
    main()
