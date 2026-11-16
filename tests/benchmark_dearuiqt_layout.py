"""Library-only layout inspection benchmark, no renderer or WinUx application."""
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'vendor'))
sys.path.insert(0, str(ROOT))
from DearUIQt.layouts import QVBoxLayout, QGridLayout
from DearUIQt.widgets import QWidget


class Backend:
    mvTable_SizingStretchProp = 0

    def __init__(self):
        self.parents = {}

    def add_group(self, **options):
        tag = len(self.parents) + 1
        self.parents[tag] = options.get('parent')
        return tag

    add_table = add_table_row = add_table_column = add_group

    def get_item_parent(self, tag):
        return self.parents.get(tag)

    def get_item_configuration(self, tag):
        return {}

    def does_item_exist(self, tag):
        return tag in self.parents

    def move_item(self, tag, *, parent, **options):
        self.parents[tag] = parent

    def delete_item(self, tag):
        self.parents.pop(tag, None)


def measure(layout, name):
    count = layout.count()
    started = time.perf_counter()
    for _ in range(3):
        for index in range(count):
            assert layout.itemAt(index) is not None
    elapsed = time.perf_counter() - started
    print('{} items={} full_walks=3 seconds={:.4f}'.format(name, count, elapsed), flush=True)


def main():
    backend = Backend()
    box = QVBoxLayout(backend=backend)
    for _ in range(3000):
        QWidget(backend.add_group(parent=box.tag), parent=box, backend=backend)
    measure(box, 'BOX')
    grid = QGridLayout(2, backend=backend)
    for row in range(500):
        for column in range(2):
            cell = grid.cell(row, column)
            QWidget(backend.add_group(parent=cell.tag), parent=cell, backend=backend)
    measure(grid, 'GRID')
    box.delete()
    grid.delete()


if __name__ == '__main__':
    main()
