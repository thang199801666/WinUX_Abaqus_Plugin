"""Application-facing adapters. UI widgets live exclusively in child viewports."""
from __future__ import annotations

import itertools
import threading

from DearUIQt.core import QThreadPool
import time
from .floating_dialog import FloatingDialogController
from ..ui.hosting.result_dialog import ResultDialog
from .logic.formatting import format_size, format_time
from .logic.job_schedule import JobEditScheduleLogic
from .logic.job_manager import JobManagerLogic
from .logic.transfer import TransferCenterLogic, TransferTaskHandle, TransferItemRow

_TransferItemRow = TransferItemRow


class BlockingDialog(ResultDialog):
    def __init__(self, view, title, message, kind="message", initial="", on_result=None,
                 primary_text=None, secondary_text=None, intent="info", owner_hwnd=None):
        self.kind = kind
        self._failure_notice = kind == "message" and intent == "error"
        self._init_result(on_result, False if kind == "confirm" else None)
        super().__init__(view, "blocking", title, {"title": title, "message": message,
            "kind": kind, "initial": initial, "primary_text": primary_text,
            "secondary_text": secondary_text, "intent": intent}, width=500, height=240,
            modal=True, owner_hwnd=owner_hwnd)

    def _close_from_escape(self):
        self.finish(self._cancel_value)


class JobEditDialog(JobEditScheduleLogic, ResultDialog):
    def __init__(self, view, values, settings=None, on_result=None):
        self._init_result(on_result)
        super().__init__(view, "job_edit", "Edit Job", {"values": list(values or []), "settings": settings or {}},
                         width=600, height=390, modal=True)


class ODBExtractDialog(ResultDialog):
    def __init__(self, view, catalog, on_result):
        self.catalog = dict(catalog or {})
        self._init_result(on_result, notify_cancel=False)
        super().__init__(view, "odb_extract", "Extract ODB History Data", {"catalog": self.catalog},
                         width=960, height=620, modal=True)


class ReferenceChartDialog(ResultDialog):
    def __init__(self, view, series, on_result, history_outputs=None):
        self._init_result(on_result, notify_cancel=False)
        payload = {"series": series}
        if history_outputs is not None:
            payload["history_outputs"] = list(history_outputs or [])
        super().__init__(view, "reference_chart", "Reference Chart", payload,
                         width=940, height=690, modal=True)


class ODBCheckDialog(FloatingDialogController):
    def __init__(self, view, result):
        self.result = dict(result or {})
        super().__init__(view, "odb_check", "Check ODB", {"result": self.result}, width=920, height=430)


class ODBXYResultDialog(FloatingDialogController):
    def __init__(self, view, result):
        self.result = dict(result or {})
        super().__init__(view, "odb_xy", "Extracted ODB Data", {"result": self.result}, width=570, height=490)


class SettingsDialog(FloatingDialogController):
    def __init__(self, view):
        # Qt keeps a QDialog object alive after close unless WA_DeleteOnClose is
        # requested. Settings is owned by View for the application lifetime, so
        # retain its expensive native/widget tree and make subsequent opens a
        # show/activate transaction instead of another process/form build.
        super().__init__(view, "settings", "Settings", width=760, height=520,
                         modal=False, retain_on_close=True)

    def handle_event(self, event, message):
        if event == "settings_saved":
            self.view.apply_general_preferences(message.get("values", {}))
            return
        if event != "install_update":
            return
        import os
        from winux_launcher import launch_winux
        project_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))

        def worker():
            try:
                launch_winux(project_dir=project_dir, existing_pid=os.getpid(), install_update=True)
            except Exception as exc:
                self.post("update_launch_failed", str(exc))
            else:
                self.view.after(0, self.destroy)

        QThreadPool.globalInstance().start(worker)


