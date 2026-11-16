"""setItem/takeItem selection, persistent handles and signal ordering."""
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
        from PySide6.QtCore import QItemSelectionModel, QItemSelection, QPersistentModelIndex, qVersion
        from PySide6.QtGui import QStandardItemModel, QStandardItem
        version = qVersion()
    else:
        sys.path.insert(0, str(Path(args.root).resolve()))
        from DearUIQt.QtCore import QItemSelectionModel, QItemSelection, QPersistentModelIndex
        from DearUIQt.QtGui import QStandardItemModel, QStandardItem
        version = 'Qt-6.8-subset'
    flags = getattr(QItemSelectionModel, 'SelectionFlag', QItemSelectionModel)
    trace = []

    def key(index):
        path = []
        while index.isValid():
            path.append([index.row(), index.column()])
            index = index.parent()
        return path[::-1] if path else None

    def keys(indexes):
        return sorted((key(index) for index in indexes), key=lambda value: json.dumps(value))

    def setup(early_layout_observer=False):
        model = QStandardItemModel()
        for row in range(3):
            model.appendRow([QStandardItem('%d:%d' % (row, col)) for col in range(3)])
        selection = None
        events, watched = [], {}
        def state():
            return {'selected': keys(selection.selectedIndexes()), 'current': key(selection.currentIndex()),
                    'current_data': selection.currentIndex().data(),
                    'persistent': {name: {'index': key(index), 'data': index.data()}
                                   for name, index in watched.items()}}
        def connect_layout():
            for name in ('layoutAboutToBeChanged', 'layoutChanged'):
                getattr(model, name).connect(lambda *args, name=name: events.append({'signal': name, 'state': state()}))
        if early_layout_observer:
            connect_layout()
        selection = QItemSelectionModel(model)
        if not early_layout_observer:
            connect_layout()
        for name in ('rowsAboutToBeRemoved', 'rowsRemoved', 'columnsAboutToBeRemoved', 'columnsRemoved'):
            getattr(model, name).connect(lambda parent, first, last, name=name: events.append(
                {'signal': name, 'parent': key(parent), 'first': first, 'last': last, 'state': state()}))
        model.dataChanged.connect(lambda top, bottom, roles: events.append(
            {'signal': 'dataChanged', 'index': key(top), 'roles': [int(role) for role in roles], 'state': state()}))
        model.itemChanged.connect(lambda item: events.append(
            {'signal': 'itemChanged', 'text': item.text(), 'state': state()}))
        selection.selectionChanged.connect(lambda added, removed: events.append(
            {'signal': 'selection', 'added': keys(added.indexes()), 'removed': keys(removed.indexes()), 'state': state()}))
        for name in ('currentChanged', 'currentRowChanged', 'currentColumnChanged'):
            getattr(selection, name).connect(lambda current, old, name=name: events.append(
                {'signal': name, 'current': key(current), 'old': key(old), 'state': state()}))
        def record(name, action):
            events.clear()
            action()
            trace.append({'name': name, 'state': state(), 'events': list(events)})
        return model, selection, watched, record

    model, selection, watched, record = setup()
    selection.setCurrentIndex(model.index(1, 1), flags.ClearAndSelect)
    watched['cell'] = QPersistentModelIndex(model.index(1, 1))
    record('replace-selected-current-cell', lambda: model.setItem(1, 1, QStandardItem('new')))
    record('replace-with-none', lambda: model.setItem(1, 1, None))
    record('materialize-after-none', lambda: model.setData(model.index(1, 1), 'materialized'))
    selection.setCurrentIndex(model.index(1, 1), flags.ClearAndSelect)
    watched['taken'] = QPersistentModelIndex(model.index(1, 1))
    taken = []
    record('take-selected-leaf', lambda: taken.append(model.takeItem(1, 1)))
    record('reinsert-taken-leaf', lambda: model.setItem(1, 1, taken[0]))
    record('set-same-item-noop', lambda: model.setItem(1, 1, taken[0]))

    model, selection, watched, record = setup()
    selection.select(QItemSelection(model.index(0, 0), model.index(2, 2)), flags.ClearAndSelect)
    selection.setCurrentIndex(model.index(1, 1), flags.NoUpdate)
    record('take-interior-of-selected-rectangle', lambda: model.takeItem(1, 1))
    record('take-corner-of-selected-rectangle', lambda: model.takeItem(0, 0))

    for operation in ('replace', 'take'):
        model, selection, watched, record = setup()
        parent = model.item(1, 0)
        parent.appendRow([QStandardItem('child-a'), QStandardItem('child-b')])
        child = parent.child(0, 0)
        child.appendRow(QStandardItem('grandchild'))
        selection.select(parent.index(), flags.Select)
        selection.select(child.child(0).index(), flags.Select)
        selection.setCurrentIndex(child.index(), flags.NoUpdate)
        watched['parent'] = QPersistentModelIndex(parent.index())
        watched['child'] = QPersistentModelIndex(child.index())
        watched['grandchild'] = QPersistentModelIndex(child.child(0).index())
        if operation == 'replace':
            record('replace-selected-parent-subtree', lambda: model.setItem(1, 0, QStandardItem('new-parent')))
        else:
            taken = []
            record('take-selected-parent-subtree', lambda: taken.append(model.takeItem(1, 0)))
            trace.append({'name': 'taken-subtree-retained', 'rows': taken[0].rowCount(),
                          'columns': taken[0].columnCount(), 'child_text': taken[0].child(0).text(),
                          'detached': taken[0].model() is None})
            record('reinsert-selected-parent-subtree', lambda: model.setItem(1, 0, taken[0]))
    model, selection, watched, record = setup()
    model.removeRows(0, 3)
    model.insertRows(0, 3)
    selection.setCurrentIndex(model.index(1, 1), flags.ClearAndSelect)
    watched['empty'] = QPersistentModelIndex(model.index(1, 1))
    record('take-empty-cell-is-noop', lambda: model.takeItem(1, 1))
    record('set-empty-cell-none-is-noop', lambda: model.setItem(1, 1, None))
    record('replace-empty-selected-cell', lambda: model.setItem(1, 1, QStandardItem('filled')))

    model, selection, watched, record = setup(early_layout_observer=True)
    selection.select(QItemSelection(model.index(0, 0), model.index(2, 2)), flags.ClearAndSelect)
    record('early-layout-observer-corner-none', lambda: model.setItem(0, 0, None))

    model, selection, watched, record = setup()
    selection.select(QItemSelection(model.index(0, 0), model.index(2, 2)), flags.ClearAndSelect)
    selection.setCurrentIndex(model.index(1, 1), flags.NoUpdate)
    watched['seed-cell'] = QPersistentModelIndex(model.index(1, 1))
    rng = random.Random(68041)
    for number in range(100):
        row, column = rng.randrange(3), rng.randrange(3)
        operation = rng.choice(('replace', 'null', 'take', 'select', 'current', 'data'))
        if operation == 'replace':
            action = lambda row=row, column=column, number=number: model.setItem(row, column, QStandardItem(str(number)))
        elif operation == 'null':
            action = lambda row=row, column=column: model.setItem(row, column, None)
        elif operation == 'take':
            action = lambda row=row, column=column: model.takeItem(row, column)
        elif operation == 'select':
            area = QItemSelection(model.index(row, column), model.index(rng.randrange(3), rng.randrange(3)))
            command = rng.choice((flags.ClearAndSelect, flags.Select, flags.ToggleCurrent, flags.Deselect | flags.Current))
            action = lambda area=area, command=command: selection.select(area, command)
        elif operation == 'current':
            action = lambda row=row, column=column: selection.setCurrentIndex(model.index(row, column), flags.NoUpdate)
        else:
            action = lambda row=row, column=column, number=number: model.setData(model.index(row, column), str(number))
        record('seed-%03d-%s' % (number, operation), action)
    print('QT_ORACLE_JSON:' + json.dumps({'version': version, 'trace': trace, 'ranges': {}}, sort_keys=True))


if __name__ == '__main__':
    main()
