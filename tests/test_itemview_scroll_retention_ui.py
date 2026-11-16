"""abaqus python tests/test_itemview_scroll_retention_ui.py [--physical-input]."""
import ctypes
import sys
import time
from ctypes import wintypes
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import run_winux
run_winux._configure_bundled_dependencies(str(ROOT))

from DearUIQt.backends import dpg
from DearUIQt.dialogs.qt_dialog import QtDialog
from DearUIQt.gui.placement import item_screen_rect
from DearUIQt.modelview import (
    QtListView, QtListItem, QtDataGridView, QtGridRow, QTreeView, QTreeItem,
    QListWidget, QTableWidget, QTableWidgetItem, QTreeWidget, QTreeWidgetItem,
)
from WinUx.controllers.callbacks import REQUIRED_CALLBACK_KEYS
from WinUx.view import WinUXView


def main():
    view = WinUXView({key: lambda *a, **kw: None for key in REQUIRED_CALLBACK_KEYS})

    def pump(count=8):
        for _ in range(count):
            view.update()
            time.sleep(.01)

    def unchanged(widget, expected, stage):
        for _ in range(8):
            pump(1)
            actual = float(dpg.get_y_scroll(widget.tag))
            assert abs(actual - expected) <= 1, (type(widget).__name__, stage, expected, actual)

    try:
        view._gui_runtime.show()
        pump()
        physical = '--physical-input' in sys.argv
        if physical:
            user32 = ctypes.windll.user32
            user32.GetForegroundWindow.restype = wintypes.HWND
            owner = wintypes.HWND(view._find_main_viewport_hwnd())
            foreground_thread = user32.GetWindowThreadProcessId(user32.GetForegroundWindow(), None)
            current_thread = ctypes.windll.kernel32.GetCurrentThreadId()
            attached = user32.AttachThreadInput(current_thread, foreground_thread, True)
            try:
                user32.BringWindowToTop(owner)
                user32.SetForegroundWindow(owner)
            finally:
                if attached:
                    user32.AttachThreadInput(current_thread, foreground_thread, False)
        for kind in ('list', 'table', 'tree', 'list_widget', 'table_widget', 'tree_widget', 'spreadsheet'):
            requested = sys.argv[sys.argv.index('--kind') + 1] if '--kind' in sys.argv else None
            if requested is not None and kind != requested:
                continue
            dialog = QtDialog(view, 'Scroll retention: ' + kind, width=640, height=430, footer=False)
            set_current = None
            if kind == 'list':
                rows = [QtListItem(i, 'Row {:03d}'.format(i)) for i in range(200)]
                widget = QtListView(items=rows, parent=dialog.content, height=330, after=view.after)
                refresh = lambda: widget.setItems(list(reversed(rows)))
                click = lambda key: widget._row_clicked(widget.items[key], True, key)
                native_for = lambda key: widget.items[key]
            elif kind == 'table':
                rows = [QtGridRow(i, ('Row {:03d}'.format(i), i)) for i in range(200)]
                widget = QtDataGridView(columns=['Name', 'Value'], parent=dialog.content,
                                        height=330, after=view.after)
                widget.setRows(rows)
                refresh = lambda: widget.setRows(list(reversed(rows)))
                click = lambda key: widget._row_clicked(widget.items[key], True, key)
                native_for = lambda key: widget.items[key]
            elif kind == 'tree':
                rows = [QTreeItem('Row {:03d}'.format(i), key=i) for i in range(200)]
                widget = QTreeView(rows, parent=dialog.content, height=330, after=view.after)
                refresh = lambda: widget.setItems(list(reversed(rows)))
                click = lambda key: widget._selected(widget._native_by_key[key], True, key)
                native_for = lambda key: widget._native_by_key[key]
            elif kind == 'list_widget':
                widget = QListWidget(parent=dialog.content, height=330, after=view.after)
                widget.addItems(['Row {:03d}'.format(i) for i in range(200)])
                rows = [widget.item(i) for i in range(200)]
                set_current = widget.setCurrentRow
                native_for = lambda key: widget.items[rows[key].key]
                click = lambda key: widget._row_clicked(native_for(key), True, rows[key].key)
                refresh = lambda: rows[80].setText('Updated row 080')
            elif kind == 'tree_widget':
                widget = QTreeWidget(parent=dialog.content, height=330, after=view.after)
                rows = [QTreeWidgetItem(['Row {:03d}'.format(i)]) for i in range(200)]
                widget.addTopLevelItems(rows)
                set_current = lambda key: widget.setCurrentItem(rows[key])
                native_for = lambda key: widget._rendered[rows[key]]['selectable']
                click = lambda key: widget._native_clicked(native_for(key), True, rows[key].key)
                refresh = lambda: rows[80].setText(0, 'Updated row 080')
            else:
                widget = QTableWidget(200, 2, parent=dialog.content, height=330, after=view.after)
                for row in range(200):
                    widget.setItem(row, 0, QTableWidgetItem('Row {:03d}'.format(row)))
                    widget.setItem(row, 1, QTableWidgetItem(str(row)))
                set_current = lambda key: widget.setCurrentCell(key, 0)
                native_for = lambda key: widget.nativeItem(key, 0)
                click = set_current
                refresh = lambda: widget.item(80, 0).setText('Updated row 080')
                if kind == 'spreadsheet':
                    behavior = widget.enableSpreadsheet(after=view.after)
                    click = lambda key: behavior.select_range((key, 0))
            if set_current is None:
                set_current = widget.setCurrentKey
            dialog.show()
            pump(20)
            set_current(0)
            pump()
            if physical:
                left, top, right, bottom = item_screen_rect(dpg, dialog.content)
                assert user32.SetCursorPos(int(left + 90), int(top + 120))
                pump(2)
                user32.mouse_event(0x0800, 0, 0, -1200, 0)
                pump()
                wheel_offset = float(dpg.get_y_scroll(widget.tag))
                assert wheel_offset > 0, (kind, 'Physical wheel did not scroll')
                unchanged(widget, wheel_offset, 'physical wheel with first row current')
            maximum = float(dpg.get_y_scroll_max(widget.tag))
            assert maximum > 500, (kind, maximum)
            dpg.set_y_scroll(widget.tag, 900)
            pump()
            offset = float(dpg.get_y_scroll(widget.tag))
            assert offset > 500, (kind, offset)
            unchanged(widget, offset, 'idle after scroll')
            widget.setFocus()
            unchanged(widget, offset, 'focus with first row current')
            set_current(1)
            unchanged(widget, offset, 'programmatic current offscreen')
            viewport_top = item_screen_rect(dpg, dialog.content)[1]
            target = next(key for key in range(200)
                          if viewport_top + 50 < dpg.get_item_state(native_for(key)).get('rect_min', (0, -10000))[1] < viewport_top + 180)
            click(target)
            unchanged(widget, offset, 'click visible row')
            if kind == 'spreadsheet':
                set_current(0)
                click(target)
                assert widget.currentRow() == target, 'Repeated range selection retained stale current row'
                unchanged(widget, offset, 'repeat range selection after external current change')
            if physical:
                set_current(0)
                unchanged(widget, offset, 'old current restored before physical click')
                left, top, right, bottom = item_screen_rect(dpg, native_for(target))
                x, y = int(left + min(40, (right - left) / 2)), int((top + bottom) / 2)
                assert user32.SetCursorPos(x, y)
                pump(2)
                cursor = wintypes.POINT()
                assert user32.GetCursorPos(ctypes.byref(cursor))
                assert (cursor.x, cursor.y) == (x, y), 'Desktop input interrupted'
                user32.mouse_event(0x0002, 0, 0, 0, 0)
                pump(2)
                user32.mouse_event(0x0004, 0, 0, 0, 0)
                unchanged(widget, offset, 'physical click visible row')
                if kind in ('list', 'table'):
                    assert widget.current == target, (kind, 'Physical click did not select target')
                elif kind == 'tree':
                    assert widget.currentKey() == target
                elif kind == 'list_widget':
                    assert widget.currentRow() == target
                elif kind == 'tree_widget':
                    assert widget.currentItem() is rows[target]
                elif kind == 'spreadsheet':
                    assert widget.currentRow() == target, (
                        kind, target, widget.currentRow(), behavior.selected_range,
                        behavior._hit(), behavior._input_available(), (x, y),
                        dpg.get_item_rect_min(native_for(target)),
                        widget.rowAtGlobal(y))
            refresh()
            unchanged(widget, offset, 'structural refresh')
            print('PASS:', kind, 'scroll, focus, selection, click and refresh retain viewport', flush=True)
            dialog.destroy()
            pump()
    finally:
        if '--physical-input' in sys.argv:
            ctypes.windll.user32.mouse_event(0x0004, 0, 0, 0, 0)
        view.request_shutdown()
        view._gui_runtime.destroy()


if __name__ == '__main__':
    main()
