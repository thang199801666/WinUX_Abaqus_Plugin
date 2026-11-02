"""Real shared worksheet editing/copy and Plot Digitizer read-only adapter."""
import os
import sys
import tempfile
import time
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import run_winux
run_winux._configure_bundled_dependencies(str(ROOT))
from DearUIQt.core import Qt
from DearUIQt.dialogs.qt_dialog import QtDialog
from DearUIQt.modelview import QTableWidget, QTableWidgetItem, QtDataGridView, QtGridRow
from DearUIQt.modelview.spreadsheet_behavior import QCursor, QKeyboard
from WinUx.controllers.callbacks import REQUIRED_CALLBACK_KEYS
from WinUx.view import WinUXView
from WinUx.plotdigitizer.ui.dialog import PlotDigitizerDialog
from PIL import Image


def main():
    temp_root = Path(os.environ['LOCALAPPDATA']) / 'Temp' / 'opencode'
    with tempfile.TemporaryDirectory(prefix='winux-spreadsheet-', dir=temp_root) as profile:
        with patch.dict(os.environ, {'APPDATA': profile}):
            view = WinUXView({key: lambda *args, **kwargs: None for key in REQUIRED_CALLBACK_KEYS})
            dialog = digitizer = None

            def pump(count=12):
                for _ in range(count):
                    view.update()
                    time.sleep(.01)

            clipboard = {'text': '', 'ok': True}
            def put(text):
                if clipboard['ok']:
                    clipboard['text'] = text
                return clipboard['ok']
            clip = SimpleNamespace(setText=put, text=lambda: clipboard['text'])

            try:
                view._gui_runtime.show()
                dialog = QtDialog(view, 'Shared spreadsheet test', 640, 420)
                table = QTableWidget(4, 4, parent=dialog._qt_parent(dialog.content), after=view.after,
                                     height=240)
                table.setHorizontalHeaderLabels(['#', 'X', 'Y', 'Z'])
                for row in range(4):
                    for col in range(4):
                        table.setItem(row, col, QTableWidgetItem(str(row * 10 + col)))
                errors = []
                sheet = table.enableSpreadsheet(first_column=1, on_error=errors.append)
                sheet.controller.clipboard = clip
                dialog.show()
                pump(25)
                sheet.select_range((2, 2), (0, 0))
                sheet.command('copy')
                assert clipboard['text'] == '1\t2\t3\n11\t12\t13\n21\t22\t23'
                sheet.select_range((0, 0), (1, 1))
                clipboard['text'] = '100\t200\n300\t400'
                sheet.command('paste')
                assert table.item(1, 2).text() == '400'
                assert table.item(1, 0).text() == '10', 'Gutter was modified'
                sheet.command('clear')
                assert table.item(1, 2).text() == ''
                clipboard['text'] = 'filled'
                sheet.command('paste')
                assert table.item(0, 1).text() == table.item(1, 2).text() == 'filled'
                clipboard['ok'] = False
                sheet.command('cut')
                assert table.item(0, 1).text() == 'filled'
                clipboard['ok'] = True
                sheet.select_range((0, 0))
                assert sheet.begin_edit()
                sheet._editor.setText('edited')
                sheet.commit_editor()
                assert table.item(0, 1).text() == 'edited'
                assert sheet.begin_edit()
                sheet._editor.setText('discarded')
                sheet.cancel_editor()
                assert table.item(0, 1).text() == 'edited'
                sheet.select_range((0, 2))
                with patch.object(sheet, 'owns_keyboard', return_value=True), \
                        patch.object(QKeyboard, 'isControlDown', return_value=False), \
                        patch.object(QKeyboard, 'isShiftDown', return_value=False):
                    sheet._key(user_data=Qt.Key_Tab)
                    pump(3)
                assert sheet.controller.selection.current == (1, 0)
                with patch.object(sheet, 'owns_keyboard', return_value=True), \
                        patch.object(QKeyboard, 'isControlDown', return_value=False), \
                        patch.object(QKeyboard, 'isShiftDown', return_value=True):
                    sheet._key(user_data=Qt.Key_Right)
                    pump(3)
                assert sheet.selected_range.bounds == (1, 0, 1, 1)

                # Use actual painted native cells, including builds that omit
                # table/row rect_min, rather than a hand-invented grid.
                pump()
                native = table.nativeItem(1, 2)
                x, y = table.backend.get_item_rect_min(native)
                with patch.object(sheet, '_input_available', return_value=True), \
                        patch.object(QCursor, 'pos', return_value=SimpleNamespace(x=lambda: x + 2, y=lambda: y + 5)):
                    assert sheet._hit() == (1, 1), sheet._hit()
                protected = table.item(2, 2)
                protected.setFlags(protected.flags() & ~Qt.ItemIsEditable)
                sheet.select_range((2, 0), (2, 2))
                before = [table.item(2, col).text() for col in range(4)]
                sheet.command('clear')
                assert [table.item(2, col).text() for col in range(4)] == before
                assert 'read-only' in errors[-1]
                table.setRowCount(5)
                sheet.select_range((4, 0))
                clipboard['text'] = '7\t8\t9'
                sheet.command('paste')
                assert [table.item(4, col).text() for col in (1, 2, 3)] == ['7', '8', '9']
                dialog.hide()
                pump(4)
                assert not sheet.owns_keyboard(), 'Hidden table still owns keyboard input'
                dialog.destroy()
                dialog = None
                pump()

                dialog = QtDialog(view, 'Application model spreadsheet', 500, 350)
                grid = QtDataGridView(dialog._qt_parent(dialog.content),
                                      [{'key': 'n', 'label': '#'}, {'key': 'x', 'label': 'X'},
                                       {'key': 'y', 'label': 'Y'}], height=200, after=view.after)
                model = [['1', '10'], ['2', '20']]
                writes = []
                def refresh():
                    grid.setRows([QtGridRow(str(i), (i + 1, *values)) for i, values in enumerate(model)])
                def apply_batch(changes):
                    # Application-side validation must finish before changing
                    # a single value; it may also own an undo transaction here.
                    for value in changes.values():
                        float(value)
                    writes.append(dict(changes))
                    for (row, col), value in changes.items():
                        model[row][col] = value
                    refresh()
                refresh()
                sheet = grid.enableSpreadsheet(first_column=1, write=apply_batch, on_error=errors.append)
                sheet.controller.clipboard = clip
                dialog.show()
                pump()
                sheet.select_range((0, 0))
                clipboard['text'] = '5\t50\n6\t60'
                sheet.command('paste')
                assert model == [['5', '50'], ['6', '60']] and len(writes) == 1
                clipboard['text'] = '7\tbad\n8\t80'
                sheet.command('paste')
                assert model == [['5', '50'], ['6', '60']] and len(writes) == 1
                assert grid.rows[0][1][1:] == ('5', '50')
                dialog.destroy()
                dialog = None
                pump()

                digitizer = PlotDigitizerDialog(view)
                digitizer.engine.apply_image(Image.new('RGB', (200, 150), 'white'), str(Path(profile) / 'test.png'))
                digitizer.engine.add_manual_point(10, 20)
                digitizer.engine.add_manual_point(30, 40)
                digitizer.show()
                digitizer._show_tool('data')
                pump(25)
                sheet = digitizer.data_worksheet
                sheet.controller.clipboard = clip
                sheet.select_range((0, 0), (1, 1))
                sheet.command('copy')
                assert clipboard['text'] == '10\t20\n30\t40'
                assert set(digitizer.result_grid.selectedKeys()) == {'manual:0', 'manual:1'}
                before = digitizer.engine._snapshot()
                sheet.command('paste')
                assert digitizer.engine._snapshot() == before, 'Read-only results bypassed digitizer engine'
                digitizer._select_all_data_points()
                assert sheet.selected_range.bounds == (0, 0, 1, 1)
                digitizer._clear_data_selection()
                assert sheet.selected_range is None
                sheet.select_range((0, 0))
                digitizer.engine.add_dataset('Second dataset')
                pump()
                assert sheet.selected_range is None, 'Cell selection leaked into a different dataset'
                print('PASS: shared real worksheet copy/paste/cut/clear, native cell hit testing, '
                      'F2 editor commit/cancel, protected cells and Plot Digitizer XY clipboard', flush=True)
            finally:
                if digitizer is not None:
                    digitizer.destroy()
                if dialog is not None:
                    dialog.destroy()
                view.request_shutdown()
                view._gui_runtime.destroy()


if __name__ == '__main__':
    main()
