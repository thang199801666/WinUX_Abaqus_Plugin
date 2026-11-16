"""CSV axis sorting and compatibility with previously saved workspaces."""
import copy
import csv
import os
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'vendor'))
sys.path.insert(0, str(ROOT))
from PIL import Image
from WinUx.plotdigitizer.core import DigitizerEngine
from WinUx.plotdigitizer.application.workspace_state import normalize_workspace_state


class DigitizerCsvSortTests(unittest.TestCase):
    def setUp(self):
        self.engine = DigitizerEngine()
        self.engine.apply_image(Image.new('RGB', (100, 100), 'white'), 'test.png')
        for key, x, y, value in (('x1', 0, 0, 0), ('x2', 99, 0, 99),
                                  ('y1', 0, 0, 99), ('y2', 0, 99, 0)):
            self.engine.set_anchor(key, x, y, value)
        for point in ((30, 80), (10, 20), (20, 50)):
            self.engine.add_manual_point(*point)
        self.directory = tempfile.TemporaryDirectory(
            dir=Path(os.environ['LOCALAPPDATA']) / 'Temp' / 'opencode')
        self.addCleanup(self.directory.cleanup)

    def export(self, **kwargs):
        path = Path(self.directory.name) / 'points.csv'
        self.engine.export_csv(str(path), **kwargs)
        with path.open(newline='', encoding='utf-8') as file:
            return list(csv.DictReader(file))

    def test_original_and_both_axis_orders(self):
        for axis, expected in ((None, [30, 10, 20]), ('x', [10, 20, 30]), ('y', [30, 20, 10])):
            with self.subTest(axis=axis):
                rows = self.export(sort_by=axis)
                self.assertEqual([round(float(row['X'])) for row in rows], expected)
                self.assertEqual([int(row['Index']) for row in rows], [1, 2, 3])

    def test_sort_does_not_mutate_points_or_history(self):
        before = copy.deepcopy(self.engine.active_dataset.manual_points)
        revision = self.engine.revision
        self.export(sort_by='y')
        self.assertEqual(self.engine.active_dataset.manual_points, before)
        self.assertEqual(self.engine.revision, revision)

    def test_mixed_points_sort_stably_at_equal_coordinates(self):
        self.engine.active_dataset.extracted_pixels = [(20, 30)]
        self.engine.recompute_all_data()
        rows = self.export(sort_by='x')
        tied = [row for row in rows if round(float(row['X'])) == 20]
        self.assertEqual([row['Source'] for row in tied], ['Smart', 'Manual'])
        rows = self.export(sort_by='y')
        values = [float(row['Y']) for row in rows]
        self.assertEqual(values, sorted(values))

    def test_old_keyword_still_sorts_x_and_explicit_axis_wins(self):
        self.assertEqual([round(float(row['X'])) for row in self.export(sort_by_x=True)], [10, 20, 30])
        self.assertEqual([round(float(row['X'])) for row in self.export(sort_by_x=True, sort_by='y')], [30, 20, 10])

    def test_each_dataset_is_sorted_independently_and_scope_is_preserved(self):
        index = self.engine.add_dataset('Other')
        self.engine.set_active_dataset(index)
        self.engine.add_manual_point(5, 10)
        self.engine.add_manual_point(8, 90)
        rows = self.export(sort_by='y')
        self.assertEqual([row['Dataset'] for row in rows], ['Serie-1'] * 3 + ['Other'] * 2)
        self.assertEqual([round(float(row['X'])) for row in rows[-2:]], [8, 5])
        self.assertEqual(len(self.export(dataset_index=index, sort_by='y')), 2)

    def test_invalid_axis_does_not_create_a_file(self):
        with self.assertRaises(ValueError):
            self.export(sort_by='z')
        self.assertFalse((Path(self.directory.name) / 'points.csv').exists())

    def test_workspace_migrates_old_checkbox_without_losing_y(self):
        for old, expected in ((False, 'original'), (True, 'x')):
            self.assertEqual(normalize_workspace_state(
                {'version': 1, 'export_sort_x': old})['export_sort'], expected)
        saved = normalize_workspace_state({'version': 1, 'export_sort': 'y'})
        self.assertEqual(saved['export_sort'], 'y')
        self.assertEqual(normalize_workspace_state(saved), saved)
        self.assertFalse(saved['export_sort_x'])
        with self.assertRaises(ValueError):
            normalize_workspace_state({'version': 1, 'export_sort': 'z'})


if __name__ == '__main__':
    unittest.main(verbosity=2)
