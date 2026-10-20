"""Headless renderer-operation benchmark for repeated checked-state updates.

Run from the project root with `python tools/benchmark_view_check_refresh.py`.
This intentionally uses the project's test backend, not real Windows timings.
"""
from __future__ import annotations

from statistics import median
from time import perf_counter

from DearUIQt.modelview import QListView
from DearUIQt.modelview.models import QtListItem
from tests.test_dearuiqt_inplace_rows_r5 import TrackingBackend


def run(rows=1000, updates=10, repeats=5):
    import DearUIQt.modelview.list as list_module

    list_module.qt_item_row_theme = lambda *_a, **_kw: 'test-row'
    list_module.qt_check_list_row_theme = lambda *_a, **_kw: 'test-check'
    list_module.qt_list_view_theme = lambda *_a, **_kw: 'test-view'
    timings = []
    last_counters = None
    for _ in range(repeats):
        backend = TrackingBackend()
        view = QListView(backend=backend)
        original = [QtListItem(index, f'Item {index}', checked=False)
                    for index in range(rows)]
        view.setItems(original)
        previous_adds, previous_deletes = backend.adds, backend.deletes
        previous_writes = backend.value_writes
        started = perf_counter()
        for update in range(updates):
            changed = list(original)
            index = update % rows
            changed[index] = QtListItem(index, f'Item {index}', checked=True)
            view.setItems(changed)
        timings.append((perf_counter() - started) * 1000)
        last_counters = {
            'selectable_creations': backend.adds - previous_adds,
            'delete_calls': backend.deletes - previous_deletes,
            'value_writes': backend.value_writes - previous_writes,
        }
        view.delete()
    return median(timings), last_counters


if __name__ == '__main__':
    elapsed, operations = run()
    print(f'Headless 1,000-row checklist, 10 updates: {elapsed:.2f} ms median')
    print('Operations:', operations)
    print('Not a Windows-native performance measurement.')
