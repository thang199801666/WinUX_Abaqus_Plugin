import unittest
import DearUIQt
from DearUIQt.docking import (
    QDockCommand, QMainWindowDockCommandBus, QDockTabGroupController,
    QDockTransition,
)


class _Window:
    pass


class _Tree:
    def group_of(self, key):
        if key not in ("a", "b"):
            return None
        return {"id": "g", "keys": ["a", "b"], "active": "a"}


class _Manager:
    _qt_accepts_dock_command_object = True
    def __init__(self):
        self._layout_tree = _Tree()
        self._entries = {
            "a": {"window": _Window(), "floating": False},
            "b": {"window": _Window(), "floating": False},
        }
        self.received = None

    @staticmethod
    def _window_requested_visible(window):
        return True

    def execute_tab_command(self, command, **payload):
        self.received = command
        return isinstance(command, QDockCommand) and command.command() == "activate"


class DockCommandObjectM5sTests(unittest.TestCase):
    def test_command_lifecycle_and_undo_metadata(self):
        cmd = QDockCommand("FLOAT", {"dock": "console"}, source="test")
        cmd.setUndoCommand("dock", dock="console")
        self.assertEqual(cmd.command(), "float")
        self.assertEqual(cmd.status(), QDockCommand.Pending)
        self.assertTrue(cmd.canUndo())
        self.assertEqual(cmd.undoCommand().command(), "dock")
        self.assertEqual(cmd.snapshot()["source"], "test")

    def test_mainwindow_bus_accepts_same_command_object(self):
        seen = []
        bus = QMainWindowDockCommandBus(lambda name, payload: seen.append((name, payload)) or 9)
        cmd = QDockCommand("add", {"area": "left"}, source="api")
        objects = []
        bus.commandObjectFinished.connect(lambda item: objects.append(item))
        self.assertEqual(bus.execute(cmd), 9)
        self.assertIs(bus.lastCommandObject(), cmd)
        self.assertIs(objects[-1], cmd)
        self.assertEqual(cmd.status(), QDockCommand.Finished)
        self.assertEqual(cmd.result(), 9)
        self.assertEqual(seen, [("add", {"area": "left"})])

    def test_tab_controller_passes_command_object_to_manager(self):
        manager = _Manager()
        controller = QDockTabGroupController(manager)
        finished = []
        controller.commandObjectFinished.connect(lambda item: finished.append(item))
        self.assertTrue(controller.activateTab("a"))
        self.assertIsInstance(manager.received, QDockCommand)
        self.assertIs(finished[-1], manager.received)
        self.assertEqual(finished[-1].status(), QDockCommand.Finished)

    def test_transition_uses_same_command_contract(self):
        transition = QDockTransition.dock(prepare=lambda ctx: True)
        command = transition.commandObject()
        self.assertEqual(command.command(), "dock")
        self.assertTrue(transition.commit({"feature": "plot"}))
        self.assertEqual(command.status(), QDockCommand.Finished)
        self.assertTrue(command.result())
        self.assertEqual(transition.diagnostics()["command"]["status"], "finished")

    def test_transition_cancel_marks_command_canceled(self):
        transition = QDockTransition.float(present=lambda ctx: True)
        self.assertTrue(transition.begin({}))
        self.assertTrue(transition.cancel("user canceled"))
        self.assertEqual(transition.commandObject().status(), QDockCommand.Canceled)

    def test_version(self):
        self.assertGreaterEqual(tuple(map(int, DearUIQt.__version__.split("."))), (1, 101, 0))


if __name__ == "__main__":
    unittest.main()
