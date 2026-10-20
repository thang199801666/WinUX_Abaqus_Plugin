"""A dialog must paint its shell before initial filesystem/report work."""
import json
import os
from pathlib import Path
import queue
import tempfile
import threading
import time
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import WinUx  # Configure bundled Dear PyGui under Abaqus Python.
from DearUIQt.dialogs.qt_dialog import QtDialog
from WinUx.ui.hosting.floating_runtime import ChildView, FloatingDialogRuntime
from WinUx.ui.hosting.floating_dialog import FloatingDialogController


class FirstPresentBarrierTests(unittest.TestCase):
    def test_hidden_settle_queue_cannot_start_initial_work(self):
        view = ChildView()
        work = Mock()
        view.after_first_present(work, "data")
        view.drain()
        work.assert_not_called()
        view.mark_presented()
        work.assert_not_called()
        view.drain()
        work.assert_called_once_with("data")
        view.mark_presented()
        view.drain()
        work.assert_called_once()

    def test_qdialog_cancel_before_first_paint_drops_initial_work(self):
        dialog = object.__new__(QtDialog)
        dialog.view = ChildView()
        dialog.winfo_exists = Mock(return_value=True)
        dialog.isVisible = Mock(return_value=True)
        work = Mock()
        dialog.after_first_present(work)
        dialog.winfo_exists.return_value = False
        dialog.view.mark_presented()
        dialog.view.drain()
        work.assert_not_called()

    def test_main_context_uses_render_barrier_not_after_zero(self):
        dialog = object.__new__(QtDialog)
        dialog.view = SimpleNamespace(after_render=Mock(), after=Mock())
        dialog.winfo_exists = Mock(return_value=True)
        dialog.isVisible = Mock(return_value=True)
        work = Mock()
        dialog.after_first_present(work)
        dialog.view.after_render.assert_called_once()
        dialog.view.after.assert_not_called()
        work.assert_not_called()
        dialog.view.after_render.call_args.args[0]()
        work.assert_called_once()

    def controller(self):
        dialog = object.__new__(FloatingDialogController)
        dialog._closed = False
        dialog._ready = False
        dialog._visible = True
        dialog._native_visible = False
        dialog._first_present_callbacks = []
        dialog.view = SimpleNamespace(after=Mock())
        return dialog

    def test_native_controller_waits_for_both_ready_and_visibility(self):
        dialog = self.controller()
        work = Mock()
        dialog.after_first_present(work)
        dialog._ready = True
        dialog._flush_first_present_callbacks()
        dialog.view.after.assert_not_called()
        dialog._native_visible = True
        dialog._flush_first_present_callbacks()
        work.assert_not_called()
        dialog.view.after.call_args.args[1]()
        work.assert_called_once()

    def test_native_controller_does_not_run_delivered_work_after_hide(self):
        dialog = self.controller()
        dialog._ready = dialog._native_visible = True
        work = Mock()
        dialog.after_first_present(work)
        dialog._visible = False
        dialog.view.after.call_args.args[1]()
        work.assert_not_called()


class InitialDataWorkerTests(unittest.TestCase):
    def test_path_normalization_never_stats_initial_location(self):
        from WinUx.dialogs.local_folder_form import LocalFolderDialog
        with patch("os.path.isdir", side_effect=AssertionError("UI stat")):
            self.assertTrue(LocalFolderDialog._normalize_initial("unavailable-share"))

    def test_legacy_schedule_provider_runs_only_in_submitted_worker(self):
        from WinUx.dialogs.job_schedule_form import JobScheduleDialog
        dialog = object.__new__(JobScheduleDialog)
        dialog.winfo_exists = Mock(return_value=True)
        dialog.isVisible = Mock(return_value=True)
        dialog._schedule_nonblocking = False
        dialog._schedule_future = None
        dialog._schedule_request_generation = 0
        dialog.schedule_provider = Mock(return_value=[("job", "Run", "now", "0", "Waiting", "run", "id")])
        dialog.runAsync = Mock()
        dialog.set_rows = Mock()
        self.assertTrue(dialog.refresh())
        dialog.schedule_provider.assert_not_called()
        result = []
        worker = threading.Thread(target=lambda: result.append(dialog.runAsync.call_args.args[0]()))
        worker.start()
        worker.join(2)
        self.assertFalse(worker.is_alive())
        dialog.runAsync.call_args.kwargs["on_result"](result[0])
        dialog.set_rows.assert_called_once()

    def test_native_diagnostics_constructor_does_not_collect_report(self):
        from WinUx.dialogs.floating_adapters import DiagnosticsDialog
        with patch("WinUx.diagnostics.build_diagnostics_report") as report, \
                patch.object(FloatingDialogController, "__init__") as construct:
            DiagnosticsDialog(SimpleNamespace())
        report.assert_not_called()
        self.assertEqual(construct.call_args.args[3], {"report": ""})

    def test_native_schedule_constructor_does_not_call_provider(self):
        from WinUx.dialogs.floating_adapters import JobScheduleDialog
        provider = Mock()
        with patch.object(FloatingDialogController, "__init__") as construct:
            JobScheduleDialog(SimpleNamespace(), provider, Mock())
        provider.assert_not_called()
        self.assertEqual(construct.call_args.args[3], {"rows": []})

    def test_native_diagnostics_collects_off_ui_and_publishes_via_queue(self):
        from WinUx.dialogs.floating_adapters import DiagnosticsDialog
        dialog = object.__new__(DiagnosticsDialog)
        dialog._closed = dialog._report_pending = False
        dialog.view = SimpleNamespace(after=Mock())
        dialog.post_latest = Mock()
        pool = Mock()
        ui_thread = threading.get_ident()
        report_threads = []

        def report():
            report_threads.append(threading.get_ident())
            return "report"

        with patch("WinUx.diagnostics.build_diagnostics_report", side_effect=report), \
                patch("WinUx.dialogs.floating_adapters.QThreadPool.globalInstance", return_value=pool):
            dialog.refresh()
            self.assertEqual(report_threads, [])
            worker = threading.Thread(target=pool.start.call_args.args[0])
            worker.start()
            worker.join(2)
        self.assertFalse(worker.is_alive())
        self.assertNotEqual(report_threads, [ui_thread])
        dialog.post_latest.assert_not_called()
        _, publish, value = dialog.view.after.call_args.args
        publish(value)
        dialog.post_latest.assert_called_once_with("report", "report")


