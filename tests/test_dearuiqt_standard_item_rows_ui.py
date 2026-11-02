"""Real model-bound table across bulk standard-item insertion/removal."""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'vendor'))
sys.path.insert(0, str(ROOT))
from DearUIQt import QGuiRuntime, StandaloneUiHost
from DearUIQt.core import Qt, QPersistentModelIndex
from DearUIQt.gui import QStandardItem, QStandardItemModel
from DearUIQt.widgets import QApplication, QMainWindow
from DearUIQt.modelview import QtDataGridView


def row(key):
    item = QStandardItem('row ' + key)
    item.setData(key, Qt.UserRole)
    return [item, QStandardItem('File')]


def main():
    runtime = QGuiRuntime()
    runtime.createContext(manual_callbacks=True)
    host = StandaloneUiHost(backend=runtime.backend)
    application = QApplication(after=host.after)
    window = model = None
    try:
        window = QMainWindow('DearUIQt bulk model rows', width=640, height=360,
                             after=host.after, backend=runtime.backend)
        grid = QtDataGridView(parent=window, columns=['Name', 'Type'], height=290, after=host.after)
        model = QStandardItemModel(0, 2)
        root = model.invisibleRootItem()
        root.appendRows([row(str(i)) for i in range(5)])
        grid.setRowKeyRole(Qt.UserRole)
        grid.setModel(model)
        runtime.createViewport(title='DearUIQt bulk model rows', width=640, height=360)
        runtime.setup()
        runtime.setPrimaryWindow(window)
        runtime.show()
        def pump():
            for _ in range(5):
                host.pump()
                runtime.renderFrame()
        pump()
        grid.setCurrentKey('3')
        persistent = QPersistentModelIndex(model.item(3).index())
        events = []
        model.rowsInserted.connect(lambda parent, first, last: events.append(('insert', first, last)))
        model.rowsRemoved.connect(lambda parent, first, last: events.append(('remove', first, last)))
        root.insertRows(1, [row('extra ' + str(i)) for i in range(3)])
        pump()
        assert events == [('insert', 1, 3)]
        assert len(grid.rows) == 8
        assert grid.rowValues('3') == ('row 3', 'File')
        assert grid.selected == {'3'} and persistent.row() == 6
        assert bool(runtime.backend.get_value(grid.items['3']))
        removed = QPersistentModelIndex(model.index(1, 0))
        root.removeRows(1, 3)
        pump()
        assert events[-1] == ('remove', 1, 3)
        assert len(grid.rows) == 5
        assert grid.selected == {'3'} and persistent.row() == 3
        assert not removed.isValid() and removed.model() is None
        model.setRowCount(20)
        pump()
        assert len(grid.rows) == 20
        empty_key = grid.rows[10][0]
        assert runtime.backend.get_item_configuration(grid.items[empty_key])['label'] == ''
        assert runtime.backend.get_value(grid._cell_text_items[empty_key][0]) == ''
        model.setRowCount(5)
        pump()
        assert len(grid.rows) == 5 and grid.selected == {'3'}
        print('PASS: standalone model-bound table bulk insert/remove/resize, '
              'single range notifications, stable-key selection and persistent item rows', flush=True)
    finally:
        if window is not None:
            window.delete()
        if model is not None:
            model.delete()
        application.delete()
        host.close()
        runtime.destroy()


if __name__ == '__main__':
    main()
