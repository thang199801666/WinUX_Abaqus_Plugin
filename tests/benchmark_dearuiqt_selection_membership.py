"""Bulk membership/delta application with the preceding per-index reference."""
import argparse
from pathlib import Path
import statistics
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from DearUIQt.QtCore import QItemSelection, QItemSelectionModel
from benchmark_dearuiqt_selection_expansion import Grid


class PerIndexSelectionModel(QItemSelectionModel):
    def _apply_selection_indexes(self, indexes, selects, deselect, toggle):
        touched = {}
        for index in indexes:
            if selects or deselect or toggle:
                touched.setdefault(index, index in self._selected)
            if deselect:
                self._selected.discard(index)
            elif toggle:
                if index in self._selected:
                    self._selected.remove(index)
                else:
                    self._selected.add(index)
            elif selects:
                self._selected.add(index)
        return ({index for index, was_selected in touched.items()
                 if not was_selected and index in self._selected},
                {index for index, was_selected in touched.items()
                 if was_selected and index not in self._selected})


def measure(model, kind, area, expected, operation, collect):
    selection = kind(model)
    try:
        selection.select(area, selection.Select)
        selection.select([], selection.Select)
        events = []
        def changed(added, removed):
            events.append((added.indexes(), removed.indexes()) if collect else (len(added), len(removed)))
        selection.selectionChanged.connect(changed)
        command = {'select': selection.Select, 'deselect': selection.Deselect, 'toggle': selection.Toggle}[operation]
        started = time.perf_counter()
        selection.select(area, command)
        elapsed = (time.perf_counter() - started) * 1000
        if operation == 'select':
            assert selection._selected == expected and events == []
            assert selection._interactive_added == selection._interactive_removed == set()
        else:
            assert selection._selected == set() and len(events) == 1
            assert selection._interactive_removed == expected and selection._interactive_added == set()
            payload = (([], sorted(expected, key=lambda index: (index.row(), index.column())))
                       if collect else (0, len(expected)))
            assert events[0] == payload
        return elapsed
    finally:
        selection.delete()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--rows', type=int, default=5000)
    parser.add_argument('--columns', type=int, default=8)
    parser.add_argument('--repeat', type=int, default=5)
    parser.add_argument('--operation', choices=('select', 'deselect', 'toggle'), default='select')
    parser.add_argument('--collect-indexes', action='store_true')
    args = parser.parse_args()
    if min(args.rows, args.columns, args.repeat) < 1:
        parser.error('rows/columns/repeat must be positive')
    model = Grid(args.rows, args.columns)
    try:
        area = QItemSelection(model.index(0, 0), model.index(args.rows - 1, args.columns - 1))
        expected = set(area._indexes())
        kinds = (PerIndexSelectionModel, QItemSelectionModel)
        samples = {kind: [] for kind in kinds}
        for _ in range(args.repeat):
            for kind in kinds:
                samples[kind].append(measure(model, kind, area, expected, args.operation, args.collect_indexes))
        reference, current = (statistics.median(samples[kind]) for kind in kinds)
        print('%d x %d cells, %s over fully selected rectangle, median of %d:' %
              (args.rows, args.columns, args.operation, args.repeat))
        print('per-index reference %.3f ms; current %.3f ms; ratio %.2fx' % (reference, current, reference / current))
        print('PASS: exact membership, interactive delta and immediate signal payload/order.')
        print('Python select() only; setup/validation excluded; signal index collection %s; no renderer/FPS claim.' %
              ('included' if args.collect_indexes else 'excluded (range counts only)'))
    finally:
        model.delete()


if __name__ == '__main__':
    main()
