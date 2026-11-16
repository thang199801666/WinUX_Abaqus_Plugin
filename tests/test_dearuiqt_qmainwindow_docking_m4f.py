import unittest

from DearUIQt.core import Qt
from DearUIQt.widgets import QMainWindow, QDockWidget


class _FakeManager:
    def __init__(self):
        self._entries = {}
        self._areas = {}
        self.calls = []
        self.options = 0x05
        self.nested = False
        self.animated = True
        self.document = False
        self.saved = None

    def _resolve_key(self, dock):
        for key, entry in self._entries.items():
            if entry.get("window") is dock:
                return key
        return None

    def addDockWidget(self, key, dock, title=None, area=None, activate=True):
        self.calls.append(("add", key, area, activate))
        self._entries[str(key)] = {"window": dock, "title": title}
        self._areas[str(key)] = area
        return str(key)

    def removeDockWidget(self, key):
        self.calls.append(("remove", str(key)))
        self._entries.pop(str(key), None)
        self._areas.pop(str(key), None)
        return True

    def dockWidgetArea(self, key):
        return self._areas.get(str(key))

    def tabifyDockWidget(self, first, second):
        self.calls.append(("tabify", first, second))
        return True

    def tabifiedDockWidgets(self, dock):
        key = self._resolve_key(dock) if not isinstance(dock, str) else dock
        return tuple(k for k in self._entries if k != key)

    def splitDockWidget(self, first, second, orientation):
        self.calls.append(("split", first, second, orientation))
        return True

    def resizeDocks(self, docks, sizes, orientation):
        self.calls.append(("resize", tuple(docks), tuple(sizes), orientation))
        return True

    def restoreDockWidget(self, key):
        self.calls.append(("restoreDock", str(key)))
        return True

    def setDockOptions(self, value): self.options = int(value); return True
    def dockOptions(self): return self.options
    def setDockNestingEnabled(self, value): self.nested = bool(value); return True
    def isDockNestingEnabled(self): return self.nested
    def setAnimated(self, value): self.animated = bool(value); return True
    def isAnimated(self): return self.animated
    def setDocumentMode(self, value): self.document = bool(value); return True
    def documentMode(self): return self.document
    def setTabPosition(self, areas, pos): self.calls.append(("tabpos", areas, pos)); return True
    def tabPosition(self, area): return "top"

    def saveState(self, version=0):
        return {"format": 3, "version": int(version), "order": list(self._entries), "docks": []}

    def restoreState(self, state, version=0):
        self.saved = (dict(state), int(version))
        return True

    def layout(self, width, height, force=False):
        self.calls.append(("layout", width, height, bool(force)))


def _dock(name):
    dock = QDockWidget.__new__(QDockWidget)
    dock._object_name = name
    dock.tag = name + "-tag"
    dock.title = name.title()
    dock.dock_area = "right"
    return dock


def _window(manager):
    window = QMainWindow.__new__(QMainWindow)
    window._dock_manager = manager
    window._dock_keys = {}
    window._require_ui = lambda: None
    return window


class QMainWindowDockingFacadeTests(unittest.TestCase):
    def test_qt_dock_area_constants_are_exposed(self):
        self.assertEqual(QMainWindow.LeftDockWidgetArea, Qt.LeftDockWidgetArea)
        self.assertEqual(QMainWindow.RightDockWidgetArea, Qt.RightDockWidgetArea)
        self.assertEqual(QMainWindow.AllDockWidgetAreas, Qt.AllDockWidgetAreas)

    def test_add_remove_and_area_use_qdockwidget_object_name(self):
        manager = _FakeManager()
        window = _window(manager)
        dock = _dock("console")
        self.assertIsNone(window.addDockWidget(Qt.LeftDockWidgetArea, dock))
        self.assertEqual(manager.calls[0], ("add", "console", "left", True))
        self.assertEqual(window.dockWidgetArea(dock), Qt.LeftDockWidgetArea)
        self.assertIsNone(window.removeDockWidget(dock))
        self.assertIn(("remove", "console"), manager.calls)
        self.assertEqual(window.dockWidgetArea(dock), Qt.NoDockWidgetArea)

    def test_tab_split_resize_and_tabified_return_dock_objects(self):
        manager = _FakeManager()
        window = _window(manager)
        first = _dock("first")
        second = _dock("second")
        window.addDockWidget(Qt.RightDockWidgetArea, first)
        window.addDockWidget(Qt.RightDockWidgetArea, second)
        self.assertTrue(window.tabifyDockWidget(first, second))
        self.assertEqual(window.tabifiedDockWidgets(first), [second])
        self.assertTrue(window.splitDockWidget(first, second, Qt.Horizontal))
        self.assertTrue(window.resizeDocks([first, second], [2, 1], Qt.Horizontal))

    def test_policy_and_versioned_state_delegate_to_manager(self):
        manager = _FakeManager()
        window = _window(manager)
        window.setDockOptions(QMainWindow.AllowTabbedDocks | QMainWindow.AllowNestedDocks)
        self.assertEqual(window.dockOptions(), 0x06)
        window.setDockNestingEnabled(True)
        self.assertTrue(window.isDockNestingEnabled())
        window.setAnimated(False)
        self.assertFalse(window.isAnimated())
        window.setDocumentMode(True)
        self.assertTrue(window.documentMode())
        state = window.saveState(7)
        self.assertEqual(state["version"], 7)
        self.assertTrue(window.restoreState(state, 7))
        self.assertEqual(manager.saved[1], 7)

    def test_restore_dock_registers_late_created_dock(self):
        manager = _FakeManager()
        window = _window(manager)
        dock = _dock("late")
        self.assertTrue(window.restoreDockWidget(dock))
        self.assertIn("late", manager._entries)
        self.assertIn(("restoreDock", "late"), manager.calls)


if __name__ == "__main__":
    unittest.main()
