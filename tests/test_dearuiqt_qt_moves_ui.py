"""Real shared list/table selection through custom-model row/column moves."""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'vendor'))
sys.path.insert(0, str(ROOT))
from DearUIQt import QGuiRuntime, StandaloneUiHost
from DearUIQt.QtCore import QModelIndex, QItemSelectionModel
from DearUIQt.QtWidgets import QApplication, QMainWindow, QHBoxLayout, QListView, QTableView
from test_dearuiqt_qt_moves import MovingTable


def main():
    runtime = QGuiRuntime()
    runtime.createContext(manual_callbacks=True)
    host = StandaloneUiHost(backend=runtime.backend)
    app = QApplication(after=host.after)
    window = model = None
    try:
        window = QMainWindow('DearUIQt custom model moves', width=760, height=360,
                             after=host.after, backend=runtime.backend)
        layout = QHBoxLayout(parent=window)
        listing = QListView(parent=layout, width=160, height=280, after=host.after)
        table = QTableView(parent=layout, height=280, after=host.after)
        model = MovingTable()
        for view in (listing, table): view.setModel(model)
        shared = QItemSelectionModel(model, parent=window)
        for view in (listing, table): view.setSelectionModel(shared)
        runtime.createViewport(title='DearUIQt custom model moves', width=760, height=360)
        runtime.setup()
        runtime.setPrimaryWindow(window)
        runtime.show()
        def verify(row, data):
            for _ in range(4):
                host.pump()
                runtime.renderFrame()
            for view in (listing, table):
                assert view.current == row and view.selected == {row}
                assert runtime.backend.get_value(view.items[row])
            assert shared.currentIndex().data() == data
        table.setCurrentKey(1)
        verify(1, '1:0')
        events = []
        shared.selectionChanged.connect(lambda *args: events.append('selection'))
        shared.currentChanged.connect(lambda *args: events.append('current'))
        root = QModelIndex()
        model.moveRows(root, 1, 2, root, 5)
        verify(3, '1:0')
        # Keep the list's displayed model column 0 fixed; arbitrary list
        # modelColumn/current painting is a separate compatibility milestone.
        model.moveColumn(root, 3, root, 1)
        verify(3, '1:0')
        model.moveRow(root, 3, root, 0)
        verify(0, '1:0')
        assert events == []
        print('PASS: real shared list/table custom-model row/column moves, item identity and silent selection/current remap', flush=True)
    finally:
        if window is not None: window.delete()
        if model is not None: model.delete()
        app.delete()
        host.close()
        runtime.destroy()


if __name__ == '__main__':
    main()
