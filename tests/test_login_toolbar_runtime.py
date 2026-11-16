"""Real toolbar click + hidden hosts: abaqus python tests/test_login_toolbar_runtime.py.

No mocked foreground/input clock. Do not use the mouse while this GUI test runs.
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

from DearUIQt.backends.native_windows import NativeWindowBackend, _last_input_tick
from WinUx.controller import WinUXController
from WinUx.preferences.general import GeneralPreferences


def main():
    temp_root = Path(os.environ['LOCALAPPDATA']) / 'Temp' / 'opencode'
    with tempfile.TemporaryDirectory(prefix='winux-login-toolbar-', dir=temp_root) as profile:
        settings = GeneralPreferences(root=profile)
        settings._store.save({'auto_login': False, 'console_visible': True})
        with patch.dict(os.environ, {'APPDATA': profile, 'WINUX_DISABLE_HARD_EXIT': '1',
                                     'WINUX_STANDALONE_PROCESS': '0'}):
            app = WinUXController()
            view = app.view
            view._gui_runtime.show()
            native = NativeWindowBackend()
            user32 = ctypes.windll.user32
            user32.GetForegroundWindow.restype = wintypes.HWND
            owner = wintypes.HWND(view._find_main_viewport_hwnd())

            def pump(frames=1, verify_login=False):
                for _ in range(frames):
                    view.update()
                    assert user32.IsWindowVisible(owner), 'Log-in hid the main WinUx window'
                    assert not user32.IsIconic(owner)
                    cloak = wintypes.DWORD()
                    assert ctypes.windll.dwmapi.DwmGetWindowAttribute(
                        owner, 14, ctypes.byref(cloak), ctypes.sizeof(cloak)) == 0
                    assert cloak.value == 0, 'Log-in DWM-cloaked WinUx'
                    if verify_login:
                        dialog = view.login_dialog
                        child = native.winId(dialog.tag)
                        foreground = int(user32.GetForegroundWindow() or 0)
                        assert foreground in (owner.value, child), (
                            'A hidden warm-up worker stole foreground', foreground, owner.value, child)
                    time.sleep(.02)

            try:
                pump(3)
                foreground_thread = user32.GetWindowThreadProcessId(
                    user32.GetForegroundWindow(), None)
                current_thread = ctypes.windll.kernel32.GetCurrentThreadId()
                attached = user32.AttachThreadInput(current_thread, foreground_thread, True)
                try:
                    user32.BringWindowToTop(owner)
                    user32.SetForegroundWindow(owner)
                finally:
                    if attached:
                        user32.AttachThreadInput(current_thread, foreground_thread, False)

                # Force the real startup race: the dock cache is starting in a
                # child process while the user presses Log-in. Do not skip the
                # console warm-up or replace the toolbar/controller callback.
                view._prepare_console_native_host()
                pump(3)
                button = view.right.toolbar.path_button
                rect = button.globalGeometry()
                user32.SetCursorPos(int(rect.x() + rect.width() / 2),
                                    int(rect.y() + rect.height() / 2))
                user32.mouse_event(0x0002, 0, 0, 0, 0)
                pump(2)
                user32.mouse_event(0x0004, 0, 0, 0, 0)
                for _ in range(16):
                    pump()
                    if getattr(view, 'login_dialog', None) is not None:
                        break
                assert getattr(view, 'login_dialog', None) is not None, 'Real Log-in click was lost'
                dialog = view.login_dialog
                pump(8, verify_login=True)

                # Invalidate the old opening-focus snapshot with new input on
                # the visible dialog. The test must pass by preventing hidden
                # worker activation, not by repeatedly stealing foreground back.
                tick = _last_input_tick(user32)
                child = native.winId(dialog.tag)
                rect = wintypes.RECT()
                user32.GetWindowRect(wintypes.HWND(child), ctypes.byref(rect))
                user32.SetCursorPos(rect.left + 30, rect.top + 50)
                user32.mouse_event(0x0001, 1, 0, 0, 0)
                pump(2, verify_login=True)
                assert _last_input_tick(user32) != tick

                deadline = time.monotonic() + 8
                while time.monotonic() < deadline:
                    pump(verify_login=True)
                    host = getattr(view, '_native_console_host', None)
                    if host is not None and host._ready:
                        # The console host may launch an idle replacement
                        # worker too. Observe those late hidden render turns.
                        pump(100, verify_login=True)
                        break
                assert host is not None and host._ready, 'Hidden Console did not finish warm-up'
                assert not host._native_visible
                assert not user32.IsWindowEnabled(wintypes.HWND(host._hwnd)), (
                    'Hidden Console must not be eligible for native activation')
                assert int(user32.GetForegroundWindow() or 0) == child
                dialog.cancel_from_window()
                pump(8)
                assert user32.IsWindowEnabled(owner)

                # A background activation guard must not break an intentional
                # dock tear-off: the same resident HWND is enabled on show and
                # made non-activatable again when docked/hidden.
                assert view.undock_console()
                deadline = time.monotonic() + 4
                while time.monotonic() < deadline:
                    pump()
                    if (host._native_visible and user32.IsWindowEnabled(wintypes.HWND(host._hwnd))
                            and int(user32.GetForegroundWindow() or 0) == host._hwnd):
                        break
                assert host._native_visible and user32.IsWindowEnabled(wintypes.HWND(host._hwnd))
                assert int(user32.GetForegroundWindow() or 0) == host._hwnd
                view.dock_console(_native_confirmed=True)
                pump(16)
                assert not host._native_visible
                assert not user32.IsWindowEnabled(wintypes.HWND(host._hwnd))
                print('PASS: actual controller/Log-in click, hidden Console + idle worker '
                      'cannot take focus, new input, Cancel and explicit dock show/hide', flush=True)
            finally:
                app._finish_close()
                view._gui_runtime.destroy()


if __name__ == '__main__':
    main()
