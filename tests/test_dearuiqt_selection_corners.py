"""Qt 6.8 corner-handle identity and construction call-count contracts."""
from pathlib import Path
import random
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from DearUIQt.QtCore import QItemSelection, QItemSelectionModel, QModelIndex
from DearUIQt.QtGui import QStandardItem, QStandardItemModel
from benchmark_dearuiqt_selection_expansion import Grid
from benchmark_dearuiqt_selection_corners import reindex_select


class CornerGrid(Grid):
    def __init__(self):
        super().__init__(4, 4)
        self.tokens = [object(), object()]
        self.phase = 0
        self.calls = 0

    def index(self, row, column, parent=QModelIndex()):
        self.calls += 1
        return (self.createIndex(row, column, self.tokens[self.phase])
                if self.hasIndex(row, column, parent) else QModelIndex())


class SelectionCornerTests(unittest.TestCase):
    def setUp(self):
        self.model = CornerGrid()
        self.addCleanup(self.model.delete)

    def test_ordered_corners_preserve_original_handles_without_reindex(self):
        a, b = self.model.index(0, 1), self.model.index(3, 2)
        self.model.phase, self.model.calls = 1, 0
        selection = QItemSelection(a, b)
        self.assertEqual(self.model.calls, 0)
        self.assertEqual(selection[0].topLeft(), a)
        self.assertEqual(selection[0].bottomRight(), b)
        self.assertIs(selection[0].topLeft().internalPointer(), self.model.tokens[0])

    def test_equal_but_distinct_singleton_handles_are_retained(self):
        a, b = self.model.index(1, 1), self.model.index(1, 1)
        self.model.phase, self.model.calls = 1, 0
        selection = QItemSelection(a, b)
        self.assertEqual(self.model.calls, 0)
        self.assertEqual(selection[0].topLeft(), a)
        self.assertEqual(selection[0].bottomRight(), b)

    def reversed(self, coordinates):
        a, b = self.model.index(*coordinates[:2]), self.model.index(*coordinates[2:])
        self.model.phase, self.model.calls = 1, 0
        selection = QItemSelection(a, b)
        self.assertEqual(self.model.calls, 2)
        area = selection[0]
        self.assertEqual((area.top(), area.left(), area.bottom(), area.right()), (0, 1, 3, 2))
        self.assertIs(area.topLeft().internalPointer(), self.model.tokens[1])
        self.assertIs(area.bottomRight().internalPointer(), self.model.tokens[1])

    def test_reversed_rows_reindex_both_corners(self):
        self.reversed((3, 1, 0, 2))

    def test_reversed_columns_reindex_both_corners(self):
        self.reversed((0, 2, 3, 1))

    def test_reversed_both_axes_reindex_both_corners(self):
        self.reversed((3, 2, 0, 1))

    def test_invalid_corner_does_not_append_or_reindex(self):
        index = self.model.index(0, 0)
        self.model.calls = 0
        selection = QItemSelection()
        selection.select(index, QModelIndex())
        selection.select(QModelIndex(), index)
        self.assertEqual(selection, [])
        self.assertEqual(self.model.calls, 0)

    def test_different_models_do_not_append(self):
        other = CornerGrid()
        self.addCleanup(other.delete)
        self.assertEqual(QItemSelection(self.model.index(0, 0), other.index(1, 1)), [])

    def test_same_coordinates_under_different_parents_do_not_append(self):
        model = QStandardItemModel()
        self.addCleanup(model.delete)
        for name in ('a', 'b'):
            item = QStandardItem(name)
            item.appendRow(QStandardItem('child'))
            model.appendRow(item)
        a, b = (model.item(row).child(0).index() for row in (0, 1))
        self.assertEqual(QItemSelection(a, b), [])
        selection = QItemSelection(a, a)
        self.assertEqual(selection[0].parent(), a.parent())

    def test_bulk_delta_payloads_do_not_reindex_ordered_singletons(self):
        selection = QItemSelectionModel(self.model)
        self.addCleanup(selection.delete)
        inputs = [self.model.index(row, column) for row in range(4) for column in range(4)]
        events = []
        selection.selectionChanged.connect(lambda added, removed: events.append(
            ([area.topLeft() for area in added], [area.topLeft() for area in removed])))
        self.model.calls = 0
        selection.select(inputs, selection.Select)
        selection.select(inputs[::2], selection.Deselect)
        self.assertEqual(self.model.calls, 0)
        self.assertEqual(events, [(inputs, []), ([], inputs[::2])])
        self.assertEqual(set(selection._selected), set(inputs[1::2]))

    def test_seeded_normalization_matches_previous_geometry_and_coverage(self):
        # Stable pointer identities make the old path a valid geometry reference.
        rng = random.Random(68131)
        for _ in range(100):
            a, b = (self.model.index(rng.randrange(4), rng.randrange(4)) for _ in range(2))
            expected, actual = QItemSelection(), QItemSelection(a, b)
            reindex_select(expected, a, b)
            self.assertEqual(actual, expected)
            self.assertEqual(actual.indexes(), expected.indexes())


if __name__ == '__main__':
    unittest.main(verbosity=2)
