"""Standard-item bulk rows: range signals, metadata and subtree ownership."""
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from DearUIQt.core import QPersistentModelIndex
from DearUIQt.gui import QStandardItem, QStandardItemModel


class StandardItemRowTests(unittest.TestCase):
    def model(self, rows=0, columns=1):
        model = QStandardItemModel(rows, columns)
        for row in range(rows):
            for column in range(columns):
                model.setItem(row, column, QStandardItem())
        self.addCleanup(model.delete)
        return model

    def test_bulk_append_sends_one_range_and_reindexes_once(self):
        model = self.model()
        root = model.invisibleRootItem()
        rows = [QStandardItem(str(i)) for i in range(100)]
        events = []
        model.rowsInserted.connect(lambda parent, first, last: events.append((parent.isValid(), first, last)))
        with patch.object(root, '_reindex_children', wraps=root._reindex_children) as reindex:
            self.assertIsNone(root.appendRows(rows))
            reindex.assert_called_once_with(0)
        self.assertEqual(events, [(False, 0, 99)])
        for i, item in enumerate(rows):
            self.assertIs(model.item(i), item)
            self.assertIs(item.model(), model)
            self.assertEqual((item.row(), item.column()), (i, 0))

    def test_insert_middle_pads_columns_and_preserves_existing_items(self):
        model = self.model(5, 2)
        root = model.invisibleRootItem()
        old = [model.item(i) for i in range(5)]
        child = QStandardItem('nested')
        old[3].appendRow(child)
        persistent = QPersistentModelIndex(old[3].index())
        extra = [[QStandardItem('a')], [QStandardItem('b'), QStandardItem('c'), QStandardItem('d')]]
        root.insertRows(2, extra)
        self.assertEqual(model.columnCount(), 3)
        self.assertIsNone(model.item(0, 2))
        self.assertIsNone(model.item(2, 1))
        self.assertIs(model.item(5), old[3])
        self.assertEqual(persistent.row(), 5)
        self.assertIs(child.model(), model)
        self.assertEqual(model.parent(child.index()).row(), 5)

    def test_remove_middle_detaches_subtrees_and_updates_tail_once(self):
        model = self.model(8)
        root = model.invisibleRootItem()
        removed, tail = model.item(2), model.item(7)
        descendant = QStandardItem('child')
        removed.appendRow(descendant)
        events = []
        model.rowsRemoved.connect(lambda parent, first, last: events.append((first, last, model.rowCount())))
        with patch.object(root, '_reindex_children', wraps=root._reindex_children) as reindex:
            self.assertTrue(root.removeRows(2, 3))
            reindex.assert_called_once_with(2)
        self.assertEqual(events, [(2, 4, 5)])
        self.assertIsNone(removed.model())
        self.assertIsNone(removed.parent())
        self.assertEqual(removed.row(), -1)
        self.assertIsNone(descendant.model())
        self.assertIs(descendant.parent(), removed)
        self.assertEqual(tail.row(), 4)
        self.assertIs(tail.model(), model)

    def test_set_row_count_grows_and_shrinks_with_one_range_per_change(self):
        model = self.model(2, 3)
        inserted, removed = [], []
        model.rowsInserted.connect(lambda parent, first, last: inserted.append((first, last, model.rowCount())))
        model.rowsRemoved.connect(lambda parent, first, last: removed.append((first, last, model.rowCount())))
        model.setRowCount(100)
        self.assertEqual(inserted, [(2, 99, 100)])
        self.assertTrue(all(model.index(row, column).isValid()
                            for row in range(100) for column in range(3)))
        self.assertIsNone(model.item(99, 2))  # Qt count APIs create empty cells, not public items.
        model.setRowCount(1)
        self.assertEqual(removed, [(1, 99, 1)])
        model.setRowCount(1)
        self.assertEqual(len(inserted), 1)
        self.assertEqual(len(removed), 1)

    def test_nested_parent_signal_and_child_indexes(self):
        model = self.model(1)
        parent = model.item(0)
        events = []
        model.rowsInserted.connect(lambda index, first, last: events.append((index.internalPointer(), first, last)))
        parent.appendRows([QStandardItem('a'), QStandardItem('b')])
        self.assertEqual(events, [(parent, 0, 1)])
        for row in range(2):
            child = parent.child(row)
            self.assertEqual(child.index().row(), row)
            self.assertIs(model.parent(child.index()).internalPointer(), parent)

    def test_invalid_bulk_input_is_validated_before_mutation(self):
        model = self.model(2)
        root = model.invisibleRootItem()
        item = QStandardItem('unchanged')
        with self.assertRaises(TypeError):
            root.appendRows([item, object()])
        self.assertEqual(model.rowCount(), 2)
        self.assertIsNone(item.model())
        def broken_rows():
            yield item
            raise ValueError('input failed')
        with self.assertRaises(ValueError):
            root.insertRows(1, broken_rows())
        self.assertEqual(model.rowCount(), 2)
        self.assertIsNone(item.parent())

    def test_empty_invalid_positions_and_legacy_negative_insert_order(self):
        model = self.model()
        root = model.invisibleRootItem()
        events = []
        model.rowsInserted.connect(lambda *args: events.append(True))
        root.appendRows([])
        self.assertFalse(events)
        root.insertRows(-2, [QStandardItem('a'), QStandardItem('b'), QStandardItem('c')])
        self.assertEqual([model.item(i).text() for i in range(3)], ['c', 'b', 'a'])
        self.assertFalse(root.removeRows(-1, 2))
        self.assertFalse(root.removeRows(99, 1))
        self.assertFalse(root.removeRows(object(), 0))
        self.assertTrue(root.removeRows(1, 999))
        self.assertEqual(model.rowCount(), 1)

    def test_sort_and_single_row_apis_remain_compatible(self):
        model = self.model()
        root = model.invisibleRootItem()
        root.appendRows([QStandardItem('b'), QStandardItem('a')])
        self.assertTrue(root.insertRow(1, QStandardItem('c')))
        model.sort(0)
        self.assertEqual([model.item(i).text() for i in range(3)], ['a', 'b', 'c'])
        taken = root.takeRow(1)
        self.assertEqual(taken[0].text(), 'b')
        self.assertIsNone(taken[0].model())
        self.assertEqual(model.item(1).row(), 1)


if __name__ == '__main__':
    unittest.main(verbosity=2)
