"""Cancellation signals running workers and rejects their late deliveries."""
from concurrent.futures import Future, CancelledError
from pathlib import Path
import sys
from threading import Event
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from PIL import Image
from WinUx.plotdigitizer.application.tasks import SmartDetectRunner, TickCalibrationRunner
from WinUx.plotdigitizer.core.engine import DigitizerEngine
from WinUx.plotdigitizer.core.models import ExtractionSettings, SmartDetectionResult
from WinUx.plotdigitizer.core import extraction
from test_digitizer_tick_background import _detection


class ProcessCancellationTests(unittest.TestCase):
    def make_engine(self):
        engine = DigitizerEngine()
        engine.image = Image.new('RGB', (400, 300), 'white')
        engine.set_plot_rect_with_corner_anchors((40, 30, 340, 250), detect_ticks=False)
        return engine

    def test_tick_cancel_rejects_queued_progress_and_result_and_allows_restart(self):
        engine = self.make_engine()
        queued, jobs, updates, done, regions = [], [], [], [], []
        def submitter(fn, *args, **kwargs):
            future = Future()
            future.set_running_or_notify_cancel()
            jobs.append((kwargs, future))
            return future
        runner = TickCalibrationRunner(engine, queued.append, submitter=submitter)
        runner.submit(engine.plot_rect, lambda *args: done.append(args),
                      on_progress=lambda *args: updates.append(args), on_region=regions.append)
        jobs[0][0]['progress'](.5, 'old')
        jobs[0][0]['region_aligned']((38, 30, 340, 251))
        self.assertTrue(runner.cancel())
        self.assertTrue(jobs[0][0]['cancelled']())
        self.assertFalse(runner.busy)
        jobs[0][1].set_result(_detection(engine.plot_rect))
        runner.submit(engine.plot_rect, lambda *args: done.append(args))
        while queued:
            queued.pop(0)()
        self.assertEqual([], updates)
        self.assertEqual([], regions)
        self.assertEqual([], done)
        self.assertTrue(runner.busy)
        jobs[1][1].set_result(_detection(engine.plot_rect))
        queued.pop(0)()
        self.assertEqual(1, len(done))
        self.assertFalse(runner.busy)

    def test_extract_cancel_does_not_clear_busy_or_deliver_for_replacement(self):
        engine = self.make_engine()
        queued, jobs, done = [], [], []
        def submitter(fn, *args, **kwargs):
            future = Future()
            future.set_running_or_notify_cancel()
            jobs.append((kwargs, future))
            return future
        runner = SmartDetectRunner(engine, queued.append, submitter=submitter)
        runner.submit(ExtractionSettings(), 0, lambda *args: done.append(args))
        self.assertTrue(runner.cancel())
        self.assertTrue(jobs[0][0]['cancelled']())
        self.assertFalse(runner.busy)
        jobs[0][1].set_result(SmartDetectionResult())
        runner.submit(ExtractionSettings(), 0, lambda *args: done.append(args))
        queued.pop(0)()
        self.assertTrue(runner.busy)
        self.assertEqual([], done)
        self.assertFalse(jobs[1][0]['cancelled']())
        jobs[1][1].set_result(SmartDetectionResult())
        queued.pop(0)()
        self.assertEqual(1, len(done))
        self.assertFalse(runner.busy)

    def test_scalar_curve_worker_checks_cancel_between_columns(self):
        image = Image.new('RGB', (100, 100), 'white')
        cancel = Event()
        calls = []
        def matches(rgb):
            calls.append(rgb)
            cancel.set()
            return False
        with patch.object(extraction, 'np', None), \
                patch.object(extraction, '_color_matcher', return_value=matches):
            with self.assertRaises(CancelledError):
                extraction.extract_curve(image, (0, 0, 99, 99), (255, 0, 0),
                                         ExtractionSettings(), cancelled=cancel.is_set)
        self.assertEqual(100, len(calls))

    def test_cancelled_engine_does_not_start_detection_or_swallow_cancel(self):
        engine = self.make_engine()
        with patch('WinUx.plotdigitizer.core.engine.detect_plot_area',
                   side_effect=AssertionError('detection started')):
            with self.assertRaises(CancelledError):
                engine.compute_smart_detect(cancelled=lambda: True)
        for detect in (extraction.detect_plot_area,
                       lambda image, **kwargs: extraction.detect_curve_colors(image, (0, 0, 99, 99), **kwargs)):
            with self.assertRaises(CancelledError):
                detect(engine.image, cancelled=lambda: True)


if __name__ == '__main__':
    unittest.main()
