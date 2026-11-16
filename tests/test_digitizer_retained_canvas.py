"""Retained canvas allocation and viewport interaction contracts."""
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import run_winux
run_winux._configure_bundled_dependencies(str(ROOT))
from WinUx.plotdigitizer.ui.retained_canvas import _PaintCommands, RetainedCanvasLayer
from WinUx.plotdigitizer.ui.controllers.canvas import CanvasController
from DearUIQt.core import QPoint


class RetainedCanvasTests(unittest.TestCase):
    def setUp(self):
        self.backend = Mock()
        self.backend.draw_circle.side_effect = [10, 11, 12]
        self.backend.draw_line.return_value = 20
        self.commands = _PaintCommands(self.backend, 1)

    def frame(self, center=(10, 20), radius=3):
        self.commands.index = 0
        result = self.commands.draw_circle(center, radius, parent=1, color=(1, 2, 3, 255))
        self.commands.finish()
        return result

    def test_identical_frame_does_not_allocate_delete_or_configure(self):
        self.assertEqual(self.frame(), self.frame())
        self.backend.draw_circle.assert_called_once()
        self.backend.delete_item.assert_not_called()
        self.backend.configure_item.assert_not_called()

    def test_zoom_updates_center_and_radius_in_place(self):
        self.frame()
        self.frame(center=(20, 40), radius=4)
        self.backend.draw_circle.assert_called_once()
        self.backend.configure_item.assert_called_once_with(10, center=(20, 40), radius=4)
        self.backend.delete_item.assert_not_called()

    def test_mutable_point_input_is_snapshotted(self):
        center = [10, 20]
        self.frame(center=center)
        center[0] = 30
        self.frame(center=center)
        self.backend.configure_item.assert_called_once_with(10, center=(30, 20))

    def test_shape_replacement_keeps_original_paint_order(self):
        self.frame()
        self.commands.index = 0
        self.commands.draw_line((0, 0), (1, 1), parent=1)
        self.commands.finish()
        self.backend.draw_line.assert_called_once_with(
            p1=(0, 0), p2=(1, 1), parent=1, before=10)
        self.backend.delete_item.assert_called_once_with(10)

    def test_removed_commands_are_deleted_once(self):
        self.commands.draw_circle((0, 0), 3)
        self.commands.draw_circle((1, 1), 3)
        self.frame(center=(0, 0))
        self.backend.delete_item.assert_called_once_with(11)
        self.assertEqual(len(self.commands.items), 1)

    def test_pan_only_changes_one_transform_not_marker_primitives(self):
        layer = RetainedCanvasLayer.__new__(RetainedCanvasLayer)
        layer.backend = self.backend
        layer.tag, layer._node = 1, 2
        layer._translation = (0, 0)
        layer.setTranslation(40, 20)
        layer.setTranslation(40, 20)
        self.backend.create_translation_matrix.assert_called_once_with((40.0, 20.0, 0.0))
        self.backend.apply_transform.assert_called_once_with(
            2, self.backend.create_translation_matrix.return_value)
        self.backend.configure_item.assert_not_called()
        self.backend.delete_item.assert_not_called()

    def test_marker_batch_reuses_primitives_and_preserves_screen_radius(self):
        self.commands.circles([(10, 20), (30, 40)], 3, color=(255, 255, 255, 235), fill=(1, 2, 3, 255))
        self.commands.finish()
        self.commands.index = 0
        self.commands.circles([(20, 40), (60, 80)], 4, color=(255, 255, 255, 235), fill=(1, 2, 3, 255))
        self.commands.finish()
        self.assertEqual(self.backend.draw_circle.call_count, 2)
        self.assertEqual(self.backend.configure_item.call_count, 2)
        self.backend.configure_item.assert_any_call(10, radius=4, center=(20, 40))
        self.backend.configure_item.assert_any_call(11, radius=4, center=(60, 80))
        self.backend.delete_item.assert_not_called()

    def test_marker_batch_and_generic_painter_share_a_consistent_cache(self):
        self.commands.circles([(10, 20)], 3, color=(1, 2, 3, 255), fill=(4, 5, 6, 255))
        self.commands.finish()
        self.commands.index = 0
        self.commands.draw_circle((10, 20), 5, segments=0, color=(1, 2, 3, 255), fill=(4, 5, 6, 255), thickness=1.0)
        self.commands.finish()
        self.commands.index = 0
        self.commands.circles([(10, 20)], 3, color=(1, 2, 3, 255), fill=(4, 5, 6, 255))
        self.commands.finish()
        self.backend.configure_item.assert_any_call(10, radius=5)
        self.backend.configure_item.assert_any_call(10, radius=3)
        self.backend.draw_circle.assert_called_once()


class ViewportPaintSchedulingTests(unittest.TestCase):
    def test_unchanged_pointer_sample_does_not_repaint_overlay(self):
        owner = SimpleNamespace(
            _middle_drag=False, _mouse_in_canvas=lambda: False,
            _canvas_rect=lambda: ((0, 0), (600, 400)),
            _fit_scale=1.0, _zoom=1.0, _pan=[0.0, 0.0],
            _edit_enabled=False, _pick_mode=None, _active_tool='axes',
            _anchor_drag_target=None, _point_press=None,
            _drag_start=None, _drag_target=None,
            engine=SimpleNamespace(image=None), _paint_pointer=Mock())
        controller = CanvasController(owner)
        with patch('WinUx.plotdigitizer.ui.controllers.canvas.QCursor.pos', return_value=QPoint(10, 20)):
            controller._mouse_move()
            controller._mouse_move()
            owner._paint_pointer.assert_called_once()
            owner._zoom = 2.0
            controller._mouse_move()
            self.assertEqual(owner._paint_pointer.call_count, 2)

    def owner(self):
        return SimpleNamespace(
            _closed=False, _auto_fit=True, _fit_scale=1.0, _zoom=1.0, _pan=[0.0, 0.0],
            engine=SimpleNamespace(image=object()), _redraw=Mock(),
            _canvas_rect=lambda: ((10, 20), (600, 400)),
            view=SimpleNamespace(_gui_runtime=SimpleNamespace(
                addBeforeRenderCallback=Mock(return_value='token'),
                removeBeforeRenderCallback=Mock())))

    def test_zoom_burst_keeps_cursor_anchor_and_paints_once(self):
        owner = self.owner()
        controller = CanvasController(owner)
        anchor = (200, 150)
        for _ in range(6):
            controller._zoom_at(1.1, mouse=(210, 170))
        scale = owner._fit_scale * owner._zoom
        self.assertAlmostEqual((200 - owner._pan[0]) / scale, anchor[0])
        self.assertAlmostEqual((150 - owner._pan[1]) / scale, anchor[1])
        owner._redraw.assert_not_called()
        register = owner.view._gui_runtime.addBeforeRenderCallback
        register.assert_called_once()
        register.call_args.args[0]()
        owner._redraw.assert_called_once()
        controller._flush_view_redraw()
        owner._redraw.assert_called_once()

    def test_closed_dialog_discards_pending_zoom_paint(self):
        owner = self.owner()
        controller = CanvasController(owner)
        controller._zoom_at(1.1)
        owner._closed = True
        controller._flush_view_redraw()
        owner._redraw.assert_not_called()
        owner.view._gui_runtime.removeBeforeRenderCallback.assert_called_once_with('token')


if __name__ == '__main__':
    unittest.main()
