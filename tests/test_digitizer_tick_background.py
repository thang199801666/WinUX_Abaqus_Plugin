import os
import sys
import unittest
from concurrent.futures import Future, CancelledError, ThreadPoolExecutor
from threading import Event
from unittest.mock import patch

from PIL import Image

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from WinUx.plotdigitizer.application.tasks import TickCalibrationRunner
from WinUx.plotdigitizer.core.engine import DigitizerEngine
from WinUx.plotdigitizer.core.tick_detection import (
    AxisTickDetection, TickCalibrationDetection, TickReading,
)
from WinUx.plotdigitizer.core.models import AxisScale
from WinUx.plotdigitizer.core import tick_detection as td
from test_digitizer_tick_auto_calibration import make_chart


def _detection(rect):
    left, top, right, bottom = rect
    x = AxisTickDetection("x", (
        TickReading(left, 0.0, "0", .9, (0, 0, 1, 1)),
        TickReading(right, 3.2, "3.2", .9, (0, 0, 1, 1)),
    ), .9, AxisScale.LINEAR)
    y = AxisTickDetection("y", (
        TickReading(top, 2000.0, "2000", .9, (0, 0, 1, 1)),
        TickReading(bottom, 0.0, "0", .9, (0, 0, 1, 1)),
    ), .9, AxisScale.LINEAR)
    return TickCalibrationDetection(x, y)


