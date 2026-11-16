"""Focused Delete regression: abaqus python tests/test_digitizer_delete_key_ui.py --native."""
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
from PIL import Image
from DearUIQt.core import Qt, QEvent, QKeyEvent
from DearUIQt.widgets import QApplication
from WinUx.controllers.callbacks import REQUIRED_CALLBACK_KEYS
from WinUx.plotdigitizer.ui.dialog import PlotDigitizerDialog
from WinUx.view import WinUXView


def main():
    native = '--native' in sys.argv
    original_cursor = wintypes.POINT()
    ctypes.windll.user32.GetCursorPos(ctypes.byref(original_cursor))
    root = Path(os.environ['LOCALAPPDATA']) / 'Temp' / 'opencode'
    with tempfile.TemporaryDirectory(prefix='digitizer-delete-', dir=root) as profile, \
            patch.dict(os.environ, {'APPDATA': profile}):
        view = WinUXView({key: lambda *a, **kw: None for key in REQUIRED_CALLBACK_KEYS})
        view._gui_runtime.show()
        dialog = PlotDigitizerDialog(view)

        def pump(count=15):
            for _ in range(count):
                view.update()
                time.sleep(.01)

        def delete(target=None):
            if native:
                user32 = ctypes.windll.user32
                target = target or dialog
                hwnd = target._native_window_backend.winId(target.tag)
                user32.GetForegroundWindow.restype = wintypes.HWND
                thread = user32.GetWindowThreadProcessId(user32.GetForegroundWindow(), None)
                current = ctypes.windll.kernel32.GetCurrentThreadId()
                attached = user32.AttachThreadInput(current, thread, True)
                try:
                    user32.SetForegroundWindow(wintypes.HWND(hwnd))
                finally:
                    if attached:
                        user32.AttachThreadInput(current, thread, False)
                user32.SetWindowPos(wintypes.HWND(hwnd), wintypes.HWND(-1), 0, 0, 0, 0, 0x0013)
                pump(8)
                if int(user32.GetForegroundWindow() or 0) != hwnd:
                    # Windows may reject activation without a user gesture.
                    # Activate only this test window through its caption, then
                    # restore the intended logical editor/table/canvas focus.
                    focused = QApplication.instance().focusObject()
                    bounds = wintypes.RECT()
                    user32.GetWindowRect(wintypes.HWND(hwnd), ctypes.byref(bounds))
                    user32.SetCursorPos((bounds.left + bounds.right) // 2, bounds.top + 12)
                    user32.mouse_event(0x0002, 0, 0, 0, 0)
                    user32.mouse_event(0x0004, 0, 0, 0, 0)
                    pump(5)
                    if focused is not None and callable(getattr(focused, 'setFocus', None)):
                        focused.setFocus()
                        QApplication.instance().setFocusObject(focused)
                assert int(user32.GetForegroundWindow() or 0) == hwnd
                user32.keybd_event(0x2E, 0, 0, 0)
                pump(15)  # Held key must still delete just the selection once.
                user32.keybd_event(0x2E, 0, 0x0002, 0)
                pump()
            else:
                hwnd = dialog._native_window_backend.winId(dialog.tag)
                # Simulate foreground only; keep real retained focus, key
                # routing, editor guards and the deletion implementation.
                with patch('WinUx.ui.native.dialog_focus.foreground_hwnd', return_value=hwnd):
                    QApplication.instance().dispatchKeyEvent(QKeyEvent(QEvent.KeyPress, Qt.Key_Delete))
                pump()

        try:
            dialog.show()
            dialog.engine.apply_image(Image.new('RGB', (240, 180), 'white'), 'delete.png')
            for point in ((30, 35), (100, 80), (170, 110)):
                dialog.engine.add_manual_point(*point)
            dialog.engine.active_dataset.extracted_pixels = [(60, 60), (180, 140)]
            pump(30)
            dialog._edit_mode_toggled(True)
            with patch.object(dialog, '_mouse_in_canvas', return_value=True), \
                    patch.object(dialog, '_canvas_to_image', return_value=(30, 35)):
                dialog._mouse_left()
                dialog._mouse_left_up()
            pump()
            assert dialog._selected_point == ('manual', 0)
            delete()
            assert len(dialog.engine.active_dataset.manual_points) == 2, 'Delete did not remove the clicked curve point'
            dialog.engine.undo()
            pump()

            dialog._set_edit_enabled(False)
            dialog._show_tool('data')
            dialog.result_grid.setCurrentKey('manual:0', select=True)
            pump()
            dialog.control_wrapper(dialog.point_x).setFocus()
            pump()
            before = len(dialog.engine.active_dataset.manual_points)
            delete()
            assert len(dialog.engine.active_dataset.manual_points) == before, 'Delete in a text editor removed document points'
            dialog.result_grid.setCurrentKey('manual:0', select=True)
            dialog.result_grid.setFocus()
            pump()
            delete()
            assert len(dialog.engine.active_dataset.manual_points) == before - 1, 'View Data Delete failed with Edit off'
            dialog.engine.undo()
            pump()

            dialog._show_tool('extract')
            dialog._edit_mode_toggled(True)
            dialog._select_canvas_points({'manual:0'})
            before = len(dialog.engine.active_dataset.manual_points)
            dialog._request_close_confirmation()
            pump(40)
            prompt = dialog._close_confirmation_dialog
            assert prompt is not None
            delete(prompt)
            assert len(dialog.engine.active_dataset.manual_points) == before, 'Modal Delete changed background points'
            prompt.finish(False)
            pump()
            dialog._select_canvas_points({'manual:0', 'manual:1', 'auto:0'})
            delete()
            assert len(dialog.engine.active_dataset.manual_points) == 1, 'Delete did not remove multiple manual points'
            assert len(dialog.engine.active_dataset.extracted_pixels) == 1, 'Delete did not remove selected auto points'
            dialog.engine.undo()
            pump()

            dialog._set_edit_enabled(False)
            dialog._show_tool('axes')
            for axis in ('x', 'y'):
                for pixel, value in ((20, 0), (100, 5), (160, 10)):
                    dialog.engine.add_calibration_point(axis, pixel if axis == 'x' else 20,
                                                       160 if axis == 'x' else pixel, value)
            pump()
            dialog.set_control_value(dialog.calibration_axis, 'X')
            dialog._calibration_axis_changed()
            dialog.calibration_grid.setCurrentKey('x:1', select=True)
            pump()
            delete()
            assert len(dialog.engine.calibration.points_x) == 2, 'Delete did not remove the selected calibration point'
            assert len(dialog.engine.calibration.points_y) == 3, 'Delete changed the other calibration axis'
            assert dialog._selected_calibration_point is None, 'Calibration Delete left a phantom next selection'
            dialog.engine.undo()
            pump()
            assert len(dialog.engine.calibration.points_x) == 3
            with patch.object(dialog, '_mouse_in_canvas', return_value=True), \
                    patch.object(dialog, '_canvas_to_image', return_value=(20, 100)):
                dialog._mouse_left()
                dialog._mouse_left_up()
            pump()
            assert dialog._selected_calibration_point == ('y', 1)
            delete()
            assert len(dialog.engine.calibration.points_y) == 2, 'Delete failed after clicking a calibration marker'
            assert len(dialog.engine.calibration.points_x) == 3
            print('PASS: Delete for clicked/multiple curve points, View Data and calibration; Undo, held-key, text-editor and modal safety')
        finally:
            if native:
                ctypes.windll.user32.keybd_event(0x2E, 0, 0x0002, 0)
                ctypes.windll.user32.SetCursorPos(original_cursor.x, original_cursor.y)
            dialog.destroy()
            view.request_shutdown()
            view._gui_runtime.destroy()


if __name__ == '__main__':
    main()
