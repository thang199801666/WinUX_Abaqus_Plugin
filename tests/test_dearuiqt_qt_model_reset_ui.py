"""Real shared views across changed-size/empty/repopulated custom-model resets."""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'vendor'))
sys.path.insert(0, str(ROOT))
from DearUIQt import QGuiRuntime, StandaloneUiHost
from DearUIQt.QtCore import QItemSelectionModel, QPersistentModelIndex
from DearUIQt.QtWidgets import QApplication, QMainWindow, QHBoxLayout, QListView, QTableView
from test_dearuiqt_qt_model_reset import ResettableTable


def main():
    runtime = QGuiRuntime()
    runtime.createContext(manual_callbacks=True)
    host = StandaloneUiHost(backend=runtime.backend)
    app = QApplication(after=host.after)
    window = model = None
    try:
        window = QMainWindow('DearUIQt reset visibility', width=760, height=360,
                             after=host.after, backend=runtime.backend)
        layout = QHBoxLayout(parent=window)
        listing = QListView(parent=layout, width=180, height=280, after=host.after)
        table = QTableView(parent=layout, height=280, after=host.after)
        model = ResettableTable()
        observations = []
        shared = None
        model.modelReset.connect(lambda: observations.append((shared.currentIndex().isValid(), shared.hasSelection())))
        for view in (listing, table): view.setModel(model)
        shared = QItemSelectionModel(model, parent=window)
        for view in (listing, table): view.setSelectionModel(shared)
        runtime.createViewport(title='DearUIQt reset visibility', width=760, height=360)
        runtime.setup()
        runtime.setPrimaryWindow(window)
        runtime.show()
        def verify(rows, selected, current):
            for _ in range(4):
                host.pump()
                runtime.renderFrame()
            for view in (listing, table):
                assert len(view.items) == rows
                assert view.selected == selected and view.current == current
                for key, native in view.items.items():
                    assert bool(runtime.backend.get_value(native)) == (key in selected)
        table.setCurrentKey(1)
        verify(2, {1}, 1)
        persistent = QPersistentModelIndex(shared.currentIndex())
        events = []
        shared.selectionChanged.connect(lambda *args: events.append('selection'))
        shared.currentChanged.connect(lambda *args: events.append('current'))
        model.resetTo([['new0', 'n1'], ['new2', 'n3'], ['new4', 'n5']])
        verify(3, set(), None)
        assert not persistent.isValid() and events == []
        model.resetTo([])
        verify(0, set(), None)
        model.resetTo([['again', 'value']])
        verify(1, set(), None)
        assert observations == [(False, False)] * 3 and events == []
        table.setCurrentKey(0)
        verify(1, {0}, 0)
        assert shared.currentIndex().data() == 'again'
        print('PASS: real shared views changed-size/empty/repopulated resets, early observer visibility and silent invalidation', flush=True)
    finally:
        if window is not None: window.delete()
        if model is not None: model.delete()
        app.delete()
        host.close()
        runtime.destroy()


if __name__ == '__main__':
    main()
