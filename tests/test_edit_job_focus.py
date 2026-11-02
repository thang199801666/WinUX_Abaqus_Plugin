"""Actual Jobs context menu -> Edit Job: abaqus python tests/test_edit_job_focus.py.

Uses physical mouse input, no mocked foreground or input timestamps.
"""
import ctypes
import os
import sys
import tempfile
import time
from ctypes import wintypes
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import run_winux
run_winux._configure_bundled_dependencies(str(ROOT))

from DearUIQt.backends import dpg
from DearUIQt.backends.native_windows import NativeWindowBackend
from DearUIQt.gui.placement import item_screen_rect
from WinUx.controller import WinUXController
from WinUx.preferences.general import GeneralPreferences


def main():
    user32 = ctypes.windll.user32
    point = wintypes.POINT()
    assert user32.GetCursorPos(ctypes.byref(point)), 'Physical input desktop unavailable'
    user32.GetForegroundWindow.restype = wintypes.HWND
    user32.GetWindow.argtypes = [wintypes.HWND, ctypes.c_uint]
    user32.GetWindow.restype = wintypes.HWND
    temp_root = Path(os.environ['LOCALAPPDATA']) / 'Temp' / 'opencode'
    with tempfile.TemporaryDirectory(prefix='winux-edit-job-', dir=temp_root) as profile:
        GeneralPreferences(root=profile)._store.save({'auto_login': False, 'console_visible': False})
        with patch.dict(os.environ, {'APPDATA': profile, 'WINUX_DISABLE_HARD_EXIT': '1',
                                     'WINUX_STANDALONE_PROCESS': '0'}):
            app = WinUXController()
            view = app.view
            view._gui_runtime.show()
            native = NativeWindowBackend()
            owner = view._find_main_viewport_hwnd()

            def pump(frames=1):
                for _ in range(frames):
                    view.update()
                    assert user32.IsWindowVisible(wintypes.HWND(owner)), 'Edit Job hid main HWND'
                    assert not user32.IsIconic(wintypes.HWND(owner)), 'Edit Job minimized main HWND'
                    cloak = wintypes.DWORD()
                    ctypes.windll.dwmapi.DwmGetWindowAttribute(
                        wintypes.HWND(owner), 14, ctypes.byref(cloak), ctypes.sizeof(cloak))
                    assert not cloak.value, 'Edit Job cloaked main HWND'
                    time.sleep(.02)

            def click(x, y):
                assert user32.SetCursorPos(int(x), int(y))
                pump(3)
                user32.mouse_event(0x0002, 0, 0, 0, 0)
                pump(2)
                user32.mouse_event(0x0004, 0, 0, 0, 0)
                pump(12)

            try:
                pump(8)
                tid = user32.GetWindowThreadProcessId(user32.GetForegroundWindow(), None)
                current = ctypes.windll.kernel32.GetCurrentThreadId()
                attached = user32.AttachThreadInput(current, tid, True)
                try:
                    user32.BringWindowToTop(wintypes.HWND(owner))
                    user32.SetForegroundWindow(wintypes.HWND(owner))
                finally:
                    if attached:
                        user32.AttachThreadInput(current, tid, False)
                assert int(user32.GetForegroundWindow() or 0) == owner
                app.server.username = 'focus-test'
                jobs = view._ensure_jobs_view()
                sample = SimpleNamespace(job_id='123', name='Example', user='focus-test',
                                         tokens='4', status='R', elapsed='00:01:00')
                view.display_jobs([sample])
                jobs.listview.select_indices([0])
                pump(4)
                original_edit = view.edit_job

                def open_edit(*args, **kwargs):
                    menu_hwnd = native._rawWinId(menu.tag)
                    assert not menu_hwnd or not user32.IsWindowVisible(wintypes.HWND(menu_hwnd)), (
                        'Edit constructed before native context menu teardown')
                    assert int(user32.GetForegroundWindow() or 0) == owner, (
                        'Native menu did not hand foreground back to WinUx')
                    return original_edit(*args, **kwargs)

                view.edit_job = open_edit
                for attempt in range(2):
                    if attempt:
                        view.collapse_to_job_monitor()
                        view.display_jobs([sample])
                        jobs = view._compact_job_monitor
                        jobs.listview.select_indices([0])
                        pump(12)
                    menu = jobs.listview._build_item_context_menu()
                    jobs.listview._context_item_index = 0
                    jobs._context_open(jobs.listview.get_selected())
                    rect = wintypes.RECT()
                    user32.GetWindowRect(wintypes.HWND(owner), ctypes.byref(rect))
                    assert jobs.listview._show_item_context_menu((rect.left + 120, rect.top + 120))
                    pump(12)
                    bounds = item_screen_rect(dpg, menu._items['edit']['label'])
                    click((bounds[0] + bounds[2]) / 2, (bounds[1] + bounds[3]) / 2)
                    dialog = getattr(view, 'edit_job_dialog', None)
                    assert dialog is not None and dialog.winfo_exists(), 'Edit menu click was lost'
                    assert dialog._native_owner_open_lease is not None, (
                        'Edit opened before the native menu returned focus to WinUx')
                    child = native.winId(dialog.tag)
                    assert int(user32.GetForegroundWindow() or 0) == child, (
                        'Edit Job lost foreground', child, int(user32.GetForegroundWindow() or 0),
                        dialog._native_owner_open_lease)
                    behind = int(user32.GetWindow(wintypes.HWND(child), 2) or 0)
                    while behind and not user32.IsWindowVisible(wintypes.HWND(behind)):
                        behind = int(user32.GetWindow(wintypes.HWND(behind), 2) or 0)
                    assert behind == owner, ('Edit Job obscured main HWND', child, owner, behind)
                    point = wintypes.POINT(30, 60)
                    user32.ClientToScreen(wintypes.HWND(child), ctypes.byref(point))
                    click(point.x, point.y)
                    assert int(user32.GetForegroundWindow() or 0) == child
                    dialog.finish(None)
                    pump(12)
                    assert int(user32.GetForegroundWindow() or 0) == owner
                print('PASS: full/PiP Edit Job context action, native menu handoff/teardown, '
                      'owner visibility/stacking, dialog client click and reopen', flush=True)
            finally:
                user32.mouse_event(0x0004, 0, 0, 0, 0)
                app._finish_close()
                view._gui_runtime.destroy()


if __name__ == '__main__':
    main()
