"""Prove range-commit fast path preserves the full-merge state/shape/signals."""
from pathlib import Path
import random
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from DearUIQt.QtCore import QItemSelection, QItemSelectionRange, QItemSelectionModel, Qt, QAbstractItemModel
from DearUIQt.QtGui import QStandardItemModel, QStandardItem
from benchmark_dearuiqt_selection_ranges import FullMergeSelectionModel, Rows


class SelectionRangeFastPathTests(unittest.TestCase):
    def setUp(self):
        self.model = QStandardItemModel()
        for row in range(8):
            self.model.appendRow([QStandardItem('%d:%d' % (row, col)) for col in range(3)])
        for row in (0, 1):
            self.model.item(row).appendRows([QStandardItem('child%d' % child) for child in range(3)])
        self.addCleanup(self.model.delete)
        self.fast = QItemSelectionModel(self.model)
        self.reference = FullMergeSelectionModel(self.model)
        self.addCleanup(self.fast.delete)
        self.addCleanup(self.reference.delete)
        self.events = {self.fast: [], self.reference: []}
        for selection in (self.fast, self.reference):
            selection.selectionChanged.connect(lambda added, removed, selection=selection: self.events[selection].append(
                (tuple(self.key(index) for index in added.indexes()), tuple(self.key(index) for index in removed.indexes()))))

    @staticmethod
    def key(index):
        path = []
        while index.isValid():
            path.append((index.row(), index.column()))
            index = index.parent()
        return tuple(reversed(path))

    def signature(self, selection):
        shape = lambda areas: [(self.key(area.topLeft()), self.key(area.bottomRight())) for area in areas]
        return (set(selection._selected), set(selection._interactive_added), set(selection._interactive_removed),
                selection.currentIndex(), shape(selection._committed_ranges), shape(selection._live_ranges),
                selection._live_command, selection._interactive_command, tuple(selection._interactive_targets))

    def same(self):
        self.assertEqual(self.signature(self.fast), self.signature(self.reference))
        self.assertEqual(self.events[self.fast], self.events[self.reference])

    def select(self, value, command):
        for selection in (self.fast, self.reference):
            selection.select(value, command)
        self.same()

    def test_many_disjoint_adds_do_not_call_full_range_merge(self):
        model = Rows(3100)
        self.addCleanup(model.delete)
        selection = QItemSelectionModel(model)
        self.addCleanup(selection.delete)
        selection.select([model.index(row) for row in range(3000)], selection.Select)
        selection.select([], selection.Select)
        original = QItemSelection.merge
        with patch.object(QItemSelection, 'merge', autospec=True, side_effect=original) as merge:
            for row in range(3000, 3100):
                selection.select(model.index(row), selection.Select)
            selection.select([], selection.Select)
        self.assertEqual(merge.call_count, 0)
        self.assertEqual(len(selection.selectedIndexes()), 3100)
        self.assertEqual(len(selection._committed_ranges), 3100)

    def test_overlap_uses_full_merge_and_preserves_rectangular_splits(self):
        self.select(QItemSelection(self.model.index(1, 0), self.model.index(3, 1)), self.fast.Select)
        self.select(QItemSelection(self.model.index(2, 0), self.model.index(4, 1)), self.fast.Select)
        self.assertFalse(self.fast._live_disjoint)
        original = QItemSelection.merge
        with patch.object(QItemSelection, 'merge', autospec=True, side_effect=original) as merge:
            self.fast.select([], self.fast.Select)
        self.assertEqual(merge.call_count, 1)
        self.reference.select([], self.reference.Select)
        self.same()

    def test_current_replacement_proof_is_relative_to_committed_layer(self):
        for row, command in ((1, self.fast.Select), (3, self.fast.SelectCurrent),
                             (2, self.fast.Select), (3, self.fast.SelectCurrent)):
            self.select(self.model.index(row, 0), command)
        self.assertFalse(self.fast._live_disjoint)
        self.select([], self.fast.Select)

    def test_overlapping_incoming_ranges_keep_exact_range_shape_when_disjoint_from_base(self):
        area = QItemSelection([QItemSelectionRange(self.model.index(1, 0), self.model.index(2, 1)),
                               QItemSelectionRange(self.model.index(2, 0), self.model.index(3, 1))])
        self.select(area, self.fast.Select)
        self.assertTrue(self.fast._live_disjoint)
        self.select([], self.fast.Select)
        self.assertEqual(len(self.fast._committed_ranges), 2)

    def test_equal_coordinates_under_different_parents_are_disjoint(self):
        for parent in (self.model.index(0, 0), self.model.index(1, 0)):
            self.select(self.model.index(1, 0, parent), self.fast.Select)
            self.assertTrue(self.fast._live_disjoint)
        self.select([], self.fast.Select)

    def test_reset_clear_and_model_switch_drop_cached_proof(self):
        self.fast.select(self.model.index(1, 0), self.fast.Select)
        self.assertTrue(self.fast._live_disjoint)
        self.fast.clearSelection()
        self.assertFalse(self.fast._live_disjoint)
        self.fast.select(self.model.index(1, 0), self.fast.Select)
        self.fast.reset()
        self.assertFalse(self.fast._live_disjoint)
        self.fast.setModel(None)
        self.assertFalse(self.fast._live_disjoint)

    def test_structural_and_layout_reconstruction_invalidate_cached_proof(self):
        self.select(self.model.index(2, 0), self.fast.Select)
        self.model.sort(0, Qt.DescendingOrder)
        self.assertFalse(self.fast._live_disjoint)
        self.same()
        self.select(self.model.index(1, 0), self.fast.Select)
        self.model.insertRows(0, 1)
        self.assertFalse(self.fast._live_disjoint)
        self.same()

    def test_pending_layout_snapshot_forces_full_merge(self):
        self.select(self.model.index(1, 0), self.fast.Select)
        self.model.layoutAboutToBeChanged.emit([], QAbstractItemModel.NoLayoutChangeHint)
        original = QItemSelection.merge
        with patch.object(QItemSelection, 'merge', autospec=True, side_effect=original) as merge:
            self.fast.select(self.model.index(2, 0), self.fast.Select)
        self.assertGreater(merge.call_count, 0)
        self.assertFalse(self.fast._live_disjoint)
        self.reference.select(self.model.index(2, 0), self.reference.Select)
        self.model.layoutChanged.emit([], QAbstractItemModel.NoLayoutChangeHint)
        self.same()

    def test_reentrant_selection_callback_can_clear_without_resurrecting_proof(self):
        for selection in (self.fast, self.reference):
            remaining = [True]
            def changed(*args, selection=selection, remaining=remaining):
                if remaining[0]:
                    remaining[0] = False
                    selection.clearSelection()
            selection.selectionChanged.connect(changed)
        self.select(self.model.index(1, 0), self.fast.Select)
        self.assertFalse(self.fast._live_disjoint)
        self.select(self.model.index(2, 0), self.fast.Select)

    def test_seeded_mixed_commands_match_full_merge_state_shape_and_events(self):
        rng = random.Random(68111)
        commands = (self.fast.Select, self.fast.Select, self.fast.SelectCurrent, self.fast.Deselect,
                    self.fast.ToggleCurrent, self.fast.ClearAndSelect, self.fast.Select | self.fast.Toggle)
        for step in range(100):
            top, bottom = sorted((rng.randrange(8), rng.randrange(8)))
            left, right = sorted((rng.randrange(3), rng.randrange(3)))
            area = QItemSelection(self.model.index(top, left), self.model.index(bottom, right))
            command = rng.choice(commands) | rng.choice((0, self.fast.Rows, self.fast.Columns))
            with self.subTest(step=step):
                self.select(area, command)


if __name__ == '__main__':
    unittest.main(verbosity=2)
