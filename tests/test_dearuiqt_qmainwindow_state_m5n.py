import unittest
from pathlib import Path

import DearUIQt
from DearUIQt.core import Qt
from DearUIQt.docking import QDockWidget, QDockWidgetStateController
from DearUIQt.widgets import QMainWindow


class _Manager:
    def __init__(self):
        self._entries = {}
        self._areas = {}

    def _resolve_key(self, dock):
        for key, entry in self._entries.items():
            if entry.get("window") is dock:
                return key
        return None

    def addDockWidget(self, key, dock, title=None, area=None, activate=True):
        key = str(key)
        self._entries[key] = {"window": dock, "title": title, "floating": False}
        self._areas[key] = area
        return key

    def removeDockWidget(self, key):
        key = str(key)
        self._entries.pop(key, None)
        self._areas.pop(key, None)
        return True

    def dockWidgetArea(self, key):
        return self._areas.get(str(key))

    def restoreDockWidget(self, key):
        key = str(key)
        if key not in self._entries:
            return False
        self._entries[key]["floating"] = False
        self._areas[key] = "left"
        return True

    def tabifyDockWidget(self, first, second):
        first = self._resolve_key(first) if not isinstance(first, str) else first
        second = self._resolve_key(second) if not isinstance(second, str) else second
        if first not in self._areas or second not in self._areas:
            return False
        self._areas[second] = self._areas[first]
        self._entries[second]["floating"] = False
        return True

    def splitDockWidget(self, first, second, orientation):
        return self.tabifyDockWidget(first, second)

    def restoreState(self, state, version=0):
        for key, entry in self._entries.items():
            entry["floating"] = bool(state.get("floating", False))
            self._areas[key] = state.get("area", self._areas.get(key, "right"))
        return True


def _dock(name, area="right"):
    dock = QDockWidget.__new__(QDockWidget)
    dock._object_name = name
    dock.tag = name + "-tag"
    dock.title = name.title()
    dock.dock_area = area
    dock._state_controller = QDockWidgetStateController(
        mode="docked", visible=True, dock_area=area)
    return dock


def _window(manager):
    window = QMainWindow.__new__(QMainWindow)
    window._dock_manager = manager
    window._dock_keys = {}
    window._require_ui = lambda: None
    return window


class QMainWindowStateM5nTests(unittest.TestCase):
    def test_controller_tracks_main_window_and_area(self):
        controller = QDockWidgetStateController(dock_area="right")
        owner = object()
        # object() is not weak-referenceable; fallback ownership must still work.
        self.assertTrue(controller.attachToMainWindow(owner, "left"))
        self.assertIs(controller.mainWindow(), owner)
        self.assertTrue(controller.isManaged())
        self.assertEqual(controller.dockArea(), "left")
        self.assertTrue(controller.detachFromMainWindow(owner))
        self.assertFalse(controller.isManaged())
        self.assertEqual(controller.dockArea(), "left")

    def test_add_remove_attach_and_detach_dock_controller(self):
        manager = _Manager()
        window = _window(manager)
        dock = _dock("console")
        window.addDockWidget(Qt.LeftDockWidgetArea, dock)
        controller = dock.stateController()
        self.assertIs(controller.mainWindow(), window)
        self.assertEqual(controller.dockArea(), "left")
        self.assertTrue(controller.isManaged())
        window.removeDockWidget(dock)
        self.assertFalse(controller.isManaged())
        # Last area is intentionally retained for later restore/re-add.
        self.assertEqual(controller.dockArea(), "left")

    def test_tabify_split_and_restore_resync_manager_area(self):
        manager = _Manager()
        window = _window(manager)
        first = _dock("first", "left")
        second = _dock("second", "right")
        window.addDockWidget(Qt.LeftDockWidgetArea, first)
        window.addDockWidget(Qt.RightDockWidgetArea, second)
        self.assertTrue(window.tabifyDockWidget(first, second))
        self.assertEqual(second.stateController().dockArea(), "left")
        manager._areas[second.objectName()] = "right"
        self.assertTrue(window.splitDockWidget(first, second, Qt.Horizontal))
        self.assertEqual(second.stateController().dockArea(), "left")
        self.assertTrue(window.restoreDockWidget(second))
        self.assertEqual(second.stateController().dockArea(), "left")
        self.assertFalse(second.stateController().isFloating())

    def test_restore_state_resyncs_registered_controllers(self):
        manager = _Manager()
        window = _window(manager)
        dock = _dock("plots")
        window.addDockWidget(Qt.RightDockWidgetArea, dock)
        self.assertTrue(window.restoreState({"area": "bottom", "floating": True}, 0))
        controller = dock.stateController()
        self.assertEqual(controller.dockArea(), "bottom")
        self.assertTrue(controller.isFloating())
        self.assertIs(controller.mainWindow(), window)

    def test_dock_manager_direct_floating_path_adopts_window_state(self):
        source = (Path(__file__).resolve().parents[1] /
                  "DearUIQt/docking/dock_manager.py").read_text()
        self.assertIn('self._apply_window_floating(entry.get("window"), floating)', source)

    def test_version(self):
        parts = tuple(int(x) for x in DearUIQt.__version__.split('.'))
        self.assertGreaterEqual(parts, (1, 96, 0))


if __name__ == "__main__":
    unittest.main()
