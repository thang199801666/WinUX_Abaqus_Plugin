"""Real shared list/table selection through standard-item sort/layout hints."""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'vendor'))
sys.path.insert(0, str(ROOT))
from DearUIQt import QGuiRuntime, StandaloneUiHost
from DearUIQt.QtCore import Qt, QItemSelectionModel, QPersistentModelIndex
from DearUIQt.QtGui import QStandardItemModel, QStandardItem
from DearUIQt.QtWidgets import QApplication, QMainWindow, QHBoxLayout, QListView, QTableView


def main():
    runtime = QGuiRuntime()
    runtime.createContext(manual_callbacks=True)
    host = StandaloneUiHost(backend=runtime.backend)
    app = QApplication(after=host.after)
    window = model = None
    try:
        window = QMainWindow('DearUIQt recursive model sort', width=760, height=360,
                             after=host.after, backend=runtime.backend)
        layout = QHBoxLayout(parent=window)
        listing = QListView(parent=layout, width=180, height=280, after=host.after)
        table = QTableView(parent=layout, height=280, after=host.after)
        model = QStandardItemModel()
        for row, (text, value) in enumerate((('b', 20), ('A', 10), ('a', 30))):
            item = QStandardItem(text)
            item.setData(value, Qt.UserRole)
            model.appendRow([item, QStandardItem('id%d' % row)])
        for view in (listing, table): view.setModel(model)
        shared = QItemSelectionModel(model, parent=window)
        for view in (listing, table): view.setSelectionModel(shared)
        runtime.createViewport(title='DearUIQt recursive model sort', width=760, height=360)
        runtime.setup()
        runtime.setPrimaryWindow(window)
        runtime.show()
        def verify(row):
            for _ in range(4):
                host.pump()
                runtime.renderFrame()
            for view in (listing, table):
                assert view.selected == {row} and view.current == row
                assert runtime.backend.get_value(view.items[row])
            assert listing.currentText() == 'b'
            assert table.rowValues(row) == ('b', 'id0')
        table.setCurrentKey(0)
        verify(0)
        persistent = QPersistentModelIndex(shared.currentIndex())
        events = []
        shared.selectionChanged.connect(lambda *args: events.append('selection'))
        shared.currentChanged.connect(lambda *args: events.append('current'))
        model.sort(0)
        verify(2)
        model.sort(0, Qt.DescendingOrder)
        verify(0)
        model.setSortRole(Qt.UserRole)
        model.sort(0)
        verify(1)
        assert persistent.row() == 1 and persistent.data() == 'b' and events == []
        print('PASS: real shared list/table standard-item case/custom-role sorts, typed layout payloads and silent identity remap', flush=True)
    finally:
        if window is not None: window.delete()
        if model is not None: model.delete()
        app.delete()
        host.close()
        runtime.destroy()


if __name__ == '__main__':
    main()
