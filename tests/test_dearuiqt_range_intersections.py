"""Geometry rejection retains full range intersection/merge semantics."""
from pathlib import Path
import random
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from DearUIQt.QtCore import QItemSelection, QItemSelectionModel, QItemSelectionRange, QModelIndex
from DearUIQt.QtGui import QStandardItemModel, QStandardItem
from benchmark_dearuiqt_range_intersections import validity_first, shape
from benchmark_dearuiqt_selection_expansion import Grid


class RangeIntersectionTests(unittest.TestCase):
    def setUp(self):
        class CountingGrid(Grid):
            def __init__(self):
                super().__init__(20, 8)
                self.parent_calls = 0
            def parent(self, index):
                self.parent_calls += 1
                return super().parent(index)
        self.model = CountingGrid()
        self.addCleanup(self.model.delete)

    def area(self, top, left, bottom, right):
        return QItemSelectionRange(self.model.index(top, left), self.model.index(bottom, right))

    def test_disjoint_rows_skip_parent_and_validity_queries(self):
        a, b = self.area(0, 0, 2, 2), self.area(4, 0, 6, 2)
        with patch.object(QItemSelectionRange, 'isValid', side_effect=AssertionError('unnecessary validity query')):
            self.assertFalse(a.intersects(b))
        self.assertEqual(self.model.parent_calls, 0)
        self.assertFalse(validity_first(a, b))
        self.assertGreater(self.model.parent_calls, 0)

    def test_disjoint_columns_skip_parent_queries(self):
        a, b = self.area(0, 0, 2, 2), self.area(0, 4, 2, 6)
        self.assertFalse(a.intersects(b))
        self.assertEqual(self.model.parent_calls, 0)

    def test_shared_edges_and_corners_intersect_inclusively(self):
        a = self.area(1, 1, 3, 3)
        for b in (self.area(3, 1, 4, 2), self.area(1, 3, 2, 4), self.area(3, 3, 5, 5)):
            self.assertTrue(a.intersects(b))
            self.assertEqual(a.intersects(b), validity_first(a, b))
        self.assertGreater(self.model.parent_calls, 0)

    def test_foreign_models_reject_before_parent_queries(self):
        other = Grid(20, 8)
        self.addCleanup(other.delete)
        a, b = self.area(1, 1, 3, 3), QItemSelectionRange(other.index(1, 1), other.index(3, 3))
        self.assertFalse(a.intersects(b))
        self.assertEqual(self.model.parent_calls, 0)

    def test_equal_geometry_under_different_parents_does_not_intersect(self):
        model = QStandardItemModel()
        self.addCleanup(model.delete)
        for name in ('a', 'b'):
            item = QStandardItem(name)
            item.appendRow([QStandardItem('x'), QStandardItem('y')])
            model.appendRow(item)
        areas = [QItemSelectionRange(model.item(row).child(0, 0).index(), model.item(row).child(0, 1).index())
                 for row in (0, 1)]
        self.assertFalse(areas[0].intersects(areas[1]))
        self.assertTrue(areas[0].intersects(QItemSelectionRange(areas[0])))

    def test_invalid_and_reversed_corners_still_reject(self):
        valid = self.area(0, 0, 10, 7)
        for invalid in (QItemSelectionRange(), self.area(5, 0, 2, 3), self.area(1, 5, 3, 2),
                        QItemSelectionRange(self.model.index(1, 1), QModelIndex())):
            self.assertFalse(valid.intersects(invalid))
            self.assertFalse(invalid.intersects(valid))
            self.assertEqual(valid.intersects(invalid), validity_first(valid, invalid))

    def test_nonrange_argument_retains_false_extension(self):
        area = self.area(0, 0, 1, 1)
        for other in (None, 3, object(), QModelIndex()):
            self.assertFalse(area.intersects(other))

    def test_intersection_geometry_and_subtraction_merge_order_match_reference(self):
        original = QItemSelection([self.area(0, 0, 6, 6), self.area(10, 0, 12, 3)])
        incoming = QItemSelection([self.area(2, 2, 4, 4), self.area(15, 1, 17, 3)])
        for command in (QItemSelectionModel.Select, QItemSelectionModel.Deselect, QItemSelectionModel.Toggle):
            actual, expected = QItemSelection(original), QItemSelection(original)
            actual.merge(incoming, command)
            with patch.object(QItemSelectionRange, 'intersects', validity_first):
                expected.merge(incoming, command)
            self.assertEqual(shape(actual), shape(expected))
            self.assertEqual(actual.indexes(), expected.indexes())

    def test_many_disjoint_pairs_have_zero_parent_queries(self):
        left = [self.area(row, 0, row, 1) for row in range(10)]
        right = [self.area(row, 0, row, 1) for row in range(10, 20)]
        selection = QItemSelection(left)
        selection.merge(QItemSelection(right), QItemSelectionModel.Toggle)
        # Incoming validity checks are required once, independently of the
        # pair scan. Every disjoint pair itself must avoid parent queries.
        self.assertEqual(self.model.parent_calls, 2 * len(right))
        self.assertEqual(shape(selection), shape(left + right))

    def test_seeded_geometry_matches_validity_first_and_symmetry(self):
        rng = random.Random(68172)
        for step in range(300):
            a, b = (self.area(rng.randrange(20), rng.randrange(8), rng.randrange(20), rng.randrange(8))
                    for _ in range(2))
            with self.subTest(step=step):
                self.assertEqual(a.intersects(b), validity_first(a, b))
                self.assertEqual(a.intersects(b), b.intersects(a))


if __name__ == '__main__':
    unittest.main(verbosity=2)
