"""Qt-oriented row/column, eligibility, parent and range contracts."""
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from DearUIQt.QtCore import QItemSelectionModel, QItemSelectionRange, QItemSelection, QModelIndex, Qt
from DearUIQt.QtGui import QStandardItemModel, QStandardItem


class QtSelectionQueriesTests(unittest.TestCase):
    def setUp(self):
        self.model = QStandardItemModel(3, 3)
        for row in range(3):
            for column in range(3):
                self.model.setItem(row, column, QStandardItem())
        self.selection = QItemSelectionModel(self.model)
        self.addCleanup(self.model.delete)
        self.addCleanup(self.selection.delete)

    def test_partial_row_or_column_is_not_fully_selected(self):
        self.selection.select(self.model.index(0, 0), self.selection.Select)
        self.assertFalse(self.selection.isRowSelected(0))
        self.assertFalse(self.selection.isColumnSelected(0))
        self.assertEqual(self.selection.selectedRows(), [])
        self.assertEqual(self.selection.selectedColumns(), [])
        self.assertTrue(self.selection.rowIntersectsSelection(0))
        self.assertTrue(self.selection.columnIntersectsSelection(0))
        self.assertFalse(self.selection.rowIntersectsSelection(1))

    def test_complete_rows_columns_and_anchor_coordinates(self):
        self.selection.select(self.model.index(1, 1), self.selection.Select | self.selection.Rows)
        self.assertEqual(self.selection.selectedRows(2), [self.model.index(1, 2)])
        self.assertEqual(self.selection.selectedColumns(), [])
        self.selection.select(self.model.index(0, 0), self.selection.ClearAndSelect | self.selection.Columns)
        self.assertEqual(self.selection.selectedColumns(2), [self.model.index(2, 0)])
        self.assertEqual(self.selection.selectedRows(), [])

    def test_disabled_and_unselectable_cells_are_ignored_for_completeness(self):
        self.model.item(0, 1).setEnabled(False)
        self.model.item(0, 2).setSelectable(False)
        self.selection.select(self.model.index(0, 0), self.selection.Select)
        self.assertTrue(self.selection.isRowSelected(0))
        self.assertEqual(self.selection.selectedRows(), [self.model.index(0, 0)])
        self.model.item(0, 0).setEnabled(False)
        self.assertFalse(self.selection.isRowSelected(0))
        self.assertFalse(self.selection.hasSelection())
        self.assertFalse(self.selection.rowIntersectsSelection(0))

    def test_disabled_cells_remain_in_structural_selection_for_reenable(self):
        cell = self.model.item(0, 1)
        cell.setEnabled(False)
        area = QItemSelectionRange(self.model.index(0, 0), self.model.index(0, 2))
        self.selection.select(area, self.selection.Select)
        self.assertFalse(self.selection.isSelected(cell.index()))
        self.assertNotIn(cell.index(), self.selection.selectedIndexes())
        self.assertTrue(self.selection.selection().contains(cell.index()))
        cell.setEnabled(True)
        self.assertTrue(self.selection.isSelected(cell.index()))

    def test_parent_scoped_rows_and_intersections_do_not_flatten_tree(self):
        parents = [self.model.item(i, 0) for i in range(2)]
        for parent in parents:
            parent.appendRows([[QStandardItem('a'), QStandardItem('b')] for _ in range(2)])
        a, b = [parent.index() for parent in parents]
        self.selection.select(self.model.index(0, 0, a), self.selection.Select | self.selection.Rows)
        self.assertTrue(self.selection.isRowSelected(0, a))
        self.assertFalse(self.selection.isRowSelected(0, b))
        self.assertFalse(self.selection.rowIntersectsSelection(0))
        self.assertTrue(self.selection.rowIntersectsSelection(0, a))
        self.assertFalse(self.selection.rowIntersectsSelection(0, b))
        self.assertEqual(self.selection.selectedRows(), [self.model.index(0, 0, a)])

    def test_foreign_parent_and_invalid_section_rejected(self):
        other = QStandardItemModel(1, 1)
        self.addCleanup(other.delete)
        self.assertFalse(self.selection.isRowSelected(0, other.index(0, 0)))
        self.assertFalse(self.selection.columnIntersectsSelection(0, other.index(0, 0)))
        for section in (-1, 99):
            self.assertFalse(self.selection.isRowSelected(section))
            self.assertFalse(self.selection.isColumnSelected(section))

    def test_range_qt_accessors_and_invalid_or_cross_parent_corners(self):
        area = QItemSelectionRange(self.model.index(0, 0), self.model.index(2, 1))
        self.assertEqual((area.top(), area.bottom(), area.left(), area.right()), (0, 2, 0, 1))
        self.assertEqual((area.height(), area.width()), (3, 2))
        self.assertEqual(area.topLeft(), self.model.index(0, 0))
        self.assertEqual(area.bottomRight(), self.model.index(2, 1))
        self.assertTrue(area.contains(1, 1))
        self.assertFalse(QItemSelectionRange().isValid())
        self.assertEqual(QItemSelectionRange().width(), 1)  # Qt's raw corner arithmetic.
        self.assertFalse(QItemSelectionRange(self.model.index(2, 2), self.model.index(0, 0)).isValid())
        self.model.item(0, 0).appendRow(QStandardItem('child'))
        child = self.model.item(0, 0).child(0).index()
        self.assertFalse(QItemSelectionRange(self.model.index(0, 0), child).isValid())
        self.assertFalse(area.contains(child))

    def test_selection_normalizes_reversed_corners_and_ignores_foreign(self):
        area = QItemSelection(self.model.index(2, 2), self.model.index(0, 0))
        self.assertEqual(len(area.indexes()), 9)
        other = QStandardItemModel(1, 1)
        self.addCleanup(other.delete)
        area.select(self.model.index(0, 0), other.index(0, 0))
        self.assertEqual(len(area), 1)

    def test_range_intersection_and_duplicate_toggle_cover_each_cell_once(self):
        a = QItemSelectionRange(self.model.index(0, 0), self.model.index(1, 1))
        b = QItemSelectionRange(self.model.index(1, 1), self.model.index(2, 2))
        self.assertEqual(a.intersected(b), QItemSelectionRange(self.model.index(1, 1)))
        self.assertTrue(a.intersects(b))
        areas = QItemSelection([a, b])
        self.assertEqual(len(areas.indexes()), 8)
        self.selection.select(areas, self.selection.Toggle)
        self.assertEqual(len(self.selection.selectedIndexes()), 7)
        self.selection.select(areas, self.selection.Toggle)
        self.assertFalse(self.selection.hasSelection())

    def test_rows_and_columns_flags_expand_union_not_just_rows(self):
        self.selection.select(self.model.index(1, 1), self.selection.Select | self.selection.Rows | self.selection.Columns)
        self.assertEqual(len(self.selection.selectedIndexes()), 5)
        self.assertTrue(self.selection.isRowSelected(1))
        self.assertTrue(self.selection.isColumnSelected(1))

    def test_selection_merge_matches_set_operations(self):
        a = QItemSelection(self.model.index(0, 0), self.model.index(1, 1))
        b = QItemSelection(self.model.index(1, 1), self.model.index(2, 2))
        expected = set(a.indexes()) ^ set(b.indexes())
        a.merge(b, self.selection.Toggle)
        self.assertEqual(set(a.indexes()), expected)
        a.merge(b, self.selection.Deselect)
        self.assertFalse(set(a.indexes()) & set(b.indexes()))

    def test_parent_change_emits_row_and_column_even_same_coordinates(self):
        a, b = self.model.item(0, 0), self.model.item(1, 0)
        a.appendRow(QStandardItem('a'))
        b.appendRow(QStandardItem('b'))
        self.selection.setCurrentIndex(a.child(0).index())
        events = []
        self.selection.currentRowChanged.connect(lambda *args: events.append('row'))
        self.selection.currentColumnChanged.connect(lambda *args: events.append('column'))
        self.selection.setCurrentIndex(b.child(0).index())
        self.assertEqual(events, ['row', 'column'])

    def test_runtime_qt_deselect_toggle_disabled_section_completeness(self):
        self.model.item(0, 1).setEnabled(False)
        self.model.item(0, 2).setSelectable(False)
        self.selection.select(self.model.index(0, 0), self.selection.Select | self.selection.Rows)
        self.selection.select([], self.selection.Select)
        self.selection.select(self.model.index(0, 1), self.selection.Deselect | self.selection.Current)
        self.assertTrue(self.selection.isSelected(self.model.index(0, 0)))
        self.assertFalse(self.selection.isRowSelected(0))
        self.assertEqual(self.selection.selectedRows(), [])
        self.selection.select(self.model.index(0, 2), self.selection.ToggleCurrent)
        self.assertFalse(self.selection.isRowSelected(0))
        self.selection.clearSelection()
        self.selection.select(self.model.index(0, 0), self.selection.Select)
        self.assertTrue(self.selection.isRowSelected(0))


if __name__ == '__main__':
    unittest.main(verbosity=2)
