"""Qt-oriented column count/convenience transactions and ownership."""
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from DearUIQt.QtCore import QPersistentModelIndex, QItemSelectionModel, QItemSelection
from DearUIQt.QtGui import QStandardItemModel, QStandardItem


class ColumnTransactionTests(unittest.TestCase):
    def setUp(self):
        self.model = QStandardItemModel()
        for row in range(3):
            self.model.appendRow([QStandardItem('%d:%d' % (row, col)) for col in range(3)])
        self.addCleanup(self.model.delete)

    def test_insert_observers_see_old_then_new_columns_and_valid_empty_indexes(self):
        events = []
        self.model.columnsAboutToBeInserted.connect(lambda *args: events.append(self.model.columnCount()))
        self.model.columnsInserted.connect(lambda *args: events.append(self.model.columnCount()))
        self.assertTrue(self.model.insertColumns(1, 2))
        self.assertEqual(events, [3, 5])
        self.assertEqual(self.model.item(0, 3).text(), '0:1')
        self.assertTrue(self.model.index(0, 1).isValid())
        self.assertIsNone(self.model.item(0, 1))
        self.assertIsNone(self.model.index(0, 1).data())

    def test_strict_model_counts_reject_invalid_without_signals(self):
        events = []
        self.model.columnsAboutToBeInserted.connect(lambda *args: events.append(args))
        self.model.columnsAboutToBeRemoved.connect(lambda *args: events.append(args))
        for col, count in ((-1, 1), (4, 1), (0, 0), (0, -1)):
            self.assertFalse(self.model.insertColumns(col, count))
        for col, count in ((-1, 1), (3, 1), (2, 2), (0, 0), (0, -1)):
            self.assertFalse(self.model.removeColumns(col, count))
        self.assertEqual(events, [])

    def test_remove_column_detaches_subtree_invalidates_and_reindexes_survivors(self):
        item = self.model.item(0, 1)
        item.appendRow(QStandardItem('child'))
        child = QPersistentModelIndex(item.child(0).index())
        tail = QPersistentModelIndex(self.model.index(0, 2))
        self.assertTrue(self.model.removeColumns(1, 1))
        self.assertIsNone(item.model())
        self.assertFalse(child.isValid())
        self.assertEqual((tail.column(), tail.data()), (1, '0:2'))

    def test_take_column_and_reinsert_preserve_items_not_old_handles(self):
        old = QPersistentModelIndex(self.model.index(1, 1))
        taken = self.model.takeColumn(1)
        self.assertEqual([item.text() for item in taken], ['0:1', '1:1', '2:1'])
        self.assertTrue(all(item.model() is None and item.parent() is None for item in taken))
        self.assertFalse(old.isValid())
        self.assertIsNone(self.model.insertColumn(0, taken))
        self.assertIs(self.model.item(1, 0), taken[1])
        self.assertFalse(old.isValid())

    def test_zero_row_column_count_changes_are_real_transactions(self):
        model = QStandardItemModel()
        self.addCleanup(model.delete)
        self.assertTrue(model.insertColumns(0, 2))
        self.assertEqual((model.rowCount(), model.columnCount()), (0, 2))
        self.assertEqual(model.takeColumn(0), [])
        self.assertEqual(model.columnCount(), 1)
        self.assertTrue(model.removeColumn(0))
        self.assertEqual(model.columnCount(), 0)

    def test_insert_inside_selected_rectangle_does_not_select_new_column(self):
        selection = QItemSelectionModel(self.model)
        self.addCleanup(selection.delete)
        selection.select(QItemSelection(self.model.index(0, 0), self.model.index(2, 2)), selection.ClearAndSelect)
        self.model.insertColumns(1, 1)
        self.assertEqual(len(selection.selectedIndexes()), 9)
        self.assertFalse(selection.isSelected(self.model.index(1, 1)))
        self.model.removeColumns(1, 1)
        self.assertEqual(len(selection.selectedIndexes()), 9)

    def test_nested_current_column_fallback_matches_qt68_root_count_quirk(self):
        parent = self.model.item(0, 0)
        parent.appendRow([QStandardItem('child') for _ in range(6)])
        selection = QItemSelectionModel(self.model)
        self.addCleanup(selection.delete)
        selection.setCurrentIndex(parent.child(0, 0).index(), selection.ClearAndSelect)
        self.assertTrue(self.model.removeColumns(0, 4, parent.index()))
        self.assertEqual(parent.columnCount(), 2)
        self.assertFalse(selection.currentIndex().isValid())

    def test_item_count_insert_past_end_pads_gap_unlike_strict_model(self):
        root = self.model.invisibleRootItem()
        self.assertIsNone(root.insertColumns(5, 1))
        self.assertEqual(root.columnCount(), 6)
        self.assertIsNone(root.child(0, 3))
        self.assertFalse(self.model.insertColumns(7, 1))
        root.removeColumns(0, 99)
        self.assertEqual(root.columnCount(), 6)

    def test_append_column_expands_rows_before_inserting_column(self):
        events = []
        self.model.rowsInserted.connect(lambda *args: events.append(('rows', self.model.rowCount(), self.model.columnCount())))
        self.model.columnsInserted.connect(lambda *args: events.append(('columns', self.model.rowCount(), self.model.columnCount())))
        self.model.appendColumn([QStandardItem(str(i)) for i in range(5)])
        self.assertEqual(events, [('rows', 5, 3), ('columns', 5, 4)])
        self.assertEqual(self.model.item(4, 3).text(), '4')

    def test_duplicate_or_owned_column_items_are_rejected_before_expanding(self):
        item = QStandardItem('new')
        with self.assertRaises(ValueError):
            self.model.appendColumn([item] * 5)
        with self.assertRaises(ValueError):
            self.model.appendColumn([QStandardItem('new')] * 4 + [self.model.item(0, 0)])
        self.assertEqual((self.model.rowCount(), self.model.columnCount()), (3, 3))
        self.assertIsNone(item.model())

    def test_foreign_and_detached_parent_rejected(self):
        other = QStandardItemModel(1, 1)
        self.addCleanup(other.delete)
        self.assertFalse(self.model.insertColumns(0, 1, other.index(0, 0)))
        parent = self.model.index(0, 0)
        self.model.takeItem(0, 0)
        self.assertFalse(self.model.insertColumns(0, 1, parent))
        self.assertFalse(self.model.removeColumns(0, 1, parent))

    def test_column_about_exception_and_reentry_do_not_poison_transaction(self):
        def fail(*args):
            with self.assertRaises(RuntimeError):
                self.model.insertColumns(0, 1)
            raise ValueError('observer failed')
        connection = self.model.columnsAboutToBeInserted.connect(fail)
        with self.assertRaisesRegex(ValueError, 'observer failed'):
            self.model.insertColumns(0, 1)
        self.assertEqual(self.model.columnCount(), 3)
        self.assertFalse(self.model._change_stack)
        connection.disconnect()
        self.assertTrue(self.model.insertColumn(0))


if __name__ == '__main__':
    unittest.main(verbosity=2)
