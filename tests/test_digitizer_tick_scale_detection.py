import math
import os
import sys
import unittest
from datetime import date, timedelta, timezone

from PIL import Image, ImageDraw, ImageFont

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from WinUx.plotdigitizer.core import tick_detection as td
from WinUx.plotdigitizer.core.engine import DigitizerEngine
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


def _ticks(values):
    return tuple(td.TickReading(float(index * 100), float(value), str(value), .91, (1, 1, 8, 8))
                 for index, value in enumerate(values))


def _log_chart(missing_x_index=None):
    image = Image.new("RGB", (760, 500), "white")
    draw = ImageDraw.Draw(image)
    font = _font()
    rect = (120, 60, 650, 390)
    left, top, right, bottom = rect
    x_values = (.1, 1, 10, 100, 1000)
    y_values = (0, 500, 1000, 1500, 2000)
    for index, value in enumerate(x_values):
        x = left + (right - left) * index / (len(x_values) - 1)
        draw.line((x, top, x, bottom), fill=(220, 220, 220), width=1)
        text = "0.1" if value == .1 else str(int(value))
        box = draw.textbbox((0, 0), text, font=font)
        if index != missing_x_index:
            draw.text((x - (box[2] - box[0]) / 2, bottom + 7), text,
                      font=font, fill=(100, 100, 100))
    for index, value in enumerate(y_values):
        y = bottom - (bottom - top) * index / (len(y_values) - 1)
        draw.line((left, y, right, y), fill=(220, 220, 220), width=1)
        text = str(value)
        box = draw.textbbox((0, 0), text, font=font)
        draw.text((left - (box[2] - box[0]) - 8, y - (box[3] - box[1]) / 2 - 2),
                  text, font=font, fill=(100, 100, 100))
    draw.rectangle(rect, outline=(80, 80, 80), width=1)
    return image, rect



def _year_comma_log_chart():
    image = Image.new("RGB", (900, 560), "white")
    draw = ImageDraw.Draw(image)
    font = _font()
    rect = (150, 70, 800, 450)
    left, top, right, bottom = rect
    years = (1981, 1985, 1989, 1993, 1997, 2001, 2005, 2009)
    # Deliberately omit vertical grid lines. Geometry must come from the
    # coherent year-label row rather than from X line peaks.
    for index, value in enumerate(years):
        x = left + (right - left) * index / (len(years) - 1)
        text = str(value)
        box = draw.textbbox((0, 0), text, font=font)
        draw.text((x - (box[2] - box[0]) / 2, bottom + 8), text,
                  font=font, fill=(90, 90, 90))
    y_values = tuple(10 ** exponent for exponent in range(9, 1, -1))
    for index, value in enumerate(y_values):
        y = top + (bottom - top) * index / (len(y_values) - 1)
        draw.line((left, y, right, y), fill=(205, 205, 205), width=1)
        text = f"{value:,}"
        box = draw.textbbox((0, 0), text, font=font)
        draw.text((left - (box[2] - box[0]) - 8,
                   y - (box[3] - box[1]) / 2 - 2),
                  text, font=font, fill=(90, 90, 90))
    draw.rectangle(rect, outline=(90, 90, 90), width=1)
    return image, rect, years, y_values


def _year_comma_log_chart_realistic():
    image = Image.new("RGB", (980, 600), "white")
    draw = ImageDraw.Draw(image)
    font = _font(15)
    rect = (165, 85, 880, 480)
    left, top, right, bottom = rect
    first_year, last_year = 1981, 2012
    years = tuple(range(1981, 2010, 4))
    # Match the real chart: year ticks are proportional to a 1981..2012 time
    # axis, so the last printed 2009 tick is intentionally before the right edge.
    for value in years:
        x = left + (right - left) * (value - first_year) / (last_year - first_year)
        text = str(value)
        box = draw.textbbox((0, 0), text, font=font)
        draw.text((x - (box[2] - box[0]) / 2, bottom + 9), text,
                  font=font, fill=(82, 82, 82))
    y_values = tuple(10 ** exponent for exponent in range(9, 1, -1))
    for index, value in enumerate(y_values):
        y = top + (bottom - top) * index / (len(y_values) - 1)
        draw.line((left, y, right, y), fill=(196, 196, 196), width=1)
        text = f"{value:,}"
        box = draw.textbbox((0, 0), text, font=font)
        draw.text((left - (box[2] - box[0]) - 9,
                   y - (box[3] - box[1]) / 2 - 2),
                  text, font=font, fill=(82, 82, 82))
    draw.line((left, top, left, bottom), fill=(90, 90, 90), width=1)
    draw.line((left, bottom, right, bottom), fill=(90, 90, 90), width=1)
    return image, rect, years, y_values


