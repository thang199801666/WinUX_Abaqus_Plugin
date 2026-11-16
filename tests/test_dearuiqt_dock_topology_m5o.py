import unittest
from pathlib import Path

import DearUIQt
from DearUIQt.core import Qt
from DearUIQt.docking import DockLayoutTree, QDockWidget, QDockWidgetStateController
from DearUIQt.widgets import QMainWindow


class _TopologyManager:
    def __init__(self):
        self._entries = {}
        self._areas = {}
        self._topology = {}

    def _resolve_key(self, dock):
        if isinstance(dock, str):
            return dock if dock in self._entries else None
        for key, entry in self._entries.items():
            if entry.get("window") is dock:
                return key
        return None

    def addDockWidget(self, key, dock, title=None, area=None, activate=True):
        key = str(key)
        self._entries[key] = {"window": dock, "title": title, "floating": False}
        self._areas[key] = area
        self._topology[key] = {
            "area": area, "tabGroupId": "group-{}".format(area),
            "tabifiedKeys": (), "activeTabKey": key,
            "splitOrientation": None, "splitPath": None,
        }
        return key

    def dockWidgetArea(self, key):
        return self._areas.get(str(key))

    def dockTopology(self, key):
        key = self._resolve_key(key) or str(key)
        return dict(self._topology.get(key) or {})


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
    window._dock_topology_connections = {}
    from DearUIQt.core import Signal
    window.dockTopologyChanged = Signal()
    window._require_ui = lambda: None
    return window


class DockTopologyM5oTests(unittest.TestCase):
    def test_layout_tree_reports_tab_and_split_topology(self):
        tree = DockLayoutTree()
        tree.add_tab("a", "left")
        tree.add_tab("b", "left")
        topo_a = tree.topology_for("a")
        self.assertEqual(topo_a["area"], "left")
        self.assertEqual(topo_a["tabifiedKeys"], ("b",))
        self.assertEqual(topo_a["activeTabKey"], "b")
        self.assertIsNone(topo_a["splitOrientation"])

        self.assertEqual(tree.split("a", "c", "horizontal"), "tabified")
        # Split a single-tab leaf in another area so split parent metadata exists.
        tree.add_tab("x", "right")
        self.assertEqual(tree.split("x", "y", "vertical"), "split")
        topo_x = tree.topology_for("x")
        topo_y = tree.topology_for("y")
        self.assertEqual(topo_x["splitOrientation"], DockLayoutTree.VERTICAL)
        self.assertEqual(topo_y["splitOrientation"], DockLayoutTree.VERTICAL)
        self.assertEqual(topo_x["splitPath"], ())
        self.assertEqual(topo_y["splitPath"], ())

    def test_controller_emits_semantic_topology_signals(self):
        controller = QDockWidgetStateController(dock_area="right")
        events = []
        controller.tabGroupChanged.connect(lambda group, keys: events.append(("tabs", group, keys)))
        controller.activeTabChanged.connect(lambda key: events.append(("active", key)))
        controller.splitTopologyChanged.connect(lambda orientation, path: events.append(("split", orientation, path)))
        controller.topologyChanged.connect(lambda snapshot: events.append(("topology", snapshot)))

        topology = {
            "area": "left", "tabGroupId": "g1", "tabifiedKeys": ("b",),
            "activeTabKey": "a", "splitOrientation": "horizontal", "splitPath": (1, 0),
        }
        self.assertTrue(controller.adoptTopology(topology))
        self.assertEqual(controller.dockArea(), "left")
        self.assertEqual(controller.tabGroupId(), "g1")
        self.assertEqual(controller.tabifiedKeys(), ("b",))
        self.assertEqual(controller.activeTabKey(), "a")
        self.assertTrue(controller.isActiveTab())
        self.assertEqual(controller.splitOrientation(), "horizontal")
        self.assertEqual(controller.splitPath(), (1, 0))
        event_count = len(events)
        self.assertFalse(controller.adoptTopology(topology))
        self.assertEqual(len(events), event_count)

    def test_qmainwindow_forwards_controller_topology_signal(self):
        manager = _TopologyManager()
        window = _window(manager)
        dock = _dock("console")
        forwarded = []
        window.dockTopologyChanged.connect(
            lambda changed_dock, snapshot: forwarded.append((changed_dock, snapshot)))
        window.addDockWidget(Qt.LeftDockWidgetArea, dock)
        self.assertEqual(dock.stateController().tabGroupId(), "group-left")

        manager._topology["console"] = {
            "area": "left", "tabGroupId": "g-tabs", "tabifiedKeys": ("plots",),
            "activeTabKey": "plots", "splitOrientation": None, "splitPath": None,
        }
        window._sync_dock_controller_from_manager(dock, "console")
        self.assertEqual(dock.stateController().tabifiedKeys(), ("plots",))
        self.assertEqual(dock.stateController().activeTabKey(), "plots")
        self.assertTrue(forwarded)
        self.assertIs(forwarded[-1][0], dock)

    def test_manager_source_syncs_topology_after_mutations(self):
        source = (Path(__file__).resolve().parents[1] /
                  "DearUIQt/docking/dock_manager.py").read_text()
        self.assertIn("def dock_topology(self, key):", source)
        self.assertIn("def _sync_all_window_topology(self):", source)
        self.assertIn("self._sync_all_window_topology()", source)

    def test_version(self):
        parts = tuple(int(x) for x in DearUIQt.__version__.split('.'))
        self.assertGreaterEqual(parts, (1, 97, 0))


if __name__ == "__main__":
    unittest.main()
