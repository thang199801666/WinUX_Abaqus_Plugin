"""Physical Reference Chart worksheet: abaqus python tests/test_reference_worksheet.py."""
import copy
import faulthandler
import ctypes
import os
import sys
import tempfile
import time
from ctypes import wintypes
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import run_winux
run_winux._configure_bundled_dependencies(str(ROOT))

from DearUIQt.backends import dpg
from DearUIQt.gui import QClipboard
from DearUIQt.gui.placement import item_screen_rect
from WinUx.controllers.callbacks import REQUIRED_CALLBACK_KEYS
from WinUx.dialogs.native_reference_tools import ReferenceChartDialog
from WinUx.services.reference_charts import validate_reference
from WinUx.view import WinUXView


def main():
    faulthandler.enable()
    user32 = ctypes.windll.user32
    cursor = wintypes.POINT()
    assert user32.GetCursorPos(ctypes.byref(cursor)), 'Physical input desktop unavailable'
    user32.GetForegroundWindow.restype = wintypes.HWND
    temp_root = Path(os.environ['LOCALAPPDATA']) / 'Temp' / 'opencode'
    with tempfile.TemporaryDirectory(prefix='winux-worksheet-', dir=temp_root) as profile:
        with patch.dict(os.environ, {'APPDATA': profile}):
            view = WinUXView({key: lambda *a, **k: None for key in REQUIRED_CALLBACK_KEYS})
            view._gui_runtime.show()
            clipboard = QClipboard()
            old_clipboard = None
            source = [validate_reference({'name': name, 'points': [[i, i * 10] for i in range(10)]})
                      for name in ('First', 'Second')]
            original = copy.deepcopy(source)
            results = []
            dialog = ReferenceChartDialog(view, source, results.append)
            dialog.show()
            sheet = dialog.data_table

            def pump(frames=8):
                for _ in range(frames):
                    view.update()
                    time.sleep(.02)

            def cell(row, column):
                tag = sheet._table_widget.nativeItem(row, column + 1)
                if sheet._active_position == (row, column):
                    tag = sheet._active_editor.tag
                left, top, right, bottom = item_screen_rect(dpg, tag)
                return int(left + 4), int((top + bottom) / 2)

            def click(point):
                assert user32.SetCursorPos(*point)
                pump(3)
                user32.mouse_event(0x0002, 0, 0, 0, 0)
                pump(2)
                user32.mouse_event(0x0004, 0, 0, 0, 0)
                pump()

            def key(code, ctrl=False, shift=False):
                if ctrl:
                    user32.keybd_event(0x11, 0, 0, 0)
                if shift:
                    user32.keybd_event(0xa0, 0x2a, 0, 0)
                    pump(2)
                scan = user32.MapVirtualKeyW(code, 0)
                flags = 1 if code in (0x25, 0x26, 0x27, 0x28, 0x2e, 0x24, 0x23) else 0
                user32.keybd_event(code, scan, flags, 0)
                pump(5)
                user32.keybd_event(code, scan, flags | 2, 0)
                if shift:
                    user32.keybd_event(0xa0, 0x2a, 2, 0)
                if ctrl:
                    user32.keybd_event(0x11, 0, 2, 0)
                pump()

            try:
                pump(24)
                old_clipboard = clipboard.text()
                assert clipboard.setText('μ\t1.25\n曲線\t2')
                assert clipboard.text() == 'μ\t1.25\n曲線\t2'
                owner = dialog._native_window_backend.winId(dialog.tag)
                tid = user32.GetWindowThreadProcessId(user32.GetForegroundWindow(), None)
                current = ctypes.windll.kernel32.GetCurrentThreadId()
                attached = user32.AttachThreadInput(current, tid, True)
                try:
                    user32.SetForegroundWindow(wintypes.HWND(owner))
                finally:
                    if attached:
                        user32.AttachThreadInput(current, tid, False)
                start, end = cell(1, 0), cell(3, 1)
                assert user32.SetCursorPos(*start)
                pump(3)
                observed = wintypes.POINT()
                user32.GetCursorPos(ctypes.byref(observed))
                assert sheet._cell_at_pointer() == (1, 0), (
                    'Drag origin hit test', sheet._cell_at_pointer(), start,
                    (observed.x, observed.y), sheet._pointer_position(),
                    user32.GetForegroundWindow(), owner, sheet._frame.isVisible())
                user32.mouse_event(0x0002, 0, 0, 0, 0)
                pump(2)
                for step in range(1, 16):
                    user32.SetCursorPos(int(start[0] + (end[0] - start[0]) * step / 15),
                                        int(start[1] + (end[1] - start[1]) * step / 15))
                    pump(2)
                user32.mouse_event(0x0004, 0, 0, 0, 0)
                pump()
                assert sheet.selected_range == (1, 0, 3, 1), ('Drag range', sheet.selected_range)
                key(0x43, ctrl=True)
                expected = '\n'.join('\t'.join(sheet.model.row_text(row)) for row in range(1, 4))
                assert clipboard.text() == expected, ('Ctrl+C', clipboard.text(), expected)
                key(0x2e)
                assert all(sheet.model.row_text(row) == ['', ''] for row in range(1, 4))

                click(cell(5, 0))
                clipboard.setText('12\t120\n13\t130')
                key(0x56, ctrl=True)
                assert sheet.model.row_text(5) == ['12', '120'], sheet.model.row_text(5)
                assert sheet.model.row_text(6) == ['13', '130']
                assert sheet.selected_range == (5, 0, 6, 1)
                click(cell(5, 1))
                key(0x28, shift=True)
                assert sheet.selected_range == (5, 1, 6, 1), ('Shift+Down', sheet.selected_range)
                key(0x58, ctrl=True)
                assert clipboard.text() == '120\n130'
                assert sheet.model.cell_text(5, 0) == '12'
                assert sheet.model.cell_text(5, 1) == ''
                key(0x56, ctrl=True)
                assert sheet.model.cell_text(6, 1) == '130'
                click(cell(7, 1))
                key(0x09)
                assert sheet.current_cell == (8, 0), ('Tab navigation', sheet.current_cell)
                key(0x41, ctrl=True)
                assert sheet.selected_range == (0, 0, 9, 1), ('Ctrl+A', sheet.selected_range)
                click(cell(8, 0))
                key(0x71)  # F2 starts the transient cell editor.
                assert sheet._active_position == (8, 0), 'F2 did not open cell editor'
                key(0x43, ctrl=True)
                assert clipboard.text() == '8', ('Native editor copy', clipboard.text())
                clipboard.setText('88')
                key(0x56, ctrl=True)
                sheet._read_inputs()
                assert sheet.model.cell_text(8, 0) == '88', 'Native editor paste'
                assert dialog._save_series()
                assert dialog._series[0]['points'][1] == [4.0, 40.0]
                assert source == original, 'Draft editing mutated the caller library'

                left, top, right, bottom = item_screen_rect(dpg, dialog.delete_series_button)
                click((int((left + right) / 2), int((top + bottom) / 2)))
                assert [item['name'] for item in dialog._series] == ['Second'], 'Delete series button'
                dialog._save()
                pump()
                assert len(results[-1]) == 1 and results[-1][0]['name'] == 'Second'
                dialog.begin_session(source, results.append)
                dialog.show()
                pump()
                dialog._remove_selected()
                dialog.finish(None)
                assert results[-1] is None and source == original, 'Cancel must not persist deletion'
                many = [validate_reference({'name': 'Series {}'.format(i), 'points': [[0, 1], [1, 2]]})
                        for i in range(6)]
                dialog.begin_session(many, results.append)
                dialog.show()
                pump(20)
                dialog.focus_control(dialog.delete_series_button)
                pump(3)
                key(0x20)
                assert len(dialog._series) == 5, 'Space must activate the focused Delete button once'
                for remaining in range(4, -1, -1):
                    left, top, right, bottom = item_screen_rect(dpg, dialog.delete_series_button)
                    click((int((left + right) / 2), int((top + bottom) / 2)))
                    assert len(dialog._series) == remaining, ('One click must delete exactly one series', remaining, len(dialog._series))
                assert not dpg.get_item_configuration(dialog.delete_series_button)['enabled']
                dialog.finish(None)
                print('PASS: physical cell drag, Unicode clipboard, Ctrl+A/C/V/X, Delete, Tab/F2, Shift selection, '
                      'Save XY, repeated Delete series, Save & Close and Cancel isolation', flush=True)
            finally:
                user32.mouse_event(0x0004, 0, 0, 0, 0)
                for code in (0x11, 0x10):
                    user32.keybd_event(code, 0, 2, 0)
                if old_clipboard is not None:
                    clipboard.setText(old_clipboard)
                view.request_shutdown()
                view._gui_runtime.destroy()


if __name__ == '__main__':
    main()