def _scientific_log_chart(marker='e'):
    image = Image.new("RGB", (700, 400), "white")
    draw = ImageDraw.Draw(image)
    font = _font()
    rect = (100, 50, 600, 320)
    left, top, right, bottom = rect
    exponents = (-3, -2, -1, 0)
    for index, exponent in enumerate(exponents):
        x = left + (right - left) * index / (len(exponents) - 1)
        draw.line((x, top, x, bottom), fill=(220, 220, 220), width=1)
        text = f"1{marker}{exponent}"
        box = draw.textbbox((0, 0), text, font=font)
        draw.text((x - (box[2] - box[0]) / 2, bottom + 7), text,
                  font=font, fill=(80, 80, 80))
    for index, value in enumerate((0, 1, 2, 3)):
        y = bottom - (bottom - top) * index / 3
        draw.line((left, y, right, y), fill=(220, 220, 220), width=1)
        text = str(value)
        box = draw.textbbox((0, 0), text, font=font)
        draw.text((left - (box[2] - box[0]) - 8, y - 8), text,
                  font=font, fill=(80, 80, 80))
    draw.rectangle(rect, outline=(80, 80, 80), width=1)
    return image, rect


def _rotated_iso_datetime_chart():
    image = Image.new("RGB", (1200, 760), "white")
    draw = ImageDraw.Draw(image)
    font = _font(18)
    rect = (145, 120, 935, 620)
    left, top, right, bottom = rect
    x_dates = tuple(date.fromisoformat(value) for value in (
        '2020-01-21', '2020-01-23', '2020-01-25', '2020-01-27', '2020-01-29',
        '2020-01-31', '2020-02-01', '2020-02-03', '2020-02-05'))
    y_values = tuple(range(0, 3_500_001, 500_000))

    def paste_rotated_text(base, xy, text, angle, font, fill):
        dummy = Image.new('RGBA', (1, 1), (255, 255, 255, 0))
        d = ImageDraw.Draw(dummy)
        box = d.textbbox((0, 0), text, font=font)
        text_image = Image.new('RGBA', (box[2] - box[0] + 8, box[3] - box[1] + 8), (255, 255, 255, 0))
        td = ImageDraw.Draw(text_image)
        td.text((4 - box[0], 4 - box[1]), text, font=font, fill=fill)
        rotated = text_image.rotate(angle, expand=True, resample=Image.Resampling.BICUBIC)
        base.alpha_composite(rotated, dest=(int(xy[0]), int(xy[1])))

    canvas = image.convert('RGBA')
    overlay_draw = ImageDraw.Draw(canvas)

    for index, value in enumerate(y_values):
        y = bottom - (bottom - top) * index / (len(y_values) - 1)
        overlay_draw.line((left, y, right, y), fill=(220, 220, 220, 255), width=1)
        text = str(value)
        box = overlay_draw.textbbox((0, 0), text, font=font)
        overlay_draw.text((left - (box[2] - box[0]) - 10, y - (box[3] - box[1]) / 2 - 2),
                          text, font=font, fill=(90, 90, 90, 255))

    for index, current in enumerate(x_dates):
        x = left + (right - left) * index / (len(x_dates) - 1)
        label = current.isoformat()
        paste_rotated_text(canvas, (x - 42, bottom + 12), label, 45, font, (90, 90, 90, 255))

    overlay_draw.line((left, top, left, bottom), fill=(95, 95, 95, 255), width=1)
    overlay_draw.line((left, bottom, right, bottom), fill=(95, 95, 95, 255), width=1)
    image = canvas.convert('RGB')
    return image, rect, x_dates, y_values


