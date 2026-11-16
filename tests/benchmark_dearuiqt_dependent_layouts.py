"""Microbenchmark for DearUIQt dependent layout queries (renderer-free fake backend)."""
import itertools
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'vendor'))
sys.path.insert(0, str(ROOT))

from DearUIQt.core import QSize
from DearUIQt.layouts import QVBoxLayout
from DearUIQt.widgets import QWidget


class Backend:
    def __init__(self):
        self.sequence = itertools.count(1)
        self.items = {}
    def add_group(self, **options):
        tag = next(self.sequence); self.items[tag] = dict(options); return tag
    def get_item_parent(self, tag): return self.items[tag].get('parent')
    def does_item_exist(self, tag): return tag in self.items
    def get_item_configuration(self, tag): return self.items.get(tag, {})
    def configure_item(self, tag, **options): self.items[tag].update(options)
    def move_item(self, tag, *, parent, **options): self.items[tag]['parent'] = parent
    def delete_item(self, tag): self.items.pop(tag, None)


class Responsive(QWidget):
    def __init__(self, backend, parent):
        super().__init__(backend.add_group(parent=parent.tag), parent=parent, backend=backend)
        policy = self.sizePolicy(); policy.setHeightForWidth(True); self.setSizePolicy(policy)
    def sizeHint(self): return QSize(80, 20)
    def minimumSizeHint(self): return QSize(20, 8)
    def heightForWidth(self, width): return max(8, int(width) // 8)


def main():
    backend = Backend()
    layout = QVBoxLayout(backend=backend, spacing=1)
    for _ in range(1000):
        Responsive(backend, layout)
    started = time.perf_counter()
    first = layout.heightForWidth(800)
    first_elapsed = time.perf_counter() - started
    started = time.perf_counter()
    for _ in range(20000):
        assert layout.heightForWidth(800) == first
    cached_elapsed = time.perf_counter() - started
    started = time.perf_counter()
    for i in range(100):
        layout.invalidate()
        layout.heightForWidth(800 + (i & 1))
    invalidated_elapsed = time.perf_counter() - started
    print('HFW items=1000 first_ms={:.3f} cached_20k_ms={:.3f} invalidated_100_ms={:.3f}'.format(
        first_elapsed * 1000, cached_elapsed * 1000, invalidated_elapsed * 1000))
    layout.delete()


if __name__ == '__main__':
    main()
