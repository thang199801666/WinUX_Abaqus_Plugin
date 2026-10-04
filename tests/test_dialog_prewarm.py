"""Measure cold/warm prompt latency and validate one-shot worker ownership."""
import os
import time
import unittest
from unittest.mock import patch
from pathlib import PurePosixPath

import test_all_floating_dialogs as support
from WinUx import dialogs
from WinUx.dialogs.prewarm_pool import DialogPrewarmPool
from WinUx.platform.floating_viewport import centered_position, window_rect, work_area


@unittest.skipUnless(os.name == "nt", "DPG worker prewarming requires Windows")
class DialogPrewarmTests(unittest.TestCase):
    def setUp(self):
        support.AllFloatingIntegrationTests.setUp(self)

    def tearDown(self):
        support.AllFloatingIntegrationTests.tearDown(self)

    tick = support.AllFloatingIntegrationTests.tick
    wait_for = support.AllFloatingIntegrationTests.wait_for
    create = support.AllFloatingIntegrationTests.create

    def prepare_pool(self):
        self.view._dialog_prewarm_pool = DialogPrewarmPool(capacity=2)
        self.wait_for(lambda: sum(worker.ready.is_set() and not worker.closed
            for worker in self.view._dialog_prewarm_pool._workers) == 2)

    def test_exit_warning_uses_ready_worker_and_is_faster_than_cold_start(self):
        cold = self.create(lambda: dialogs.BlockingDialog(self.view, "Confirm Close App", "Exit WinUx?", kind="confirm"))
        cold_ms = cold._open_elapsed_ms
        cold.destroy()
        self.wait_for(lambda: cold._process.poll() is not None, timeout=8)
        self.prepare_pool()
        received = []
        warm = self.create(lambda: dialogs.BlockingDialog(self.view, "Confirm Close App", "Exit WinUx?", kind="confirm", on_result=received.append))
        self.assertTrue(warm._from_prewarm)
        print("\nExit-warning click-to-ready: cold={:.1f}ms warm={:.1f}ms".format(cold_ms, warm._open_elapsed_ms))
        self.assertLess(warm._open_elapsed_ms, cold_ms * .7)
        self.assertLess(warm._open_elapsed_ms, 500)
        published = next(event for event in warm._startup_layout if event["stage"] == "published")
        left, top, right, bottom = published["rect"]
        self.assertEqual((left, top), centered_position(window_rect(self.owner), (right-left, bottom-top), work_area(self.owner)))
        self.user32.PostMessageW(warm._hwnd, 0x0010, 0, 0)
        self.wait_for(lambda: received == [False])
        self.assertTrue(self.user32.IsWindowEnabled(self.owner))

    def test_workers_are_usable_for_different_dialog_types_and_replenished(self):
        self.prepare_pool()
        job = self.create(lambda: dialogs.JobManagerDialog(self.view, [PurePosixPath("/scratch/job.inp")], lambda *a: None, lambda *a: None))
        bookmarks = self.create(lambda: dialogs.BookmarksDialog(self.view, [], lambda *a: None, lambda *a: None, lambda *a: None))
        self.assertTrue(job._from_prewarm)
        self.assertTrue(bookmarks._from_prewarm)
        self.assertNotEqual(job._process.pid, bookmarks._process.pid)
        job.destroy()
        bookmarks.destroy()
        self.wait_for(lambda: sum(worker.ready.is_set() and not worker.closed
            for worker in self.view._dialog_prewarm_pool._workers) == 2)

    def test_pool_claim_never_waits_on_preparation_lock_and_close_retires_idle_workers(self):
        self.prepare_pool()
        pool = self.view._dialog_prewarm_pool
        workers = list(pool._workers)
        pool._lock.acquire()
        try:
            started = time.perf_counter()
            self.assertIsNone(pool.claim())
            self.assertLess(time.perf_counter()-started, .05)
        finally:
            pool._lock.release()
        pool.close()
        self.wait_for(lambda: all(worker.process.poll() is not None for worker in workers), timeout=8)
        self.assertIsNone(pool.claim())


if __name__ == "__main__":
    unittest.main()
