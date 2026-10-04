from __future__ import annotations

from pathlib import Path
from copy import deepcopy
import json

from ..abaqus_version_preferences import AbaqusVersionPreferences
from ..services.odb_extract import build_combined_curves
from ..services.odb_check import check_local_odb
from ..runtime.operation_context import OperationContext


class OdbAnalysisController:
    def __init__(self, app):
        self.app = app

    @property
    def view(self):
        return self.app.view

    @property
    def server(self):
        return self.app.server

    def check_odb(self, panel, selected_paths=None):
        """Post-process one local or server ODB and show the shared result UI."""
        panel_id = str(getattr(panel, "panel_id", "") or "")
        if self.app._closing:
            return
        if panel_id not in ("local", "server"):
            return
        if panel_id == "server" and not self.app._ensure_server_online():
            return

        selected = list(selected_paths if selected_paths is not None
                        else panel.selected_transfer_paths())
        selected = [path for path in selected
                    if str(path).casefold().endswith(".odb")]
        if len(selected) != 1:
            return

        if panel_id == "server":
            path = self.server.normalize(selected[0])
        else:
            path = Path(selected[0]).expanduser()
        panel.status.set("Checking ODB {}...".format(path.name))

        context = OperationContext(self.app, remote=panel.panel_id == "server")

        def worker():
            try:
                context.check()
                commands = AbaqusVersionPreferences().ordered_commands()
                if panel_id == "server":
                    result = self.server.check_odb(
                        path, abaqus_commands=commands)
                else:
                    result = check_local_odb(
                        path, abaqus_commands=commands,
                        timeout=self.server.ODB_CHECK_TIMEOUT_SECONDS)
            except Exception as exc:
                context.post(0, self.app._odb_check_failed, panel, str(exc))
                return
            context.post(0, self.app._odb_check_succeeded, panel, result)

        handle = self.app._submit_analysis(
            "check-odb:{}:{}".format(panel_id, path.name), worker,
            key=("check-odb", panel_id, str(path), context.connection if context.remote else None), coalesce=True)
        context.report_rejection(handle, self.app._odb_check_failed, panel)

    def _odb_check_succeeded(self, panel, result):
        panel.status.set("ODB check completed")
        self.view.show_odb_check(result)

    def _odb_check_failed(self, panel, error):
        panel.status.set("ODB check failed")
        self.view.show_error("Check ODB", error)

    def extract_odb(self, panel, selected_paths=None):
        """Open selective History Output extraction for one server-side ODB."""
        if self.app._closing or panel.panel_id != "server":
            return
        if not self.app._ensure_server_online():
            return
        paths = list(selected_paths if selected_paths is not None
                     else panel.selected_transfer_paths())
        paths = [self.server.normalize(path) for path in paths
                 if str(path).casefold().endswith(".odb")]
        if len(paths) != 1:
            return
        path = paths[0]
        panel.status.set("Reading ODB History Output list...")

        context = OperationContext(self.app, remote=panel.panel_id == "server")

        def worker():
            try:
                context.check()
                commands = AbaqusVersionPreferences().ordered_commands()
                catalog = self.server.list_odb_history_outputs(
                    path, abaqus_commands=commands)
            except Exception as exc:
                context.post(0, self.app._odb_extract_failed, panel, str(exc))
                return
            context.post(
                0, self.app._odb_extract_catalog_ready, panel, path, catalog)

        handle = self.app._submit_analysis(
            "odb-history-catalog:{}".format(path.name), worker,
            key=("odb-history-catalog", str(path), context.connection), coalesce=True)
        context.report_rejection(handle, self.app._odb_extract_failed, panel)

    def _odb_extract_catalog_ready(self, panel, path, catalog):
        context = OperationContext(self.app, remote=True)
        rows = list(catalog.get("historyOutputs") or [])
        panel.status.set("{} History Output item{}".format(
            len(rows), "" if len(rows) == 1 else "s"))
        if not rows:
            self.view.show_message(
                "Extract ODB Data", "No History Output data was found in this ODB.")
            return

        def selected(selection):
            if self.app._closing:
                return
            if context.current():
                self.app._extract_odb_selected(panel, path, selection)
            else:
                self.view.show_error("Extract ODB Data", "Server connection changed; reopen the extraction dialog")

        self.view.show_odb_extract(catalog, selected)

    def _extract_odb_selected(self, panel, path, selection):
        selection = deepcopy(selection or {})
        x_items = list((selection or {}).get("x") or [])
        y_items = list((selection or {}).get("y") or [])
        if not x_items or not y_items:
            return
        unique = []
        seen = set()
        for item in x_items + y_items:
            item_id = str(item.get("id") or "")
            if item_id and item_id not in seen:
                seen.add(item_id)
                unique.append(dict(item))
        panel.status.set(
            "Extracting {} selected History Output item{}...".format(
                len(unique), "" if len(unique) == 1 else "s"))

        context = OperationContext(self.app, remote=panel.panel_id == "server")

        def worker():
            try:
                context.check()
                commands = AbaqusVersionPreferences().ordered_commands()
                extracted = self.server.extract_odb_history_data(
                    path, unique, abaqus_commands=commands)
                result = build_combined_curves(extracted, selection)
                result["abaqusCommand"] = extracted.get("abaqusCommand")
                result["analysisSeconds"] = extracted.get("analysisSeconds")
                result["remoteSize"] = extracted.get("remoteSize")
            except Exception as exc:
                context.post(0, self.app._odb_extract_failed, panel, str(exc))
                return
            context.post(0, self.app._odb_extract_succeeded, panel, result)

        key = (
            "odb-history-data", str(path),
            json.dumps(selection, sort_keys=True, default=str), context.connection,
        )
        handle = self.app._submit_analysis(
            "odb-history-data:{}".format(path.name), worker,
            key=key, coalesce=True)
        context.report_rejection(handle, self.app._odb_extract_failed, panel)

    def _odb_extract_succeeded(self, panel, result):
        curves = list(result.get("curves") or [])
        panel.status.set("Created {} combined data set{}".format(
            len(curves), "" if len(curves) == 1 else "s"))
        if not curves:
            self.view.show_message(
                "Extract ODB Data",
                "The selected History Output data could not be combined.")
            return
        self.view.show_odb_xy_results(result)

    def _odb_extract_failed(self, panel, error):
        panel.status.set("ODB data extraction failed")
        self.view.show_error("Extract ODB Data", error)

