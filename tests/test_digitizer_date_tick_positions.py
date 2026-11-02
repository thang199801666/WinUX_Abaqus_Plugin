"""Tick geometry must come from strokes, not the centre of rotated OCR text."""
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import run_winux
run_winux._configure_bundled_dependencies(str(ROOT))
from PIL import Image, ImageDraw
from WinUx.plotdigitizer.core import tick_detection as td
from WinUx.plotdigitizer.core.engine import DigitizerEngine


class DateTickPositionTests(unittest.TestCase):
    def setUp(self):
        self.path = Path(__file__).parent / 'fixtures' / 'plotdigitizer' / 'faint_rotated_date_ticks.png'
        with Image.open(self.path) as source:
            self.image = source.convert('RGB')
        self.rect = (94, 30, 719, 480)
        self.positions = (93, 167, 240.5, 314, 388, 461, 498, 572, 645, 719)
        self.dates = ('2020-01-21', '2020-01-23', '2020-01-25', '2020-01-27',
                      '2020-01-29', '2020-01-31', '2020-02-01', '2020-02-03',
                      '2020-02-05', '2020-02-07')

    def test_faint_marks_are_recovered_at_the_physical_edge(self):
        marks = td._axis_edge_tick_candidates(self.image, self.rect, 'x')
        self.assertEqual(len(self.positions), len(marks))
        for (position, _strength), expected in zip(marks, self.positions):
            self.assertAlmostEqual(expected, position, delta=1)

    def test_real_dates_and_engine_points_follow_marks_not_text_centres(self):
        result = td.detect_calibration_ticks(self.image, self.rect)
        self.assertTrue(result.x.ready, result.x)
        self.assertEqual(list(self.dates), [tick.text for tick in result.x.ticks])
        for tick, expected in zip(result.x.ticks, self.positions):
            self.assertAlmostEqual(expected, tick.position, delta=1)
            self.assertNotEqual((0, 0, 0, 0), tick.bbox)
        second = result.x.ticks[1]
        self.assertGreater(abs(second.position - (second.bbox[0] + second.bbox[2]) / 2), 15)
        self.assertEqual(37, result.x.ticks[6].position - result.x.ticks[5].position)
        engine = DigitizerEngine()
        engine.apply_image(self.image, str(self.path))
        engine.set_plot_rect_with_corner_anchors(self.rect, detect_ticks=False)
        self.assertTrue(engine.apply_tick_calibration_detection(result, expected_rect=self.rect))
        self.assertEqual(list(self.positions), [point.px for point in engine.calibration_points('x')])
        self.assertEqual([tick.value for tick in result.x.ticks],
                         [point.value for point in engine.calibration_points('x')])

    def test_tiny_neutral_ticks_need_an_actual_spine_for_faint_retry(self):
        rect = (30, 20, 230, 100)
        positions = (30, 90, 150, 180, 230)
        image = Image.new('RGB', (260, 150), 'white')
        draw = ImageDraw.Draw(image)
        for x in positions:
            draw.line((x, 100, x, 106), fill=(244, 244, 244))
        self.assertEqual([], td._axis_edge_tick_candidates(image, rect, 'x', _faint=True))
        draw.line((30, 100, 230, 100), fill=(239, 239, 239))
        self.assertEqual(list(positions), [p for p, _ in td._axis_edge_tick_candidates(image, rect, 'x')])

    def test_small_region_offsets_keep_the_same_dates_and_stroke_positions(self):
        for rect in ((92, 29, 720, 479), (96, 32, 717, 481)):
            with self.subTest(rect=rect):
                result = td.detect_calibration_ticks(self.image, rect).x
                self.assertTrue(result.ready)
                self.assertEqual(list(self.dates), [tick.text for tick in result.ticks])
                for tick, expected in zip(result.ticks, self.positions):
                    self.assertAlmostEqual(expected, tick.position, delta=1)

    def test_end_alignment_is_shared_and_does_not_regularize_irregular_marks(self):
        positions = (90., 180., 270., 315., 405.)
        labels = [(position - 20.5, [bytearray([1] * 50) for _ in range(50)],
                   (int(position - 45), 120, int(position + 4), 169)) for position in positions]
        with patch.object(td, '_x_label_masks', return_value=labels), \
                patch.object(td, '_label_deskew_angle', return_value=-45):
            actual, words = td._label_driven_words(Image.new('RGB', (500, 200)),
                                                  (90, 20, 405, 100), 'x', positions)
        self.assertEqual(positions, actual)
        self.assertEqual(set(positions), set(words))

    def test_overlapping_group_box_does_not_take_its_neighbours_first_pixel(self):
        mask = [bytearray(9) for _ in range(9)]
        for y in range(6):
            mask[y][1] = 1
        mask[1][2] = 1
        for y in range(1, 6):
            mask[y][3] = 1
        for y in range(1, 8):
            mask[y][7] = 1
        for x in range(3, 8):
            mask[7][x] = 1
        result = td._isolated_word_group(mask, td._mask_image(mask), (3, 1, 7, 7), 11)
        self.assertEqual(11, sum(map(sum, result)))
        self.assertEqual(0, result[0][0])
        self.assertEqual(1, result[0][-1])
        self.assertEqual(bytearray([1] * 5), result[-1])


if __name__ == '__main__':
    unittest.main()
