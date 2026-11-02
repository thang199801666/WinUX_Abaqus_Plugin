import math
import unittest

from WinUx.plotdigitizer.core.calibration import Calibration
from WinUx.plotdigitizer.core.models import AxisAnchor, AxisScale
from WinUx.plotdigitizer.core.engine import DigitizerEngine
from PIL import Image


class MultiPointCalibrationTests(unittest.TestCase):
    def make_calibration(self):
        calibration = Calibration()
        for key, px, py, value in (("x1", 0, 100, 0), ("x2", 100, 100, 10),
                                   ("y1", 0, 100, 0), ("y2", 0, 0, 100)):
            calibration.set_anchor(key, px, py, value)
        return calibration

    def test_fit_uses_interior_points_and_round_trips(self):
        calibration = self.make_calibration()
        calibration.set_axis_points("x", [AxisAnchor(0, 100, 0),
                                          AxisAnchor(50, 100, 6),
                                          AxisAnchor(100, 100, 10)])
        calibration.set_axis_points("y", [AxisAnchor(0, 100, 0),
                                          AxisAnchor(0, 50, 51),
                                          AxisAnchor(0, 0, 100)])
        x, y = calibration.pixel_to_data(50, 50)
        self.assertAlmostEqual(16 / 3, x)
        self.assertAlmostEqual(151 / 3, y)
        px, py = calibration.data_to_pixel(x, y)
        self.assertAlmostEqual(50, px)
        self.assertAlmostEqual(50, py)
        restored = Calibration.from_dict(calibration.to_dict())
        self.assertEqual(calibration.pixel_to_data(25, 75), restored.pixel_to_data(25, 75))

    def test_manual_anchor_edit_clears_only_its_axis_fit(self):
        calibration = self.make_calibration()
        points = [AxisAnchor(i, i, i) for i in (1, 10, 100)]
        calibration.set_axis_points("x", points)
        calibration.set_axis_points("y", points)
        calibration.set_anchor("x2", 100, 100, 20)
        self.assertEqual([], calibration.points_x)
        self.assertEqual(points, calibration.points_y)
        self.assertAlmostEqual(10, calibration.pixel_to_data(50, 50)[0])

    def test_logarithmic_fit_and_invalid_points(self):
        calibration = self.make_calibration()
        calibration.set_anchor("x1", 0, 100, 1)
        calibration.set_anchor("x2", 100, 100, 100)
        calibration.scale_x = AxisScale.LOG10
        points = [AxisAnchor(0, 100, 1), AxisAnchor(50, 100, 10), AxisAnchor(100, 100, 100)]
        calibration.set_axis_points("x", points)
        self.assertAlmostEqual(math.sqrt(10), calibration.pixel_to_data(25, 50)[0])
        self.assertAlmostEqual(25, calibration.data_to_pixel(math.sqrt(10), 50)[0])
        with self.assertRaises(ValueError):
            calibration.set_axis_points("x", [AxisAnchor(0, 0, 0)] + points)
        self.assertEqual(points, calibration.points_x)

    def test_old_projects_still_use_two_anchors(self):
        calibration = self.make_calibration()
        data = calibration.to_dict()
        del data["points_x"], data["points_y"]
        self.assertEqual((5, 50), Calibration.from_dict(data).pixel_to_data(50, 50))


class EditableCalibrationPointsTests(unittest.TestCase):
    def setUp(self):
        self.engine = DigitizerEngine()
        self.engine.image = Image.new('RGB', (201, 201), 'white')

    def populate(self):
        for px, value in ((10, 0), (100, 5), (190, 10)):
            self.engine.add_calibration_point('x', px, 190, value)
        for py, value in ((190, 0), (100, 50), (10, 100)):
            self.engine.add_calibration_point('y', 10, py, value)

    def test_build_calibration_from_independent_point_lists(self):
        self.populate()
        self.assertTrue(self.engine.calibration_ready())
        self.assertEqual(3, len(self.engine.calibration_points('x')))
        self.assertEqual(3, len(self.engine.calibration_points('y')))
        self.assertEqual((5, 50), self.engine.pixel_to_data(100, 100))

    def test_update_move_remove_preserve_other_points_and_undo(self):
        self.populate()
        previous = self.engine.calibration.to_dict()
        self.engine.update_calibration_point('x', 1, value=6, px=102)
        self.assertEqual(3, len(self.engine.calibration.points_x))
        self.assertEqual(previous['points_y'], self.engine.calibration.to_dict()['points_y'])
        self.engine.undo()
        self.assertEqual(previous, self.engine.calibration.to_dict())
        self.engine.redo()
        self.assertEqual(6, self.engine.calibration.points_x[1].value)
        self.engine.remove_calibration_point('x', 1)
        self.assertTrue(self.engine.calibration_ready())
        self.assertEqual(2, len(self.engine.calibration.points_x))
        self.engine.remove_calibration_point('x', 1)
        self.assertFalse(self.engine.calibration_ready())
        self.assertIsNone(self.engine.calibration.x2)

    def test_duplicate_pixels_and_invalid_values_are_atomic(self):
        self.populate()
        previous = self.engine.calibration.to_dict()
        for value in (float('nan'), float('inf')):
            with self.assertRaises(ValueError):
                self.engine.update_calibration_point('x', 1, value=value)
            self.assertEqual(previous, self.engine.calibration.to_dict())
        with self.assertRaises(ValueError):
            self.engine.add_calibration_point('x', 100, 150, 6)
        self.assertEqual(previous, self.engine.calibration.to_dict())

    def test_unverified_box_seeds_do_not_enter_manual_point_fit(self):
        self.engine.set_plot_rect_with_corner_anchors((10, 10, 190, 190), detect_ticks=False)
        self.assertEqual([], self.engine.calibration_points('y'))
        self.engine.add_calibration_point('y', 10, 190, 0)
        self.engine.add_calibration_point('y', 10, 100, 500)
        self.engine.add_calibration_point('y', 10, 10, 1000)
        self.assertEqual([0, 500, 1000], [p.value for p in self.engine.calibration.points_y])

    def test_remove_all_points_and_add_again(self):
        self.populate()
        for _ in range(3):
            self.engine.remove_calibration_point('x', 0)
        self.assertEqual([], self.engine.calibration_points('x'))
        self.assertIsNone(self.engine.calibration.x1)
        self.engine.add_calibration_point('x', 50, 190, 2)
        self.assertEqual([2], [p.value for p in self.engine.calibration_points('x')])

    def test_manual_logarithmic_axes_and_round_trip(self):
        self.engine.set_axis_scale(x=AxisScale.LOG10, y=AxisScale.LN)
        for pixel, value in ((10, 1), (100, 10), (190, 100)):
            self.engine.add_calibration_point('x', pixel, 190, value)
        for pixel, value in ((190, 1), (100, math.e), (10, math.e ** 2)):
            self.engine.add_calibration_point('y', 10, pixel, value)
        x, y = self.engine.pixel_to_data(100, 100)
        self.assertAlmostEqual(10, x)
        self.assertAlmostEqual(math.e, y)
        px, py = self.engine.calibration.data_to_pixel(x, y)
        self.assertAlmostEqual(100, px)
        self.assertAlmostEqual(100, py)
        previous = self.engine.calibration.to_dict()
        with self.assertRaises(ValueError):
            self.engine.update_calibration_point('x', 1, value=0)
        self.assertEqual(previous, self.engine.calibration.to_dict())
