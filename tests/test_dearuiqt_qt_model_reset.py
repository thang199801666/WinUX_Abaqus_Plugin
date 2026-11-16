"""Qt reset visibility and DearUIQt transaction safety policies."""
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from DearUIQt.QtCore import QAbstractTableModel, QModelIndex, QItemSelectionModel, QPersistentModelIndex
from DearUIQt.QtGui import QStandardItemModel, QStandardItem


class ResettableTable(QAbstractTableModel):
    def __init__(self):
        super().__init__()
        self.values = [['old0', 'old1'], ['old2', 'old3']]

    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.values)

    def columnCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() or not self.values else len(self.values[0])

    def data(self, index, role=0):
        return (self.values[index.row()][index.column()] if index.isValid() and int(role) == 0
                and 0 <= index.row() < self.rowCount() and 0 <= index.column() < self.columnCount() else None)

    def resetTo(self, values):
        self.beginResetModel()
        self.values = values
        self.endResetModel()


class ModelResetTests(unittest.TestCase):
    def setUp(self):
        self.model = ResettableTable()
        self.addCleanup(self.model.delete)

    def selection(self):
        selection = QItemSelectionModel(self.model)
        self.addCleanup(selection.delete)
        selection.setCurrentIndex(self.model.index(1, 0), selection.ClearAndSelect)
        return selection

    def test_early_model_reset_observer_sees_empty_selection_invalid_current(self):
        observations = []
        selection = None
        self.model.modelReset.connect(lambda: observations.append((
            selection.currentIndex().isValid(), selection.selectedIndexes())))
        selection = self.selection()
        persistent = QPersistentModelIndex(self.model.index(1, 0))
        self.model.resetTo([['new0'], ['new1']])
        self.assertEqual(observations, [(False, [])])
        self.assertFalse(persistent.isValid())

    def test_selection_created_in_early_reset_observer_is_cleared_by_later_qt_slot(self):
        selection = None
        self.model.modelReset.connect(lambda: selection.select(self.model.index(0, 0), selection.Select))
        selection = self.selection()
        events = []
        selection.selectionChanged.connect(lambda added, removed: events.append((added.indexes(), removed.indexes())))
        self.model.resetTo([['new']])
        self.assertEqual(events, [([self.model.index(0, 0)], [])])
        self.assertFalse(selection.hasSelection())

    def test_selection_created_in_late_reset_observer_persists(self):
        selection = self.selection()
        self.model.modelReset.connect(lambda: selection.select(self.model.index(0, 0), selection.Select))
        self.model.resetTo([['new']])
        self.assertEqual(selection.selectedIndexes(), [self.model.index(0, 0)])

    def test_about_to_sees_old_state_and_reset_emits_no_selection_current_delta(self):
        selection = self.selection()
        about, events = [], []
        self.model.modelAboutToBeReset.connect(lambda: about.append(selection.currentIndex().data()))
        selection.currentChanged.connect(lambda *args: events.append(args))
        selection.selectionChanged.connect(lambda *args: events.append(args))
        self.model.resetTo([])
        self.assertEqual(about, ['old2'])
        self.assertEqual(events, [])
        self.assertFalse(selection.currentIndex().isValid())

    def test_about_exception_releases_guard_without_mutating_storage(self):
        def fail():
            raise ValueError('about failed')
        connection = self.model.modelAboutToBeReset.connect(fail)
        with self.assertRaisesRegex(ValueError, 'about failed'):
            self.model.resetTo([])
        self.assertEqual(self.model.rowCount(), 2)
        self.assertFalse(self.model._reset_active)
        self.assertFalse(self.model._change_stack)
        connection.disconnect()
        self.model.resetTo([])

    def test_nested_structural_mutations_are_rejected_during_reset(self):
        standard = QStandardItemModel(1, 1)
        self.addCleanup(standard.delete)
        def about():
            for action in (standard.beginResetModel, lambda: standard.appendRow(QStandardItem('unsafe')),
                           lambda: standard.beginInsertRows(QModelIndex(), 0, 0),
                           lambda: standard.beginMoveColumns(QModelIndex(), 0, 0, QModelIndex(), 1)):
                with self.assertRaises(RuntimeError):
                    action()
        standard.modelAboutToBeReset.connect(about)
        standard.clear()
        self.assertEqual(standard.rowCount(), 0)
        self.assertFalse(standard._reset_active)

    def test_mismatched_end_reset_does_not_consume_an_insert_transaction(self):
        self.model.beginInsertRows(QModelIndex(), 0, 0)
        with self.assertRaises(RuntimeError):
            self.model.endResetModel()
        self.assertEqual(self.model._change_stack[-1][0], 'insert_rows')
        self.model.values.insert(0, ['inserted0', 'inserted1'])
        self.model.endInsertRows()
        self.assertFalse(self.model._change_stack)

    def test_completed_exception_does_not_poison_next_reset(self):
        def fail():
            raise ValueError('completed failed')
        connection = self.model.modelReset.connect(fail)
        with self.assertRaisesRegex(ValueError, 'completed failed'):
            self.model.resetTo([])
        self.assertFalse(self.model._reset_active)
        self.assertFalse(self.model._change_stack)
        connection.disconnect()
        self.model.resetTo([['new']])
        self.assertEqual(self.model.index(0, 0).data(), 'new')


if __name__ == '__main__':
    unittest.main(verbosity=2)
