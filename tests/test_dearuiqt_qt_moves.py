"""Custom-model move protocol contracts (standard-item moves stay unsupported)."""
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from DearUIQt.QtCore import QAbstractTableModel, QAbstractItemModel, QModelIndex, QPersistentModelIndex, QItemSelectionModel, QItemSelection
from DearUIQt.QtGui import QStandardItemModel


class MovingTable(QAbstractTableModel):
    def __init__(self):
        super().__init__()
        self.values = [['%d:%d' % (r, c) for c in range(4)] for r in range(5)]

    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.values)

    def columnCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.values[0])

    def data(self, index, role=0):
        return self.values[index.row()][index.column()] if index.isValid() and int(role) == 0 else None

    def moveRows(self, sourceParent, sourceRow, count, destinationParent, destinationChild):
        if (sourceParent.isValid() or destinationParent.isValid() or count <= 0 or sourceRow < 0
                or sourceRow + count > self.rowCount() or not 0 <= destinationChild <= self.rowCount()):
            return False
        if not self.beginMoveRows(sourceParent, sourceRow, sourceRow + count - 1, destinationParent, destinationChild):
            return False
        block = self.values[sourceRow:sourceRow + count]
        del self.values[sourceRow:sourceRow + count]
        target = destinationChild - count if destinationChild > sourceRow else destinationChild
        self.values[target:target] = block
        self.endMoveRows()
        return True

    def moveColumns(self, sourceParent, sourceColumn, count, destinationParent, destinationChild):
        if (sourceParent.isValid() or destinationParent.isValid() or count <= 0 or sourceColumn < 0
                or sourceColumn + count > self.columnCount() or not 0 <= destinationChild <= self.columnCount()):
            return False
        if not self.beginMoveColumns(sourceParent, sourceColumn, sourceColumn + count - 1, destinationParent, destinationChild):
            return False
        target = destinationChild - count if destinationChild > sourceColumn else destinationChild
        for row in self.values:
            block = row[sourceColumn:sourceColumn + count]
            del row[sourceColumn:sourceColumn + count]
            row[target:target] = block
        self.endMoveColumns()
        return True


class Node:
    def __init__(self, text, owner=None):
        self.text, self.owner, self.children = text, owner, []
        if owner is not None:
            owner.children.append(self)


class MovingTree(QAbstractItemModel):
    def __init__(self):
        super().__init__()
        self.root = Node('root')

    def node(self, index):
        return index.internalPointer() if index.isValid() else self.root

    def indexForNode(self, node):
        return self.createIndex(node.owner.children.index(node), 0, node) if node.owner else QModelIndex()

    def index(self, row, column, parent=QModelIndex()):
        children = self.node(parent).children
        return self.createIndex(row, column, children[row]) if column == 0 and 0 <= row < len(children) else QModelIndex()

    def parent(self, index):
        return self.indexForNode(self.node(index).owner) if index.isValid() else QModelIndex()

    def rowCount(self, parent=QModelIndex()):
        return len(self.node(parent).children)

    def columnCount(self, parent=QModelIndex()):
        return 1

    def data(self, index, role=0):
        return self.node(index).text if index.isValid() and int(role) == 0 else None

    def moveRows(self, sourceParent, sourceRow, count, destinationParent, destinationChild):
        source, destination = self.node(sourceParent), self.node(destinationParent)
        if count <= 0 or sourceRow < 0 or sourceRow + count > len(source.children) or not 0 <= destinationChild <= len(destination.children):
            return False
        if not self.beginMoveRows(sourceParent, sourceRow, sourceRow + count - 1, destinationParent, destinationChild):
            return False
        block = source.children[sourceRow:sourceRow + count]
        del source.children[sourceRow:sourceRow + count]
        target = destinationChild - count if source is destination and destinationChild > sourceRow else destinationChild
        destination.children[target:target] = block
        for node in block:
            node.owner = destination
        self.endMoveRows()
        return True


