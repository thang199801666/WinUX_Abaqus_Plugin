"""Column count/convenience transactions including persistent/selection state."""
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
        from PySide6.QtCore import QItemSelectionModel, QItemSelection, QPersistentModelIndex, QModelIndex, qVersion
        from PySide6.QtGui import QStandardItemModel, QStandardItem
        version = qVersion()
    else:
        sys.path.insert(0, str(Path(args.root).resolve()))
        from DearUIQt.QtCore import QItemSelectionModel, QItemSelection, QPersistentModelIndex, QModelIndex
        from DearUIQt.QtGui import QStandardItemModel, QStandardItem
        version = 'Qt-6.8-subset'
    flags = getattr(QItemSelectionModel, 'SelectionFlag', QItemSelectionModel)
    model = QStandardItemModel()
    for row in range(4):
        model.appendRow([QStandardItem('%d:%d' % (row, column)) for column in range(4)])
    selection = QItemSelectionModel(model)
    watched = {'cell': QPersistentModelIndex(model.index(1, 2))}
    selection.select(QItemSelection(model.index(0, 1), model.index(2, 3)), flags.ClearAndSelect)
    selection.setCurrentIndex(model.index(1, 2), flags.NoUpdate)
    events, trace = [], []

    def key(index):
        path = []
        while index.isValid():
            path.append([index.row(), index.column()])
            index = index.parent()
        return path[::-1] if path else None

    def keys(indexes):
        return sorted((key(index) for index in indexes), key=lambda value: json.dumps(value))

    def state():
        return {'selected': keys(selection.selectedIndexes()), 'current': key(selection.currentIndex()),
                'data': selection.currentIndex().data(),
                'persistent': {name: [key(index), index.data()] for name, index in watched.items()}}

    def table(parent=QModelIndex()):
        return [[model.index(row, col, parent).data() for col in range(model.columnCount(parent))]
                for row in range(model.rowCount(parent))]

    for name in ('rowsAboutToBeInserted', 'rowsInserted', 'columnsAboutToBeInserted', 'columnsInserted',
                 'columnsAboutToBeRemoved', 'columnsRemoved'):
        getattr(model, name).connect(lambda parent, first, last, name=name: events.append({
            'signal': name, 'parent': key(parent), 'first': first, 'last': last,
            'rows': model.rowCount(parent), 'columns': model.columnCount(parent),
            'table': table(parent), 'state': state()}))
    selection.selectionChanged.connect(lambda added, removed: events.append({
        'signal': 'selection', 'added': keys(added.indexes()), 'removed': keys(removed.indexes()), 'state': state()}))
    for name in ('currentChanged', 'currentRowChanged', 'currentColumnChanged'):
        getattr(selection, name).connect(lambda current, old, name=name: events.append({
            'signal': name, 'current': key(current), 'old': key(old), 'state': state()}))

    def record(name, action):
        events.clear()
        result = action()
        trace.append({'name': name, 'result': result, 'table': table(), 'columns': model.columnCount(),
                      'state': state(), 'events': list(events)})

    record('insert-columns-before', lambda: model.insertColumns(1, 2))
    record('remove-column-before', lambda: model.removeColumns(0, 1))
    record('insert-inside-selection', lambda: model.insertColumns(4, 1))
    record('remove-inside-selection', lambda: model.removeColumns(3, 2))
    for col, count in ((-1, 1), (0, 0), (0, -1), (20, 1)):
        record('invalid-insert-%d-%d' % (col, count), lambda col=col, count=count: model.insertColumns(col, count))
        record('invalid-remove-%d-%d' % (col, count), lambda col=col, count=count: model.removeColumns(col, count))
    record('invalid-remove-overrun', lambda: model.removeColumns(0, model.columnCount() + 1))
    taken = []
    record('take-column', lambda: taken.extend(model.takeColumn(1)))
    trace.append({'name': 'taken-ownership', 'detached': [item is None or item.model() is None for item in taken]})
    # PySide's sequence binding rejects None entries, although C++ permits null
    # items. Keep the detached-ownership snapshot above, then supply real items.
    taken = [item if item is not None else QStandardItem('padded') for item in taken]
    record('reinsert-column', lambda: model.insertColumn(1, taken))
    record('append-column-expands-rows', lambda: model.appendColumn([QStandardItem('extra-%d' % i) for i in range(6)]))
    record('insert-single-count-overload', lambda: model.insertColumn(0))
    record('remove-single-count-overload', lambda: model.removeColumn(0))
    record('item-count-past-end', lambda: model.invisibleRootItem().insertColumns(model.columnCount() + 2, 1))
    record('item-invalid-remove', lambda: model.invisibleRootItem().removeColumns(0, model.columnCount() + 1))
    parent = model.itemFromIndex(model.index(0, 0))
    parent.appendRow([QStandardItem('child-%d' % i) for i in range(9)])
    selection.setCurrentIndex(parent.child(0, 0).index(), flags.ClearAndSelect)
    watched['nested'] = QPersistentModelIndex(parent.child(0, 1).index())
    record('nested-insert-columns', lambda: model.insertColumns(1, 1, parent.index()))
    record('nested-remove-current-columns', lambda: model.removeColumns(0, 8, parent.index()))
    other = QStandardItemModel(1, 1)
    record('foreign-parent-insert', lambda: model.insertColumns(0, 1, other.index(0, 0)))
    record('foreign-parent-remove', lambda: model.removeColumns(0, 1, other.index(0, 0)))
    rng = random.Random(68051)
    for number in range(100):
        op = rng.choice(('insert', 'remove', 'select', 'current'))
        count = model.columnCount()
        if op == 'insert' and count < 10:
            col = rng.randrange(count + 1)
            action = lambda col=col: model.insertColumns(col, 1)
        elif op == 'remove' and count:
            col = rng.randrange(count)
            action = lambda col=col: model.removeColumns(col, 1)
        elif count and op == 'select':
            area = QItemSelection(model.index(0, rng.randrange(count)), model.index(2, rng.randrange(count)))
            command = rng.choice((flags.Select, flags.ClearAndSelect, flags.ToggleCurrent))
            action = lambda area=area, command=command: selection.select(area, command)
        elif count:
            col = rng.randrange(count)
            action = lambda col=col: selection.setCurrentIndex(model.index(1, col), flags.NoUpdate)
        else:
            action = lambda: model.insertColumns(0, 1)
        record('seed-%03d-%s' % (number, op), action)
    model.setRowCount(0)
    model.setColumnCount(2)
    record('zero-rows-insert-columns', lambda: model.insertColumns(1, 2))
    record('zero-rows-take-column', lambda: model.takeColumn(1))
    record('zero-rows-remove-all-columns', lambda: model.removeColumns(0, 3))
    record('zero-rows-invalid-take-column', lambda: model.takeColumn(0))
    record('sequence-insert-past-end-expands-rows-only', lambda: model.insertColumn(2, [QStandardItem('unowned')]))
    print('QT_ORACLE_JSON:' + json.dumps({'version': version, 'trace': trace, 'ranges': {}}, sort_keys=True))


if __name__ == '__main__':
    main()
