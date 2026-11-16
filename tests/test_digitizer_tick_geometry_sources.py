import os
import unittest

from PIL import Image, ImageDraw, ImageFont

from WinUx.plotdigitizer.core import tick_detection as td
from WinUx.plotdigitizer.core.models import AxisScale


def _font(size=16):
    for path in (
        r"C:\Windows\Fonts\arial.ttf",
        r"C:\Windows\Fonts\segoeui.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/liberation2/LiberationSans-Regular.ttf",
    ):
        if os.path.isfile(path):
            return ImageFont.truetype(path, size)
    return ImageFont.load_default()


def _gridless_chart(*, tick_marks):
    image = Image.new("RGB", (800, 520), "white")
    draw = ImageDraw.Draw(image)
    font = _font()
    rect = (120, 60, 700, 420)
    left, top, right, bottom = rect
    x_values = (0, 1, 2, 3, 4, 5)
    y_values = (0, 20, 40, 60, 80, 100)

    for index, value in enumerate(x_values):
        x = left + (right - left) * index / (len(x_values) - 1)
        if tick_marks:
            draw.line((x, bottom, x, bottom + 5), fill=(70, 70, 70), width=1)
        text = str(value)
        box = draw.textbbox((0, 0), text, font=font)
        draw.text((x - (box[2] - box[0]) / 2, bottom + 8), text,
                  font=font, fill=(80, 80, 80))

    for index, value in enumerate(y_values):
        y = bottom - (bottom - top) * index / (len(y_values) - 1)
        if tick_marks:
            draw.line((left - 5, y, left, y), fill=(70, 70, 70), width=1)
        text = str(value)
        box = draw.textbbox((0, 0), text, font=font)
        draw.text((left - (box[2] - box[0]) - 9,
                   y - (box[3] - box[1]) / 2 - 2), text,
                  font=font, fill=(80, 80, 80))

    draw.line((left, top, left, bottom), fill=(60, 60, 60), width=1)
    draw.line((left, bottom, right, bottom), fill=(60, 60, 60), width=1)
    return image, rect, x_values, y_values


