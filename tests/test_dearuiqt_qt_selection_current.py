"""Qt 6.8 Current selects an interactive layer, not the keyboard current index."""
from pathlib import Path
import random
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from DearUIQt.QtCore import QAbstractTableModel, QItemSelectionModel, QModelIndex


class Model(QAbstractTableModel):
    def rowCount(self, parent=None): return 10
    def columnCount(self, parent=None): return 3


class TwoLayerReference:
    """Plain committed + current selection model, deliberately not delta-based."""
    def __init__(self):
        self.committed = set()
        self.current = []
        self.command = QItemSelectionModel.NoUpdate

    @staticmethod
    def apply(base, indexes, command):
        result = set(base)
        for index in indexes:
            if command & QItemSelectionModel.Toggle:
                if index in result:
                    result.remove(index)
                else:
                    result.add(index)
            elif command & QItemSelectionModel.Deselect:
                result.discard(index)
            elif command & QItemSelectionModel.Select:
                result.add(index)
        return result

    def selected(self):
        return self.apply(self.committed, self.current, self.command)

    def select(self, indexes, command):
        if command == QItemSelectionModel.NoUpdate:
            return
        if command & QItemSelectionModel.Clear:
            self.committed.clear()
            self.current = []
        if not command & QItemSelectionModel.Current:
            self.committed = self.selected()
            self.current = []
        if command & (QItemSelectionModel.Select | QItemSelectionModel.Deselect | QItemSelectionModel.Toggle):
            self.current = list(indexes)
            self.command = command


class QtSelectionCurrentTests(unittest.TestCase):
    def setUp(self):
        self.model = Model()
        self.selection = QItemSelectionModel(self.model)
        self.addCleanup(self.model.delete)
        self.addCleanup(self.selection.delete)
        self.a, self.b, self.c = [self.model.index(row, 0) for row in range(3)]
        self.events, self.current_events = [], []
        self.selection.selectionChanged.connect(lambda added, removed: self.events.append(
            (set(added.indexes()), set(removed.indexes()))))
        self.selection.currentChanged.connect(lambda *args: self.current_events.append(args))

    def assert_selected(self, *indexes):
        self.assertEqual(set(self.selection.selectedIndexes()), set(indexes))

    def test_current_flag_does_not_move_keyboard_current(self):
        self.selection.setCurrentIndex(self.a, self.selection.NoUpdate)
        self.current_events.clear()
        self.selection.select([self.b, self.c], self.selection.SelectCurrent)
        self.assert_selected(self.b, self.c)
        self.assertEqual(self.selection.currentIndex(), self.a)
        self.assertFalse(self.current_events)

    def test_current_replaces_last_noncurrent_interactive_operation(self):
        self.selection.select(self.a, self.selection.Select)
        self.selection.select(self.b, self.selection.SelectCurrent)
        self.assert_selected(self.b)
        self.assertEqual(self.events[-1], ({self.b}, {self.a}))
        self.assertFalse(self.selection.currentIndex().isValid())

    def test_noncurrent_commits_preceding_layer_before_next_current(self):
        self.selection.select(self.a, self.selection.Select)
        self.selection.select(self.b, self.selection.Select)
        self.selection.select(self.c, self.selection.SelectCurrent)
        self.assert_selected(self.a, self.c)
        self.assertEqual(self.events[-1], ({self.c}, {self.b}))

    def test_toggle_current_restores_committed_items_before_replacement(self):
        self.selection.select(self.a, self.selection.Select)
        self.selection.select([], self.selection.Select)  # Commit a.
        self.selection.select(self.a, self.selection.ToggleCurrent)
        self.assert_selected()
        self.selection.select(self.b, self.selection.ToggleCurrent)
        self.assert_selected(self.a, self.b)

    def test_deselect_current_and_clear_current_selection(self):
        self.selection.select(self.a, self.selection.Select)
        self.selection.select([], self.selection.Select)
        self.selection.select(self.a, self.selection.Deselect | self.selection.Current)
        self.assert_selected()
        self.selection.select(self.b, self.selection.SelectCurrent)
        self.assert_selected(self.a, self.b)
        self.selection.select(self.c, self.selection.ClearAndSelect | self.selection.Current)
        self.assert_selected(self.c)
        self.selection.select(self.b, self.selection.SelectCurrent)
        self.assert_selected(self.b)

    def test_no_update_current_alone_and_current_index_clear_preserve_layer(self):
        self.selection.select(self.a, self.selection.Select)
        self.selection.select(self.b, self.selection.NoUpdate)
        self.selection.select(self.c, self.selection.Current)
        self.selection.clearCurrentIndex()
        self.selection.select(self.b, self.selection.SelectCurrent)
        self.assert_selected(self.b)

    def test_clear_selection_and_reset_cannot_resurrect_previous_layer(self):
        for operation in (self.selection.clearSelection, self.selection.reset):
            self.selection.reset()
            self.selection.select(self.a, self.selection.Select)
            self.selection.select([], self.selection.Select)
            self.selection.select(self.a, self.selection.ToggleCurrent)
            self.assert_selected()
            operation()
            self.selection.select(self.b, self.selection.SelectCurrent)
            self.assert_selected(self.b)

    def test_set_current_index_still_explicitly_selects_and_moves_current(self):
        self.selection.setCurrentIndex(self.b, self.selection.ClearAndSelect)
        self.assert_selected(self.b)
        self.assertEqual(self.selection.currentIndex(), self.b)
        self.assertEqual(len(self.current_events), 1)

    def test_rows_and_columns_expand_inside_replaced_interactive_layer(self):
        rows = self.selection.Rows
        self.selection.select(self.a, self.selection.Select | rows)
        self.selection.select(self.b, self.selection.Select | rows)
        self.selection.select(self.c, self.selection.SelectCurrent | rows)
        base = {self.model.index(0, column) for column in range(3)}
        third = {self.model.index(2, column) for column in range(3)}
        self.assert_selected(*(base | third))
        target = self.model.index(2, 1)
        self.selection.select(target, self.selection.ToggleCurrent | self.selection.Columns)
        column = {self.model.index(row, 1) for row in range(10)}
        self.assert_selected(*(base ^ column))
        self.assertFalse(self.selection.currentIndex().isValid())

    def test_seeded_sequences_match_independent_two_layer_reference(self):
        reference = TwoLayerReference()
        rng = random.Random(68012)
        commands = [self.selection.NoUpdate, self.selection.Select, self.selection.Deselect,
                    self.selection.Toggle, self.selection.Clear, self.selection.Current,
                    self.selection.SelectCurrent, self.selection.ToggleCurrent,
                    self.selection.Deselect | self.selection.Current,
                    self.selection.ClearAndSelect, self.selection.ClearAndSelect | self.selection.Current]
        pool = [self.model.index(row, column) for row in range(10) for column in range(3)]
        for _ in range(1000):
            indexes = rng.sample(pool, rng.randrange(7))
            command = rng.choice(commands)
            before = reference.selected()
            reference.select(indexes, command)
            expected = reference.selected()
            self.events.clear()
            self.selection.select(indexes, command)
            self.assertEqual(set(self.selection.selectedIndexes()), expected)
            self.assertEqual(self.events, [(expected - before, before - expected)] if expected != before else [])
            self.assertFalse(self.selection.currentIndex().isValid())


if __name__ == '__main__':
    unittest.main(verbosity=2)
