"""Transfer preflight feedback, native routing and non-overlapping row layout."""
import json
import os
import ctypes
from ctypes import wintypes
from pathlib import Path
import queue
import threading
import time
from collections import OrderedDict, deque
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from WinUx.controllers.transfer import TransferController
from WinUx.controllers.explorer_transfer_interaction import ExplorerTransferInteractionMixin
from WinUx.view import WinUXView, _dialog_type
from WinUx.ui.hosting.floating_runtime import FloatingDialogRuntime


class TransferFeedbackTests(unittest.TestCase):
    def test_progress_is_requested_before_any_conflict_io(self):
        progress = Mock()
        view = SimpleNamespace(show_transfer_progress=Mock(return_value=progress))
        app = SimpleNamespace(view=view, _submit_background=Mock())
        controller = TransferController(app)
        controller.drop_is_valid = Mock(return_value=True)
        controller.cross_panel_conflicts = Mock()
        source = SimpleNamespace(panel_id="local", status=Mock())
        target = SimpleNamespace(panel_id="server")
        controller.process_queued_drop(source, target, "/remote", True, [Path("chart.csv")])
        view.show_transfer_progress.assert_called_once()
        action, event = view.show_transfer_progress.call_args.args
        self.assertEqual(action, "Upload")
        self.assertIsInstance(event, threading.Event)
        progress.set_preparing.assert_called_once()
        controller.cross_panel_conflicts.assert_not_called()
        app._submit_background.assert_called_once()
        self.assertIs(app.transfer_cancel, event)

    def test_external_drop_does_not_stat_files_on_ui_thread(self):
        app = object.__new__(ExplorerTransferInteractionMixin)
        progress = Mock()
        app.view = SimpleNamespace(left=object(), after=Mock(),
                                   show_transfer_progress=Mock(return_value=progress))
        app.server = SimpleNamespace(connected=True)
        app.transfer_cancel = None
        app._process_queued_drop = Mock()
        target = SimpleNamespace(panel_id="server", current_path="/remote", status=Mock())
        with patch.object(Path, "exists", side_effect=AssertionError("Filesystem I/O on UI thread")):
            app.external_drop(target, ["C:/file.csv"])
        app.view.show_transfer_progress.assert_called_once()
        app.view.after.assert_called_once()

    def test_early_drag_requests_hidden_preparation_without_showing(self):
        app = object.__new__(ExplorerTransferInteractionMixin)
        prepare = Mock()
        app.view = SimpleNamespace(panels=[], after=Mock(), _prewarm_transfer_center=prepare)
        app.drag_start(None)
        app.view.after.assert_called_once_with(0, prepare)
        prepare.assert_not_called()

    def test_preflight_cancellation_skips_filesystem_and_remote_io(self):
        progress = Mock()
        view = SimpleNamespace(after=Mock(), show_transfer_progress=Mock(return_value=progress))
        app = SimpleNamespace(view=view, _submit_background=Mock(), _closing=False)
        controller = TransferController(app)
        controller.drop_is_valid = Mock(return_value=True)
        controller.cross_panel_conflicts = Mock()
        controller.start_drop_transfer = Mock()
        source = SimpleNamespace(panel_id="local", status=Mock())
        target = SimpleNamespace(panel_id="server")
        controller.process_queued_drop(source, target, "/remote", True, [Path("file.csv")])
        app.transfer_cancel.set()
        worker = app._submit_background.call_args.args[1]
        with patch.object(Path, "exists", side_effect=AssertionError("Cancelled preflight did I/O")):
            worker()
        controller.cross_panel_conflicts.assert_not_called()
        _, callback, *args = view.after.call_args.args
        callback(*args)
        progress.complete.assert_called_once()
        controller.start_drop_transfer.assert_not_called()

    def test_transfer_center_never_uses_main_context_default(self):
        # Main-window dialogs resolve to the in-process retained form by
        # default; the dedicated TransferCenterDialog implementation is kept,
        # never a generic main-context fallback dialog.
        from WinUx.dialogs.inprocess_adapters import TransferCenterDialog
        self.assertIs(_dialog_type("TransferCenterDialog"), TransferCenterDialog)

    def test_preparation_does_not_show_and_explicit_progress_only_shows_once(self):
        center = Mock()
        view = object.__new__(WinUXView)
        view.transfer_center_dialog = center
        view._floating_focus_suppressed = False
        view.winfo_exists = Mock(return_value=True)
        view._prewarm_transfer_center()
        center.show.assert_not_called()
        event = threading.Event()
        view.show_transfer_progress("Upload", event, ["file.csv"])
        center.add_task.assert_called_once_with("Upload", event, items=["file.csv"])
        center.show.assert_not_called()  # add_task owns the one visibility request

    def test_progress_does_not_bypass_overwrite_confirmation(self):
        progress = Mock()
        event = threading.Event()
        view = SimpleNamespace(confirm_action_async=Mock())
        controller = TransferController(SimpleNamespace(view=view, _closing=False))
        controller.start_drop_transfer = Mock()
        source = SimpleNamespace(panel_id="local", status=Mock())
        target = SimpleNamespace(panel_id="server")
        controller.drop_conflicts_ready(source, target, [Path("file.csv")], "/remote", True,
                                        ["file.csv"], progress, event)
        controller.start_drop_transfer.assert_not_called()
        progress.set_preparing.assert_called_once_with("Waiting for overwrite confirmation...")
        callback = view.confirm_action_async.call_args.args[2]
        callback(False)
        self.assertTrue(event.is_set())
        progress.complete.assert_called_once()
        controller.start_drop_transfer.assert_not_called()


