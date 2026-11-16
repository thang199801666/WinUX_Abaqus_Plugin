"""Real Login/controller close: abaqus python tests/test_login_success_foreground.py.

Only SSH I/O is stubbed; foreground state and the input clock are real.
Add --physical-input to click Connect (do not move the mouse during that run).
"""
import ctypes
import os
import sys
import tempfile
import time
from ctypes import wintypes
from pathlib import Path, PurePosixPath
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import run_winux
run_winux._configure_bundled_dependencies(str(ROOT))
from WinUx.controller import WinUXController
from WinUx.preferences.general import GeneralPreferences
from DearUIQt.backends import dpg
from DearUIQt.backends.native_windows import NativeWindowBackend, _last_input_tick, _window_process_id
from DearUIQt.gui.placement import item_screen_rect


def main():
    temporary = Path(os.environ['LOCALAPPDATA']) / 'Temp' / 'opencode'
    with tempfile.TemporaryDirectory(prefix='winux-login-success-', dir=temporary) as profile:
        GeneralPreferences(root=profile)._store.save({
            'auto_login': False, 'console_visible': True})
        with patch.dict(os.environ, {'APPDATA': profile, 'WINUX_DISABLE_HARD_EXIT': '1',
                                     'WINUX_STANDALONE_PROCESS': '0'}):
            app = WinUXController()
            view = app.view
            view._gui_runtime.show()
            user32 = ctypes.windll.user32
            user32.GetForegroundWindow.restype = wintypes.HWND
            owner = wintypes.HWND(view._find_main_viewport_hwnd())
            def pump(count=1):
                for _ in range(count):
                    view.update()
                    time.sleep(.02)
            try:
                pump(6)
                thread = user32.GetWindowThreadProcessId(user32.GetForegroundWindow(), None)
                current = ctypes.windll.kernel32.GetCurrentThreadId()
                attached = user32.AttachThreadInput(current, thread, True)
                try:
                    user32.BringWindowToTop(owner)
                    user32.SetForegroundWindow(owner)
                finally:
                    if attached:
                        user32.AttachThreadInput(current, thread, False)
                assert int(user32.GetForegroundWindow() or 0) == owner.value
                dialog = view.show_login()
                pump(16)
                # Leave the active InputText edit buffer before setting fixture
                # values; a later native edit callback would restore its draft.
                dialog.focus_editor(dialog.password)
                pump(2)
                dialog.host_combo.setCurrentText('test.invalid')
                dialog.username_combo.setCurrentText('test')
                dialog.set_control_value(dialog.port, '22')
                home = PurePosixPath('/home/test')
                trace = []
                originals = {method: getattr(NativeWindowBackend, method) for method in
                             ('beginOwnerClose', 'hideForOwnerClose', 'repairOwnerAfterHide')}
                def traced(method):
                    def call(backend, *args, **kwargs):
                        result = originals[method](backend, *args, **kwargs)
                        foreground = int(user32.GetForegroundWindow() or 0)
                        title = ctypes.create_unicode_buffer(256)
                        user32.GetWindowTextW(wintypes.HWND(foreground), title, len(title))
                        trace.append((method, repr(result), foreground, title.value,
                                      _window_process_id(user32, foreground), _last_input_tick(user32)))
                        return result
                    return call
                with patch.object(app.server, 'connect', return_value=home), \
                        patch.object(app, '_session_server_factory', return_value=app.server, create=True), \
                        patch.object(app.server, 'list_directory', return_value=[]), \
                        patch.object(app.server, 'set_shell_directory'), \
                        patch.object(dialog, 'save_preferences'), \
                        patch.object(NativeWindowBackend, 'beginOwnerClose', traced('beginOwnerClose')), \
                        patch.object(NativeWindowBackend, 'hideForOwnerClose', traced('hideForOwnerClose')), \
                        patch.object(NativeWindowBackend, 'repairOwnerAfterHide', traced('repairOwnerAfterHide')):
                    if '--physical-input' in sys.argv:
                        pump(2)
                        left, top, right, bottom = item_screen_rect(dpg, dialog.connect_button)
                        if '--debug-input' in sys.argv:
                            native = NativeWindowBackend()
                            child = native.winId(dialog.tag)
                            rect = wintypes.RECT()
                            user32.GetWindowRect(wintypes.HWND(child), ctypes.byref(rect))
                            print('INPUT', child, 'window', (rect.left, rect.top, rect.right, rect.bottom),
                                  'button', (left, top, right, bottom),
                                  'state', dpg.get_item_state(dialog.connect_button), flush=True)
                            from PIL import ImageGrab
                            ImageGrab.grab(bbox=(rect.left, rect.top, rect.right, rect.bottom)).save(
                                temporary / 'winux-login-input.png')
                        assert user32.SetCursorPos(int((left + right) / 2), int((top + bottom) / 2))
                        pump(2)
                        user32.mouse_event(0x0002, 0, 0, 0, 0)
                        pump(2)
                        user32.mouse_event(0x0004, 0, 0, 0, 0)
                    else:
                        dialog.accept()
                    deadline = time.monotonic() + 8
                    while not dialog._destroy_scheduled and time.monotonic() < deadline:
                        pump()
                    assert dialog._destroy_scheduled, 'Successful Login did not close'
                    pump(16)
                    assert user32.IsWindowVisible(owner), 'Successful Login hid WinUx'
                    assert user32.IsWindowEnabled(owner), 'Login left WinUx disabled'
                    assert int(user32.GetForegroundWindow() or 0) == owner.value, (
                        'Successful Login lost foreground', owner.value,
                        int(user32.GetForegroundWindow() or 0), trace)
                # The captured real-world failure was BlockingDialog.destroy
                # from OK, so cover that exact form rather than Login alone.
                message = view.show_message('Focus regression', 'Close this message with OK')
                pump(12)
                if '--physical-input' in sys.argv:
                    left, top, right, bottom = item_screen_rect(dpg, message._default_button)
                    assert user32.SetCursorPos(int((left + right) / 2), int((top + bottom) / 2))
                    pump(2)
                    user32.mouse_event(0x0002, 0, 0, 0, 0)
                    pump(2)
                    user32.mouse_event(0x0004, 0, 0, 0, 0)
                else:
                    message.accept()
                pump(16)
                assert not message.isVisible(), 'Message OK did not close'
                assert int(user32.GetForegroundWindow() or 0) == owner.value, (
                    'Message OK lost main foreground', int(user32.GetForegroundWindow() or 0))
                # Check the shared close path as well, not just Login's form.
                for name, factory in (('Login Cancel', view.show_login),
                                      ('Settings', view.show_settings),
                                      ('Diagnostics', view.show_diagnostics)):
                    closing = factory()
                    pump(12)
                    closing.reject()
                    pump(12)
                    assert int(user32.GetForegroundWindow() or 0) == owner.value, (
                        name, 'Dialog close lost main foreground',
                        int(user32.GetForegroundWindow() or 0))
                    assert user32.IsWindowVisible(owner) and user32.IsWindowEnabled(owner)
                # SC_CLOSE is the native caption X / Alt+F4 path, not reject().
                user32.SendMessageW.argtypes = [wintypes.HWND, wintypes.UINT,
                                                wintypes.WPARAM, wintypes.LPARAM]
                user32.SendMessageW.restype = ctypes.c_ssize_t
                native = NativeWindowBackend()
                for name, factory in (('Login X', view.show_login),
                                      ('Settings X', view.show_settings),
                                      ('Diagnostics X', view.show_diagnostics)):
                    closing = factory()
                    pump(12)
                    child = native.winId(closing.tag)
                    assert child and int(user32.GetForegroundWindow() or 0) == child
                    trace.clear()
                    with patch.object(NativeWindowBackend, 'beginOwnerClose', traced('beginOwnerClose')), \
                            patch.object(NativeWindowBackend, 'hideForOwnerClose', traced('hideForOwnerClose')), \
                            patch.object(NativeWindowBackend, 'repairOwnerAfterHide', traced('repairOwnerAfterHide')):
                        user32.SendMessageW(wintypes.HWND(child), 0x0112, 0xF060, 0)
                        assert getattr(closing, '_native_close_request_pending', False), (
                            name, 'Native X bypassed the QDialog close queue')
                        assert user32.IsWindowVisible(wintypes.HWND(child)), (
                            name, 'Native X hid the HWND before owner handoff')
                        pump(16)
                    assert not closing.isVisible(), (name, 'Native X did not close dialog')
                    assert int(user32.GetForegroundWindow() or 0) == owner.value, (
                        name, 'Native X lost main foreground',
                        int(user32.GetForegroundWindow() or 0), trace)
                    assert user32.IsWindowVisible(owner) and user32.IsWindowEnabled(owner)
                print('PASS: Login Connect/Cancel, Message OK and native X on Login/Settings/Diagnostics', flush=True)
            finally:
                user32.mouse_event(0x0004, 0, 0, 0, 0)
                app._finish_close()
                view._gui_runtime.destroy()


if __name__ == '__main__':
    main()
