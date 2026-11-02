"""Open Image selection while Plot Digitizer remains open (abaqus python)."""
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
from PIL import Image
from DearUIQt.core import Qt, QEvent, QMouseEvent
from DearUIQt.widgets import QApplication, QRetainedItem
from DearUIQt.gui.placement import item_screen_rect
from DearUIQt.backends import dpg
from WinUx.controllers.callbacks import REQUIRED_CALLBACK_KEYS
from WinUx.plotdigitizer.ui.dialog import PlotDigitizerDialog
from WinUx.view import WinUXView


def main():
    physical = '--pointer' in sys.argv
    user32 = ctypes.windll.user32
    original_cursor = wintypes.POINT()
    user32.GetCursorPos(ctypes.byref(original_cursor))
    temp = Path(os.environ['LOCALAPPDATA']) / 'Temp' / 'opencode'
    with tempfile.TemporaryDirectory(prefix='digitizer-image-selection-', dir=temp) as directory:
        with patch.dict(os.environ, {'APPDATA': directory}):
            images = Path(directory) / 'images'
            images.mkdir()
            for name in ('01.png', '02.png', '03.png'):
                Image.new('RGB', (100, 100), 'white').save(str(images / name))
            view = WinUXView({key: lambda *a, **kw: None for key in REQUIRED_CALLBACK_KEYS})
            view._gui_runtime.show()
            digitizer = PlotDigitizerDialog(view)

            def pump(count=20):
                for _ in range(count):
                    view.update()
                    time.sleep(.01)

            try:
                digitizer.show()
                digitizer._file_directory = str(images)
                pump()
                for _ in range(2):
                    digitizer._choose_open_image()
                    chooser = digitizer._file_dialog.dialog
                    pump(70)
                    if physical:
                        from DearUIQt.backends.native_windows import NativeWindowBackend
                        hwnd = NativeWindowBackend().winId(chooser.tag)
                        user32.GetForegroundWindow.restype = wintypes.HWND
                        thread = user32.GetWindowThreadProcessId(user32.GetForegroundWindow(), None)
                        current = ctypes.windll.kernel32.GetCurrentThreadId()
                        attached = user32.AttachThreadInput(current, thread, True)
                        try:
                            user32.SetForegroundWindow(wintypes.HWND(hwnd))
                        finally:
                            if attached:
                                user32.AttachThreadInput(current, thread, False)
                        user32.SetWindowPos(wintypes.HWND(hwnd), wintypes.HWND(-1),
                                            0, 0, 0, 0, 0x0013)
                        pump(10)
                        assert int(user32.GetForegroundWindow() or 0) == hwnd
                    listing = chooser.listbox
                    assert len(listing._values) == 3
                    changes = []
                    listing.currentChanged.connect(lambda key: changes.append(key))
                    if '--trace' in sys.argv:
                        def trace_selection(key):
                            if len(changes) <= 5:
                                import traceback
                                print('CURRENT', key, flush=True)
                                traceback.print_stack(limit=10)
                        listing.currentChanged.connect(trace_selection)
                    for row in (1, 0, 2, 1):
                        key = listing._values[row].key
                        rect = QRetainedItem(listing.items[key]).globalGeometry(clipped=True)
                        point = (rect.x() + 30, rect.y() + min(6, rect.height() / 2))
                        if physical:
                            screen = item_screen_rect(dpg, listing.items[key])
                            user32.SetCursorPos(int(screen[0] + 30), int(screen[1] + 6))
                            pump(4)
                            # Focus/reflow may move a reused native surface.
                            # Hit-test its final geometry, not the old frame.
                            screen = item_screen_rect(dpg, listing.items[key])
                            user32.SetCursorPos(int(screen[0] + 30), int(screen[1] + 6))
                            assert int(user32.GetForegroundWindow() or 0) == hwnd
                            user32.mouse_event(0x0002, 0, 0, 0, 0)
                            pump(16 if row == 2 else 3)
                            user32.mouse_event(0x0004, 0, 0, 0, 0)
                        else:
                            assert chooser.event(QMouseEvent(QEvent.MouseButtonPress, point,
                                button=Qt.LeftButton, buttons=Qt.LeftButton)), (
                                    'Open Image did not route the row press', row,
                                    QApplication.instance().activeModalWidget(), rect)
                            chooser.event(QMouseEvent(QEvent.MouseButtonRelease, point,
                                button=Qt.LeftButton, buttons=Qt.NoButton))
                        pump(35)
                        assert listing.currentKey() == key, (row, listing.currentKey(), key, changes)
                        assert listing.selectedKeys() == [key], (row, listing.selectedKeys(), changes)
                        assert chooser._folder_edit_control.text() == Path(key).name
                        first = listing._values[0].key
                        listing._clicked(listing.items[first], True, first)
                        pump(4)
                        assert listing.currentKey() == key, ('stale first-row callback', changes)
                    chooser._select_folder()
                    pump(60)
                    assert digitizer.engine.image_path == str(images / '02.png')
                print('PASS: Plot Digitizer Open Image selects rows 2/3 without reverting; repeated picker and image acceptance')
            finally:
                if physical:
                    user32.mouse_event(0x0004, 0, 0, 0, 0)
                    user32.SetCursorPos(original_cursor.x, original_cursor.y)
                if digitizer._file_dialog is not None:
                    digitizer._file_dialog.close()
                digitizer.destroy()
                view.request_shutdown()
                view._gui_runtime.destroy()


if __name__ == '__main__':
    main()
