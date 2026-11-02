"""Boolean range intersections across geometry, validity, models and parents."""
import argparse
import json
from pathlib import Path
import random
import sys


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--engine', choices=('qt', 'dearuiqt'), required=True)
    parser.add_argument('--root', default='.')
    args = parser.parse_args()
    if args.engine == 'qt':
        from PySide6.QtCore import QItemSelectionRange, QModelIndex, qVersion
        from PySide6.QtGui import QStandardItemModel, QStandardItem
        version = qVersion()
    else:
        sys.path.insert(0, str(Path(args.root).resolve()))
        from DearUIQt.QtCore import QItemSelectionRange, QModelIndex
        from DearUIQt.QtGui import QStandardItemModel, QStandardItem
        version = 'Qt-6.8-subset'
    model, other = QStandardItemModel(4, 4), QStandardItemModel(4, 4)
    for row in (0, 1):
        item = QStandardItem('parent%d' % row)
        for child in range(3):
            item.appendRow([QStandardItem('%d:%d' % (child, column)) for column in range(3)])
        model.setItem(row, 0, item)
    ranges = [QItemSelectionRange(), QItemSelectionRange(model.index(0, 0)),
              QItemSelectionRange(model.index(0, 0), model.index(2, 2)),
              QItemSelectionRange(model.index(1, 1), model.index(3, 3)),
              QItemSelectionRange(model.index(3, 3)),
              QItemSelectionRange(model.index(3, 0), model.index(0, 3)),
              QItemSelectionRange(model.index(0, 3), model.index(3, 0)),
              QItemSelectionRange(other.index(0, 0), other.index(2, 2)),
              QItemSelectionRange(model.index(0, 0, model.index(0, 0)), model.index(2, 2, model.index(0, 0))),
              QItemSelectionRange(model.index(0, 0, model.index(1, 0)), model.index(2, 2, model.index(1, 0))),
              QItemSelectionRange(model.index(0, 0), QModelIndex())]
    trace = []
    def snapshot(name, a, b):
        trace.append({'name': name, 'valid': [a.isValid(), b.isValid()],
                      'intersects': a.intersects(b), 'reverse': b.intersects(a)})
    for i, a in enumerate(ranges):
        for j, b in enumerate(ranges):
            snapshot('%d-%d' % (i, j), a, b)
    rng = random.Random(68171)
    parents = [QModelIndex(), model.index(0, 0), model.index(1, 0)]
    for step in range(100):
        pair = []
        for _ in range(2):
            parent = rng.choice(parents)
            pair.append(QItemSelectionRange(model.index(rng.randrange(3), rng.randrange(3), parent),
                                            model.index(rng.randrange(3), rng.randrange(3), parent)))
        snapshot('seeded-%d' % step, *pair)
    print('QT_ORACLE_JSON:' + json.dumps({'version': version, 'trace': trace, 'ranges': []}))


if __name__ == '__main__':
    main()
