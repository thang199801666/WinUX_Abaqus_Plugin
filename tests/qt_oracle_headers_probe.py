"""Header defaults, roles, items and row/column structural signal snapshots."""
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
        from PySide6.QtCore import Qt, qVersion
        from PySide6.QtGui import QStandardItemModel, QStandardItem
        version = qVersion()
    else:
        sys.path.insert(0, str(Path(args.root).resolve()))
        from DearUIQt.QtCore import Qt
        from DearUIQt.QtGui import QStandardItemModel, QStandardItem
        version = 'Qt-6.8-subset'
    orientation = getattr(Qt, 'Orientation', Qt)
    roles = getattr(Qt, 'ItemDataRole', Qt)
    h, v = orientation.Horizontal, orientation.Vertical
    model = QStandardItemModel(3, 3)
    trace, events = [], []

    def headers(axis):
        count = model.columnCount() if axis == h else model.rowCount()
        return [[model.headerData(section, axis, role) for role in
                 (roles.DisplayRole, roles.EditRole, roles.UserRole)] for section in range(count)]

    def state():
        return {'h': headers(h), 'v': headers(v), 'rows': model.rowCount(), 'columns': model.columnCount()}

    model.headerDataChanged.connect(lambda axis, first, last: events.append({
        'signal': 'headerDataChanged', 'horizontal': axis == h, 'first': first, 'last': last, 'state': state()}))
    model.itemChanged.connect(lambda item: events.append({'signal': 'itemChanged', 'text': item.text()}))
    model.dataChanged.connect(lambda *args: events.append({'signal': 'dataChanged'}))
    for name in ('rowsAboutToBeInserted', 'rowsInserted', 'rowsAboutToBeRemoved', 'rowsRemoved',
                 'columnsAboutToBeInserted', 'columnsInserted', 'columnsAboutToBeRemoved', 'columnsRemoved'):
        getattr(model, name).connect(lambda *args, name=name: events.append({'signal': name, 'state': state()}))

    def record(name, action=lambda: None):
        events.clear()
        result = action()
        trace.append({'name': name, 'result': result, 'state': state(), 'events': list(events)})

    record('default-headers')
    for section in (-1, 3):
        record('invalid-set-%d' % section, lambda section=section: model.setHeaderData(section, h, 'bad'))
    record('set-display-header', lambda: model.setHeaderData(1, h, 'B'))
    record('set-same-header', lambda: model.setHeaderData(1, h, 'B'))
    record('set-custom-role-header', lambda: model.setHeaderData(0, h, 'metadata', roles.UserRole))
    record('set-numeric-header', lambda: model.setHeaderData(2, h, 42))
    record('clear-header-value', lambda: model.setHeaderData(2, h, None))
    record('clear-missing-header-role', lambda: model.setHeaderData(2, h, None, roles.UserRole))
    record('horizontal-labels', lambda: model.setHorizontalHeaderLabels(['A', 'B2', 'C']))
    record('shorter-horizontal-labels-preserve-tail', lambda: model.setHorizontalHeaderLabels(['A2']))
    record('empty-horizontal-labels', lambda: model.setHorizontalHeaderLabels([]))
    record('vertical-labels-expand', lambda: model.setVerticalHeaderLabels(['r0', 'r1', 'r2', 'r3']))
    record('insert-columns-shift-headers', lambda: model.insertColumns(1, 2))
    record('remove-columns-shift-headers', lambda: model.removeColumns(0, 2))
    record('insert-rows-shift-headers', lambda: model.insertRows(1, 2))
    record('remove-rows-shift-headers', lambda: model.removeRows(0, 2))
    # Header-item methods are intentionally late: the initial data-only probe
    # also provides useful diagnostics before these new APIs are implemented.
    record('take-body-column-removes-header', lambda: model.takeColumn(1) and None)
    record('take-body-row-removes-header', lambda: model.takeRow(1) and None)
    item = QStandardItem('header-item')
    record('set-horizontal-header-item-expand', lambda: model.setHorizontalHeaderItem(4, item))
    trace.append({'name': 'header-item-identity', 'same': model.horizontalHeaderItem(4) is item,
                  'model': item.model() is model, 'parent_none': item.parent() is None,
                  'row': item.row(), 'column': item.column(), 'index_valid': item.index().isValid()})
    record('edit-header-item', lambda: item.setText('edited') and None)
    taken = []
    record('take-header-item-silent', lambda: taken.append(model.takeHorizontalHeaderItem(4)))
    trace.append({'name': 'taken-header-ownership', 'same': taken[0] is item, 'model_none': item.model() is None})
    record('reinsert-header-item', lambda: model.setVerticalHeaderItem(0, taken[0]))
    record('set-same-header-item', lambda: model.setVerticalHeaderItem(0, taken[0]))
    record('set-header-item-none', lambda: model.setVerticalHeaderItem(0, None))
    record('resize-columns-removes-headers', lambda: model.setColumnCount(1))
    record('resize-columns-new-defaults', lambda: model.setColumnCount(3))
    record('resize-rows-removes-headers', lambda: model.setRowCount(1))
    record('resize-rows-new-defaults', lambda: model.setRowCount(3))
    parent = model.itemFromIndex(model.index(0, 0))
    record('nested-append-keeps-root-headers', lambda: parent.appendRow(QStandardItem('child')) and None)
    record('nested-row-count-keeps-root-headers', lambda: model.insertRows(0, 1, parent.index()))
    record('nested-column-count-keeps-root-headers', lambda: model.insertColumns(0, 1, parent.index()))
    rng = random.Random(68061)
    for number in range(100):
        axis = rng.choice((h, v))
        count = model.columnCount() if axis == h else model.rowCount()
        operation = rng.choice(('data', 'labels', 'insert', 'remove', 'take', 'item'))
        section = rng.randrange(count + 1)
        if operation == 'data':
            value = rng.choice((None, number, 'value-%d' % number))
            role = rng.choice((roles.DisplayRole, roles.EditRole, roles.UserRole))
            action = lambda section=section, axis=axis, value=value, role=role: model.setHeaderData(section, axis, value, role)
        elif operation == 'labels':
            labels = ['label-%d-%d' % (number, i) for i in range(rng.randrange(5))]
            method = model.setHorizontalHeaderLabels if axis == h else model.setVerticalHeaderLabels
            action = lambda labels=labels, method=method: method(labels)
        elif operation == 'insert' and count < 7:
            method = model.insertColumns if axis == h else model.insertRows
            action = lambda section=section, method=method: method(section, 1)
        elif operation == 'remove':
            method = model.removeColumns if axis == h else model.removeRows
            action = lambda section=section, method=method: method(section, 1)
        elif operation == 'take':
            method = model.takeHorizontalHeaderItem if axis == h else model.takeVerticalHeaderItem
            action = lambda section=section, method=method: (method(section), None)[1]
        else:
            method = model.setHorizontalHeaderItem if axis == h else model.setVerticalHeaderItem
            item = QStandardItem('item-%d' % number)
            action = lambda section=section, method=method, item=item: method(section, item)
        record('seed-%03d-%s' % (number, operation), action)
    model.setColumnCount(3)
    model.columnsAboutToBeInserted.connect(lambda *args: model.setHeaderData(1, h, 'edited-before-shift'))
    record('header-data-edit-inside-about-to', lambda: model.insertColumns(0, 1))
    print('QT_ORACLE_JSON:' + json.dumps({'version': version, 'trace': trace, 'ranges': {}}, sort_keys=True))


if __name__ == '__main__':
    main()
