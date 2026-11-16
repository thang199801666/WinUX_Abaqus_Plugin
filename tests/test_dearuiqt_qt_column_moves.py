"""Cross-parent columns using the same hierarchical matrix as the Qt oracle."""
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from DearUIQt.QtCore import QAbstractItemModel, QModelIndex, QPersistentModelIndex, QItemSelectionModel
from qt_move_matrix_fixture import make_matrix_model


class CrossParentColumnTests(unittest.TestCase):
    def setUp(self):
        self.model = make_matrix_model(QAbstractItemModel, QModelIndex)()
        self.addCleanup(self.model.delete)
        self.root = QModelIndex()

    def index(self, cell):
        return self.model.indexForCell(cell)

    def test_block_transfer_moves_cells_in_every_row(self):
        a, b = self.model.a, self.model.b
        moved = [a.grid[row][1] for row in range(2)]
        self.assertTrue(self.model.moveColumns(self.index(a), 1, 2, self.index(b), 1))
        self.assertEqual((self.model.columnCount(self.index(a)), self.model.columnCount(self.index(b))), (1, 5))
        for row, item in enumerate(moved):
            self.assertIs(b.grid[row][1], item)
            self.assertIs(item.owner, b)

    def test_destination_siblings_persistently_shift_right(self):
        index = QPersistentModelIndex(self.index(self.model.b.grid[1][2]))
        self.model.moveColumns(self.index(self.model.a), 1, 2, self.index(self.model.b), 1)
        self.assertEqual((index.row(), index.column(), index.data()), (1, 4, 'B-1:2'))

    def test_descendant_selection_current_and_identity_travel_without_delta_signals(self):
        selection = QItemSelectionModel(self.model)
        self.addCleanup(selection.delete)
        selection.setCurrentIndex(self.index(self.model.grandchild), selection.ClearAndSelect)
        persistent = QPersistentModelIndex(self.index(self.model.grandchild))
        events = []
        selection.currentChanged.connect(lambda *args: events.append('current'))
        selection.selectionChanged.connect(lambda *args: events.append('selection'))
        self.model.moveColumns(self.index(self.model.a), 1, 1, self.index(self.model.b), 0)
        self.assertEqual(persistent.parent().parent(), self.index(self.model.b))
        self.assertEqual(selection.currentIndex(), self.index(self.model.grandchild))
        self.assertEqual(selection.selectedIndexes(), [self.index(self.model.grandchild)])
        self.assertEqual(events, [])

    def test_root_column_move_adjusts_destination_parent_column(self):
        destination = QPersistentModelIndex(self.index(self.model.c))
        grand = QPersistentModelIndex(self.index(self.model.grandchild))
        self.assertTrue(self.model.moveColumn(self.root, 0, self.index(self.model.c), 1))
        self.assertEqual(destination.column(), 1)
        self.assertEqual(grand.data(), 'A-1:1-0:0')
        self.assertIs(self.model.a.owner, self.model.c)

    def test_move_back_to_root_adjusts_source_parent_in_completed_signal(self):
        self.model.moveColumn(self.root, 0, self.index(self.model.c), 1)
        events = []
        self.model.columnsMoved.connect(lambda source, first, last, target, child: events.append(source.column()))
        self.model.moveColumn(self.index(self.model.c), 1, self.root, 0)
        self.assertEqual(events, [2])
        self.assertIs(self.model.a.owner, self.model.root)

    def test_empty_source_table_can_receive_columns_again_with_identity_preserved(self):
        index = QPersistentModelIndex(self.index(self.model.branch))
        self.model.moveColumns(self.index(self.model.a), 0, 3, self.index(self.model.b), 0)
        self.assertEqual(self.model.columnCount(self.index(self.model.a)), 0)
        self.assertEqual(self.model.rowCount(self.index(self.model.a)), 2)
        self.assertTrue(index.isValid())
        self.model.moveColumns(self.index(self.model.b), 0, 3, self.index(self.model.a), 0)
        self.assertEqual(index, self.index(self.model.branch))

    def test_column_cycle_to_descendant_is_rejected_without_mutation(self):
        before = self.model.contents()
        self.assertFalse(self.model.moveColumn(self.root, 0, self.index(self.model.grandchild), 0))
        self.assertEqual(self.model.contents(), before)
        self.assertFalse(self.model._move_active)

    def test_foreign_parent_is_rejected_by_custom_storage_wrapper(self):
        other = make_matrix_model(QAbstractItemModel, QModelIndex)()
        self.addCleanup(other.delete)
        self.assertFalse(self.model.moveColumn(self.index(self.model.a), 0, other.indexForCell(other.b), 0))


if __name__ == '__main__':
    unittest.main(verbosity=2)
