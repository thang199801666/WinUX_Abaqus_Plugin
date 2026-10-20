"""Verify native ordering, form containment and composite-control movement."""
import sys
from types import SimpleNamespace
import unittest

if sys.platform != 'win32':
    raise unittest.SkipTest('requires Windows Dear PyGui')
try:
    from WinUx.ui.components.explorer_list_view import dpg
except (ImportError, OSError) as exc:
    raise unittest.SkipTest('native Dear PyGui unavailable') from exc

from WinUx.ui import QVBoxLayout, QHBoxLayout, QFormLayout, QLabel, QLineEdit, QSpinBox
from WinUx.dialogs.qt_dialog import QtDialog


class NativeLayoutApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        dpg.create_context()
        dpg.create_viewport(title='Qt-style layouts regression', width=700, height=440)
        dpg.setup_dearpygui()
        dpg.show_viewport()

    @classmethod
    def tearDownClass(cls):
        dpg.destroy_context()

    def setUp(self):
        self.window = dpg.add_window(width=640, height=360)

    def tearDown(self):
        dpg.delete_item(self.window)

    def test_box_insertion_reorders_native_items_and_transfers_ownership(self):
        first = QVBoxLayout(parent=self.window, backend=dpg)
        second = QHBoxLayout(parent=self.window, backend=dpg)
        a = QLabel('A', parent=first)
        b = QLabel('B', parent=first)
        first.insertWidget(0, b)
        self.assertEqual(dpg.get_item_children(first.tag, 1), [b.tag, a.tag])
        self.assertIs(first.itemAt(0).widget(), b)
        second.addWidget(b)
        self.assertIs(b.parent, second)
        first.delete()
        self.assertTrue(dpg.does_item_exist(b.tag))
        self.assertFalse(dpg.does_item_exist(a.tag))
        second.delete()
        self.assertFalse(dpg.does_item_exist(b.tag))

    def test_take_at_preserves_native_widget_after_layout_disposal(self):
        layout = QVBoxLayout(parent=self.window, backend=dpg)
        label = QLabel('Retained', parent=layout)
        item = layout.takeAt(0)
        self.assertIs(item.widget(), label)
        self.assertEqual(dpg.get_item_parent(label.tag), self.window)
        layout.delete()
        self.assertTrue(dpg.does_item_exist(label.tag))
        label.delete()

    def test_form_moves_entire_spin_box_and_preserves_numeric_editor(self):
        form = QFormLayout(parent=self.window, backend=dpg)
        editor = QLineEdit('job', parent=self.window, backend=dpg)
        spin = QSpinBox(8, parent=self.window, backend=dpg, minimum=1, maximum=32)
        editor_parent = dpg.get_item_parent(spin.tag)
        form.addRow('Job name', editor)
        form.addRow('CPUs', spin)
        self.assertEqual(form.labelForField(editor).text(), 'Job name')
        self.assertEqual(dpg.get_item_parent(editor.tag), form.cell(0, form.FieldRole).tag)
        self.assertEqual(dpg.get_item_parent(spin.container), form.cell(1, form.FieldRole).tag)
        self.assertEqual(dpg.get_item_parent(spin.tag), editor_parent)
        spin.stepUp()
        self.assertEqual(spin.value(), 9)
        for _ in range(3):
            dpg.render_dearpygui_frame()
        self.assertGreater(dpg.get_item_rect_size(spin.container)[0], 0)
        self.assertGreater(dpg.get_item_rect_size(editor.tag)[0], 0)
        form.delete()
        self.assertFalse(dpg.does_item_exist(spin.container))
        self.assertFalse(dpg.does_item_exist(editor.tag))

    def test_delete_later_disposes_native_control_once(self):
        queued = []
        label = QLabel('Deferred', parent=self.window, backend=dpg,
                       after=lambda delay, callback, *args: queued.append((callback, args)))
        label.deleteLater()
        label.deleteLater()
        self.assertTrue(dpg.does_item_exist(label.tag))
        self.assertEqual(len(queued), 1)
        callback, args = queued.pop()
        callback(*args)
        self.assertFalse(dpg.does_item_exist(label.tag))

    def test_dialog_action_keeps_its_owned_layout_parent(self):
        dialog = QtDialog(SimpleNamespace(after=lambda *args: None), 'Owned layout')
        try:
            layout = dialog.own_widget(QHBoxLayout(parent=dialog.content, backend=dpg))
            button = dialog.action('Apply', lambda: None, parent=layout)
            self.assertEqual(layout.count(), 1)
            widget = layout.itemAt(0).widget()
            self.assertEqual(widget.tag, button)
            self.assertIs(widget.parent, layout)
            self.assertEqual(dpg.get_item_parent(button), layout.tag)
            dialog.destroy()
            self.assertTrue(widget._deleted)
            self.assertFalse(dpg.does_item_exist(button))
        finally:
            dialog.destroy()
