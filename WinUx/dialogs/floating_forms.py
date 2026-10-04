"""Factories and RPC endpoints for every standalone dialog client area."""
from __future__ import annotations

from .login_form import LoginForm
from .blocking_form import BlockingDialog
from .bookmarks_form import BookmarksDialog
from .site_manager_form import SiteManagerDialog
from .sync_preview_form import SyncPreviewDialog
from .server_path_form import ServerPathDialog
from .local_folder_form import LocalFolderDialog
from .progress_form import ProgressDialog
from .job_edit_form import JobEditDialog
from .job_manager_form import JobManagerDialog
from .job_schedule_form import JobScheduleDialog
from .settings_form import SettingsDialog
from .diagnostics_form import DiagnosticsDialog
from .odb_check_form import ODBCheckDialog
from .odb_extract_form import ODBExtractDialog, ODBXYResultDialog
from .console_form import ConsoleDialog
from .transfer_center_form import TransferCenterDialog


FORM_KINDS = ("login", "blocking", "bookmarks", "sites", "sync", "server_path", "local_folder",
              "progress", "job_edit", "job_manager", "job_schedule", "settings",
              "diagnostics", "odb_check", "odb_extract", "odb_xy", "console", "transfer_center")


def create_form(kind, payload, view, emit):
    result = lambda value: emit("result", value=value)
    state = {}
    if kind == "login":
        form = LoginForm(view, lambda form, values: emit("submit", values=values), initial=payload.get("initial", {}))
    elif kind == "blocking":
        form = BlockingDialog(view, on_result=result, **payload)
    elif kind == "bookmarks":
        form = BookmarksDialog(view, payload.get("entries", []),
            lambda entry: emit("open", entry=entry), lambda entry: emit("remove", entry=entry),
            lambda entry, label: emit("rename", entry=entry, label=label),
            rename_prompt=lambda entry: emit("rename_prompt", entry=entry))
    elif kind == "sites":
        form = SiteManagerDialog(view, payload.get("sites", []),
            lambda values: emit("save", values=values), lambda values: emit("delete", values=values),
            lambda values: emit("connect", values=values))
    elif kind == "sync":
        form = SyncPreviewDialog(view, payload.get("rows", []), payload.get("local_path", ""), payload.get("server_path", ""),
            lambda: emit("refresh"), lambda rows: emit("transfer", rows=rows))
    elif kind == "server_path":
        form = ServerPathDialog(view, payload.get("initial", "/"), lambda path: [], on_selected=result)
        form.request_search = lambda generation, value: emit("search", generation=generation, value=value)
    elif kind == "local_folder":
        form = LocalFolderDialog(view, payload.get("initial", ""), on_result=result)
    elif kind == "progress":
        class CancelEvent:
            def set(self):
                emit("cancel")
        form = ProgressDialog(view, payload.get("operation", "Transfer"), CancelEvent())
    elif kind == "job_edit":
        form = JobEditDialog(view, payload.get("values", []), payload.get("settings", {}), on_result=result)
    elif kind == "job_manager":
        form = JobManagerDialog(view, payload.get("paths", []),
            lambda form, jobs: emit("run", jobs=jobs), lambda form, paths: emit("estimate"))
    elif kind == "job_schedule":
        state["rows"] = payload.get("rows", [])
        def provider():
            emit("refresh")
            return state["rows"]
        form = JobScheduleDialog(view, provider, lambda action, kind, key: emit("action", action=action, kind=kind, key=key))
    elif kind == "settings":
        form = SettingsDialog(view)
    elif kind == "diagnostics":
        state["report"] = str(payload.get("report", ""))
        def provider():
            emit("refresh")
            return state["report"]
        form = DiagnosticsDialog(view, report_provider=provider)
    elif kind == "odb_check":
        form = ODBCheckDialog(view, payload.get("result", {}))
    elif kind == "odb_extract":
        form = ODBExtractDialog(view, payload.get("catalog", {}), on_result=result)
    elif kind == "odb_xy":
        form = ODBXYResultDialog(view, payload.get("result", {}))
    elif kind == "console":
        state["output"] = ""
        form = ConsoleDialog(view, lambda: state["output"],
            lambda command: emit("command", value=command), lambda: emit("interrupt"))
    elif kind == "transfer_center":
        form = TransferCenterDialog(view, on_cancel_all=lambda: emit("cancel_all"),
            on_clear_finished=lambda: emit("clear_finished"), on_row_action=lambda row_id: emit("row_action", row_id=row_id))
    else:
        raise ValueError("Unsupported floating dialog type: {}".format(kind))
    form._remote_state = state
    form._floating_kind = kind
    return form


def deliver_command(form, command, args):
    state = form._remote_state
    if form._floating_kind == "job_schedule" and command == "set_rows":
        state["rows"] = args[0]
    elif form._floating_kind == "diagnostics" and command == "report":
        state["report"] = str(args[0])
    elif form._floating_kind == "console" and command == "output":
        state["output"] = str(args[0])
    elif form._floating_kind == "transfer_center" and command == "rows_update":
        with form._row_update_lock:
            form._pending_row_updates = dict(args[0])
        form.handle_command("flush_row_updates")
        return
    form.handle_command(command, *args)


def client_layout(form):
    """Geometry diagnostics, never editor/credential contents."""
    import dearpygui.dearpygui as dpg
    def bounds(item):
        left, top = dpg.get_item_rect_min(item)
        width, height = dpg.get_item_rect_size(item)
        return [left, top, left+width, top+height]
    widgets = {}
    if form._floating_kind == "login":
        widgets = {name: bounds(item) for name, item in (
            ("host", form.host), ("host_arrow", form.host_combo.button),
            ("username", form.username), ("username_arrow", form.username_combo.button),
            ("password", form.password), ("connect", form.connect_button), ("cancel", form.cancel_button))}
    elif form._floating_kind == "job_manager" and form.rows_by_path:
        row = next(iter(form.rows_by_path.values()))
        widgets = {name: bounds(row[name]) for name in ("run", "version", "cpus", "precision", "overwrite", "schedule", "time")}
    return {"client": [dpg.get_viewport_client_width(), dpg.get_viewport_client_height()],
            "widgets": widgets, "footer": bounds(form.footer) if form.has_footer else [0, dpg.get_viewport_client_height(), 0, dpg.get_viewport_client_height()],
            "shell_scrollbar": not dpg.get_item_configuration(form.tag)["no_scrollbar"]}
