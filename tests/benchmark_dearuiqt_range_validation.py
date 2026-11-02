"""Singleton range validation: retained full check vs same-handle shortcut."""
import argparse
from contextlib import nullcontext
from pathlib import Path
import statistics
import sys
import time
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from DearUIQt.QtCore import QItemSelection, QItemSelectionRange, QItemSelectionModel
from benchmark_dearuiqt_selection_expansion import Grid, measure


def full_validity(self):
    """Pre-S6 validity check, including repeated parent queries for one handle."""
    return (self._top_left.isValid() and self._bottom_right.isValid() and
            self.model() is self._bottom_right.model() and
            self.parent() == self._bottom_right.parent() and
            self.top() <= self.bottom() and self.left() <= self.right())


def enumerate_payload(selection, expected):
    started = time.perf_counter()
    result = selection.indexes()
    elapsed = (time.perf_counter() - started) * 1000
    assert result == expected
    return elapsed


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--rows', type=int, default=5000)
    parser.add_argument('--columns', type=int, default=8)
    parser.add_argument('--repeat', type=int, default=5)
    parser.add_argument('--mode', choices=('payload', 'bulk-select'), default='payload')
    parser.add_argument('--shape', choices=('singletons', 'rectangle'), default='singletons')
    args = parser.parse_args()
    if min(args.rows, args.columns, args.repeat) < 1:
        parser.error('rows/columns/repeat must be positive')
    if args.mode == 'bulk-select' and args.shape != 'singletons':
        parser.error('--shape is only configurable in payload mode')
    model = Grid(args.rows, args.columns)
    try:
        indexes = [model.index(row, column) for row in range(args.rows) for column in range(args.columns)]
        payload = (QItemSelection(QItemSelectionRange(index) for index in indexes) if args.shape == 'singletons' else
                   QItemSelection(indexes[0], indexes[-1]))
        inputs = [model.index(row, 0) for row in range(args.rows)]
        samples = {True: [], False: []}
        for _ in range(args.repeat):
            for reference in samples:
                context = patch.object(QItemSelectionRange, 'isValid', full_validity) if reference else nullcontext()
                with context:
                    elapsed = (enumerate_payload(payload, indexes) if args.mode == 'payload' else
                               measure(model, QItemSelectionModel, inputs, 'rows', args.rows))
                    samples[reference].append(elapsed)
        reference, current = (statistics.median(samples[key]) for key in (True, False))
        label = args.mode + ('/' + args.shape if args.mode == 'payload' else '')
        print('%d x %d cells, %s, median of %d:' % (args.rows, args.columns, label, args.repeat))
        print('full-validity reference %.3f ms; current %.3f ms; ratio %.2fx' % (reference, current, reference / current))
        print('PASS: exact row-major payload order (payload), coverage/range count and immediate signal (bulk-select).')
        print('Python only; setup/validation excluded. Bulk includes signal enumeration/final commit. No renderer/FPS claim.')
    finally:
        model.delete()


if __name__ == '__main__':
    main()
