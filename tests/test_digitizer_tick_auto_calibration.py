import os
import sys
import unittest
from unittest.mock import patch

from PIL import Image, ImageDraw, ImageFont

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from WinUx.plotdigitizer.core.engine import DigitizerEngine
from WinUx.plotdigitizer.core.models import AxisScale
from WinUx.plotdigitizer.core.tick_detection import (
    AxisTickDetection, TickReading, detect_calibration_ticks, estimate_axis_value_at,
)
import WinUx.plotdigitizer.core.tick_detection as tick_detection


def _font(size=16):
    candidates = (
        r"C:\Windows\Fonts\arial.ttf",
        r"C:\Windows\Fonts\segoeui.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/liberation2/LiberationSans-Regular.ttf",
    )
    for path in candidates:
        if os.path.isfile(path):
            return ImageFont.truetype(path, size)
    return ImageFont.load_default()


def make_chart():
    image = Image.new("RGB", (680, 500), "white")
    draw = ImageDraw.Draw(image)
    font = _font()
    rect = (110, 60, 610, 390)
    left, top, right, bottom = rect
    x_values = (0.0, .8, 1.6, 2.4, 3.2)
    y_values = (0.0, 500.0, 1000.0, 1500.0, 2000.0)
    for index, value in enumerate(x_values):
        x = left + (right - left) * index / (len(x_values) - 1)
        draw.line((x, top, x, bottom), fill=(220, 220, 220), width=1)
        text = ("{:.6f}".format(value)).rstrip("0").rstrip(".")
        bbox = draw.textbbox((0, 0), text, font=font)
        width = bbox[2] - bbox[0]
        draw.text((x - width / 2, bottom + 7), text, font=font, fill=(100, 100, 100))
    for index, value in enumerate(y_values):
        y = bottom - (bottom - top) * index / (len(y_values) - 1)
        draw.line((left, y, right, y), fill=(220, 220, 220), width=1)
        text = str(int(value))
        bbox = draw.textbbox((0, 0), text, font=font)
        width, height = bbox[2] - bbox[0], bbox[3] - bbox[1]
        draw.text((left - width - 8, y - height / 2 - 2), text,
                  font=font, fill=(100, 100, 100))
    draw.rectangle(rect, outline=(80, 80, 80), width=1)
    return image, rect




def make_chart_with_close_y_title():
    image, rect = make_chart()
    draw = ImageDraw.Draw(image)
    font = _font()
    left, top, right, bottom = rect
    text = "Load (lb)"
    bbox = font.getbbox(text)
    title = Image.new("RGBA", (bbox[2] - bbox[0] + 10, bbox[3] - bbox[1] + 10),
                      (255, 255, 255, 0))
    title_draw = ImageDraw.Draw(title)
    title_draw.text((5 - bbox[0], 5 - bbox[1]), text, font=font, fill=(80, 80, 80, 255))
    title = title.rotate(90, expand=True)
    # Intentionally place the rotated title close enough to intersect several
    # Y-label scan rows.  The detector must not treat title glyphs as ticks.
    x = left - 40
    y = int((top + bottom - title.height) / 2)
    image.paste(title, (x, y), title)
    return image, rect


def make_chart_with_rotated_tick_labels(*, rotate_x=False, rotate_y=False):
    image = Image.new("RGB", (760, 560), "white")
    draw = ImageDraw.Draw(image)
    font = _font()
    rect = (170, 60, 670, 390)
    left, top, right, bottom = rect
    x_values = (0.0, .8, 1.6, 2.4, 3.2)
    y_values = (0.0, 500.0, 1000.0, 1500.0, 2000.0)

    def label_image(text, rotate):
        bbox = font.getbbox(text)
        label = Image.new("RGBA", (bbox[2] - bbox[0] + 8, bbox[3] - bbox[1] + 8),
                          (255, 255, 255, 0))
        ImageDraw.Draw(label).text((4 - bbox[0], 4 - bbox[1]), text,
                                   font=font, fill=(100, 100, 100, 255))
        return label.rotate(90, expand=True) if rotate else label

    for index, value in enumerate(x_values):
        x = left + (right - left) * index / (len(x_values) - 1)
        draw.line((x, top, x, bottom), fill=(220, 220, 220), width=1)
        text = ("{:.6f}".format(value)).rstrip("0").rstrip(".")
        label = label_image(text, rotate_x)
        image.paste(label, (int(x - label.width / 2), bottom + 7), label)
    for index, value in enumerate(y_values):
        y = bottom - (bottom - top) * index / (len(y_values) - 1)
        draw.line((left, y, right, y), fill=(220, 220, 220), width=1)
        label = label_image(str(int(value)), rotate_y)
        image.paste(label, (left - label.width - 8, int(y - label.height / 2)), label)
    draw.rectangle(rect, outline=(80, 80, 80), width=1)
    return image, rect

