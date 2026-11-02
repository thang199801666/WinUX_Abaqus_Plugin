"""Standard-item recursive sort, empty cells, roles and layout payloads."""
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
        from PySide6.QtCore import Qt, QAbstractItemModel, QItemSelectionModel, QItemSelection, QPersistentModelIndex, QModelIndex, qVersion
        from PySide6.QtGui import QStandardItemModel, QStandardItem
        version = qVersion()
    else:
        sys.path.insert(0, str(Path(args.root).resolve()))
        from DearUIQt.QtCore import Qt, QAbstractItemModel, QItemSelectionModel, QItemSelection, QPersistentModelIndex, QModelIndex
        from DearUIQt.QtGui import QStandardItemModel, QStandardItem
        version = 'Qt-6.8-subset'
    roles = getattr(Qt, 'ItemDataRole', Qt)
    order = getattr(Qt, 'SortOrder', Qt)
    flags = getattr(QItemSelectionModel, 'SelectionFlag', QItemSelectionModel)
    trace = []

    def key(index):
        path = []
        while index.isValid():
            path.append([index.row(), index.column()])
            index = index.parent()
        return path[::-1] if path else None

    def watch(model):
        selection = QItemSelectionModel(model)
        selection.select(QItemSelection(model.index(0, 0), model.index(min(2, model.rowCount() - 1), 1)), flags.ClearAndSelect)
        selection.setCurrentIndex(model.index(0, 1), flags.NoUpdate)
        persistent = QPersistentModelIndex(model.index(0, 1))
        events = []
        def table(parent=QModelIndex()):
            parent_item = model.itemFromIndex(parent) if parent.isValid() else model.invisibleRootItem()
            result = []
            for row in range(model.rowCount(parent)):
                values = []
                for column in range(model.columnCount(parent)):
                    index = model.index(row, column, parent)
                    values.append({'data': index.data(), 'item': parent_item.child(row, column) is not None,
                                   'children': table(index) if model.rowCount(index) else []})
                result.append(values)
            return result
        def state():
            return {'table': table(), 'selected': sorted((key(index) for index in selection.selectedIndexes()), key=lambda v: json.dumps(v)),
                    'current': key(selection.currentIndex()), 'current_data': selection.currentIndex().data(),
                    'persistent': [key(persistent), persistent.data()],
                    'row_headers': [model.headerData(row, getattr(Qt, 'Orientation', Qt).Vertical)
                                    for row in range(model.rowCount())]}
        for name in ('layoutAboutToBeChanged', 'layoutChanged'):
            def layout(*payload, name=name):
                events.append({'signal': name, 'args': len(payload),
                               'parents': [key(index) for index in payload[0]] if payload else [],
                               'hint': getattr(payload[1], 'value', payload[1]) if len(payload) > 1 else None,
                               'state': state()})
            signal = getattr(model, name)
            if args.engine == 'qt':
                # PySide defaults to a synthetic zero-argument overload. Choose
                # the actual Qt C++ signature to verify parents and layout hint.
                signal = signal['QList<QPersistentModelIndex>', 'QAbstractItemModel::LayoutChangeHint']
            signal.connect(layout)
        model.itemChanged.connect(lambda *args: events.append({'signal': 'itemChanged'}))
        model.dataChanged.connect(lambda *args: events.append({'signal': 'dataChanged'}))
        selection.selectionChanged.connect(lambda *args: events.append({'signal': 'selection'}))
        selection.currentChanged.connect(lambda *args: events.append({'signal': 'current'}))
        def record(name, action):
            events.clear()
            action()
            trace.append({'name': name, 'state': state(), 'events': list(events)})
        return record

    model = QStandardItemModel(6, 2)
    values = ['b', None, 'A', QStandardItem(), '', 'a']
    for row, value in enumerate(values):
        if value is not None:
            item = value if isinstance(value, QStandardItem) else QStandardItem(value)
            item.setData(10 - row, roles.UserRole)
            model.setItem(row, 0, item)
        model.setItem(row, 1, QStandardItem('id%d' % row))
    model.item(0, 0).appendRow([QStandardItem('z'), QStandardItem('child-id0')])
    model.item(0, 0).appendRow([QStandardItem('a'), QStandardItem('child-id1')])
    model.item(0, 1).appendRow(QStandardItem('z-in-other-column'))
    model.item(0, 1).appendRow(QStandardItem('a-in-other-column'))
    record = watch(model)
    record('ascending-case-empty-recursive', lambda: model.sort(0, order.AscendingOrder))
    record('descending-missing-cell-always-last', lambda: model.sort(0, order.DescendingOrder))
    model.setSortRole(roles.UserRole)
    record('numeric-custom-sort-role', lambda: model.sort(0))
    record('negative-sort-column', lambda: model.sort(-1))
    record('past-end-sort-column', lambda: model.sort(2))
    # Use the original populated parent even if custom-role sorting changed its row.
    parent = next(model.item(row, 0) for row in range(model.rowCount())
                  if model.item(row, 0) is not None and model.item(row, 0).rowCount())
    record('nested-item-sort-layout-parent', lambda: parent.sortChildren(0, order.DescendingOrder))
    rng = random.Random(68091)
    for number in range(100):
        column = rng.choice((-1, 0, 1, 2))
        sort_order = rng.choice((order.AscendingOrder, order.DescendingOrder))
        model.setSortRole(rng.choice((roles.DisplayRole, roles.UserRole)))
        record('seed-%03d' % number, lambda column=column, sort_order=sort_order: model.sort(column, sort_order))

    class ReverseItem(QStandardItem):
        def __lt__(self, other):
            return self.text() > other.text()
    custom = QStandardItemModel()
    for text in ('a', 'z', 'm'):
        custom.appendRow([ReverseItem(text), QStandardItem('id-' + text)])
    record = watch(custom)
    record('custom-item-comparator', lambda: custom.sort(0))
    for name, values in (('integer-stable-ties', [2, 1, 2, 1]),
                         ('float-stable-ties', [2.5, -1.25, 0.0, 2.5]),
                         ('mixed-numeric-rounding', [1, 1.6, 2, 2.4]),
                         ('utf16-string-order', ['\ue000', '\U0001f600', 'a'])):
        numeric = QStandardItemModel()
        for row, value in enumerate(values):
            item = QStandardItem()
            item.setData(value, roles.DisplayRole)
            numeric.appendRow([item, QStandardItem('id%d' % row)])
        numeric.setVerticalHeaderLabels(['header%d' % row for row in range(len(values))])
        record = watch(numeric)
        record(name + '-ascending', lambda: numeric.sort(0))
        record(name + '-descending', lambda: numeric.sort(0, order.DescendingOrder))
    empty = QStandardItemModel(0, 2)
    record = watch(empty)
    record('empty-model-sort-no-layout', lambda: empty.sort(0))
    detached = QStandardItem()
    detached.appendRow(QStandardItem('b'))
    detached.appendRow(QStandardItem('A'))
    detached.sortChildren(0)
    trace.append({'name': 'detached-display-role-case-sensitive',
                  'texts': [detached.child(row).text() for row in range(detached.rowCount())]})
    print('QT_ORACLE_JSON:' + json.dumps({'version': version, 'trace': trace, 'ranges': {}}, sort_keys=True))


if __name__ == '__main__':
    main()
