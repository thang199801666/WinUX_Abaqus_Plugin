import importlib
import time
import unittest
from pathlib import Path

from DearUIQt import QFuture


ROOT = Path(__file__).resolve().parents[1]


class QtOwnedComputePoolsM4vTests(unittest.TestCase):
    def test_plot_digitizer_default_pool_is_dearuiqt_owned(self):
        source = (ROOT / "WinUx/plotdigitizer/application/tasks.py").read_text(encoding="utf-8")
        self.assertIn("from DearUIQt import QThreadPool", source)
        self.assertIn("_SHARED_SMART_DETECT_POOL = QThreadPool(", source)
        self.assertNotIn("ThreadPoolExecutor", source)

        tasks = importlib.import_module("WinUx.plotdigitizer.application.tasks")
        pool = tasks._SHARED_SMART_DETECT_POOL
        future = pool.start(lambda: 17)
        self.assertIsInstance(future, QFuture)
        self.assertEqual(future.result(2.0), 17)
        self.assertLessEqual(pool.threadCount(), pool.maxThreadCount())

    def test_odb_upgrade_uses_dedicated_qthreadpool_and_preserves_order(self):
        source = (ROOT / "WinUx/services/odb/upgrade.py").read_text(encoding="utf-8")
        self.assertIn("from DearUIQt import QThreadPool", source)
        self.assertIn('name="winux-odb-upgrade"', source)
        self.assertNotIn("ThreadPoolExecutor", source)
        self.assertNotIn("as_completed", source)

        from WinUx.services.odb.upgrade import run_parallel_odb_upgrades

        running = 0
        peak = 0
        def run_one(path):
            nonlocal running, peak
            running += 1
            peak = max(peak, running)
            try:
                # Reverse completion order to prove result order is independent
                # of worker completion order.
                time.sleep({"a.odb": .06, "b.odb": .03, "c.odb": .01}[path])
                return {"results": [{"path": path, "status": "upgraded"}]}
            finally:
                running -= 1

        payload = run_parallel_odb_upgrades(
            ["a.odb", "b.odb", "c.odb"], run_one, max_workers=2)
        self.assertEqual([row["path"] for row in payload["results"]],
                         ["a.odb", "b.odb", "c.odb"])
        self.assertEqual(payload["workerCount"], 2)
        self.assertGreaterEqual(peak, 2)
        self.assertLessEqual(peak, 2)

    def test_odb_upgrade_keeps_per_file_failure_isolation(self):
        from WinUx.services.odb.upgrade import run_parallel_odb_upgrades

        def run_one(path):
            if path == "bad.odb":
                raise RuntimeError("simulated failure")
            return {"results": [{"path": path, "status": "upgraded"}]}

        payload = run_parallel_odb_upgrades(
            ["one.odb", "bad.odb", "two.odb"], run_one, max_workers=3)
        self.assertEqual(payload["results"][0]["status"], "upgraded")
        self.assertEqual(payload["results"][1]["status"], "error")
        self.assertIn("simulated failure", payload["results"][1]["error"])
        self.assertEqual(payload["results"][2]["status"], "upgraded")


if __name__ == "__main__":
    unittest.main()
