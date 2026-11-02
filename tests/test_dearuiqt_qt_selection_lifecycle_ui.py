"""Qt-compatible selection-model lifecycle on a real DearUIQt list/model."""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'vendor'))
sys.path.insert(0, str(ROOT))
from DearUIQt import QGuiRuntime, StandaloneUiHost
from DearUIQt.QtCore import QItemSelectionModel
from DearUIQt.QtGui import QStandardItem, QStandardItemModel
from DearUIQt.QtWidgets import QApplication, QMainWindow, QListView


def populate(model):
    model.invisibleRootItem().appendRows([QStandardItem('row ' + str(i)) for i in range(4)])


def main():
    runtime = QGuiRuntime()
    runtime.createContext(manual_callbacks=True)
    host = StandaloneUiHost(backend=runtime.backend)
    application = QApplication(after=host.after)
    window = model = other = None
    try:
        window = QMainWindow('DearUIQt Qt selection lifecycle', width=520, height=360,
                             after=host.after, backend=runtime.backend)
        model = QStandardItemModel()
        populate(model)
        view = QListView(parent=window, height=280, after=host.after)
        view.setModel(model)
        runtime.createViewport(title='DearUIQt Qt selection lifecycle', width=520, height=360)
        runtime.setup()
        runtime.setPrimaryWindow(window)
        runtime.show()
        def pump():
            for _ in range(5):
                host.pump()
                runtime.renderFrame()
        pump()
        view.setCurrentKey(1)
        selection = view.selectionModel()
        events = []
        selection.selectionChanged.connect(lambda *args: events.append('selection'))
        selection.currentChanged.connect(lambda *args: events.append('current'))
        model.clear()
        pump()
        assert events == []
        assert not selection.hasSelection() and not selection.currentIndex().isValid()
        assert not view.items
        populate(model)
        pump()
        view.setCurrentKey(2)
        events.clear()
        selected = set(selection.selectedIndexes())
        selection.clearCurrentIndex()
        pump()
        assert events == ['current']
        assert set(selection.selectedIndexes()) == selected
        assert bool(runtime.backend.get_value(view.items[2]))
        assert view.current is None  # M1.3a propagates model current to the list.
        other = QStandardItemModel()
        populate(other)
        # Switch an independently owned selection model, not the view's model
        # behind its back (that would leave a deliberately mismatched binding).
        selection = QItemSelectionModel(model, parent=window)
        selection.selectionChanged.connect(lambda *args: events.append('selection'))
        selection.currentChanged.connect(lambda *args: events.append('current'))
        changed = []
        selection.modelChanged.connect(changed.append)
        selection.setModel(other)
        selection.setCurrentIndex(other.index(0, 0), QItemSelectionModel.ClearAndSelect)
        events.clear()
        model.modelReset.emit()
        assert selection.currentIndex() == other.index(0, 0)
        assert events == []
        other.beginResetModel()
        other.endResetModel()
        assert events == []
        assert changed == [other]
        assert not selection.hasSelection() and not selection.currentIndex().isValid()
        print('PASS: Qt facades, real model/list reset, silent selection lifecycle, '
              'independent current clearing and old/new model reset isolation', flush=True)
    finally:
        if window is not None: window.delete()
        if model is not None: model.delete()
        if other is not None: other.delete()
        application.delete()
        host.close()
        runtime.destroy()


if __name__ == '__main__':
    main()
