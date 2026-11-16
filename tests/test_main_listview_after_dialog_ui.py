"""abaqus python tests/test_main_listview_after_dialog_ui.py.

Real pointer/wheel input. Do not move the mouse while this test is running.
No live SSH connection or real filesystem modifications are used.
"""
import ctypes
import os
import math
import sys
import tempfile
import time
from contextlib import ExitStack
from ctypes import wintypes
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import run_winux
run_winux._configure_bundled_dependencies(str(ROOT))
from DearUIQt.backends import dpg
from DearUIQt.gui.placement import item_screen_rect
from WinUx.controllers.callbacks import REQUIRED_CALLBACK_KEYS
from WinUx.ui.components.explorer.list_view import ListViewItem
from WinUx.view import WinUXView


def main():
    stack = ExitStack()
    temporary = Path(os.environ['LOCALAPPDATA']) / 'Temp' / 'opencode'
    profile = stack.enter_context(tempfile.TemporaryDirectory(prefix='winux-list-state-', dir=temporary))
    stack.enter_context(patch.dict(os.environ, {
        'APPDATA': profile, 'WINUX_STANDALONE_PROCESS': '0', 'WINUX_DISABLE_HARD_EXIT': '1'}))
    from WinUx.preferences.general import GeneralPreferences
    GeneralPreferences(root=profile)._store.save({'auto_login': False, 'console_visible': True})
    app = None
    if '--controller' in sys.argv:
        from WinUx.controller import WinUXController
        app = WinUXController()
        view = app.view
    else:
        view = WinUXView({key: lambda *args, **kwargs: None for key in REQUIRED_CALLBACK_KEYS})
    view._gui_runtime.show()
    user32 = ctypes.windll.user32
    user32.GetForegroundWindow.restype = wintypes.HWND
    owner = wintypes.HWND(view._find_main_viewport_hwnd())
    def pump(count=1):
        for _ in range(count):
            view.update()
            time.sleep(.015)
    def click(x, y):
        assert user32.SetCursorPos(int(x), int(y))
        pump(2)
        actual = wintypes.POINT()
        assert user32.GetCursorPos(ctypes.byref(actual))
        assert (actual.x, actual.y) == (int(x), int(y)), 'Desktop input interrupted; do not move the mouse'
        user32.mouse_event(0x0002, 0, 0, 0, 0)
        pump(2)
        user32.mouse_event(0x0004, 0, 0, 0, 0)
        pump(6)
    def exercise(lv, label):
        left, top, right, bottom = item_screen_rect(dpg, lv.body_window)
        x, y = left + min(150, (right-left)/2), top + min(80, (bottom-top)/2)
        click(x, y)
        before = dpg.get_y_scroll(lv.body_window)
        user32.mouse_event(0x0800, 0, 0, -360, 0)
        pump(8)
        scrolled = dpg.get_y_scroll(lv.body_window)
        assert scrolled > before + 1, (label, 'Wheel blocked', before, scrolled)
        pump(16)
        assert abs(dpg.get_y_scroll(lv.body_window) - scrolled) <= 1, (
            label, 'Wheel scroll snapped back', scrolled, dpg.get_y_scroll(lv.body_window))
        row = int(math.floor((scrolled + 60) / lv.ROW_HEIGHT))
        row_y = top + (row + .5) * lv.ROW_HEIGHT - scrolled
        click(x, row_y)
        assert lv.selected == {row}, (label, 'Click did not select row', row, lv.selected)
        pump(20)
        assert lv.selected == {row}, (label, 'Selection snapped back', row, lv.selected)
        assert abs(dpg.get_y_scroll(lv.body_window) - scrolled) <= 1, (
            label, 'Click reset scroll', scrolled, dpg.get_y_scroll(lv.body_window))
    try:
        pump(8)
        if app is not None:
            deadline = time.monotonic() + 8
            while app._initial_load_pending and time.monotonic() < deadline:
                pump()
            assert not app._initial_load_pending, 'Initial folder did not finish loading'
        thread = user32.GetWindowThreadProcessId(user32.GetForegroundWindow(), None)
        current = ctypes.windll.kernel32.GetCurrentThreadId()
        attached = user32.AttachThreadInput(current, thread, True)
        try:
            user32.BringWindowToTop(owner)
            user32.SetForegroundWindow(owner)
        finally:
            if attached:
                user32.AttachThreadInput(current, thread, False)
        for panel in (view.left, view.right):
            panel.listview.set_items([
                ListViewItem(name='Item {:03d}.txt'.format(i),
                             path='C:/focus-fixture/{:03d}.txt'.format(i),
                             is_dir=False, item_type='File') for i in range(150)])
        pump(12)
        for stage in ('startup', 'Login Cancel', 'Message OK', 'Settings Cancel'):
            if stage == 'Login Cancel':
                dialog = view.show_login()
                pump(12)
                dialog.reject()
            elif stage == 'Message OK':
                dialog = view.show_message('Focus regression', 'Close with OK')
                pump(12)
                dialog.accept()
            elif stage == 'Settings Cancel':
                dialog = view.show_settings()
                pump(12)
                dialog.reject()
            pump(12)
            assert int(user32.GetForegroundWindow() or 0) == owner.value, (stage, 'Main not foreground')
            for panel in (view.left, view.right):
                exercise(panel.listview, (stage, panel.panel_id))
        print('PASS: main Local/Server selection and wheel state survive dialog closes', flush=True)
    finally:
        user32.mouse_event(0x0004, 0, 0, 0, 0)
        if app is not None:
            app._finish_close()
        else:
            view.request_shutdown()
        view._gui_runtime.destroy()
        stack.close()


if __name__ == '__main__':
    main()
