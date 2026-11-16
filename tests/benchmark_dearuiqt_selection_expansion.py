"""Single-axis bulk selection expansion; full-reference vs candidate bookkeeping."""
import argparse
from pathlib import Path
import statistics
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from DearUIQt.QtCore import QAbstractTableModel, QItemSelectionModel


class FullExpansionSelectionModel(QItemSelectionModel):
    def _expand_selection_ranges(self, areas, command):
        return self._merge_expanded_ranges(areas, command)

    def _expand_selection_indexes(self, indexes, command):
        return self._expand_selection_indexes_full(indexes, command)


class Grid(QAbstractTableModel):
    def __init__(self, rows, columns):
        super().__init__()
        self.rows, self.columns = rows, columns

    def rowCount(self, parent=None):
        return 0 if parent is not None and parent.isValid() else self.rows

    def columnCount(self, parent=None):
        return 0 if parent is not None and parent.isValid() else self.columns


def measure(model, kind, inputs, axis, expected_ranges):
    selection = kind(model)
    try:
        events = []
        selection.selectionChanged.connect(lambda added, removed: events.append((added.indexes(), removed.indexes())))
        command = selection.ClearAndSelect | (selection.Rows if axis == 'rows' else selection.Columns)
        started = time.perf_counter()
        selection.select(inputs, command)
        selection.select([], selection.Select)
        elapsed = (time.perf_counter() - started) * 1000
        expected = {model.index(row, col) for row in range(model.rows) for col in range(model.columns)}
        assert len(events) == 1 and set(events[0][0]) == expected and events[0][1] == []
        assert set(selection.selectedIndexes()) == expected
        assert set(selection._committed_ranges._indexes()) == expected
        assert len(selection._committed_ranges) == expected_ranges
        return elapsed
    finally:
        selection.delete()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--sections', type=int, default=500)
    parser.add_argument('--width', type=int, default=8)
    parser.add_argument('--axis', choices=('rows', 'columns'), default='rows')
    parser.add_argument('--repeat', type=int, default=3)
    parser.add_argument('--all-cells', action='store_true')
    parser.add_argument('--current-only', action='store_true')
    options = parser.parse_args()
    if min(options.sections, options.width, options.repeat) <= 0:
        parser.error('sections/width/repeat must be positive')
    rows, columns = ((options.sections, options.width) if options.axis == 'rows'
                     else (options.width, options.sections))
    model = Grid(rows, columns)
    try:
        if options.all_cells:
            inputs = [model.index(row, col) for row in range(rows) for col in range(columns)]
        else:
            inputs = ([model.index(row, 0) for row in range(rows)] if options.axis == 'rows'
                      else [model.index(0, col) for col in range(columns)])
        kinds = [QItemSelectionModel] if options.current_only else [FullExpansionSelectionModel, QItemSelectionModel]
        results = {kind: [] for kind in kinds}
        for _ in range(options.repeat):
            for kind in kinds:
                results[kind].append(measure(model, kind, inputs, options.axis, options.sections))
        current = statistics.median(results[QItemSelectionModel])
        print('%d %s x width %d; %d input indexes; median of %d:' %
              (options.sections, options.axis, options.width, len(inputs), options.repeat))
        if options.current_only:
            print('current %.3f ms (reference not measured at this scale)' % current)
        else:
            reference = statistics.median(results[FullExpansionSelectionModel])
            print('full expansion %.3f ms; current %.3f ms; ratio %.2fx' % (reference, current, reference / current))
        print('PASS: one immediate signal, identical coverage and expanded range count.')
        print('Python-only; includes delta construction/collection and final commit, excludes setup/final validation; not GUI FPS.')
    finally:
        model.delete()


if __name__ == '__main__':
    main()
