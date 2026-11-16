"""Regression for short tick marks and large, detached rotated year glyphs."""
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import run_winux
run_winux._configure_bundled_dependencies(str(ROOT))
from PIL import Image
from WinUx.plotdigitizer.core import tick_detection as td
from WinUx.plotdigitizer.core.engine import DigitizerEngine


class MusicSalesAxisTests(unittest.TestCase):
    def setUp(self):
        self.path = Path(__file__).parent / 'fixtures' / 'plotdigitizer' / 'music_sales_rotated_years.png'
        with Image.open(self.path) as source:
            self.image = source.convert('RGB')
        self.rect = (110, 174, 697, 567)

    def test_y_labels_are_not_replaced_by_horizontal_tick_fragments(self):
        _positions, words = td._label_driven_words(self.image, self.rect, 'y')
        self.assertEqual(7, len(words))
        self.assertTrue(all(len(mask) >= 20 for mask, _bbox in words.values()))
        ten = min(words, key=lambda position: abs(position - 501))
        mask, bbox = words[ten]
        self.assertLess(bbox[0], 50)  # Include the detached leading 1 in 10.
        self.assertEqual(10, td._read_probe_word(mask)[1])

    def test_rotated_words_include_detached_digits_but_not_neighbour_ink(self):
        positions = [p for p, _score in td._axis_edge_tick_candidates(self.image, self.rect, 'x')]
        words = td._physical_tick_words(self.image, self.rect, 'x', positions)
        for position, year in zip(positions, range(2011, 2019)):
            with self.subTest(year=year):
                mask, _bbox = words[position]
                upright = td._rotate_mask(mask, -45)
                reading = td._read_probe_word(upright)
                self.assertIsNotNone(reading)
                self.assertEqual(year, reading[1])

    def test_real_image_calibrates_both_axes_at_observed_tick_positions(self):
        for rect in (self.rect, (112, 172, 695, 568)):
            with self.subTest(rect=rect):
                detection = td.detect_calibration_ticks(self.image, rect)
                self.assertTrue(detection.ready, detection)
                measured_x = [tick for tick in detection.x.ticks if tick.bbox != (0, 0, 0, 0)]
                self.assertEqual(list(range(2011, 2019)), [tick.value for tick in measured_x])
                for tick, expected in zip(measured_x, (110, 183, 256, 330, 403.5, 477, 550, 624)):
                    self.assertAlmostEqual(expected, tick.position, delta=1)
                self.assertEqual([60, 50, 40, 30, 20, 10, 0],
                                 [tick.value for tick in detection.y.ticks])

                engine = DigitizerEngine()
                engine.apply_image(self.image, str(self.path))
                engine.set_plot_rect_with_corner_anchors(rect, detect_ticks=False)
                self.assertTrue(engine.apply_tick_calibration_detection(detection, expected_rect=rect))
                self.assertTrue(engine.calibration_ready)
                self.assertEqual(list(range(2011, 2019)),
                                 [point.value for point in engine.calibration_points('x')])
                self.assertEqual(7, len(engine.calibration_points('y')))


if __name__ == '__main__':
    unittest.main()
