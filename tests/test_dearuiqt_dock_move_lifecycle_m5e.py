from pathlib import Path
import unittest

from DearUIQt import __version__
from DearUIQt.docking import QDockWindowLifecycle


ROOT = Path(__file__).resolve().parents[1]


class DockMoveLifecycleM5eTests(unittest.TestCase):
    def test_version(self):
        self.assertGreaterEqual(tuple(map(int, __version__.split('.'))), (1, 87, 0))

    def test_move_signals_and_target_cleanup(self):
        life = QDockWindowLifecycle('floating', True)
        started, targets, finished = [], [], []
        life.moveStarted.connect(started.append)
        life.dropTargetChanged.connect(targets.append)
        life.moveFinished.connect(finished.append)
        self.assertTrue(life.beginMove())
        self.assertTrue(life.setDropTarget('bottom', 'outer'))
        self.assertTrue(life.endMove(docked=True))
        self.assertEqual(len(started), 1)
        self.assertEqual(targets[-1], None)
        self.assertEqual(finished[-1]['target'], {'area': 'bottom', 'scope': 'outer'})
        self.assertTrue(finished[-1]['docked'])

    def test_console_drag_routes_through_lifecycle(self):
        source = (ROOT / 'WinUx/ui/behaviors/docking/console.py').read_text()
        self.assertIn('_console_begin_dock_move()', source)
        self.assertIn('_console_update_dock_target(target, scope)', source)
        self.assertIn('_console_end_dock_move(', source)

    def test_plot_drag_routes_through_lifecycle(self):
        source = (ROOT / 'WinUx/ui/behaviors/docking/plot.py').read_text()
        self.assertIn('_plot_begin_dock_move(key)', source)
        self.assertIn('_plot_update_dock_target(key, target_area, target_scope)', source)
        self.assertIn('_plot_end_dock_move(', source)

    def test_native_host_routes_user32_gesture_to_lifecycle(self):
        source = (ROOT / 'WinUx/dialogs/native_dock_hosts.py').read_text()
        self.assertIn('self._qt_begin_move(target)', source)
        self.assertIn('self._qt_update_drop_target(target)', source)
        self.assertIn('self._qt_end_move(docked=(target is not None), target=target)', source)


if __name__ == '__main__':
    unittest.main()