class DiagnosticsDialog(FloatingDialogController):
    def __init__(self, view):
        self._report_pending = False
        super().__init__(view, "diagnostics", "WinUx Diagnostics", {"report": ""},
                          width=720, height=480, retain_on_close=True)

    def refresh(self, *args):
        if self._closed or self._report_pending:
            return False
        from ..diagnostics import build_diagnostics_report
        self._report_pending = True

        def publish(report):
            self._report_pending = False
            if not self._closed:
                self.post_latest("report", report)

        def worker():
            try:
                report = build_diagnostics_report()
            except Exception as exc:
                report = "Diagnostics refresh failed: {}".format(exc)
            self.view.after(0, publish, report)

        try:
            QThreadPool.globalInstance().start(worker)
        except Exception:
            self._report_pending = False
            raise
        return True

    def handle_event(self, event, message):
        if event == "refresh":
            self.refresh()


class BookmarksDialog(FloatingDialogController):
    def __init__(self, view, entries, on_open, on_remove, on_rename):
        self._on_open, self._on_remove, self._on_rename = on_open, on_remove, on_rename
        super().__init__(view, "bookmarks", "Bookmarks", {"entries": list(entries or [])},
                         width=650, height=360, retain_on_close=True)

    def refresh(self, entries, on_open=None, on_remove=None, on_rename=None):
        if on_open is not None:
            self._on_open = on_open
        if on_remove is not None:
            self._on_remove = on_remove
        if on_rename is not None:
            self._on_rename = on_rename
        return self.post_latest("refresh", list(entries or []))

    def request_open(self, entry):
        self.view.after(0, self._on_open, dict(entry))

    def request_remove(self, entry):
        self.view.after(0, self._on_remove, dict(entry))

    def request_rename(self, entry, label):
        self.view.after(0, self._on_rename, dict(entry), str(label))

    def handle_event(self, event, message):
        entry = message.get("entry") or {}
        if event == "open":
            self.request_open(entry)
        elif event == "remove":
            self.request_remove(entry)
        elif event == "rename_prompt":
            def renamed(value):
                if self.winfo_exists() and value and value.strip():
                    self.request_rename(entry, value.strip())
            self.own_dialog(BlockingDialog(self.view, "Rename Bookmark", "Bookmark name:", kind="input",
                initial=entry.get("label") or "", primary_text="Save", on_result=renamed, owner_hwnd=self._hwnd))


class SiteManagerDialog(FloatingDialogController):
    def __init__(self, view, sites, on_save, on_delete, on_connect):
        self._on_save, self._on_delete, self._on_connect = on_save, on_delete, on_connect
        super().__init__(view, "sites", "Site Manager", {"sites": list(sites or [])},
                         width=680, height=410, retain_on_close=True)

    def refresh(self, sites, selected_id=None, on_save=None, on_delete=None, on_connect=None):
        if on_save is not None:
            self._on_save = on_save
        if on_delete is not None:
            self._on_delete = on_delete
        if on_connect is not None:
            self._on_connect = on_connect
        return self.post_latest("refresh", list(sites or []), selected_id)

    def show_error(self, message):
        return self.post("error", str(message))

    def request_save(self, values):
        self.view.after(0, self._on_save, dict(values))

    def request_delete(self, site):
        self.view.after(0, self._on_delete, dict(site))

    def request_connect(self, values):
        self.view.after(0, self._on_connect, dict(values))

    def handle_event(self, event, message):
        callback = {"save": self.request_save, "delete": self.request_delete, "connect": self.request_connect}.get(event)
        if callback:
            callback(message.get("values") or {})