class TickScaleDetectionTests(unittest.TestCase):
    def test_decades_auto_classify_as_log10(self):
        self.assertEqual(AxisScale.LOG10,
                         td._observed_axis_scale(_ticks((1, 10, 100, 1000)), AxisScale.LINEAR))

    def test_e_powers_auto_classify_as_ln(self):
        values = (1, math.e, math.e ** 2, math.e ** 3)
        self.assertEqual(AxisScale.LN,
                         td._observed_axis_scale(_ticks(values), AxisScale.LINEAR))

    def test_positive_linear_range_stays_linear(self):
        self.assertEqual(AxisScale.LINEAR,
                          td._observed_axis_scale(_ticks((100, 200, 300, 400, 500)), AxisScale.LINEAR))

    def test_one_clear_nonlog_label_is_not_discarded_to_force_log(self):
        self.assertEqual(AxisScale.LINEAR,
                         td._observed_axis_scale(_ticks((1, 10, 100, 1000, 2500)), AxisScale.LINEAR))

    def test_one_weak_outlier_can_be_excluded_from_scale_fit_not_readings(self):
        ticks = list(_ticks((1, 10, 100, 1000, 2500)))
        ticks[-1] = td.TickReading(400, 2500, '2500', .45, (1, 1, 8, 8))
        original = tuple(ticks)
        self.assertEqual(AxisScale.LOG10, td._observed_axis_scale(ticks, AxisScale.LINEAR))
        self.assertEqual(original, tuple(ticks))

    def test_inferred_ticks_do_not_vote_on_scale(self):
        ticks = list(_ticks((100, 200, 300, 400)))
        ticks.append(td.TickReading(450.0, 1000000.0, "1000000", .95, (0, 0, 0, 0)))
        self.assertEqual(AxisScale.LINEAR,
                         td._observed_axis_scale(tuple(ticks), AxisScale.LINEAR))

    def test_log_completion_interpolates_in_log_space(self):
        observed = tuple(td.TickReading(float(pixel), float(value), str(value), .9, (1, 1, 5, 5))
                         for pixel, value in ((0, 1), (100, 10), (300, 1000), (400, 10000)))
        detection = td.AxisTickDetection('x', observed, .9, AxisScale.LOG10)
        self.assertTrue(td._axis_completion_supported(detection, (0, 100, 200, 300, 400)))
        completed = td._complete_lattice_ticks(detection, (0, 100, 200, 300, 400), (0, 0, 400, 300))
        middle = min(completed.ticks, key=lambda tick: abs(tick.position - 200))
        self.assertAlmostEqual(100.0, middle.value, places=6)
        self.assertEqual((0, 0, 0, 0), middle.bbox)


    def test_missing_log_label_is_reconstructed_in_log_space(self):
        image, rect = _log_chart(missing_x_index=2)
        result = td.detect_calibration_ticks(image, rect)
        self.assertTrue(result.x.ready)
        self.assertEqual(AxisScale.LOG10, result.x.scale)
        self.assertEqual(5, len(result.x.ticks))
        middle = min(result.x.ticks, key=lambda tick: abs(tick.value - 10))
        self.assertAlmostEqual(10.0, middle.value, places=5)
        self.assertEqual((0, 0, 0, 0), middle.bbox)

    def test_log_outlier_requires_raster_support_before_repair(self):
        positions = tuple(float(index * 100) for index in range(5))
        values = (1, 10, 100, 800, 10000)
        ticks = tuple(td.TickReading(position, float(value), str(value), .9, (1, 1, 5, 8))
                      for position, value in zip(positions, values))
        detection = td.AxisTickDetection('x', ticks, .9, AxisScale.LOG10,
                                         mark_positions=positions)
        words = {300.0: ([[1]], (1, 1, 5, 8))}
        from unittest.mock import patch
        with patch.object(td, '_normalize_word_mask', return_value=object()),                 patch.object(td, '_normalized_word_template_score',
                             side_effect=lambda observed, text: .10 if text == '1000' else .30):
            repaired = td._infer_template_supported_log_outliers(detection, words, positions)
        target = repaired.ticks[3]
        self.assertAlmostEqual(1000.0, target.value, places=5)
        self.assertEqual((0, 0, 0, 0), target.bbox)
        self.assertIn(300.0, repaired.unread_positions)

    def test_full_ocr_detects_log10_x_and_linear_y(self):
        image, rect = _log_chart()
        result = td.detect_calibration_ticks(image, rect)
        self.assertTrue(result.x.ready)
        self.assertTrue(result.y.ready)
        self.assertEqual(AxisScale.LOG10, result.x.scale)
        self.assertEqual(AxisScale.LINEAR, result.y.scale)
        self.assertEqual([.1, 1, 10, 100, 1000],
                         [round(tick.value, 6) for tick in result.x.ticks])

    def test_year_axis_without_vertical_grid_and_comma_log_y(self):
        image, rect, years, y_values = _year_comma_log_chart()
        result = td.detect_calibration_ticks(image, rect)
        self.assertTrue(result.x.ready, result.x)
        self.assertTrue(result.y.ready, result.y)
        self.assertEqual(AxisScale.DATETIME, result.x.scale)
        self.assertEqual(AxisScale.LOG10, result.y.scale)
        self.assertEqual(list(years), [round(tick.value) for tick in result.x.ticks])
        self.assertEqual(list(y_values), [round(tick.value) for tick in result.y.ticks])

    def test_realistic_datetime_year_axis_and_comma_log_y(self):
        image, rect, years, y_values = _year_comma_log_chart_realistic()
        result = td.detect_calibration_ticks(image, rect)
        self.assertTrue(result.x.ready, result.x)
        self.assertTrue(result.y.ready, result.y)
        self.assertEqual(AxisScale.DATETIME, result.x.scale)
        self.assertEqual(AxisScale.LOG10, result.y.scale)
        self.assertEqual(list(years), [round(tick.value) for tick in result.x.ticks])
        self.assertEqual(list(y_values), [round(tick.value) for tick in result.y.ticks])

    def test_rotated_iso_datetime_x_axis_and_linear_y(self):
        image, rect, x_dates, y_values = _rotated_iso_datetime_chart()
        result = td.detect_calibration_ticks(image, rect)
        self.assertTrue(result.x.ready, result.x)
        self.assertTrue(result.y.ready, result.y)
        self.assertEqual(AxisScale.DATETIME, result.x.scale)
        self.assertEqual(AxisScale.LINEAR, result.y.scale)
        expected = [__import__('datetime').datetime.combine(value, __import__('datetime').datetime.min.time()).replace(tzinfo=timezone.utc).timestamp()
                    for value in x_dates]
        self.assertEqual([round(value) for value in expected],
                         [round(tick.value) for tick in result.x.ticks])
        self.assertEqual(list(reversed(y_values)), [round(tick.value) for tick in result.y.ticks])

    def test_datetime_calibration_uses_linear_time_mapping_not_log_mapping(self):
        from WinUx.plotdigitizer.core.calibration import Calibration
        from WinUx.plotdigitizer.core.models import AxisAnchor
        cal = Calibration(scale_x=AxisScale.DATETIME, scale_y=AxisScale.LINEAR)
        cal.x1 = AxisAnchor(0.0, 100.0, 1981.0)
        cal.x2 = AxisAnchor(100.0, 100.0, 2011.0)
        cal.y1 = AxisAnchor(0.0, 100.0, 0.0)
        cal.y2 = AxisAnchor(0.0, 0.0, 100.0)
        cal.points_x = [AxisAnchor(0.0, 100.0, 1981.0),
                        AxisAnchor(50.0, 100.0, 1996.0),
                        AxisAnchor(100.0, 100.0, 2011.0)]
        x, _ = cal.pixel_to_data(25.0, 50.0)
        self.assertAlmostEqual(1988.5, x, places=6)
        px, _ = cal.data_to_pixel(1988.5, 50.0)
        self.assertAlmostEqual(25.0, px, places=6)

    def test_engine_adopts_datetime_x_and_log10_y(self):
        image, rect, years, y_values = _year_comma_log_chart_realistic()
        engine = DigitizerEngine()
        engine.image = image
        engine.set_plot_rect(rect)
        result = td.detect_calibration_ticks(image, rect)
        self.assertTrue(engine.apply_tick_calibration_detection(result, expected_rect=rect))
        self.assertEqual(AxisScale.DATETIME, engine.calibration.scale_x)
        self.assertEqual(AxisScale.LOG10, engine.calibration.scale_y)
        x_left, y_bottom = engine.calibration.pixel_to_data(rect[0], rect[3])
        x_right, y_top = engine.calibration.pixel_to_data(rect[2], rect[1])
        self.assertAlmostEqual(1981.0, x_left, delta=.15)
        self.assertAlmostEqual(2012.0, x_right, delta=.15)
        self.assertAlmostEqual(100.0, y_bottom, delta=.2)
        self.assertAlmostEqual(1_000_000_000.0, y_top, delta=1000.0)

    def test_thousands_separator_is_numeric_hypothesis(self):
        hypotheses = td._numeric_text_hypotheses('100.000')
        self.assertIn(('100,000', 100000.0), hypotheses)
        hypotheses = td._numeric_text_hypotheses('10.000000')
        self.assertIn(('10,000,000', 10000000.0), hypotheses)

    def test_engine_adopts_detected_scale(self):
        image, rect = _log_chart()
        engine = DigitizerEngine()
        engine.image = image
        engine.set_plot_rect(rect)
        result = td.detect_calibration_ticks(image, rect)
        self.assertTrue(engine.apply_tick_calibration_detection(result, expected_rect=rect))
        self.assertEqual(AxisScale.LOG10, engine.calibration.scale_x)
        self.assertEqual(AxisScale.LINEAR, engine.calibration.scale_y)

    def test_full_ocr_reads_lowercase_scientific_notation(self):
        image, rect = _scientific_log_chart('e')
        result = td.detect_calibration_ticks(image, rect)
        self.assertTrue(result.x.ready, result.x)
        self.assertEqual(AxisScale.LOG10, result.x.scale)
        self.assertEqual([.001, .01, .1, 1.0],
                         [round(tick.value, 6) for tick in result.x.ticks])
        self.assertTrue(all('e' in tick.text.lower() for tick in result.x.ticks))

    def test_full_ocr_reads_uppercase_scientific_notation(self):
        image, rect = _scientific_log_chart('E')
        result = td.detect_calibration_ticks(image, rect)
        self.assertTrue(result.x.ready, result.x)
        self.assertEqual(AxisScale.LOG10, result.x.scale)
        self.assertEqual([.001, .01, .1, 1.0],
                         [round(tick.value, 6) for tick in result.x.ticks])


