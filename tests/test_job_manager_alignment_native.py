"""Compare every editable Job Manager cell against the real Segoe UI grid."""
from pathlib import PurePosixPath
from types import SimpleNamespace
import sys
import unittest

if sys.platform != 'win32':
    raise unittest.SkipTest('requires Windows Dear PyGui')
try:
    from WinUx.ui.components.explorer_list_view import dpg
except (ImportError, OSError) as exc:
    raise unittest.SkipTest('native Dear PyGui unavailable') from exc

from WinUx.dialogs.job_manager_form import JobManagerDialog
from WinUx.dialogs.qt_dialog import QtDialog
from WinUx.ui import QGridLayout, QFormLayout, QLabel, QLineEdit
from WinUx.ui.appearance import configure_ui_context
from WinUx.runtime.dpg_callbacks import run_callback_jobs


class JobManagerAlignmentTests(unittest.TestCase):
    def test_all_cell_centres_and_editor_edges_align_across_rows_and_modes(self):
        dpg.create_context()
        try:
            view = SimpleNamespace(after=lambda *args: None)
            configure_ui_context(view)
            paths = [PurePosixPath('/work/model_%d.inp' % i) for i in range(3)]
            form = JobManagerDialog(view, paths, lambda *args: None, lambda *args: None)
            dpg.configure_item(form.tag, modal=False, no_title_bar=True)
            dpg.create_viewport(title='Job Manager alignment regression', width=1050, height=400)
            dpg.setup_dearpygui()
            dpg.show_viewport()
            dpg.set_primary_window(form.tag, True)

            def pump():
                for _ in range(4):
                    dpg.render_dearpygui_frame()
                    run_callback_jobs(dpg.get_callback_queue() or [])

            def assert_geometry():
                row_tops = []
                for row in form.rows_by_path.values():
                    reference_y = dpg.get_item_rect_min(row['version'])[1]
                    reference_height = dpg.get_item_rect_size(row['version'])[1]
                    self.assertEqual(reference_height, 26)
                    centre = reference_y + reference_height / 2
                    row_tops.append(reference_y)
                    for key in ('run', 'name', 'version', 'cpus', 'precision', 'overwrite', 'schedule', 'time'):
                        y = dpg.get_item_rect_min(row[key])[1]
                        height = dpg.get_item_rect_size(row[key])[1]
                        self.assertAlmostEqual(y + height / 2, centre, delta=.5, msg=key)
                    for key in ('precision', 'schedule', 'time'):
                        self.assertEqual(dpg.get_item_rect_min(row[key])[1], reference_y, key)
                        self.assertEqual(dpg.get_item_rect_size(row[key])[1], reference_height, key)
                    shell = form._control_wrappers[row['cpus']].container
                    # scrollY tables create an internal ImGui window absent
                    # from DPG's parent tree. The enclosing group's rendered
                    # rectangle is the authoritative screen-space shell origin.
                    cell = dpg.get_item_parent(shell)
                    self.assertEqual(dpg.get_item_rect_min(cell)[1], reference_y)
                    self.assertEqual(dpg.get_item_rect_size(shell)[1], reference_height)
                self.assertEqual([row_tops[i+1] - row_tops[i] for i in range(2)], [form.ROW_HEIGHT] * 2)

            for width in (1050, 1250):
                dpg.configure_viewport(0, width=width)
                for mode in ('Now', 'Run After', 'Run At', 'Now'):
                    for path in paths:
                        dpg.set_value(form.rows_by_path[path]['schedule'], mode)
                        form._schedule_changed(None, mode, path)
                    pump()
                    assert_geometry()
                    for row in form.rows_by_path.values():
                        self.assertEqual(dpg.get_item_configuration(row['time'])['enabled'], mode != 'Now')

            path = paths[0]
            form._schedule_changed(None, 'Run After', path)
            row = form.rows_by_path[path]
            editor = form._control_wrappers[row['time']]
            dpg.set_value(row['time'], '01:00:00')
            editor._changed(row['time'], '01:00:00', path)
            self.assertFalse(row['live'])
            self.assertEqual(row['saved']['Run After'], '01:00:00')
        finally:
            dpg.destroy_context()

    def test_shared_form_labels_align_with_line_combo_and_spin_editors(self):
        dpg.create_context()
        try:
            view = SimpleNamespace(after=lambda *args: None)
            configure_ui_context(view)
            form = QtDialog(view, 'Form alignment', 680, 420)
            table = form.form_layout()
            editors = [
                form.form_layout_row(table, 'Name', lambda parent: form.line_edit('Model', parent=parent)),
                form.form_layout_row(table, 'Version', lambda parent: form.combo(['abq2026'], parent=parent)),
                form.form_layout_row(table, 'CPUs', lambda parent: form.spin_int(8, parent=parent)),
            ]
            single = form.field('Single field', 'Text')
            wrapped = form.own_widget(QFormLayout(parent=form.content, backend=dpg))
            wrapped_editor = QLineEdit('Value', parent=form.content, backend=dpg)
            wrapped.addRow('Wrapped form', wrapped_editor)
            dpg.configure_item(form.tag, modal=False, no_title_bar=True)
            dpg.create_viewport(title='Shared form alignment regression', width=700, height=460)
            dpg.setup_dearpygui()
            dpg.show_viewport()
            dpg.set_primary_window(form.tag, True)
            for _ in range(4):
                dpg.render_dearpygui_frame()
                run_callback_jobs(dpg.get_callback_queue() or [])
            for row, editor in zip(dpg.get_item_children(table, 1), editors):
                label_cell = dpg.get_item_children(row, 1)[0]
                label = dpg.get_item_children(label_cell, 1)[0]
                label_y = dpg.get_item_rect_min(label)[1]
                label_height = dpg.get_item_rect_size(label)[1]
                editor_y = dpg.get_item_rect_min(editor)[1]
                editor_height = dpg.get_item_rect_size(editor)[1]
                self.assertAlmostEqual(label_y + label_height / 2, editor_y + editor_height / 2, delta=.5)
            grid = form._widget_owner.findChild(QGridLayout)
            label = grid.cell(0, 0).findChild(QLabel).tag
            self.assertAlmostEqual(
                dpg.get_item_rect_min(label)[1] + dpg.get_item_rect_size(label)[1] / 2,
                dpg.get_item_rect_min(single)[1] + dpg.get_item_rect_size(single)[1] / 2, delta=.5)
            label = wrapped.labelForField(wrapped_editor).tag
            self.assertAlmostEqual(
                dpg.get_item_rect_min(label)[1] + dpg.get_item_rect_size(label)[1] / 2,
                dpg.get_item_rect_min(wrapped_editor.tag)[1] + dpg.get_item_rect_size(wrapped_editor.tag)[1] / 2, delta=.5)
        finally:
            dpg.destroy_context()
