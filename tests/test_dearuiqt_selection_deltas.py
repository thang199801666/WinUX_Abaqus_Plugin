"""Core-only selection deltas, duplicate commands and callback reentrancy."""
from pathlib import Path
import random
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from DearUIQt.core import QAbstractTableModel, QModelIndex, QItemSelectionModel


class Model(QAbstractTableModel):
    def rowCount(self, parent=None): return 20
    def columnCount(self, parent=None): return 4


def legacy_select(selection_model, indexes, command):
    """Historical reference for non-Current paths/benchmarks, not Qt conformance.

    Its Current behavior is intentionally obsolete; see the independent Qt
    two-layer tests in test_dearuiqt_qt_selection_current.py.
    """
    indexes = [index for index in indexes if index.isValid() and index.model() is selection_model.model()]
    before = set(selection_model._selected)
    if command & selection_model.Clear:
        selection_model._selected.clear()
    if command & selection_model.Rows:
        indexes = [selection_model.model().index(index.row(), column, index.parent())
                   for index in indexes for column in range(selection_model.model().columnCount(index.parent()))]
    elif command & selection_model.Columns:
        indexes = [selection_model.model().index(row, index.column(), index.parent())
                   for index in indexes for row in range(selection_model.model().rowCount(index.parent()))]
    for index in indexes:
        if command & selection_model.Toggle:
            if index in selection_model._selected:
                selection_model._selected.remove(index)
            else:
                selection_model._selected.add(index)
        elif command & selection_model.Deselect:
            selection_model._selected.discard(index)
        elif command & selection_model.Select:
            selection_model._selected.add(index)
    if command & selection_model.Current and indexes:
        selection_model.setCurrentIndex(indexes[-1], selection_model.NoUpdate)
    after = set(selection_model._selected)
    return after - before, before - after


class SelectionDeltaTests(unittest.TestCase):
    def setUp(self):
        self.model = Model()
        self.selection = QItemSelectionModel(self.model)
        self.addCleanup(self.selection.delete)
        self.events = []
        self.selection.selectionChanged.connect(lambda added, removed: self.events.append(
            (set(added.indexes()), set(removed.indexes()))))

    def test_add_remove_and_unchanged_local_edits(self):
        a, b = self.model.index(1, 0), self.model.index(2, 1)
        self.selection.select([a, b], self.selection.Select)
        self.assertEqual(self.events, [({a, b}, set())])
        self.selection.select(a, self.selection.Select)
        self.assertEqual(len(self.events), 1)
        self.selection.select(a, self.selection.Deselect)
        self.assertEqual(self.events[-1], (set(), {a}))
        self.assertEqual(set(self.selection.selectedIndexes()), {b})

    def test_duplicate_toggles_emit_only_net_delta(self):
        a = self.model.index(1, 0)
        self.selection.select([a, a], self.selection.Toggle)
        self.assertEqual(self.events, [({a}, set())])
        self.selection.select([a, a, a], self.selection.Toggle)
        self.assertEqual(self.events[-1], (set(), {a}))
        self.selection.select([a, a], self.selection.Toggle)
        self.assertEqual(self.events[-1], ({a}, set()))

    def test_explicit_current_index_callback_can_add_nested_selection(self):
        a, b = self.model.index(1, 0), self.model.index(9, 3)
        self.selection.currentChanged.connect(lambda *args: self.selection.select(b, self.selection.Select))
        self.selection.setCurrentIndex(a, self.selection.Select)
        self.assertEqual(self.events, [({a}, set()), ({b}, set())])
        self.assertEqual(self.selection.currentIndex(), a)

    def test_clear_and_invalid_or_foreign_indexes(self):
        a = self.model.index(1, 0)
        foreign = Model()
        self.selection.select(a, self.selection.Select)
        self.events.clear()
        self.selection.select([QModelIndex(), foreign.index(0, 0)], self.selection.ClearAndSelect)
        self.assertEqual(self.events, [(set(), {a})])
        self.assertFalse(self.selection.hasSelection())

    def test_selection_callback_can_clear_then_accept_next_local_edit(self):
        a, b = self.model.index(1, 0), self.model.index(2, 0)
        once = [False]
        def clear_once(*args):
            if not once[0]:
                once[0] = True
                self.selection.clearSelection()
        self.selection.selectionChanged.connect(clear_once)
        self.selection.select(a, self.selection.Select)
        self.assertEqual(self.events, [({a}, set()), (set(), {a})])
        self.assertFalse(self.selection.hasSelection())
        self.selection.select(b, self.selection.Select)
        self.assertEqual(self.events[-1], ({b}, set()))
        self.assertEqual(set(self.selection.selectedIndexes()), {b})

    def test_no_update_does_not_consume_input_or_emit(self):
        def invalid_input():
            raise AssertionError('NoUpdate should not enumerate indexes')
            yield
        self.selection.select(invalid_input(), self.selection.NoUpdate)
        self.assertFalse(self.events)

    def test_rows_columns_and_mixed_commands_match_full_copy_reference(self):
        rng = random.Random(7281)
        reference = QItemSelectionModel(self.model)
        self.addCleanup(reference.delete)
        commands = [self.selection.Select, self.selection.Deselect, self.selection.Toggle,
                    self.selection.ClearAndSelect, self.selection.Clear,
                    self.selection.Select | self.selection.Toggle,
                    self.selection.Select | self.selection.Deselect]
        for _ in range(500):
            indexes = [self.model.index(rng.randrange(20), rng.randrange(4)) for _ in range(rng.randrange(6))]
            if indexes and rng.choice((True, False)):
                indexes += indexes[:2]
            command = rng.choice(commands) | rng.choice((0, self.selection.Rows, self.selection.Columns))
            # Historical reference is retained only for non-overlapping inputs;
            # duplicate/overlap handling now follows the Qt selection contract.
            if command & self.selection.Rows:
                indexes = list({index.row(): index for index in indexes}.values())
            elif command & self.selection.Columns:
                indexes = list({index.column(): index for index in indexes}.values())
            else:
                indexes = list(dict.fromkeys(indexes))
            added, removed = legacy_select(reference, indexes, command)
            self.events.clear()
            self.selection.select(indexes, command)
            self.assertEqual(self.selection._selected, reference._selected)
            self.assertEqual(self.selection.currentIndex(), reference.currentIndex())
            self.assertEqual(self.events, [(added, removed)] if added or removed else [])


if __name__ == '__main__':
    unittest.main(verbosity=2)
