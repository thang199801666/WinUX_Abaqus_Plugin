"""Real shared list/table selection in both directions, reset and model switch."""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'vendor'))
sys.path.insert(0, str(ROOT))
from DearUIQt import QGuiRuntime, StandaloneUiHost
from DearUIQt.QtCore import QItemSelectionModel
from DearUIQt.QtGui import QStandardItemModel, QStandardItem
from DearUIQt.QtWidgets import QApplication, QMainWindow, QHBoxLayout, QListView, QTableView


def make_model(rows):
    model = QStandardItemModel()
    model.invisibleRootItem().appendRows([
        [QStandardItem('row ' + str(i)), QStandardItem('File'), QStandardItem(str(i))]
        for i in range(rows)])
    return model


def main():
    runtime = QGuiRuntime()
    runtime.createContext(manual_callbacks=True)
    host = StandaloneUiHost(backend=runtime.backend)
    application = QApplication(after=host.after)
    window = model = other = None
    try:
        window = QMainWindow('DearUIQt shared Qt selection', width=860, height=400,
                             after=host.after, backend=runtime.backend)
        layout = QHBoxLayout(parent=window)
        first = QListView(parent=layout, width=180, height=300, multiple=True, after=host.after)
        second = QListView(parent=layout, width=180, height=300, multiple=True, after=host.after)
        grid = QTableView(parent=layout, columns=['Name', 'Type', 'Size'], width=420, height=300,
                          multiple=True, after=host.after)
        views = (first, second, grid)
        model = make_model(8)
        for view in views: view.setModel(model)
        shared = QItemSelectionModel(model, parent=window)
        for view in views: view.setSelectionModel(shared)
        runtime.createViewport(title='DearUIQt shared Qt selection', width=860, height=400)
        runtime.setup()
        runtime.setPrimaryWindow(window)
        runtime.show()
        def pump():
            for _ in range(5):
                host.pump()
                runtime.renderFrame()
        def verify(selected, current):
            pump()
            for view in views:
                assert view.selected == selected, (type(view).__name__, view.selected, selected)
                assert view.current == current
                for key, native in view.items.items():
                    assert bool(runtime.backend.get_value(native)) == (key in selected)
        pump()
        events = []
        shared.selectionChanged.connect(lambda *args: events.append(True))
        first.setCurrentIndex(model.index(3, 0))
        verify({3}, 3)
        assert len(events) == 1
        shared.select(model.index(5, 0), shared.SelectCurrent)
        verify({5}, 3)  # Current selection is independent of keyboard current.
        shared.clearCurrentIndex()
        verify({5}, None)
        shared.clearSelection()
        verify(set(), None)
        grid.setCurrentKey(2)
        verify({2}, 2)
        assert len(shared.selectedIndexes()) == 3
        assert shared.selectedRows() == [model.index(2, 0)]
        model.insertColumns(1, 1)
        verify({2}, 2)
        assert len(shared.selectedIndexes()) == 3
        assert not shared.isSelected(model.index(2, 1))
        model.removeColumns(1, 1)
        verify({2}, 2)
        assert shared.selectedRows() == [model.index(2, 0)]
        model.insertRows(0, 2)
        verify({4}, 4)
        model.removeRows(0, 1)
        verify({3}, 3)
        model.removeRows(3, 1)
        verify(set(), 2)  # Qt moves current to the preceding surviving row.
        shared.setCurrentIndex(model.index(2, 0), shared.ClearAndSelect)
        model.setItem(2, 0, QStandardItem('replacement'))
        verify({2}, 2)
        taken = model.takeItem(2, 0)
        verify(set(), None)
        model.setItem(2, 0, taken)
        verify(set(), None)
        model.beginResetModel()
        model.endResetModel()
        verify(set(), None)
        root = model.invisibleRootItem()
        root.setRowCount(10)
        shared.setCurrentIndex(model.index(9, 0), shared.ClearAndSelect | shared.Rows)
        verify({9}, 9)
        root.setRowCount(4)
        verify(set(), 3)
        root.setRowCount(-1)  # Qt item API rejects negatives, without clearing.
        verify(set(), 3)
        assert model.rowCount() == 4
        root.setRowCount(0)
        verify(set(), None)
        root.setRowCount(8)
        verify(set(), None)
        other = make_model(2)
        first.setModel(other)
        second.setCurrentKey(6)
        pump()
        assert shared.model() is model
        assert second.selected == grid.selected == {6}
        assert first.selected == set() and first.current is None
        first.setModel(None)
        pump()
        assert first.items == {}
        print('PASS: real Qt-facade shared list/table selection, external Current vs keyboard '
               'current, structural remap/current fallback, item replacement/take, full-row query, silent reset, '
               'item-owned row resize, isolated model switch and detach', flush=True)
    finally:
        if window is not None: window.delete()
        if model is not None: model.delete()
        if other is not None: other.delete()
        application.delete()
        host.close()
        runtime.destroy()


if __name__ == '__main__':
    main()
