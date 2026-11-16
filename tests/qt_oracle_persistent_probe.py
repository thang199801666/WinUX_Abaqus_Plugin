"""Persistent index lifetime/coordinates, run in isolated Qt/DearUIQt processes."""
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
        from PySide6.QtCore import QPersistentModelIndex, QModelIndex, QAbstractTableModel, Qt, qVersion
        from PySide6.QtGui import QStandardItemModel, QStandardItem
        version = qVersion()
    else:
        sys.path.insert(0, str(Path(args.root).resolve()))
        from DearUIQt.QtCore import QPersistentModelIndex, QModelIndex, QAbstractTableModel, Qt
        from DearUIQt.QtGui import QStandardItemModel, QStandardItem
        version = 'Qt-6.8-subset'

    model = QStandardItemModel()
    for row in range(4):
        model.appendRow([QStandardItem('%d:%d' % (row, col)) for col in range(2)])
    model.item(2, 0).appendRow(QStandardItem('child'))
    model.item(2, 0).child(0).appendRow(QStandardItem('grandchild'))
    watched = {'before': QPersistentModelIndex(model.index(0, 0)),
               'middle': QPersistentModelIndex(model.index(2, 0)),
               'tail': QPersistentModelIndex(model.index(3, 1)),
               'child': QPersistentModelIndex(model.item(2, 0).child(0).index()),
               'grandchild': QPersistentModelIndex(model.item(2, 0).child(0).child(0).index())}
    trace = []
    clearing = False
    clear_events = []

    def state(index):
        parent = index.parent() if hasattr(index, 'parent') else index.toModelIndex().parent()
        return {'valid': index.isValid(), 'row': index.row(), 'column': index.column(),
                'model': index.model() is model, 'data': index.data(),
                'parent': [parent.row(), parent.column()] if parent.isValid() else None}

    def record(name):
        trace.append({'name': name, 'indexes': {key: state(index) for key, index in watched.items()}})

    def signal_record(name):
        if clearing:
            clear_events.append({'name': name, 'indexes': {key: state(index) for key, index in watched.items()}})
        else:
            record(name)

    for signal in ('rowsAboutToBeInserted', 'rowsInserted', 'rowsAboutToBeRemoved', 'rowsRemoved',
                   'columnsAboutToBeRemoved', 'columnsRemoved', 'modelAboutToBeReset', 'modelReset'):
        getattr(model, signal).connect(lambda *unused, signal=signal: signal_record(signal))
    record('initial')
    model.insertRows(1, 2)
    record('after-insert')
    model.removeRows(1, 1)
    record('after-remove-before')
    # Remove a parent subtree, then reinsert it. Old persistent handles must
    # never spring back to life when their former items are re-adopted.
    taken = model.takeRow(3)
    record('after-take-parent')
    model.appendRow(taken)
    record('after-reinsert-parent')
    model.setColumnCount(1)
    record('after-remove-column')
    watched['replacement'] = QPersistentModelIndex(model.index(0, 0))
    model.setItem(0, 0, QStandardItem('replacement'))
    record('after-setItem')
    watched['taken_cell'] = QPersistentModelIndex(model.index(0, 0))
    cell = model.takeItem(0, 0)
    record('after-takeItem')
    model.setItem(0, 0, cell)
    record('after-reinsertItem')
    watched['null_replaced'] = QPersistentModelIndex(model.index(0, 0))
    model.setItem(0, 0, None)
    record('after-setItem-null')
    watched['empty'] = QPersistentModelIndex(model.index(1, 0))
    model.setData(model.index(1, 0), 'materialized')
    record('after-materialize')
    # Exercise the C++ reset contract directly. PySide6's clear() wrapper injects
    # one takeRow(0) per row before calling C++ clear(); keep those raw events
    # separately, not as a requirement for the backend-neutral Qt C++ contract.
    model.beginResetModel()
    model.endResetModel()
    record('after-explicit-reset')
    watched['clear_cell'] = QPersistentModelIndex(model.index(1, 0))
    clearing = True
    model.clear()
    clearing = False
    record('after-clear')
    model.appendRow(QStandardItem('new model content'))
    record('after-reset-repopulate')
    # Explicitly exercise the base protocol without row()/column() methods on
    # internalPointer. This catches accidental dependence on standard items.
    class FlatModel(QAbstractTableModel):
        def __init__(self):
            super().__init__()
            self.values = [['a', 'b'], ['c', 'd'], ['e', 'f']]

        def rowCount(self, parent=QModelIndex()):
            return 0 if parent.isValid() else len(self.values)

        def columnCount(self, parent=QModelIndex()):
            return 0 if parent.isValid() else len(self.values[0])

        def data(self, index, role=0):
            return self.values[index.row()][index.column()] if index.isValid() and int(role) == 0 else None

    model = FlatModel()
    watched = {'flat': QPersistentModelIndex(model.index(2, 1))}
    record('pointerless-initial')
    model.beginInsertRows(QModelIndex(), 1, 1)
    model.values.insert(1, ['new', 'row'])
    model.endInsertRows()
    record('pointerless-insert')
    model.beginRemoveRows(QModelIndex(), 0, 0)
    del model.values[0]
    model.endRemoveRows()
    record('pointerless-remove-before')
    model.beginInsertColumns(QModelIndex(), 0, 0)
    for row in model.values:
        row.insert(0, 'new column')
    model.endInsertColumns()
    record('pointerless-insert-column')
    model.beginRemoveColumns(QModelIndex(), 1, 1)
    for row in model.values:
        del row[1]
    model.endRemoveColumns()
    record('pointerless-remove-column-before')
    model.beginRemoveColumns(QModelIndex(), 1, 1)
    for row in model.values:
        del row[1]
    model.endRemoveColumns()
    record('pointerless-remove-column-containing')
    model = QStandardItemModel()
    for text in ('z', 'a', 'm'):
        model.appendRow(QStandardItem(text))
    watched = {'sorted': QPersistentModelIndex(model.index(0, 0))}
    model.layoutAboutToBeChanged.connect(lambda *args: record('layoutAboutToBeChanged'))
    model.layoutChanged.connect(lambda *args: record('layoutChanged'))
    model.sort(0)
    record('after-model-sort')
    order = getattr(Qt, 'SortOrder', Qt)
    model.invisibleRootItem().sortChildren(0, order.DescendingOrder)
    record('after-item-sort')
    print('QT_ORACLE_JSON:' + json.dumps({'version': version, 'trace': trace, 'ranges': {},
                                         'observations': {'clear_wrapper_events': clear_events}}, sort_keys=True))


if __name__ == '__main__':
    main()
