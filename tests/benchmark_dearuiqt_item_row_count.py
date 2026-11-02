"""Batched item resize API vs an explicit one-row-at-a-time workaround."""
import argparse
from pathlib import Path
import statistics
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from DearUIQt.QtGui import QStandardItem, QStandardItemModel


def resize_one_row_at_a_time(model, item, target):
    parent = item.index()
    while item.rowCount() < target:
        changed = model.insertRows(item.rowCount(), 1, parent)
        assert changed
    while item.rowCount() > target:
        changed = model.removeRows(item.rowCount() - 1, 1, parent)
        assert changed


def measure(rows, columns, operation, batched):
    model = QStandardItemModel(1, 1)
    try:
        item = QStandardItem('parent')
        item.setColumnCount(columns)
        model.setItem(0, 0, item)
        if operation == 'shrink':
            item.setRowCount(rows)
        target = rows if operation == 'grow' else 0
        events = []
        prefix = 'Inserted' if operation == 'grow' else 'Removed'
        for name in ('rowsAboutToBe' + prefix, 'rows' + prefix):
            getattr(model, name).connect(lambda parent, first, last, name=name: events.append(
                (name, first, last, item.rowCount())))
        started = time.perf_counter()
        if batched:
            item.setRowCount(target)
        else:
            resize_one_row_at_a_time(model, item, target)
        elapsed = (time.perf_counter() - started) * 1000
        assert (item.rowCount(), item.columnCount()) == (target, columns)
        assert all(item.child(row, column) is None for row in range(target) for column in range(columns))
        assert len(events) == (2 if batched else 2 * rows)
        if batched:
            before = 0 if operation == 'grow' else rows
            assert events == [('rowsAboutToBe' + prefix, 0, rows - 1, before),
                              ('rows' + prefix, 0, rows - 1, target)]
        return elapsed, len(events)
    finally:
        model.delete()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--rows', type=int, default=2000)
    parser.add_argument('--columns', type=int, default=4)
    parser.add_argument('--repeat', type=int, default=5)
    parser.add_argument('--operation', choices=('grow', 'shrink'), default='grow')
    args = parser.parse_args()
    if args.rows < 1 or args.columns < 0 or args.repeat < 1:
        parser.error('rows/repeat must be positive and columns nonnegative')
    samples = {False: [], True: []}
    for _ in range(args.repeat):
        for batched in samples:
            elapsed, events = measure(args.rows, args.columns, args.operation, batched)
            samples[batched].append(elapsed)
    reference, current = (statistics.median(samples[key]) for key in (False, True))
    print('%s %d item-owned rows x %d columns, median of %d:' %
          (args.operation, args.rows, args.columns, args.repeat))
    print('one-row workaround %.3f ms; setRowCount %.3f ms; ratio %.2fx' % (reference, current, reference / current))
    print('PASS: same final dimensions/lazy cells; notifications %d -> 2.' % (2 * args.rows))
    print('API batching comparison, NOT identical signal history or an old setRowCount implementation.')
    print('Python transactions/lightweight observers only; setup/validation excluded; no GUI/FPS or Qt-native claim.')


if __name__ == '__main__':
    main()
