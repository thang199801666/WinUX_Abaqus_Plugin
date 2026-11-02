"""Item-owned row resizing: Qt subset and DearUIQt transaction safeguards."""
from pathlib import Path
import random
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from DearUIQt.QtCore import QItemSelectionModel, QPersistentModelIndex, Qt
from DearUIQt.QtGui import QStandardItem, QStandardItemModel


class ItemRowCountTests(unittest.TestCase):
    def setUp(self):
        self.model = QStandardItemModel(2, 2)
        self.item = QStandardItem('parent')
        for row in range(3):
            self.item.appendRow([QStandardItem('%d:a' % row), QStandardItem('%d:b' % row)])
        self.model.setItem(0, 0, self.item)
        self.addCleanup(self.model.delete)

    def record(self):
        events = []
        for name in ('rowsAboutToBeInserted', 'rowsInserted', 'rowsAboutToBeRemoved', 'rowsRemoved'):
            getattr(self.model, name).connect(lambda parent, first, last, name=name: events.append(
                (name, parent, first, last, self.item.rowCount())))
        return events

    def test_detached_zero_column_rows_grow_and_shrink_without_items(self):
        item = QStandardItem()
        self.assertIsNone(item.setRowCount(5))
        self.assertEqual((item.rowCount(), item.columnCount()), (5, 0))
        self.assertIsNone(item.child(0))
        item.setRowCount(2)
        self.assertEqual((item.rowCount(), item.columnCount()), (2, 0))
        item.setRowCount(0)
        self.assertEqual(item.rowCount(), 0)

    def test_detached_resize_preserves_columns_and_surviving_ownership(self):
        item = QStandardItem()
        children = [QStandardItem('a'), QStandardItem('b')]
        for child in children:
            item.appendRow([child, QStandardItem('second')])
        item.setRowCount(1)
        self.assertIs(item.child(0), children[0])
        self.assertIs(children[0].parent(), item)
        # DearUIQt retained removed items detach; Qt deletes wrappers instead.
        self.assertIsNone(children[1].parent())
        item.setRowCount(4)
        self.assertEqual(item.columnCount(), 2)
        self.assertTrue(all(item.child(row, col) is None for row in range(1, 4) for col in range(2)))

    def test_attached_growth_is_one_transaction_with_lazy_empty_cells(self):
        events = self.record()
        parent = self.item.index()
        self.item.setRowCount(100)
        self.assertEqual(events, [('rowsAboutToBeInserted', parent, 3, 99, 3),
                                  ('rowsInserted', parent, 3, 99, 100)])
        self.assertTrue(self.model.index(99, 1, parent).isValid())
        self.assertIsNone(self.item.child(99, 1))
        self.assertEqual(self.item.columnCount(), 2)

    def test_shrink_invalidates_removed_subtree_and_remaps_current(self):
        self.item.child(2).appendRow(QStandardItem('descendant'))
        survivor = QPersistentModelIndex(self.item.child(0).index())
        removed = QPersistentModelIndex(self.item.child(2).index())
        descendant = QPersistentModelIndex(self.item.child(2).child(0).index())
        selection = QItemSelectionModel(self.model)
        self.addCleanup(selection.delete)
        selection.setCurrentIndex(self.item.child(2).index(), selection.Select | selection.Rows)
        events = self.record()
        parent = self.item.index()
        self.item.setRowCount(1)
        self.assertEqual(events, [('rowsAboutToBeRemoved', parent, 1, 2, 3),
                                  ('rowsRemoved', parent, 1, 2, 1)])
        self.assertTrue(survivor.isValid())
        self.assertFalse(removed.isValid())
        self.assertFalse(descendant.isValid())
        self.assertEqual(selection.currentIndex(), self.item.child(0).index())
        self.assertEqual(selection.selectedIndexes(), [])

    def test_equal_and_negative_counts_are_silent_noops(self):
        events = self.record()
        child = self.item.child(2)
        for count in (3, -1, -10):
            self.assertIsNone(self.item.setRowCount(count))
        self.assertEqual(self.item.rowCount(), 3)
        self.assertIs(self.item.child(2), child)
        self.assertEqual(events, [])

    def test_invisible_root_resizes_headers_and_preserves_column_count(self):
        self.model.setVerticalHeaderLabels(['first', 'second'])
        root = self.model.invisibleRootItem()
        root.setRowCount(1)
        self.assertEqual(self.model.rowCount(), 1)
        self.assertEqual(self.model.headerData(0, Qt.Vertical), 'first')
        root.setRowCount(3)
        self.assertEqual([self.model.headerData(row, Qt.Vertical) for row in range(3)], ['first', 2, 3])
        root.setRowCount(0)
        self.assertEqual((self.model.rowCount(), self.model.columnCount()), (0, 2))

    def test_about_to_reentry_is_rejected_before_mutation(self):
        def nested(*args):
            with self.assertRaises(RuntimeError):
                self.item.setRowCount(1)
        self.model.rowsAboutToBeInserted.connect(nested)
        self.item.setRowCount(5)
        self.assertEqual(self.item.rowCount(), 5)

    def test_about_to_exception_leaves_resize_reusable(self):
        def fail(*args):
            raise ValueError('observer failure')
        connection = self.model.rowsAboutToBeInserted.connect(fail)
        with self.assertRaisesRegex(ValueError, 'observer failure'):
            self.item.setRowCount(5)
        self.assertEqual(self.item.rowCount(), 3)
        connection.disconnect()
        self.item.setRowCount(5)
        self.assertEqual(self.item.rowCount(), 5)

    def test_completed_observer_can_start_followup_resize(self):
        def completed(*args):
            self.item.setRowCount(2)
        connection = self.model.rowsInserted.connect(completed)
        self.item.setRowCount(5)
        connection.disconnect()
        self.assertEqual(self.item.rowCount(), 2)
        self.item.setRowCount(4)
        self.assertEqual(self.item.rowCount(), 4)

    def test_seeded_counts_keep_model_dimensions_and_existing_survivors(self):
        rng = random.Random(68201)
        for step in range(100):
            before = self.item.rowCount()
            first = self.item.child(0) if before else None
            count = rng.randrange(-2, 12)
            with self.subTest(step=step, count=count):
                self.item.setRowCount(count)
                self.assertEqual(self.item.rowCount(), before if count < 0 else count)
                self.assertEqual(self.model.rowCount(self.item.index()), self.item.rowCount())
                self.assertEqual(self.item.columnCount(), 2)
                if count != 0 and before:
                    self.assertIs(self.item.child(0), first)


if __name__ == '__main__':
    unittest.main(verbosity=2)