@unittest.skipUnless(os.name == "nt", "Requires native Windows presentation")
class NativeFirstPresentTests(unittest.TestCase):
    def test_file_and_folder_stat_happen_after_visible_shell_on_worker_thread(self):
        import ctypes
        from ctypes import wintypes
        import dearpygui.dearpygui as dpg
        user32 = ctypes.windll.user32
        user32.IsWindowVisible.argtypes = [wintypes.HWND]
        root = Path(os.environ["LOCALAPPDATA"]) / "Temp" / "opencode"
        root.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=root, prefix="winux-first-present-") as directory:
            file = Path(directory) / "chart.csv"
            file.write_text("1,2\n")
            for kind, initial in (("local_folder", directory), ("local_file", str(file))):
                with self.subTest(kind=kind):
                    commands = queue.Queue()
                    errors, probes, ready_states = [], [], []
                    main_thread = threading.get_ident()

                    class Connection:
                        def sendall(_self, data):
                            message = json.loads(data)
                            event = message.get("event")
                            reply = {"prepared": "publish", "staged": "publish_commit",
                                     "closing": "owner_handoff_ready"}.get(event)
                            if reply:
                                commands.put({"command": reply, "lease": kind})
                            if event == "ready":
                                ready_states.append((runtime.view._first_presented,
                                                     bool(user32.IsWindowVisible(runtime.native.hwnd))))

                    runtime = FloatingDialogRuntime(Connection(), iter(commands.get, None), {
                        "kind": kind, "payload": {"initial": initial, "extensions": [".csv"]},
                        "visible": True, "lease": kind, "owner_hwnd": 0, "reuse_host": False})
                    target = os.path.normcase(os.path.abspath(initial))
                    isdir, isfile, path_isfile = os.path.isdir, os.path.isfile, Path.is_file

                    def guard(path):
                        if os.path.normcase(os.path.abspath(path)) == target:
                            probes.append((threading.get_ident(), runtime.view._first_presented))
                            self.assertNotEqual(threading.get_ident(), main_thread, "Initial stat blocked UI")
                            self.assertTrue(runtime.view._first_presented, "Stat preceded visible first frame")

                    def guarded_isdir(path):
                        guard(path)
                        return isdir(path)

                    def guarded_isfile(path):
                        guard(path)
                        return isfile(path)

                    def guarded_path_isfile(path):
                        guard(path)
                        return path_isfile(path)

                    build = runtime._build
                    deadline = time.monotonic() + 5

                    def check():
                        try:
                            if not runtime.view._first_presented or dpg.get_value(runtime.form.status) == "Loading...":
                                self.assertLess(time.monotonic(), deadline, "Initial listing timed out")
                                runtime.view.after(5, check)
                                return
                            self.assertTrue(probes)
                            self.assertTrue(all(thread != main_thread and presented for thread, presented in probes))
                            self.assertEqual(ready_states, [(False, True)])
                            self.assertEqual(runtime.form._current_path, directory)
                            if kind == "local_file":
                                self.assertEqual(dpg.get_value(runtime.form.file_edit), "chart.csv")
                            runtime.form.destroy()
                        except Exception as exc:
                            errors.append(exc)
                            runtime.form.destroy()

                    def build_and_check():
                        build()
                        runtime.view.after(10, check)

                    try:
                        with patch("os.path.isdir", side_effect=guarded_isdir), \
                                patch("os.path.isfile", side_effect=guarded_isfile), \
                                patch.object(Path, "is_file", guarded_path_isfile), \
                                patch.object(runtime, "_build", side_effect=build_and_check):
                            runtime.run()
                    finally:
                        commands.put(None)
                    if errors:
                        raise errors[0]


if __name__ == "__main__":
    unittest.main()
