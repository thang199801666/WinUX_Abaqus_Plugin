"""Same-handle singleton validation without caching model queries or flags."""
from pathlib import Path
import random
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from DearUIQt.QtCore import QItemSelection, QItemSelectionRange, QModelIndex
from DearUIQt.QtGui import QStandardItem, QStandardItemModel
from benchmark_dearuiqt_selection_expansion import Grid
from benchmark_dearuiqt_range_validation import full_validity


class CountingGrid(Grid):
    def __init__(self):
        super().__init__(4, 4)
        self.parent_calls = 0
        self.index_calls = 0
        self.missing = set()

    def parent(self, index):
        self.parent_calls += 1
        return super().parent(index)

    def index(self, row, column, parent=QModelIndex()):
        self.index_calls += 1
        return QModelIndex() if (row, column) in self.missing else super().index(row, column, parent)


class RangeValidationTests(unittest.TestCase):
    def setUp(self):
        self.model = CountingGrid()
        self.addCleanup(self.model.delete)

    def test_same_handle_singleton_skips_redundant_parent_queries(self):
        area = QItemSelectionRange(self.model.index(1, 1))
        self.assertTrue(area.isValid())
        self.assertEqual(self.model.parent_calls, 0)
        self.assertTrue(full_validity(area))
        self.assertEqual(self.model.parent_calls, 2)

    def test_invalid_singleton_and_default_range_remain_invalid(self):
        for area in (QItemSelectionRange(), QItemSelectionRange(QModelIndex()),
                     QItemSelectionRange(self.model.createIndex(-1, 0))):
            self.assertFalse(area.isValid())
            self.assertEqual(area.isValid(), full_validity(area))
            self.assertEqual(area.indexes(), [])
        self.assertEqual(self.model.parent_calls, 0)

    def test_equal_but_distinct_handles_keep_full_validation(self):
        a, b = self.model.index(1, 1), self.model.index(1, 1)
        self.assertEqual(a, b)
        self.assertIsNot(a, b)
        self.assertTrue(QItemSelectionRange(a, b).isValid())
        self.assertEqual(self.model.parent_calls, 2)

    def test_rectangles_and_reversed_corners_keep_full_validation(self):
        for coordinates, valid in (((0, 0, 3, 3), True), ((3, 0, 0, 3), False),
                                   ((0, 3, 3, 0), False), ((3, 3, 0, 0), False)):
            a, b = self.model.index(*coordinates[:2]), self.model.index(*coordinates[2:])
            area = QItemSelectionRange(a, b)
            self.assertEqual(area.isValid(), valid)
            self.assertEqual(area.isValid(), full_validity(area))
        self.assertGreater(self.model.parent_calls, 0)

    def test_foreign_model_corners_remain_invalid(self):
        other = CountingGrid()
        self.addCleanup(other.delete)
        area = QItemSelectionRange(self.model.index(1, 1), other.index(1, 1))
        self.assertFalse(area.isValid())
        self.assertEqual(area.indexes(), [])

    def test_different_parents_and_nested_singleton_remain_isolated(self):
        model = QStandardItemModel()
        self.addCleanup(model.delete)
        for name in ('a', 'b'):
            item = QStandardItem(name)
            item.appendRow(QStandardItem('child'))
            model.appendRow(item)
        a, b = (model.item(row).child(0).index() for row in (0, 1))
        self.assertFalse(QItemSelectionRange(a, b).isValid())
        area = QItemSelectionRange(a)
        self.assertTrue(area.isValid())
        self.assertEqual(area.parent(), a.parent())
        self.assertEqual(area.indexes(), [a])

    def test_flags_are_queried_again_after_each_change(self):
        model = QStandardItemModel(1, 1)
        self.addCleanup(model.delete)
        item = QStandardItem('a')
        model.setItem(0, 0, item)
        index = item.index()
        area = QItemSelectionRange(index)
        self.assertEqual(area.indexes(), [index])
        item.setEnabled(False)
        self.assertTrue(area.isValid())
        self.assertTrue(area.isEmpty())
        self.assertEqual(area.indexes(), [])
        item.setEnabled(True)
        item.setSelectable(False)
        self.assertEqual(area.indexes(), [])
        item.setSelectable(True)
        self.assertEqual(area.indexes(), [index])

    def test_singleton_enumeration_still_calls_model_index(self):
        index = self.model.index(1, 1)
        area = QItemSelectionRange(index)
        self.model.index_calls = 0
        self.assertEqual(area.indexes(), [index])
        self.assertEqual(self.model.index_calls, 1)
        # Synthetic sparse-model diagnostic: do not substitute the stored
        # corner for a fresh model.index(), even on the singleton shortcut.
        self.model.missing.add((1, 1))
        self.assertEqual(area.indexes(), [])
        self.assertEqual(self.model.index_calls, 2)

    def test_copy_and_overlapping_payload_keep_duplicate_index_order(self):
        a, b = self.model.index(1, 1), self.model.index(2, 2)
        original = QItemSelectionRange(a)
        copied = QItemSelectionRange(original)
        self.assertEqual(original, copied)
        self.assertTrue(copied.isValid())
        payload = QItemSelection([original, QItemSelectionRange(b), copied])
        self.assertEqual(payload.indexes(), [a, b, a])

    def test_seeded_corner_validity_matches_full_reference(self):
        rng = random.Random(68161)
        indexes = [self.model.index(row, column) for row in range(4) for column in range(4)] + [QModelIndex()]
        for step in range(200):
            a = rng.choice(indexes)
            b = a if step % 2 else rng.choice(indexes)
            area = QItemSelectionRange(a, b)
            with self.subTest(step=step):
                self.assertEqual(area.isValid(), full_validity(area))


if __name__ == '__main__':
    unittest.main(verbosity=2)
