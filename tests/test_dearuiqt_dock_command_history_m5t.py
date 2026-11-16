import unittest

import DearUIQt
from DearUIQt.docking import QDockCommandHistory, QMainWindowDockCommandBus, QDockTransition
from DearUIQt.widgets import QMainWindow


class _StateHarness:
    def __init__(self):
        self.value = []

    def capture(self):
        return tuple(self.value)

    def restore(self, checkpoint):
        self.value[:] = list(checkpoint)
        return True

    def execute(self, command, payload):
        if command == "append":
            self.value.append(payload["value"])
            return True
        if command == "fail":
            self.value.append("temporary")
            raise RuntimeError("boom")
        return False


class _Dock:
    def __init__(self, name):
        self.name = name


class _Manager:
    def __init__(self):
        self._entries = {}
        self.restored = None

    def addDockWidget(self, key, window, title=None, area=None, activate=False):
        self._entries[str(key)] = {
            "window": window, "title": title, "area": area, "floating": False,
        }
        return str(key)

    def removeDockWidget(self, key):
        return self._entries.pop(str(key), None) is not None

    def saveState(self, version=0):
        return {
            "format": 3, "version": int(version),
            "order": list(self._entries),
            "docks": [{"key": key, "object_name": key, "area": entry.get("area"),
                       "floating": bool(entry.get("floating")), "visible": True}
                      for key, entry in self._entries.items()],
        }

    def restoreState(self, state, version=0):
        self.restored = dict(state or {})
        return int(self.restored.get("version", 0)) == int(version)


class DockCommandHistoryM5tTests(unittest.TestCase):
    def test_bus_records_checkpoint_history_and_undo_redo(self):
        harness = _StateHarness()
        history = QDockCommandHistory(harness.capture, harness.restore, limit=4)
        bus = QMainWindowDockCommandBus(harness.execute)
        bus.setHistory(history)

        self.assertTrue(bus.execute("append", value="a"))
        self.assertTrue(bus.execute("append", value="b"))
        self.assertEqual(harness.value, ["a", "b"])
        self.assertTrue(history.canUndo())
        self.assertTrue(history.undo())
        self.assertEqual(harness.value, ["a"])
        self.assertTrue(history.canRedo())
        self.assertTrue(history.redo())
        self.assertEqual(harness.value, ["a", "b"])

    def test_new_command_after_undo_clears_redo(self):
        harness = _StateHarness()
        history = QDockCommandHistory(harness.capture, harness.restore)
        bus = QMainWindowDockCommandBus(harness.execute)
        bus.setHistory(history)
        bus.execute("append", value=1)
        bus.execute("append", value=2)
        self.assertTrue(history.undo())
        bus.execute("append", value=3)
        self.assertEqual(harness.value, [1, 3])
        self.assertFalse(history.canRedo())

    def test_failed_command_does_not_create_history_entry(self):
        harness = _StateHarness()
        history = QDockCommandHistory(harness.capture, harness.restore)
        bus = QMainWindowDockCommandBus(harness.execute)
        bus.setHistory(history)
        with self.assertRaises(RuntimeError):
            bus.execute("fail")
        self.assertFalse(history.canUndo())

    def test_qmainwindow_checkpoint_restores_runtime_dock_registry(self):
        window = QMainWindow.__new__(QMainWindow)
        manager = _Manager()
        dock = _Dock("console")
        manager.addDockWidget("console", dock, title="Console", area="bottom")
        window._dock_manager = manager
        window._dock_keys = {id(dock): "console"}
        window._ensure_dock_manager = lambda: manager
        detached = []
        synced = []
        window._detach_dock_controller = lambda item: detached.append(item)
        window._sync_dock_controller_from_manager = lambda item, key=None: synced.append((item, key)) or True

        checkpoint = window._capture_dock_history_checkpoint()
        manager.removeDockWidget("console")
        window._dock_keys.clear()
        self.assertTrue(window._restore_dock_history_checkpoint(checkpoint))
        self.assertIs(manager._entries["console"]["window"], dock)
        self.assertEqual(window._dock_keys[id(dock)], "console")
        self.assertEqual(synced[-1], (dock, "console"))

    def test_async_transition_records_only_after_commit(self):
        harness = _StateHarness()
        history = QDockCommandHistory(harness.capture, harness.restore)
        transition = QDockTransition.float(
            present=lambda ctx: True,
            transfer=lambda ctx: harness.value.append("floating") or True)
        self.assertTrue(history.trackTransition(transition))
        self.assertTrue(transition.begin({}))
        self.assertFalse(history.canUndo())
        self.assertTrue(transition.complete())
        self.assertTrue(history.canUndo())
        self.assertTrue(history.undo())
        self.assertEqual(harness.value, [])

    def test_history_limit_and_diagnostics(self):
        harness = _StateHarness()
        history = QDockCommandHistory(harness.capture, harness.restore, limit=2)
        bus = QMainWindowDockCommandBus(harness.execute)
        bus.setHistory(history)
        for value in (1, 2, 3):
            bus.execute("append", value=value)
        self.assertEqual(history.snapshot()["undoCount"], 2)
        self.assertTrue(history.canUndo())

    def test_version(self):
        self.assertGreaterEqual(tuple(map(int, DearUIQt.__version__.split("."))), (1, 102, 0))


if __name__ == "__main__":
    unittest.main()
