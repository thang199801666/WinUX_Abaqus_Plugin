"""Settings UI regression: abaqus python tests/test_settings_layout.py."""
import ctypes
import os
import sys
import time
from ctypes import wintypes
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import run_winux
run_winux._configure_bundled_dependencies(str(ROOT))
from DearUIQt.backends import dpg
from DearUIQt.gui.placement import item_screen_rect
from DearUIQt.backends.native_windows import NativeWindowBackend
from WinUx.controllers.callbacks import REQUIRED_CALLBACK_KEYS
from WinUx.dialogs.settings_form import SettingsDialog
from WinUx.view import WinUXView


def main():
    view = WinUXView({key: lambda *a, **k: None for key in REQUIRED_CALLBACK_KEYS})
    view._gui_runtime.show()
    def pump(frames=24):
        for _ in range(frames):
            view.update()
            time.sleep(.01)
    pump()
    dialog = SettingsDialog(view)
    dialog._ensure_page('abaqus', defer_io=False)
    dialog._show_page('abaqus')
    dialog.show()
    pump(36)
    native = NativeWindowBackend()
    hwnd = native.winId(dialog.tag)
    ctypes.windll.user32.SetWindowPos(
        wintypes.HWND(hwnd), wintypes.HWND(-1), 0, 0, 0, 0,
        0x0001 | 0x0002 | 0x0010)
    ctypes.windll.user32.SetForegroundWindow(wintypes.HWND(hwnd))
    pump(8)
    editor = item_screen_rect(dpg, dialog.version_editor)
    default = item_screen_rect(dpg, dialog.default_command)
    assert abs(editor[0] - default[0]) <= 1, (editor, default)
    assert abs(editor[2] - default[2]) <= 1, (editor, default)
    for tag in dialog._version_action_buttons.values():
        button = item_screen_rect(dpg, tag)
        assert editor[0] <= button[0] < button[2] <= editor[2], (button, editor)
    from PIL import ImageGrab
    rect = wintypes.RECT()
    ctypes.windll.user32.GetWindowRect(wintypes.HWND(hwnd), ctypes.byref(rect))
    screenshot = ImageGrab.grab()
    scale = screenshot.width / ctypes.windll.user32.GetSystemMetrics(0)
    target = Path(os.environ['LOCALAPPDATA']) / 'Temp' / 'opencode' / 'settings_layout.png'
    screenshot.crop(tuple(round(v * scale) for v in
                          (rect.left, rect.top, rect.right, rect.bottom))).save(str(target))
    print('SCREENSHOT', target, flush=True)
    dialog.resize(660, 400)
    pump(16)
    editor_small = item_screen_rect(dpg, dialog.version_editor)
    for tag in dialog._version_action_buttons.values():
        assert item_screen_rect(dpg, tag)[2] <= editor_small[2]
    dialog.resize(720, 440)
    pump(8)
    original = list(dialog._versions)
    dialog.set_control_value(dialog.version_editor, 'abq_test_layout')
    dialog._edit_version('add')
    assert 'abq_test_layout' in dialog._versions
    dialog.set_control_value(dialog.version_editor, 'abq_test_renamed')
    dialog._edit_version('update')
    assert 'abq_test_renamed' in dialog._versions
    dialog._edit_version('delete')
    assert dialog._versions == original
    # Visit every lazy page, including the long scrollable pages.
    for page in dialog.PAGE_ORDER:
        dialog._ensure_page(page, defer_io=False)
        dialog._show_page(page)
        pump(8)
        assert dialog.page_stack.currentWidget() is dialog._page_widgets[page]
    dialog._show_page('updates')
    dialog._finish_update_check({
        'local_version': '1.1.5', 'server_version': '1.1.5',
        'source_label': 'GitHub Releases: thang199801666/WinUX_Abaqus_Plugin (stable)',
    })
    assert dialog.control_value(dialog.status) == 'WinUx is up to date.'
    assert 'GitHub Releases' in dialog.control_value(dialog.update_check_status)
    for width, height in ((660, 400), (720, 440), (900, 580)):
        dialog.resize(width, height)
        dialog._set_status('Settings could not be saved. Check the configuration path and permissions, then try again.', True)
        pump(20)
        status = item_screen_rect(dpg, dialog.status)
        left = item_screen_rect(dpg, dialog.set_default_button)
        save = item_screen_rect(dpg, dialog._default_button)
        assert status[3] <= left[1] - 2, (status, left)
        assert abs(left[1] - save[1]) <= 1, (left, save)
        assert status[0] >= left[0] - 1, (status, left)
        page_width = dpg.get_item_rect_size(dialog.page_scroll.tag)[0]
        assert dpg.get_item_configuration(dialog.update_provider_note)['wrap'] <= page_width - 36
    dialog._set_status('WinUx is up to date.')
    pump(12)
    ctypes.windll.user32.GetWindowRect(wintypes.HWND(hwnd), ctypes.byref(rect))
    screenshot = ImageGrab.grab()
    target = target.with_name('settings_updates_layout.png')
    screenshot.crop(tuple(round(v * scale) for v in
                          (rect.left, rect.top, rect.right, rect.bottom))).save(str(target))
    print('SCREENSHOT', target, flush=True)
    dialog._set_status('')
    pump(8)
    assert not dpg.is_item_shown(dialog._footer_status_host)
    dialog.destroy()  # No Save: the test must not alter persisted settings.
    pump(8)
    view.request_shutdown()
    view._gui_runtime.destroy()
    print('PASS: compact settings, aligned forms/actions, all pages, command editing', flush=True)


if __name__ == '__main__':
    main()