def _minor_tick_chart(*, logarithmic_y=False):
    image = Image.new("RGB", (760, 520), "white")
    draw = ImageDraw.Draw(image)
    font = _font()
    rect = (120, 60, 650, 420)
    left, top, right, bottom = rect

    for index in range(11):
        x = left + (right - left) * index / 10
        major = index % 2 == 0
        draw.line((x, bottom, x, bottom + (5 if major else 3)),
                  fill=(70, 70, 70), width=1)
        if major:
            text = str(index // 2)
            box = draw.textbbox((0, 0), text, font=font)
            draw.text((x - (box[2] - box[0]) / 2, bottom + 8), text,
                      font=font, fill=(80, 80, 80))

    if logarithmic_y:
        import math
        for decade in range(3):
            for mantissa in range(1, 10):
                value = mantissa * (10 ** decade)
                y = bottom - math.log10(value) / 3 * (bottom - top)
                major = mantissa == 1
                draw.line((left - (6 if major else 3), y, left, y),
                          fill=(70, 70, 70), width=1)
                if major:
                    text = str(value)
                    box = draw.textbbox((0, 0), text, font=font)
                    draw.text((left - (box[2] - box[0]) - 9,
                               y - (box[3] - box[1]) / 2 - 2), text,
                              font=font, fill=(80, 80, 80))
        text = "1000"
        box = draw.textbbox((0, 0), text, font=font)
        draw.line((left - 6, top, left, top), fill=(70, 70, 70), width=1)
        draw.text((left - (box[2] - box[0]) - 9,
                   top - (box[3] - box[1]) / 2 - 2), text,
                  font=font, fill=(80, 80, 80))
    else:
        for index in range(11):
            y = bottom - (bottom - top) * index / 10
            major = index % 2 == 0
            draw.line((left - (5 if major else 3), y, left, y),
                      fill=(70, 70, 70), width=1)
            if major:
                text = str(index * 10)
                box = draw.textbbox((0, 0), text, font=font)
                draw.text((left - (box[2] - box[0]) - 9,
                           y - (box[3] - box[1]) / 2 - 2), text,
                          font=font, fill=(80, 80, 80))

    draw.line((left, top, left, bottom), fill=(60, 60, 60), width=1)
    draw.line((left, bottom, right, bottom), fill=(60, 60, 60), width=1)
    return image, rect


class TickGeometrySourceTests(unittest.TestCase):
    def test_short_axis_ticks_calibrate_without_grid_lines(self):
        image, rect, x_values, y_values = _gridless_chart(tick_marks=True)
        y_marks = td._axis_edge_tick_candidates(image, rect, 'y')
        self.assertEqual(len(y_values), len(y_marks))

        result = td.detect_calibration_ticks(image, rect)
        self.assertTrue(result.x.ready, result.x)
        self.assertTrue(result.y.ready, result.y)
        self.assertEqual(AxisScale.LINEAR, result.x.scale)
        self.assertEqual(AxisScale.LINEAR, result.y.scale)
        self.assertEqual(list(x_values), [round(tick.value) for tick in result.x.ticks])
        self.assertEqual(list(reversed(y_values)), [round(tick.value) for tick in result.y.ticks])

    def test_label_geometry_calibrates_y_without_grid_or_tick_marks(self):
        image, rect, x_values, y_values = _gridless_chart(tick_marks=False)
        # The bottom border is the only edge-stroke candidate; the remaining Y
        # geometry must therefore come from the observed label column itself.
        self.assertLess(len(td._axis_edge_tick_candidates(image, rect, 'y')), 3)
        label_positions, _words = td._label_driven_words(image, rect, 'y')
        self.assertEqual(len(y_values), len(label_positions))

        result = td.detect_calibration_ticks(image, rect)
        self.assertTrue(result.x.ready, result.x)
        self.assertTrue(result.y.ready, result.y)
        self.assertEqual(list(x_values), [round(tick.value) for tick in result.x.ticks])
        self.assertEqual(list(reversed(y_values)), [round(tick.value) for tick in result.y.ticks])

    def test_label_backed_irregular_mark_is_protected_from_lattice_pruning(self):
        candidates = [(0, 6), (100, 6), (200, 6), (250, 6), (300, 6), (400, 6)]
        pruned = td._coherent_major_mark_subset(candidates)
        self.assertNotIn((250.0, 6.0), pruned)
        protected = td._coherent_major_mark_subset(candidates, protected_positions=(250,))
        self.assertIn((250.0, 6.0), protected)
        self.assertEqual(len(candidates), len(protected))

    def test_curve_crossing_axis_is_not_promoted_to_extra_major_tick(self):
        image, rect, _x_values, y_values = _gridless_chart(tick_marks=True)
        draw = ImageDraw.Draw(image)
        left, _top, _right, _bottom = rect
        # A neutral curve enters the Y spine between the 40 and 20 ticks.
        # Edge geometry alone sees it as a short perpendicular stroke.
        draw.line((left, 293, left + 80, 305), fill=(50, 50, 50), width=3)
        raw = td._axis_edge_tick_candidates(image, rect, 'y')
        self.assertGreater(len(raw), len(y_values))
        coherent = td._coherent_major_mark_subset(td._major_axis_edge_subset(raw))
        self.assertEqual(len(y_values), len(coherent))

        result = td.detect_calibration_ticks(image, rect)
        self.assertTrue(result.y.ready, result.y)
        self.assertEqual(len(y_values), len(result.y.mark_positions))
        self.assertEqual(list(reversed(y_values)),
                         [round(tick.value) for tick in result.y.ticks])

    def test_minor_tick_lengths_do_not_override_major_linear_lattice(self):
        image, rect = _minor_tick_chart(logarithmic_y=False)
        raw = td._axis_edge_tick_candidates(image, rect, 'y')
        major = td._major_axis_edge_subset(raw)
        self.assertGreater(len(raw), len(major))
        self.assertEqual(6, len(major))

        result = td.detect_calibration_ticks(image, rect)
        self.assertTrue(result.y.ready, result.y)
        self.assertEqual(AxisScale.LINEAR, result.y.scale)
        self.assertEqual([100, 80, 60, 40, 20, 0],
                         [round(tick.value) for tick in result.y.ticks])

    def test_log_minor_ticks_keep_decade_labels_as_calibration_lattice(self):
        image, rect = _minor_tick_chart(logarithmic_y=True)
        raw = td._axis_edge_tick_candidates(image, rect, 'y')
        major = td._major_axis_edge_subset(raw)
        self.assertGreater(len(raw), len(major))
        self.assertEqual(4, len(major))

        result = td.detect_calibration_ticks(image, rect)
        self.assertTrue(result.y.ready, result.y)
        self.assertEqual(AxisScale.LOG10, result.y.scale)
        self.assertEqual([1000, 100, 10, 1],
                         [round(tick.value) for tick in result.y.ticks])


if __name__ == '__main__':
    unittest.main()
