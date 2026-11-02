"""Axis geometry is aligned before OCR, without guessing any tick values."""
from concurrent.futures import CancelledError, Future
from dataclasses import replace
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from PIL import Image, ImageDraw
from WinUx.plotdigitizer.core.region_detection import align_region_to_axes
from WinUx.plotdigitizer.core import tick_detection as td
from WinUx.plotdigitizer.core.engine import DigitizerEngine
from WinUx.plotdigitizer.core.calibration import Calibration
from WinUx.plotdigitizer.application.tasks import TickCalibrationRunner
from test_digitizer_tick_background import _detection


class RegionAlignmentTests(unittest.TestCase):
    selected = (89, 40, 300, 248)
    aligned = (80, 40, 300, 240)

    def image(self, color=(100, 100, 100), background='white', horizontal=True):
        image = Image.new('RGB', (400, 300), background)
        draw = ImageDraw.Draw(image)
        draw.line((80, 40, 80, 240), fill=color, width=2)
        if horizontal:
            draw.line((80, 240, 300, 240), fill=color, width=2)
        return image

    def test_snaps_axis_edges_and_preserves_top_and_right(self):
        self.assertEqual(self.aligned, align_region_to_axes(self.image(), self.selected))

    def test_thick_axis_snaps_to_stroke_centre(self):
        image = Image.new('RGB', (400, 300), 'white')
        draw = ImageDraw.Draw(image)
        draw.line((80, 40, 80, 240), fill=(90, 90, 90), width=5)
        draw.line((80, 240, 300, 240), fill=(90, 90, 90), width=5)
        self.assertEqual(self.aligned, align_region_to_axes(image, self.selected))

    def test_single_confident_axis_moves_only_its_corresponding_edge(self):
        self.assertEqual((80, 40, 300, 248), align_region_to_axes(self.image(horizontal=False), self.selected))

    def test_white_axes_on_dark_background_are_supported(self):
        self.assertEqual(self.aligned, align_region_to_axes(self.image('white', 'black'), self.selected))

    def test_blank_faint_grid_and_colored_curve_do_not_move_edges(self):
        for image in (Image.new('RGB', (400, 300), 'white'), self.image((230, 230, 230)),
                      self.image((200, 0, 0))):
            with self.subTest(image=image):
                self.assertEqual(self.selected, align_region_to_axes(image, self.selected))

    def test_ambiguous_frame_lines_do_not_steal_axes(self):
        image = self.image()
        ImageDraw.Draw(image).rectangle((70, 28, 320, 250), outline='black', width=2)
        selected = (85, 40, 300, 245)
        self.assertEqual(selected, align_region_to_axes(image, selected))

    def test_distant_axes_and_tiny_regions_are_left_unchanged(self):
        for selected in ((115, 40, 300, 275), (80, 235, 90, 245)):
            self.assertEqual(selected, align_region_to_axes(self.image(), selected))

    def test_cancelled_alignment_does_not_load_pixels(self):
        image = self.image()
        with patch.object(Image.Image, 'load', side_effect=AssertionError('pixel scan started')):
            with self.assertRaises(CancelledError):
                align_region_to_axes(image, self.selected, cancelled=lambda: True)

    def test_ocr_receives_aligned_rectangle_not_the_rough_selection(self):
        calls, progress = [], []
        def detect(image, rect, axis, scale, **kwargs):
            calls.append(rect)
            return getattr(_detection(rect), axis)
        with patch.object(td, '_detect_axis', side_effect=detect):
            result = td.detect_calibration_ticks(self.image(), self.selected, align_axes=True,
                                                 progress=lambda value, text: progress.append((value, text)))
        self.assertEqual([self.aligned, self.aligned], calls)
        self.assertEqual(self.aligned, result.aligned_rect)
        self.assertIn('Aligning region', progress[0][1])
        self.assertEqual(sorted(v for v, _ in progress), [v for v, _ in progress])

    def test_snapping_disabled_skips_alignment_and_keeps_exact_ocr_rectangle(self):
        calls, previews = [], []
        def detect(image, rect, axis, scale, **kwargs):
            calls.append(rect)
            return getattr(_detection(rect), axis)
        with patch.object(td, 'align_region_to_axes', side_effect=AssertionError('unexpected snap')), \
                patch.object(td, '_detect_axis', side_effect=detect):
            result = td.detect_calibration_ticks(self.image(), self.selected, align_axes=False,
                                                 region_aligned=previews.append)
        self.assertEqual([self.selected, self.selected], calls)
        self.assertIsNone(result.aligned_rect)
        self.assertEqual([], previews)

    def test_disabled_snapping_also_prevents_nearby_zero_from_moving_corners(self):
        engine = DigitizerEngine()
        engine.image = self.image()
        selected = (83, 40, 300, 243)  # Within the separate zero-origin snap tolerance.
        engine.set_axis_snapping(False)
        engine.set_plot_rect_with_corner_anchors(selected, detect_ticks=False)
        result = replace(_detection(self.aligned), aligned_rect=self.aligned)
        self.assertTrue(engine.apply_tick_calibration_detection(result, expected_rect=selected))
        self.assertEqual(selected, engine.plot_rect)
        self.assertEqual(selected, engine.calibration.box_rect)
        self.assertEqual((83, 243), (engine.calibration.x1.px, engine.calibration.x1.py))
        self.assertEqual((83, 243), (engine.calibration.y1.px, engine.calibration.y1.py))
        self.assertEqual(80, engine.calibration.points_x[0].px)  # Measured ticks stay untouched.
        self.assertFalse(engine.calibration.snap_to_axes)
        engine.undo()
        self.assertEqual(selected, engine.plot_rect)
        engine.redo()
        self.assertEqual(selected, engine.plot_rect)

    def test_runner_honours_policy_and_invalidates_a_job_when_it_changes(self):
        engine = DigitizerEngine()
        engine.image = self.image()
        engine.set_plot_rect_with_corner_anchors(self.selected, detect_ticks=False)
        jobs, queued, done = [], [], []
        def submitter(fn, *args, **kwargs):
            future = Future()
            future.set_running_or_notify_cancel()
            jobs.append((kwargs, future))
            return future
        runner = TickCalibrationRunner(engine, queued.append, submitter=submitter)
        runner.submit(self.selected, lambda *args: done.append(args))
        self.assertTrue(jobs[-1][0]['align_axes'])
        engine.set_axis_snapping(False)
        self.assertTrue(jobs[0][0]['cancelled']())
        runner.submit(self.selected, lambda *args: done.append(args))
        self.assertFalse(jobs[-1][0]['align_axes'])
        jobs[0][1].set_result(replace(_detection(self.aligned), aligned_rect=self.aligned))
        jobs[1][1].set_result(_detection(self.selected))
        while queued:
            queued.pop(0)()
        self.assertEqual(1, len(done))
        self.assertIsNone(done[0][2])

    def test_snap_policy_round_trip_legacy_default_and_reset(self):
        self.assertTrue(Calibration.from_dict({}).snap_to_axes)
        cal = Calibration(snap_to_axes=False)
        self.assertFalse(Calibration.from_dict(cal.to_dict()).snap_to_axes)
        with self.assertRaises(ValueError):
            Calibration(snap_to_axes='false').validate()
        engine = DigitizerEngine()
        engine.set_axis_snapping(False)
        engine.apply_image(self.image(), 'snap.png')
        self.assertFalse(engine.calibration.snap_to_axes)
        engine.reset_calibration()
        self.assertFalse(engine.calibration.snap_to_axes)
        engine.clean_markers()
        self.assertFalse(engine.calibration.snap_to_axes)
        engine.clean_project()
        self.assertTrue(engine.calibration.snap_to_axes)

    def test_engine_applies_geometry_and_ticks_together_with_undo(self):
        engine = DigitizerEngine()
        engine.image = self.image()
        engine.set_plot_rect_with_corner_anchors(self.selected, detect_ticks=False)
        result = replace(_detection(self.aligned), aligned_rect=self.aligned)
        self.assertTrue(engine.apply_tick_calibration_detection(result, expected_rect=self.selected))
        self.assertEqual(self.aligned, engine.plot_rect)
        self.assertTrue(all(p.px == 80 for p in engine.calibration.points_y))
        self.assertTrue(all(p.py == 240 for p in engine.calibration.points_x))
        engine.undo()
        self.assertEqual(self.selected, engine.plot_rect)
        engine.redo()
        self.assertEqual(self.aligned, engine.plot_rect)

    def test_stale_result_cannot_move_new_selection(self):
        engine = DigitizerEngine()
        engine.image = self.image()
        other = (120, 50, 300, 260)
        engine.set_plot_rect_with_corner_anchors(other, detect_ticks=False)
        result = replace(_detection(self.aligned), aligned_rect=self.aligned)
        self.assertFalse(engine.apply_tick_calibration_detection(result, expected_rect=self.selected))
        self.assertEqual(other, engine.plot_rect)

    def test_aligned_geometry_is_kept_even_when_all_tick_text_is_unreadable(self):
        engine = DigitizerEngine()
        engine.image = self.image()
        engine.set_plot_rect_with_corner_anchors(self.selected, detect_ticks=False)
        result = _detection(self.aligned)
        result = replace(result, x=replace(result.x, ticks=()), y=replace(result.y, ticks=()), aligned_rect=self.aligned)
        self.assertTrue(engine.apply_tick_calibration_detection(result, expected_rect=self.selected))
        self.assertEqual(self.aligned, engine.plot_rect)
        self.assertFalse(engine.auto_tick_verified_axes)
        self.assertEqual([], engine.calibration.points_x)
        self.assertEqual([], engine.calibration.points_y)


if __name__ == '__main__':
    unittest.main()
