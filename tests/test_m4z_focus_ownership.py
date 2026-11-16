from collections import deque
from pathlib import Path
import re
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

from DearUIQt.core.application import QApplication
from DearUIQt.widgets import QWidget
from test_dearuiqt_layout_cache import Backend


class Scheduler:
    def __init__(self):
        self.callbacks = deque()

    def after(self, _delay, callback, *args):
        self.callbacks.append((callback, args))


class FocusOwnershipM4zTests(unittest.TestCase):
    def tearDown(self):
        app = QApplication.instance()
        if app is not None:
            app.delete()

    def test_public_focus_bridge_updates_focus_and_active_window(self):
        scheduler = Scheduler()
        app = QApplication(after=scheduler.after)
        backend = Backend()
        window = QWidget(backend.add_group(), backend=backend, after=scheduler.after)
        child = QWidget(backend.add_group(parent=window.tag), parent=window,
                        backend=backend, after=scheduler.after)
        changes = []
        app.focusChanged.connect(lambda old, new: changes.append((old, new)))
        try:
            self.assertTrue(app.setFocusWidget(child))
            self.assertIs(app.focusWidget(), child)
            self.assertIs(app.focusObject(), child)
            self.assertIs(app.activeWindow(), window)
            self.assertEqual(changes[-1], (None, child))
            self.assertFalse(app.setFocusWidget(child))
        finally:
            window.delete()

    def test_public_focus_bridge_rejects_non_qobject(self):
        scheduler = Scheduler()
        app = QApplication(after=scheduler.after)
        with self.assertRaises(TypeError):
            app.setFocusWidget(object())

    def test_dialog_uses_qpointer_focus_snapshot_and_reactivation(self):
        source = (ROOT / "DearUIQt" / "dialogs" / "qt_dialog.py").read_text(encoding="utf-8")
        self.assertIn("self._focus_restore_widget = QPointer(candidate)", source)
        self.assertIn("parent.activateWindow()", source)
        self.assertIn("fallback_dialog.activateWindow()", source)
        self.assertIn("candidate.setFocus()", source)

    def test_winux_does_not_reach_into_private_application_focus(self):
        offenders = []
        for path in (ROOT / "WinUx").rglob("*.py"):
            text = path.read_text(encoding="utf-8", errors="ignore")
            if "._set_focus_widget(" in text or "._focus_widget" in text:
                offenders.append(str(path.relative_to(ROOT)))
        self.assertEqual(offenders, [])

    def test_m4z_version(self):
        source = (ROOT / "DearUIQt" / "__init__.py").read_text(encoding="utf-8")
        match = re.search(r'__version__\s*=\s*"(\d+)\.(\d+)\.(\d+)"', source)
        self.assertIsNotNone(match)
        self.assertGreaterEqual(tuple(map(int, match.groups())), (1, 82, 0))


if __name__ == "__main__":
    unittest.main(verbosity=2)
