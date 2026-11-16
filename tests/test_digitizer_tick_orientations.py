"""Focused tick OCR regressions: shifted labels, arbitrary angles and safety."""
import os
import sys
import time
import unittest
from unittest.mock import patch

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, 'vendor'))
from PIL import Image, ImageDraw
from test_digitizer_tick_auto_calibration import _font, make_chart
from WinUx.plotdigitizer.core import tick_detection as td


def make_oriented_chart(angle_x=0, angle_y=0, *, shifted=False, nonzero=False, jitter=False,
                        x_values=None, y_values=None):
    image = Image.new('RGB', (1080, 900), 'white')
    draw = ImageDraw.Draw(image)
    rect = (250, 150, 970, 710)
    font = _font(17)
    xs = list(x_values) if x_values is not None else [i * .08 for i in range(9)]
    ys = list(y_values) if y_values is not None else [10000 + i * 1000 if nonzero else i * 8000 for i in range(len(xs))]

    def label(text, angle):
        bounds = font.getbbox(text)
        tile = Image.new('RGBA', (bounds[2] - bounds[0] + 8, bounds[3] - bounds[1] + 8))
        ImageDraw.Draw(tile).text((4 - bounds[0], 4 - bounds[1]), text,
                                 font=font, fill=(85, 85, 85, 255))
        return tile.rotate(angle, resample=Image.Resampling.BICUBIC, expand=True)

    for index in range(len(xs)):
        x = rect[0] + index * (rect[2] - rect[0]) / (len(xs) - 1)
        y = rect[3] - index * (rect[3] - rect[1]) / (len(ys) - 1)
        draw.line((x, rect[1], x, rect[3]), fill=(220, 220, 220))
        draw.line((rect[0], y, rect[2], y), fill=(220, 220, 220))
        delta = (index % 3 - 1) * 2 if jitter else 0
        x_label = label('{:g}'.format(xs[index]), angle_x + delta)
        y_label = label(str(ys[index]), angle_y - delta)
        dx = 10 if shifted else 0
        dy = (index % 3 - 1) * 5 if shifted else 0
        image.paste(x_label, (round(x - x_label.width / 2 + dx), rect[3] + 7), x_label)
        image.paste(y_label, (rect[0] - y_label.width - 8, round(y - y_label.height / 2 + dy)), y_label)
    draw.rectangle(rect, outline=(80, 80, 80))
    draw.text((470, 70), 'Load versus displacement', fill=(70, 70, 70), font=font)
    title = label('Load (lb)', 90)
    image.paste(title, (75, 400), title)
    draw.text((480, 835), 'Displacement (in)', fill=(70, 70, 70), font=font)
    return image, rect, xs, ys


class TickOrientationTests(unittest.TestCase):
    def check_chart(self, ax, ay, *, scale=td.AxisScale.LINEAR, **options):
        image, rect, xs, ys = make_oriented_chart(ax, ay, **options)
        start = time.perf_counter()
        detected = td.detect_calibration_ticks(image, rect, scale, scale)
        print('\nangles X={} Y={} {}: {:.3f}s'.format(ax, ay, options, time.perf_counter() - start))
        for reading, expected in ((detected.x, xs), (detected.y, list(reversed(ys)))):
            self.assertTrue(reading.ready, reading)
            self.assertEqual(len(expected), len(reading.ticks))
            self.assertGreaterEqual(sum(t.bbox != (0, 0, 0, 0) for t in reading.ticks), 3)
            for tick, value in zip(reading.ticks, expected):
                self.assertAlmostEqual(value, tick.value, delta=max(.0001, abs(value) * .001))
        # An enlarged local retry can locate a stroke at a half source pixel.
        # Mapping must hit the observed tick, not invent/snap a value at Box edges.
        self.assertAlmostEqual(xs[0], td.estimate_axis_value_at(detected.x, detected.x.ticks[0].position), delta=.0001)
        self.assertAlmostEqual(ys[0], td.estimate_axis_value_at(detected.y, detected.y.ticks[-1].position), delta=1)

    def test_shifted_horizontal_labels(self):
        self.check_chart(0, 0, shifted=True)

    def test_oblique_labels_in_both_directions(self):
        for angle in (-60, -35, -15, 15, 35, 60):
            with self.subTest(angle=angle):
                self.check_chart(angle, -angle)

    def test_vertical_and_upside_down_labels(self):
        for ax, ay in ((90, -90), (-90, 90), (180, 180)):
            with self.subTest(x=ax, y=ay):
                self.check_chart(ax, ay)

    def test_small_and_near_vertical_angles(self):
        for angle in (-8, 5, 75, 88):
            with self.subTest(angle=angle):
                self.check_chart(angle, -angle)

    def test_independent_angles_with_shift_and_small_label_jitter(self):
        self.check_chart(32, -22, shifted=True, jitter=True)

    def test_nonzero_axis_is_not_forced_to_zero_after_deskew(self):
        self.check_chart(-28, 42, nonzero=True)

    def test_rotated_logarithmic_values(self):
        self.check_chart(24, -37, scale=td.AxisScale.LOG10,
                         x_values=(1, 10, 100, 1000, 10000), y_values=(1, 10, 100, 1000, 10000))

    def test_negative_values_and_decimal_signs_survive_deskew(self):
        self.check_chart(-25, 30, x_values=[(i - 4) * .08 for i in range(9)],
                         y_values=[(i - 4) * 8000 for i in range(9)])

    def test_repeated_rotated_text_does_not_invent_a_numeric_scale(self):
        image, rect, _, _ = make_oriented_chart()
        draw = ImageDraw.Draw(image)
        draw.rectangle((0, 100, rect[0] - 2, 760), fill='white')
        draw.rectangle((200, rect[3] + 2, 1050, 899), fill='white')
        for index in range(9):
            tile = Image.new('RGBA', (62, 26))
            ImageDraw.Draw(tile).text((4, 2), '0.08', fill=(85, 85, 85, 255), font=_font(17))
            tile = tile.rotate(35, expand=True, resample=Image.Resampling.BICUBIC)
            x = rect[0] + index * (rect[2] - rect[0]) / 8
            y = rect[3] - index * (rect[3] - rect[1]) / 8
            image.paste(tile, (round(x - tile.width / 2), rect[3] + 7), tile)
            image.paste(tile, (rect[0] - tile.width - 8, round(y - tile.height / 2)), tile)
        result = td.detect_calibration_ticks(image, rect)
        self.assertFalse(result.x.ready, result.x)
        self.assertFalse(result.y.ready, result.y)

    def test_readable_horizontal_axis_does_not_run_deskew_ocr(self):
        image, rect = make_chart()
        with patch.object(td, '_detect_transformed_axis', side_effect=AssertionError('unnecessary deskew OCR')):
            self.assertTrue(td._detect_axis(image, rect, 'y', td.AxisScale.LINEAR).ready)


if __name__ == '__main__':
    unittest.main()
