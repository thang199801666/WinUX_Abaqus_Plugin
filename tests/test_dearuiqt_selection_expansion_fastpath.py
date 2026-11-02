"""Compare single-axis expansion with the retained full-expansion reference."""
from pathlib import Path
import random
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from DearUIQt.QtCore import QItemSelection, QItemSelectionModel
from DearUIQt.QtGui import QStandardItemModel, QStandardItem
from benchmark_dearuiqt_selection_expansion import FullExpansionSelectionModel, Grid


class SelectionExpansionFastPathTests(unittest.TestCase):
    def setUp(self):
        self.model = QStandardItemModel()
        for row in range(7):
            self.model.appendRow([QStandardItem('%d:%d' % (row, col)) for col in range(4)])
        for row in (0, 1):
            for child in range(3):
                self.model.item(row).appendRow([QStandardItem('a%d' % child), QStandardItem('b%d' % child)])
        self.addCleanup(self.model.delete)
        self.fast = QItemSelectionModel(self.model)
        self.reference = FullExpansionSelectionModel(self.model)
        self.addCleanup(self.fast.delete)
        self.addCleanup(self.reference.delete)
        self.events = {self.fast: [], self.reference: []}
        for selection in (self.fast, self.reference):
            selection.selectionChanged.connect(lambda added, removed, selection=selection: self.events[selection].append(
                (tuple(self.key(index) for index in added.indexes()), tuple(self.key(index) for index in removed.indexes()))))

    @staticmethod
    def key(index):
        result = []
        while index.isValid():
            result.append((index.row(), index.column()))
            index = index.parent()
        return tuple(reversed(result))

    def signature(self, selection):
        shape = lambda areas: [(self.key(area.topLeft()), self.key(area.bottomRight())) for area in areas]
        return (set(selection._selected), set(selection._interactive_added), set(selection._interactive_removed),
                tuple(selection._interactive_targets), selection._interactive_command,
                shape(selection._committed_ranges), shape(selection._live_ranges), selection._live_command)

    def same(self):
        self.assertEqual(self.signature(self.fast), self.signature(self.reference))
        self.assertEqual(self.events[self.fast], self.events[self.reference])
        self.assertEqual(self.fast.selectedRows(), self.reference.selectedRows())
        self.assertEqual(self.fast.selectedColumns(), self.reference.selectedColumns())

    def select(self, value, command):
        for selection in (self.fast, self.reference):
            selection.select(value, command)
        self.same()

    def test_duplicate_rows_preserve_last_metadata_and_first_target_order(self):
        inputs = [self.model.index(row, col) for row, col in ((4, 0), (2, 1), (4, 3), (1, 0))]
        with patch.object(self.fast, '_merge_expanded_ranges', wraps=self.fast._merge_expanded_ranges) as merge:
            self.select(inputs, self.fast.Select | self.fast.Rows)
        self.assertEqual(merge.call_count, 0)
        self.assertEqual([area.top() for area in self.fast._live_ranges], [2, 4, 1])
        self.select(inputs, self.fast.Deselect | self.fast.Rows)
        self.assertEqual([index.row() for index in self.fast._interactive_targets], [4] * 4 + [2] * 4 + [1] * 4)

    def test_duplicate_columns_preserve_metadata_order(self):
        inputs = [self.model.index(row, col) for row, col in ((0, 3), (2, 1), (4, 3), (0, 0))]
        with patch.object(self.fast, '_merge_expanded_ranges', wraps=self.fast._merge_expanded_ranges) as merge:
            self.select(inputs, self.fast.Select | self.fast.Columns)
        self.assertEqual(merge.call_count, 0)
        self.assertEqual([area.left() for area in self.fast._live_ranges], [1, 3, 0])

    def test_all_cell_input_expands_each_row_only_once(self):
        class CountingGrid(Grid):
            def __init__(self):
                super().__init__(10, 8)
                self.index_calls = 0
            def index(self, *args):
                self.index_calls += 1
                return super().index(*args)
        model = CountingGrid()
        self.addCleanup(model.delete)
        fast, reference = QItemSelectionModel(model), FullExpansionSelectionModel(model)
        self.addCleanup(fast.delete)
        self.addCleanup(reference.delete)
        inputs = [model.index(row, col) for row in range(10) for col in range(8)]
        model.index_calls = 0
        current = fast._expand_selection_indexes(inputs, fast.Rows)
        self.assertEqual(model.index_calls, 80)
        model.index_calls = 0
        previous = reference._expand_selection_indexes(inputs, reference.Rows)
        self.assertEqual(model.index_calls, 640)
        self.assertEqual(current, list(dict.fromkeys(previous)))

    def test_multirow_rectangle_keeps_general_metadata_path(self):
        area = QItemSelection(self.model.index(1, 1), self.model.index(5, 2))
        with patch.object(self.fast, '_merge_expanded_ranges', wraps=self.fast._merge_expanded_ranges) as merge:
            self.select(area, self.fast.Select | self.fast.Rows)
        self.assertEqual(merge.call_count, 1)

    def test_rows_columns_union_keeps_full_expansion_paths(self):
        inputs = [self.model.index(2, 1), self.model.index(4, 3)]
        with patch.object(self.fast, '_merge_expanded_ranges', wraps=self.fast._merge_expanded_ranges) as ranges:
            with patch.object(self.fast, '_expand_selection_indexes_full', wraps=self.fast._expand_selection_indexes_full) as indexes:
                self.select(inputs, self.fast.Toggle | self.fast.Rows | self.fast.Columns)
        self.assertEqual(ranges.call_count, 1)
        self.assertEqual(indexes.call_count, 1)

    def test_equal_section_coordinates_under_different_parents_do_not_merge(self):
        a, b = self.model.index(0, 0), self.model.index(1, 0)
        other = QStandardItemModel(1, 1)
        self.addCleanup(other.delete)
        inputs = [self.model.index(1, 0, a), other.index(0, 0),
                  self.model.index(1, 1, b), self.model.index(1, 1, a)]
        self.select(inputs, self.fast.Select | self.fast.Rows)
        self.assertEqual([area.parent() for area in self.fast._live_ranges], [b, a])

    def test_zero_dimension_models_and_invalid_indexes_have_no_coverage(self):
        for rows, columns, flag in ((3, 0, self.fast.Rows), (0, 3, self.fast.Columns)):
            model = Grid(rows, columns)
            self.addCleanup(model.delete)
            for kind in (QItemSelectionModel, FullExpansionSelectionModel):
                selection = kind(model)
                self.addCleanup(selection.delete)
                selection.select([model.index(0, 0)], selection.Select | flag)
                self.assertEqual(selection.selectedIndexes(), [])
                self.assertEqual(selection._live_ranges, [])

    def test_disabled_cells_and_current_layers_keep_structural_coverage(self):
        self.model.item(2, 1).setEnabled(False)
        self.model.item(2, 3).setSelectable(False)
        inputs = [self.model.index(2, 0), self.model.index(2, 2)]
        for command in (self.fast.Select | self.fast.Rows,
                        self.fast.Deselect | self.fast.Current | self.fast.Rows,
                        self.fast.ToggleCurrent | self.fast.Columns):
            self.select(inputs, command)

    def test_structural_followup_preserves_ranges_and_signal_timing(self):
        self.select([self.model.index(row, 0) for row in (2, 4, 2)], self.fast.Select | self.fast.Rows)
        self.model.insertRows(3, 1)
        self.same()
        self.model.insertColumns(1, 1)
        self.same()
        self.model.removeRows(1, 2)
        self.same()

    def test_seeded_axes_flags_and_input_shapes_match_full_reference(self):
        rng = random.Random(68121)
        axes = (self.fast.Rows, self.fast.Columns, self.fast.Rows | self.fast.Columns)
        commands = (self.fast.Select, self.fast.SelectCurrent, self.fast.ToggleCurrent,
                    self.fast.Deselect | self.fast.Current, self.fast.ClearAndSelect)
        for step in range(100):
            points = [self.model.index(rng.randrange(7), rng.randrange(4)) for _ in range(3)]
            value = points if step % 2 else QItemSelection(points[0], points[-1])
            with self.subTest(step=step):
                self.select(value, rng.choice(axes) | rng.choice(commands))


if __name__ == '__main__':
    unittest.main(verbosity=2)