class SyncPreviewDialog(FloatingDialogController):
    def __init__(self, view, rows, local_path, server_path, on_refresh, on_transfer):
        self._on_refresh, self._on_transfer = on_refresh, on_transfer
        super().__init__(view, "sync", "Directory Synchronization Preview",
            {"rows": list(rows or []), "local_path": str(local_path), "server_path": str(server_path)},
            width=820, height=470, retain_on_close=True)

    def refresh(self, rows, local_path, server_path, on_refresh=None, on_transfer=None):
        if on_refresh is not None:
            self._on_refresh = on_refresh
        if on_transfer is not None:
            self._on_transfer = on_transfer
        return self.post_latest("refresh", list(rows or []), str(local_path), str(server_path))

    def set_status(self, text):
        return self.post("status", str(text))

    def begin_scan(self, local_path, server_path):
        return self.post("begin_scan", str(local_path), str(server_path))

    def request_refresh(self):
        self.view.after(0, self._on_refresh)

    def request_transfer(self, rows):
        self.view.after(0, self._on_transfer, list(rows or []))

    def handle_event(self, event, message):
        if event == "refresh":
            self.request_refresh()
        elif event == "transfer":
            self.request_transfer(message.get("rows") or [])


class LocalFolderDialog(ResultDialog):
    """Application-facing local folder browser using the shared DPG host."""

    def __init__(self, view, initial, on_selected=None):
        self._init_result(on_selected, cancel_value=None, notify_cancel=False)
        super().__init__(
            view, "local_folder", "Open Folder",
            {"initial": str(initial or "")},
            width=780, height=500, modal=True, resizable=True,
        )


class LocalFileDialog(ResultDialog):
    """File browser in its own owned HWND, unconstrained by the owner viewport."""

    def __init__(self, view, initial="", on_selected=None, *, extensions=(),
                 save=False, default_filename="", width=840, height=540):
        self._init_result(on_selected, cancel_value=None, notify_cancel=True)
        super().__init__(
            view, "local_file", "Save File" if save else "Open File",
            {"initial": str(initial or ""), "extensions": list(extensions),
             "save": bool(save), "default_filename": str(default_filename or "")},
            width=width, height=height, modal=True, resizable=True)


class ServerPathDialog(FloatingDialogController):
    def __init__(self, view, initial, suggestion_provider, on_selected=None, task_submitter=None):
        self.suggestion_provider, self.on_selected, self.task_submitter = suggestion_provider, on_selected, task_submitter
        self._finished = False
        super().__init__(view, "server_path", "Server Folder", {"initial": str(initial or "/")}, width=560, height=300, modal=True)

    def request_search(self, generation, value):
        def worker():
            try:
                values, error = [str(item) for item in (self.suggestion_provider(value) or [])], None
            except Exception as exc:
                values, error = [], str(exc)
            self.post("results", generation, value, values, error)
        if callable(self.task_submitter):
            self.task_submitter("server-path-search", worker, key="server-path-search:{}".format(id(self)), replace=True)
        else:
            QThreadPool.globalInstance().start(worker)

    def _record_selection(self, value):
        if self._finished:
            return False
        self._finished = True
        self._selected_value = value
        self._selection_notified = False
        return True

    def finish(self, value):
        if not self._record_selection(value):
            return
        self.destroy()

    def handle_event(self, event, message):
        if event == "search":
            self.request_search(message["generation"], str(message["value"]))
        elif event == "result":
            # Child owns its native close; only record the result here.
            self._record_selection(message.get("value"))

    def _finish(self):
        already_finalized = bool(getattr(self, "_finalized", False))
        super()._finish()
        if already_finalized or getattr(self, "_selection_notified", False):
            return
        self._selection_notified = True
        value = getattr(self, "_selected_value", None)
        if value and callable(self.on_selected):
            self.view.after(0, self.on_selected, str(value))

    def wait(self):
        return None


