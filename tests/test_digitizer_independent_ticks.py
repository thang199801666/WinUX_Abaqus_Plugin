"""Independent OCR and through-tick mapping regressions (abaqus python)."""
import sys
from pathlib import Path
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from PIL import Image, ImageDraw
from test_digitizer_tick_auto_calibration import _font
from WinUx.plotdigitizer.core import tick_detection as td
from WinUx.plotdigitizer.core.calibration import Calibration
from WinUx.plotdigitizer.core.models import AxisAnchor, AxisScale
from WinUx.plotdigitizer.core.engine import DigitizerEngine


class IndependentTickTests(unittest.TestCase):
    def chart(self, values, positions=None, label_gap=7):
        rect = (110, 60, 710, 390)
        positions = positions or [110 + i * 600 / (len(values) - 1) for i in range(len(values))]
        image = Image.new('RGB', (800, 500), 'white')
        draw = ImageDraw.Draw(image)
        for x, value in zip(positions, values):
            draw.line((x, 60, x, 390), fill=(220, 220, 220))
            text = str(value)
            box = _font(16).getbbox(text)
            draw.text((x - (box[2] - box[0]) / 2, 390 + label_gap), text, font=_font(16), fill=(100, 100, 100))
        draw.rectangle(rect, outline=(80, 80, 80))
        return image, rect

    def test_nonlinear_labels_are_not_repaired(self):
        values = [0, .08, .16, .24, .32, .4, .48, .56, .6]
        image, rect = self.chart(values)
        with patch.object(td, '_robust_axis_values', side_effect=AssertionError('value repair')), \
             patch.object(td, '_regular_grid_lattice', side_effect=AssertionError('invented positions')), \
             patch.object(td, '_complete_lattice_ticks', side_effect=AssertionError('tick filling')):
            detected = td._detect_axis(image, rect, 'x', AxisScale.LINEAR)
        self.assertTrue(detected.ready)
        self.assertEqual(values, [t.value for t in detected.ticks])

    def test_nonuniform_positions_are_observed_not_completed(self):
        image, rect = self.chart([0, 1, 3, 9, 20], [110, 175, 310, 505, 710])
        detected = td._detect_axis(image, rect, 'x', AxisScale.LINEAR)
        self.assertEqual([110, 175, 310, 505, 710], [t.position for t in detected.ticks])
        self.assertEqual([0, 1, 3, 9, 20], [t.value for t in detected.ticks])

    def test_hand_drawn_box_baseline_does_not_join_x_labels(self):
        values = [0, .08, .16, .24, .32, .4, .48, .56, .6]
        image, rect = self.chart(values, label_gap=4)
        # The plot baseline spans only 80% of the padded label crop. The old
        # full-crop rule remover left it in place and dilation joined all words.
        # An outer frame must not beat the last numeric label geometrically.
        ImageDraw.Draw(image).rectangle((20, 20, 735, 475), outline=(80, 80, 80), width=2)
        for bottom in (386, 387, 388, 389, 390, 391):
            with self.subTest(bottom=bottom):
                detected = td._detect_axis(image, (*rect[:3], bottom), 'x', AxisScale.LINEAR)
                self.assertTrue(detected.ready)
                self.assertEqual(values, [t.value for t in detected.ticks])
                self.assertEqual((), detected.unread_positions)

    def test_missing_word_is_reported_not_filled(self):
        image, rect = self.chart([0, 1, 3, 9, 20])
        ImageDraw.Draw(image).rectangle((395, 395, 425, 425), fill='white')
        with patch.object(td, '_label_deskew_angle', return_value=0), \
             patch.object(td, '_read_rotated_source_word', side_effect=AssertionError('whole-axis retry')):
            detected = td._detect_axis(image, rect, 'x', AxisScale.LINEAR)
        self.assertIn(410, detected.unread_positions)
        self.assertNotIn(410, [t.position for t in detected.ticks])

    def test_box_inset_does_not_drop_observed_endpoint_ticks(self):
        image, rect = self.chart([0, 1, 3, 9, 20])
        inset = (rect[0] + 3, rect[1] + 3, rect[2] - 3, rect[3] - 3)
        detected = td._detect_axis(image, inset, 'x', AxisScale.LINEAR)
        self.assertEqual([0, 1, 3, 9, 20], [t.value for t in detected.ticks])
        self.assertEqual([110, 260, 410, 560, 710], [t.position for t in detected.ticks])

    def test_log_classification_does_not_modify_values(self):
        image, rect = self.chart([1, 10, 100, 1000])
        detected = td._detect_axis(image, rect, 'x', AxisScale.LINEAR)
        self.assertEqual(AxisScale.LOG10, detected.scale)
        self.assertEqual([1, 10, 100, 1000], [t.value for t in detected.ticks])

    def test_left_aligned_y_zero_is_measured_not_inferred(self):
        image = Image.new('RGB', (520, 450), 'white')
        draw = ImageDraw.Draw(image)
        rect = (110, 50, 480, 390)
        values = (64000, 48000, 32000, 16000, 0)
        for index, value in enumerate(values):
            y = 50 + index * 85
            draw.line((110, y, 480, y), fill=(220, 220, 220))
            draw.text((50, y - 8), str(value), font=_font(16), fill=(90, 90, 90))
        draw.rectangle(rect, outline=(80, 80, 80))
        detected = td._detect_axis(image, rect, 'y', AxisScale.LINEAR)
        self.assertEqual(list(values), [t.value for t in detected.ticks])
        self.assertFalse(detected.unread_positions)
        self.assertTrue(all(t.bbox != (0, 0, 0, 0) for t in detected.ticks))

    def calibration(self, scale=AxisScale.LINEAR):
        cal = Calibration(mapping_x='ticks', scale_x=scale)
        cal.set_anchor('y1', 0, 100, 0)
        cal.set_anchor('y2', 0, 0, 1)
        values = [1, 10, 1000] if scale != AxisScale.LINEAR else [0, .56, .6]
        cal.set_axis_points('x', [AxisAnchor(p, 100, v) for p, v in zip([0, 50, 100], values)], sync_anchors=True)
        return cal

    def test_mapping_hits_every_tick_and_round_trips_after_save(self):
        cal = Calibration.from_dict(self.calibration().to_dict())
        for pixel in [-10, 0, 25, 50, 75, 100, 110]:
            x, y = cal.pixel_to_data(pixel, 40)
            px, py = cal.data_to_pixel(x, y)
            self.assertAlmostEqual(pixel, px)
            self.assertAlmostEqual(40, py)
        self.assertEqual(.56, cal.pixel_to_data(50, 100)[0])
        self.assertEqual(.6, cal.pixel_to_data(100, 100)[0])
        self.assertAlmostEqual(.58, cal.pixel_to_data(75, 100)[0])

    def test_log_mapping_interpolates_between_adjacent_ticks(self):
        cal = self.calibration(AxisScale.LOG10)
        self.assertAlmostEqual(100, cal.pixel_to_data(75, 100)[0])
        self.assertAlmostEqual(75, cal.data_to_pixel(100, 0)[0])

    def test_nonmonotonic_manual_correction_is_rejected(self):
        cal = self.calibration()
        with self.assertRaises(ValueError):
            cal.set_axis_points('x', [AxisAnchor(0, 100, 0), AxisAnchor(50, 100, 2), AxisAnchor(100, 100, 1)])
        self.assertEqual(.56, cal.axis_points('x')[1].value)

    def test_engine_keeps_box_corners_separate_from_measured_tick_mapping(self):
        engine = DigitizerEngine()
        engine.image = Image.new('RGB', (200, 200), 'white')
        engine.set_plot_rect_with_corner_anchors((10, 10, 190, 190), detect_ticks=False)
        ticks = tuple(td.TickReading(p, v, str(v), .9, (1, 1, 5, 5))
                      for p, v in [(20, 0), (100, .56), (180, .6)])
        result = td.TickCalibrationDetection(td.AxisTickDetection('x', ticks, .9, AxisScale.LINEAR),
                                            td.AxisTickDetection('y', (), 0, AxisScale.LINEAR))
        self.assertTrue(engine.apply_tick_calibration_detection(result))
        self.assertEqual((10, 190), (engine.calibration.x1.px, engine.calibration.x1.py))
        self.assertEqual((10, 190), (engine.calibration.y1.px, engine.calibration.y1.py))
        self.assertEqual(190, engine.calibration.x2.px)
        self.assertEqual([20, 100, 180], [p.px for p in engine.calibration.points_x])
        self.assertEqual(.56, engine.calibration.pixel_to_data(100, 190)[0])
        engine.update_calibration_point('x', 1, value=.5)
        self.assertEqual('ticks', engine.calibration.mapping_x)
        self.assertEqual(.5, engine.calibration.pixel_to_data(100, 190)[0])
        engine.undo()
        self.assertEqual('ticks', engine.calibration.mapping_x)
        self.assertEqual(.56, engine.calibration.pixel_to_data(100, 190)[0])


if __name__ == '__main__':
    unittest.main()
