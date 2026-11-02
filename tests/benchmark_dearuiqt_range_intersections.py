"""Geometry-first rejection vs the preceding validity-first intersection test."""
import argparse
from contextlib import nullcontext
from pathlib import Path
import statistics
import sys
import time
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from DearUIQt.QtCore import QItemSelection, QItemSelectionModel, QItemSelectionRange
from benchmark_dearuiqt_selection_expansion import Grid


def validity_first(self, other):
    return (isinstance(other, QItemSelectionRange) and self.isValid() and other.isValid()
            and self.model() is other.model() and self.parent() == other.parent()
            and max(self.top(), other.top()) <= min(self.bottom(), other.bottom())
            and max(self.left(), other.left()) <= min(self.right(), other.right()))


def shape(selection):
    return [(area.topLeft(), area.bottomRight()) for area in selection]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--seed', type=int, default=1000)
    parser.add_argument('--incoming', type=int, default=100)
    parser.add_argument('--repeat', type=int, default=5)
    parser.add_argument('--operation', choices=('select', 'deselect', 'toggle'), default='toggle')
    parser.add_argument('--overlap', action='store_true', help='One overlapping incoming range; others stay disjoint')
    args = parser.parse_args()
    if min(args.seed, args.incoming, args.repeat) <= 0:
        parser.error('seed/incoming/repeat must be positive')
    model = Grid(args.seed + args.incoming + 1, 3)
    try:
        seed = QItemSelection(QItemSelectionRange(model.index(row, 0), model.index(row, 1)) for row in range(args.seed))
        incoming = QItemSelection(QItemSelectionRange(model.index(row, 0), model.index(row, 1))
                                  for row in range(args.seed, args.seed + args.incoming))
        if args.overlap:
            incoming[0] = QItemSelectionRange(model.index(args.seed // 2, 1), model.index(args.seed // 2, 2))
        command = {'select': QItemSelectionModel.Select, 'deselect': QItemSelectionModel.Deselect,
                   'toggle': QItemSelectionModel.Toggle}[args.operation]
        old, new = set(seed._indexes()), set(incoming._indexes())
        expected = old | new if args.operation == 'select' else old - new if args.operation == 'deselect' else old ^ new
        results, expected_shape = {True: [], False: []}, None
        for _ in range(args.repeat):
            for reference in results:
                selection = QItemSelection(seed)
                context = patch.object(QItemSelectionRange, 'intersects', validity_first) if reference else nullcontext()
                with context:
                    started = time.perf_counter()
                    selection.merge(incoming, command)
                    elapsed = (time.perf_counter() - started) * 1000
                assert set(selection._indexes()) == expected
                if expected_shape is None:
                    expected_shape = shape(selection)
                assert shape(selection) == expected_shape
                results[reference].append(elapsed)
        reference, current = (statistics.median(results[key]) for key in (True, False))
        print('%d seeded ranges + %d incoming, %s, %s, median of %d:' %
              (args.seed, args.incoming, args.operation, 'one overlap' if args.overlap else 'disjoint', args.repeat))
        print('validity-first reference %.3f ms; current %.3f ms; ratio %.2fx' % (reference, current, reference / current))
        print('PASS: exact range shape/order and set-operation coverage.')
        print('Python merge() only; setup/validation excluded. Pair search remains quadratic; no GUI/FPS claim.')
    finally:
        model.delete()


if __name__ == '__main__':
    main()
