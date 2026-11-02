"""Item-owned child row resizing, structural ordering and persistent selection."""
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
        from PySide6.QtCore import QItemSelectionModel, QPersistentModelIndex, Qt, qVersion
        from PySide6.QtGui import QStandardItemModel, QStandardItem
        version = qVersion()
    else:
        sys.path.insert(0, str(Path(args.root).resolve()))
        from DearUIQt.QtCore import QItemSelectionModel, QPersistentModelIndex, Qt
        from DearUIQt.QtGui import QStandardItemModel, QStandardItem
        version = 'Qt-6.8-subset'
    trace = []
    detached = QStandardItem('detached')
    for count in (3, 3, -1, 1, 0, 2):
        result = detached.setRowCount(count)
        trace.append({'name': 'detached-zero-columns-%d' % count, 'return': result,
                      'dimensions': [detached.rowCount(), detached.columnCount()]})
    detached.setColumnCount(2)
    for count in (4, 1, -3, 0):
        result = detached.setRowCount(count)
        trace.append({'name': 'detached-two-columns-%d' % count, 'return': result,
                      'dimensions': [detached.rowCount(), detached.columnCount()],
                      'empty': all(detached.child(row, column) is None for row in range(detached.rowCount())
                                   for column in range(detached.columnCount()))})

    model = QStandardItemModel(2, 2)
    parent = QStandardItem('parent')
    for row in range(3):
        parent.appendRow([QStandardItem('%d:a' % row), QStandardItem('%d:b' % row)])
    parent.child(2).appendRow(QStandardItem('descendant'))
    model.setItem(0, 0, parent)
    model.setVerticalHeaderLabels(['first', 'second'])
    handles = [QPersistentModelIndex(parent.child(0).index()),
               QPersistentModelIndex(parent.child(2).index()),
               QPersistentModelIndex(parent.child(2).child(0).index())]
    selection = QItemSelectionModel(model)
    flags = QItemSelectionModel.SelectionFlag
    selection.select(parent.child(0).index(), flags.Select | flags.Rows)
    selection.setCurrentIndex(parent.child(2).index(), flags.Select | flags.Rows)
    def key(index):
        result = []
        while index.isValid():
            result.append([index.row(), index.column()])
            index = index.parent()
        return result[::-1]
    def state(name):
        item = model.item(0, 0) if model.rowCount() else None
        return {'name': name, 'root': [model.rowCount(), model.columnCount()],
                'child': [item.rowCount(), item.columnCount()] if item is not None else None,
                'selection': sorted(key(index) for index in selection.selectedIndexes()),
                'current': key(selection.currentIndex()),
                'persistent': [[handle.isValid(), key(handle), handle.data()] for handle in handles],
                'headers': [model.headerData(row, Qt.Vertical) for row in range(model.rowCount())]}
    for name in ('rowsAboutToBeInserted', 'rowsInserted', 'rowsAboutToBeRemoved', 'rowsRemoved'):
        getattr(model, name).connect(lambda index, first, last, name=name: trace.append(
            dict(state(name), parent=key(index), first=first, last=last)))
    selection.selectionChanged.connect(lambda added, removed: trace.append(dict(
        state('selectionChanged'), added=sorted(key(index) for index in added.indexes()),
        removed=sorted(key(index) for index in removed.indexes()))))
    selection.currentChanged.connect(lambda current, previous: trace.append(dict(
        state('currentChanged'), previous=key(previous))))
    for count in (6, 6, -1, 2, 0, 3):
        result = parent.setRowCount(count)
        trace.append(dict(state('attached-%d' % count), result=result))
    for count in (5, 5, -1, 1, 0):
        result = model.invisibleRootItem().setRowCount(count)
        trace.append(dict(state('root-%d' % count), result=result))
    print('QT_ORACLE_JSON:' + json.dumps({'version': version, 'trace': trace, 'ranges': []}))


if __name__ == '__main__':
    main()
