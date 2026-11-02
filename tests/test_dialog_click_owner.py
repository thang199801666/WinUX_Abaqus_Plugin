"""Dialog client clicks keep WinUx behind it: abaqus python tests/test_dialog_click_owner.py."""
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

from DearUIQt.backends.native_windows import NativeWindowBackend
from DearUIQt.dialogs.qt_dialog import QtDialog
from WinUx.controllers.callbacks import REQUIRED_CALLBACK_KEYS
from WinUx.view import WinUXView
from native_owner_probe import NativeOwnerProbe


def main():
    cursor = wintypes.POINT()
    assert ctypes.windll.user32.GetCursorPos(ctypes.byref(cursor)), (
        'Interactive desktop is inaccessible: GetCursorPos failed; '
        'this physical-input regression cannot run on a locked/inaccessible desktop')
    temp_root = Path(os.environ['LOCALAPPDATA']) / 'Temp' / 'opencode'
    with tempfile.TemporaryDirectory(prefix='winux-dialog-click-', dir=temp_root) as profile:
        with patch.dict(os.environ, {'APPDATA': profile}):
            view = WinUXView({key: lambda *a, **k: None for key in REQUIRED_CALLBACK_KEYS})
            view._gui_runtime.show()
            user32 = ctypes.windll.user32
            native = NativeWindowBackend()
            user32.GetForegroundWindow.restype = wintypes.HWND
            user32.GetWindow.argtypes = [wintypes.HWND, ctypes.c_uint]
            user32.GetWindow.restype = wintypes.HWND
            user32.CreateWindowExW.argtypes = [
                wintypes.DWORD, wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.DWORD,
                ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                wintypes.HWND, wintypes.HMENU, wintypes.HINSTANCE, ctypes.c_void_p]
            user32.CreateWindowExW.restype = wintypes.HWND
            blocker = None
            dialog = None
            probe = None

            def pump(frames=8):
                for _ in range(frames):
                    view.update()
                    time.sleep(.02)

            def foreground(hwnd):
                tid = user32.GetWindowThreadProcessId(user32.GetForegroundWindow(), None)
                current = ctypes.windll.kernel32.GetCurrentThreadId()
                attached = user32.AttachThreadInput(current, tid, True)
                try:
                    user32.BringWindowToTop(wintypes.HWND(hwnd))
                    user32.SetForegroundWindow(wintypes.HWND(hwnd))
                finally:
                    if attached:
                        user32.AttachThreadInput(current, tid, False)
                if int(user32.GetForegroundWindow() or 0) != hwnd:
                    # Foreground permission is not guaranteed for a test
                    # launched from a terminal. Use actual caption input rather
                    # than pretending that SetForegroundWindow succeeded.
                    rect = wintypes.RECT()
                    assert user32.GetWindowRect(wintypes.HWND(hwnd), ctypes.byref(rect))
                    assert user32.SetCursorPos(rect.left + 80, rect.top + 15)
                    user32.mouse_event(0x0002, 0, 0, 0, 0)
                    user32.mouse_event(0x0004, 0, 0, 0, 0)
                    pump(3)

            def verify_pair(child, owner):
                assert user32.IsWindowVisible(wintypes.HWND(owner))
                assert not user32.IsIconic(wintypes.HWND(owner))
                cloak = wintypes.DWORD()
                assert ctypes.windll.dwmapi.DwmGetWindowAttribute(
                    wintypes.HWND(owner), 14, ctypes.byref(cloak), ctypes.sizeof(cloak)) == 0
                assert not cloak.value
                assert int(user32.GetForegroundWindow() or 0) == child, (
                    'Dialog did not keep native foreground after the click', dialog.modal,
                    child, int(user32.GetForegroundWindow() or 0),
                    user32.IsWindowEnabled(wintypes.HWND(child)))
                behind = int(user32.GetWindow(wintypes.HWND(child), 2) or 0)
                while behind and not user32.IsWindowVisible(wintypes.HWND(behind)):
                    behind = int(user32.GetWindow(wintypes.HWND(behind), 2) or 0)
                assert behind == owner, ('Clicking the dialog left WinUx behind another window',
                                          dialog.modal, child, owner, behind)

            try:
                pump()
                owner = view._find_main_viewport_hwnd()
                # Establish foreground before creating an unrelated HWND, as
                # in the real application when the user opens a dialog.
                foreground(owner)
                assert int(user32.GetForegroundWindow() or 0) == owner
                x, y, width, height = view._compact_window_rect()
                blocker = user32.CreateWindowExW(
                    0x08000000, 'STATIC', 'Dialog owner regression background',
                    0x90000000, x, y, width, height, None, None, None, None)
                assert blocker
                # Exercise the real form as well as the minimal dialog below;
                # in particular, do not force child foreground after opening.
                foreground(owner)
                dialog = view.show_settings()
                pump(16)
                child = native.winId(dialog.tag)
                verify_pair(child, owner)
                dialog.destroy()
                dialog = None
                pump()
                for modal in (True, False):
                    foreground(owner)
                    pump(2)
                    assert int(user32.GetForegroundWindow() or 0) == owner, (
                        'Main test window did not activate', owner, user32.GetForegroundWindow())
                    dialog = QtDialog(view, 'Click inside dialog', width=420, height=250,
                                      modal=modal, footer=False)
                    dialog.show()
                    pump(12)
                    child = native.winId(dialog.tag)
                    foreground(child)
                    assert int(user32.GetForegroundWindow() or 0) == child, 'Could not focus the test dialog'
                    for _ in range(2):
                        # A separate application can end up between dialog and
                        # owner after native activation. Click the dialog itself
                        # (new input), not an opening-time focus-repair mock.
                        user32.SetWindowPos(wintypes.HWND(blocker), wintypes.HWND(child),
                                            x, y, width, height, 0x0010)
                        point = wintypes.POINT(30, 40)
                        user32.ClientToScreen(wintypes.HWND(child), ctypes.byref(point))
                        assert user32.SetCursorPos(point.x, point.y)
                        user32.mouse_event(0x0002, 0, 0, 0, 0)
                        pump(2)
                        user32.mouse_event(0x0004, 0, 0, 0, 0)
                        pump()
                        verify_pair(child, owner)
                    dialog.destroy()
                    pump()
                    dialog = None
                # Opening a second dialog while the first remains active must
                # keep the entire owner chain on screen, not just its leaf.
                foreground(owner)
                outer = QtDialog(view, 'Outer dialog', width=480, height=300,
                                 modal=True, footer=False)
                outer.show()
                pump(12)
                outer_hwnd = native.winId(outer.tag)
                user32.SetWindowPos(wintypes.HWND(blocker), wintypes.HWND(outer_hwnd),
                                    x, y, width, height, 0x0010)
                dialog = QtDialog(view, 'Nested dialog', width=360, height=200,
                                  modal=True, footer=False)
                dialog.show()
                pump(12)
                child = native.winId(dialog.tag)
                verify_pair(child, outer_hwnd)
                behind = int(user32.GetWindow(wintypes.HWND(outer_hwnd), 2) or 0)
                while behind and not user32.IsWindowVisible(wintypes.HWND(behind)):
                    behind = int(user32.GetWindow(wintypes.HWND(behind), 2) or 0)
                assert behind == owner, ('Nested dialog obscured main window', behind, owner)
                dialog.destroy()
                dialog = None
                outer.destroy()
                pump()
                # Legacy process-hosted modal/modeless dialogs use the same
                # backend visibility/stack policy as ordinary in-process forms.
                from WinUx.dialogs.floating_adapters import SettingsDialog, JobEditDialog
                for factory in (lambda: SettingsDialog(view), lambda: JobEditDialog(
                        view, ('123', 'Example', 'user', '4', 'R', '00:01:00'))):
                    foreground(owner)
                    probe = NativeOwnerProbe(owner).start()
                    dialog = factory()
                    dialog.show()
                    deadline = time.monotonic() + 20
                    while time.monotonic() < deadline:
                        pump(1)
                        if dialog._ready and dialog._native_visible:
                            break
                    assert dialog._ready and dialog._native_visible
                    child = dialog._hwnd
                    pump(8)
                    verify_pair(child, owner)
                    user32.SetWindowPos(wintypes.HWND(blocker), wintypes.HWND(child),
                                        x, y, width, height, 0x0010)
                    point = wintypes.POINT(30, 40)
                    user32.ClientToScreen(wintypes.HWND(child), ctypes.byref(point))
                    assert user32.SetCursorPos(point.x, point.y)
                    user32.mouse_event(0x0002, 0, 0, 0, 0)
                    pump(2)
                    user32.mouse_event(0x0004, 0, 0, 0, 0)
                    pump(8)
                    verify_pair(child, owner)
                    dialog.destroy()
                    dialog = None
                    pump(16)
                    probe.close()
                    assert not probe.events, ('Process-hosted dialog changed main presentation', probe.events)
                    probe = None
                print('PASS: real Settings opening, physical client clicks, modal/modeless '
                      'owner stacking, nested/process-hosted dialogs and main visibility', flush=True)
            finally:
                if probe is not None:
                    probe.close()
                user32.mouse_event(0x0004, 0, 0, 0, 0)
                if blocker:
                    user32.DestroyWindow(wintypes.HWND(blocker))
                if dialog is not None:
                    dialog.destroy()
                view.request_shutdown()
                view._gui_runtime.destroy()


if __name__ == '__main__':
    main()
