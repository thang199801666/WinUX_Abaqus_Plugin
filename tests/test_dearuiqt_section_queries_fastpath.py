"""Query-local live blocker indexing vs repeated section scans."""
from pathlib import Path
import random
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from DearUIQt.QtCore import QItemSelectionModel, QItemSelection, QAbstractItemModel
from DearUIQt.QtGui import QStandardItemModel, QStandardItem
from benchmark_dearuiqt_section_queries import RepeatedScanSelectionModel
from benchmark_dearuiqt_selection_expansion import Grid


class SectionQueryFastPathTests(unittest.TestCase):
    def setUp(self):
        self.model = QStandardItemModel()
        for row in range(6):
            self.model.appendRow([QStandardItem('%d:%d' % (row, column)) for column in range(4)])
        for row in (0, 1):
            for child in range(3):
                self.model.item(row).appendRow([QStandardItem('a'), QStandardItem('b')])
        self.addCleanup(self.model.delete)
        self.fast = QItemSelectionModel(self.model)
        self.reference = RepeatedScanSelectionModel(self.model)
        self.addCleanup(self.fast.delete)
        self.addCleanup(self.reference.delete)

    def same(self):
        for anchor in (-1, 0, 1, 9):
            self.assertEqual(self.fast.selectedRows(anchor), self.reference.selectedRows(anchor))
            self.assertEqual(self.fast.selectedColumns(anchor), self.reference.selectedColumns(anchor))

    def select(self, value, command):
        for selection in (self.fast, self.reference):
            selection.select(value, command)
        self.same()

    def fill(self):
        self.select(QItemSelection(self.model.index(0, 0), self.model.index(5, 3)), self.fast.ClearAndSelect)
        self.select([], self.fast.Select)

    def count_scans(self, rows):
        model = Grid(100, 8) if rows else Grid(8, 100)
        self.addCleanup(model.delete)
        selections = [kind(model) for kind in (QItemSelectionModel, RepeatedScanSelectionModel)]
        inputs = [model.index(section, 0) if rows else model.index(0, section) for section in range(0, 100, 2)]
        calls, results = [], []
        for selection in selections:
            self.addCleanup(selection.delete)
            selection.select(QItemSelection(model.index(0, 0), model.index(model.rows - 1, model.columns - 1)), selection.Select)
            selection.select(inputs, selection.Deselect)
            with patch.object(selection, '_section_blocking_targets', wraps=selection._section_blocking_targets) as targets:
                results.append(selection.selectedRows() if rows else selection.selectedColumns())
            calls.append(targets.call_count)
        self.assertEqual(results[0], results[1])
        self.assertEqual(calls, [1, 100])

    def test_bulk_rows_index_blockers_once_instead_of_per_candidate(self):
        self.count_scans(True)

    def test_bulk_columns_index_blockers_once_instead_of_per_candidate(self):
        self.count_scans(False)

    def test_disabled_deselect_target_blocks_even_without_membership_delta(self):
        self.model.item(2, 1).setEnabled(False)
        self.select(self.model.index(2, 0), self.fast.Select)
        self.select(self.model.index(2, 2), self.fast.Select)
        self.select(self.model.index(2, 3), self.fast.Select)
        self.select(self.model.index(2, 1), self.fast.Deselect | self.fast.Current)
        self.assertEqual(self.fast._interactive_removed, set())
        self.assertEqual(self.fast.selectedRows(), [])
        self.assertFalse(self.fast.isRowSelected(2))

    def test_toggle_removal_blocks_but_toggle_addition_does_not(self):
        self.fill()
        self.model.item(2, 1).setEnabled(False)
        self.select(self.model.index(2, 1), self.fast.ToggleCurrent)
        self.assertNotIn(self.model.index(2, 0), self.fast.selectedRows())
        self.select([], self.fast.ClearAndSelect)
        self.select(self.model.index(2, 0), self.fast.Toggle | self.fast.Rows)
        self.assertIn(self.model.index(2, 0), self.fast.selectedRows())

    def test_current_replacement_and_commit_do_not_keep_cached_blockers(self):
        self.fill()
        self.select(self.model.index(2, 1), self.fast.Deselect | self.fast.Current)
        self.select(self.model.index(4, 1), self.fast.Deselect | self.fast.Current)
        self.assertIn(self.model.index(2, 0), self.fast.selectedRows())
        self.select([], self.fast.Select)
        self.model.item(4, 1).setEnabled(False)
        self.same()
        self.assertIn(self.model.index(4, 0), self.fast.selectedRows())

    def test_parent_keys_isolate_equal_child_sections(self):
        a, b = self.model.index(0, 0), self.model.index(1, 0)
        for parent in (a, b):
            self.select(self.model.index(1, 0, parent), self.fast.Select | self.fast.Rows)
        self.select(self.model.index(1, 1, a), self.fast.Deselect)
        self.assertEqual(self.fast.selectedRows(), [self.model.index(1, 0, b)])

    def test_flag_changes_between_queries_are_not_cached(self):
        self.fill()
        self.select(self.model.index(2, 1), self.fast.Deselect)
        self.select([], self.fast.Select)
        self.model.item(2, 1).setEnabled(False)
        self.same()
        self.assertIn(self.model.index(2, 0), self.fast.selectedRows())
        self.model.item(2, 1).setEnabled(True)
        self.same()
        self.assertNotIn(self.model.index(2, 0), self.fast.selectedRows())

    def test_pending_layout_keeps_per_section_fallback(self):
        self.fill()
        self.select(self.model.index(2, 1), self.fast.Deselect)
        self.model.layoutAboutToBeChanged.emit([], QAbstractItemModel.NoLayoutChangeHint)
        with patch.object(self.fast, '_section_selected', wraps=self.fast._section_selected) as query:
            self.same()
        self.assertTrue(query.call_args_list)
        self.assertTrue(all(call.kwargs['blocked_sections'] is None for call in query.call_args_list))
        self.model.layoutChanged.emit([], QAbstractItemModel.NoLayoutChangeHint)
        self.same()

    def test_structure_clear_reset_and_queries_emit_no_selection_changes(self):
        self.fill()
        self.select(self.model.index(2, 1), self.fast.Deselect)
        self.model.insertRows(1, 1)
        self.model.removeColumns(2, 1)
        self.same()
        events = []
        self.fast.selectionChanged.connect(lambda *args: events.append(args))
        self.same()
        self.assertEqual(events, [])
        self.fast.clearSelection()
        self.reference.clearSelection()
        with patch.object(self.fast, '_section_blocking_targets', wraps=self.fast._section_blocking_targets) as targets:
            self.same()
        self.assertEqual(targets.call_count, 0)
        self.fast.reset()
        self.reference.reset()
        self.same()

    def test_seeded_commands_axes_and_eligibility_match_repeated_scan(self):
        rng = random.Random(68141)
        commands = (self.fast.Select, self.fast.ClearAndSelect, self.fast.ToggleCurrent,
                    self.fast.Deselect, self.fast.Deselect | self.fast.Current,
                    self.fast.Deselect | self.fast.Toggle)
        for step in range(100):
            row, column = rng.randrange(6), rng.randrange(4)
            self.model.item(row, column).setEnabled(bool(rng.randrange(2)))
            value = [self.model.index(rng.randrange(6), rng.randrange(4)) for _ in range(3)]
            with self.subTest(step=step):
                self.select(value, rng.choice(commands) | rng.choice((0, self.fast.Rows, self.fast.Columns)))


if __name__ == '__main__':
    unittest.main(verbosity=2)