class TickBackgroundCalibrationTests(unittest.TestCase):
    def test_submit_failure_does_not_leave_runner_busy(self):
        engine = DigitizerEngine()
        engine.image = Image.new('RGB', (400, 300), 'white')
        rect = (40, 30, 340, 250)
        engine.set_plot_rect_with_corner_anchors(rect, detect_ticks=False)
        def submitter(*args, **kwargs):
            raise RuntimeError('closed executor')
        runner = TickCalibrationRunner(engine, lambda fn: None, submitter=submitter)
        with self.assertRaisesRegex(RuntimeError, 'closed executor'):
            runner.submit(rect, lambda *args: None, on_progress=lambda *args: None)
        self.assertFalse(runner.busy)
        self.assertTrue(runner._cancel_event.is_set())

    def test_progress_is_monotonic_and_does_not_change_readings(self):
        image, rect = make_chart()
        expected = td.detect_calibration_ticks(image, rect)
        updates = []
        result = td.detect_calibration_ticks(image, rect, progress=lambda *args: updates.append(args))
        self.assertEqual(expected, result)
        values = [value for value, _ in updates]
        self.assertEqual(0, values[0])
        self.assertEqual(1, values[-1])
        self.assertEqual(sorted(values), values)
        self.assertTrue(any('X labels:' in text for _, text in updates))
        self.assertTrue(any('Y labels:' in text for _, text in updates))

    def test_retry_progress_stays_below_completion_and_cancel_never_reports_done(self):
        image = Image.new('RGB', (200, 200), 'white')
        rect = (10, 10, 190, 190)
        empty = AxisTickDetection('y', (), 0, AxisScale.LINEAR)
        updates = []
        def retry(*args, progress=None, **kwargs):
            progress(0, 'retry start')
            progress(.5, 'retry word')
            progress(1, 'retry end')
            return empty
        with patch.object(td, '_detect_axis', return_value=empty), \
                patch.object(td, '_retry_small_y_labels', side_effect=retry):
            td.detect_calibration_ticks(image, rect, progress=lambda *args: updates.append(args))
        self.assertEqual(sorted(v for v, _ in updates), [v for v, _ in updates])
        self.assertLess(next(v for v, label in updates if label == 'retry end'), 1)
        self.assertEqual(1, updates[-1][0])
        cancel = Event()
        updates.clear()
        def progress(value, message):
            updates.append(value)
            cancel.set()
        with self.assertRaises(CancelledError):
            td.detect_calibration_ticks(image, rect, cancelled=cancel.is_set, progress=progress)
        self.assertNotIn(1, updates)

    def test_progress_coalesces_and_ignores_superseded_closed_and_finished_jobs(self):
        engine = DigitizerEngine()
        engine.image = Image.new('RGB', (400, 300), 'white')
        rect = (40, 30, 340, 250)
        engine.set_plot_rect_with_corner_anchors(rect, detect_ticks=False)
        jobs, queued, updates = [], [], []
        def submitter(fn, *args, **kwargs):
            future = Future()
            future.set_running_or_notify_cancel()
            jobs.append((kwargs['progress'], future))
            return future
        runner = TickCalibrationRunner(engine, queued.append, submitter=submitter)
        runner.submit(rect, lambda *args: None, on_progress=lambda *args: updates.append(args))
        for i in range(100):
            jobs[0][0](i / 100, str(i))
        self.assertEqual(1, len(queued))
        self.assertEqual([], updates)  # No callbacks run on the worker.
        queued.pop(0)()
        self.assertEqual([(.99, '99')], updates)
        jobs[0][0](1, 'old')
        runner.submit(rect, lambda *args: None, on_progress=lambda *args: updates.append(args))
        queued.pop(0)()
        self.assertEqual(1, len(updates))
        jobs[1][0](.5, 'new')
        queued.pop(0)()
        self.assertEqual((.5, 'new'), updates[-1])
        jobs[1][1].set_result(_detection(rect))
        queued.pop(0)()
        jobs[1][0](.9, 'late')
        queued.pop(0)()
        self.assertEqual((.5, 'new'), updates[-1])
        runner.submit(rect, lambda *args: None, on_progress=lambda *args: updates.append(args))
        jobs[2][0](.1, 'closed')
        runner.close()
        queued.pop(0)()
        self.assertEqual((.5, 'new'), updates[-1])

    def test_cancelled_detector_does_not_start_geometry_or_ocr(self):
        with patch.object(td, '_line_peak_candidates', side_effect=AssertionError('work started')):
            with self.assertRaises(CancelledError):
                td.detect_calibration_ticks(Image.new('RGB', (200, 200)), (10, 10, 190, 190),
                                            cancelled=lambda: True)

    def test_running_detector_stops_between_words(self):
        image, rect = make_chart()
        cancel = Event()
        def read(mask):
            cancel.set()
            return ('0', 0, .9)
        with patch.object(td, '_read_independent_word', side_effect=read) as ocr:
            with self.assertRaises(CancelledError):
                td._detect_axis(image, rect, 'x', AxisScale.LINEAR, cancelled=cancel.is_set)
        self.assertEqual(1, ocr.call_count)

    def test_cancelled_after_x_does_not_start_y(self):
        cancel = Event()
        def detect(image, rect, axis, scale, **kwargs):
            cancel.set()
            return _detection(rect).x
        with patch.object(td, '_detect_axis', side_effect=detect) as detect_axis:
            with self.assertRaises(CancelledError):
                td.detect_calibration_ticks(Image.new('RGB', (200, 200)), (10, 10, 190, 190),
                                            cancelled=cancel.is_set)
        self.assertEqual(1, detect_axis.call_count)

    def test_new_box_cancels_running_old_box_not_just_its_delivery(self):
        engine = DigitizerEngine()
        engine.image = Image.new('RGB', (400, 300), 'white')
        rect = (40, 30, 340, 250)
        engine.set_plot_rect_with_corner_anchors(rect, detect_ticks=False)
        jobs, queued, delivered = [], [], []
        def submitter(fn, *args, **kwargs):
            future = Future()
            future.set_running_or_notify_cancel()
            jobs.append((fn, args, kwargs, future))
            return future
        runner = TickCalibrationRunner(engine, queued.append, submitter=submitter)
        runner.submit(rect, lambda *args: delivered.append(args))
        self.assertFalse(jobs[0][2]['cancelled']())
        runner.submit(rect, lambda *args: delivered.append(args))
        self.assertTrue(jobs[0][2]['cancelled']())
        self.assertFalse(jobs[1][2]['cancelled']())
        fn, args, kwargs, old = jobs[0]
        with self.assertRaises(CancelledError):
            fn(*args, **kwargs)
        old.set_exception(CancelledError())
        jobs[1][3].set_result(_detection(rect))
        while queued:
            queued.pop(0)()
        self.assertEqual(1, len(delivered))
        self.assertTrue(delivered[0][0].ready)
        self.assertFalse(runner.busy)

    def test_clean_and_close_signal_running_work_to_stop(self):
        engine = DigitizerEngine()
        engine.image = Image.new('RGB', (400, 300), 'white')
        rect = (40, 30, 340, 250)
        engine.set_plot_rect_with_corner_anchors(rect, detect_ticks=False)
        callbacks = []
        def submitter(fn, *args, **kwargs):
            future = Future()
            future.set_running_or_notify_cancel()
            callbacks.append(kwargs['cancelled'])
            return future
        runner = TickCalibrationRunner(engine, lambda f: None, submitter=submitter)
        runner.submit(rect, lambda *args: None)
        engine.clean_markers()
        self.assertTrue(callbacks[0]())
        engine.set_plot_rect_with_corner_anchors(rect, detect_ticks=False)
        runner.submit(rect, lambda *args: None)
        self.assertFalse(callbacks[1]())
        runner.close()
        self.assertTrue(callbacks[1]())
        self.assertFalse(runner.busy)

    def test_superseded_job_releases_single_worker_for_latest_box(self):
        engine = DigitizerEngine()
        engine.image = Image.new('RGB', (400, 300), 'white')
        rect = (40, 30, 340, 250)
        engine.set_plot_rect_with_corner_anchors(rect, detect_ticks=False)
        started, release = Event(), Event()
        calls, finished, queued, delivered = [], [], [], []
        def detect(image, box, *scales, cancelled=None, align_axes=False):
            calls.append(box)
            if len(calls) == 1:
                started.set()
                if not release.wait(5):
                    raise TimeoutError('Test worker was not released.')
            td._check_tick_cancelled(cancelled)
            finished.append(box)
            return _detection(box)
        with ThreadPoolExecutor(max_workers=1) as pool, \
             patch('WinUx.plotdigitizer.application.tasks.detect_calibration_ticks', side_effect=detect):
            runner = TickCalibrationRunner(engine, queued.append, submitter=pool.submit)
            try:
                runner.submit(rect, lambda *args: delivered.append(args))
                self.assertTrue(started.wait(3))
                old = runner._future
                runner.submit(rect, lambda *args: delivered.append(args))
            finally:
                release.set()
            with self.assertRaises(CancelledError):
                old.result(timeout=3)
            self.assertTrue(runner._future.result(timeout=3).ready)
        while queued:
            queued.pop(0)()
        self.assertEqual([rect], finished)
        self.assertEqual(1, len(delivered))
        self.assertFalse(runner.busy)

    def test_box_can_commit_without_running_tick_ocr(self):
        engine = DigitizerEngine()
        engine.image = Image.new("RGB", (400, 300), "white")
        result = engine.set_plot_rect_with_corner_anchors(
            (40, 30, 340, 250), detect_ticks=False)
        self.assertIsNone(result)
        self.assertEqual((40, 30, 340, 250), engine.plot_rect)
        self.assertEqual(0.0, engine.calibration.x1.value)
        self.assertEqual(1.0, engine.calibration.x2.value)
        self.assertEqual(0.0, engine.calibration.y1.value)
        self.assertEqual(1.0, engine.calibration.y2.value)

    def test_background_detection_can_be_applied_after_box_commit(self):
        engine = DigitizerEngine()
        engine.image = Image.new("RGB", (400, 300), "white")
        rect = (40, 30, 340, 250)
        engine.set_plot_rect_with_corner_anchors(rect, detect_ticks=False)
        self.assertTrue(engine.apply_tick_calibration_detection(
            _detection(rect), expected_rect=rect))
        self.assertAlmostEqual(0.0, engine.calibration.x1.value)
        self.assertAlmostEqual(3.2, engine.calibration.x2.value)
        self.assertAlmostEqual(0.0, engine.calibration.y1.value)
        self.assertAlmostEqual(2000.0, engine.calibration.y2.value)

    def test_runner_dispatches_completed_detection_without_mutating_worker_state(self):
        engine = DigitizerEngine()
        engine.image = Image.new("RGB", (400, 300), "white")
        rect = (40, 30, 340, 250)
        engine.set_plot_rect_with_corner_anchors(rect, detect_ticks=False)
        delivered = []
        queued = []

        def submitter(fn, *args, **kwargs):
            future = Future()
            future.set_result(_detection(rect))
            return future

        runner = TickCalibrationRunner(engine, queued.append, submitter=submitter)
        self.assertTrue(runner.submit(rect, lambda *args: delivered.append(args)))
        self.assertTrue(runner.busy)
        self.assertEqual(1, len(queued))
        queued.pop(0)()
        self.assertFalse(runner.busy)
        self.assertEqual(1, len(delivered))
        detection, returned_rect, error = delivered[0]
        self.assertIsNone(error)
        self.assertEqual(rect, returned_rect)
        self.assertTrue(detection.ready)


if __name__ == "__main__":
    unittest.main()
