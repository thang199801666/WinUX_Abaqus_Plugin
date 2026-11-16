"""Bulk full-row/column query cost with a live Deselect/Toggle layer."""
import argparse
from pathlib import Path
import statistics
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from DearUIQt.QtCore import QItemSelection, QItemSelectionModel
from benchmark_dearuiqt_selection_expansion import Grid


class RepeatedScanSelectionModel(QItemSelectionModel):
    """Pre-S4 query: scan live blockers separately for every candidate section."""
    def _selected_sections(self, anchor, rows):
        if self._model is None:
            return []
        candidates = dict.fromkeys((index.parent(), index.row() if rows else index.column())
                                   for index in self.selectedIndexes())
        result = []
        for parent, section in candidates:
            if self._section_selected(section, parent, rows):
                result.append(self._model.index(section, anchor, parent) if rows else
                              self._model.index(anchor, section, parent))
        return result


def measure(model, kind, axis, operation):
    selection = kind(model)
    try:
        selection.select(QItemSelection(model.index(0, 0), model.index(model.rows - 1, model.columns - 1)),
                         selection.Select)
        selection.select([], selection.Select)
        rows = axis == 'rows'
        sections = model.rows if rows else model.columns
        inputs = [model.index(section, 0) if rows else model.index(0, section)
                  for section in range(0, sections, 2)]
        if operation == 'select':
            inputs = []
        command = {'select': selection.Select, 'deselect': selection.Deselect, 'toggle': selection.Toggle}[operation]
        selection.select(inputs, command | selection.Current)
        events = []
        selection.selectionChanged.connect(lambda *args: events.append(args))
        started = time.perf_counter()
        result = selection.selectedRows() if rows else selection.selectedColumns()
        elapsed = (time.perf_counter() - started) * 1000
        expected = [model.index(section, 0) if rows else model.index(0, section)
                    for section in (range(sections) if operation == 'select' else range(1, sections, 2))]
        assert result == expected and events == []
        return elapsed
    finally:
        selection.delete()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--sections', type=int, default=2000)
    parser.add_argument('--width', type=int, default=8)
    parser.add_argument('--repeat', type=int, default=5)
    parser.add_argument('--axis', choices=('rows', 'columns'), default='rows')
    parser.add_argument('--operation', choices=('select', 'deselect', 'toggle'), default='deselect')
    parser.add_argument('--current-only', action='store_true')
    args = parser.parse_args()
    if args.sections < 2 or args.width < 2 or args.repeat < 1:
        parser.error('sections/width must be >= 2 and repeat >= 1')
    dimensions = (args.sections, args.width) if args.axis == 'rows' else (args.width, args.sections)
    model = Grid(*dimensions)
    try:
        kinds = [QItemSelectionModel] if args.current_only else [RepeatedScanSelectionModel, QItemSelectionModel]
        results = {kind: [] for kind in kinds}
        for _ in range(args.repeat):
            for kind in kinds:
                results[kind].append(measure(model, kind, args.axis, args.operation))
        current = statistics.median(results[QItemSelectionModel])
        operation = ('select, no live blockers' if args.operation == 'select' else
                     args.operation + ' on one cell in every even section')
        print('%d %s x width %d, %s; median of %d:' %
              (args.sections, args.axis, args.width, operation, args.repeat))
        if args.current_only:
            print('current %.3f ms (reference not measured at this scale)' % current)
        else:
            reference = statistics.median(results[RepeatedScanSelectionModel])
            print('repeated-scan reference %.3f ms; current %.3f ms; ratio %.2fx' %
                  (reference, current, reference / current))
        print('PASS: exact full-section query result/order; no query signals.')
        print('Python query only; selection setup and validation excluded; no renderer/FPS claim.')
    finally:
        model.delete()


if __name__ == '__main__':
    main()