class TransferBatchingTests(unittest.TestCase):
    def adapter(self):
        from WinUx.dialogs.floating_adapters import TransferCenterDialog
        center = object.__new__(TransferCenterDialog)
        center._closed = False
        center._lease = "batch"
        center._outgoing = queue.Queue(maxsize=256)
        center._row_update_lock = threading.Lock()
        center._pending_row_additions = {}
        center._row_add_scheduled = False
        center._pending_row_updates = {}
        center._row_update_scheduled = False
        center.pending = deque()
        center.view = SimpleNamespace(after=lambda delay, callback, *args:
                                       center.pending.append((callback, args)))
        return center

    def test_idle_preparation_failure_is_logged_not_shown_as_a_popup(self):
        from WinUx.ui.hosting.floating_dialog import FloatingDialogController
        center = self.adapter()
        center._idle_preparation, center._visible = True, False
        center._append_failure_log, center.destroy = Mock(), Mock()
        with patch("WinUx.diagnostics.log_event"), \
                patch.object(FloatingDialogController, "_failed") as failed:
            center._failed("Cannot start host", stage="startup")
        center.destroy.assert_called_once()
        center._append_failure_log.assert_called_once()
        failed.assert_not_called()

    def test_explicit_transfer_failure_keeps_normal_error_reporting(self):
        from WinUx.ui.hosting.floating_dialog import FloatingDialogController
        center = self.adapter()
        center._idle_preparation, center._visible = False, True
        with patch.object(FloatingDialogController, "_failed") as failed:
            center._failed("Cannot start host", stage="startup")
        failed.assert_called_once_with("Cannot start host", details="", stage="startup")

    def test_hidden_active_transfer_cannot_be_evicted_by_resident_cache(self):
        from WinUx.ui.hosting.floating_dialog import FloatingDialogController
        center = self.adapter()
        center._has_active_tasks = Mock(return_value=True)
        with patch.object(FloatingDialogController, "_evict_retained") as evict:
            self.assertFalse(center._evict_retained(5))
        evict.assert_not_called()

    def test_thousands_of_rows_use_one_ipc_message_not_a_full_queue(self):
        center = self.adapter()
        for index in range(2000):
            self.assertTrue(center.post("add_row", index, "Upload", "file-%d.csv" % index))
        self.assertEqual(len(center.pending), 1)
        center._flush_row_additions()
        self.assertEqual(center._outgoing.qsize(), 1)
        message = center._outgoing.get_nowait()
        self.assertEqual(message["command"], "add_rows")
        self.assertEqual(len(message["args"][0]), 2000)

    def test_removed_pending_row_is_never_sent(self):
        center = self.adapter()
        center.post("add_row", 1, "Upload", "file.csv")
        center.post("remove_row", 1)
        center._flush_row_additions()
        self.assertTrue(center._outgoing.empty())

    def test_additions_are_sent_before_their_progress_updates(self):
        center = self.adapter()
        center.post("add_row", 1, "Upload", "file.csv")
        center._pending_row_updates = {1: {"ratio": .5}}
        center._flush_row_updates()
        self.assertEqual(center._outgoing.get_nowait()["command"], "add_rows")
        self.assertEqual(center._outgoing.get_nowait()["command"], "rows_update")

    def test_child_yields_between_row_creation_batches_and_can_remove_pending_rows(self):
        from WinUx.dialogs.transfer_center_form import TransferCenterDialog
        form = object.__new__(TransferCenterDialog)
        form._pending_row_creations = OrderedDict()
        form._deferred_row_updates = {}
        form._row_creation_scheduled = False
        form.row_widgets = {}
        form.view = SimpleNamespace(after=Mock())
        form.winfo_exists = Mock(return_value=True)
        form._add_row = Mock()
        rows = [(index, "Upload", "file.csv") for index in range(100)]
        form.handle_command("add_rows", rows)
        form.handle_command("remove_row", 99)
        form._flush_row_creations()
        self.assertEqual(form._add_row.call_count, form.ROWS_PER_TURN)
        self.assertEqual(len(form._pending_row_creations), 99 - form.ROWS_PER_TURN)
        self.assertNotIn(99, form._pending_row_creations)
        self.assertEqual(form.view.after.call_count, 2)


