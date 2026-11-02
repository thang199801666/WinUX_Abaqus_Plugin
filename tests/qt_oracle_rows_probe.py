"""Structural model transactions, run identically under Qt or DearUIQt."""
import argparse
import json
import random
from pathlib import Path
import sys


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--engine', choices=('qt', 'dearuiqt'), required=True)
    parser.add_argument('--root', default='.')
    options = parser.parse_args()
    if options.engine == 'qt':
        from PySide6.QtCore import QModelIndex, Qt, qVersion
        from PySide6.QtGui import QStandardItemModel, QStandardItem
        version = qVersion()
    else:
        sys.path.insert(0, str(Path(options.root).resolve()))
        from DearUIQt.QtCore import QModelIndex, Qt
        from DearUIQt.QtGui import QStandardItemModel, QStandardItem
        version = 'Qt-6.8-subset'
    roles = getattr(Qt, 'ItemDataRole', Qt)

    def key(index):
        path = []
        while index.isValid():
            path.append([index.row(), index.column()])
            index = index.parent()
        return path[::-1] if path else None

    model = QStandardItemModel()
    for row in range(3):
        model.appendRow([QStandardItem('%d:%d' % (row, column)) for column in range(2)])

    def table(parent=QModelIndex()):
        return [[model.data(model.index(row, column, parent), roles.DisplayRole)
                 for column in range(model.columnCount(parent))]
                for row in range(model.rowCount(parent))]

    events, trace = [], []
    for name in ('rowsAboutToBeInserted', 'rowsInserted', 'rowsAboutToBeRemoved', 'rowsRemoved',
                 'columnsAboutToBeInserted', 'columnsInserted', 'columnsAboutToBeRemoved', 'columnsRemoved'):
        getattr(model, name).connect(lambda parent, first, last, name=name: events.append({
            'signal': name, 'parent': key(parent), 'first': first, 'last': last,
            'rows': model.rowCount(parent), 'columns': model.columnCount(parent), 'table': table(parent)}))
    model.dataChanged.connect(lambda top, bottom, changed: events.append({
        'signal': 'dataChanged', 'top': key(top), 'bottom': key(bottom),
        'roles': [int(role) for role in changed]}))
    model.itemChanged.connect(lambda item: events.append({'signal': 'itemChanged', 'text': item.text()}))

    def record(name, result=None):
        trace.append({'name': name, 'result': result, 'table': table(), 'columns': model.columnCount(),
                      'events': list(events)})
        events.clear()

    record('insertRows', model.insertRows(1, 2))
    index = model.index(1, 1)
    trace.append({'name': 'empty-cell', 'index_valid': index.isValid(),
                  'data': model.data(index, roles.DisplayRole), 'item_exists': model.item(1, 1) is not None})
    record('setData-empty', model.setData(model.index(1, 0), 'inserted'))
    record('removeRows', model.removeRows(3, 1))
    for name, row, count in [('invalid-remove-overrun', 3, 2), ('invalid-remove-zero', 0, 0),
                              ('invalid-remove-negative', -1, 1)]:
        record(name, model.removeRows(row, count))
    record('invalid-insert-past-end', model.insertRows(model.rowCount() + 1, 1))
    record('invalid-insert-zero', model.insertRows(0, 0))
    record('invalid-insert-negative', model.insertRows(-1, 1))
    model.setRowCount(7)
    record('grow-count')
    model.setRowCount(2)
    record('shrink-count')
    model.setColumnCount(4)
    record('grow-columns')
    model.setColumnCount(1)
    record('shrink-columns')
    parent = model.index(0, 0)
    result = model.insertRows(0, 2, parent)
    record('nested-zero-column-rows', result)
    item = model.itemFromIndex(parent)
    item.appendRow(QStandardItem('nested'))
    record('nested-append-item')
    result = model.insertRows(1, 1, parent)
    record('nested-insertRows', result)
    trace.append({'name': 'nested-empty-cell', 'valid': model.index(1, 0, parent).isValid(),
                  'parent': key(model.index(1, 0, parent).parent()), 'table': table(parent)})
    other = QStandardItemModel()
    other.appendRow(QStandardItem('foreign'))
    record('foreign-parent-insert', model.insertRows(0, 1, other.index(0, 0)))
    record('foreign-parent-remove', model.removeRows(0, 1, other.index(0, 0)))
    taken = model.takeRow(0)
    record('takeRow')
    trace.append({'name': 'detached-ownership', 'model_none': taken[0].model() is None,
                  'parent_none': taken[0].parent() is None, 'row': taken[0].row()})
    model.appendRow(taken)
    record('reinsert-taken')
    cell = model.index(0, 0)
    empty_before = model.item(0, 0) is None
    materialized = model.itemFromIndex(cell)
    trace.append({'name': 'lazy-materialization', 'before_empty': empty_before,
                  'after_exists': model.item(0, 0) is not None,
                  'item_is_cell': model.item(0, 0) is materialized,
                  'same_index': cell == model.index(0, 0)})
    model.setItem(4, 2, QStandardItem('expanded'))
    record('setItem-expand')
    model.setItem(0, 0, QStandardItem('replacement'))
    record('setItem-replace')
    record('setData-same', model.setData(model.index(0, 0), 'replacement'))
    model.setData(model.index(0, 0), 'display', roles.DisplayRole)
    record('setData-display')
    model.setData(model.index(0, 0), 'payload', roles.UserRole)
    record('setData-user')
    # Bounded deterministic count mutations test old/new snapshots across many
    # empty-cell and zero-column transitions, without relying on stale indexes.
    rng = random.Random(68023)
    for number in range(200):
        operation = rng.choice(('insert', 'remove', 'rows', 'columns'))
        if operation == 'insert':
            result = model.insertRows(rng.randrange(model.rowCount() + 2), rng.randrange(4))
        elif operation == 'remove':
            result = model.removeRows(rng.randrange(model.rowCount() + 2), rng.randrange(4))
        elif operation == 'rows':
            result = model.setRowCount(rng.randrange(7))
        else:
            result = model.setColumnCount(rng.randrange(5))
        record('seed-%03d-%s' % (number, operation), result)
    print('QT_ORACLE_JSON:' + json.dumps({'engine': options.engine, 'version': version,
                                         'trace': trace, 'ranges': {}}, sort_keys=True))


if __name__ == '__main__':
    main()
