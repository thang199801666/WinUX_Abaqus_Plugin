"""Real table selection/cell themes and row refresh; no WinUx imports."""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'vendor'))
sys.path.insert(0, str(ROOT))
from DearUIQt import QGuiRuntime, StandaloneUiHost
from DearUIQt.core import QAbstractTableModel, Qt
from DearUIQt.widgets import QApplication, QMainWindow
from DearUIQt.modelview import QtDataGridView, QtGridRow
from DearUIQt.modelview.themes import qt_item_row_theme, qt_item_text_theme


def main():
    runtime = QGuiRuntime()
    runtime.createContext(manual_callbacks=True)
    host = StandaloneUiHost(backend=runtime.backend)
    application = QApplication(after=host.after)
    window = None
    try:
        window = QMainWindow('DearUIQt table update regression', width=680, height=400,
                             after=host.after, backend=runtime.backend)
        table = QtDataGridView(parent=window, columns=['Name', 'Type', 'Size'],
                               height=320, after=host.after, multiple=True)
        rows = [QtGridRow(i, ('row ' + str(i), 'File', i)) for i in range(20)]
        table.setRows(rows)
        runtime.createViewport(title='DearUIQt table update regression', width=680, height=400)
        runtime.setup()
        runtime.setPrimaryWindow(window)
        runtime.show()
        backend = runtime.backend
        def pump(count=4):
            for _ in range(count):
                host.pump()
                runtime.renderFrame()
        pump(12)
        for key in (7, 8, 3):
            table.setCurrentKey(key)
            pump()
            assert table.selected == {key}
            for row_key, native in table.items.items():
                assert bool(backend.get_value(native)) == (row_key == key)
            expected_row = qt_item_row_theme(backend, selected=True, current=True, active=True)
            expected_text = qt_item_text_theme(backend, selected=True, active=True)
            assert backend.get_item_theme(table.items[key]) == expected_row
            assert all(backend.get_item_theme(cell) == expected_text
                       for cell in table._cell_text_items[key])
        original = table.items[3]
        table.setRows(rows + [QtGridRow(20, ('extra', 'File', 20))])
        pump()
        assert table.items[3] == original and table.selected == {3}
        table.setRows(list(reversed(rows)))
        pump()
        assert table.items[3] != original and table.selected == {3}
        table._row_clicked(original, True, 3)
        table._set_view_focus(False)
        pump()
        expected_text = qt_item_text_theme(backend, selected=True, active=False)
        assert all(backend.get_item_theme(cell) == expected_text
                   for cell in table._cell_text_items[3])
        class Model(QAbstractTableModel):
            def rowCount(self, parent=None):
                return 0 if parent is not None and parent.isValid() else 200
            def columnCount(self, parent=None): return 3
            def data(self, index, role=Qt.DisplayRole):
                return str(index.row()) if role == Qt.DisplayRole else None
        model = Model()
        table.setModel(model)
        selection = table.selectionModel()
        snapshots = []
        selection.selectionChanged.connect(lambda added, removed: snapshots.append(
            len(selection.selectedIndexes())))
        table.selectAll()
        pump()
        assert snapshots == [600]
        table._sync_model_selection()
        assert snapshots == [600], 'No-op sync emitted transient clear/reselect'
        table.setCurrentKey(10)
        pump()
        assert snapshots == [600, 3]
        assert selection.currentIndex() == model.index(10, 0)
        assert bool(backend.get_value(table.items[10]))
        print('PASS: DearUIQt-only real table selection, sibling text colors, '
              'active/inactive themes, append/reorder, stale callbacks and '
              'single-snapshot model selection', flush=True)
    finally:
        if window is not None:
            window.delete()
        application.delete()
        host.close()
        runtime.destroy()


if __name__ == '__main__':
    main()
