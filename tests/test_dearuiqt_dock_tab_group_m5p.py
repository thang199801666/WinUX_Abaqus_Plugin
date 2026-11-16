import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from DearUIQt.docking import DockLayoutTree, QDockTabGroupController


class _Window:
    def __init__(self, visible=True):
        self.visible = bool(visible)


class _Manager:
    def __init__(self):
        self._layout_tree = DockLayoutTree()
        self._entries = {}
        self.raised = []
        self.moved = []

    @staticmethod
    def _window_requested_visible(window):
        return bool(window.visible)

    def add(self, key, area="right", visible=True):
        self._entries[key] = {"window": _Window(visible), "floating": False}
        self._layout_tree.add_tab(key, area, activate=True)

    def raise_dock_widget(self, key):
        if key not in self._entries:
            return False
        self.raised.append(key)
        return self._layout_tree.set_active(key) or True

    def reorder_dock_widget(self, key, index):
        group = list(self._layout_tree.group_keys(key))
        if key not in group:
            return False
        group.remove(key)
        index = max(0, min(int(index), len(group)))
        group.insert(index, key)
        node = self._layout_tree.group_of(key)
        node["keys"] = group
        self.moved.append((key, index))
        return True


class DockTabGroupM5pTests(unittest.TestCase):
    def make_controller(self):
        manager = _Manager()
        manager.add("console")
        manager.add("plots")
        return manager, QDockTabGroupController(manager)

    def test_sync_mirrors_group_active_order_and_visibility(self):
        manager, controller = self.make_controller()
        group = controller.groupSnapshot("console")
        self.assertEqual(group["keys"], ("console", "plots"))
        self.assertEqual(group["activeKey"], "plots")
        self.assertEqual(group["visibleKeys"], ("console", "plots"))

        manager._entries["console"]["window"].visible = False
        seen = []
        controller.tabVisibilityChanged.connect(lambda gid, keys: seen.append((gid, keys)))
        self.assertTrue(controller.sync())
        self.assertEqual(controller.visibleTabs("plots"), ("plots",))
        self.assertEqual(seen[-1][1], ("plots",))

    def test_commands_delegate_to_canonical_manager_then_resync(self):
        manager, controller = self.make_controller()
        self.assertTrue(controller.setActiveTab("console"))
        self.assertEqual(manager.raised[-1], "console")
        self.assertEqual(controller.activeTab("console"), "console")

        self.assertTrue(controller.moveTab("plots", 0))
        self.assertEqual(manager.moved[-1], ("plots", 0))
        self.assertEqual(controller.tabOrder("console"), ("plots", "console"))

    def test_group_signals_only_fire_when_semantics_change(self):
        manager, controller = self.make_controller()
        groups = []
        active = []
        order = []
        controller.groupChanged.connect(lambda *args: groups.append(args))
        controller.activeTabChanged.connect(lambda *args: active.append(args))
        controller.tabOrderChanged.connect(lambda *args: order.append(args))
        self.assertFalse(controller.sync())
        self.assertEqual(groups, [])

        manager._layout_tree.set_active("console")
        self.assertTrue(controller.sync())
        self.assertEqual(len(active), 1)
        self.assertEqual(active[0][1], "console")
        self.assertEqual(order, [])

    def test_drag_transaction_is_retained_and_cancelable(self):
        _manager, controller = self.make_controller()
        started = []
        updated = []
        finished = []
        controller.dragStarted.connect(lambda state: started.append(state))
        controller.dragUpdated.connect(lambda state: updated.append(state))
        controller.dragFinished.connect(lambda state: finished.append(state))

        self.assertTrue(controller.beginDrag("console", (10, 20), grouped=True))
        self.assertTrue(controller.updateDrag((20, 25), 1, outside=True))
        state = controller.dragState()
        self.assertEqual(state["key"], "console")
        self.assertEqual(state["insertIndex"], 1)
        self.assertTrue(state["outside"])
        self.assertTrue(state["grouped"])
        self.assertTrue(controller.cancelDrag())
        self.assertIsNone(controller.dragState())
        self.assertEqual(finished[-1]["result"], "cancelled")
        self.assertEqual(len(started), 1)
        self.assertEqual(len(updated), 1)

    def test_version(self):
        import DearUIQt
        self.assertGreaterEqual(tuple(map(int, DearUIQt.__version__.split("."))), (1, 98, 0))

    def test_public_exports_and_integration_contracts(self):
        from DearUIQt import QDockTabGroupController as TopLevel
        self.assertIs(TopLevel, QDockTabGroupController)

        manager_path = os.path.join(ROOT, "DearUIQt", "docking", "dock_manager.py")
        window_path = os.path.join(ROOT, "DearUIQt", "widgets", "windows.py")
        dock_path = os.path.join(ROOT, "DearUIQt", "docking", "dock_widget.py")
        with open(manager_path, encoding="utf-8") as fh:
            manager_source = fh.read()
        with open(window_path, encoding="utf-8") as fh:
            window_source = fh.read()
        with open(dock_path, encoding="utf-8") as fh:
            dock_source = fh.read()
        self.assertIn("QDockTabGroupController(self)", manager_source)
        self.assertIn("tabGroupController = tab_group_controller", manager_source)
        self.assertIn("def dockTabGroupController", window_source)
        self.assertIn("dockTabGroupChanged = Signal()", window_source)
        self.assertIn("def tabGroupController", dock_source)


if __name__ == "__main__":
    unittest.main()
