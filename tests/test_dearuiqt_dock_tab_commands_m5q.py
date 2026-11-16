import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from DearUIQt.docking import QDockTabGroupController


class _CommandManager:
    def __init__(self):
        self.commands = []
        self._layout_tree = _Tree()
        self._entries = {
            "a": {"window": _Window(), "floating": False},
            "b": {"window": _Window(), "floating": False},
        }

    @staticmethod
    def _window_requested_visible(window):
        return True

    def execute_tab_command(self, command, **payload):
        self.commands.append((command, dict(payload)))
        if command == "activate":
            self._layout_tree.active = payload["key"]
        elif command == "move":
            key = payload["key"]
            keys = list(self._layout_tree.keys)
            keys.remove(key)
            keys.insert(payload["index"], key)
            self._layout_tree.keys = tuple(keys)
        return command in {"activate", "move", "dock", "detach", "cancel"}


class _Window:
    pass


class _Tree:
    def __init__(self):
        self.keys = ("a", "b")
        self.active = "b"

    def group_of(self, key):
        if key not in self.keys:
            return None
        return {"id": "g", "keys": list(self.keys), "active": self.active}


class DockTabCommandM5qTests(unittest.TestCase):
    def make_controller(self):
        manager = _CommandManager()
        return manager, QDockTabGroupController(manager)

    def test_semantic_commands_use_single_manager_gateway(self):
        manager, controller = self.make_controller()
        requested = []
        finished = []
        controller.commandRequested.connect(lambda payload: requested.append(payload))
        controller.commandFinished.connect(lambda payload: finished.append(payload))

        self.assertTrue(controller.activateTab("a"))
        self.assertTrue(controller.moveTab("b", 0))
        self.assertTrue(controller.dockTab("a", "b", "left"))
        self.assertTrue(controller.detachTab("a", (10, 20), (3, 4), grouped=False))

        self.assertEqual([item[0] for item in manager.commands],
                         ["activate", "move", "dock", "detach"])
        self.assertEqual(requested[2]["targetKey"], "b")
        self.assertEqual(requested[2]["zone"], "left")
        self.assertTrue(all(item["accepted"] for item in finished))
        self.assertEqual(controller.activeTab("a"), "a")
        self.assertEqual(controller.tabOrder("a"), ("b", "a"))

    def test_grouped_detach_carries_group_identity(self):
        manager, controller = self.make_controller()
        self.assertTrue(controller.detachTab(
            "a", (30, 40), (5, 6), grouped=True, keys=("a", "b")))
        command, payload = manager.commands[-1]
        self.assertEqual(command, "detach")
        self.assertTrue(payload["grouped"])
        self.assertEqual(payload["keys"], ("a", "b"))

    def test_cancel_is_semantic_command(self):
        manager, controller = self.make_controller()
        self.assertTrue(controller.cancelCommand())
        self.assertEqual(manager.commands[-1][0], "cancel")

    def test_renderer_routes_drop_reorder_and_detach_through_controller(self):
        path = os.path.join(ROOT, "DearUIQt", "docking", "dock_manager.py")
        with open(path, encoding="utf-8") as fh:
            source = fh.read()
        self.assertIn("def execute_tab_command", source)
        self.assertIn("self._tab_group_controller.activateTab(key)", source)
        self.assertIn("self._tab_group_controller.moveTab(key, index)", source)
        self.assertIn("self._tab_group_controller.dockTab(", source)
        self.assertIn("self._tab_group_controller.detachTab(", source)

        interaction = source[source.index("def update_interaction"):source.index("def _rebuild_tab_view")]
        self.assertNotIn("self.reorder_dock_widget(key, index)", interaction)
        self.assertNotIn("self._request_drag_tearoff(key, mouse, drag_anchor)", interaction)
        self.assertNotIn("self.dock_relative(\n", interaction)

    def test_version(self):
        import DearUIQt
        self.assertGreaterEqual(tuple(map(int, DearUIQt.__version__.split("."))), (1, 99, 0))


if __name__ == "__main__":
    unittest.main()