class CompleteTickLatticeTests(unittest.TestCase):
    def test_y_repaired_ocr_requires_independent_pixel_support(self):
        ticks = tuple(TickReading(float(p), float(v), text, .85, (1, 1, 5, 5))
                      for p, v, text in ((60, 2000, '2000'), (142, 1500, '1500'),
                                         (225, 1000, '1000'), (307, 500, '600'),
                                         (390, 0, '0')))
        detected = AxisTickDetection('y', ticks, .85, AxisScale.LINEAR)
        with patch.object(tick_detection, '_slot_oriented_masks',
                          return_value=[(0, [[1]], (1, 1, 5, 5))]), \
                patch.object(tick_detection, '_word_template_score', return_value=.20):
            result = tick_detection._verified_y_detection(
                None, (100, 60, 600, 390), detected, 82.5)
        self.assertEqual(5, len(result.ticks))
        with patch.object(tick_detection, '_slot_oriented_masks',
                          return_value=[(0, [[1]], (1, 1, 5, 5))]), \
                patch.object(tick_detection, '_word_template_score', return_value=.60):
            self.assertIsNone(tick_detection._verified_y_detection(
                None, (100, 60, 600, 390), detected, 82.5))

    def test_interpolates_missing_major_tick_without_claiming_ocr(self):
        ticks = tuple(TickReading(float(p), float(v), str(v), .91, (1, 1, 5, 5))
                      for p, v in ((60, 2000), (142, 1500), (307, 500), (390, 0)))
        detected = AxisTickDetection('y', ticks, .91, AxisScale.LINEAR)
        result = tick_detection._complete_lattice_ticks(
            detected, [60, 142, 225, 307, 390], (100, 60, 600, 390))
        self.assertEqual(5, len(result.ticks))
        inferred = min(result.ticks, key=lambda t: abs(t.position - 225))
        self.assertEqual(1000, inferred.value)
        self.assertEqual((0, 0, 0, 0), inferred.bbox)
        self.assertLess(inferred.confidence, .4)

    def test_unreliable_axis_does_not_invent_tick_values(self):
        ticks = tuple(TickReading(float(p), float(v), str(v), .91, (1, 1, 5, 5))
                      for p, v in ((60, 2), (142, 1500), (390, 0)))
        detected = AxisTickDetection('y', ticks, .92, AxisScale.LINEAR)
        result = tick_detection._complete_lattice_ticks(
            detected, [60, 142, 225, 307, 390], (100, 60, 600, 390))
        self.assertEqual(len(ticks), len(result.ticks))


