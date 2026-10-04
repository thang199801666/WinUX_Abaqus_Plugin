"""Actual DPG item behavior, independent of a viewport or SSH session."""
import threading
import unittest
from types import SimpleNamespace
from unittest.mock import patch

try:
    import dearpygui.dearpygui as dpg
except (ImportError, OSError) as exc:
    raise unittest.SkipTest("native DPG unavailable; use tools/run_native_tests.py: {}".format(exc)) from exc

from WinUx.widgets import QLabel, QLineEdit, QPushButton, QProgressBar, QVBoxLayout, QSignalBlocker, QCheckBox, QGridLayout
from WinUx.dialogs.qt_dialog import QtDialog
from WinUx.dialogs.login_form import LoginForm
from WinUx.components import qt_combo_box
from tests.test_console_renderer import fixture as console_renderer_fixture
from WinUx.dialogs.job_schedule_form import JobScheduleDialog
from WinUx.dialogs.progress_form import ProgressDialog
from WinUx.components.explorer_drag_preview import DragPreviewHelper
from WinUx.components.explorer_list_model import ListViewItem


class NativeWrapperTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        dpg.create_context()

    @classmethod
    def tearDownClass(cls):
        dpg.destroy_context()

    def setUp(self):
        self.pending = []
        self.window = dpg.add_window()
        self.layout = QVBoxLayout(parent=self.window, after=self.after, backend=dpg)

    def after(self, delay, callback, *args):
        self.pending.append((callback, args))

    def tearDown(self):
        self.layout.delete()
        for callback, args in self.pending:
            callback(*args)
        dpg.delete_item(self.window)

    def test_inherited_native_backend_and_parent_disposal(self):
        label = QLabel("Ready", parent=self.layout)
        self.assertEqual(dpg.get_item_parent(label.tag), self.layout.tag)
        label.setText("Loaded")
        self.assertEqual(dpg.get_value(label.tag), "Loaded")
        self.layout.delete()
        self.assertFalse(dpg.does_item_exist(label.tag))

    def test_native_grid_cells_reparent_and_delete(self):
        first = QGridLayout(3, parent=self.layout)
        second = QGridLayout(2, parent=self.layout)
        label = QLabel('Cell', parent=first.cell(1, 2))
        self.assertEqual(dpg.get_item_parent(label.tag), first.cell(1, 2).tag)
        self.assertIs(first.cell(1, 2), label.parent)
        second.addWidget(label, 0, 1)
        self.assertEqual(dpg.get_item_parent(label.tag), second.cell(0, 1).tag)
        first.delete()
        self.assertTrue(dpg.does_item_exist(label.tag))
        second.delete()
        self.assertFalse(dpg.does_item_exist(label.tag))

    def test_dialog_field_grid_and_failed_builder_cleanup(self):
        dialog = QtDialog(SimpleNamespace(after=self.after), 'Grid form')
        try:
            field = dialog.field('Name', 'value')
            grid = dialog._widget_owner._children[-1]
            self.assertIsInstance(grid, QGridLayout)
            self.assertEqual(dpg.get_item_parent(field), grid.cell(0, 1).tag)
            self.assertEqual(dpg.get_value(field), 'value')
            label = grid.cell(0, 0)._children[0]
            self.assertEqual(dpg.get_value(label.tag), 'Name')
            previous = len(dialog._widget_owner._children)
            def fail():
                dpg.add_text('temporary')
                raise ValueError('builder failed')
            with self.assertRaises(ValueError):
                dialog.labeled_widget('Failed', fail)
            self.assertEqual(len(dialog._widget_owner._children), previous)
            self.assertTrue(dpg.does_item_exist(field))
        finally:
            dialog.destroy()
        self.assertFalse(dpg.does_item_exist(field))

    def test_native_button_callback_enable_and_size(self):
        button = QPushButton("Run", parent=self.layout, width=120, height=28)
        clicked = []
        button.clicked.connect(lambda: clicked.append(True))
        config = dpg.get_item_configuration(button.tag)
        self.assertEqual((config["width"], config["height"]), (120, 28))
        config["callback"](button.tag, None, None)
        self.assertEqual(clicked, [True])
        button.setEnabled(False)
        self.assertFalse(dpg.get_item_configuration(button.tag)["enabled"])

    def test_native_lineedit_blocking_and_user_callback(self):
        edit = QLineEdit("old", parent=self.layout)
        changed = []
        edit.textChanged.connect(changed.append)
        with QSignalBlocker(edit):
            edit.setText("synced")
        self.assertEqual(edit.text(), "synced")
        self.assertEqual(changed, [])
        callback = dpg.get_item_configuration(edit.tag)["callback"]
        dpg.set_value(edit.tag, "typed")
        callback(edit.tag, "typed", None)
        self.assertEqual(changed, ["typed"])

    def test_native_worker_progress_coalesces_and_clamps(self):
        bar = QProgressBar(parent=self.layout)
        worker = threading.Thread(target=lambda: [bar.setValue(i / 10) for i in range(20)])
        worker.start()
        worker.join()
        self.assertEqual(len(self.pending), 1)
        callback, args = self.pending.pop()
        callback(*args)
        self.assertEqual(dpg.get_value(bar.tag), 1.0)
        bar.setFormat("100%")
        self.assertEqual(dpg.get_item_configuration(bar.tag)["overlay"], "100%")

    def test_native_checkbox_blocking_callback_and_pending_value(self):
        box = QCheckBox("Option", checked=True, parent=self.layout)
        changes = []
        box.toggled.connect(changes.append)
        self.assertTrue(box.isChecked())
        with QSignalBlocker(box):
            box.setChecked(False)
        self.assertFalse(box.isChecked())
        self.assertEqual(changes, [])
        worker = threading.Thread(target=box.setChecked, args=(True,))
        worker.start()
        worker.join()
        callback = dpg.get_item_configuration(box.tag)["callback"]
        callback(box.tag, False, None)
        for cb, args in self.pending:
            cb(*args)
        self.pending.clear()
        self.assertFalse(box.isChecked())
        dpg.set_value(box.tag, True)
        callback(box.tag, True, None)
        self.assertEqual(changes, [True])

    def test_native_lineedit_interaction_invalidates_old_worker_value(self):
        edit = QLineEdit("initial", parent=self.layout)
        worker = threading.Thread(target=edit.setText, args=("stale",))
        worker.start()
        worker.join()
        dpg.set_value(edit.tag, "typed")
        dpg.get_item_configuration(edit.tag)["callback"](edit.tag, "typed", None)
        for cb, args in self.pending:
            cb(*args)
        self.pending.clear()
        self.assertEqual(edit.text(), "typed")

    def test_login_remember_checkbox_preserves_snapshot_and_owned_cleanup(self):
        with patch("WinUx.dialogs.login_form.LoginPreferences"):
            dialog = LoginForm(SimpleNamespace(after=self.after), lambda *args: None,
                initial={"host": "server", "username": "user", "port": "22", "remember": True})
        checkbox = dialog._remember_widget
        try:
            self.assertEqual(dialog.remember, checkbox.tag)
            self.assertIn(checkbox, dialog._widget_owner._children)
            self.assertTrue(dialog._snapshot()["remember"])
            checkbox.setChecked(False)
            self.assertFalse(dialog._snapshot()["remember"])
        finally:
            dialog.destroy()
        self.assertTrue(checkbox._deleted)
        self.assertFalse(dpg.does_item_exist(checkbox.tag))

    def test_combo_theme_cache_uses_context_safe_aliases(self):
        for factory in (qt_combo_box._input_theme, qt_combo_box._disabled_input_theme,
                        qt_combo_box._combo_theme, qt_combo_box._disabled_combo_theme):
            tag = factory()
            self.assertIsInstance(tag, str)
            self.assertEqual(dpg.get_item_info(tag)["type"], "mvAppItemType::mvTheme")
            dpg.delete_item(tag)
            self.assertEqual(factory(), tag)
            self.assertTrue(dpg.does_item_exist(tag))

    def test_console_blink_preserves_real_native_text_items(self):
        view, _, renderer = console_renderer_fixture()
        renderer.backend = dpg
        view.content = dpg.add_child_window(parent=self.window, width=640, height=240)
        view.canvas = dpg.add_drawlist(parent=view.content, width=640, height=240)
        view._current_line_fill = dpg.draw_rectangle((0, 0), (10, 10), parent=view.canvas)
        view._caret = dpg.draw_rectangle((0, 0), (10, 2), parent=view.canvas)
        with patch.object(dpg, 'get_item_state', return_value={'rect_size': (640, 240)}), \
             patch('WinUx.components.console_renderer.time.monotonic', return_value=0):
            renderer.paint()
        items = tuple(view._line_items)
        self.assertTrue(items)
        with patch.object(dpg, 'get_item_state', return_value={'rect_size': (640, 240)}), \
             patch('WinUx.components.console_renderer.time.monotonic', return_value=.51), \
             patch.object(dpg, 'draw_text', wraps=dpg.draw_text) as draws, \
             patch.object(dpg, 'delete_item', wraps=dpg.delete_item) as deletes:
            renderer.paint()
            draws.assert_not_called()
            deletes.assert_not_called()
        self.assertTrue(all(dpg.does_item_exist(item) for item in items))
        self.assertFalse(dpg.get_item_configuration(view._caret)['show'])
        self.assertEqual(dpg.get_item_configuration(items[0])['text'], 'line1')

    def test_native_visibility_and_late_callback_disposal(self):
        label = QLabel("old", parent=self.layout)
        label.setVisible(False)
        self.assertFalse(dpg.get_item_configuration(label.tag)["show"])
        worker = threading.Thread(target=label.setText, args=("late",))
        worker.start()
        worker.join()
        label.delete()
        callback, args = self.pending.pop()
        callback(*args)
        self.assertFalse(dpg.does_item_exist(label.tag))

    def test_schedule_unchanged_snapshot_skips_native_writes(self):
        rows = [("job", "run", "2030-01-01", "1s", "waiting", "run", "1")]
        dialog = JobScheduleDialog(SimpleNamespace(after=self.after), lambda: rows, lambda *args: None)
        try:
            with patch.object(dpg, "set_value", wraps=dpg.set_value) as writes, \
                 patch.object(dpg, "configure_item", wraps=dpg.configure_item) as configs:
                dialog.set_rows(rows)
                writes.assert_not_called()
                configs.assert_not_called()
            changed = [rows[0][:3] + ("0s",) + rows[0][4:]]
            with patch.object(dpg, "set_value", wraps=dpg.set_value) as writes:
                dialog.set_rows(changed)
                writes.assert_called_once_with(dialog._row_items[0][0][3], "0s")
        finally:
            dialog.destroy()

    def test_schedule_rebuild_releases_owned_row_buttons(self):
        rows = [("job", "run", "2030-01-01", "1s", "waiting", "run", "1")]
        dialog = JobScheduleDialog(SimpleNamespace(after=self.after), lambda: rows, lambda *args: None)
        try:
            footer_count = len(dialog._widget_owner._children) - 2
            stale = tuple(dialog._widget_owner._children[-2:])
            for i in range(10):
                dialog.set_rows([rows[0][:6] + (str(i + 2),)])
                self.assertEqual(len(dialog._widget_owner._children), footer_count + 2)
            self.assertTrue(all(widget._deleted for widget in stale))
            dialog.set_rows([])
            self.assertEqual(len(dialog._widget_owner._children), footer_count)
        finally:
            dialog.destroy()

    def test_drag_preview_is_lazy_and_releases_native_draw_items(self):
        preview = DragPreviewHelper("native_resource_test")
        self.assertIsNone(preview._drawlist)
        preview.set_theme({"drag_text": (1, 2, 3, 255)})
        preview.begin([ListViewItem("file.inp")])
        self.assertTrue(preview.active)
        self.assertTrue(dpg.does_item_exist(preview._drawlist))
        drawlist = preview._drawlist
        preview.end()
        self.assertFalse(preview.active)
        self.assertEqual(preview.items, [])
        preview.destroy()
        self.assertFalse(dpg.does_item_exist(drawlist))

    def test_external_cancelling_command_blocks_later_progress(self):
        dialog = ProgressDialog(SimpleNamespace(after=self.after), "Upload", threading.Event())
        try:
            dialog.handle_command("cancelling")
            dialog.handle_command("progress", "stale", .5, .5, "stale stats")
            self.assertEqual(dpg.get_value(dialog.current), "Cancelling...")
            self.assertTrue(dialog._cancelling)
        finally:
            dialog.destroy()
