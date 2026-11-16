import unittest

import DearUIQt
from DearUIQt.gui import QUndoCommand, QUndoStack


class _SetValue(QUndoCommand):
    def __init__(self, box, value, text="Set Value"):
        super().__init__(text)
        self.box = box
        self.old = box[0]
        self.value = value

    def redo(self):
        self.box[0] = self.value

    def undo(self):
        self.box[0] = self.old


class _MergeValue(_SetValue):
    def id(self):
        return 7

    def mergeWith(self, other):
        if not isinstance(other, _MergeValue):
            return False
        self.value = other.value
        self.setText("Set %s" % other.value)
        return True


class UndoCommandM5vTests(unittest.TestCase):
    def test_native_stack_push_undo_redo_and_actions(self):
        box = [0]
        stack = QUndoStack()
        undo = stack.createUndoAction(prefix="Undo")
        stack.push(_SetValue(box, 4, "Set Four"))
        self.assertEqual(box[0], 4)
        self.assertEqual(stack.count(), 1)
        self.assertEqual(stack.index(), 1)
        self.assertEqual(stack.undoText(), "Set Four")
        self.assertEqual(undo.text(), "Undo Set Four")
        self.assertTrue(stack.undo())
        self.assertEqual(box[0], 0)
        self.assertEqual(stack.redoText(), "Set Four")
        self.assertTrue(stack.redo())
        self.assertEqual(box[0], 4)

    def test_merge_coalesces_adjacent_commands(self):
        box = [0]
        stack = QUndoStack()
        stack.push(_MergeValue(box, 1, "Set 1"))
        stack.push(_MergeValue(box, 2, "Set 2"))
        stack.push(_MergeValue(box, 3, "Set 3"))
        self.assertEqual(box[0], 3)
        self.assertEqual(stack.count(), 1)
        self.assertEqual(stack.undoText(), "Set 3")
        self.assertTrue(stack.undo())
        self.assertEqual(box[0], 0)
        self.assertTrue(stack.redo())
        self.assertEqual(box[0], 3)

    def test_macro_is_one_undo_step(self):
        a = [0]
        b = [0]
        stack = QUndoStack()
        stack.beginMacro("Update Pair")
        stack.push(_SetValue(a, 10, "A"))
        stack.push(_SetValue(b, 20, "B"))
        self.assertTrue(stack.endMacro())
        self.assertEqual((a[0], b[0]), (10, 20))
        self.assertEqual(stack.count(), 1)
        self.assertEqual(stack.command(0).childCount(), 2)
        self.assertEqual(stack.undoText(), "Update Pair")
        self.assertTrue(stack.undo())
        self.assertEqual((a[0], b[0]), (0, 0))
        self.assertTrue(stack.redo())
        self.assertEqual((a[0], b[0]), (10, 20))

    def test_clean_index_redo_branch_and_undo_limit(self):
        box = [0]
        stack = QUndoStack()
        stack.push(_SetValue(box, 1, "One"))
        stack.setClean()
        self.assertTrue(stack.isClean())
        stack.push(_SetValue(box, 2, "Two"))
        self.assertFalse(stack.isClean())
        stack.undo()
        self.assertTrue(stack.isClean())
        stack.push(_SetValue(box, 3, "Three"))
        self.assertFalse(stack.canRedo())
        stack.setUndoLimit(2)
        stack.push(_SetValue(box, 4, "Four"))
        self.assertEqual(stack.count(), 2)
        self.assertEqual(stack.index(), 2)

    def test_composite_parent_command(self):
        box = [0]
        parent = QUndoCommand("Composite")
        _SetValue(box, 1, "One")  # standalone, not executed
        first = _SetValue(box, 2, "Two")
        second = _SetValue(box, 3, "Three")
        parent._append_child(first)
        parent._append_child(second)
        stack = QUndoStack()
        stack.push(parent)
        self.assertEqual(box[0], 3)
        self.assertTrue(stack.undo())
        self.assertEqual(box[0], 0)

    def test_history_adapter_mode_rejects_native_push_without_breaking_history(self):
        class History:
            def __init__(self):
                from DearUIQt.core import Signal
                self.changed = Signal()
            def canUndo(self): return False
            def canRedo(self): return False
            def snapshot(self): return {"undoCount": 0, "redoCount": 0}
        stack = QUndoStack(History())
        with self.assertRaises(RuntimeError):
            stack.push(QUndoCommand("Nope"))
        self.assertEqual(stack.count(), 0)

    def test_version_and_exports(self):
        self.assertGreaterEqual(tuple(map(int, DearUIQt.__version__.split('.'))), (1, 104, 0))
        self.assertIs(DearUIQt.QUndoCommand, QUndoCommand)


if __name__ == "__main__":
    unittest.main()