class TickAutoCalibrationTests(unittest.TestCase):
    def test_small_resized_chart_keeps_multiple_ticks_on_both_axes(self):
        image, rect = make_chart()
        sx, sy = .9, .6
        image = image.resize((round(image.width * sx), round(image.height * sy)),
                             Image.Resampling.BICUBIC)
        rect = tuple(round(value * (sx if index % 2 == 0 else sy))
                     for index, value in enumerate(rect))
        result = detect_calibration_ticks(image, rect)
        self.assertTrue(result.ready)
        self.assertEqual([0, .8, 1.6, 2.4, 3.2],
                         [round(t.value, 6) for t in result.x.ticks])
        self.assertEqual([2000, 1500, 1000, 500, 0],
                         [round(t.value) for t in result.y.ticks])

    def test_y_axis_visual_consistency_with_close_title(self):
        # A high count of pseudo-digit fragments from the rotated Y title
        # must not beat the real five-label Y series.
        image, rect = make_chart_with_close_y_title()
        detection = detect_calibration_ticks(image, rect)
        self.assertTrue(detection.y.ready)
        self.assertAlmostEqual(0, estimate_axis_value_at(detection.y, rect[3]), delta=20)
        self.assertAlmostEqual(2000, estimate_axis_value_at(detection.y, rect[1]), delta=20)

    def test_detects_tick_positions_and_values_without_external_ocr(self):
        image, rect = make_chart()
        result = detect_calibration_ticks(image, rect, AxisScale.LINEAR, AxisScale.LINEAR)
        self.assertTrue(result.ready)
        self.assertEqual(5, len(result.x.ticks))
        self.assertEqual(5, len(result.y.ticks))
        self.assertAlmostEqual(0.0, result.x.ticks[0].value, places=6)
        self.assertAlmostEqual(3.2, result.x.ticks[-1].value, places=6)
        self.assertAlmostEqual(2000.0, result.y.ticks[0].value, places=6)
        self.assertAlmostEqual(0.0, result.y.ticks[-1].value, places=6)
        self.assertAlmostEqual(rect[0], result.x.ticks[0].position, delta=2)
        self.assertAlmostEqual(rect[2], result.x.ticks[-1].position, delta=2)
        self.assertAlmostEqual(rect[1], result.y.ticks[0].position, delta=2)
        self.assertAlmostEqual(rect[3], result.y.ticks[-1].position, delta=2)

    def test_box_auto_applies_detected_tick_calibration(self):
        image, rect = make_chart()
        engine = DigitizerEngine()
        engine.image = image
        detection = engine.set_plot_rect_with_corner_anchors(rect)
        self.assertTrue(detection.ready)
        self.assertTrue(engine.calibration.ready())
        self.assertGreaterEqual(len(engine.calibration.points_x), 3)
        self.assertGreaterEqual(len(engine.calibration.points_y), 3)
        self.assertAlmostEqual(0.0, engine.calibration.x1.value, places=6)
        self.assertAlmostEqual(3.2, engine.calibration.x2.value, places=6)
        self.assertAlmostEqual(0.0, engine.calibration.y1.value, places=6)
        self.assertAlmostEqual(2000.0, engine.calibration.y2.value, places=6)
        x, y = engine.pixel_to_data(rect[2], rect[1])
        self.assertAlmostEqual(3.2, x, delta=.03)
        self.assertAlmostEqual(2000.0, y, delta=8)

    def test_manual_values_replace_fit_and_undo_restores_all_points(self):
        image, rect = make_chart()
        engine = DigitizerEngine()
        engine.image = image
        engine.set_plot_rect_with_corner_anchors(rect)
        previous = engine.calibration.to_dict()
        engine.set_anchor_values({'x1': 0, 'x2': 4, 'y1': 0, 'y2': 2500})
        self.assertEqual([], engine.calibration.points_x)
        self.assertEqual([], engine.calibration.points_y)
        engine.undo()
        self.assertEqual(previous, engine.calibration.to_dict())


    def test_y_axis_title_noise_does_not_skew_y_edge_calibration(self):
        image, rect = make_chart_with_close_y_title()
        result = detect_calibration_ticks(image, rect, AxisScale.LINEAR, AxisScale.LINEAR)
        self.assertTrue(result.y.ready)
        self.assertGreaterEqual(len(result.y.ticks), 4)
        engine = DigitizerEngine()
        engine.image = image
        detection = engine.set_plot_rect_with_corner_anchors(rect)
        self.assertTrue(detection.y.ready)
        self.assertAlmostEqual(0.0, engine.calibration.y1.value, places=6)
        self.assertAlmostEqual(2000.0, engine.calibration.y2.value, places=6)
        # Pseudo-label rows from the rotated title must not survive as extra
        # calibration ticks between the real 500-unit lattice positions.
        values = sorted(round(tick.value) for tick in detection.y.ticks)
        self.assertEqual(len(values), len(set(values)))
        self.assertTrue(set(values).issubset({0, 500, 1000, 1500, 2000}))

    def test_vertical_y_tick_text_is_supported(self):
        image, rect = make_chart_with_rotated_tick_labels(rotate_y=True)
        result = detect_calibration_ticks(image, rect, AxisScale.LINEAR, AxisScale.LINEAR)
        self.assertTrue(result.y.ready)
        self.assertAlmostEqual(2000.0, result.y.ticks[0].value, places=6)
        self.assertAlmostEqual(0.0, result.y.ticks[-1].value, places=6)
        engine = DigitizerEngine()
        engine.image = image
        engine.set_plot_rect_with_corner_anchors(rect)
        self.assertAlmostEqual(0.0, engine.calibration.y1.value, places=6)
        self.assertAlmostEqual(2000.0, engine.calibration.y2.value, places=6)

    def test_vertical_x_and_y_tick_text_are_supported(self):
        image, rect = make_chart_with_rotated_tick_labels(rotate_x=True, rotate_y=True)
        result = detect_calibration_ticks(image, rect, AxisScale.LINEAR, AxisScale.LINEAR)
        self.assertTrue(result.ready)
        self.assertAlmostEqual(0.0, result.x.ticks[0].value, places=6)
        self.assertAlmostEqual(3.2, result.x.ticks[-1].value, places=6)
        self.assertAlmostEqual(2000.0, result.y.ticks[0].value, places=6)
        self.assertAlmostEqual(0.0, result.y.ticks[-1].value, places=6)

    def test_y_verified_sequence_beats_overconfident_glyph_ocr(self):
        image, rect = make_chart()
        positions = (rect[1], rect[1] + 82.5, rect[1] + 165.0,
                     rect[1] + 247.5, rect[3])
        bogus = AxisTickDetection(
            "y",
            tuple(TickReading(float(pos), float(value), str(value), .95, (0, 0, 1, 1))
                  for pos, value in zip(positions, (0, 1400, 2800, 4200, 5600))),
            .94, AxisScale.LINEAR)
        verified = AxisTickDetection(
            "y",
            tuple(TickReading(float(pos), float(value), str(value), .72, (0, 0, 1, 1))
                  for pos, value in zip(positions, (2000, 1500, 1000, 500, 0))),
            .64, AxisScale.LINEAR)
        with patch.object(tick_detection, "_build_axis_detection", return_value=bogus), \
                patch.object(tick_detection, "_zero_anchored_template_detection",
                             return_value=verified):
            result = tick_detection._detect_axis(
                image, rect, "y", AxisScale.LINEAR)
        self.assertNotEqual(bogus, result)
        self.assertTrue(not result.ready or result.ticks[0].value == 2000.0)

    def test_conflicting_interior_ocr_is_not_accepted_as_calibration(self):
        detection = AxisTickDetection(
            "y",
            (TickReading(100.0, 2000.0, "2000", .8, (0, 0, 1, 1)),
             TickReading(200.0, 1500.0, "1500", .8, (0, 0, 1, 1)),
             # Deliberately bad interior OCR value that would skew a free fit.
             TickReading(300.0, 9000.0, "9000", .8, (0, 0, 1, 1)),
             TickReading(400.0, 0.0, "0", .8, (0, 0, 1, 1))),
            .9, AxisScale.LINEAR)
        self.assertFalse(detection.ready)
        with self.assertRaises(ValueError):
            estimate_axis_value_at(detection, 397.0)

    def test_nonzero_y_axis_must_not_be_forced_to_zero(self):
        """A conventional 10..50 axis must not become a fake 0..80 axis."""
        image = Image.new("RGB", (720, 540), "white")
        draw = ImageDraw.Draw(image)
        font = _font()
        rect = (150, 70, 650, 420)
        left, top, right, bottom = rect
        for index, value in enumerate((10, 20, 30, 40, 50)):
            y = bottom - (bottom - top) * index / 4
            draw.line((left, y, right, y), fill=(215, 215, 215))
            label = str(value)
            bounds = draw.textbbox((0, 0), label, font=font)
            draw.text((left - (bounds[2] - bounds[0]) - 8, y - 8),
                      label, font=font, fill=(90, 90, 90))
        for index in range(5):
            x = left + (right - left) * index / 4
            draw.line((x, top, x, bottom), fill=(215, 215, 215))
            draw.text((x - 5, bottom + 7), str(index), font=font,
                      fill=(90, 90, 90))
        draw.rectangle(rect, outline=(80, 80, 80))
        detection = detect_calibration_ticks(image, rect)
        self.assertTrue(detection.y.ready)
        self.assertAlmostEqual(50, estimate_axis_value_at(detection.y, top), delta=1)
        self.assertAlmostEqual(10, estimate_axis_value_at(detection.y, bottom), delta=1)

    def test_blank_box_preserves_existing_corner_seed_fallback(self):
        engine = DigitizerEngine()
        engine.image = Image.new("RGB", (400, 300), "white")
        detection = engine.set_plot_rect_with_corner_anchors((40, 30, 340, 250))
        self.assertFalse(detection.ready)
        self.assertEqual(0.0, engine.calibration.x1.value)
        self.assertEqual(1.0, engine.calibration.x2.value)
        self.assertEqual(0.0, engine.calibration.y1.value)
        self.assertEqual(1.0, engine.calibration.y2.value)
        self.assertEqual(40.0, engine.calibration.x1.px)
        self.assertEqual(340.0, engine.calibration.x2.px)
        self.assertEqual(250.0, engine.calibration.y1.py)
        self.assertEqual(30.0, engine.calibration.y2.py)