@unittest.skipUnless(os.name == "nt", "Requires real DPG/GLFW layout")
class NativeTransferLayoutTests(unittest.TestCase):
    def test_long_names_and_errors_resize_without_clipping_or_progress_overlay(self):
        import dearpygui.dearpygui as dpg
        from DearUIQt.qt.scroller import dpg_window_rect
        commands = queue.Queue()
        errors = []
        events = []

        class Connection:
            def sendall(self, data):
                message = json.loads(data)
                events.append(message)
                reply = {"prepared": "publish", "staged": "publish_commit",
                         "closing": "owner_handoff_ready"}.get(message.get("event"))
                if reply:
                    commands.put({"command": reply, "lease": "layout"})

        runtime = FloatingDialogRuntime(Connection(), iter(commands.get, None), {
            "kind": "transfer_center", "visible": True, "lease": "layout",
            "width": 820, "height": 500, "owner_hwnd": 0, "reuse_host": False})
        original = runtime._build
        completed = []
        baseline_resources = []
        name = "very-long-folder-name/" * 12 + "chart.csv"
        statistics = "Permission denied: " + "long error detail " * 22
        sizes = iter((620, 820, 1050))

        def guarded(callback):
            try:
                callback()
            except Exception as exc:
                errors.append(exc)
                runtime.form.destroy()

        def rect(item):
            x, y = dpg.get_item_rect_min(item)
            w, h = dpg.get_item_rect_size(item)
            return x, y, x + w, y + h

        settled = {"last": None, "tries": 0}
        def next_size():
            try:
                width = next(sizes)
            except StopIteration:
                form = runtime.form
                form.handle_command("remove_row", 1)
                self.assertEqual((len(form._control_wrappers), len(form._native_parent_owners)),
                                 baseline_resources[0], "Removed transfer row leaked retained controls")
                runtime.form.destroy()
                return
            dpg.set_viewport_width(width)
            start_frame = dpg.get_frame_count()

            def check():
                if dpg.get_frame_count() < start_frame + 5:
                    runtime.view.after(5, lambda: guarded(check))
                    return
                form = runtime.form
                row = form.row_widgets[1]
                snapshot = tuple(tuple(int(round(v)) for v in r) for r in (rect(row["title"]), rect(row["action"]),
                            rect(row["status_text"]), rect(row["stats"]),
                            dpg_window_rect(dpg, row["group"]), rect(row["percentage"])))
                # Wrapped-label relayout and the card auto-resize can lag the
                # value updates by a few frames; wait until geometry is stable so
                # the assertions measure a real layout, never a transient one.
                if snapshot != settled["last"] and settled["tries"] < 400:
                    settled["last"], settled["tries"] = snapshot, settled["tries"] + 1
                    runtime.view.after(5, lambda: guarded(check))
                    return
                title, action = rect(row["title"]), rect(row["action"])
                progress = dpg_window_rect(dpg, row["progress_host"])
                percentage = rect(row["percentage"])
                status, stats = rect(row["status_text"]), rect(row["stats"])
                card = dpg_window_rect(dpg, row["group"])
                # Row zones stack vertically: title, status, then the shared
                # controls grid (progress + cancel).
                self.assertLessEqual(title[3], status[1] + 1, "title runs into the status row")
                self.assertLessEqual(status[3], action[1] + 1, "status runs into the controls row")
                self.assertLessEqual(max(title[3], action[3], stats[3]), card[3] - 3,
                                     "row content clipped by card title=%r action=%r stats=%r card=%r" % (title, action, stats, card))
                # The wrapped title and the action stay inside the card.
                self.assertLessEqual(title[2], card[2] - 4, "title clipped by card")
                self.assertLessEqual(action[2], card[2] - 1, "action clipped by card")
                # The percentage label is rendered inside the progress host,
                # centered horizontally (fixed-center text, not an overlay).
                self.assertGreaterEqual(percentage[0], progress[0], "percentage clipped left")
                self.assertLessEqual(percentage[2], progress[2] + 1, "percentage clipped right")
                self.assertLessEqual(
                    abs((percentage[0] + percentage[2]) - (progress[0] + progress[2])), 32,
                    "percentage is not horizontally centered in the progress host")
                self.assertGreater(card[3] - card[1], 84, "wrapped card failed to grow")
                self.assertEqual(dpg.get_value(row["percentage"]), "50.0%")
                self.assertEqual(dpg.get_item_configuration(row["progress"])["overlay"], "")
                rows_bounds = dpg_window_rect(dpg, form.rows_host)
                footer_bounds = dpg_window_rect(dpg, form.footer_shell)
                self.assertLessEqual(rows_bounds[3], footer_bounds[1] + 1)
                completed.append(width)
                next_size()
                runtime.view.after(5, lambda: guarded(check))

        def build():
            original()
            form = runtime.form
            baseline_resources.append((len(form._control_wrappers), len(form._native_parent_owners)))
            form.handle_command("add_rows", [(1, "Upload", name)])
            form._pending_row_updates = {1: {"status": "Failed", "statistics": statistics, "ratio": .5}}
            form.handle_command("flush_row_updates")
            runtime.view.after(10, lambda: guarded(next_size))
            runtime.view.after(18000, lambda: guarded(lambda: self.fail("Layout test timed out after %d settles" % settled["tries"])))

        try:
            with patch.object(runtime, "_build", side_effect=build):
                runtime.run()
        finally:
            commands.put(None)
        if errors:
            raise errors[0]
        self.assertEqual(completed, [620, 820, 1050])


