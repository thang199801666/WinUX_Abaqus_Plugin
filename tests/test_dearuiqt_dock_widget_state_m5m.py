import unittest
from pathlib import Path

import DearUIQt
from DearUIQt.docking import QDockWidgetStateController, QDockWindowLifecycle


class DockWidgetStateM5mTests(unittest.TestCase):
    def test_request_does_not_commit_until_host_adopts(self):
        requests = []
        c = QDockWidgetStateController(
            mode="docked", visible=True,
            request_floating=lambda desired: requests.append(desired) or True)
        tops = []
        c.topLevelChanged.connect(tops.append)
        self.assertTrue(c.requestFloating(True))
        self.assertEqual(requests, [True])
        self.assertTrue(c.requestInProgress())
        self.assertFalse(c.isFloating())
        self.assertEqual(tops, [])
        self.assertTrue(c.adoptFloating(True))
        self.assertTrue(c.isFloating())
        self.assertFalse(c.requestInProgress())
        self.assertEqual(tops, [True])

    def test_no_host_adapter_commits_synchronously(self):
        c = QDockWidgetStateController(mode="docked", visible=True)
        self.assertTrue(c.requestFloating(True))
        self.assertTrue(c.isFloating())
        self.assertEqual(c.lifecycle().mode(), QDockWindowLifecycle.Floating)

    def test_visibility_geometry_and_move_share_one_lifecycle(self):
        c = QDockWidgetStateController(mode="floating", visible=True)
        life = c.lifecycle()
        geometry = {"pos": (10, 20), "size": (640, 480)}
        self.assertTrue(c.setGeometry(geometry))
        self.assertEqual(life.geometry(), geometry)
        self.assertTrue(c.setVisible(False))
        self.assertFalse(life.isVisible())
        life.beginMove("left", "inner")
        self.assertTrue(life.isMoving())
        self.assertEqual(life.dropTarget(), {"area": "left", "scope": "inner"})

    def test_winux_console_and_plot_reuse_dock_owned_lifecycle(self):
        root = Path(__file__).resolve().parents[1]
        console = (root / "WinUx/ui/behaviors/docking/console.py").read_text()
        plot = (root / "WinUx/ui/behaviors/docking/plot.py").read_text()
        dock = (root / "DearUIQt/docking/dock_widget.py").read_text()
        self.assertIn('dock.stateController().lifecycle()', console)
        self.assertIn('panel.dock.stateController().lifecycle()', plot)
        self.assertIn('self._state_controller.requestFloating', dock)
        self.assertIn('self._state_controller.adoptFloating', dock)

    def test_version(self):
        parts = tuple(int(x) for x in DearUIQt.__version__.split('.'))
        self.assertGreaterEqual(parts, (1, 95, 0))


if __name__ == '__main__':
    unittest.main()
