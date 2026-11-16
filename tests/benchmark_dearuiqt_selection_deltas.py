"""Core-only direct-selection delta cost; no native renderer or WinUx."""
from pathlib import Path
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_dearuiqt_selection_deltas import Model, QItemSelectionModel, legacy_select
from DearUIQt.core import QItemSelection


class LargeModel(Model):
    def rowCount(self, parent=None): return 40000


def previous_select(selection, index):
    added, removed = legacy_select(selection, [index], selection.Select)
    if added or removed:
        selected, deselected = QItemSelection(), QItemSelection()
        for value in sorted(added, key=lambda item: (item.row(), item.column())):
            selected.select(value, value)
        for value in sorted(removed, key=lambda item: (item.row(), item.column())):
            deselected.select(value, value)
        selection.selectionChanged.emit(selected, deselected)


def main():
    model = LargeModel()
    seed = [model.index(row, 0) for row in range(30000)]
    additions = [model.index(row, 0) for row in range(30000, 31000)]
    results = []
    for optimized in (False, True):
        selection = QItemSelectionModel(model)
        try:
            selection.select(seed, selection.Select)
            notifications = [0]
            def changed(*args): notifications[0] += 1
            selection.selectionChanged.connect(changed)
            started = time.perf_counter()
            for index in additions:
                if optimized:
                    selection.select(index, selection.Select)
                else:
                    previous_select(selection, index)
            results.append((time.perf_counter() - started) * 1000)
            assert len(selection.selectedIndexes()) == 31000
            assert notifications[0] == 1000
        finally:
            selection.delete()
    print('30,000 selected indexes + 1,000 direct additions: %.2f -> %.2f ms' % tuple(results))
    print('Both paths retain 1,000 immediate delta notifications; only selection bookkeeping changes.')
    print('Python-only timing; no native rendering or application observer work.')


if __name__ == '__main__':
    main()
