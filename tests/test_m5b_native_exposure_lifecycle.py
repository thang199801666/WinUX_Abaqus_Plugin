from pathlib import Path
import re
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

from DearUIQt.QtCore import QEvent, QPoint, QRect, QSize
from DearUIQt.core.application import QApplication
from DearUIQt.widgets import QWidget
from test_dearuiqt_layout_cache import Backend


class Probe(QWidget):
    def __init__(self, *args, **kwargs):
        self.events = []
        super().__init__(*args, **kwargs)

    def moveEvent(self, event):
        self.events.append(("move", dict(event.payload)))

    def resizeEvent(self, event):
        self.events.append(("resize", dict(event.payload)))

    def exposeEvent(self, event):
        self.events.append(("expose", dict(event.payload)))

    def changeEvent(self, event):
        if event.type() == QEvent.ActivationChange:
            self.events.append(("activation", dict(event.payload)))


class NativeExposureM5bTests(unittest.TestCase):
    def make_window(self):
        backend = Backend()
        tag = backend.add_group()
        return backend, Probe(tag, backend=backend)

    def test_api_geometry_emits_only_real_move_resize_transitions(self):
        _backend, window = self.make_window()
        try:
            window.setGeometry(10, 20, 300, 200)
            kinds = [kind for kind, _ in window.events]
            self.assertEqual(kinds.count("move"), 1)
            self.assertEqual(kinds.count("resize"), 1)
            window.setGeometry(10, 20, 300, 200)
            kinds = [kind for kind, _ in window.events]
            self.assertEqual(kinds.count("move"), 1)
            self.assertEqual(kinds.count("resize"), 1)
            move = next(payload for kind, payload in window.events if kind == "move")
            resize = next(payload for kind, payload in window.events if kind == "resize")
            self.assertEqual(move["pos"], QPoint(10, 20))
            self.assertEqual(resize["size"], QSize(300, 200))
            self.assertEqual(move["source"], "api")
        finally:
            window.delete()

    def test_native_geometry_sync_never_writes_back(self):
        backend, window = self.make_window()
        writes_before = len(getattr(backend, "configured", []))
        try:
            self.assertTrue(window.syncGeometryFromNative((40, 50, 640, 480)))
            self.assertEqual(window.geometry(), QRect(40, 50, 640, 480))
            writes_after = len(getattr(backend, "configured", []))
            self.assertEqual(writes_after, writes_before)
            self.assertFalse(window.syncGeometryFromNative((40, 50, 640, 480)))
            payloads = [payload for kind, payload in window.events if kind in ("move", "resize")]
            self.assertTrue(all(payload["source"] == "native" for payload in payloads))
        finally:
            window.delete()

    def test_native_exposure_is_retained_and_deduplicated(self):
        _backend, window = self.make_window()
        try:
            self.assertTrue(window.isExposed())
            self.assertTrue(window.syncExposureFromNative(False))
            self.assertFalse(window.isExposed())
            self.assertFalse(window.syncExposureFromNative(False))
            self.assertTrue(window.syncExposureFromNative(True))
            exposes = [payload for kind, payload in window.events if kind == "expose"]
            self.assertEqual(len(exposes), 2)
            self.assertEqual(exposes[0]["source"], "native")
        finally:
            window.delete()

    def test_activation_transition_delivers_activation_change(self):
        app = QApplication.instance()
        owned = False
        if app is None:
            app = QApplication()
            owned = True
        backend1, first = self.make_window()
        backend2, second = self.make_window()
        try:
            app.setActiveWindow(first)
            app.setActiveWindow(second)
            first_changes = [p for k, p in first.events if k == "activation"]
            second_changes = [p for k, p in second.events if k == "activation"]
            self.assertEqual([p["active"] for p in first_changes[-2:]], [True, False])
            self.assertTrue(second_changes[-1]["active"])
        finally:
            first.delete()
            second.delete()
            if owned:
                app.delete()

    def test_winux_host_loop_syncs_state_geometry_and_exposure(self):
        source = (ROOT / "WinUx" / "ui" / "behaviors" / "window" / "lifecycle.py").read_text(
            encoding="utf-8")
        self.assertIn("syncWindowStateFromNative", source)
        self.assertIn("syncGeometryFromNative", source)
        self.assertIn("syncExposureFromNative", source)

    def test_m5b_version(self):
        source = (ROOT / "DearUIQt" / "__init__.py").read_text(encoding="utf-8")
        match = re.search(r'__version__\s*=\s*"(\d+)\.(\d+)\.(\d+)"', source)
        self.assertIsNotNone(match)
        self.assertGreaterEqual(tuple(map(int, match.groups())), (1, 84, 0))


if __name__ == "__main__":
    unittest.main(verbosity=2)
