"""Fused membership/delta updates preserve per-index selection contracts."""
from pathlib import Path
import random
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from DearUIQt.QtCore import QItemSelectionModel, QItemSelection, QModelIndex, QAbstractItemModel
from DearUIQt.QtGui import QStandardItemModel, QStandardItem
from benchmark_dearuiqt_selection_membership import PerIndexSelectionModel


class SelectionMembershipTests(unittest.TestCase):
    def setUp(self):
        self.model = QStandardItemModel()
        for row in range(6):
            self.model.appendRow([QStandardItem('%d:%d' % (row, column)) for column in range(4)])
        for row in (0, 1):
            self.model.item(row).appendRow([QStandardItem('a'), QStandardItem('b')])
        self.addCleanup(self.model.delete)
        self.fast, self.reference = QItemSelectionModel(self.model), PerIndexSelectionModel(self.model)
        self.addCleanup(self.fast.delete)
        self.addCleanup(self.reference.delete)
        self.events = {self.fast: [], self.reference: []}
        for selection in self.events:
            selection.selectionChanged.connect(lambda added, removed, selection=selection: self.events[selection].append(
                (tuple(self.key(index) for index in added.indexes()), tuple(self.key(index) for index in removed.indexes()))))

    @staticmethod
    def key(index):
        path = []
        while index.isValid():
            path.append((index.row(), index.column()))
            index = index.parent()
        return tuple(reversed(path))

    def same(self):
        def state(selection):
            return (selection._selected, selection._interactive_added, selection._interactive_removed,
                    selection._interactive_targets, selection._interactive_command,
                    selection._committed_ranges, selection._live_ranges, selection._live_command,
                    selection._live_disjoint, selection.currentIndex())
        self.assertEqual(state(self.fast), state(self.reference))
        self.assertEqual(self.events[self.fast], self.events[self.reference])
        self.assertEqual(self.fast.selectedRows(), self.reference.selectedRows())
        self.assertEqual(self.fast.selectedColumns(), self.reference.selectedColumns())

    def select(self, value, command):
        for selection in self.events:
            selection.select(value, command)
        self.same()

    def test_all_mutation_flag_combinations_preserve_precedence(self):
        values = [self.model.index(row, 0) for row in range(4)]
        for bits in range(8):
            for selection in self.events:
                selection._selected = set(values[:2])
                added, removed = selection._apply_selection_indexes(dict.fromkeys(values[1:]),
                                                                   bool(bits & 1), bool(bits & 2), bool(bits & 4))
                old, targets = set(values[:2]), set(values[1:])
                expected = old - targets if bits & 2 else old ^ targets if bits & 4 else old | targets if bits & 1 else old
                self.assertEqual(selection._selected, expected)
                self.assertEqual(added, expected - old)
                self.assertEqual(removed, old - expected)

    def test_no_update_does_not_consume_input_and_nonmutating_helper_is_noop(self):
        self.select(self.model.index(0, 0), self.fast.Select)
        def forbidden():
            raise AssertionError('NoUpdate consumed input')
            yield
        self.select(forbidden(), self.fast.NoUpdate)
        for selection in self.events:
            old = set(selection._selected)
            self.assertEqual(selection._apply_selection_indexes({}, False, False, False), (set(), set()))
            self.assertEqual(selection._selected, old)

    def test_reselect_overlap_has_empty_delta_and_no_signal(self):
        area = QItemSelection(self.model.index(0, 0), self.model.index(5, 3))
        self.select(area, self.fast.Select)
        count = len(self.events[self.fast])
        self.select(area, self.fast.Select)
        self.assertEqual(len(self.events[self.fast]), count)
        self.assertEqual(self.fast._interactive_added, set())

    def test_duplicate_toggles_are_normalized_once(self):
        a, b = self.model.index(0, 0), self.model.index(1, 1)
        self.select([a, a, b, a], self.fast.Toggle)
        self.assertEqual(self.fast._selected, {a, b})
        self.select([b, a, a], self.fast.Toggle)
        self.assertEqual(self.fast._selected, set())

    def test_current_replacement_clear_and_deselect_target_order(self):
        self.select(self.model.index(2, 1), self.fast.Select | self.fast.Rows)
        self.select([self.model.index(2, col) for col in (3, 0, 3, 1)], self.fast.Deselect | self.fast.Current)
        self.assertEqual([index.column() for index in self.fast._interactive_targets], [3, 0, 1])
        self.select(self.model.index(4, 1), self.fast.SelectCurrent)
        self.select(self.model.index(1, 0), self.fast.ClearAndSelect | self.fast.Current)
        self.select([], self.fast.Select)

    def test_axes_disabled_cells_foreign_indexes_and_nested_parent_identity(self):
        self.model.item(2, 1).setEnabled(False)
        other = QStandardItemModel(1, 1)
        self.addCleanup(other.delete)
        for parent in (self.model.index(0, 0), self.model.index(1, 0)):
            self.select([self.model.index(0, 0, parent), other.index(0, 0)], self.fast.Select | self.fast.Rows)
        for flag in (self.fast.Rows, self.fast.Columns, self.fast.Rows | self.fast.Columns):
            self.select([self.model.index(2, 1), QModelIndex()], self.fast.Toggle | flag)

    def test_pending_layout_and_structural_followup_match_reference(self):
        self.select(QItemSelection(self.model.index(1, 0), self.model.index(4, 3)), self.fast.Select)
        self.model.layoutAboutToBeChanged.emit([], QAbstractItemModel.NoLayoutChangeHint)
        self.select(self.model.index(2, 1), self.fast.Deselect)
        self.model.layoutChanged.emit([], QAbstractItemModel.NoLayoutChangeHint)
        self.same()
        self.model.insertRows(2, 1)
        self.model.removeColumns(1, 1)
        self.same()

    def test_reentrant_clear_then_nested_select_keeps_net_layers(self):
        for selection in self.events:
            remaining = [True]
            def changed(*args, selection=selection, remaining=remaining):
                if remaining[0]:
                    remaining[0] = False
                    selection.clearSelection()
                    selection.select(self.model.index(5, 3), selection.Select)
            selection.selectionChanged.connect(changed)
        self.select(QItemSelection(self.model.index(0, 0), self.model.index(3, 2)), self.fast.Select)
        self.select(self.model.index(1, 1), self.fast.ToggleCurrent)

    def test_bulk_reselection_avoids_repeated_python_hash_lookups(self):
        class CountingIndex(QModelIndex):
            calls = 0
            def __hash__(self):
                type(self).calls += 1
                return super().__hash__()
        inputs = dict.fromkeys(CountingIndex(row, 0, self.model) for row in range(100))
        counts = []
        for selection in (self.fast, self.reference):
            selection._selected = set(inputs)
            CountingIndex.calls = 0
            added, removed = selection._apply_selection_indexes(inputs, True, False, False)
            counts.append(CountingIndex.calls)
            self.assertEqual((added, removed), (set(), set()))
        self.assertLess(counts[0], counts[1])
        self.assertGreaterEqual(counts[1], 200)

    def test_seeded_flags_and_input_shapes_match_per_index_path(self):
        rng = random.Random(68151)
        for step in range(150):
            points = [self.model.index(rng.randrange(6), rng.randrange(4)) for _ in range(3)]
            value = points if step % 2 else QItemSelection(points[0], points[-1])
            command = rng.randrange(128)
            with self.subTest(step=step, command=command):
                self.select(value, command)


if __name__ == '__main__':
    unittest.main(verbosity=2)
