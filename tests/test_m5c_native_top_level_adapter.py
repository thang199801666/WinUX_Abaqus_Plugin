from pathlib import Path
import re
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from DearUIQt.backends.native_windows import NativeTopLevelWindow


class NativeTopLevelAdapterM5cTests(unittest.TestCase):
    def test_adapter_is_public_and_centralizes_presentation_calls(self):
        source = (ROOT / "DearUIQt" / "backends" / "native_windows.py").read_text(encoding="utf-8")
        self.assertIn("class NativeTopLevelWindow", source)
        for token in ("GetWindowRect", "SetWindowPos", "ShowWindow", "SetForegroundWindow"):
            self.assertIn(token, source)

    def test_floating_viewport_routes_presentation_through_adapter(self):
        source = (ROOT / "WinUx" / "ui" / "native" / "floating_viewport.py").read_text(encoding="utf-8")
        self.assertIn("NativeTopLevelWindow", source)
        self.assertIn(".setGeometry(", source)
        self.assertIn(".setVisible(", source)
        self.assertIn(".restore(", source)

    def test_pip_and_dock_reveal_share_adapter(self):
        pip = (ROOT / "WinUx" / "ui" / "behaviors" / "window" / "compact_job_monitor.py").read_text(encoding="utf-8")
        dock = (ROOT / "WinUx" / "ui" / "native" / "native_dock_gesture.py").read_text(encoding="utf-8")
        self.assertIn("NativeTopLevelWindow", pip)
        self.assertIn("NativeTopLevelWindow", dock)

    def test_m5c_version(self):
        source = (ROOT / "DearUIQt" / "__init__.py").read_text(encoding="utf-8")
        match = re.search(r'__version__\s*=\s*"(\d+)\.(\d+)\.(\d+)"', source)
        self.assertIsNotNone(match)
        self.assertGreaterEqual(tuple(map(int, match.groups())), (1, 85, 0))


if __name__ == "__main__":
    unittest.main(verbosity=2)
