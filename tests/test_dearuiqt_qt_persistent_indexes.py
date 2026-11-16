"""Persistent-index structural contracts; no renderer or Qt runtime required."""
import gc
from pathlib import Path
import sys
import unittest
import weakref

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from DearUIQt.QtCore import QPersistentModelIndex, QModelIndex, QAbstractTableModel, Qt
from DearUIQt.QtGui import QStandardItem, QStandardItemModel


class PersistentIndexTests(unittest.TestCase):
    def model(self):
        model = QStandardItemModel()
        for text in ('z', 'a', 'm'):
            model.appendRow([QStandardItem(text), QStandardItem(text + ' column')])
        self.addCleanup(model.delete)
        return model

    def test_insert_and_remove_before_preserve_item_and_notify_after_remap(self):
        model = self.model()
        index = QPersistentModelIndex(model.index(2, 1))
        events = []
        model.rowsAboutToBeInserted.connect(lambda *args: events.append(index.row()))
        model.rowsInserted.connect(lambda *args: events.append(index.row()))
        model.insertRows(0, 2)
        self.assertEqual(events, [2, 4])
        model.removeRows(0, 1)
        self.assertEqual(index.row(), 3)
        self.assertEqual(index.data(), 'm column')

    def test_removed_index_stays_invalid_after_reinsert(self):
        model = self.model()
        index = QPersistentModelIndex(model.index(1, 0))
        taken = model.takeRow(1)
        self.assertFalse(index.isValid())
        self.assertEqual((index.row(), index.column(), index.model(), index.data()), (-1, -1, None, None))
        model.appendRow(taken)
        self.assertFalse(index.isValid())
        self.assertFalse(index.parent().isValid())

    def test_removing_parent_invalidates_all_descendants(self):
        model = self.model()
        parent = model.item(1, 0)
        child = QStandardItem('child')
        child.appendRow(QStandardItem('grandchild'))
        parent.appendRow(child)
        indexes = [QPersistentModelIndex(item.index()) for item in (parent, child, child.child(0))]
        model.removeRows(1, 1)
        self.assertFalse(any(index.isValid() for index in indexes))

    def test_ancestor_shift_updates_descendant_parent_path(self):
        model = self.model()
        model.item(1, 0).appendRow(QStandardItem('child'))
        index = QPersistentModelIndex(model.item(1, 0).child(0).index())
        model.insertRows(0, 2)
        self.assertEqual((index.row(), index.parent().row(), index.data()), (0, 3, 'child'))
        model.removeRows(0, 1)
        self.assertEqual(index.parent().row(), 2)

    def test_unrelated_parent_mutation_does_not_shift_index(self):
        model = self.model()
        for row in (0, 1):
            model.item(row, 0).appendRow(QStandardItem('child'))
        index = QPersistentModelIndex(model.item(0, 0).child(0).index())
        model.insertRows(0, 2, model.index(1, 0))
        self.assertEqual((index.row(), index.parent().row()), (0, 0))

    def test_column_removal_invalidates_cells_and_subtrees(self):
        model = self.model()
        model.item(0, 1).appendRow(QStandardItem('child'))
        kept = QPersistentModelIndex(model.index(0, 0))
        removed = QPersistentModelIndex(model.index(0, 1))
        child = QPersistentModelIndex(model.item(0, 1).child(0).index())
        model.setColumnCount(1)
        self.assertTrue(kept.isValid())
        self.assertFalse(removed.isValid())
        self.assertFalse(child.isValid())

    def test_replacing_item_keeps_cell_handle_but_invalidates_descendants(self):
        model = self.model()
        model.item(0, 0).appendRow(QStandardItem('child'))
        cell = QPersistentModelIndex(model.index(0, 0))
        child = QPersistentModelIndex(model.item(0, 0).child(0).index())
        model.setItem(0, 0, QStandardItem('replacement'))
        self.assertEqual(cell.data(), 'replacement')
        self.assertFalse(child.isValid())
        model.setItem(0, 0, None)
        self.assertFalse(cell.isValid())

    def test_take_item_invalidates_cell_without_resurrection(self):
        model = self.model()
        cell = QPersistentModelIndex(model.index(0, 0))
        item = model.takeItem(0, 0)
        model.setItem(0, 0, item)
        self.assertFalse(cell.isValid())

    def test_empty_cell_materialization_preserves_persistent_identity(self):
        model = QStandardItemModel(2, 1)
        self.addCleanup(model.delete)
        cell = QPersistentModelIndex(model.index(1, 0))
        self.assertIsNone(model.item(1))
        model.insertRows(0, 1)
        model.setData(model.index(2, 0), 'filled')
        self.assertEqual((cell.row(), cell.data()), (2, 'filled'))

    def test_reset_invalidates_before_model_reset_observers(self):
        model = self.model()
        cell = QPersistentModelIndex(model.index(0, 0))
        events = []
        model.modelAboutToBeReset.connect(lambda: events.append(cell.isValid()))
        model.modelReset.connect(lambda: events.append(cell.isValid()))
        model.beginResetModel()
        model.endResetModel()
        self.assertEqual(events, [True, False])

    def test_delete_invalidates_and_releases_model_reference(self):
        model = self.model()
        cell = QPersistentModelIndex(model.index(0, 0))
        model.delete()
        self.assertFalse(cell.isValid())
        self.assertIsNone(cell.model())

    def test_registry_does_not_keep_unused_handles_alive(self):
        model = self.model()
        cell = QPersistentModelIndex(model.index(0, 0))
        reference = weakref.ref(cell)
        del cell
        gc.collect()
        self.assertIsNone(reference())
        self.assertEqual(model.persistentIndexList(), [])

    def test_copy_equality_conversion_and_unique_registry_queries(self):
        model = self.model()
        original = model.index(0, 0)
        cell = QPersistentModelIndex(original)
        copy = QPersistentModelIndex(cell)
        self.assertEqual(cell, copy)
        self.assertEqual(QModelIndex(cell), original)
        self.assertEqual(QModelIndex(original), original)
        self.assertEqual(model.persistentIndexList(), [original])
        model.insertRows(0, 1)
        self.assertEqual((cell.row(), copy.row()), (1, 1))

    def test_layout_remapping_applies_simultaneously_to_all_copies(self):
        model = self.model()
        first, second = model.index(0, 0), model.index(1, 0)
        a, b, c = QPersistentModelIndex(first), QPersistentModelIndex(second), QPersistentModelIndex(first)
        model.changePersistentIndexList([first, second], [second, first])
        self.assertEqual([QModelIndex(index) for index in (a, b, c)], [second, first, second])

    def test_sort_remaps_before_layout_changed(self):
        model = self.model()
        cell = QPersistentModelIndex(model.index(0, 0))
        events = []
        model.layoutAboutToBeChanged.connect(lambda *args: events.append(cell.row()))
        model.layoutChanged.connect(lambda *args: events.append(cell.row()))
        model.sort(0)
        self.assertEqual(events, [0, 2])
        model.invisibleRootItem().sortChildren(0, Qt.DescendingOrder)
        self.assertEqual((cell.row(), cell.data()), (0, 'z'))

    def test_pointerless_base_protocol_remaps_rows_and_columns(self):
        class Flat(QAbstractTableModel):
            rows, columns = 3, 2
            def rowCount(self, parent=QModelIndex()):
                return 0 if parent.isValid() else self.rows
            def columnCount(self, parent=QModelIndex()):
                return 0 if parent.isValid() else self.columns
        model = Flat()
        self.addCleanup(model.delete)
        cell = QPersistentModelIndex(model.index(2, 1))
        model.beginInsertRows(QModelIndex(), 1, 2)
        model.rows += 2
        model.endInsertRows()
        model.beginInsertColumns(QModelIndex(), 0, 0)
        model.columns += 1
        model.endInsertColumns()
        self.assertEqual((cell.row(), cell.column()), (4, 2))
        model.beginRemoveColumns(QModelIndex(), 2, 2)
        model.columns -= 1
        model.endRemoveColumns()
        self.assertFalse(cell.isValid())

    def test_handle_created_during_about_to_is_included_in_transaction(self):
        model = self.model()
        cells = []
        model.rowsAboutToBeInserted.connect(lambda *args: cells.append(QPersistentModelIndex(model.index(1, 0))))
        model.insertRows(0, 1)
        self.assertEqual((cells[0].row(), cells[0].data()), (2, 'a'))


if __name__ == '__main__':
    unittest.main(verbosity=2)
