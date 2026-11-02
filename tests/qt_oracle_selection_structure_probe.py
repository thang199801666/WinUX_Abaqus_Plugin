"""Selection/current structural state and signal timing against Qt 6.8."""
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
        from PySide6.QtCore import QItemSelectionModel, QItemSelection, QModelIndex, Qt, qVersion
        from PySide6.QtGui import QStandardItemModel, QStandardItem
        version = qVersion()
    else:
        sys.path.insert(0, str(Path(args.root).resolve()))
        from DearUIQt.QtCore import QItemSelectionModel, QItemSelection, QModelIndex, Qt
        from DearUIQt.QtGui import QStandardItemModel, QStandardItem
        version = 'Qt-6.8-subset'
    flags = getattr(QItemSelectionModel, 'SelectionFlag', QItemSelectionModel)
    trace = []

    def key(index):
        result = []
        while index.isValid():
            result.append([index.row(), index.column()])
            index = index.parent()
        return result[::-1] if result else None

    def keys(indexes):
        return sorted((key(index) for index in indexes), key=lambda value: json.dumps(value))

    def setup():
        model = QStandardItemModel()
        for row in range(5):
            model.appendRow([QStandardItem('%d:%d' % (row, col)) for col in range(3)])
        selection = QItemSelectionModel(model)
        events = []
        def state():
            return {'selected': keys(selection.selectedIndexes()), 'current': key(selection.currentIndex()),
                    'current_data': selection.currentIndex().data()}
        selection.selectionChanged.connect(lambda added, removed: events.append(
            {'signal': 'selection', 'added': keys(added.indexes()), 'removed': keys(removed.indexes()), 'state': state()}))
        for name in ('currentChanged', 'currentRowChanged', 'currentColumnChanged'):
            getattr(selection, name).connect(lambda current, previous, name=name: events.append(
                {'signal': name, 'current': key(current), 'previous': key(previous), 'state': state()}))
        for name in ('rowsAboutToBeInserted', 'rowsInserted', 'rowsAboutToBeRemoved', 'rowsRemoved',
                     'columnsAboutToBeInserted', 'columnsInserted', 'columnsAboutToBeRemoved', 'columnsRemoved'):
            getattr(model, name).connect(lambda parent, first, last, name=name: events.append(
                {'signal': name, 'parent': key(parent), 'first': first, 'last': last, 'state': state()}))
        def record(name, action):
            events.clear()
            action()
            trace.append({'name': name, 'state': state(), 'events': list(events)})
        return model, selection, record

    model, selection, record = setup()
    selection.setCurrentIndex(model.index(3, 1), flags.ClearAndSelect)
    record('insert-before-selected-current', lambda: model.insertRows(1, 2))
    record('remove-before-selected-current', lambda: model.removeRows(1, 1))
    record('remove-current-with-previous-sibling', lambda: model.removeRows(4, 1))
    record('remove-current-at-first-row', lambda: model.removeRows(0, 4))
    record('remove-last-current-row', lambda: model.removeRows(0, model.rowCount()))

    model, selection, record = setup()
    selection.select(QItemSelection(model.index(1, 0), model.index(3, 2)), flags.ClearAndSelect)
    record('insert-inside-rectangle', lambda: model.insertRows(2, 1))
    record('remove-inside-rectangle', lambda: model.removeRows(2, 2))
    record('insert-before-rectangle', lambda: model.insertRows(0, 1))
    record('remove-before-rectangle', lambda: model.removeRows(0, 1))

    model, selection, record = setup()
    selection.select(model.index(1, 0), flags.Select)
    selection.select(model.index(3, 0), flags.SelectCurrent)
    record('insert-finalizes-interactive-layer', lambda: model.insertRows(0, 1))
    record('current-after-insert', lambda: selection.select(model.index(2, 0), flags.ToggleCurrent))
    record('remove-finalizes-interactive-layer', lambda: model.removeRows(0, 1))
    record('current-after-remove', lambda: selection.select(model.index(0, 0), flags.SelectCurrent))

    model, selection, record = setup()
    selection.setCurrentIndex(model.index(2, 2), flags.ClearAndSelect)
    record('remove-current-column', lambda: model.setColumnCount(2))
    record('remove-current-column-again', lambda: model.setColumnCount(1))
    record('remove-all-columns', lambda: model.setColumnCount(0))

    model, selection, record = setup()
    parent = model.item(2, 0)
    parent.appendRow([QStandardItem('child-a'), QStandardItem('child-b')])
    child = parent.child(0)
    child.appendRow(QStandardItem('grandchild'))
    selection.select(child.child(0).index(), flags.ClearAndSelect)
    selection.setCurrentIndex(child.index(), flags.NoUpdate)
    record('insert-before-ancestor', lambda: model.insertRows(0, 1))
    record('remove-ancestor-subtree', lambda: model.removeRows(3, 1))

    model, selection, record = setup()
    selection.setCurrentIndex(model.index(1, 0), flags.ClearAndSelect)
    record('sort-remaps-selection-current', lambda: model.sort(0, getattr(Qt, 'SortOrder', Qt).DescendingOrder))
    model, selection, record = setup()
    selection.select(QItemSelection(model.index(0, 0), model.index(2, 1)), flags.ClearAndSelect)
    record('sort-reverses-range-corners', lambda: model.sort(0, getattr(Qt, 'SortOrder', Qt).DescendingOrder))
    record('remove-selected-after-layout', lambda: model.removeRows(3, 1))
    record('insert-inside-range-after-layout', lambda: model.insertRows(3, 1))
    model, selection, record = setup()
    rng = random.Random(68031)
    commands = (flags.ClearAndSelect, flags.Select, flags.Toggle, flags.SelectCurrent,
                flags.ToggleCurrent, flags.Deselect | flags.Current)
    for number in range(250):
        operation = rng.choice(('select', 'current', 'insert', 'remove', 'columns'))
        rows, columns = model.rowCount(), model.columnCount()
        if operation == 'select' and rows and columns:
            a = model.index(rng.randrange(rows), rng.randrange(columns))
            b = model.index(rng.randrange(rows), rng.randrange(columns))
            area = QItemSelection(a, b)
            command = rng.choice(commands)
            action = lambda area=area, command=command: selection.select(area, command)
        elif operation == 'current' and rows and columns:
            index = model.index(rng.randrange(rows), rng.randrange(columns))
            action = lambda index=index: selection.setCurrentIndex(index, flags.NoUpdate)
        elif operation == 'insert' and rows < 9:
            row = rng.randrange(rows + 1)
            action = lambda row=row: model.insertRows(row, 1)
        elif operation == 'remove' and rows:
            row = rng.randrange(rows)
            action = lambda row=row: model.removeRows(row, 1)
        else:
            count = rng.randrange(5)
            action = lambda count=count: model.setColumnCount(count)
        record('seed-%03d-%s' % (number, operation), action)
    print('QT_ORACLE_JSON:' + json.dumps({'version': version, 'trace': trace, 'ranges': {}}, sort_keys=True))


if __name__ == '__main__':
    main()