if __name__ == "__main__":
    unittest.main()

# Regression: well-read nonzero Y labels must not invoke the expensive,
# potentially misleading zero-anchored exhaustive sequence search.
def test_nonzero_y_skips_zero_origin_hypothesis_when_pixels_agree():
    from unittest.mock import patch
    from WinUx.plotdigitizer.core import tick_detection as td
    from PIL import Image, ImageDraw
    image = Image.new('RGB', (720, 540), 'white')
    draw = ImageDraw.Draw(image)
    font = _font()
    rect = (150, 70, 650, 420)
    for i, value in enumerate((10, 20, 30, 40, 50)):
        y = 420 - 350 * i / 4
        draw.line((150, y, 650, y), fill=(215, 215, 215))
        bbox = draw.textbbox((0, 0), str(value), font=font)
        draw.text((150 - (bbox[2] - bbox[0]) - 8, y - 8), str(value), font=font, fill=(90, 90, 90))
    draw.rectangle(rect, outline=(80, 80, 80))
    with patch.object(td, '_zero_anchored_template_detection', side_effect=AssertionError('slow fallback called')):
        result = td._detect_axis(image, rect, 'y', AxisScale.LINEAR)
    assert result.ready
    assert abs(td.estimate_axis_value_at(result, 70) - 50) < 1

class FastRealLabelPassTests(unittest.TestCase):
    def test_y_direct_labels_avoid_expensive_template_fallback(self):
        image, rect = make_chart_with_close_y_title()
        with patch.object(tick_detection, '_zero_anchored_template_detection',
                          side_effect=AssertionError('unexpected exhaustive fallback')):
            result = tick_detection._detect_axis(image, rect, 'y', AxisScale.LINEAR)
        self.assertTrue(result.ready)
        # This fixture paints the title over the middle label. Independent OCR
        # may reject that obscured word; it must not repair it from the series.
        expected = {60: 2000, 142: 1500, 225: 1000, 307: 500, 390: 0}
        for tick in result.ticks:
            self.assertEqual(expected[tick.position], tick.value)
        self.assertEqual(set(expected), {t.position for t in result.ticks} | set(result.unread_positions))
        self.assertGreaterEqual(len(result.ticks), 4)