if __name__ == '__main__':
    unittest.main()

class TickAccuracyConsensusTests(unittest.TestCase):
    def test_multi_hypothesis_consensus_beats_one_overconfident_outlier(self):
        reading = td._consensus_numeric_reading((
            ('3.2', 3.2, .92),
            ('1.2', 1.2, .69),
            ('1.2', 1.2, .67),
            ('1.2', 1.2, .65),
        ))
        self.assertIsNotNone(reading)
        self.assertEqual('1.2', reading[0])
        self.assertAlmostEqual(1.2, reading[1])
        self.assertGreater(reading[2], .60)

    def test_consensus_preserves_single_clear_reading(self):
        self.assertEqual(('0.6', 0.6, .91),
                         td._consensus_numeric_reading((('0.6', .6, .91),)))

    def test_scientific_notation_is_a_value_template_variant(self):
        variants = td._format_tick_value_variants(.001)
        self.assertIn('0.001', variants)
        self.assertIn('1e-3', variants)
        self.assertIn('1E-3', variants)
        self.assertIn('10^-3', variants)

    def test_scientific_glyph_reader_handles_decimal_mantissa(self):
        font = _font()
        text = '2.5e-3'
        box = font.getbbox(text)
        image = Image.new('RGB', (box[2] - box[0] + 8, box[3] - box[1] + 8), 'white')
        ImageDraw.Draw(image).text((4 - box[0], 4 - box[1]), text, font=font, fill=(80, 80, 80))
        mask = td._binary_mask(image)
        bounds = td._bbox(mask)
        reading = td._read_scientific_glyph_word(td._crop_mask(mask, bounds))
        self.assertIsNotNone(reading)
        self.assertAlmostEqual(.0025, reading[1], places=8)

    def test_plain_multi_digit_word_is_not_relabelled_scientific(self):
        font = _font()
        text = '2000'
        box = font.getbbox(text)
        image = Image.new('RGB', (box[2] - box[0] + 8, box[3] - box[1] + 8), 'white')
        ImageDraw.Draw(image).text((4 - box[0], 4 - box[1]), text, font=font, fill=(80, 80, 80))
        mask = td._binary_mask(image)
        bounds = td._bbox(mask)
        self.assertIsNone(td._read_scientific_glyph_word(td._crop_mask(mask, bounds)))

    def test_value_template_verification_accepts_equivalent_scientific_text(self):
        observed = td._word_templates('1e-3')[0]
        correct = td._normalized_value_template_score(observed, .001)
        wrong = td._normalized_value_template_score(observed, .002)
        self.assertLess(correct, .01)
        self.assertGreater(wrong, correct + .03)

    def test_two_weak_ocr_outliers_do_not_hide_clear_log_geometry(self):
        values = (1, 70, 100, 1000, 30000, 100000)
        confidence = (.92, .45, .92, .92, .45, .92)
        ticks = tuple(td.TickReading(float(index * 100), float(value), str(value), conf,
                                     (1, 1, 8, 8))
                      for index, (value, conf) in enumerate(zip(values, confidence)))
        self.assertEqual(AxisScale.LOG10,
                         td._observed_axis_scale(ticks, AxisScale.LINEAR))

    def test_two_strong_conflicting_labels_are_not_discarded_to_force_log(self):
        values = (1, 70, 100, 1000, 30000, 100000)
        confidence = (.92, .90, .92, .92, .90, .92)
        ticks = tuple(td.TickReading(float(index * 100), float(value), str(value), conf,
                                     (1, 1, 8, 8))
                      for index, (value, conf) in enumerate(zip(values, confidence)))
        self.assertEqual(AxisScale.LINEAR,
                         td._observed_axis_scale(ticks, AxisScale.LINEAR))
