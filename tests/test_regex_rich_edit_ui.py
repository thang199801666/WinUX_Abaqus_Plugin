"""Real Rich Edit selection/undo/color/lifetime contract; no physical input."""
import ctypes
from ctypes import wintypes
import os
from pathlib import Path
import sys
import tempfile
import time
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import run_winux
run_winux._configure_bundled_dependencies(str(ROOT))
from DearUIQt.dialogs.qt_dialog import QtDialog
from WinUx.controllers.callbacks import REQUIRED_CALLBACK_KEYS
from WinUx.ui.components.regex_rich_edit import RegexRichEdit, _Range, _CharFormat, _rgb, _com_method
from WinUx.view import WinUXView


def main():
    temp = Path(os.environ['LOCALAPPDATA']) / 'Temp' / 'opencode'
    with tempfile.TemporaryDirectory(prefix='regex-rich-edit-', dir=temp) as profile, \
            patch.dict(os.environ, {'APPDATA': profile}):
        view = WinUXView({key: lambda *a, **k: None for key in REQUIRED_CALLBACK_KEYS})
        dialog = None
        field = None
        try:
            view._gui_runtime.show()
            dialog = QtDialog(view, 'Inline regex editor', 700, 450)
            field = dialog.own_widget(RegexRichEdit('U1\nRF3 🙂', parent=dialog.contentWidget(),
                owner_handle=lambda: dialog._native_window_backend.winId(dialog.tag),
                after=view.after, multiline=True, height=240))
            dialog.show()

            def pump(count=8):
                for _ in range(count):
                    view.update()
                    field.sync_native()
                    time.sleep(.01)

            pump(25)
            assert field.hwnd and field._document.value
            assert field.text() == 'U1\nRF3 🙂'
            selection = _Range(1, 5)
            field._send(0x0437, 0, ctypes.byref(selection))
            native_selection = ctypes.c_void_p()
            _com_method(field._document, 8, ctypes.c_long, ctypes.c_void_p)(
                field._document, ctypes.byref(native_selection))
            _com_method(native_selection, 59, ctypes.c_long, ctypes.c_long)(native_selection, 1)
            assert field.set_colors([(0, 2, (30, 40, 50), (170, 220, 255))])
            actual = _Range()
            field._send(0x0434, 0, ctypes.byref(actual))
            assert (actual.start, actual.end) == (1, 5), (actual.start, actual.end)
            flags = ctypes.c_long()
            _com_method(native_selection, 58, ctypes.c_long, ctypes.c_void_p)(native_selection, ctypes.byref(flags))
            assert flags.value & 1, 'Recoloring reversed the active end of the selection'
            _com_method(native_selection, 2, wintypes.ULONG)(native_selection)
            field._send(0x0437, 0, ctypes.byref(_Range(0, 1)))
            fmt = _CharFormat()
            fmt.size = ctypes.sizeof(fmt)
            field._send(0x043A, 1, ctypes.byref(fmt))
            assert fmt.foreground == _rgb((30, 40, 50)), fmt.foreground
            assert fmt.background == _rgb((170, 220, 255)), fmt.background

            # Formatting must not become an undo step or wipe text-edit history.
            field._send(0x0437, 0, ctypes.byref(_Range(-1, -1)))
            inserted = ctypes.create_unicode_buffer('X')
            field._send(0x00C2, 1, inserted)  # EM_REPLACESEL, undoable edit
            assert field.text().endswith('X'), field.text()
            before = field.text()
            field.set_colors([(0, 2, (0, 90, 150), (200, 235, 255))])
            assert field.text() == before
            assert field._send(0x00C6), 'Formatting cleared the undo queue'  # EM_CANUNDO
            field._send(0x00C7)  # EM_UNDO
            assert field.text() == 'U1\nRF3 🙂', field.text()

            if '--screenshot' in sys.argv:
                from PIL import ImageGrab
                hwnd = dialog._native_window_backend.winId(dialog.tag)
                ctypes.windll.user32.SetWindowPos(wintypes.HWND(hwnd), wintypes.HWND(-1), 0, 0, 0, 0, 0x0013)
                pump()
                rect = wintypes.RECT()
                ctypes.windll.user32.GetWindowRect(wintypes.HWND(hwnd), ctypes.byref(rect))
                path = temp / 'regex-rich-edit.png'
                image = ImageGrab.grab()
                scale = image.width / ctypes.windll.user32.GetSystemMetrics(0)
                image.crop(tuple(round(value * scale) for value in
                    (rect.left, rect.top, rect.right, rect.bottom))).save(path)
                print('SCREENSHOT', path, flush=True)
            handle = field.hwnd
            field.close_native()
            assert not ctypes.windll.user32.IsWindow(wintypes.HWND(handle))
            print('PASS: native inline colors, multiline/Unicode, preserved selection, '
                  'text undo through recoloring and native child cleanup', flush=True)
        finally:
            if field is not None:
                field.close_native()
            if dialog is not None:
                dialog.destroy()
            view.request_shutdown()
            view._gui_runtime.destroy()


if __name__ == '__main__':
    main()
