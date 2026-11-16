"""M6t adaptive nested-loop idle backoff regressions."""
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


class _FakeApp:
    def __init__(self, results):
        import threading
        self._thread = threading.get_ident()
        self._quitting = False
        self._results = list(results)
        self.turns = 0

    def threadId(self):
        return self._thread

    def processEvents(self, max_events=None):
        self.turns += 1
        if self._results:
            return self._results.pop(0)
        return 0

    def processHostTurn(self):
        return False


class AdaptiveNestedIdleTests(unittest.TestCase):
    def test_idle_backoff_reaches_120hz_ceiling(self):
        from DearUIQt.core.event_loop import QEventLoop
        app = _FakeApp([0, 0, 0, 0, 0])
        loop = QEventLoop(application=app)
        sleeps = []

        def fake_sleep(value):
            sleeps.append(value)
            if len(sleeps) == 5:
                loop.quit()

        with patch("DearUIQt.core.event_loop.time.sleep", side_effect=fake_sleep):
            self.assertEqual(loop.exec(), 0)
        self.assertEqual(sleeps, [0.001, 0.002, 0.004, 0.008, 0.008])

    def test_qt_work_resets_idle_backoff(self):
        from DearUIQt.core.event_loop import QEventLoop
        app = _FakeApp([0, 0, 1, 0, 0])
        loop = QEventLoop(application=app)
        sleeps = []

        def fake_sleep(value):
            sleeps.append(value)
            if len(sleeps) == 4:
                loop.quit()

        with patch("DearUIQt.core.event_loop.time.sleep", side_effect=fake_sleep):
            self.assertEqual(loop.exec(), 0)
        self.assertEqual(sleeps, [0.001, 0.002, 0.001, 0.002])

    def test_close_during_host_pump_does_not_sleep(self):
        from DearUIQt.core.event_loop import QEventLoop
        app = _FakeApp([0])
        sleeps = []
        loop = None

        def pump():
            loop.quit()

        loop = QEventLoop(application=app, pump=pump)
        with patch("DearUIQt.core.event_loop.time.sleep", side_effect=lambda value: sleeps.append(value)):
            self.assertEqual(loop.exec(), 0)
        self.assertEqual(sleeps, [])

    def test_release_version_is_m6t(self):
        import DearUIQt
        self.assertGreaterEqual(tuple(map(int, DearUIQt.__version__.split("."))), (1, 128, 0))


if __name__ == "__main__":
    unittest.main(verbosity=2)
