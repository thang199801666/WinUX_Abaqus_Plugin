import unittest
from pathlib import Path

import DearUIQt
from DearUIQt.docking import QMainWindowDockCommandBus
from DearUIQt.widgets import QMainWindow


class _FloatDock:
    def __init__(self):
        self.values = []

    def setFloating(self, value):
        self.values.append(bool(value))


class QMainWindowCommandBusM5rTests(unittest.TestCase):
    def test_bus_orders_signals_and_records_diagnostics(self):
        calls = []
        bus = QMainWindowDockCommandBus(lambda command, payload: calls.append((command, payload)) or 7)
        events = []
        bus.commandRequested.connect(lambda command, payload, seq: events.append(("requested", command, seq)))
        bus.commandStarted.connect(lambda command, payload, seq: events.append(("started", command, seq)))
        bus.commandFinished.connect(lambda command, payload, result, seq: events.append(("finished", command, result, seq)))
        self.assertEqual(bus.execute("add", area="left"), 7)
        self.assertEqual([e[0] for e in events], ["requested", "started", "finished"])
        self.assertEqual(calls, [("add", {"area": "left"})])
        self.assertFalse(bus.isExecuting())
        last = bus.lastCommand()
        self.assertEqual(last["command"], "add")
        self.assertEqual(last["status"], "finished")
        self.assertEqual(last["result"], 7)

    def test_bus_rejects_nested_mutation(self):
        holder = {}
        def executor(command, payload):
            if command == "outer":
                return holder["bus"].execute("inner")
            return True
        holder["bus"] = QMainWindowDockCommandBus(executor)
        with self.assertRaises(RuntimeError):
            holder["bus"].execute("outer")
        self.assertEqual(holder["bus"].lastCommand()["status"], "failed")

    def test_mainwindow_float_and_dock_commands_share_bus(self):
        window = QMainWindow.__new__(QMainWindow)
        window._require_ui = lambda: None
        dock = _FloatDock()
        finished = []
        bus = window.dockCommandBus()
        bus.commandFinished.connect(lambda command, payload, result, seq: finished.append(command))
        self.assertTrue(window.setDockWidgetFloating(dock, True))
        self.assertTrue(window.setDockWidgetFloating(dock, False))
        self.assertEqual(dock.values, [True, False])
        self.assertEqual(finished, ["float", "dock"])

    def test_qmainwindow_mutation_apis_route_through_command_bus(self):
        source = (Path(__file__).resolve().parents[1] / "DearUIQt/widgets/windows.py").read_text()
        self.assertIn('return self.executeDockCommand("add"', source)
        self.assertIn('return self.executeDockCommand("remove"', source)
        self.assertIn('return self.executeDockCommand("tabify"', source)
        self.assertIn('return self.executeDockCommand("split"', source)
        self.assertIn('return self.executeDockCommand("restore"', source)
        self.assertIn('"float" if floating else "dock"', source)

    def test_version(self):
        self.assertGreaterEqual(tuple(map(int, DearUIQt.__version__.split("."))), (1, 100, 0))


if __name__ == "__main__":
    unittest.main()
