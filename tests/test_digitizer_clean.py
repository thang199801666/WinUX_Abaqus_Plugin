"""Clean-project/markers scope, Undo and warning-dialog transactions."""
import sys
from pathlib import Path
import unittest
from unittest.mock import Mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from PIL import Image
from WinUx.plotdigitizer.core import DigitizerEngine
from WinUx.plotdigitizer.core.models import DataPoint
from WinUx.plotdigitizer.ui.dialog import PlotDigitizerDialog


class CleanTests(unittest.TestCase):
    def engine(self):
        engine = DigitizerEngine()
        engine.apply_image(Image.new('RGB', (200, 200), 'white'), 'chart.png')
        engine.set_plot_rect_with_corner_anchors((10, 10, 190, 190), detect_ticks=False)
        engine.active_dataset.manual_points.append(DataPoint(40, 50))
        engine.active_dataset.extracted_pixels = [(50, 60), (60, 70)]
        engine.active_dataset.locked = True
        engine.recompute_all_data()
        return engine

    def test_clean_markers_keeps_image_settings_and_supports_undo_redo(self):
        engine = self.engine()
        before, image, path = engine._snapshot(), engine.image, engine.image_path
        engine.clean_markers()
        self.assertIs(image, engine.image)
        self.assertEqual(path, engine.image_path)
        self.assertTrue(engine.active_dataset.locked)
        self.assertFalse(engine.active_dataset.manual_points)
        self.assertFalse(engine.active_dataset.extracted_pixels)
        self.assertIsNone(engine.plot_rect)
        self.assertFalse(engine.calibration.ready())
        self.assertFalse(engine.auto_tick_verified_axes)
        self.assertTrue(engine.undo())
        self.assertEqual(before, engine._snapshot())
        self.assertTrue(engine.redo())
        self.assertFalse(engine.active_dataset.manual_points)

    def test_clean_project_removes_image_and_history(self):
        engine = self.engine()
        engine.project_view_state = {'zoom': 2}
        revision = engine.revision
        engine.clean_project()
        self.assertIsNone(engine.image)
        self.assertIsNone(engine.image_path)
        self.assertIsNone(engine.plot_rect)
        self.assertEqual(1, len(engine.datasets))
        self.assertFalse(engine.active_dataset.locked)
        self.assertFalse(engine.can_undo)
        self.assertFalse(engine.can_redo)
        self.assertFalse(engine.project_view_state)
        self.assertGreater(engine.revision, revision)

    def test_clean_empty_markers_invalidates_inflight_workers(self):
        engine = DigitizerEngine()
        before = engine.revision
        engine.clean_markers()
        self.assertGreater(engine.revision, before)

    def dialog(self):
        dialog = object.__new__(PlotDigitizerDialog)
        dialog.engine = self.engine()
        dialog._closed = False
        dialog.view = Mock()
        dialog._project_path = 'saved.pdg'
        dialog._image_load_generation = dialog._project_load_generation = 0
        dialog._image_load_future = Mock()
        dialog._texture_tag = Mock()
        dialog._cancel_pick = Mock()
        dialog._refresh_all = Mock()
        dialog._set_status = Mock()
        return dialog

    def test_cancel_is_noop_and_warning_is_owned_by_digitizer(self):
        dialog = self.dialog()
        before = dialog.engine._snapshot()
        dialog._request_clean('markers')
        args, kwargs = dialog.view.confirm_action_async.call_args
        self.assertEqual('warning', kwargs['intent'])
        self.assertIs(dialog, kwargs['parent'])
        self.assertEqual('Cancel', kwargs['secondary_text'])
        args[2](False)
        self.assertEqual(before, dialog.engine._snapshot())
        self.assertFalse(dialog._image_load_future.cancel.called)
        self.assertFalse(dialog._texture_tag.delete.called)

    def test_clean_markers_waits_for_confirmation_and_keeps_project_path(self):
        dialog = self.dialog()
        image = dialog.engine.image
        dialog._request_clean('markers')
        self.assertTrue(dialog.engine.active_dataset.manual_points)
        dialog._request_clean('markers')
        self.assertEqual(1, dialog.view.confirm_action_async.call_count)
        dialog.view.confirm_action_async.call_args.args[2](True)
        self.assertIs(image, dialog.engine.image)
        self.assertEqual('saved.pdg', dialog._project_path)
        self.assertFalse(dialog.engine.active_dataset.manual_points)
        self.assertIsNone(dialog._display_axis_ticks)
        dialog._image_load_future.cancel.assert_called_once()
        self.assertFalse(dialog._texture_tag.delete.called)

    def test_confirm_project_clears_save_path_and_texture(self):
        dialog = self.dialog()
        texture = dialog._texture_tag
        dialog._request_clean('project')
        dialog.view.confirm_action_async.call_args.args[2](True)
        self.assertIsNone(dialog._project_path)
        self.assertIsNone(dialog.engine.image)
        self.assertIsNone(dialog._texture_tag)
        texture.delete.assert_called_once()


if __name__ == '__main__':
    unittest.main()