class ProgressDialog(FloatingDialogController):
    _format_size = staticmethod(format_size)
    _format_time = staticmethod(format_time)

    def __init__(self, view, operation, cancel_event, items=None):
        self.operation, self.cancel_event = str(operation), cancel_event
        self.items = list(items or [])
        self.started_at = time.monotonic()
        super().__init__(view, "progress", self.operation, {"operation": self.operation}, width=500, height=225)

    def update_progress(self, name, current_done, current_total, overall_done, overall_total):
        current = max(0, min(1, float(current_done or 0) / max(1, float(current_total or 0))))
        overall = max(0, min(1, float(overall_done or 0) / max(1, float(overall_total or 0))))
        speed = float(overall_done or 0) / max(.001, time.monotonic() - self.started_at)
        eta = max(0, float(overall_total or 0) - float(overall_done or 0)) / speed if speed else None
        self.post_latest("progress", "{}: {} ({:.1f}%)".format(self.operation, name, current*100), current, overall,
            "Speed: {}/s | Estimated time: {}".format(self._format_size(speed), self._format_time(eta)))

    def cancel(self):
        self.cancel_event.set()
        self.post("cancelling")

    def complete(self):
        self.destroy()

    def fail(self, message):
        return self.post("fail", str(message))

    def handle_event(self, event, message):
        if event == "cancel":
            self.cancel()


class JobScheduleDialog(FloatingDialogController):
    def __init__(self, view, schedule_provider, schedule_command):
        self.schedule_provider, self.schedule_command = schedule_provider, schedule_command
        self._schedule_pending = False
        super().__init__(view, "job_schedule", "Job Schedule",
                         {"rows": []},
                         width=840, height=260, modal=False, retain_on_close=True)

    def refresh(self):
        if not self.winfo_exists() or self._schedule_pending:
            return False
        self._schedule_pending = True

        def publish(rows, error):
            self._schedule_pending = False
            if not self._closed:
                if error is None:
                    self.post_latest("set_rows", rows)
                else:
                    self.post_latest("status", "Schedule refresh failed: {}".format(error))

        def worker():
            try:
                rows, error = list(self.schedule_provider() or []), None
            except Exception as exc:
                rows, error = [], str(exc)
            self.view.after(0, publish, rows, error)

        try:
            QThreadPool.globalInstance().start(worker)
        except Exception:
            self._schedule_pending = False
            raise
        return True

    def request_refresh(self):
        self.view.after(0, self.refresh)

    def request_action(self, action, kind, key):
        self.view.after(0, self.schedule_command, str(action), str(kind), str(key))

    def handle_event(self, event, message):
        if event == "refresh":
            self.refresh()
        elif event == "action":
            self.request_action(message["action"], message["kind"], message["key"])


class JobManagerDialog(JobManagerLogic, FloatingDialogController):
    def __init__(self, view, paths, run_callback, compute_callback):
        self.paths = sorted(list(paths), key=self._input_file_sort_key)
        self.row_order = list(self.paths)
        self.run_callback, self.compute_callback = run_callback, compute_callback
        self._pending_queue_job_names = set()
        self._submission_finished = self._close_requested = False
        super().__init__(view, "job_manager", "Abaqus Job Manager", {"paths": self.paths}, width=1080, height=440, modal=True)

    def handle_event(self, event, message):
        if event == "estimate":
            self._request_core_estimates()
        elif event == "run":
            self._submit_from_native(message.get("jobs") or [])


