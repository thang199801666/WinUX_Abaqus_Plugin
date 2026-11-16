"""Qt checkIndex boolean/options contract and bounded model invariant audit."""
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
        from PySide6.QtCore import QAbstractItemModel, QModelIndex, QPersistentModelIndex, qVersion
        from PySide6.QtGui import QStandardItemModel, QStandardItem
        version = qVersion()
    else:
        sys.path.insert(0, str(Path(args.root).resolve()))
        from DearUIQt.QtCore import QAbstractItemModel, QModelIndex, QPersistentModelIndex
        from DearUIQt.QtGui import QStandardItemModel, QStandardItem
        version = 'Qt-6.8-subset'
    class Model(QAbstractItemModel):
        def __init__(self):
            super().__init__()
            self.parent_calls = 0
        def rowCount(self, parent=QModelIndex()):
            return 0 if parent.isValid() else 2
        def columnCount(self, parent=QModelIndex()):
            return 0 if parent.isValid() else 2
        def index(self, row, column, parent=QModelIndex()):
            return self.createIndex(row, column) if not parent.isValid() and 0 <= row < 2 and 0 <= column < 2 else QModelIndex()
        def parent(self, index):
            self.parent_calls += 1
            return QModelIndex()
    model, other = Model(), Model()
    flags = QAbstractItemModel.CheckIndexOption
    trace = []
    indexes = [('invalid', QModelIndex()), ('valid', model.index(1, 1)),
               ('foreign', other.index(0, 0)), ('out-row', model.createIndex(5, 0)),
               ('out-column', model.createIndex(0, 5)), ('negative-invalid', model.createIndex(-1, 0)),
               ('persistent', QPersistentModelIndex(model.index(0, 1)))]
    for name, index in indexes:
        for value in range(8):
            model.parent_calls = 0
            result = model.checkIndex(index, flags(value))
            trace.append({'name': '%s-%d' % (name, value), 'result': result, 'parent_calls': model.parent_calls})
    standard = QStandardItemModel()
    parent = QStandardItem('parent')
    parent.appendRow(QStandardItem('child'))
    standard.appendRow(parent)
    for value in range(8):
        trace.append({'name': 'nested-%d' % value, 'result': standard.checkIndex(parent.child(0).index(), flags(value))})
    # Both engines execute the same test-only invariant traversal. The runner
    # prepends its source for Qt so it never imports the workspace.
    try:
        audit = assert_model_consistent
    except NameError:
        from model_conformance import assert_model_consistent as audit
    tester_failures, tester = [], None
    previous_handler = None
    if args.engine == 'qt':
        from PySide6.QtCore import qInstallMessageHandler, QtMsgType
        from PySide6.QtTest import QAbstractItemModelTester
        def message_handler(kind, context, message):
            warning = kind in (QtMsgType.QtWarningMsg, QtMsgType.QtCriticalMsg, QtMsgType.QtFatalMsg)
            if (warning and context.category == 'qt.modeltest') or message.startswith('FAIL!'):
                tester_failures.append(message)
        previous_handler = qInstallMessageHandler(message_handler)
        tester = QAbstractItemModelTester(standard, QAbstractItemModelTester.FailureReportingMode.Warning)
        tester.setUseFetchMore(False)
    for name, action in [('initial', lambda: None), ('insert-rows', lambda: standard.insertRows(0, 2)),
                         ('insert-columns', lambda: standard.insertColumns(0, 1)),
                         ('sort', lambda: standard.sort(0)), ('remove-columns', lambda: standard.removeColumns(0, 1)),
                         ('remove-rows', lambda: standard.removeRows(0, 1))]:
        action()
        trace.append({'name': 'invariants-' + name, 'visited': audit(standard, QModelIndex())})
    if args.engine == 'qt':
        qInstallMessageHandler(previous_handler)
        if tester_failures:
            raise AssertionError('Real Qt model tester failures: ' + repr(tester_failures))
    result = {'version': version, 'trace': trace, 'ranges': {}}
    if args.engine == 'qt':
        result['observations'] = {'real_qt_model_tester_failures': tester_failures}
        result['comparison_notes'] = ['Qt engine also ran real QAbstractItemModelTester with zero failures. '
                                      'DearUIQt uses a bounded test-only invariant helper, not the full Qt tester.']
    print('QT_ORACLE_JSON:' + json.dumps(result, sort_keys=True))


if __name__ == '__main__':
    main()
