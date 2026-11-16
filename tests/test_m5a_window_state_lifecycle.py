from pathlib import Path
import re
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

from DearUIQt.QtCore import QEvent, Qt
from DearUIQt.widgets import QWidget
from test_dearuiqt_layout_cache import Backend


class StateProbe(QWidget):
    def __init__(self, *args, **kwargs):
        self.transitions = []
        super().__init__(*args, **kwargs)

    def changeEvent(self, event):
        if event.type() == QEvent.WindowStateChange:
            self.transitions.append(dict(event.payload))


class WindowStateM5aTests(unittest.TestCase):
    def make_window(self):
        backend = Backend()
        tag = backend.add_group()
        return backend, StateProbe(tag, backend=backend)

    def test_retained_window_state_emits_only_real_transitions(self):
        _backend, window = self.make_window()
        try:
            self.assertEqual(window.windowState(), Qt.WindowNoState)
            window.setWindowState(Qt.WindowMinimized)
            self.assertTrue(window.isMinimized())
            self.assertEqual(len(window.transitions), 1)
            self.assertEqual(window.transitions[-1]["oldState"], Qt.WindowNoState)
            self.assertEqual(window.transitions[-1]["state"], Qt.WindowMinimized)
            self.assertEqual(window.transitions[-1]["source"], "api")

            window.setWindowState(Qt.WindowMinimized)
            self.assertEqual(len(window.transitions), 1)

            window.showNormal()
            self.assertEqual(window.windowState(), Qt.WindowNoState)
            self.assertEqual(len(window.transitions), 2)
        finally:
            window.delete()

    def test_native_sync_does_not_write_state_back_to_os(self):
        _backend, window = self.make_window()
        writes = []
        window._apply_window_state_native = lambda state: writes.append(state) or True
        try:
            self.assertTrue(window.syncWindowStateFromNative(Qt.WindowMaximized))
            self.assertTrue(window.isMaximized())
            self.assertEqual(writes, [])
            self.assertEqual(window.transitions[-1]["source"], "native")

            window.setWindowState(Qt.WindowNoState)
            self.assertEqual(writes, [Qt.WindowNoState])
        finally:
            window.delete()

    def test_presentation_state_is_mutually_exclusive(self):
        _backend, window = self.make_window()
        try:
            window.setWindowState(Qt.WindowMinimized | Qt.WindowMaximized)
            self.assertFalse(window.isMinimized())
            self.assertTrue(window.isMaximized())
            window.setWindowState(Qt.WindowMinimized | Qt.WindowFullScreen)
            self.assertFalse(window.isMinimized())
            self.assertTrue(window.isFullScreen())
        finally:
            window.delete()

    def test_winux_primary_loop_synchronizes_native_window_state(self):
        source = (ROOT / "WinUx" / "ui" / "behaviors" / "window" / "lifecycle.py").read_text(
            encoding="utf-8")
        self.assertIn("syncWindowStateFromNative", source)
        self.assertIn("Qt.WindowMinimized", source)
        self.assertIn("Qt.WindowMaximized", source)

    def test_m5a_version(self):
        source = (ROOT / "DearUIQt" / "__init__.py").read_text(encoding="utf-8")
        match = re.search(r'__version__\s*=\s*"(\d+)\.(\d+)\.(\d+)"', source)
        self.assertIsNotNone(match)
        self.assertGreaterEqual(tuple(map(int, match.groups())), (1, 83, 0))


if __name__ == "__main__":
    unittest.main(verbosity=2)
