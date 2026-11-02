"""Real library-only layout mutation/visibility/resize regression."""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'vendor'))
sys.path.insert(0, str(ROOT))
from DearUIQt import QGuiRuntime, StandaloneUiHost
from DearUIQt.core import QSize, QObject
from DearUIQt.layouts import QVBoxLayout, QGridLayout
from DearUIQt.widgets import QApplication, QMainWindow, QPushButton, QLabel, QRetainedItem


def main():
    runtime = QGuiRuntime()
    runtime.createContext(manual_callbacks=True)
    host = StandaloneUiHost(backend=runtime.backend)
    application = QApplication(after=host.after)
    window = None
    try:
        window = QMainWindow('DearUIQt layout regression', width=480, height=280,
                             backend=runtime.backend, after=host.after)
        box = QVBoxLayout(parent=window, spacing=4)
        window.setLayout(box)
        first = QPushButton('First', parent=box)
        first.setFixedSize(100, 24)
        runtime.createViewport(title='DearUIQt layout regression', width=480, height=280)
        runtime.setup()
        runtime.setPrimaryWindow(window)
        runtime.show()
        def pump():
            for _ in range(8):
                host.pump()
                runtime.renderFrame()
        pump()
        assert box.sizeHint() == QSize(100, 24)
        second = QPushButton('Second', parent=box)
        second.setFixedSize(80, 24)
        assert box.sizeHint() == QSize(100, 52)
        first.delete()
        assert box.count() == 1 and box.sizeHint() == QSize(80, 24)
        second.hide()
        assert box.sizeHint() == QSize(0, 0)
        second.show()
        runtime.resizeViewport(640, 360)
        pump()
        assert box.sizeHint() == QSize(80, 24)
        assert tuple(runtime.backend.get_item_rect_size(second.tag)) == (80, 24)

        grid = QGridLayout(2, parent=box)
        assert grid.count() == 0
        cell_button = QPushButton('Grid', parent=grid.cell(0, 1))
        cell_button.setFixedSize(70, 24)
        assert grid.count() == 1 and grid.sizeHint() == QSize(70, 24)
        box.insertLayout(0, grid)
        assert box.itemAt(0).layout() is grid
        pump()
        cell_button.delete()
        assert grid.count() == 0 and grid.sizeHint() == QSize(0, 0)
        pump()
        assert box.clear(delete=False) == 2
        assert box.count() == 0
        assert second.parent is window and grid.parent is window
        assert second.exists() and grid.exists()
        box.addWidget(second)
        pump()
        assert tuple(runtime.backend.get_item_rect_size(second.tag)) == (80, 24)

        canonical = QLabel('Still owned by window', parent=window)
        adapter_root = QObject(parent=window)
        adapter = QRetainedItem(canonical.tag, parent=adapter_root, backend=runtime.backend)
        application.setFocusObject(canonical)
        adapter_root.delete()
        assert adapter._deleted and canonical.exists()
        assert canonical.text() == 'Still owned by window'
        assert application.focusObject() is canonical
        pump()
        print('PASS: DearUIQt-only layout mutation/resize, live clear/reuse and non-owning native cleanup', flush=True)
    finally:
        if window is not None:
            window.delete()
        application.delete()
        host.close()
        runtime.destroy()


if __name__ == '__main__':
    main()
