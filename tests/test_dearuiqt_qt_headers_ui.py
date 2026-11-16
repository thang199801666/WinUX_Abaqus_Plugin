"""Real generated table headers through label edits and column transactions."""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'vendor'))
sys.path.insert(0, str(ROOT))
from DearUIQt import QGuiRuntime, StandaloneUiHost
from DearUIQt.QtCore import Qt
from DearUIQt.QtGui import QStandardItemModel, QStandardItem
from DearUIQt.QtWidgets import QApplication, QMainWindow, QTableView


def main():
    runtime = QGuiRuntime()
    runtime.createContext(manual_callbacks=True)
    host = StandaloneUiHost(backend=runtime.backend)
    app = QApplication(after=host.after)
    window = model = None
    try:
        window = QMainWindow('DearUIQt model headers', width=640, height=360,
                             after=host.after, backend=runtime.backend)
        grid = QTableView(parent=window, height=280, after=host.after)
        model = QStandardItemModel()
        for row in range(3):
            model.appendRow([QStandardItem('%d:%d' % (row, col)) for col in range(3)])
        grid.setModel(model)
        runtime.createViewport(title='DearUIQt model headers', width=640, height=360)
        runtime.setup()
        runtime.setPrimaryWindow(window)
        runtime.show()
        def verify(labels):
            for _ in range(4):
                host.pump()
                runtime.renderFrame()
            assert [column.label for column in grid.columns] == labels
            native = runtime.backend.get_item_children(grid.tag, 0)
            assert [runtime.backend.get_item_configuration(item)['label'] for item in native] == labels
        verify(['1', '2', '3'])
        grid.setCurrentKey(1)
        model.setHorizontalHeaderLabels(['A', 'B', 'C'])
        verify(['A', 'B', 'C'])
        model.horizontalHeaderItem(1).setText('edited')
        verify(['A', 'edited', 'C'])
        model.insertColumns(1, 1)
        verify(['A', '2', 'edited', 'C'])
        model.removeColumns(0, 2)
        verify(['edited', 'C'])
        model.setHeaderData(1, Qt.Horizontal, 42)
        verify(['edited', '42'])
        events = []
        model.headerDataChanged.connect(lambda *args: events.append(args))
        taken = model.takeHorizontalHeaderItem(1)
        verify(['edited', '2'])
        assert events == []  # Native refresh must not invent a public Qt signal.
        model.setHorizontalHeaderItem(1, taken)
        verify(['edited', '42'])
        assert grid.selected == {1} and grid.current == 1
        print('PASS: real generated table default/edited/numeric headers, column shifts and selection retention', flush=True)
    finally:
        if window is not None: window.delete()
        if model is not None: model.delete()
        app.delete()
        host.close()
        runtime.destroy()


if __name__ == '__main__':
    main()
