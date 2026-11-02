"""QItemSelection.select preserves ordered handles; only reversed corners reindex."""
import argparse
import json
from pathlib import Path
import sys


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--engine', choices=('qt', 'dearuiqt'), required=True)
    parser.add_argument('--root', default='.')
    args = parser.parse_args()
    if args.engine == 'qt':
        from PySide6.QtCore import QAbstractTableModel, QModelIndex, QItemSelection, qVersion
        version = qVersion()
    else:
        sys.path.insert(0, str(Path(args.root).resolve()))
        from DearUIQt.QtCore import QAbstractTableModel, QModelIndex, QItemSelection
        version = 'Qt-6.8-subset'

    class Model(QAbstractTableModel):
        def __init__(self):
            super().__init__()
            self.tokens = [object(), object()]
            self.phase = 0
            self.calls = 0
        def rowCount(self, parent=QModelIndex()):
            return 0 if parent.isValid() else 4
        def columnCount(self, parent=QModelIndex()):
            return 0 if parent.isValid() else 4
        def index(self, row, column, parent=QModelIndex()):
            self.calls += 1
            return (self.createIndex(row, column, self.tokens[self.phase])
                    if not parent.isValid() and 0 <= row < 4 and 0 <= column < 4 else QModelIndex())

    trace = []
    model = Model()
    for phase in (0, 1):
        for name, corners in (('singleton', (1, 1, 1, 1)), ('ordered', (0, 1, 3, 2)),
                              ('reverse-rows', (3, 1, 0, 2)), ('reverse-columns', (0, 2, 3, 1)),
                              ('reverse-both', (3, 2, 0, 1))):
            model.phase = 0
            a, b = model.index(*corners[:2]), model.index(*corners[2:])
            model.phase, model.calls = phase, 0
            selection = QItemSelection()
            selection.select(a, b)
            area = selection[0]
            trace.append({'name': '%s-phase%d' % (name, phase), 'calls': model.calls,
                          'corners': [area.top(), area.left(), area.bottom(), area.right()],
                          'original_top': area.topLeft() == a, 'original_bottom': area.bottomRight() == b})
    print('QT_ORACLE_JSON:' + json.dumps({'version': version, 'trace': trace, 'ranges': []}))


if __name__ == '__main__':
    main()
