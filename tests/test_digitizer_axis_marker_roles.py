"""Reserved axis glyphs, common Box origin and measured tick identity."""
import sys
from pathlib import Path
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from PIL import Image
from WinUx.plotdigitizer.core import DigitizerEngine
from WinUx.plotdigitizer.core.calibration import Calibration
from WinUx.plotdigitizer.core.models import AxisAnchor
from WinUx.plotdigitizer.core import tick_detection as td
from WinUx.plotdigitizer.ui import markers
from WinUx.plotdigitizer.ui.dialog import PlotDigitizerDialog


class AxisMarkerRoleTests(unittest.TestCase):
    def test_box_origin_snaps_to_observed_zero_instead_of_extrapolating(self):
        engine = self.engine()
        engine.set_calibration_points('x', [AxisAnchor(22, 200, 0), AxisAnchor(100, 200, .25), AxisAnchor(190, 200, .6)])
        engine.set_calibration_points('y', [AxisAnchor(22, 30, 20000), AxisAnchor(22, 100, 10000), AxisAnchor(22, 198, 0)])
        cal = engine.calibration
        self.assertEqual((22, 198, 0), (cal.x1.px, cal.x1.py, cal.x1.value))
        self.assertEqual((22, 198, 0), (cal.y1.px, cal.y1.py, cal.y1.value))
        self.assertEqual((22, 20, 200, 198), engine.plot_rect)
        self.assertEqual((0, 0), cal.pixel_to_data(22, 198))
        self.assertEqual((22, 198), cal.data_to_pixel(0, 0))
        self.assertEqual(3, len(cal.points_x))
        self.assertEqual(3, len(cal.points_y))
        self.assertEqual((22, 198), (cal.points_x[0].px, cal.points_x[0].py))
        self.assertEqual((22, 198), (cal.points_y[-1].px, cal.points_y[-1].py))

    def engine(self):
        engine = DigitizerEngine()
        engine.image = Image.new('RGB', (220, 220), 'white')
        engine.set_plot_rect_with_corner_anchors((20, 20, 200, 200), detect_ticks=False)
        def axis(name, samples):
            return td.AxisTickDetection(name, tuple(td.TickReading(p, v, str(v), .9, (1, 1, 5, 5))
                                                   for p, v in samples), .9, td.AxisScale.LINEAR)
        # Neither axis has a printed endpoint label at the drawn Box corners.
        detection = td.TickCalibrationDetection(axis('x', [(30, 1), (100, 3), (190, 9)]),
                                                axis('y', [(30, 900), (100, 200), (190, 50)]))
        engine.apply_tick_calibration_detection(detection)
        return engine

    def test_box_origin_is_common_even_with_missing_endpoint_labels(self):
        engine = self.engine()
        cal = engine.calibration
        self.assertEqual((20, 200), (cal.x1.px, cal.x1.py))
        self.assertEqual((cal.x1.px, cal.x1.py), (cal.y1.px, cal.y1.py))
        self.assertEqual([30, 100, 190], [p.py for p in cal.points_y])
        self.assertEqual((3, 200), cal.pixel_to_data(100, 100))
        saved = Calibration.from_dict(cal.to_dict())
        self.assertEqual(cal.box_rect, saved.box_rect)
        engine.update_calibration_point('y', 1, value=250)
        self.assertEqual((20, 200), (engine.calibration.y1.px, engine.calibration.y1.py))
        engine.undo()
        self.assertEqual(cal.to_dict(), engine.calibration.to_dict())

    def test_marker_keys_distinguish_corner_handles_from_tick_indices(self):
        dialog = object.__new__(PlotDigitizerDialog)
        dialog.engine = self.engine()
        items = dict(dialog._calibration_markers())
        self.assertIs(items['x1'], dialog.engine.calibration.x1)
        self.assertIs(items['y1'], dialog.engine.calibration.y1)
        self.assertIs(items['yt1'], dialog.engine.calibration.points_y[0])
        self.assertEqual(0, dialog._calibration_point_index('yt1'))
        self.assertIsNone(dialog._calibration_point_index('y1'))
        self.assertIs(dialog._calibration_marker('yt2'), dialog.engine.calibration.points_y[1])

    def test_axes_use_asterisks_and_origin_uses_hollow_donut(self):
        for axis, kind in [('x', 'tick'), ('y', 'tick'), ('x', 'corner'), ('y', 'corner')]:
            painter = Mock()
            with patch.object(markers, 'QPainter', return_value=painter):
                markers.draw_axis_marker(object(), (10, 10), axis, kind=kind)
            self.assertFalse(painter.drawEllipse.called)
            self.assertFalse(painter.drawPolygon.called)
            self.assertEqual(6, painter.drawLine.call_count)  # 3 strokes + halo.
        painter = Mock()
        with patch.object(markers, 'QPainter', return_value=painter):
            markers.draw_axis_marker(object(), (10, 10), 'x', kind='origin')
        self.assertFalse(painter.drawLine.called)
        self.assertEqual(2, painter.drawEllipse.call_count)
        for call in painter.drawEllipse.call_args_list:
            self.assertEqual((0, 0, 0, 0), call.kwargs['fill'])

    def test_shared_origin_is_drawn_once_with_two_axis_labels(self):
        dialog = object.__new__(PlotDigitizerDialog)
        dialog.engine = self.engine()
        dialog._anchor_drag_target = dialog._anchor_drag_preview = None
        dialog.canvas = object()
        dialog._image_to_canvas = lambda x, y: (x + 200, y + 100)
        painter = Mock()
        with patch('WinUx.plotdigitizer.ui.dialog.draw_axis_marker') as draw:
            dialog._paint_calibration_markers(painter, 600, 600)
        self.assertEqual(1, sum(call.kwargs['kind'] == 'origin' for call in draw.call_args_list))
        labels = [call.args[1] for call in painter.drawText.call_args_list]
        self.assertTrue(any(label.startswith('X1 = ~') for label in labels))
        self.assertTrue(any(label.startswith('Y1 = ~') for label in labels))
        # Display ordinals can differ from storage order (boxed Y ticks are
        # numbered upward from the origin). Resolve the actual painted label.
        anchors = {dialog._calibration_marker_label_key(key): point
                   for key, point in dialog._calibration_markers()}
        for call in painter.drawText.call_args_list:
            (text_x, text_y), text = call.args
            key = text.split(' = ')[0]
            anchor = anchors[key]
            marker_x, marker_y = dialog._image_to_canvas(anchor.px, anchor.py)
            if key.startswith('X'):
                self.assertGreater(text_y, marker_y + 6)
            else:
                self.assertLessEqual(text_x + len(text) * 7, marker_x - 6)


if __name__ == '__main__':
    unittest.main()
