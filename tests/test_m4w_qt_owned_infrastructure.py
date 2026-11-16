from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class QtOwnedInfrastructureTests(unittest.TestCase):
    def _source(self, relative):
        return (ROOT / relative).read_text(encoding="utf-8")

    def test_hang_watchdog_uses_qthread_worker(self):
        source = self._source("WinUx/runtime/hang_watchdog.py")
        self.assertIn("QThread(name=\"winux-ui-watchdog\"", source)
        self.assertIn("worker.moveToThread(thread)", source)
        self.assertIn("requestInterruption()", source)
        self.assertNotIn("threading.Thread(", source)

    def test_native_tk_host_uses_one_qthread_worker(self):
        source = self._source("WinUx/ui/native/native_dialog_host.py")
        self.assertIn("QThread(name=\"winux-native-ui\"", source)
        self.assertIn("worker.moveToThread(thread)", source)
        self.assertIn("class _NativeTkHostWorker(QObject)", source)
        self.assertNotIn("threading.Thread(", source)

    def test_m4w_minimum_version(self):
        source = self._source("DearUIQt/__init__.py")
        import re
        match = re.search(r'__version__ = "(\d+)\.(\d+)\.(\d+)"', source)
        self.assertIsNotNone(match)
        self.assertGreaterEqual(tuple(map(int, match.groups())), (1, 79, 0))


if __name__ == "__main__":
    unittest.main()
