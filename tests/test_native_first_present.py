"""First exposure regression: abaqus python tests/test_native_first_present.py."""
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
from DearUIQt.backends.native_presentation import presentation_for
from DearUIQt.backends.native_windows import NativeWindowBackend
from DearUIQt.dialogs.qt_dialog import QtDialog
from DearUIQt.widgets import QMenu, QComboBox, QToolButton
from WinUx.controllers.callbacks import REQUIRED_CALLBACK_KEYS
from WinUx.view import WinUXView
from WinUx.preferences.dialog_geometry import DialogGeometryPreferences


def main():
    view = WinUXView({key: lambda *a, **k: None for key in REQUIRED_CALLBACK_KEYS})
    preferences = tempfile.TemporaryDirectory(
        prefix='winux-first-present-',
        dir=Path(os.environ['LOCALAPPDATA']) / 'Temp' / 'opencode')
    view._compact_geometry_preferences = DialogGeometryPreferences(root=preferences.name)
    view._gui_runtime.show()
    presentation = presentation_for(view._gui_runtime.backend, create=True)
    assert presentation is not None
    native = NativeWindowBackend()
    events = []
    current_frame = [0]
    original_cloak = presentation._cloak

    def record_cloak(hwnd, enabled):
        success = original_cloak(hwnd, enabled)
        events.append((int(hwnd), enabled, success, current_frame[0],
                       presentation._geometry(hwnd), presentation._hook is not None))
        return success

    presentation._cloak = record_cloak

    owner_hwnd = view._find_main_viewport_hwnd()

    def verify_owner():
        user32 = ctypes.windll.user32
        owner = wintypes.HWND(owner_hwnd)
        assert user32.IsWindowVisible(owner), 'Main WinUx window was hidden'
        assert not user32.IsIconic(owner), 'Main WinUx window was minimized'
        cloaked = wintypes.DWORD()
        assert ctypes.windll.dwmapi.DwmGetWindowAttribute(
            owner, 14, ctypes.byref(cloaked), ctypes.sizeof(cloaked)) == 0
        assert cloaked.value == 0, 'Main WinUx window was DWM-cloaked'

    def pump(frames=12):
        for _ in range(frames):
            current_frame[0] += 1
            view.update()
            verify_owner()
            time.sleep(.01)

    def verify(item):
        pump()
        hwnd = native.winId(item)
        assert hwnd
        history = [event for event in events if event[0] == hwnd]
        assert history and history[0][1:3] == (True, True), history
        assert history[0][5], 'A new native window was not cloaked in its pre-show hook'
        exposed = [event for event in history if not event[1] and event[2]]
        assert len(exposed) == 1, history
        assert exposed[0][3] > history[0][3], 'Window revealed before its hidden layout rendered'
        assert exposed[0][3] - history[0][3] < 8, 'Presentation fell back instead of settling'
        assert exposed[0][4] == presentation._geometry(hwnd), (
            'First visible geometry was provisional', history, presentation._geometry(hwnd))
        cloaked = wintypes.DWORD()
        assert ctypes.windll.dwmapi.DwmGetWindowAttribute(
            wintypes.HWND(hwnd), 14, ctypes.byref(cloaked), ctypes.sizeof(cloaked)) == 0
        assert cloaked.value == 0, 'Native window remained invisible'
        return hwnd

    pump(4)
    for compact in (False, True):
        if compact:
            view.collapse_to_job_monitor()
            pump()
        for title in ('Job Status', 'Job Details'):
            dialog = view.show_message(title, 'Job 123: Running')
            pump()
            user32 = ctypes.windll.user32
            user32.GetWindow.argtypes = [wintypes.HWND, ctypes.c_uint]
            user32.GetWindow.restype = wintypes.HWND
            child = native.winId(dialog.tag)
            assert int(user32.GetWindow(wintypes.HWND(child), 4) or 0) == owner_hwnd
            # A newly allocated platform HWND can have no window behind it
            # until activation settles. Repair must not lower/repaint WinUx
            # based on this provisional ordering (the one-frame flash).
            get_window = user32.GetWindow
            set_position = user32.SetWindowPos
            owner_moves = []

            def provisional_order(hwnd, command):
                handle = getattr(hwnd, 'value', hwnd)
                if handle == child and command == 2:
                    return 0
                return get_window(hwnd, command)

            def record_position(hwnd, *args):
                if getattr(hwnd, 'value', hwnd) == owner_hwnd:
                    owner_moves.append(args)
                return set_position(hwnd, *args)

            user32.GetWindow = provisional_order
            user32.SetWindowPos = record_position
            try:
                dialog._recover_native_owner_presentation()
                assert not owner_moves, 'Provisional dialog order moved the main window'
            finally:
                user32.GetWindow = get_window
                user32.SetWindowPos = set_position
            if not compact:
                # Reproduce a late platform Z-order transition, *after* the
                # one-shot first-present repair. An unrelated window must not
                # obscure WinUx while its modal remains in foreground.
                user32.CreateWindowExW.argtypes = [
                    wintypes.DWORD, wintypes.LPCWSTR, wintypes.LPCWSTR,
                    wintypes.DWORD, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                    ctypes.c_int, wintypes.HWND, wintypes.HMENU,
                    wintypes.HINSTANCE, ctypes.c_void_p]
                user32.CreateWindowExW.restype = wintypes.HWND
                blocker = user32.CreateWindowExW(
                    0x08000000, 'STATIC', 'WinUx Z-order regression',
                    0x90000000, 50, 50, 640, 480, None, None, None, None)
                assert blocker
                try:
                    foreground_thread = user32.GetWindowThreadProcessId(
                        user32.GetForegroundWindow(), None)
                    current_thread = ctypes.windll.kernel32.GetCurrentThreadId()
                    attached = user32.AttachThreadInput(current_thread, foreground_thread, True)
                    try:
                        user32.SetForegroundWindow(wintypes.HWND(child))
                    finally:
                        if attached:
                            user32.AttachThreadInput(current_thread, foreground_thread, False)
                    user32.SetWindowPos(blocker, wintypes.HWND(child),
                                        0, 0, 0, 0, 0x0013)
                    behind = int(user32.GetWindow(wintypes.HWND(child), 2) or 0)
                    while behind and not user32.IsWindowVisible(wintypes.HWND(behind)):
                        behind = int(user32.GetWindow(wintypes.HWND(behind), 2) or 0)
                    assert behind == blocker
                    pump(4)
                    behind = int(user32.GetWindow(wintypes.HWND(child), 2) or 0)
                    while behind and not user32.IsWindowVisible(wintypes.HWND(behind)):
                        behind = int(user32.GetWindow(wintypes.HWND(behind), 2) or 0)
                    assert behind == owner_hwnd, (
                        'Late modal activation obscured WinUx', child, owner_hwnd,
                        behind, int(user32.GetForegroundWindow() or 0))
                finally:
                    user32.DestroyWindow(wintypes.HWND(blocker))
            behind = int(user32.GetWindow(wintypes.HWND(child), 2) or 0)
            while behind and not user32.IsWindowVisible(wintypes.HWND(behind)):
                behind = int(user32.GetWindow(wintypes.HWND(behind), 2) or 0)
            assert behind == owner_hwnd, ('Main WinUx window fell behind another window',
                                          title, child, owner_hwnd, behind)
            dialog.accept()
            pump(8)
        for modal in (True, False):
            events.clear()
            dialog = QtDialog(view, 'First present', width=440, height=280,
                              modal=modal, footer=False, resizable=False)
            button = QToolButton('Menu', parent=dialog.content)
            combo = QComboBox(['Choice {}'.format(i) for i in range(20)],
                              parent=dialog.content, width=160)
            dialog.show()
            verify(dialog.tag)
            menu = QMenu([{'label': 'One', 'action': 'one'}])
            button.setMenu(menu)
            events.clear()
            assert button.showMenu()
            verify(menu.tag)
            menu.hide()
            pump(4)
            events.clear()
            assert combo.showPopup()
            verify(combo._choice_popup.tag)
            combo.hidePopup()
            pump(4)
            menu.delete()
            dialog.destroy()
            pump(8)
        events.clear()
        context = QMenu([{'label': 'Details', 'action': 'details'}])
        context.popupGlobal((200, 200))
        verify(context.tag)
        context.hide()
        pump(4)
        # Closing before first presentation must not reveal or strand a popup.
        context.popupGlobal((300, 300))
        context.hide()
        pump(4)
        assert not presentation.pending and not presentation.cloaked
        # Also cancel after HWND creation, while its first frame is cloaked.
        context.popupGlobal((300, 300))
        pump(1)
        context.hide()
        pump(4)
        assert not presentation.pending and not presentation.cloaked
        context.delete()
        early = QtDialog(view, 'Cancel before exposure', width=400, height=240,
                         footer=False, resizable=False)
        early.show()
        pump(1)
        early.destroy()
        pump(8)
        assert not presentation.pending and not presentation.cloaked
        print('PASS:', 'PiP' if compact else 'full app',
              'pre-show cloak, stable first exposure, dialogs/dropdowns/context, cancellation', flush=True)
    presentation._cloak = original_cloak
    view.request_shutdown()
    view._gui_runtime.destroy()
    preferences.cleanup()


if __name__ == '__main__':
    main()
