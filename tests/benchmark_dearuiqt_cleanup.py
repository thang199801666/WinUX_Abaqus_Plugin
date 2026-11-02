"""Library-only non-owning subtree deletion and live layout detachment."""
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'vendor'))
sys.path.insert(0, str(ROOT))
from DearUIQt.core import QObject, QEvent
from DearUIQt.widgets import QApplication, QWidget, QRetainedItem
from DearUIQt.layouts import QVBoxLayout, QGridLayout
from DearUIQt.runtime import StandaloneUiHost
from benchmark_dearuiqt_layout import Backend


def adapter_tree():
    backend = Backend()
    host = StandaloneUiHost(backend=backend)
    app = QApplication(after=host.after)
    root, unrelated = QObject(after=host.after), QObject(after=host.after)
    try:
        for _ in range(1000):
            QRetainedItem(backend.add_group(), parent=root, backend=backend)
        for _ in range(3000):
            app.postEvent(unrelated, QEvent(QEvent.User))
        started = time.perf_counter()
        root.delete()
        elapsed = time.perf_counter() - started
        assert len(app._posted) == 3000
        assert len(backend.parents) == 1000, 'Non-owning adapters deleted native items'
        print('ADAPTER_DELETE nodes=1000 unrelated_events=3000 seconds={:.4f}'.format(elapsed), flush=True)
    finally:
        root.delete()
        unrelated.delete()
        app.delete()
        host.close()


def detach_layout(grid_mode):
    backend = Backend()
    root = QWidget(backend.add_group(), backend=backend)
    layout = QGridLayout(2, parent=root) if grid_mode else QVBoxLayout(parent=root)
    widgets = []
    count = 1000 if grid_mode else 3000
    try:
        for index in range(count):
            parent = layout.cell(index // 2, index % 2) if grid_mode else layout
            widgets.append(QWidget(backend.add_group(parent=parent.tag), parent=parent, backend=backend))
        started = time.perf_counter()
        assert layout.clear(delete=False) == count
        elapsed = time.perf_counter() - started
        assert layout.count() == 0
        assert all(widget.parent is root and not widget._deleted for widget in widgets)
        print('{} nodes={} seconds={:.4f}'.format(
            'GRID_DETACH' if grid_mode else 'BOX_DETACH', count, elapsed), flush=True)
    finally:
        root.delete()


if __name__ == '__main__':
    adapter_tree()
    detach_layout(False)
    detach_layout(True)
