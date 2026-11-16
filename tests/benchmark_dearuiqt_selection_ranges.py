"""Qt-compatible range commit cost, same range/state/signal validation per path."""
import argparse
from pathlib import Path
import statistics
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from DearUIQt.QtCore import QAbstractListModel, QItemSelectionModel


class FullMergeSelectionModel(QItemSelectionModel):
    """Reference: commit every live range through the pre-optimization merge."""
    def _commit_live_ranges(self):
        self._committed_ranges.merge(self._live_ranges, self._live_command)
        self._live_ranges.clear()
        self._live_command = self.NoUpdate
        self._live_disjoint = False


class Rows(QAbstractListModel):
    def __init__(self, count):
        super().__init__()
        self.count = count
    def rowCount(self, parent=None):
        return 0 if parent is not None and parent.isValid() else self.count


def measure(model, selection_type, seed, additions):
    selection = selection_type(model)
    try:
        selection.select(seed, selection.Select)
        selection.select([], selection.Select)  # Commit seed outside timed work.
        events = []
        selection.selectionChanged.connect(lambda added, removed: events.append(
            ([(index.row(), index.column()) for index in added.indexes()], removed.indexes())))
        started = time.perf_counter()
        for index in additions:
            selection.select(index, selection.Select)
        selection.select([], selection.Select)  # Include committing final add.
        elapsed = (time.perf_counter() - started) * 1000
        assert events == [([(index.row(), index.column())], []) for index in additions]
        assert set(selection.selectedIndexes()) == set(seed + additions)
        assert set(selection._committed_ranges._indexes()) == set(seed + additions)
        assert len(selection._committed_ranges) == len(seed) + len(additions)
        return elapsed
    finally:
        selection.delete()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--seed', type=int, default=2000)
    parser.add_argument('--adds', type=int, default=100)
    parser.add_argument('--repeat', type=int, default=3)
    parser.add_argument('--current-only', action='store_true', help='Skip the expensive reference for scaling runs')
    options = parser.parse_args()
    if min(options.seed, options.adds, options.repeat) <= 0:
        parser.error('seed/adds/repeat must be positive')
    model = Rows(options.seed + options.adds + 10)
    try:
        seed = [model.index(row) for row in range(options.seed)]
        additions = [model.index(row) for row in range(options.seed, options.seed + options.adds)]
        results = ({QItemSelectionModel: []} if options.current_only else
                   {FullMergeSelectionModel: [], QItemSelectionModel: []})
        for _ in range(options.repeat):
            for kind in results:
                results[kind].append(measure(model, kind, seed, additions))
        candidate = statistics.median(results[QItemSelectionModel])
        print('%d seeded singleton ranges + %d disjoint additions, median of %d:' %
              (options.seed, options.adds, options.repeat))
        if options.current_only:
            print('current %.3f ms (no reference measured at this scale)' % candidate)
        else:
            reference = statistics.median(results[FullMergeSelectionModel])
            print('full-merge reference %.3f ms; current %.3f ms; ratio %.2fx' %
                  (reference, candidate, reference / candidate))
        print('PASS: identical selected coverage, singleton range shape and immediate signal payload/order.')
        print('Python bookkeeping only; no renderer, GUI FPS, Qt-native latency or whole-selection speed claim.')
    finally:
        model.delete()


if __name__ == '__main__':
    main()
