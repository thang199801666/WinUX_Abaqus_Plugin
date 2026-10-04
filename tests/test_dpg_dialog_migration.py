"""Exercise actual Dear PyGui widgets without SSH, Tk roots or a display loop."""
from pathlib import Path
import threading
import unittest
from unittest.mock import patch

import dearpygui.dearpygui as dpg
from WinUx.dialogs.qt_dialog import QtDialog, QtTable
from WinUx.dialogs.blocking_form import BlockingDialog
from WinUx.dialogs.login_form import LoginForm as LoginDialog
from WinUx.dialogs.server_path_form import ServerPathDialog
from WinUx.dialogs.progress_form import ProgressDialog
from WinUx.dialogs.bookmarks_form import BookmarksDialog
from WinUx.dialogs.site_manager_form import SiteManagerDialog
from WinUx.dialogs.sync_preview_form import SyncPreviewDialog
from WinUx.dialogs.diagnostics_form import DiagnosticsDialog
from WinUx.dialogs.job_edit_form import JobEditDialog
from WinUx.dialogs.job_manager_form import JobManagerDialog
from WinUx.dialogs.job_schedule_form import JobScheduleDialog
from WinUx.dialogs.settings_form import SettingsDialog
from WinUx.dialogs.odb_check_form import ODBCheckDialog
from WinUx.dialogs.odb_extract_form import ODBExtractDialog, ODBXYResultDialog
from WinUx.dialogs.console_form import ConsoleDialog
from WinUx.dialogs.transfer_center_form import TransferCenterDialog


class View:
    def __init__(self):
        self.queue = []

    def after(self, delay, callback, *args):
        self.queue.append((delay, callback, args))

    def after_render(self, callback, *args):
        self.after(20, callback, *args)

    def drain(self):
        queued, self.queue = self.queue, []
        for delay, callback, args in queued:
            if delay == 0 or delay == 20:
                callback(*args)


class MigrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        dpg.create_context()

    @classmethod
    def tearDownClass(cls):
        dpg.destroy_context()

    def setUp(self):
        self.view = View()
        self.dialogs = []

    def tearDown(self):
        for dialog in self.dialogs:
            dialog.destroy()
        self.view.drain()

    def keep(self, dialog):
        self.dialogs.append(dialog)
        return dialog

    def test_all_main_dialogs_build_real_dpg_widgets_without_starting_tk(self):
        noop = lambda *args: None
        with patch("tkinter.Tk", side_effect=AssertionError("Tk backend started")), patch("tkinter.Toplevel", side_effect=AssertionError("Tk window started")):
            self.keep(BlockingDialog(self.view, "Test", "Message"))
            self.keep(LoginDialog(self.view, noop))
            self.keep(ServerPathDialog(self.view, "/", lambda path: [], task_submitter=noop))
            self.keep(ProgressDialog(self.view, "Upload", threading.Event()))
            self.keep(BookmarksDialog(self.view, [], noop, noop, noop))
            self.keep(SiteManagerDialog(self.view, [], noop, noop, noop))
            self.keep(SyncPreviewDialog(self.view, [], "/local", "/remote", noop, noop))
            self.keep(DiagnosticsDialog(self.view))
            self.keep(JobEditDialog(self.view, ("1", "Job", "User", "4", "Running", "1s")))
            self.keep(JobManagerDialog(self.view, [Path("job1.inp")], noop, noop))
            self.keep(JobScheduleDialog(self.view, lambda: [], noop))
            self.keep(SettingsDialog(self.view))
            self.keep(ODBCheckDialog(self.view, {}))
            self.keep(ODBExtractDialog(self.view, {}, noop))
            self.keep(ODBXYResultDialog(self.view, {}))
            self.keep(ConsoleDialog(self.view, lambda: "", noop, noop))
            self.keep(TransferCenterDialog(self.view))
        for dialog in self.dialogs:
            self.assertIsInstance(dialog, QtDialog)
            self.assertTrue(dpg.does_item_exist(dialog.tag))

    def test_confirm_and_input_deliver_one_result_and_close_before_callback(self):
        received = []
        dialog = self.keep(BlockingDialog(self.view, "Delete", "Confirm?", kind="confirm", on_result=received.append))
        dialog._close_from_escape()
        dialog.accept()
        self.assertFalse(dialog.winfo_exists())
        self.view.drain()
        self.assertEqual(received, [False])
        dialog = self.keep(BlockingDialog(self.view, "Name", "Enter", kind="input", initial="hello", on_result=received.append))
        dialog.invoke_default()
        self.view.drain()
        self.assertEqual(received, [False, "hello"])

    def test_late_worker_result_is_dropped_after_destroy(self):
        dialog = self.keep(QtDialog(self.view, "Worker"))
        received = []
        dialog.handle_command = lambda *args: received.append(args)
        dialog.post("result", 1)
        dialog.destroy()
        self.view.drain()
        self.assertEqual(received, [])

    def test_table_keyboard_current_index_range_and_toggle(self):
        dialog = self.keep(QtDialog(self.view, "Table"))
        table = QtTable(dialog.content, ("Name",), multiple=True)
        table.set_rows([(i, (str(i),)) for i in range(4)])
        table.navigate(dpg.mvKey_Home)
        table.navigate(dpg.mvKey_Down, shift=True)
        self.assertEqual(table.selected, {0, 1})
        table.navigate(dpg.mvKey_Down, ctrl=True)
        self.assertEqual(table.current, 2)
        self.assertEqual(table.selected, {0, 1})
        table.navigate(dpg.mvKey_Spacebar, ctrl=True)
        self.assertEqual(table.selected, {0, 1, 2})
        table.navigate(dpg.mvKey_A, ctrl=True)
        self.assertEqual(table.selected, {0, 1, 2, 3})

    def test_server_path_discards_stale_search_and_emits_selected_once(self):
        selected = []
        dialog = self.keep(ServerPathDialog(self.view, "/", lambda path: [], selected.append,
                                            task_submitter=lambda *a, **k: None))
        generation = dialog._generation
        dialog.handle_command("results", generation-1, "/", ["/stale"], None)
        self.assertEqual(dpg.get_item_configuration(dialog.listbox)["items"], [])
        dialog.handle_command("results", generation, "/", ["/current"], None)
        self.assertEqual(dpg.get_item_configuration(dialog.listbox)["items"], ["/current"])
        dialog.finish("/current")
        dialog.finish("/duplicate")
        self.view.drain()
        self.assertEqual(selected, ["/current"])

    def test_transfer_cancellation_and_failure_keep_correct_lifecycle(self):
        event = threading.Event()
        dialog = self.keep(ProgressDialog(self.view, "Upload", event))
        dialog._close_from_escape()
        self.assertTrue(event.is_set())
        self.assertTrue(dialog.winfo_exists())
        dialog.fail("Network lost")
        self.view.drain()
        self.assertEqual(dpg.get_item_configuration(dialog.action_button)["label"], "Close")
        dialog.cancel()
        self.assertFalse(dialog.winfo_exists())

    def test_transfer_center_preserves_task_handles_and_coalesces_progress(self):
        center = self.keep(TransferCenterDialog(self.view))
        task = center.add_task("Upload", threading.Event(), ["one.inp", "two.inp"])
        self.view.drain()
        task.update_progress("one.inp", 10, 100, 10, 200)
        task.update_progress("one.inp", 80, 100, 80, 200)
        self.view.drain()
        row = center.row_widgets[task.rows[0].row_id]
        self.assertAlmostEqual(dpg.get_value(row["progress"]), .8)
        center.hide()
        self.assertTrue(task.winfo_exists())
        task.cancel()
        self.assertTrue(task.cancel_event.is_set())
        task.complete()
        self.view.drain()
        self.assertEqual(task.state, "cancelled")

    def test_extract_keeps_catalog_order_cartesian_pairing_and_reverse(self):
        received = []
        catalog = {"historyOutputs": [{"id": "a", "output": "RF1"}, {"id": "b", "output": "U1"}]}
        dialog = self.keep(ODBExtractDialog(self.view, catalog, received.append))
        dialog.history.selected = {"b", "a"}
        dialog._add_selected("x")
        dialog.history.selected = {"b"}
        dialog._add_selected("y")
        dpg.set_value(dialog.reverse, "Reverse X")
        dialog._accept()
        self.view.drain()
        self.assertEqual([item["id"] for item in received[0]["x"]], ["a", "b"])
        self.assertEqual(received[0]["reverse"], "Reverse X")

    def test_login_validation_busy_state_and_preferences_snapshot(self):
        received = []
        with patch("WinUx.dialogs.login_form.LoginPreferences") as prefs:
            prefs.return_value.load.return_value = {"host": "server", "username": "user", "port": "0", "password": "secret"}
            dialog = self.keep(LoginDialog(self.view, lambda *args: received.append(args)))
            dialog.submit()
            self.assertIn("Port", dpg.get_value(dialog.error))
            dpg.set_value(dialog.port, "22")
            dialog.submit()
            dialog.submit()
            self.view.drain()
            self.assertEqual(len(received), 1)
            dialog.save_preferences()
            self.assertEqual(prefs.return_value.save_success.call_args.args[0]["password"], "secret")


if __name__ == "__main__":
    unittest.main()
