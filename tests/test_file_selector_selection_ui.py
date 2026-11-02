"""Rendered chooser stability; add --pointer to exercise real Windows clicks."""
import os
from pathlib import Path
import sys
import tempfile
import time
import ctypes
from ctypes import wintypes
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import run_winux
run_winux._configure_bundled_dependencies(str(ROOT))
from WinUx.controllers.callbacks import REQUIRED_CALLBACK_KEYS
from WinUx.view import WinUXView
from WinUx.dialogs.local_folder_form import LocalFolderDialog
from WinUx.dialogs.local_file_form import LocalFileDialog
from DearUIQt.backends import dpg


def main():
    temp = Path(os.environ['LOCALAPPDATA']) / 'Temp' / 'opencode'
    with tempfile.TemporaryDirectory(dir=temp) as directory:
        original_cursor = wintypes.POINT()
        ctypes.windll.user32.GetCursorPos(ctypes.byref(original_cursor))
        root = Path(directory)
        for i in range(30):
            (root / ('folder_%02d.inp' % i)).mkdir()
        (root / 'model.inp').write_text('test')
        with patch.dict(os.environ, {'APPDATA': directory}):
            view = WinUXView({key: lambda *a, **k: None for key in REQUIRED_CALLBACK_KEYS})
            dialog = None
            def pump(count):
                for _ in range(count):
                    view.update()
                    time.sleep(.01)
            try:
                view._gui_runtime.show()
                pump(20)
                if '--compact' in sys.argv:
                    view.collapse_to_job_monitor()
                    pump(20)
                    view.restore_from_job_monitor()
                    pump(30)
                for cls in (LocalFolderDialog, LocalFileDialog) * 2:
                    dialog = cls(view, directory, lambda value: None)
                    dialog.show()
                    pump(50)
                    listing = dialog.listbox
                    # All text cells must share one baseline; the bitmap uses
                    # the font-bearing optical correction, not a taller row.
                    for item in listing._values[:10]:
                        native = listing.items[item.key]
                        assert dpg.get_item_rect_size(native)[0] > 32, (item.key, 'collapsed filename')
                        assert dpg.get_item_configuration(native)['label'] == item.text, (
                            item.key, dpg.get_item_configuration(native)['label'])
                        name_y = dpg.get_item_rect_min(listing.items[item.key])[1]
                        for cell in listing.detail_texts[item.key]:
                            assert dpg.get_item_rect_min(cell)[1] == name_y
                    pitches = [dpg.get_item_rect_min(listing.items[item.key])[1]
                               for item in listing._values[:10]]
                    assert len(set(b - a for a, b in zip(pitches, pitches[1:]))) == 1
                    if '--alignment' in sys.argv:
                        first = listing._values[0].key
                        icon = dpg.get_item_parent(listing.icons[first])
                        print('GEOMETRY', cls.__name__,
                              [(dpg.get_item_type(tag), dpg.get_item_rect_min(tag), dpg.get_item_rect_size(tag))
                               for tag in (icon, listing.items[first], *listing.detail_texts[first])], flush=True)
                        from PIL import ImageGrab
                        from DearUIQt.gui.placement import item_screen_rect
                        rect = item_screen_rect(dpg, listing.tag)
                        ImageGrab.grab().crop(tuple(map(int, rect))).save(str(temp / ('selector_alignment_' + cls.__name__ + '.png')))
                    key = listing._values[7].key
                    changes = []
                    listing.currentChanged.connect(lambda value: changes.append(value))
                    generation = listing._row_generation
                    if '--pointer' in sys.argv:
                        from DearUIQt.backends.native_windows import NativeWindowBackend
                        hwnd = NativeWindowBackend().winId(dialog.tag)
                        user32 = ctypes.windll.user32
                        user32.GetForegroundWindow.restype = wintypes.HWND
                        thread = user32.GetWindowThreadProcessId(user32.GetForegroundWindow(), None)
                        current_thread = ctypes.windll.kernel32.GetCurrentThreadId()
                        attached = user32.AttachThreadInput(current_thread, thread, True)
                        try:
                            user32.SetForegroundWindow(wintypes.HWND(hwnd))
                        finally:
                            if attached:
                                user32.AttachThreadInput(current_thread, thread, False)
                        pump(8)
                        assert int(user32.GetForegroundWindow() or 0) == hwnd
                        from DearUIQt.gui.placement import item_screen_rect
                        for row in (0, 1, 7, 1, 0, 8):
                            row_key = listing._values[row].key
                            rect = item_screen_rect(dpg, listing.items[row_key])
                            user32.SetCursorPos(int(rect[0] + 30), int(rect[1] + 6))
                            pump(4)
                            user32.mouse_event(0x0002, 0, 0, 0, 0)
                            pump(3)
                            user32.mouse_event(0x0004, 0, 0, 0, 0)
                            pump(3)
                            assert listing.current == row_key, (cls.__name__, row, listing.current, changes)
                            for _ in range(30):
                                pump(1)
                                assert listing.selected == {row_key}, (cls.__name__, row, listing.selected, changes)
                        print('PASS', cls.__name__, 'first rows and alternating selection without flicker', flush=True)
                        rect = item_screen_rect(dpg, listing.items[key])
                        ctypes.windll.user32.SetCursorPos(int(rect[0] + 30), int(rect[1] + 6))
                        pump(4)
                        ctypes.windll.user32.mouse_event(0x0002, 0, 0, 0, 0)
                        pump(4)
                        ctypes.windll.user32.mouse_event(0x0004, 0, 0, 0, 0)
                        pump(4)
                    else:
                        listing._qt_bridge_click = None
                        assert listing._route_pointer_key(key)
                    assert listing.current == key
                    pump(60)
                    assert listing.current == key, (cls.__name__, changes)
                    assert listing.selected == {key}, (cls.__name__, listing.selected)
                    assert listing._row_generation == generation, (generation, listing._row_generation)
                    listing.navigate(dpg.mvKey_Down)
                    next_key = listing._values[8].key
                    pump(10)
                    assert listing.current == next_key
                    assert listing.selected == {next_key}
                    if '--pointer' in sys.argv:
                        # A real double-click must navigate in both Open Folder
                        # and Open File, not raise in the shared row callback.
                        pump(60)
                        rect = item_screen_rect(dpg, listing.items[next_key])
                        ctypes.windll.user32.SetCursorPos(int(rect[0] + 30), int(rect[1] + 6))
                        pump(4)
                        for _ in range(2):
                            ctypes.windll.user32.mouse_event(0x0002, 0, 0, 0, 0)
                            pump(2)
                            ctypes.windll.user32.mouse_event(0x0004, 0, 0, 0, 0)
                            pump(2)
                        pump(50)
                        assert os.path.normcase(dialog._current_path) == os.path.normcase(next_key), (
                            cls.__name__, dialog._current_path, next_key)
                        print('PASS', cls.__name__, 'physical folder double-click navigation', flush=True)
                    print('PASS', cls.__name__, 'stable selection', flush=True)
                    dialog.destroy()
                    dialog = None
                    pump(5)
            finally:
                if '--pointer' in sys.argv:
                    ctypes.windll.user32.mouse_event(0x0004, 0, 0, 0, 0)
                    ctypes.windll.user32.SetCursorPos(original_cursor.x, original_cursor.y)
                if dialog is not None:
                    dialog.destroy()
                view.request_shutdown()
                view._gui_runtime.destroy()


if __name__ == '__main__':
    main()