class MoveTransactionTests(unittest.TestCase):
    def setUp(self):
        self.model = MovingTable()
        self.root = QModelIndex()
        self.selection = QItemSelectionModel(self.model)
        self.addCleanup(self.model.delete)
        self.addCleanup(self.selection.delete)

    def tree(self):
        tree = MovingTree()
        self.addCleanup(tree.delete)
        a, b = Node('A', tree.root), Node('B', tree.root)
        child = Node('child', a)
        grand = Node('grand', child)
        return tree, a, b, child, grand

    def test_standard_item_inherits_false_defaults_without_invented_moves(self):
        standard = QStandardItemModel(3, 3)
        self.addCleanup(standard.delete)
        self.assertFalse(standard.moveRow(self.root, 0, self.root, 3))
        self.assertFalse(standard.moveColumn(self.root, 0, self.root, 3))

    def test_row_block_down_remaps_moved_and_displaced_persistent_handles(self):
        moved = QPersistentModelIndex(self.model.index(1, 0))
        displaced = QPersistentModelIndex(self.model.index(4, 0))
        self.assertTrue(self.model.moveRows(self.root, 1, 2, self.root, 5))
        self.assertEqual((moved.row(), moved.data()), (3, '1:0'))
        self.assertEqual((displaced.row(), displaced.data()), (2, '4:0'))

    def test_row_block_up_and_single_convenience_overload(self):
        index = QPersistentModelIndex(self.model.index(3, 0))
        self.model.moveRows(self.root, 3, 2, self.root, 0)
        self.assertEqual((index.row(), index.data()), (0, '3:0'))
        self.assertTrue(self.model.moveRow(self.root, 0, self.root, 5))
        self.assertEqual(index.row(), 4)

    def test_column_block_and_single_convenience_remap_without_losing_data(self):
        index = QPersistentModelIndex(self.model.index(2, 0))
        self.assertTrue(self.model.moveColumns(self.root, 0, 2, self.root, 4))
        self.assertEqual((index.column(), index.data()), (2, '2:0'))
        self.assertTrue(self.model.moveColumn(self.root, 2, self.root, 0))
        self.assertEqual((index.column(), index.data()), (0, '2:0'))

    def test_overlap_and_noop_destinations_are_rejected_without_signals(self):
        events = []
        self.model.rowsAboutToBeMoved.connect(lambda *args: events.append(args))
        for destination in (1, 2, 3):
            self.assertFalse(self.model.moveRows(self.root, 1, 2, self.root, destination))
        self.assertEqual(events, [])
        self.assertFalse(self.model._change_stack)

    def test_move_signals_see_old_then_new_coordinates_without_public_deltas(self):
        self.selection.setCurrentIndex(self.model.index(1, 0), self.selection.ClearAndSelect)
        events = []
        self.model.rowsAboutToBeMoved.connect(lambda *args: events.append(('about', self.selection.currentIndex().row())))
        self.model.rowsMoved.connect(lambda *args: events.append(('done', self.selection.currentIndex().row())))
        self.selection.selectionChanged.connect(lambda *args: events.append(('selection',)))
        self.selection.currentChanged.connect(lambda *args: events.append(('current',)))
        self.model.moveRow(self.root, 1, self.root, 5)
        self.assertEqual(events, [('about', 1), ('done', 4)])
        self.assertEqual(self.selection.selectedIndexes(), [self.model.index(4, 0)])

    def test_rectangle_selection_rebuilds_scattered_coverage_after_move(self):
        self.selection.select(QItemSelection(self.model.index(0, 0), self.model.index(2, 1)), self.selection.ClearAndSelect)
        self.model.moveRow(self.root, 1, self.root, 5)
        self.assertEqual({index.row() for index in self.selection.selectedIndexes()}, {0, 1, 4})
        self.assertEqual(len(self.selection.selectedIndexes()), 6)

    def test_move_preserves_interactive_current_layer(self):
        self.selection.select(self.model.index(0, 0), self.selection.Select)
        self.selection.select(self.model.index(2, 0), self.selection.SelectCurrent)
        self.model.moveRow(self.root, 2, self.root, 0)
        self.selection.select(self.model.index(1, 0), self.selection.SelectCurrent)
        self.assertEqual(self.selection.selectedIndexes(), [self.model.index(1, 0)])

    def test_cross_parent_move_preserves_descendant_identity_and_paths(self):
        tree, a, b, child, grand = self.tree()
        index = QPersistentModelIndex(tree.indexForNode(grand))
        tree.moveRow(tree.indexForNode(a), 0, tree.indexForNode(b), 0)
        self.assertEqual(index.data(), 'grand')
        self.assertEqual(index.parent().parent(), tree.indexForNode(b))
        self.assertIs(child.owner, b)

    def test_moving_root_under_destination_adjusts_destination_parent_coordinate(self):
        tree, a, b, child, grand = self.tree()
        destination = QPersistentModelIndex(tree.indexForNode(b))
        index = QPersistentModelIndex(tree.indexForNode(grand))
        events = []
        tree.rowsMoved.connect(lambda source, first, last, target, child: events.append(target.row()))
        self.assertTrue(tree.moveRow(self.root, 0, tree.indexForNode(b), 0))
        self.assertEqual(events, [0])
        self.assertEqual(destination.row(), 0)
        self.assertEqual(index.data(), 'grand')
        self.assertIs(a.owner, b)

    def test_move_to_self_or_descendant_is_rejected(self):
        tree, a, b, child, grand = self.tree()
        self.assertFalse(tree.moveRow(self.root, 0, tree.indexForNode(a), 0))
        self.assertFalse(tree.moveRow(self.root, 0, tree.indexForNode(grand), 0))
        self.assertIs(a.owner, tree.root)

    def test_invalid_begin_and_mismatched_end_leave_transaction_reusable(self):
        self.assertFalse(self.model.beginMoveRows(self.root, -1, 0, self.root, 2))
        self.assertTrue(self.model.beginMoveRows(self.root, 0, 0, self.root, 5))
        with self.assertRaises(RuntimeError):
            self.model.endMoveColumns()
        self.model.values.append(self.model.values.pop(0))
        self.model.endMoveRows()
        self.assertFalse(self.model._change_stack)

    def test_about_exception_and_nested_move_rejection_release_guard(self):
        def fail(*args):
            with self.assertRaises(RuntimeError):
                self.model.moveRow(self.root, 0, self.root, 5)
            raise ValueError('about failed')
        connection = self.model.rowsAboutToBeMoved.connect(fail)
        with self.assertRaisesRegex(ValueError, 'about failed'):
            self.model.moveRow(self.root, 0, self.root, 5)
        connection.disconnect()
        self.assertFalse(self.model._move_active)
        self.assertFalse(self.model._change_stack)
        self.assertTrue(self.model.moveRow(self.root, 0, self.root, 5))

    def test_completed_observer_can_start_another_move(self):
        events = []
        def moved(*args):
            if not events:
                events.append(True)
                self.model.moveColumn(self.root, 0, self.root, 4)
        self.model.rowsMoved.connect(moved)
        self.assertTrue(self.model.moveRow(self.root, 0, self.root, 5))
        self.assertEqual(events, [True])
        self.assertFalse(self.model._move_active)
        self.assertFalse(self.model._change_stack)


if __name__ == '__main__':
    unittest.main(verbosity=2)
