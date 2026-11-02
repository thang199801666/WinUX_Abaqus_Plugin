"""Real list highlight geometry; no physical mouse/keyboard input."""
import os
import ctypes
import sys
import tempfile
import time
from pathlib import Path
from ctypes import wintypes
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import run_winux
run_winux._configure_bundled_dependencies(str(ROOT))
from DearUIQt.backends import dpg
from DearUIQt.gui.placement import item_screen_rect
from WinUx.controllers.callbacks import REQUIRED_CALLBACK_KEYS
from WinUx.dialogs.settings_form import SettingsDialog
from WinUx.view import WinUXView


def main():
    temp_root = Path(os.environ['LOCALAPPDATA']) / 'Temp' / 'opencode'
    with tempfile.TemporaryDirectory(prefix='winux-list-style-', dir=temp_root) as profile:
        with patch.dict(os.environ, {'APPDATA': profile}):
            view = WinUXView({key: lambda *args, **kwargs: None for key in REQUIRED_CALLBACK_KEYS})
            dialog = None

            def pump(count=15):
                for _ in range(count):
                    view.update()
                    time.sleep(.01)

            try:
                view._gui_runtime.show()
                dialog = SettingsDialog(view)
                dialog.show()
                pump(30)
                listing = dialog.navigation_list
                bounds = item_screen_rect(dpg, listing.tag)
                positions = []
                for row in range(listing.count()):
                    listing.setCurrentRow(row)
                    pump(3)
                    item = listing.item(row)
                    native = listing.items[item.key]
                    rect = item_screen_rect(dpg, native)
                    assert abs(rect[0] - bounds[0]) <= 2, (bounds, rect)
                    assert abs(rect[2] - bounds[2]) <= 2, (bounds, rect)
                    assert listing.currentText() == item.text()
                    assert dpg.get_item_configuration(native)['label'] == '  ' + item.text()
                    positions.append(rect)
                for previous, current in zip(positions, positions[1:]):
                    assert abs(current[1] - previous[3]) <= 1, (previous, current)
                listing.setCurrentRow(0)
                pump()
                # Keep the exact caption when updating an existing native row.
                item = listing.item(0)
                native = listing.items[item.key]
                item.setText('General settings')
                pump(3)
                assert listing.items[item.key] == native
                assert listing.currentText() == 'General settings'
                assert dpg.get_item_configuration(native)['label'] == '  General settings'
                item.setText('General')
                pump()
                from PIL import ImageGrab
                from DearUIQt.backends.native_windows import NativeWindowBackend
                hwnd = NativeWindowBackend().winId(dialog.tag)
                assert hwnd
                ctypes.windll.user32.SetWindowPos(
                    wintypes.HWND(hwnd), wintypes.HWND(-1), 0, 0, 0, 0,
                    0x0001 | 0x0002 | 0x0010)
                pump(8)
                rect = wintypes.RECT()
                assert ctypes.windll.user32.GetWindowRect(wintypes.HWND(hwnd), ctypes.byref(rect))
                image = ImageGrab.grab()
                scale = image.width / ctypes.windll.user32.GetSystemMetrics(0)
                image.crop(tuple(round(value * scale) for value in
                                 (rect.left, rect.top, rect.right, rect.bottom))).save(
                                     str(temp_root / 'list_selection_style.png'))
                print('PASS: full-width list highlight, contiguous/equal rows, caption inset, '
                      'unchanged model text and in-place updates', flush=True)
                print('SCREENSHOT', temp_root / 'list_selection_style.png', flush=True)
            finally:
                if dialog is not None:
                    dialog.destroy()
                view.request_shutdown()
                view._gui_runtime.destroy()


if __name__ == '__main__':
    main()