class ConsoleDialog(FloatingDialogController):
    def __init__(self, view, output_callback, command_callback, interrupt_callback, error_callback=None, completion_callback=None, completion_list_callback=None):
        self.output_callback, self.command_callback = output_callback, command_callback
        self.interrupt_callback, self.error_callback = interrupt_callback, error_callback
        self.completion_callback = completion_callback
        self.completion_list_callback = completion_list_callback
        self._last_output = None
        super().__init__(view, "console", "SSH Console", width=680, height=410)
        self.view.after(0, self._poll_output)

    def _poll_output(self):
        if not self.winfo_exists():
            return
        try:
            output = self.output_callback()
            if output != self._last_output:
                self._last_output = output
                self.post_latest("output", str(output or ""))
        except Exception as exc:
            if callable(self.error_callback):
                self.error_callback(str(exc))
        self.view.after(100, self._poll_output)

    def focus_input(self):
        return self.post("focus")

    def handle_event(self, event, message):
        if event == "command":
            command = str(message["value"])
            accepted = False
            try:
                accepted = bool(self.command_callback(command))
            finally:
                self.post("command_result", command, accepted)
        elif event == "interrupt":
            self.post("interrupt_result", bool(self.interrupt_callback()))
        elif event == "completion_list":
            callback = getattr(self, "completion_list_callback", None)
            if callable(callback):
                callback(str(message.get("draft", "")),
                         list(message.get("candidates") or ()),
                         int(message.get("columns", 80)))
        elif event == "complete":
            request_id = int(message.get("request_id", 0))
            callback = getattr(self, "completion_callback", None)
            if not callable(callback):
                self.post("completion_result", request_id, {
                    "start": int(message.get("cursor", 0)),
                    "end": int(message.get("cursor", 0)),
                    "candidates": [],
                })
                return

            def completed(result):
                if self.winfo_exists():
                    self.post("completion_result", request_id, result)

            callback(str(message.get("draft", "")),
                     int(message.get("cursor", 0)), completed)

    def close(self, wait=True, timeout=1.0):
        self.destroy()
        return not self.winfo_exists()


class TransferCenterDialog(TransferCenterLogic, FloatingDialogController):
    def __init__(self, view):
        self._idle_preparation = True
        self.tasks = []
        self._active_batch_failed = False
        self._row_ids = itertools.count(1)
        self._row_to_task = {}
        self._row_update_lock = threading.Lock()
        self._pending_row_updates = {}
        self._row_update_scheduled = False
        self._pending_row_additions = {}
        self._row_add_scheduled = False
        super().__init__(view, "transfer_center", "Transfer Center", width=820, height=500,
                          visible=False, retain_on_close=True,
                          allow_minimize=True, allow_maximize=True)

    def show(self):
        self._idle_preparation = False
        return super().show()

    lift = show
    activate = show
    focus = show

    def _evict_retained(self, generation):
        # Hide is not cancellation. Cache pressure from opening other tools
        # must never terminate the progress host while a transfer is active.
        if self._has_active_tasks():
            return False
        return super()._evict_retained(generation)

    def _failed(self, message, details="", stage=""):
        if self._idle_preparation and not self._visible:
            from ..diagnostics import log_event
            self._append_failure_log(message, details, stage)
            log_event("Transfer window idle preparation failed: {}".format(message))
            self._reuse_host = False
            self.destroy()
            return
        return super()._failed(message, details=details, stage=stage)

    def post(self, command, *args, **kwargs):
        if command == "add_row":
            if self._closed:
                return False
            with self._row_update_lock:
                self._pending_row_additions[args[0]] = args
                schedule = not self._row_add_scheduled
                self._row_add_scheduled = True
            if schedule:
                self.view.after(0, self._flush_row_additions)
            return True
        if command == "remove_row":
            with self._row_update_lock:
                if self._pending_row_additions.pop(args[0], None) is not None:
                    return True
        if command == "flush_row_updates":
            self.view.after(0, self._flush_row_updates)
            return True
        return super().post(command, *args, **kwargs)

    def _flush_row_additions(self):
        with self._row_update_lock:
            rows = list(self._pending_row_additions.values())
            self._pending_row_additions.clear()
            self._row_add_scheduled = False
        if rows:
            super().post("add_rows", rows)

    def _flush_row_updates(self):
        self._flush_row_additions()
        updates = self._take_pending_row_updates()
        if updates:
            super().post("rows_update", updates)

    def handle_event(self, event, message):
        if event == "row_action":
            self._handle_row_action(message["row_id"])
        elif event == "cancel_all":
            self.cancel_all()
        elif event == "clear_finished":
            self.clear_finished()

    def destroy(self, **kwargs):
        self.cancel_all(update_ui=False)
        super().destroy(**kwargs)
