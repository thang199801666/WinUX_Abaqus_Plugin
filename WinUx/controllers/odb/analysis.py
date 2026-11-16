from __future__ import annotations

from pathlib import Path
from copy import deepcopy
import json

from ...preferences.abaqus_versions import AbaqusVersionPreferences
from ...services.odb.extract import (
    build_combined_curves, list_local_odb_history_outputs,
    extract_local_odb_history_data,
)
from ...services.odb.check import check_local_odb
from ...services.odb.upgrade import (
    check_local_odb_upgrades, upgrade_local_odbs,
)
from ...runtime.operation_context import OperationContext
from ...runtime.completion import submit_with_completion


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

        context = OperationContext(self.app, remote=panel_id == "server")
        server = (getattr(context, "server", None) or self.server) if context.remote else self.server

        def worker():
            context.check()
            commands = AbaqusVersionPreferences().ordered_commands()
            if panel_id == "server":
                return server.check_odb(path, abaqus_commands=commands)
            return check_local_odb(
                path, abaqus_commands=commands,
                timeout=server.ODB_CHECK_TIMEOUT_SECONDS)

        def completed(handle):
            if self.app._closing or (context.remote and not context.current()):
                return
            if handle.state == "completed":
                self.app._odb_check_succeeded(panel, handle.result)
            else:
                error = handle.exception or RuntimeError("ODB check cancelled")
                self.app._odb_check_failed(panel, str(error))

        submit_with_completion(
            self.app._submit_analysis, getattr(self.app, "_analysis_tasks", None),
            "check-odb:{}:{}".format(panel_id, path.name), worker, completed, scheduler=self.view,
            key=("check-odb", panel_id, str(path), context.connection if context.remote else None),
            coalesce=True, session_scoped=context.remote)

    def _odb_check_succeeded(self, panel, result):
        panel.status.set("ODB check completed")
        self.view.show_odb_check(result)

    def _odb_check_failed(self, panel, error):
        panel.status.set("ODB check failed")
        self.view.show_error("Check ODB", error)

    @staticmethod
    def _odb_upgrade_names(rows, limit=8):
        rows = list(rows or [])
        names = [str(row.get("name") or row.get("path") or "ODB") for row in rows]
        shown = names[:max(1, int(limit))]
        lines = ["- {}".format(name) for name in shown]
        if len(names) > len(shown):
            lines.append("- ... and {} more".format(len(names) - len(shown)))
        return lines

    def upgrade_odb(self, panel, selected_paths=None):
        """Check selected ODBs and, after confirmation, upgrade in place."""
        panel_id = str(getattr(panel, "panel_id", "") or "")
        if self.app._closing or panel_id not in ("local", "server"):
            return
        if panel_id == "server" and not self.app._ensure_server_online():
            return

        selected = list(selected_paths if selected_paths is not None
                        else panel.selected_transfer_paths())
        # Mixed Explorer selections are supported.  Upgrade only the ODB
        # subset and ignore unrelated files/folders, matching the context-menu
        # enable-state contract.
        selected = [path for path in selected
                    if str(path).casefold().endswith(".odb")]
        if not selected:
            self.view.show_error(
                "Upgrade ODB", "Select at least one .odb file.")
            return
        # Preserve selection order while eliminating accidental duplicates.
        unique = []
        seen = set()
        for path in selected:
            key = str(path)
            if key in seen:
                continue
            seen.add(key)
            unique.append(path)
        if panel_id == "server":
            paths = [self.server.normalize(path) for path in unique]
        else:
            paths = [Path(path).expanduser() for path in unique]

        panel.status.set("Checking ODB upgrade requirements...")
        context = OperationContext(self.app, remote=panel_id == "server")
        server = (getattr(context, "server", None) or self.server) if context.remote else self.server

        def worker():
            context.check()
            commands = AbaqusVersionPreferences().ordered_commands()
            if panel_id == "server":
                return server.check_odb_upgrade_requirements(
                    paths, abaqus_commands=commands)
            return check_local_odb_upgrades(paths, abaqus_commands=commands)

        def completed(handle):
            if self.app._closing or (context.remote and not context.current()):
                return
            if handle.state == "completed":
                self.app._odb_upgrade_checked(panel, handle.result)
            else:
                error = handle.exception or RuntimeError("ODB upgrade check cancelled")
                self.app._odb_upgrade_failed(
                    panel, "Could not check ODB upgrade status: {}".format(error))

        key = (
            "upgrade-odb-check", panel_id,
            tuple(str(path) for path in paths),
            context.connection if context.remote else None,
        )
        submit_with_completion(
            self.app._submit_analysis, getattr(self.app, "_analysis_tasks", None),
            "upgrade-odb-check:{}:{}".format(panel_id, len(paths)),
            worker, completed, scheduler=self.view, key=key, coalesce=True, session_scoped=context.remote)

    def _odb_upgrade_checked(self, panel, result):
        if self.app._closing:
            return
        rows = list((result or {}).get("results") or [])
        command = str((result or {}).get("abaqusCommand") or "Abaqus")
        errors = [row for row in rows if row.get("error")]
        if errors:
            lines = [
                "WinUx could not determine the upgrade state of all selected ODB files.",
                "",
            ]
            for row in errors[:8]:
                lines.append("- {}: {}".format(
                    row.get("name") or row.get("path") or "ODB",
                    row.get("error")))
            if len(errors) > 8:
                lines.append("- ... and {} more".format(len(errors) - 8))
            panel.status.set("ODB upgrade check failed")
            self.view.show_error("Upgrade ODB", "\n".join(lines))
            return

        needs = [row for row in rows if bool(row.get("requiresUpgrade"))]
        current = [row for row in rows if not bool(row.get("requiresUpgrade"))]
        if not needs:
            panel.status.set("ODB files are already upgraded")
            message = [
                "All selected ODB files are already compatible with {} and do not need to be upgraded again."
                .format(command),
            ]
            if rows:
                message.extend(["", *self._odb_upgrade_names(rows)])
            self.view.show_message("Upgrade ODB", "\n".join(message))
            return

        message = [
            "{} ODB file{} require{} an upgrade using {}.".format(
                len(needs), "" if len(needs) == 1 else "s",
                "s" if len(needs) == 1 else "", command),
            "",
            "Files to upgrade:",
        ]
        message.extend(self._odb_upgrade_names(needs))
        if current:
            message.extend([
                "",
                "{} selected file{} already current and will be skipped.".format(
                    len(current), " is" if len(current) == 1 else "s are"),
            ])
        message.extend([
            "",
            "With overwrite enabled, WinUx replaces the original only after Abaqus completes successfully.",
            "If overwrite is disabled, WinUx keeps the original and creates a new *_upgraded.odb file instead.",
            "Up to 4 ODB files will be upgraded in parallel.",
            "Continue?",
        ])
        paths = [row.get("path") for row in needs if row.get("path")]
        panel.status.set("{} ODB file{} need upgrade".format(
            len(needs), "" if len(needs) == 1 else "s"))
        self.view.confirm_action_checkbox_async(
            "Upgrade ODB",
            "\n".join(message),
            lambda confirmed, overwrite, target=panel, selected=paths, executable=command:
                self._start_odb_upgrade(
                    target, selected, executable, overwrite=overwrite)
                if confirmed else None,
            checkbox_text="Overwrite original files",
            checkbox_checked=True,
            primary_text="Upgrade",
            secondary_text="Cancel",
            intent="warning",
        )

    def _start_odb_upgrade(self, panel, paths, abaqus_command, overwrite=True):
        if self.app._closing or not paths:
            return
        panel_id = str(getattr(panel, "panel_id", "") or "")
        if panel_id == "server" and not self.app._ensure_server_online():
            return
        worker_count = min(4, max(1, len(paths)))
        panel.status.set(
            "Upgrading {} ODB file{} with {} worker{}{}...".format(
                len(paths), "" if len(paths) == 1 else "s",
                worker_count, "" if worker_count == 1 else "s",
                "" if overwrite else " (keep originals)"))
        context = OperationContext(self.app, remote=panel_id == "server")
        server = (getattr(context, "server", None) or self.server) if context.remote else self.server

        def worker():
            context.check()
            if panel_id == "server":
                return server.upgrade_odbs(
                    paths, abaqus_command=abaqus_command, overwrite=overwrite)
            return upgrade_local_odbs(
                paths, abaqus_command=abaqus_command, overwrite=overwrite)

        def completed(handle):
            if self.app._closing or (context.remote and not context.current()):
                return
            if handle.state == "completed":
                self.app._odb_upgrade_succeeded(panel, handle.result)
            else:
                error = handle.exception or RuntimeError("ODB upgrade cancelled")
                self.app._odb_upgrade_failed(panel, str(error))

        key = (
            "upgrade-odb-run", panel_id,
            tuple(str(path) for path in paths), str(abaqus_command),
            bool(overwrite), context.connection if context.remote else None,
        )
        submit_with_completion(
            self.app._submit_analysis, getattr(self.app, "_analysis_tasks", None),
            "upgrade-odb:{}:{}".format(panel_id, len(paths)),
            worker, completed, scheduler=self.view, key=key, coalesce=True, session_scoped=context.remote)

    def _odb_upgrade_succeeded(self, panel, result):
        rows = list((result or {}).get("results") or [])
        command = str((result or {}).get("abaqusCommand") or "Abaqus")
        upgraded = [row for row in rows if row.get("status") == "upgraded"]
        current = [row for row in rows if row.get("status") == "current"]
        failed = [row for row in rows if row.get("status") == "error" or row.get("error")]

        if upgraded:
            try:
                self.app.open_path(panel, panel.current_path, False)
            except Exception:
                pass
        panel.status.set(
            "Upgraded {} ODB file{}".format(
                len(upgraded), "" if len(upgraded) == 1 else "s")
            if upgraded else "ODB upgrade completed")

        worker_count = int((result or {}).get("workerCount") or 1)
        lines = [
            "Abaqus command: {}".format(command),
            "Upgrade workers: {}".format(worker_count),
            "",
        ]
        overwrite = bool((result or {}).get("overwrite", True))
        if upgraded:
            if overwrite:
                lines.append("Upgraded successfully / originals replaced ({}):".format(
                    len(upgraded)))
                lines.extend(self._odb_upgrade_names(upgraded))
            else:
                lines.append("Upgraded copies created; originals kept ({}):".format(
                    len(upgraded)))
                for row in upgraded[:8]:
                    source = str(row.get("name") or row.get("path") or "ODB")
                    output = str(row.get("outputName") or row.get("outputPath") or "upgraded ODB")
                    lines.append("- {} -> {}".format(source, output))
                if len(upgraded) > 8:
                    lines.append("- ... and {} more".format(len(upgraded) - 8))
        if current:
            if len(lines) > 2:
                lines.append("")
            lines.append("Already current / skipped ({}):".format(len(current)))
            lines.extend(self._odb_upgrade_names(current))
        if failed:
            if len(lines) > 2:
                lines.append("")
            lines.append("Failed ({}):".format(len(failed)))
            for row in failed[:8]:
                lines.append("- {}: {}".format(
                    row.get("name") or row.get("path") or "ODB",
                    row.get("error") or "Upgrade failed"))
            if len(failed) > 8:
                lines.append("- ... and {} more".format(len(failed) - 8))

        if failed:
            self.view.show_error("Upgrade ODB", "\n".join(lines))
        else:
            self.view.show_message("Upgrade ODB", "\n".join(lines))

    def _odb_upgrade_failed(self, panel, error):
        panel.status.set("ODB upgrade failed")
        self.view.show_error("Upgrade ODB", str(error))

    def extract_odb(self, panel, selected_paths=None):
        """Open selective History Output extraction for one local/server ODB."""
        panel_id = str(getattr(panel, "panel_id", "") or "")
        if self.app._closing or panel_id not in ("local", "server"):
            return
        if panel_id == "server" and not self.app._ensure_server_online():
            return
        paths = list(selected_paths if selected_paths is not None
                     else panel.selected_transfer_paths())
        paths = [path for path in paths if str(path).casefold().endswith(".odb")]
        if len(paths) != 1:
            return
        path = (self.server.normalize(paths[0]) if panel_id == "server"
                else Path(paths[0]).expanduser())
        panel.status.set("Reading ODB History Output list...")

        context = OperationContext(self.app, remote=panel.panel_id == "server")
        server = (getattr(context, "server", None) or self.server) if context.remote else self.server

        def selected(selection):
            if self.app._closing:
                return
            if context.current():
                self.app._extract_odb_selected(panel, path, selection)
            else:
                self.view.show_error(
                    "Extract ODB Data",
                    "Server connection changed; reopen the extraction dialog")

        # Publish the dialog before Abaqus/remote catalog discovery.  ODB
        # startup can take seconds even though the work already runs off the UI
        # thread; delaying creation until the catalog is ready makes the command
        # feel blocked.  The dialog is a lightweight shell first and receives
        # its catalog over the existing floating-dialog IPC channel.
        dialog = self.view.show_odb_extract(
            {"historyOutputs": [], "loading": True, "sessionKey": str(path)}, selected)

        def worker():
            context.check()
            commands = AbaqusVersionPreferences().ordered_commands()
            if panel_id == "server":
                return server.list_odb_history_outputs(
                    path, abaqus_commands=commands)
            return list_local_odb_history_outputs(
                path, abaqus_commands=commands,
                timeout=server.ODB_CHECK_TIMEOUT_SECONDS)

        def completed(handle):
            if self.app._closing or (context.remote and not context.current()):
                return
            if handle.state == "completed":
                self.app._odb_extract_catalog_ready(
                    panel, path, handle.result, dialog=dialog)
            else:
                error = handle.exception or RuntimeError("ODB catalog read cancelled")
                self.app._odb_extract_failed(panel, str(error), dialog=dialog)

        submit_with_completion(
            self.app._submit_analysis, getattr(self.app, "_analysis_tasks", None),
            "odb-history-catalog:{}".format(path.name), worker, completed, scheduler=self.view,
            key=("odb-history-catalog", panel_id, str(path),
                 context.connection if context.remote else None),
            coalesce=True, session_scoped=context.remote)

    def _odb_extract_catalog_ready(self, panel, path, catalog, dialog=None):
        catalog = dict(catalog or {})
        catalog.setdefault("sessionKey", str(path))
        rows = list(catalog.get("historyOutputs") or [])
        panel.status.set("{} History Output item{}".format(
            len(rows), "" if len(rows) == 1 else "s"))
        if dialog is not None and getattr(dialog, "winfo_exists", lambda: False)():
            if rows:
                dialog.set_catalog(catalog)
            else:
                dialog.set_catalog(catalog, message=
                    "No History Output data was found in this ODB.")
            return
        # Compatibility fallback for callers that still complete without a
        # pre-published dialog.
        if not rows:
            self.view.show_message(
                "Extract ODB Data", "No History Output data was found in this ODB.")
            return

        context = OperationContext(
            self.app, remote=str(getattr(panel, "panel_id", "")) == "server")

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
        server = (getattr(context, "server", None) or self.server) if context.remote else self.server

        def worker():
            context.check()
            cached_series = []
            missing = []
            for item in unique:
                cached_points = item.get("cachedPoints")
                if cached_points is None:
                    missing.append(dict(item))
                    continue
                cached_series.append({
                    "id": str(item.get("id") or ""),
                    "step": str(item.get("step") or ""),
                    "historyRegion": str(item.get("historyRegion") or ""),
                    "output": str(item.get("output") or ""),
                    "description": str(item.get("description") or ""),
                    "displayName": str(item.get("displayName") or item.get("output") or ""),
                    "points": list(cached_points or []),
                    "skipped": 0,
                    "error": None,
                })

            # Small catalog histories are already resident from the catalog
            # pass.  Combine them locally and avoid a second Abaqus process /
            # openOdb entirely.  If only some selected histories were cached,
            # remote-extract only the missing IDs and merge both sources.
            remote = None
            if missing:
                commands = AbaqusVersionPreferences().ordered_commands()
                request_items = []
                for item in missing:
                    clean = dict(item)
                    clean.pop("cachedPoints", None)
                    request_items.append(clean)
                if panel.panel_id == "server":
                    remote = server.extract_odb_history_data(
                        path, request_items, abaqus_commands=commands,
                        abaqus_command=(selection or {}).get("abaqusCommand"))
                else:
                    remote = extract_local_odb_history_data(
                        path, request_items, abaqus_commands=commands,
                        abaqus_command=(selection or {}).get("abaqusCommand"),
                        timeout=server.ODB_CHECK_TIMEOUT_SECONDS)
                cached_series.extend(list(remote.get("series") or []))

            extracted = {
                "schemaVersion": 1,
                "mode": "extract",
                "odb": (remote or {}).get("odb", getattr(path, "name", "")),
                "path": (remote or {}).get("path", str(path)),
                "series": cached_series,
            }
            result = build_combined_curves(extracted, selection)
            result["abaqusCommand"] = ((remote or {}).get("abaqusCommand") or
                                        (selection or {}).get("abaqusCommand"))
            result["analysisSeconds"] = (remote or {}).get("analysisSeconds", 0.0)
            result["remoteSize"] = (remote or {}).get("remoteSize")
            result["cacheHit"] = not bool(missing)
            result["cachedSeries"] = len(cached_series) - len(list((remote or {}).get("series") or []))
            return result

        def completed(handle):
            if self.app._closing or (context.remote and not context.current()):
                return
            if handle.state == "completed":
                self.app._odb_extract_succeeded(panel, handle.result)
            else:
                error = handle.exception or RuntimeError("ODB extraction cancelled")
                self.app._odb_extract_failed(panel, str(error))

        key = (
            "odb-history-data", str(path),
            json.dumps(selection, sort_keys=True, default=str), context.connection,
        )
        submit_with_completion(
            self.app._submit_analysis, getattr(self.app, "_analysis_tasks", None),
            "odb-history-data:{}".format(path.name), worker, completed, scheduler=self.view,
            key=key, coalesce=True, session_scoped=context.remote)

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

    def _odb_extract_failed(self, panel, error, dialog=None):
        panel.status.set("ODB data extraction failed")
        if dialog is not None and getattr(dialog, "winfo_exists", lambda: False)():
            dialog.set_error(str(error))
            return
        self.view.show_error("Extract ODB Data", error)