@unittest.skipUnless(os.name == "nt", "Requires the real main and native transfer windows")
class MainTransferWindowTests(unittest.TestCase):
    def test_prepared_window_can_leave_main_bounds_and_hide_does_not_cancel(self):
        from WinUx.controllers import REQUIRED_CALLBACK_KEYS
        from DearUIQt.dialogs.qt_dialog import QtDialog
        user32 = ctypes.windll.user32
        user32.GetAncestor.argtypes = [wintypes.HWND, wintypes.UINT]
        user32.GetAncestor.restype = wintypes.HWND
        user32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
        user32.SetWindowPos.argtypes = [wintypes.HWND, wintypes.HWND,
            ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, wintypes.UINT]
        user32.IsWindowVisible.argtypes = [wintypes.HWND]
        view = WinUXView({key: Mock(return_value=[]) for key in REQUIRED_CALLBACK_KEYS})
        errors, completed = [], []
        event = threading.Event()

        def scenario():
            # Startup preparation now warms only the shared host pool.  The
            # actual owned Transfer Center HWND is created on first use so a
            # hidden child cannot disturb main-window focus/Z-order.
            view._prewarm_transfer_center()
            center = view.transfer_center_dialog
            self.assertIsInstance(center, QtDialog)
            self.assertFalse(center.isVisible())
            task = view.show_transfer_progress("Upload", event, ["folder/" * 20 + "chart.csv"])
            self.assertIs(center, view.transfer_center_dialog)
            yield lambda: user32.IsWindowVisible(center.winId())
            hwnd = center.winId()
            self.assertEqual(int(user32.GetAncestor(wintypes.HWND(hwnd), 2) or 0), hwnd)
            main = wintypes.RECT()
            self.assertTrue(user32.GetWindowRect(view._find_main_viewport_hwnd(), ctypes.byref(main)))
            self.assertTrue(user32.SetWindowPos(wintypes.HWND(hwnd), None, main.right + 20, main.top,
                                                0, 0, 0x0001 | 0x0004 | 0x0010))
            actual = wintypes.RECT()
            self.assertTrue(user32.GetWindowRect(wintypes.HWND(hwnd), ctypes.byref(actual)))
            self.assertGreater(actual.left, main.right)
            center.hide()
            yield lambda: not user32.IsWindowVisible(center.winId())
            # Hiding keeps the queued transfer alive; only destruction cancels.
            self.assertFalse(event.is_set())
            self.assertTrue(task.winfo_exists())
            center.show()
            yield lambda: user32.IsWindowVisible(center.winId())
            # Re-showing reuses the same retained dialog and native window.
            self.assertIs(center, view.transfer_center_dialog)
            self.assertTrue(center.winfo_exists())
            completed.append(True)

        steps, pending = scenario(), []

        def advance():
            try:
                if pending:
                    predicate, deadline = pending[0]
                    if not predicate():
                        if time.monotonic() > deadline:
                            raise AssertionError("Native transfer visibility transition timed out")
                        view.after(10, advance)
                        return
                    pending.clear()
                pending.append((next(steps), time.monotonic() + 8))
                view.after(10, advance)
            except StopIteration:
                view.request_shutdown()
            except Exception as exc:
                errors.append(exc)
                view.request_shutdown()

        view.after(250, advance)
        view.run()
        if errors:
            raise errors[0]
        self.assertEqual(completed, [True])


if __name__ == "__main__":
    unittest.main()
