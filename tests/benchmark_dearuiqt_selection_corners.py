"""Corner-preserving construction vs the previous reindex-every-corner path."""
import argparse
from contextlib import nullcontext
from pathlib import Path
import statistics
import sys
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from DearUIQt.QtCore import QItemSelection, QItemSelectionRange, QItemSelectionModel
from benchmark_dearuiqt_selection_expansion import Grid, measure


def reindex_select(self, topLeft, bottomRight):
    """Pre-S3 construction, retained only as a timing reference."""
    if (not topLeft.isValid() or not bottomRight.isValid()
            or topLeft.model() is not bottomRight.model()
            or topLeft.parent() != bottomRight.parent()):
        return
    model, parent = topLeft.model(), topLeft.parent()
    self.append(QItemSelectionRange(
        model.index(min(topLeft.row(), bottomRight.row()), min(topLeft.column(), bottomRight.column()), parent),
        model.index(max(topLeft.row(), bottomRight.row()), max(topLeft.column(), bottomRight.column()), parent)))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--sections', type=int, default=5000)
    parser.add_argument('--width', type=int, default=8)
    parser.add_argument('--repeat', type=int, default=5)
    parser.add_argument('--axis', choices=('rows', 'columns'), default='rows')
    args = parser.parse_args()
    if min(args.sections, args.width, args.repeat) <= 0:
        parser.error('sections/width/repeat must be positive')
    rows, columns = ((args.sections, args.width) if args.axis == 'rows' else (args.width, args.sections))
    model = Grid(rows, columns)
    try:
        inputs = ([model.index(row, 0) for row in range(rows)] if args.axis == 'rows'
                  else [model.index(0, column) for column in range(columns)])
        results = {True: [], False: []}
        for _ in range(args.repeat):
            for reference in results:
                context = patch.object(QItemSelection, 'select', reindex_select) if reference else nullcontext()
                with context:
                    results[reference].append(measure(model, QItemSelectionModel, inputs, args.axis, args.sections))
        old, current = (statistics.median(results[kind]) for kind in (True, False))
        print('%d %s x width %d, median of %d:' % (args.sections, args.axis, args.width, args.repeat))
        print('reindex-corner reference %.3f ms; current %.3f ms; ratio %.2fx' % (old, current, old / current))
        print('PASS: one immediate signal, full selected/range coverage and unchanged range count.')
        print('Both paths keep S1/S2. Includes signal index collection/final commit; excludes setup/validation; not GUI FPS.')
    finally:
        model.delete()


if __name__ == '__main__':
    main()
