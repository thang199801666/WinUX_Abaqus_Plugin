"""Physical menu-bar switching: abaqus python tests/test_menubar_hover_ui.py.

Run alone; this test temporarily moves the desktop cursor.
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

from DearUIQt.backends.native_windows import NativeWindowBackend
from WinUx.controllers.callbacks import REQUIRED_CALLBACK_KEYS
from WinUx.view import WinUXView
from native_owner_probe import NativeOwnerProbe, _Message


def main():
    user32 = ctypes.windll.user32
    user32.GetForegroundWindow.restype = wintypes.HWND
    cursor = wintypes.POINT()
    assert user32.GetCursorPos(ctypes.byref(cursor))
    user32.GetDC.argtypes = [wintypes.HWND]
    user32.GetDC.restype = wintypes.HDC
    user32.ReleaseDC.argtypes = [wintypes.HWND, wintypes.HDC]
    gdi32 = ctypes.windll.gdi32
    gdi32.GetPixel.argtypes = [wintypes.HDC, ctypes.c_int, ctypes.c_int]
    gdi32.GetPixel.restype = wintypes.DWORD

    def pixel(dc, x, y):
        color = int(gdi32.GetPixel(dc, int(x), int(y)))
        assert color != 0xffffffff, 'Desktop pixel capture unavailable'
        return color & 255, (color >> 8) & 255, (color >> 16) & 255
    temp = Path(os.environ['LOCALAPPDATA']) / 'Temp' / 'opencode'
    with tempfile.TemporaryDirectory(prefix='menubar-hover-', dir=temp) as profile, \
            patch.dict(os.environ, {'APPDATA': profile}):
        view = WinUXView({key: lambda *a, **kw: None for key in REQUIRED_CALLBACK_KEYS})
        view._gui_runtime.show()
        hook = None
        probe = None
        dc = None

        def pump(count=1):
            for _ in range(count):
                view.update()
                time.sleep(.016)

        try:
            pump(15)
            owner = view._find_main_viewport_hwnd()
            user32.SetWindowPos(wintypes.HWND(owner), wintypes.HWND(-1), 0, 0, 0, 0, 0x0013)
            thread = user32.GetWindowThreadProcessId(user32.GetForegroundWindow(), None)
            current = ctypes.windll.kernel32.GetCurrentThreadId()
            attached = user32.AttachThreadInput(current, thread, True)
            try:
                user32.SetForegroundWindow(wintypes.HWND(owner))
            finally:
                if attached:
                    user32.AttachThreadInput(current, thread, False)
            pump(8)
            assert int(user32.GetForegroundWindow() or 0) == owner
            bar = view._menu_bar_wrapper
            if '--baseline' in sys.argv:
                for root in bar._menus:
                    root.backend.configure_item(root.tag, no_focus_on_appearing=False,
                                                no_bring_to_front_on_focus=False)
            menu = bar._menus[4]  # View, as in the reported screenshot.
            rect = bar._button_anchor_rect(bar._buttons[menu])
            x, y, width, height = bar._button_anchor_screen_rect(rect)
            user32.SetCursorPos(int(x + width / 2), int(y + height / 2))
            pump(4)
            user32.mouse_event(0x0002, 0, 0, 0, 0)
            pump(2)
            user32.mouse_event(0x0004, 0, 0, 0, 0)
            pump(20)
            assert menu.isVisible()
            popup = NativeWindowBackend().winId(menu.tag)
            assert popup
            probe = NativeOwnerProbe(owner).start()
            messages = Counter()
            activation = []
            callback_type = ctypes.WINFUNCTYPE(ctypes.c_ssize_t, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM)

            @callback_type
            def observe(code, wparam, lparam):
                if code >= 0:
                    message = ctypes.cast(lparam, ctypes.POINTER(_Message)).contents
                    hwnd = int(message.hwnd or 0)
                    if hwnd == owner:
                        messages[(hwnd == owner, hex(message.message), int(message.wparam))] += 1
                        if message.message in (0x0006, 0x0086):
                            activation.append((hwnd == owner, hex(message.message), int(message.wparam)))
                return user32.CallNextHookEx(hook, code, wparam, lparam)

            hook = user32.SetWindowsHookExW(4, observe, None, current)
            assert hook
            foreground = Counter()
            dc = user32.GetDC(None)
            assert dc
            main_rect = wintypes.RECT()
            user32.GetWindowRect(wintypes.HWND(owner), ctypes.byref(main_rect))
            # Stable blank client/title pixels, outside the dropdown and cursor.
            samples = [(main_rect.left + 20, main_rect.top + 15),
                       (main_rect.left + 30, main_rect.bottom - 90),
                       (main_rect.right - 30, main_rect.bottom - 90)]
            baseline = [pixel(dc, *point) for point in samples]
            visual_changes = []
            switches = 0
            for menu in (bar._menus + list(reversed(bar._menus))) * 2:
                rect = bar._button_anchor_rect(bar._buttons[menu])
                x, y, width, height = bar._button_anchor_screen_rect(rect)
                for frame in range(16):
                    user32.SetCursorPos(int(x + width / 2), int(y + height / 2))
                    pump()
                    foreground[int(user32.GetForegroundWindow() or 0)] += 1
                    ctypes.windll.dwmapi.DwmFlush()
                    current_pixels = [pixel(dc, *point) for point in samples]
                    if current_pixels != baseline:
                        visual_changes.append((bar._menus.index(menu), frame, current_pixels))
                assert bar._active_menu is menu and menu.isVisible(), (
                    'Hover did not switch menu', bar._menus.index(menu),
                    bar._menus.index(bar._active_menu) if bar._active_menu in bar._menus else None,
                    (x, y, width, height), [(root.isVisible()) for root in bar._menus],
                    list(activation[-8:]), foreground)
                switches += 1
            print('Owner', owner, 'popup', popup, 'foreground', foreground, flush=True)
            print('Activation', activation[:30], 'count', len(activation), flush=True)
            print('Owner events', probe.events[:30], 'count', len(probe.events), flush=True)
            print('Messages', messages.most_common(20), flush=True)
            print('Switches', switches, 'visual changes', visual_changes[:8], flush=True)
            assert not probe.events, ('Owner hidden/reframed while switching menus', probe.events)
            assert not activation, ('Owner activation changed while switching menus', activation)
            assert set(foreground) == {owner}, foreground
            assert not visual_changes, ('Owner pixels flashed', visual_changes[:8])
            # Logical popup keyboard routing must still work without giving
            # the native popup focus. Keep the pointer off the rows so it does
            # not overwrite keyboard selection on the next hover callback.
            geometry = menu.globalGeometry()
            user32.SetCursorPos(geometry.x() + 1, geometry.y() + 1)
            pump(6)
            ids = menu._visible_action_ids()
            index = ids.index(menu._active_action) if menu._active_action in ids else 0
            expected = ids[(index + 1) % len(ids)]
            user32.keybd_event(0x28, 0, 0, 0)  # Down
            pump(2)
            user32.keybd_event(0x28, 0, 2, 0)
            pump(6)
            assert menu._active_action == expected, ('Keyboard selection failed', expected, menu._active_action)
            user32.keybd_event(0x1B, 0, 0, 0)  # Escape
            pump(2)
            user32.keybd_event(0x1B, 0, 2, 0)
            pump(6)
            assert not menu.isVisible(), 'Escape did not close no-focus popup'
            print('PASS: 24 menu-bar hover switches, stable owner pixels/focus; Down/Escape work', flush=True)
        finally:
            if hook:
                user32.UnhookWindowsHookEx(hook)
            if probe:
                probe.close()
            if dc:
                user32.ReleaseDC(None, dc)
            user32.mouse_event(0x0004, 0, 0, 0, 0)
            user32.SetCursorPos(cursor.x, cursor.y)
            view.request_shutdown()
            view._gui_runtime.destroy()


if __name__ == '__main__':
    main()
