"""Qt selection/current behavior across model mutations, without a renderer."""
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from DearUIQt.QtCore import QItemSelectionModel, QItemSelection, Qt
from DearUIQt.QtGui import QStandardItemModel, QStandardItem


class SelectionStructureTests(unittest.TestCase):
    def setUp(self):
        self.model = QStandardItemModel()
        for row in range(5):
            self.model.appendRow([QStandardItem('%d:%d' % (row, col)) for col in range(3)])
        self.selection = QItemSelectionModel(self.model)
        self.addCleanup(self.model.delete)
        self.addCleanup(self.selection.delete)

    def coords(self):
        return {(index.row(), index.column()) for index in self.selection.selectedIndexes()}

    def test_insert_before_selection_emits_empty_delta_before_mutation(self):
        self.selection.setCurrentIndex(self.model.index(2, 0), self.selection.ClearAndSelect)
        events = []
        self.selection.selectionChanged.connect(lambda added, removed: events.append(
            (added.indexes(), removed.indexes(), self.model.rowCount(), self.selection.currentIndex().row())))
        self.model.insertRows(0, 2)
        self.assertEqual(events, [([], [], 5, 2)])
        self.assertEqual(self.coords(), {(4, 0)})
        self.assertEqual(self.selection.currentIndex().data(), '2:0')

    def test_insert_inside_rectangle_keeps_new_cells_unselected_without_delta(self):
        self.selection.select(QItemSelection(self.model.index(1, 0), self.model.index(3, 2)),
                              self.selection.ClearAndSelect)
        events = []
        self.selection.selectionChanged.connect(lambda *args: events.append(args))
        self.model.insertRows(2, 2)
        self.assertEqual(self.coords(), {(row, col) for row in (1, 4, 5) for col in range(3)})
        self.assertEqual(events, [])

    def test_remove_selected_current_prefers_previous_row_before_deselection(self):
        self.selection.setCurrentIndex(self.model.index(2, 1), self.selection.ClearAndSelect)
        events = []
        self.selection.currentChanged.connect(lambda current, old: events.append(('current', current.row(), old.row())))
        self.selection.selectionChanged.connect(lambda added, removed: events.append(
            ('selection', [index.row() for index in removed.indexes()])))
        self.model.removeRows(2, 1)
        self.assertEqual(events, [('current', 1, 2), ('selection', [2])])
        self.assertEqual(self.selection.currentIndex().data(), '1:1')
        self.assertFalse(self.selection.hasSelection())

    def test_remove_first_current_uses_next_survivor_then_invalid_when_empty(self):
        self.selection.setCurrentIndex(self.model.index(0, 1), self.selection.NoUpdate)
        self.model.removeRows(0, 2)
        self.assertEqual((self.selection.currentIndex().row(), self.selection.currentIndex().data()), (0, '2:1'))
        self.model.removeRows(0, 3)
        self.assertFalse(self.selection.currentIndex().isValid())

    def test_remove_before_selection_remaps_without_current_signal(self):
        self.selection.setCurrentIndex(self.model.index(3, 0), self.selection.ClearAndSelect)
        events = []
        self.selection.currentChanged.connect(lambda *args: events.append(args))
        self.model.removeRows(0, 1)
        self.assertEqual(self.coords(), {(2, 0)})
        self.assertEqual(self.selection.currentIndex().row(), 2)
        self.assertEqual(events, [])

    def test_structural_change_commits_interactive_layer(self):
        self.selection.select(self.model.index(1, 0), self.selection.Select)
        self.selection.select(self.model.index(3, 0), self.selection.SelectCurrent)
        self.model.insertRows(0, 1)
        self.selection.select(self.model.index(2, 0), self.selection.SelectCurrent)
        self.assertEqual(self.coords(), {(2, 0), (4, 0)})

    def test_column_removal_fallback_and_empty_column_table(self):
        self.selection.setCurrentIndex(self.model.index(2, 2), self.selection.ClearAndSelect)
        self.model.setColumnCount(2)
        self.assertEqual((self.selection.currentIndex().row(), self.selection.currentIndex().column()), (2, 1))
        self.assertFalse(self.selection.hasSelection())
        self.model.setColumnCount(0)
        self.assertFalse(self.selection.currentIndex().isValid())

    def test_remove_ancestor_invalidates_descendant_current_without_current_signal(self):
        parent = self.model.item(2, 0)
        parent.appendRow(QStandardItem('child'))
        self.selection.setCurrentIndex(parent.child(0).index(), self.selection.ClearAndSelect)
        events = []
        self.selection.currentChanged.connect(lambda *args: events.append(args))
        self.model.removeRows(2, 1)
        self.assertFalse(self.selection.currentIndex().isValid())
        self.assertFalse(self.selection.hasSelection())
        self.assertEqual(events, [])

    def test_sort_preserves_selected_item_and_current_without_public_delta(self):
        self.selection.setCurrentIndex(self.model.index(1, 1), self.selection.ClearAndSelect)
        events = []
        self.selection.selectionChanged.connect(lambda *args: events.append(args))
        self.selection.currentChanged.connect(lambda *args: events.append(args))
        self.model.sort(0, Qt.DescendingOrder)
        self.assertEqual(self.coords(), {(3, 1)})
        self.assertEqual(self.selection.currentIndex().data(), '1:1')
        self.assertEqual(events, [])

    def test_sort_rebuilds_reversed_range_corners_for_next_removal(self):
        self.selection.select(QItemSelection(self.model.index(0, 0), self.model.index(2, 1)),
                              self.selection.ClearAndSelect)
        self.model.sort(0, Qt.DescendingOrder)
        events = []
        self.selection.selectionChanged.connect(lambda added, removed: events.append(
            {(index.row(), index.column()) for index in removed.indexes()}))
        self.model.removeRows(3, 1)
        self.assertEqual(events, [{(3, 0), (3, 1)}])
        self.assertEqual(self.coords(), {(row, col) for row in (2, 3) for col in (0, 1)})

    def test_about_to_observer_can_replace_selection_after_snapshot(self):
        self.selection.select(self.model.index(0, 0), self.selection.Select)
        self.model.rowsAboutToBeInserted.connect(lambda *args: self.selection.select(
            self.model.index(3, 0), self.selection.ClearAndSelect))
        self.model.insertRows(0, 1)
        self.assertEqual(self.coords(), {(4, 0)})

    def test_model_switch_disconnects_old_structural_signals(self):
        other = QStandardItemModel(2, 2)
        self.addCleanup(other.delete)
        self.selection.setModel(other)
        self.selection.select(other.index(1, 0), self.selection.Select)
        self.model.insertRows(0, 1)
        self.assertEqual(self.coords(), {(1, 0)})
        self.assertIsNone(self.selection._pending_structure)

    def test_early_completed_observer_sees_remap_and_can_begin_next_transaction(self):
        observed = []
        late_selection = None
        def inserted(*args):
            if not observed:
                observed.append(late_selection.currentIndex().row())
                self.model.insertRows(0, 1)
        self.model.rowsInserted.connect(inserted)
        late_selection = QItemSelectionModel(self.model)
        self.addCleanup(late_selection.delete)
        late_selection.setCurrentIndex(self.model.index(2, 0), late_selection.ClearAndSelect)
        self.model.insertRows(0, 1)
        self.assertEqual(observed, [3])
        self.assertEqual(late_selection.currentIndex().row(), 4)
        self.assertEqual(late_selection.selectedIndexes(), [self.model.index(4, 0)])

    def test_delete_disconnects_structural_lambda_receivers(self):
        self.selection.delete()
        self.assertFalse(any(connection.receiver is self.selection
                             for connection in self.model.rowsAboutToBeInserted._slots))
        self.model.insertRows(0, 1)


if __name__ == '__main__':
    unittest.main(verbosity=2)
