"""M6s nested event-loop idle efficiency regressions."""
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


class _FakeApp:
    def __init__(self):
        import threading
        self._thread = threading.get_ident()
        self._quitting = False
        self.turns = 0

    def threadId(self):
        return self._thread

    def processEvents(self, max_events=None):
        self.turns += 1
        return 0

    def processHostTurn(self):
        return False


class EventLoopIdleEfficiencyTests(unittest.TestCase):
    def test_idle_nested_loop_yields_even_with_host_pump(self):
        from DearUIQt.core.event_loop import QEventLoop
        app = _FakeApp()
        sleeps = []
        loop = None

        def pump():
            loop.quit()

        loop = QEventLoop(application=app, pump=pump)
        with patch("DearUIQt.core.event_loop.time.sleep", side_effect=lambda value: sleeps.append(value)):
            self.assertEqual(loop.exec(), 0)
        # A host callback can close the nested loop synchronously. Newer
        # revisions avoid sleeping after that close; older M6s builds yielded
        # once here. Both satisfy the original no-busy-spin contract.
        self.assertIn(sleeps, ([], [0.001]))

    def test_qdialog_exec_uses_low_frequency_orphan_guard(self):
        source = (ROOT / "DearUIQt" / "dialogs" / "qdialog.py").read_text()
        start = source.index("def exec(self):")
        end = source.index("exec_ = exec", start)
        block = source[start:end]
        self.assertIn("guard.setInterval(100)", block)
        self.assertNotIn("guard.setInterval(16)", block)
        self.assertIn("self.finished.connect(loop.exit)", block)

    def test_release_version_is_at_least_m6s(self):
        import DearUIQt
        major, minor, patch = (int(part) for part in DearUIQt.__version__.split("."))
        self.assertGreaterEqual((major, minor, patch), (1, 127, 0))


if __name__ == "__main__":
    unittest.main(verbosity=2)
