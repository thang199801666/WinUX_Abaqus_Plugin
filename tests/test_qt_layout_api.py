import threading
import unittest
from unittest.mock import Mock

from WinUx.ui import QObject, QLabel, QLineEdit, QVBoxLayout, QHBoxLayout, QGridLayout, QFormLayout


class LayoutApiTests(unittest.TestCase):
    def setUp(self):
        self.backend = Mock()
        self.backend.add_group.side_effect = iter(range(100, 200))
        self.backend.add_text.side_effect = iter(range(200, 300))
        self.backend.add_input_text.side_effect = iter(range(300, 400))
        self.backend.add_table.return_value = 400
        self.backend.add_table_row.side_effect = iter(range(500, 600))
        self.backend.get_item_parent.return_value = 10

    def test_box_insert_reorder_and_nested_layout_lookup(self):
        box = QVBoxLayout(parent=10, backend=self.backend)
        first = QLabel('first', parent=box)
        second = QLabel('second', parent=box)
        helper = QObject(box)
        box.insertWidget(0, second)
        self.assertEqual(box.count(), 2)
        self.assertIs(box.itemAt(0).widget(), second)
        self.assertEqual(box.indexOf(first), 1)
        self.assertIsNone(box.itemAt(-1))
        self.backend.move_item.assert_called_with(second.tag, parent=box.tag, before=first.tag)
        nested = QHBoxLayout(parent=10, backend=self.backend)
        box.addLayout(nested)
        self.assertIs(box.itemAt(2).layout(), nested)
        self.assertIsNone(box.itemAt(2).widget())
        self.assertEqual(box.indexOf(helper), -1)

    def test_take_keeps_widget_alive_after_old_layout_is_deleted(self):
        box = QVBoxLayout(parent=10, backend=self.backend)
        label = QLabel('keep', parent=box)
        item = box.takeAt(0)
        self.assertIs(item.widget(), label)
        self.assertEqual(box.count(), 0)
        self.backend.move_item.assert_called_with(label.tag, parent=10)
        box.delete()
        self.assertFalse(label._deleted)
        label.delete()
        self.assertTrue(item.isEmpty())

    def test_cross_backend_and_cycle_errors_do_not_reparent(self):
        box = QVBoxLayout(parent=10, backend=self.backend)
        foreign = QLabel('foreign', backend=Mock())
        self.backend.move_item.reset_mock()
        with self.assertRaises(ValueError):
            box.addWidget(foreign)
        with self.assertRaises(ValueError):
            box.addLayout(box)
        self.backend.move_item.assert_not_called()

    def test_grid_inspection_and_removal_are_row_major(self):
        grid = QGridLayout(2, parent=10, backend=self.backend)
        later = QLabel('later', backend=self.backend)
        first = QLabel('first', backend=self.backend)
        grid.addWidget(later, 2, 1)
        grid.addWidget(first, 0, 0)
        self.assertEqual(grid.rowCount(), 3)
        self.assertEqual(grid.columnCount(), 2)
        self.assertEqual(grid.count(), 2)
        self.assertEqual(grid.getItemPosition(0), (0, 0, 1, 1))
        self.assertIs(grid.itemAtPosition(2, 1).widget(), later)
        self.assertIsNone(grid.itemAtPosition(1, 1))
        self.assertIs(grid.removeWidget(later).widget(), later)
        self.assertEqual(grid.indexOf(later), -1)

    def test_form_creates_owned_label_and_accepts_nested_field_layout(self):
        form = QFormLayout(parent=10, backend=self.backend)
        field = QLineEdit('value', backend=self.backend)
        self.assertEqual(form.addRow('Name', field), 0)
        label = form.labelForField(field)
        self.assertIsInstance(label, QLabel)
        self.assertEqual(label._properties['value'], 'Name')
        nested = QHBoxLayout(parent=10, backend=self.backend)
        form.addRow('Options', nested)
        self.assertIs(form.itemAtPosition(1, form.FieldRole).layout(), nested)
        form.delete()
        self.assertTrue(field._deleted)
        self.assertTrue(label._deleted)
        self.assertTrue(nested._deleted)

    def test_constructing_child_on_worker_fails_before_native_creation(self):
        box = QVBoxLayout(parent=10, backend=self.backend)
        errors = []

        def create():
            try:
                QLabel(parent=box)
            except RuntimeError as exc:
                errors.append(str(exc))

        worker = threading.Thread(target=create)
        worker.start()
        worker.join()
        self.assertEqual(len(errors), 1)
        self.backend.add_text.assert_not_called()


class QObjectLifecycleApiTests(unittest.TestCase):
    def test_find_child_and_children_respect_names_and_reparenting(self):
        backend = Mock()
        root = QObject()
        box = QVBoxLayout(parent=root, backend=backend)
        label = QLabel('name', parent=box)
        label.setObjectName('status')
        self.assertIs(root.findChild(QLabel, 'status'), label)
        children = box.children()
        children.clear()
        self.assertEqual(box.children(), [label])
        label.setParent(root)
        self.assertIsNone(box.findChild(QLabel))
        self.assertEqual(root.findChildren(QLabel), [label])

    def test_delete_later_is_idempotent_and_parent_disposal_invalidates_it(self):
        queued = []
        root = QObject(after=lambda delay, callback, *args: queued.append((callback, args)))
        child = QObject(root)
        destroyed = Mock()
        child.destroyed.connect(destroyed)
        child.deleteLater()
        child.deleteLater()
        self.assertEqual(len(queued), 1)
        self.assertFalse(child._deleted)
        root.delete()
        callback, args = queued.pop()
        callback(*args)
        destroyed.assert_called_once_with(child)

    def test_signal_block_state_can_be_queried(self):
        obj = QObject()
        self.assertFalse(obj.signalsBlocked())
        obj.blockSignals(True)
        self.assertTrue(obj.signalsBlocked())
