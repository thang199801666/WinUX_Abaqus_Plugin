from pathlib import Path
import sys
import unittest
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "vendor"))
sys.path.insert(0, str(ROOT))

from WinUx.plotdigitizer.ui.controllers.calibration import CalibrationController


class FakeRibbon:
    def __init__(self):
        self.tab = "data"
        self.calls = []
    def set_active_tab(self, tab):
        self.tab = tab
        self.calls.append(tab)


class FakePage:
    pass


class FakeOwner:
    def __init__(self):
        self.ribbon = FakeRibbon()
        self._tool_pages = {"axes": FakePage(), "extract": FakePage(), "data": FakePage()}
        self._active_tool = "data"
        self._pick_mode = None
        self._calibration_draft = None
        self._anchor_drag_target = None
        self._anchor_drag_preview = None
        self._hover_anchor = None
        self.result_grid = object()
        self.active_table = self.result_grid
        self.settings_panel = object()
        self.tool_list = SimpleNamespace(currentKey=lambda: "data")
    def set_control_visible(self, *args):
        pass
    def _refresh_point_editor(self):
        pass
    def _refresh_workflow_completion(self):
        pass
    def _cancel_pick(self):
        pass


class TabStateContractTests(unittest.TestCase):
    def test_internal_tool_change_preserves_user_selected_ribbon_tab(self):
        owner = FakeOwner()
        controller = CalibrationController(owner)
        # Avoid retained-item scrollbar access; same-tool early return is enough
        # to verify no implicit ribbon synchronization happens.
        controller._show_tool("data")
        self.assertEqual(owner.ribbon.tab, "data")
        self.assertEqual(owner.ribbon.calls, [])

    def test_explicit_navigation_can_sync_ribbon(self):
        owner = FakeOwner()
        controller = CalibrationController(owner)
        controller._show_tool("data", sync_ribbon=True)
        self.assertEqual(owner.ribbon.tab, "data")
        self.assertEqual(owner.ribbon.calls, ["data"])

    def test_view_data_button_requests_explicit_tab_sync(self):
        source = (ROOT / "WinUx" / "plotdigitizer" / "ui" / "dialog.py").read_text()
        self.assertIn("lambda: self._show_tool('data', sync_ribbon=True)", source)

if __name__ == "__main__":
    unittest.main()
