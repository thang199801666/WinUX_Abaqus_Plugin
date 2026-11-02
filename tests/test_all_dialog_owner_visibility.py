"""Shared native menu/dialog policy: abaqus python tests/test_all_dialog_owner_visibility.py.

Physical input; run GUI tests sequentially and do not move the mouse.
"""
import ctypes
import os
import sys
import stat
import tempfile
import threading
import time
from ctypes import wintypes
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import run_winux
run_winux._configure_bundled_dependencies(str(ROOT))

from DearUIQt.backends import dpg
from DearUIQt.backends.native_windows import NativeWindowBackend
from DearUIQt.gui import QAction
from DearUIQt.gui.placement import item_screen_rect
from DearUIQt.widgets import QMenu
from WinUx.controllers.callbacks import REQUIRED_CALLBACK_KEYS
from WinUx.services.transfer_conflicts import ConflictReview, TransferItemState
from WinUx.view import WinUXView, _dialog_type
from native_owner_probe import NativeOwnerProbe


def main():
    user32 = ctypes.windll.user32
    cursor = wintypes.POINT()
    assert user32.GetCursorPos(ctypes.byref(cursor)), 'Physical input desktop unavailable'
    user32.GetForegroundWindow.restype = wintypes.HWND
    user32.GetWindow.argtypes = [wintypes.HWND, ctypes.c_uint]
    user32.GetWindow.restype = wintypes.HWND
    temp_root = Path(os.environ['LOCALAPPDATA']) / 'Temp' / 'opencode'
    with tempfile.TemporaryDirectory(prefix='winux-all-dialogs-', dir=temp_root) as profile:
        with patch.dict(os.environ, {'APPDATA': profile}):
            view = WinUXView({key: lambda *a, **k: None for key in REQUIRED_CALLBACK_KEYS})
            view._gui_runtime.show()
            owner = view._find_main_viewport_hwnd()
            native = NativeWindowBackend()
            menu = QMenu(after=view.after)
            opened = []
            noop = lambda *a, **k: None
            inp = Path(profile) / 'Example.inp'
            inp.write_text('*Heading\nNative owner regression\n', encoding='utf-8')
            conflict_source = Path(profile) / 'Existing.odb'
            conflict_source.write_bytes(b'odb')
            conflict_left = TransferItemState(3, time.time(), stat.S_IFREG | 0o644)
            conflict_right = TransferItemState(3, time.time() - 10, stat.S_IFREG | 0o644)
            conflict_review = ConflictReview(
                (conflict_source,), {str(conflict_source): conflict_left},
                {str(conflict_source): conflict_right}, Path(profile),
                'server', 'local', 1)
            specs = (
                ('Login', view.show_login),
                ('Settings', view.show_settings),
                ('Diagnostics', view.show_diagnostics),
                ('Bookmarks', lambda: view.show_bookmarks([], noop, noop, noop)),
                ('Site Manager', lambda: view.show_site_manager([], noop, noop, noop)),
                ('Job Schedule', view.show_job_schedule),
                ('Job Manager', lambda: view.show_job_manager([inp], noop, noop)),
                ('Edit Job', lambda: view.edit_job(('123', 'Example', 'user', '4', 'R', '00:01:00'))),
                ('Transfer Center', view.show_transfer_center),
                ('Transfer Conflict', lambda: view.confirm_transfer_conflicts_async(
                    conflict_review, lambda *_args: None)),
                ('Message', lambda: view.show_message('Message', 'Keep main visible')),
                ('Error', lambda: view.show_error('Error', 'Keep main visible')),
                ('Confirm', lambda: view.confirm_action_async('Confirm', 'Keep main visible?', noop)),
                ('Input', lambda: view.ask_text_async('Input', 'Value', callback=noop)),
                ('Local Folder', lambda: view.show_local_folder_dialog(profile, noop)),
                ('Server Path', lambda: view.show_server_path('/', lambda *a, **k: [], noop)),
                ('Check ODB', lambda: view.show_odb_check({})),
                ('Extract ODB', lambda: view.show_odb_extract({}, noop)),
                ('ODB Results', lambda: view.show_odb_xy_results({})),
                ('Sync Preview', lambda: view.show_sync_preview([], profile, '/', noop, noop)),
                ('Progress', lambda: _dialog_type('ProgressDialog')(view, 'Progress', threading.Event())),
            )

            def verify_main():
                assert user32.IsWindowVisible(wintypes.HWND(owner)), (name, 'Main hidden')
                assert not user32.IsIconic(wintypes.HWND(owner)), (name, 'Main minimized')
                cloak = wintypes.DWORD()
                ctypes.windll.dwmapi.DwmGetWindowAttribute(
                    wintypes.HWND(owner), 14, ctypes.byref(cloak), ctypes.sizeof(cloak))
                assert not cloak.value, (name, 'Main cloaked')

            def pump(frames=1):
                for _ in range(frames):
                    view.update()
                    verify_main()
                    time.sleep(.015)

            def verify_stack(child):
                assert int(user32.GetForegroundWindow() or 0) == child, (name, 'Dialog lost foreground')
                behind = int(user32.GetWindow(wintypes.HWND(child), 2) or 0)
                while behind and not user32.IsWindowVisible(wintypes.HWND(behind)):
                    behind = int(user32.GetWindow(wintypes.HWND(behind), 2) or 0)
                assert behind == owner, (name, 'Main obscured', behind, owner)

            name = 'startup'
            probe = None
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
                for compact in (False, True):
                    if compact:
                        view.collapse_to_job_monitor()
                        pump(8)
                    for index, (name, factory) in enumerate(specs):
                        probe = NativeOwnerProbe(owner).start()
                        def launch(*args):
                            popup = native._rawWinId(menu.tag)
                            assert int(user32.GetForegroundWindow() or 0) == owner, (name, 'Menu lost owner')
                            dialog = factory()
                            assert dialog is not None, name
                            dialog.show()
                            if popup and user32.IsWindowVisible(wintypes.HWND(popup)):
                                assert not dialog.isVisible(), (name, 'Dialog shown before native menu teardown')
                            opened.append(dialog)

                        if index % 2:
                            action = QAction(name)
                            action.triggered.connect(launch)
                            menu.setActions([action])
                        else:
                            menu.setActions([{'id': 'open', 'action': 'open', 'label': name}])
                            connection = menu.triggered.connect(launch)
                        rect = wintypes.RECT()
                        user32.GetWindowRect(wintypes.HWND(owner), ctypes.byref(rect))
                        assert menu.popupGlobal((rect.left + 80, rect.top + 80), owner=view.primary_window_tag)
                        pump(8)
                        key = next(iter(menu._items))
                        left, top, right, bottom = item_screen_rect(dpg, menu._items[key]['label'])
                        assert user32.SetCursorPos(int((left + right) / 2), int((top + bottom) / 2))
                        pump(2)
                        user32.mouse_event(0x0002, 0, 0, 0, 0)
                        pump(2)
                        user32.mouse_event(0x0004, 0, 0, 0, 0)
                        pump(14)
                        if not index % 2:
                            connection.disconnect()
                        assert opened, (name, 'Menu command was lost')
                        dialog = opened.pop()
                        child = native.winId(dialog.tag)
                        verify_stack(child)
                        point = wintypes.POINT(24, 40)
                        user32.ClientToScreen(wintypes.HWND(child), ctypes.byref(point))
                        assert user32.SetCursorPos(point.x, point.y)
                        user32.mouse_event(0x0002, 0, 0, 0, 0)
                        pump(2)
                        user32.mouse_event(0x0004, 0, 0, 0, 0)
                        pump(4)
                        verify_stack(child)
                        dialog.reject()
                        if name == 'Progress':
                            # Progress Cancel requests worker cancellation; the
                            # worker normally closes its still-visible surface.
                            dialog.destroy()
                        pump(10)
                        assert not dialog.isVisible(), (name, 'Reject did not close dialog')
                        assert int(user32.GetForegroundWindow() or 0) == owner, (name, 'Close lost owner')
                        probe.close()
                        assert not probe.events, (name, 'Transient primary-window flicker risk', probe.events)
                        probe = None
                    print('PASS: {} real dialogs, {} main window, plain/QAction menu launch and '
                          'client clicks; no primary hide/cloak/geometry/frame transitions'.format(
                              len(specs), 'PiP' if compact else 'full'), flush=True)
            finally:
                if probe is not None:
                    probe.close()
                user32.mouse_event(0x0004, 0, 0, 0, 0)
                menu.delete()
                view.request_shutdown()
                view._gui_runtime.destroy()


if __name__ == '__main__':
    main()
