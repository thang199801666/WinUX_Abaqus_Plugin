"""Dialog content regression: abaqus python tests/test_dialog_content_render_ui.py."""
import ctypes
import os
import sys
import time
from pathlib import Path
from ctypes import wintypes

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import run_winux
run_winux._configure_bundled_dependencies(str(ROOT))
from WinUx.controllers.callbacks import REQUIRED_CALLBACK_KEYS
from WinUx.view import WinUXView
from DearUIQt.backends import dpg
from WinUx.dialogs.inprocess.transient import BlockingDialog, LoginDialog
from WinUx.dialogs.settings_form import SettingsDialog


def pump(view, frames=12):
    for _ in range(frames):
        view.update()
        time.sleep(.01)


def visible_text(parent):
    result = []
    for children in dpg.get_item_children(parent).values():
        for child in children:
            state = dpg.get_item_state(child)
            if dpg.get_item_info(child)['type'] == 'mvAppItemType::mvText' and state.get('visible'):
                result.append(dpg.get_value(child))
            result.extend(visible_text(child))
    return result

def main():
    view = WinUXView({key: lambda *a, **kw: None for key in REQUIRED_CALLBACK_KEYS})
    try:
        view._gui_runtime.show()
        pump(view)
        owner = wintypes.HWND(view._find_main_viewport_hwnd())
        ctypes.windll.user32.SetWindowPos(owner, wintypes.HWND(-1), 0, 0, 0, 0, 0x0001 | 0x0002 | 0x0010)
        for role in ('info', 'warning', 'error', 'question'):
            message = 'Visible content: {} dialog'.format(role)
            dialog = BlockingDialog(view, 'Dialog render test', message, intent=role)
            pump(view)
            assert dpg.get_item_state(dialog.tag)['visible']
            assert message in visible_text(dialog.content), (role, visible_text(dialog.content))
            dialog.reject()
            pump(view, 4)
            print('PASS: {} message content rendered'.format(role), flush=True)
        # Main-tree updates must wait while a native modal owns presentation.
        dialog = view.show_message('Session update test', 'Content survives session tab updates')
        pump(view)
        snapshot = {'sessions': [{'session_id': 'render-test', 'account_label': 'Render test'}],
                    'active_session_id': 'render-test'}
        assert view.set_session_tabs(snapshot) is False
        pump(view)
        assert view._pending_session_tabs_snapshot == snapshot
        assert 'Content survives session tab updates' in visible_text(dialog.content)
        dialog.reject()
        pump(view, 24)
        assert view._pending_session_tabs_snapshot is None
        print('PASS: session tab update serialized behind native dialog', flush=True)
        for factory in (lambda: LoginDialog(view, lambda *a, **kw: None), lambda: SettingsDialog(view)):
            dialog = factory()
            dialog.show()
            pump(view, 24)
            assert dpg.get_item_state(dialog.tag)['visible']
            assert dpg.get_item_state(dialog.content)['rect_size'][1] > 0
            assert visible_text(dialog.content), type(dialog).__name__
            print('PASS: {} content rendered'.format(type(dialog).__name__), flush=True)
            dialog.reject()
            pump(view, 4)
        dialog = view.show_message('Dialog render test', 'Dialog content is visible')
        pump(view)
        assert 'Dialog content is visible' in visible_text(dialog.content)
        from PIL import ImageGrab
        from DearUIQt.backends.native_windows import NativeWindowBackend
        native = NativeWindowBackend()
        assert dialog._native_window_backend is not None, 'Expected the 1.1.12 DearUIQt dialog host'
        hwnd = native.winId(dialog.tag)
        assert hwnd, 'Dialog has no presentation HWND'
        ctypes.windll.user32.SetWindowPos(wintypes.HWND(hwnd), wintypes.HWND(-1), 0, 0, 0, 0, 0x0001 | 0x0002 | 0x0010)
        pump(view)
        rect = wintypes.RECT()
        ctypes.windll.user32.GetWindowRect(wintypes.HWND(hwnd), ctypes.byref(rect))
        ImageGrab.grab(bbox=(rect.left, rect.top, rect.right, rect.bottom)).save(
            str(Path(os.environ['LOCALAPPDATA']) / 'Temp/opencode/dialog_probe.png'))
        print('PASS: application show_message content rendered', flush=True)
    finally:
        view.request_shutdown()
        view._gui_runtime.destroy()


if __name__ == '__main__':
    main()
