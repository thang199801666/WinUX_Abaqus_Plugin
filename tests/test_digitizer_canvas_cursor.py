"""Canvas-wide crosshair, marker feedback and pan cursor policy."""
from types import SimpleNamespace
import unittest
from unittest.mock import Mock

from WinUx.plotdigitizer.ui.dialog import PlotDigitizerDialog
from WinUx.plotdigitizer.ui.markers import cursor_hits_marker


class MarkerCursorHitTests(unittest.TestCase):
    def dataset(self, *, visible=True, locked=False):
        return SimpleNamespace(visible=visible, locked=locked,
                               extracted_pixels=[(50, 60)], manual_points=[])

    def test_visible_marker_is_detected_even_if_dataset_is_locked(self):
        self.assertTrue(cursor_hits_marker([self.dataset(locked=True)], 50, 60, 1))

    def test_hidden_dataset_does_not_change_cursor(self):
        self.assertFalse(cursor_hits_marker([self.dataset(visible=False)], 50, 60, 1))

    def test_hit_radius_stays_in_screen_pixels_when_zoomed(self):
        dataset = self.dataset()
        self.assertTrue(cursor_hits_marker([dataset], 53, 60, 2))
        self.assertFalse(cursor_hits_marker([dataset], 56, 60, 2))

    def test_manual_and_inactive_dataset_markers_are_detected(self):
        dataset = self.dataset()
        dataset.extracted_pixels = []
        dataset.manual_points = [SimpleNamespace(px=80, py=90)]
        self.assertTrue(cursor_hits_marker([self.dataset(), dataset], 80, 90, 1))


class CrosshairPaintTests(unittest.TestCase):
    def view(self, *, local=(120, 80), marker=False, pan=False):
        painter = Mock()
        layer = SimpleNamespace(exists=lambda: True, clear=Mock(), painter=lambda: painter)
        view = SimpleNamespace(
            _pointer_layer=layer, _sync_canvas_cursor=Mock(), _middle_drag=pan,
            _paint_preview=Mock(),
            _drag_start=None, _drag_preview=None, _drag_target=None, _hover_point=None,
            _cursor_canvas=local, _cursor_pixel=None, _cursor_over_marker=marker,
            _canvas_rect=lambda: ((0, 0), (640, 480)),
        )
        return view, painter

    def test_crosshair_spans_canvas_without_an_image_or_pick_mode(self):
        view, painter = self.view()
        PlotDigitizerDialog._paint_pointer(view)
        self.assertEqual(painter.drawLine.call_args_list[0].args, ((0, 80), (640, 80)))
        self.assertEqual(painter.drawLine.call_args_list[1].args, ((120, 0), (120, 480)))
        painter.drawRect.assert_not_called()

    def test_marker_hover_adds_center_square(self):
        view, painter = self.view(marker=True)
        PlotDigitizerDialog._paint_pointer(view)
        self.assertEqual(painter.drawLine.call_count, 2)
        self.assertEqual(painter.drawRect.call_args.args, ((116, 76), (124, 84)))

    def test_pan_hides_crosshair_and_clears_previous_overlay(self):
        view, painter = self.view(pan=True)
        PlotDigitizerDialog._paint_pointer(view)
        view._pointer_layer.clear.assert_called_once()
        painter.drawLine.assert_not_called()
        view._sync_canvas_cursor.assert_called_once()

    def test_leaving_canvas_removes_crosshair(self):
        view, painter = self.view(local=None)
        PlotDigitizerDialog._paint_pointer(view)
        painter.drawLine.assert_not_called()


if __name__ == "__main__":
    unittest.main()
