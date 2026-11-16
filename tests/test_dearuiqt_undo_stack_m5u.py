import unittest

import DearUIQt
from DearUIQt.core import QEvent, QKeyEvent, Qt
from DearUIQt.docking import QDockCommand, QDockCommandHistory, QMainWindowDockCommandBus
from DearUIQt.gui import QUndoStack
from DearUIQt.widgets.editors import ImGuiLineEdit
from DearUIQt.widgets import QMainWindow


class _Harness:
    def __init__(self):
        self.values = []

    def capture(self):
        return tuple(self.values)

    def restore(self, checkpoint):
        self.values[:] = list(checkpoint)
        return True

    def execute(self, command, payload):
        if command == "append":
            self.values.append(payload["value"])
            return True
        return False


class UndoStackM5uTests(unittest.TestCase):
    def test_stack_tracks_history_text_index_and_state(self):
        harness = _Harness()
        history = QDockCommandHistory(harness.capture, harness.restore)
        stack = QUndoStack(history)
        bus = QMainWindowDockCommandBus(harness.execute)
        bus.setHistory(history)
        changes = []
        stack.indexChanged.connect(lambda value: changes.append(value))

        self.assertFalse(stack.canUndo())
        self.assertEqual(stack.undoText(), "")
        self.assertTrue(bus.execute("append", value="a"))
        self.assertEqual(stack.index(), 1)
        self.assertEqual(stack.count(), 1)
        self.assertEqual(stack.undoText(), "Append")
        self.assertTrue(stack.canUndo())
        self.assertIn(1, changes)

        self.assertTrue(stack.undo())
        self.assertEqual(stack.index(), 0)
        self.assertEqual(stack.redoText(), "Append")
        self.assertTrue(stack.canRedo())
        self.assertTrue(stack.redo())
        self.assertEqual(harness.values, ["a"])

    def test_undo_redo_actions_follow_stack_and_trigger_history(self):
        harness = _Harness()
        history = QDockCommandHistory(harness.capture, harness.restore)
        stack = QUndoStack(history)
        bus = QMainWindowDockCommandBus(harness.execute)
        bus.setHistory(history)
        undo = stack.createUndoAction(prefix="Undo")
        redo = stack.createRedoAction(prefix="Redo")

        self.assertFalse(undo.isEnabled())
        self.assertFalse(redo.isEnabled())
        self.assertEqual(undo.shortcut().toString(), "Ctrl+Z")
        self.assertEqual(redo.shortcut().toString(), "Ctrl+Shift+Z")

        bus.execute("append", value="x")
        self.assertTrue(undo.isEnabled())
        self.assertEqual(undo.text(), "Undo Append")
        self.assertTrue(undo.trigger())
        self.assertEqual(harness.values, [])
        self.assertFalse(undo.isEnabled())
        self.assertTrue(redo.isEnabled())
        self.assertEqual(redo.text(), "Redo Append")
        self.assertTrue(redo.trigger())
        self.assertEqual(harness.values, ["x"])

    def test_command_metadata_supplies_action_text(self):
        harness = _Harness()
        history = QDockCommandHistory(harness.capture, harness.restore)
        before = history.capture()
        harness.values.append("console")
        command = QDockCommand("add", metadata={"text": "Add Console"})
        self.assertTrue(history.record(command, before, history.capture()))
        self.assertEqual(history.undoText(), "Add Console")
        stack = QUndoStack(history)
        action = stack.createUndoAction(prefix="Undo")
        self.assertEqual(action.text(), "Undo Add Console")

    def test_qmainwindow_exposes_one_stack_for_its_history(self):
        harness = _Harness()
        history = QDockCommandHistory(harness.capture, harness.restore)
        window = QMainWindow.__new__(QMainWindow)
        window._dock_command_history = history
        window._dock_undo_stack = None
        stack = window.dockUndoStack()
        self.assertIs(stack.history(), history)
        self.assertIs(window.dockUndoStack(), stack)

    def test_text_editor_keeps_standard_undo_shortcut(self):
        editor = ImGuiLineEdit.__new__(ImGuiLineEdit)
        event = QKeyEvent(QEvent.ShortcutOverride, Qt.Key_Z, Qt.ControlModifier)
        event.ignore()
        ImGuiLineEdit.shortcutOverrideEvent(editor, event)
        self.assertTrue(event.isAccepted())

        other = QKeyEvent(QEvent.ShortcutOverride, Qt.Key_F5, Qt.ControlModifier)
        other.accept()
        ImGuiLineEdit.shortcutOverrideEvent(editor, other)
        self.assertFalse(other.isAccepted())

    def test_version(self):
        self.assertGreaterEqual(tuple(map(int, DearUIQt.__version__.split("."))), (1, 103, 0))


if __name__ == "__main__":
    unittest.main()
