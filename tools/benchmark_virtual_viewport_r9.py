"""Reproducible *headless* virtual-table and indexed-navigation benchmark.

Run from the repository root with: python tools/benchmark_virtual_viewport_r9.py
No Windows-native DPG, frame timings, scrolling or GUI runtime are measured.
"""
from statistics import median
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from time import perf_counter

from DearUIQt.modelview import QTableView, QtGridRow, QtItemViewState, ReadOnlyTableViewport
from tests.test_dearuiqt_modelview_r79 import FakeBackend


def sample(call, repeat=5):
    times = []
    for _ in range(repeat):
        start = perf_counter()
        call()
        times.append((perf_counter()-start)*1000)
    return round(median(times), 3)


def main():
    count = 100_000
    keys = list(range(count))
    state = QtItemViewState().replace(keys)
    state.current = count - 2500
    def old_scan():
        for _ in range(2000):
            keys.index(count-2500)
    def indexed():
        for _ in range(2000):
            state._key_index[state.current]
    print('2000 deep-row position lookups, ms:')
    print('  linear list.index (r8-equivalent):', sample(old_scan))
    print('  indexed dictionary (r9):       ', sample(indexed))
    backend = FakeBackend()
    view = QTableView(columns=['Name'], backend=backend)
    source = [QtGridRow(i, (str(i),)) for i in keys]
    pilot = ReadOnlyTableViewport(view, source, row_height=24, overscan=8)
    first = pilot.render(0, 480)
    middle = pilot.render(1_200_000, 480)
    print('  total logical rows:             ', len(source))
    print('  first window native rows:       ', first.materialized_rows)
    print('  middle window native rows:      ', middle.materialized_rows)
    print('  native rows after move:         ', len(view._row_tags))
    pilot.detach()
    view.delete()


if __name__ == '__main__':
    main()
