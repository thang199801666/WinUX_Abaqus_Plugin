"""Serializable selection scenarios, executed with either DearUIQt or real Qt."""
import argparse
import json
from pathlib import Path
import random
import sys


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--engine', choices=('qt', 'dearuiqt'), required=True)
    parser.add_argument('--root', default='.')
    options = parser.parse_args()
    if options.engine == 'qt':
        from PySide6.QtCore import QItemSelectionModel, QItemSelection, QItemSelectionRange, QModelIndex, Qt, qVersion
        from PySide6.QtGui import QStandardItemModel, QStandardItem
        version = qVersion()
    else:
        sys.path.insert(0, str(Path(options.root).resolve()))
        from DearUIQt.QtCore import QItemSelectionModel, QItemSelection, QItemSelectionRange, QModelIndex, Qt
        from DearUIQt.QtGui import QStandardItemModel, QStandardItem
        version = 'Qt-6.8-subset'

    def flat(rows=4, columns=3):
        model = QStandardItemModel()
        for row in range(rows):
            model.appendRow([QStandardItem('%d:%d' % (row, column)) for column in range(columns)])
        return model

    def key(index):
        if not index.isValid():
            return None
        path = []
        while index.isValid():
            path.append([index.row(), index.column()])
            index = index.parent()
        return path[::-1]

    def keys(indexes):
        return sorted([key(index) for index in indexes], key=lambda value: json.dumps(value))

    def snapshot(selection):
        model = selection.model()
        return {'selected': keys(selection.selectedIndexes()), 'current': key(selection.currentIndex()),
                'has': selection.hasSelection(), 'rows': keys(selection.selectedRows()),
                'columns': keys(selection.selectedColumns()),
                'full_rows': [selection.isRowSelected(row) for row in range(model.rowCount())],
                'full_columns': [selection.isColumnSelected(column) for column in range(model.columnCount())],
                'row_intersects': [selection.rowIntersectsSelection(row) for row in range(model.rowCount())],
                'column_intersects': [selection.columnIntersectsSelection(column) for column in range(model.columnCount())]}

    model = flat()
    selection = QItemSelectionModel(model)
    flags = getattr(QItemSelectionModel, 'SelectionFlag', QItemSelectionModel)
    events = []
    selection.selectionChanged.connect(lambda added, removed: events.append(
        ['selection', keys(added.indexes()), keys(removed.indexes())]))
    selection.currentChanged.connect(lambda current, previous: events.append(['current', key(current), key(previous)]))
    selection.currentRowChanged.connect(lambda current, previous: events.append(['row', key(current), key(previous)]))
    selection.currentColumnChanged.connect(lambda current, previous: events.append(['column', key(current), key(previous)]))
    trace = []
    def record(name):
        trace.append({'name': name, 'state': snapshot(selection), 'events': list(events)})
        events.clear()

    selection.setCurrentIndex(model.index(0, 0), flags.NoUpdate)
    record('keyboard-current')
    operations = [(['Select'], [(0, 0)]), (['Select'], [(1, 0)]),
                  (['SelectCurrent'], [(2, 0)]), (['ToggleCurrent'], [(0, 0)]),
                  (['ClearAndSelect', 'Rows', 'Columns'], [(1, 1)]),
                  (['Toggle'], [(1, 1), (1, 1)]),
                  (['ClearAndSelect'], [(0, 0), (0, 1), (0, 2)]),
                  (['Select', 'Deselect'], [(0, 0)]),
                  (['Toggle', 'Deselect'], [(0, 1)]),
                  (['Select', 'Toggle'], [(0, 2)]),
                  (['Deselect', 'Current'], [(0, 0)])]
    rng = random.Random(68012)
    for _ in range(1000):
        names = [rng.choice(['Select', 'Deselect', 'Toggle', 'SelectCurrent', 'ToggleCurrent',
                             'ClearAndSelect', 'Current'])]
        expansion = rng.choice([None, 'Rows', 'Columns'])
        if expansion: names.append(expansion)
        # One rectangle/cell per random command: multi-range overlap is tested
        # separately, rather than obscuring the basic two-layer oracle trace.
        operations.append((names, [(rng.randrange(4), rng.randrange(3))]))
    for number, (names, coordinates) in enumerate(operations):
        command = flags.NoUpdate
        for name in names: command |= getattr(flags, name)
        area = QItemSelection()
        for row, column in coordinates:
            index = model.index(row, column)
            area.select(index, index)
        selection.select(area, command)
        record('%03d:%s' % (number, '|'.join(names)))
    selection.clearSelection()
    record('clear-selection')
    selection.clearCurrentIndex()
    record('clear-current')
    selection.setCurrentIndex(model.index(1, 2), flags.ClearAndSelect)
    events.clear()
    selection.reset()
    record('silent-reset')
    selection.select(QItemSelection(model.index(0, 0), model.index(0, 2)), flags.Select)
    model.item(0, 1).setEnabled(False)
    model.item(0, 2).setSelectable(False)
    record('disabled-unselectable')
    selection.select(QItemSelection(), flags.Select)  # Commit before interactive replacement.
    selection.select(model.index(0, 1), flags.Deselect | flags.Current)
    record('deselect-current-disabled')
    selection.select(model.index(0, 2), flags.ToggleCurrent)
    record('toggle-current-unselectable')
    area = QItemSelectionRange(model.index(0, 0), model.index(2, 1))
    ranges = {'valid': area.isValid(), 'width': area.width(), 'height': area.height(),
              'indexes': keys(area.indexes()), 'empty': area.isEmpty(),
              'default_width': QItemSelectionRange().width(),
              'reversed_valid': QItemSelectionRange(model.index(2, 2), model.index(0, 0)).isValid()}
    print('QT_ORACLE_JSON:' + json.dumps({'engine': options.engine, 'version': version,
                                         'trace': trace, 'ranges': ranges}, sort_keys=True))


if __name__ == '__main__':
    main()
