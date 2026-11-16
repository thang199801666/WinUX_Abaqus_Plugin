"""Qt standard-item replacement/take selection and subtree lifecycle."""
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from DearUIQt.QtCore import QItemSelectionModel, QItemSelection, QPersistentModelIndex
from DearUIQt.QtGui import QStandardItemModel, QStandardItem


class ItemLifecycleTests(unittest.TestCase):
    def setUp(self):
        self.model = QStandardItemModel()
        for row in range(3):
            self.model.appendRow([QStandardItem('%d:%d' % (row, col)) for col in range(3)])
        self.selection = QItemSelectionModel(self.model)
        self.addCleanup(self.model.delete)
        self.addCleanup(self.selection.delete)

    def select_cell(self):
        self.selection.setCurrentIndex(self.model.index(1, 1), self.selection.ClearAndSelect)

    def select_rectangle(self):
        self.selection.select(QItemSelection(self.model.index(0, 0), self.model.index(2, 2)),
                              self.selection.ClearAndSelect)

    def test_replace_selected_cell_emits_layout_then_data_without_selection_delta(self):
        self.select_cell()
        events = []
        for name in ('layoutAboutToBeChanged', 'layoutChanged', 'itemChanged', 'dataChanged'):
            getattr(self.model, name).connect(lambda *args, name=name: events.append(name))
        self.selection.selectionChanged.connect(lambda *args: events.append('selection'))
        self.selection.currentChanged.connect(lambda *args: events.append('current'))
        self.model.setItem(1, 1, QStandardItem('new'))
        self.assertEqual(events, ['layoutAboutToBeChanged', 'layoutChanged', 'itemChanged', 'dataChanged'])
        self.assertEqual(self.selection.currentIndex().data(), 'new')
        self.assertEqual(self.selection.selectedIndexes(), [self.model.index(1, 1)])

    def test_set_none_invalidates_selected_cell_without_resurrection(self):
        self.select_cell()
        self.model.setItem(1, 1, None)
        self.assertFalse(self.selection.currentIndex().isValid())
        self.assertFalse(self.selection.hasSelection())
        self.model.setData(self.model.index(1, 1), 'new')
        self.assertFalse(self.selection.hasSelection())

    def test_take_leaf_uses_data_changed_not_layout_or_selection_signals(self):
        self.select_cell()
        events = []
        self.model.layoutChanged.connect(lambda *args: events.append('layout'))
        self.selection.selectionChanged.connect(lambda *args: events.append('selection'))
        self.selection.currentChanged.connect(lambda *args: events.append('current'))
        self.model.dataChanged.connect(lambda *args: events.append('data'))
        taken = self.model.takeItem(1, 1)
        self.assertEqual(events, ['data'])
        self.assertFalse(self.selection.currentIndex().isValid())
        self.assertFalse(self.selection.hasSelection())
        self.assertIsNone(taken.model())
        self.model.setItem(1, 1, taken)
        self.assertFalse(self.selection.hasSelection())

    def test_take_interior_keeps_range_coverage_but_invalidates_current(self):
        self.select_rectangle()
        self.selection.setCurrentIndex(self.model.index(1, 1), self.selection.NoUpdate)
        self.model.takeItem(1, 1)
        self.assertEqual(len(self.selection.selectedIndexes()), 9)
        self.assertTrue(self.selection.isSelected(self.model.index(1, 1)))
        self.assertFalse(self.selection.currentIndex().isValid())
        self.assertIsNone(self.model.item(1, 1))

    def test_take_corner_invalidates_whole_stored_range(self):
        self.select_rectangle()
        self.model.takeItem(0, 0)
        self.assertFalse(self.selection.hasSelection())

    def test_replace_corner_with_none_layout_preserves_other_selected_cells(self):
        self.select_rectangle()
        self.model.setItem(0, 0, None)
        self.assertEqual(len(self.selection.selectedIndexes()), 8)
        self.assertFalse(self.selection.isSelected(self.model.index(0, 0)))

    def test_take_empty_cell_and_set_none_are_silent_noops(self):
        model = QStandardItemModel(2, 2)
        self.addCleanup(model.delete)
        index = model.index(0, 0)
        persistent = QPersistentModelIndex(index)
        events = []
        model.dataChanged.connect(lambda *args: events.append('data'))
        model.layoutChanged.connect(lambda *args: events.append('layout'))
        self.assertIsNone(model.takeItem(0, 0))
        model.setItem(0, 0, None)
        self.assertTrue(persistent.isValid())
        self.assertEqual(events, [])

    def test_take_subtree_temporarily_notifies_child_table_removal_and_retains_ownership(self):
        parent = self.model.item(1, 0)
        child = QStandardItem('child')
        parent.appendRow([child, QStandardItem('sibling')])
        child.appendRow(QStandardItem('grandchild'))
        self.selection.setCurrentIndex(child.index(), self.selection.ClearAndSelect)
        persistent = QPersistentModelIndex(child.index())
        events = []
        for name in ('rowsAboutToBeRemoved', 'rowsRemoved', 'columnsAboutToBeRemoved', 'columnsRemoved'):
            getattr(self.model, name).connect(lambda index, first, last, name=name: events.append(
                (name, self.model.rowCount(index), self.model.columnCount(index))))
        taken = self.model.takeItem(1, 0)
        self.assertEqual(events, [('rowsAboutToBeRemoved', 1, 2), ('rowsRemoved', 0, 2),
                                  ('columnsAboutToBeRemoved', 0, 2), ('columnsRemoved', 0, 0)])
        self.assertEqual((taken.rowCount(), taken.columnCount()), (1, 2))
        self.assertIs(child.parent(), taken)
        self.assertIsNone(child.model())
        self.assertFalse(persistent.isValid())
        self.assertFalse(self.selection.currentIndex().isValid())
        self.model.setItem(1, 0, taken)
        self.assertFalse(persistent.isValid())

    def test_replacing_parent_invalidates_descendant_selection_and_current(self):
        parent = self.model.item(1, 0)
        parent.appendRow(QStandardItem('child'))
        self.selection.select(parent.index(), self.selection.Select)
        self.selection.setCurrentIndex(parent.child(0).index(), self.selection.Select)
        self.model.setItem(1, 0, QStandardItem('replacement'))
        self.assertEqual(self.selection.selectedIndexes(), [self.model.index(1, 0)])
        self.assertFalse(self.selection.currentIndex().isValid())

    def test_same_item_noop_emits_no_layout(self):
        events = []
        self.model.layoutAboutToBeChanged.connect(lambda *args: events.append(args))
        self.model.setItem(1, 1, self.model.item(1, 1))
        self.assertEqual(events, [])

    def test_layout_observer_before_selection_slot_sees_invalid_corners_then_rebuilt_cells(self):
        counts = []
        late = None
        self.model.layoutChanged.connect(lambda *args: counts.append(len(late.selectedIndexes())))
        late = QItemSelectionModel(self.model)
        self.addCleanup(late.delete)
        late.select(QItemSelection(self.model.index(0, 0), self.model.index(2, 2)), late.ClearAndSelect)
        self.model.setItem(0, 0, None)
        self.assertEqual(counts, [0])
        self.assertEqual(len(late.selectedIndexes()), 8)

    def test_take_subtree_observer_exception_does_not_lose_child_table(self):
        parent = self.model.item(1, 0)
        parent.appendRow(QStandardItem('child'))
        def fail(*args):
            raise ValueError('observer failed')
        connection = self.model.rowsRemoved.connect(fail)
        with self.assertRaisesRegex(ValueError, 'observer failed'):
            self.model.takeItem(1, 0)
        self.assertIs(self.model.item(1, 0), parent)
        self.assertEqual(parent.child(0).text(), 'child')
        self.assertEqual((parent.rowCount(), parent.columnCount()), (1, 1))
        self.assertFalse(self.model._change_stack)
        connection.disconnect()


if __name__ == '__main__':
    unittest.main(verbosity=2)
