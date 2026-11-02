"""Real title drag/tear-off: abaqus python tests/test_native_dock_drag.py.

Uses physical pointer input. Do not move the mouse while this test runs.
"""
import ctypes
import os
import sys
import tempfile
import time
from ctypes import wintypes
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import run_winux
run_winux._configure_bundled_dependencies(str(ROOT))

from WinUx.controllers.callbacks import REQUIRED_CALLBACK_KEYS
from WinUx.preferences.general import GeneralPreferences
from WinUx.ui.native.native_dock_gesture import gesture_mode, _native_caption_band
from WinUx.view import WinUXView


def main():
    temp_root = Path(os.environ['LOCALAPPDATA']) / 'Temp' / 'opencode'
    with tempfile.TemporaryDirectory(prefix='winux-dock-drag-', dir=temp_root) as profile:
        GeneralPreferences(root=profile)._store.save({'console_visible': True})
        with patch.dict(os.environ, {'APPDATA': profile}):
            view = WinUXView({key: lambda *a, **k: None for key in REQUIRED_CALLBACK_KEYS})
            view._gui_runtime.show()
            user32 = ctypes.windll.user32
            user32.GetForegroundWindow.restype = wintypes.HWND

            def pump(frames=1):
                for _ in range(frames):
                    view.update()
                    time.sleep(.02)

            def rectangle(hwnd):
                rc = wintypes.RECT()
                user32.GetWindowRect(wintypes.HWND(hwnd), ctypes.byref(rc))
                return rc.left, rc.top, rc.right, rc.bottom

            def focus(hwnd):
                foreground_thread = user32.GetWindowThreadProcessId(user32.GetForegroundWindow(), None)
                current = ctypes.windll.kernel32.GetCurrentThreadId()
                attached = user32.AttachThreadInput(current, foreground_thread, True)
                try:
                    user32.BringWindowToTop(wintypes.HWND(hwnd))
                    user32.SetForegroundWindow(wintypes.HWND(hwnd))
                finally:
                    if attached:
                        user32.AttachThreadInput(current, foreground_thread, False)

            def drag(start, end, host):
                user32.SetCursorPos(*map(int, start))
                pump(4)
                user32.mouse_event(0x0002, 0, 0, 0, 0)
                moving = False
                try:
                    pump(3)
                    for step in range(1, 31):
                        user32.SetCursorPos(int(start[0] + (end[0] - start[0]) * step / 30),
                                            int(start[1] + (end[1] - start[1]) * step / 30))
                        pump(3)
                        moving = moving or gesture_mode(host._hwnd) == 1
                    assert moving, 'Title drag never entered the native move loop'
                finally:
                    user32.mouse_event(0x0004, 0, 0, 0, 0)
                pump(10)

            try:
                pump(8)
                view._prepare_console_native_host()
                deadline = time.monotonic() + 12
                host = None
                while time.monotonic() < deadline:
                    pump()
                    host = getattr(view, '_native_console_host', None)
                    if host is not None and host._ready:
                        break
                assert host is not None and host._ready
                owner = view._find_main_viewport_hwnd()
                for attempt in range(2):
                    focus(owner)
                    header = view.console_dock.dragHandleWidget().globalGeometry()
                    start = (int(header.x() + header.width() / 2),
                             int(header.y() + header.height() / 2))
                    work = view._compact_monitor_work_area(owner)
                    end = (work[2] - 160, work[1] + 220)
                    drag(start, end, host)
                    assert view._console_dock_mode == 'floating'
                    assert host._native_visible and user32.IsWindowEnabled(wintypes.HWND(host._hwnd))

                    # A second grab on the detached native caption must move
                    # the same HWND, rather than requiring another undock.
                    focus(host._hwnd)
                    before = rectangle(host._hwnd)
                    top, bottom = _native_caption_band(host._hwnd)
                    start = ((before[0] + before[2]) // 2, before[1] + (top + bottom) // 2)
                    drag(start, (start[0] - 90, start[1] + 70), host)
                    after = rectangle(host._hwnd)
                    assert after[:2] != before[:2], ('Floating title could not move the window', before, after)
                    view.dock_console(_native_confirmed=True)
                    pump(16)
                    assert not host._native_visible
                print('PASS: warm title tear-off keeps the original press, detached caption drag, '
                      'dock and second tear-off', flush=True)
            finally:
                user32.mouse_event(0x0004, 0, 0, 0, 0)
                view.request_shutdown()
                view._gui_runtime.destroy()


if __name__ == '__main__':
    main()
