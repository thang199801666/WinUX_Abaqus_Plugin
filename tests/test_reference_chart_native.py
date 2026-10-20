"""Reference editor and overlay integration in a real Dear PyGui viewport."""
import tempfile
import time
import unittest
from unittest.mock import Mock, patch

import WinUx
import dearpygui.dearpygui as dpg

from WinUx.ui.components.job_plots import JobPlotsWindow
from WinUx.dialogs.floating_forms import create_form
from WinUx.dialogs.floating_runtime import ChildView, configure_context
from WinUx.dialogs.reference_chart_form import ReferenceChartDialog
from WinUx.runtime.dpg_callbacks import run_callback_jobs
from WinUx.services.reference_charts import ReferenceChartLibrary, parse_reference_text


class ReferenceChartNativeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.library = ReferenceChartLibrary(root=self.temp.name)
        self.view = ChildView()
        self.plots, self.dialogs = [], []
        dpg.create_context()
        configure_context(self.view)
        self.root = dpg.add_window(label="Reference chart check", width=1000, height=700)
        dpg.create_viewport(title="WinUx Reference Chart test", width=1000, height=700)
        dpg.set_primary_window(self.root, True)
        dpg.setup_dearpygui()
        dpg.show_viewport()

    def tearDown(self):
        for dialog in self.dialogs:
            if dialog.winfo_exists():
                dialog.finish(None)
        for plot in self.plots:
            plot.close()
        self.view.drain()
        dpg.destroy_context()
        self.temp.cleanup()

    def frame(self, count=4):
        for _ in range(count):
            self.view.drain()
            dpg.render_dearpygui_frame()
            run_callback_jobs(dpg.get_callback_queue() or [])
            time.sleep(0.005)

    def plot(self, name="one", **kwargs):
        panel = JobPlotsWindow(self.root, name, name, reference_library=self.library,
                               after=self.view.after, **kwargs)
        self.plots.append(panel)
        self.frame()
        return panel

    def dialog(self, result):
        form = ReferenceChartDialog(self.view, self.library.snapshot(), result)
        self.dialogs.append(form)
        self.frame()
        return form

    def test_empty_reference_button_opens_input_dialog(self):
        manage = Mock()
        panel = self.plot(on_reference_manage=manage)
        cfg = dpg.get_item_configuration(panel.reference_button)
        cfg["callback"](panel.reference_button, None, None)
        self.frame()
        manage.assert_called_once_with()

    def test_saved_reference_menu_and_overlay_work_without_odb_data(self):
        series = parse_reference_text("X,Measured A,Measured B\n0,1,3\n1,2,4")
        self.library.replace(series)
        panel = self.plot()
        panel._open_reference_menu()
        self.frame()
        self.assertTrue(dpg.is_item_shown(panel.reference_popup))
        first_id = series[0]["id"]
        self.assertTrue(dpg.get_value(panel._reference_menu_items[first_id]))
        self.assertEqual(dpg.get_value(panel._reference_series_tags[first_id])[:2], [[0, 1], [1, 2]])
        cfg = dpg.get_item_configuration(panel._reference_menu_items[first_id])
        cfg["callback"](panel._reference_menu_items[first_id], False, cfg["user_data"])
        self.frame()
        self.assertNotIn(first_id, panel._reference_series_tags)
        self.assertFalse(dpg.get_value(panel._reference_menu_items[first_id]))
        self.assertFalse(ReferenceChartLibrary(root=self.temp.name).snapshot()[0]["enabled"])

    def test_close_and_new_job_restore_reference_data_and_selection(self):
        series = parse_reference_text("X,A,B\n0,1,2\n1,3,4")
        self.library.replace(series)
        panel = self.plot()
        panel._set_reference_enabled(series[1]["id"], False)
        panel.close()
        self.library = ReferenceChartLibrary(root=self.temp.name)
        reopened = self.plot("another_job")
        self.assertIn(series[0]["id"], reopened._reference_series_tags)
        self.assertNotIn(series[1]["id"], reopened._reference_series_tags)
        self.assertFalse(dpg.get_value(reopened._reference_menu_items[series[1]["id"]]))

    def test_history_reset_and_none_do_not_remove_reference_series(self):
        series = parse_reference_text("0,10\n1,20", "Experiment")
        self.library.replace(series)
        panel = self.plot()
        panel.set_catalog({"historyOutputs": [{"id": "KE", "output": "ALLKE"}]})
        panel.update_frame({"series": [{"id": "KE", "reset": True, "points": [[0, 1]]}]})
        panel._set_all(False)
        self.assertIn(series[0]["id"], panel._reference_series_tags)
        panel.set_catalog({"historyOutputs": []})
        self.assertIn(series[0]["id"], panel._reference_series_tags)

    def test_editor_adds_one_pasted_series_at_a_time(self):
        result = Mock()
        form = self.dialog(result)
        form.data_table.paste_text("X\tY\n0\t1\n1\t2")
        dpg.set_value(form.name_edit, "Experiment A")
        self.assertTrue(form._add_input())
        form.data_table.paste_text("0.5\t3\n2.5\t4")
        dpg.set_value(form.name_edit, "Experiment B")
        form._save()
        saved = result.call_args.args[0]
        self.assertEqual([row["name"] for row in saved], ["Experiment A", "Experiment B"])
        self.assertEqual(saved[1]["points"], [[0.5, 3], [2.5, 4]])
        self.library.replace(saved)
        self.assertEqual(len(ReferenceChartLibrary(root=self.temp.name).snapshot()), 2)

    def test_editor_cancel_discards_remove_and_input_drafts(self):
        self.library.replace(parse_reference_text("0,1", "Saved"))
        result = Mock()
        form = self.dialog(result)
        form._remove_selected()
        form.data_table.paste_text("0,99")
        form._close_from_escape()
        result.assert_called_once_with(None)
        self.assertEqual(self.library.snapshot()[0]["name"], "Saved")

    def test_editor_edit_preserves_identity_and_disabled_state(self):
        original = parse_reference_text("0,1", "Before")
        original[0]["enabled"] = False
        self.library.replace(original)
        result = Mock()
        form = self.dialog(result)
        form._edit_selected()
        dpg.set_value(form.name_edit, "After")
        form.data_table.paste_text("0,2\n1,3")
        form._save()
        saved = result.call_args.args[0][0]
        self.assertEqual(saved["id"], original[0]["id"])
        self.assertFalse(saved["enabled"])
        self.assertEqual(saved["name"], "After")

    def test_invalid_input_keeps_editor_open(self):
        result = Mock()
        form = self.dialog(result)
        form.data_table.paste_text("0,NaN")
        form._save()
        result.assert_not_called()
        self.assertTrue(form.winfo_exists())
        self.assertIn("finite", dpg.get_value(form.status))

    def test_floating_factory_emits_result_for_reference_kind(self):
        emit = Mock()
        form = create_form("reference_chart", {"series": []}, self.view, emit)
        self.dialogs.append(form)
        form.data_table.paste_text("0,1\n1,2")
        form._save()
        self.assertEqual(emit.call_args.args, ("result",))
        self.assertEqual(emit.call_args.kwargs["value"][0]["points"], [[0, 1], [1, 2]])

    def test_single_point_reference_and_failed_visibility_save_restore_checkbox(self):
        series = parse_reference_text("0,10", "One measurement")
        self.library.replace(series)
        panel = self.plot()
        series_id = series[0]["id"]
        self.assertIn(series_id, panel._reference_series_tags)
        with patch.object(self.library.store, "save", side_effect=OSError("Read-only profile")):
            panel._set_reference_enabled(series_id, False)
        self.assertTrue(dpg.get_value(panel._reference_menu_items[series_id]))
        self.assertIn(series_id, panel._reference_series_tags)
        self.assertIn("Read-only profile", dpg.get_value(panel.status_text))

    def test_references_remain_available_after_plot_is_floated(self):
        series = parse_reference_text("0,1\n1,2", "Measured")
        self.library.replace(series)
        panel = self.plot()
        floating = dpg.add_window(label="Floating comparison", width=650, height=500)
        dpg.move_item(panel.root, parent=floating)
        panel.set_dock_mode("floating")
        self.frame()
        panel.sync_layout()
        panel._open_reference_menu()
        self.frame()
        self.assertTrue(dpg.is_item_shown(panel.reference_popup))
        self.assertIn(series[0]["id"], panel._reference_series_tags)

    def test_worksheet_has_only_xy_columns_and_editable_cells(self):
        form = self.dialog(Mock())
        sheet = form.data_table
        columns = dpg.get_item_children(sheet.table, 0)
        labels = [dpg.get_item_configuration(tag)["label"] for tag in columns]
        self.assertEqual(labels, ["#", "X", "Y"])
        self.assertEqual(len(sheet.cells), 20 * 2)
        self.assertTrue(all(dpg.get_item_info(tag)["type"].endswith("mvInputText")
                            for tag in sheet.cells.values()))
        self.assertFalse(dpg.get_item_configuration(sheet.table)["scrollX"])
        self.assertTrue(dpg.get_item_configuration(sheet.table)["scrollY"])

    def test_worksheet_context_menu_has_excel_friendly_actions(self):
        form = self.dialog(Mock())
        actions = [item.get("action") for item in form.data_table._context_menu._actions
                   if not item.get("separator")]
        self.assertEqual(actions, ["paste", "copy_cell", "copy_table",
                                   "clear_cell", "clear_row", "clear_all", "add_rows"])

    def test_worksheet_add_rows_preserves_values(self):
        form = self.dialog(Mock())
        sheet = form.data_table
        dpg.set_value(sheet.cells[0, 0], "0")
        dpg.set_value(sheet.cells[0, 1], "7")
        sheet.add_rows()
        self.assertEqual(sheet.model.pair_count, 1)
        self.assertEqual(sheet.model.row_count, 30)
        self.assertEqual(dpg.get_value(sheet.cells[0, 1]), "7")

    def test_worksheet_enter_moves_down_without_saving_dialog(self):
        result = Mock()
        form = self.dialog(result)
        sheet = form.data_table
        sheet.focus_cell(0, 0)
        self.frame()
        self.assertEqual(sheet.focused_position(), (0, 0))
        sheet._key_pressed(None, dpg.mvKey_Return)
        form.invoke_default()
        self.frame()
        result.assert_not_called()
        self.assertEqual(sheet.focused_position(), (1, 0))

    def test_worksheet_ctrl_v_pastes_rectangle_at_selected_cell(self):
        form = self.dialog(Mock())
        sheet = form.data_table
        sheet.focus_cell(1, 0)
        self.frame()
        with patch.object(dpg, "get_clipboard_text", return_value="10\t100\n11\t101"), \
                patch.object(dpg, "is_key_down", side_effect=lambda key: key == dpg.mvKey_LControl):
            sheet._key_pressed(None, dpg.mvKey_V)
            self.frame()
        series = sheet.to_series("Pasted")
        self.assertEqual(series[0]["points"], [[10, 100], [11, 101]])

    def test_worksheet_incomplete_pair_reports_coordinates(self):
        result = Mock()
        form = self.dialog(result)
        dpg.set_value(form.data_table.cells[1, 1], "4")
        form._save()
        result.assert_not_called()
        self.assertIn("Row 2: X and Y", dpg.get_value(form.status))

    def test_worksheet_closing_preserves_contents_until_native_viewport_hides(self):
        form = self.dialog(Mock())
        table_tag = form.data_table.tag
        form._defer_visual_destroy = True
        form.finish(None)
        self.assertTrue(dpg.does_item_exist(table_tag))
        self.assertTrue(dpg.is_item_shown(table_tag))
        form._finalize_visual_destroy()
        self.assertFalse(dpg.does_item_exist(table_tag))

    def test_worksheet_focuses_first_cell_on_open_and_reveals_new_rows(self):
        form = self.dialog(Mock())
        sheet = form.data_table
        self.assertEqual(sheet.focused_position(), (0, 0))
        dpg.set_value(sheet.cells[0, 1], "7")
        sheet.move_cell(25, 0)
        self.frame()
        self.assertEqual(sheet.model.row_count, 35)
        self.assertEqual(sheet.focused_position(), (25, 0))
        self.assertTrue(dpg.get_item_state(sheet.cells[25, 0])["visible"])
        self.assertEqual(dpg.get_value(sheet.cells[0, 1]), "7")


if __name__ == "__main__":
    unittest.main()
