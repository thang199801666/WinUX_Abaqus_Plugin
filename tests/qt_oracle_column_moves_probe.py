"""Cross-parent column moves, ancestor shifts and descendant identities."""
import argparse
import json
import random
from pathlib import Path
import sys


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--engine', choices=('qt', 'dearuiqt'), required=True)
    parser.add_argument('--root', default='.')
    args = parser.parse_args()
    if args.engine == 'qt':
        from PySide6.QtCore import QAbstractItemModel, QModelIndex, QPersistentModelIndex, QItemSelectionModel, QItemSelection, qVersion
        version = qVersion()
    else:
        sys.path.insert(0, str(Path(args.root).resolve()))
        from DearUIQt.QtCore import QAbstractItemModel, QModelIndex, QPersistentModelIndex, QItemSelectionModel, QItemSelection
        version = 'Qt-6.8-subset'
    try:
        factory = make_matrix_model
    except NameError:
        from qt_move_matrix_fixture import make_matrix_model as factory
    model = factory(QAbstractItemModel, QModelIndex)()
    flags = getattr(QItemSelectionModel, 'SelectionFlag', QItemSelectionModel)
    selection = QItemSelectionModel(model)
    a = model.indexForCell(model.a)
    selection.select(QItemSelection(model.index(0, 0, a), model.index(1, 2, a)), flags.ClearAndSelect)
    selection.setCurrentIndex(model.indexForCell(model.branch), flags.NoUpdate)
    watched = [QPersistentModelIndex(model.indexForCell(cell)) for cell in
               (model.a, model.b, model.c, model.branch, model.grandchild, model.a.grid[0][0], model.b.grid[1][2])]
    trace, events = [], []

    def key(index):
        path = []
        while index.isValid():
            path.append([index.row(), index.column()])
            index = index.parent()
        return path[::-1] if path else None

    def state():
        return {'current': key(selection.currentIndex()), 'current_data': selection.currentIndex().data(),
                'selected': sorted((key(index) for index in selection.selectedIndexes()), key=lambda value: json.dumps(value)),
                'persistent': [[key(index), index.data()] for index in watched], 'contents': model.contents()}

    for name in ('columnsAboutToBeMoved', 'columnsMoved'):
        getattr(model, name).connect(lambda source, first, last, target, destination, name=name: events.append({
            'signal': name, 'source': key(source), 'first': first, 'last': last,
            'target': key(target), 'destination': destination, 'state': state()}))
    selection.currentChanged.connect(lambda *args: events.append({'signal': 'current'}))
    selection.selectionChanged.connect(lambda added, removed: events.append({
        'signal': 'selection', 'added': sorted((key(index) for index in added.indexes()), key=lambda value: json.dumps(value)),
        'removed': sorted((key(index) for index in removed.indexes()), key=lambda value: json.dumps(value))}))

    def record(name, action):
        events.clear()
        result = action()
        trace.append({'name': name, 'result': result, 'state': state(), 'events': list(events)})

    def index(cell):
        return model.indexForCell(cell)
    root = QModelIndex()
    record('transfer-column-block-with-descendants', lambda: model.moveColumns(index(model.a), 1, 2, index(model.b), 1))
    record('transfer-back-to-source-front', lambda: model.moveColumn(index(model.b), 1, index(model.a), 0))
    record('root-column-under-shifting-target', lambda: model.moveColumn(root, 0, index(model.c), 1))
    record('reject-move-parent-under-self', lambda: model.moveColumn(root, 1, index(model.c), 0))
    record('child-column-before-shifting-source-parent', lambda: model.moveColumn(index(model.c), 1, root, 0))
    rng = random.Random(68081)
    for number in range(100):
        source, target = (model.a, model.b) if rng.randrange(2) else (model.b, model.a)
        available = model.columnCount(index(source))
        if available == 0:
            source, target = target, source
            available = model.columnCount(index(source))
        first = rng.randrange(available)
        count = rng.randrange(1, available - first + 1)
        destination = rng.randrange(model.columnCount(index(target)) + 1)
        record('seed-%03d' % number, lambda source=source, target=target, first=first, count=count, destination=destination:
               model.moveColumns(index(source), first, count, index(target), destination))
    print('QT_ORACLE_JSON:' + json.dumps({'version': version, 'trace': trace, 'ranges': {}}, sort_keys=True))


if __name__ == '__main__':
    main()
