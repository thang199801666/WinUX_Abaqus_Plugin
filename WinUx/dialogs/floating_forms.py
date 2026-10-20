"""Factories and RPC endpoints for every standalone dialog client area."""
from __future__ import annotations

FORM_KINDS = ("login", "blocking", "bookmarks", "sites", "sync", "server_path", "local_folder", "local_file", "plotdigitizer",
              "progress", "job_edit", "job_manager", "job_schedule", "settings",
               "diagnostics", "odb_check", "odb_extract", "odb_xy", "console", "transfer_center",
                 "reference_chart", "console_dock", "plot_dock")


def prepare_common_form_imports():
    """Pay common form import cost in a hidden worker, never construct a form.

    Cold launches remain lazy. Do not warm tools with application/background
    work (PlotDigitizer, ODB, SSH, etc.) or retain credentials/filesystem state.
    """
    import os
    from importlib import import_module
    # Real process-hosted top-level dialogs are the default.  A deployment may
    # explicitly opt back into legacy main-context dialogs; only then can the
    # lightweight forms be excluded from the hidden worker warm set.
    modules = [
        "blocking_form", "login_form", "local_folder_form", "local_file_form",
    ]
    use_inprocess = str(os.environ.get("WINUX_INPROCESS_DIALOGS", "0")).strip().lower() \
        not in {"0", "false", "off", "no"}
    if not use_inprocess:
        # Default native-top-level mode warms these forms off the click path.
        modules.extend((
            "settings_form", "job_schedule_form", "bookmarks_form",
            "site_manager_form", "sync_preview_form", "diagnostics_form",
            "transfer_center_form",
        ))
    for module in modules:
        import_module("." + module, __package__)


def create_form(kind, payload, view, emit):
    result = lambda value: emit("result", value=value)
    state = {}
    if kind == "login":
        from .login_form import LoginForm
        form = LoginForm(view, lambda form, values: emit("submit", values=values), initial=payload.get("initial", {}))
    elif kind == "blocking":
        from .blocking_form import BlockingDialog
        form = BlockingDialog(view, on_result=result, **payload)
    elif kind == "bookmarks":
        from .bookmarks_form import BookmarksDialog
        form = BookmarksDialog(view, payload.get("entries", []),
            lambda entry: emit("open", entry=entry), lambda entry: emit("remove", entry=entry),
            lambda entry, label: emit("rename", entry=entry, label=label),
            rename_prompt=lambda entry: emit("rename_prompt", entry=entry))
    elif kind == "sites":
        from .site_manager_form import SiteManagerDialog
        form = SiteManagerDialog(view, payload.get("sites", []),
            lambda values: emit("save", values=values), lambda values: emit("delete", values=values),
            lambda values: emit("connect", values=values))
    elif kind == "sync":
        from .sync_preview_form import SyncPreviewDialog
        form = SyncPreviewDialog(view, payload.get("rows", []), payload.get("local_path", ""), payload.get("server_path", ""),
            lambda: emit("refresh"), lambda rows: emit("transfer", rows=rows))
    elif kind == "server_path":
        from .server_path_form import ServerPathDialog
        form = ServerPathDialog(view, payload.get("initial", "/"), lambda path: [], on_selected=result)
        form.request_search = lambda generation, value: emit("search", generation=generation, value=value)
    elif kind == "local_folder":
        from .local_folder_form import LocalFolderDialog
        form = LocalFolderDialog(view, payload.get("initial", ""), on_result=result)
    elif kind == "local_file":
        from .local_file_form import LocalFileDialog
        form = LocalFileDialog(
            view, payload.get("initial", ""), on_result=result,
            extensions=payload.get("extensions", ()), save=payload.get("save", False),
            default_filename=payload.get("default_filename", ""))
    elif kind == "plotdigitizer":
        from ..plotdigitizer.ui import PlotDigitizerDialog
        from ..plotdigitizer.application import reference_candidate

        class ReferenceSink:
            available = bool(payload.get("reference_available"))

            def add_dataset(self, dataset):
                candidate = reference_candidate(dataset, ())
                emit("reference", candidate=candidate)
                return candidate

        form = PlotDigitizerDialog(view, reference_sink=ReferenceSink())
    elif kind == "progress":
        from .progress_form import ProgressDialog
        class CancelEvent:
            def set(self):
                emit("cancel")
        form = ProgressDialog(view, payload.get("operation", "Transfer"), CancelEvent())
    elif kind == "job_edit":
        from .job_edit_form import JobEditDialog
        form = JobEditDialog(view, payload.get("values", []), payload.get("settings", {}), on_result=result)
    elif kind == "job_manager":
        from .job_manager_form import JobManagerDialog
        form = JobManagerDialog(view, payload.get("paths", []),
            lambda form, jobs: emit("run", jobs=jobs), lambda form, paths: emit("estimate"))
    elif kind == "job_schedule":
        from .job_schedule_form import JobScheduleDialog
        state["rows"] = payload.get("rows", [])
        def provider():
            emit("refresh")
            return state["rows"]
        form = JobScheduleDialog(view, provider, lambda action, kind, key: emit("action", action=action, kind=kind, key=key))
    elif kind == "settings":
        from .settings_form import SettingsDialog
        form = SettingsDialog(view, on_install_update=lambda: emit("install_update"),
                              on_settings_saved=lambda values: emit("settings_saved", values=values))
    elif kind == "diagnostics":
        from .diagnostics_form import DiagnosticsDialog
        state["report"] = str(payload.get("report", ""))
        def provider():
            emit("refresh")
            return state["report"]
        form = DiagnosticsDialog(view, report_provider=provider)
    elif kind == "odb_check":
        from .odb_check_form import ODBCheckDialog
        form = ODBCheckDialog(view, payload.get("result", {}))
    elif kind == "odb_extract":
        from .odb_extract_form import ODBExtractDialog
        form = ODBExtractDialog(view, payload.get("catalog", {}), on_result=result)
    elif kind == "reference_chart":
        from .reference_chart_form import ReferenceChartDialog
        form = ReferenceChartDialog(
            view, payload.get("series", []), on_result=result,
            history_outputs=payload.get("history_outputs", []))
    elif kind == "odb_xy":
        from .odb_extract_form import ODBXYResultDialog
        form = ODBXYResultDialog(view, payload.get("result", {}))
    elif kind == "console":
        from .console_form import ConsoleDialog
        state["output"] = ""
        completion_waiters = {}
        completion_counter = [0]
        def request_completion(draft, cursor, done):
            completion_counter[0] += 1
            request_id = completion_counter[0]
            completion_waiters[request_id] = done
            emit("complete", request_id=request_id, draft=draft, cursor=int(cursor))
            return True
        def show_completion_list(draft, candidates, columns=80):
            emit("completion_list", draft=str(draft), candidates=list(candidates),
                 columns=int(columns))
            return True
        form = ConsoleDialog(view, lambda: state["output"],
            lambda command: emit("command", value=command), lambda: emit("interrupt"),
            completion_callback=request_completion,
            completion_list_callback=show_completion_list)
        form._completion_waiters = completion_waiters
    elif kind == "console_dock":
        from .native_dock_forms import ConsoleDockForm
        form = ConsoleDockForm(view, payload, emit)
    elif kind == "plot_dock":
        from .native_dock_forms import PlotDockForm
        form = PlotDockForm(view, payload, emit)
    elif kind == "transfer_center":
        from .transfer_center_form import TransferCenterDialog
        form = TransferCenterDialog(view, on_cancel_all=lambda: emit("cancel_all"),
            on_clear_finished=lambda: emit("clear_finished"), on_row_action=lambda row_id: emit("row_action", row_id=row_id))
    else:
        raise ValueError("Unsupported floating dialog type: {}".format(kind))
    form._remote_state = state
    form._floating_kind = kind
    return form


