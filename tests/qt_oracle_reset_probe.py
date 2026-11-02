"""Reset observer ordering, silent selection invalidation and repopulation."""
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
        from PySide6.QtCore import QAbstractTableModel, QModelIndex, QPersistentModelIndex, QItemSelectionModel, qVersion
        version = qVersion()
    else:
        sys.path.insert(0, str(Path(args.root).resolve()))
        from DearUIQt.QtCore import QAbstractTableModel, QModelIndex, QPersistentModelIndex, QItemSelectionModel
        version = 'Qt-6.8-subset'
    flags = getattr(QItemSelectionModel, 'SelectionFlag', QItemSelectionModel)
    trace = []

    class Model(QAbstractTableModel):
        def __init__(self):
            super().__init__()
            self.values = [['old0', 'old1'], ['old2', 'old3']]
        def rowCount(self, parent=QModelIndex()):
            return 0 if parent.isValid() else len(self.values)
        def columnCount(self, parent=QModelIndex()):
            return 0 if parent.isValid() or not self.values else len(self.values[0])
        def data(self, index, role=0):
            return (self.values[index.row()][index.column()]
                    if index.isValid() and int(role) == 0 and 0 <= index.row() < self.rowCount()
                    and 0 <= index.column() < self.columnCount() else None)

    for action in ('query', 'select-early', 'select-late'):
        model = Model()
        selection = None
        events = []
        persistent = QPersistentModelIndex(model.index(1, 0))
        def key(index):
            return [index.row(), index.column()] if index.isValid() else None
        def state():
            return {'current': key(selection.currentIndex()), 'current_data': selection.currentIndex().data(),
                    'selected': sorted(key(index) for index in selection.selectedIndexes()),
                    'persistent': key(persistent), 'persistent_data': persistent.data()}
        def early_reset():
            events.append({'signal': 'early-modelReset', 'state': state()})
            if action == 'select-early' and model.rowCount():
                selection.select(model.index(0, 0), flags.Select)
                events.append({'signal': 'early-after-select', 'state': state()})
        model.modelReset.connect(early_reset)
        selection = QItemSelectionModel(model)
        selection.setCurrentIndex(model.index(1, 0), flags.ClearAndSelect)
        selection.selectionChanged.connect(lambda added, removed: events.append({
            'signal': 'selection', 'added': sorted(key(index) for index in added.indexes()),
            'removed': sorted(key(index) for index in removed.indexes()), 'state': state()}))
        selection.currentChanged.connect(lambda *args: events.append({'signal': 'current', 'state': state()}))
        model.modelAboutToBeReset.connect(lambda: events.append({'signal': 'modelAboutToBeReset', 'state': state()}))
        def late_reset():
            events.append({'signal': 'late-modelReset', 'state': state()})
            if action == 'select-late' and model.rowCount():
                selection.select(model.index(0, 0), flags.Select)
                events.append({'signal': 'late-after-select', 'state': state()})
        model.modelReset.connect(late_reset)
        for iteration, values in enumerate(([['new0', 'new1'], ['new2', 'new3']], [], [['again']])):
            events.clear()
            model.beginResetModel()
            model.values = values
            model.endResetModel()
            trace.append({'name': '%s-%d' % (action, iteration), 'state': state(), 'events': list(events)})
    print('QT_ORACLE_JSON:' + json.dumps({'version': version, 'trace': trace, 'ranges': {}}, sort_keys=True))


if __name__ == '__main__':
    main()
