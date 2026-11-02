"""Real model-bound QListView local text/flags/checkbox changes, no WinUx."""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'vendor'))
sys.path.insert(0, str(ROOT))
from DearUIQt import QGuiRuntime, StandaloneUiHost
from DearUIQt.core import Qt
from DearUIQt.gui import QStandardItem, QStandardItemModel
from DearUIQt.widgets import QApplication, QMainWindow
from DearUIQt.modelview import QtListView


def main():
    runtime = QGuiRuntime()
    runtime.createContext(manual_callbacks=True)
    host = StandaloneUiHost(backend=runtime.backend)
    application = QApplication(after=host.after)
    window = model = None
    try:
        window = QMainWindow('DearUIQt list data updates', width=520, height=360,
                             after=host.after, backend=runtime.backend)
        model = QStandardItemModel()
        items = [QStandardItem('row ' + str(i)) for i in range(20)]
        items[4].setCheckState(Qt.Unchecked)
        model.invisibleRootItem().appendRows(items)
        view = QtListView(parent=window, height=280, after=host.after)
        view.setModel(model)
        runtime.createViewport(title='DearUIQt list data updates', width=520, height=360)
        runtime.setup()
        runtime.setPrimaryWindow(window)
        runtime.show()
        def pump():
            for _ in range(5):
                host.pump()
                runtime.renderFrame()
        pump()
        view.setCurrentKey(3)
        pump()
        native = dict(view.items)
        checkbox = view.checkboxes[4]
        items[3].setText('updated selected row')
        items[4].setCheckState(Qt.Checked)
        items[4].setEnabled(False)
        items[10].setData({'id': 10}, Qt.UserRole)
        pump()
        backend = runtime.backend
        assert view.items == native
        assert view.checkboxes[4] == checkbox
        assert view.selected == {3} and view.currentText() == 'updated selected row'
        assert backend.get_item_configuration(native[3])['label'] == '  updated selected row'
        assert bool(backend.get_value(checkbox))
        assert not backend.get_item_configuration(checkbox)['enabled']
        assert not backend.get_item_configuration(native[4])['enabled']
        assert view.itemData(10) == {'id': 10}
        items[7].setCheckState(Qt.Checked)
        pump()
        assert 7 in view.checkboxes
        assert view.selected == {3}
        assert bool(backend.get_value(view.items[3]))
        assert bool(backend.get_value(view.checkboxes[7]))
        print('PASS: native model-bound list local label/payload/flags/checkbox updates, '
              'stable IDs and structural checkbox fallback with selection retained', flush=True)
    finally:
        if window is not None: window.delete()
        if model is not None: model.delete()
        application.delete()
        host.close()
        runtime.destroy()


if __name__ == '__main__':
    main()
