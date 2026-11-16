"""M4t contracts: feature workers use QThread/QThreadPool rather than ad-hoc threads."""
from pathlib import Path
import unittest

from DearUIQt import __version__

ROOT = Path(__file__).resolve().parents[1]


class QtOwnedFeatureWorkerTests(unittest.TestCase):
    def source(self, rel):
        return (ROOT / rel).read_text(encoding="utf-8")

    def test_version(self):
        parts = tuple(int(value) for value in __version__.split(".")[:3])
        self.assertGreaterEqual(parts, (1, 76, 0))

    def test_job_plot_uses_qthread_worker_object(self):
        source = self.source("WinUx/controllers/jobs/plot.py")
        self.assertIn("class _JobPlotWorker(QObject)", source)
        self.assertIn("QThread(", source)
        self.assertIn("worker.moveToThread(thread)", source)
        self.assertIn("thread.requestInterruption()", source)
        self.assertNotIn("thread = threading.Thread(\n            target=self.watch_loop", source)

    def test_odb_probe_races_use_shared_qthreadpool(self):
        for rel in ("WinUx/services/odb/check.py", "WinUx/services/odb/remote.py"):
            source = self.source(rel)
            self.assertIn("QThreadPool.globalInstance()", source)
            self.assertIn("future.waitForFinished()", source)
            self.assertNotIn("thread = threading.Thread(", source)

    def test_server_notepad_short_jobs_use_shared_pool(self):
        for rel in ("WinUx/services/server_notepad/background.py",
                    "WinUx/services/server_notepad/save.py"):
            source = self.source(rel)
            self.assertIn("QThreadPool.globalInstance().start(worker)", source)
            self.assertNotIn("threading.Thread(", source)


if __name__ == "__main__":
    unittest.main()
