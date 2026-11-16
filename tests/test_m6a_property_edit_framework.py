import unittest

import DearUIQt
from DearUIQt.gui import QUndoStack, QPropertyEditCommand, QPropertyEditController
from DearUIQt.modelview.delegates import QStyledItemDelegate
from DearUIQt.core import Qt


class _Index:
    def __init__(self, model, row=0, column=0):
        self._model = model
        self._row = row
        self._column = column
    def data(self, role):
        return self._model.data(self, role)
    def row(self): return self._row
    def column(self): return self._column


class _Model:
    def __init__(self, value="old"):
        self.value = value
        self.writes = []
    def data(self, index, role):
        del index
        if role in (Qt.EditRole, Qt.DisplayRole):
            return self.value
        return None
    def setData(self, index, value, role):
        del index
        if role != Qt.EditRole:
            return False
        self.value = value
        self.writes.append(value)
        return True


class _Editor:
    def __init__(self, text): self._text = text
    def text(self): return self._text


class PropertyEditFrameworkM6aTests(unittest.TestCase):
    def test_live_edit_cancel_restores_snapshot_without_history(self):
        box = [10]
        stack = QUndoStack()
        controller = QPropertyEditController(
            getter=lambda: box[0], setter=lambda value: box.__setitem__(0, value),
            undo_stack=stack, label="Edit value")
        controller.begin()
        controller.update(20, live=True)
        self.assertEqual(box[0], 20)
        self.assertTrue(controller.cancel())
        self.assertEqual(box[0], 10)
        self.assertEqual(stack.count(), 0)

    def test_commit_records_one_property_command_and_undo_redo(self):
        box = [1]
        stack = QUndoStack()
        controller = QPropertyEditController(
            getter=lambda: box[0], setter=lambda value: box.__setitem__(0, value),
            undo_stack=stack, label="Edit property")
        controller.begin()
        controller.update(7, live=True)
        self.assertTrue(controller.commit())
        self.assertEqual(stack.count(), 1)
        self.assertEqual(stack.undoText(), "Edit property")
        self.assertTrue(stack.undo())
        self.assertEqual(box[0], 1)
        self.assertTrue(stack.redo())
        self.assertEqual(box[0], 7)

    def test_repeated_property_edits_merge_with_same_key(self):
        box = [0]
        stack = QUndoStack()
        controller = QPropertyEditController(
            getter=lambda: box[0], setter=lambda value: box.__setitem__(0, value),
            undo_stack=stack, label="Nudge", merge_key=("value", 1), merge_window=10.0)
        controller.edit(1)
        controller.edit(2)
        controller.edit(3)
        self.assertEqual(stack.count(), 1)
        self.assertTrue(stack.undo())
        self.assertEqual(box[0], 0)
        self.assertTrue(stack.redo())
        self.assertEqual(box[0], 3)

    def test_table_delegate_records_model_command_not_editor_command(self):
        model = _Model("old")
        index = _Index(model)
        stack = QUndoStack()
        delegate = QStyledItemDelegate()
        delegate.setUndoStack(stack, label="Edit cell")
        self.assertTrue(delegate.setModelData(_Editor("new"), model, index))
        self.assertEqual(model.value, "new")
        self.assertEqual(stack.count(), 1)
        self.assertTrue(stack.undo())
        self.assertEqual(model.value, "old")
        self.assertTrue(stack.redo())
        self.assertEqual(model.value, "new")

    def test_command_export_and_version(self):
        self.assertIs(DearUIQt.QPropertyEditCommand, QPropertyEditCommand)
        self.assertIs(DearUIQt.QPropertyEditController, QPropertyEditController)
        self.assertGreaterEqual(tuple(map(int, DearUIQt.__version__.split('.'))), (1, 109, 0))


if __name__ == "__main__":
    unittest.main(verbosity=2)