def deliver_command(form, command, args):
    if command == "dialog_accept":
        form.accept()
        return
    state = form._remote_state
    if form._floating_kind == "job_schedule" and command == "set_rows":
        state["rows"] = args[0]
    elif form._floating_kind == "diagnostics" and command == "report":
        state["report"] = str(args[0])
    elif form._floating_kind == "console" and command == "output":
        state["output"] = str(args[0])
    elif form._floating_kind == "console" and command == "completion_result":
        request_id, result = int(args[0]), args[1]
        callback = getattr(form, "_completion_waiters", {}).pop(request_id, None)
        if callable(callback):
            callback(result)
        return
    elif form._floating_kind == "transfer_center" and command == "rows_update":
        with form._row_update_lock:
            form._pending_row_updates = dict(args[0])
        form.handle_command("flush_row_updates")
        return
    form.handle_command(command, *args)


def client_layout(form):
    """Geometry diagnostics, never editor/credential contents."""
    from DearUIQt.backends import dpg
    def bounds(item):
        from ..ui.workspace import item_rect
        rect = item_rect(item, dpg)
        if rect is None:
            raise ValueError("No layout bounds for item {}".format(item))
        return list(rect)
    widgets = {}
    if form._floating_kind == "login":
        widgets = {name: bounds(item) for name, item in (
            ("host", form.host), ("username", form.username),
            ("password", form.password), ("connect", form.connect_button), ("cancel", form.cancel_button))}
        from DearUIQt.gui.style import METRICS
        for name, combo in (("host_arrow", form.host_combo), ("username_arrow", form.username_combo)):
            left, top, right, bottom = bounds(combo.tag)
            widgets[name] = [right - METRICS.arrow_width - 1, top + 1, right - 1, bottom - 1]
    elif form._floating_kind == "job_manager" and form.rows_by_path:
        row = next(iter(form.rows_by_path.values()))
        widgets = {name: bounds(row[name]) for name in ("run", "version", "cpus", "precision", "overwrite", "schedule", "time")}
    elif form._floating_kind == "reference_chart":
        from DearUIQt.backends.dearpygui import dpg_window_rect
        widgets = {name: bounds(item) for name, item in (
            ("series_name", form.name_edit), ("add", form.add_button))}
        widgets["data"] = list(dpg_window_rect(dpg, form.data_table.tag))
    elif form._floating_kind == "plotdigitizer":
        widgets = {name: bounds(item) for name, item in (
            ("datasets", form.dataset_panel),
            ("canvas", form.canvas), ("settings", form.settings_panel))}
    elif form._floating_kind == "local_file":
        widgets = {name: bounds(item) for name, item in (
            ("filename", form.file_edit), ("file_type", form.file_type),
            ("list", form.listbox.tag))}
    return {"client": [dpg.get_viewport_client_width(), dpg.get_viewport_client_height()],
            "typography": {"family": getattr(form.view, "ui_font_family", ""),
                           "size": getattr(form.view, "ui_font_size", 0)},
            "widgets": widgets, "footer": bounds(form.footer) if form.has_footer else [0, dpg.get_viewport_client_height(), 0, dpg.get_viewport_client_height()],
            "shell_scrollbar": not dpg.get_item_configuration(form.tag)["no_scrollbar"]}
