from __future__ import annotations

from pathlib import Path
from copy import deepcopy
import json

from ...preferences.abaqus_versions import AbaqusVersionPreferences
from ...services.odb.extract import build_combined_curves
from ...services.odb.check import check_local_odb
from ...services.odb.upgrade import (
    check_local_odb_upgrades, upgrade_local_odbs,
)
from ...runtime.operation_context import OperationContext


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

        def worker():
            try:
                context.check()
                commands = AbaqusVersionPreferences().ordered_commands()
                if panel_id == "server":
                    result = self.server.check_odb_upgrade_requirements(
                        paths, abaqus_commands=commands)
                else:
                    result = check_local_odb_upgrades(
                        paths, abaqus_commands=commands)
            except Exception as exc:
                context.post(
                    0, self.app._odb_upgrade_failed, panel,
                    "Could not check ODB upgrade status: {}".format(exc))
                return
            context.post(0, self.app._odb_upgrade_checked, panel, result)

        key = (
            "upgrade-odb-check", panel_id,
            tuple(str(path) for path in paths),
            context.connection if context.remote else None,
        )
        handle = self.app._submit_analysis(
            "upgrade-odb-check:{}:{}".format(panel_id, len(paths)),
            worker, key=key, coalesce=True)
        context.report_rejection(handle, self.app._odb_upgrade_failed, panel)

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

        def worker():
            try:
                context.check()
                if panel_id == "server":
                    result = self.server.upgrade_odbs(
                        paths, abaqus_command=abaqus_command,
                        overwrite=overwrite)
                else:
                    result = upgrade_local_odbs(
                        paths, abaqus_command=abaqus_command,
                        overwrite=overwrite)
            except Exception as exc:
                context.post(0, self.app._odb_upgrade_failed, panel, str(exc))
                return
            context.post(0, self.app._odb_upgrade_succeeded, panel, result)

        key = (
            "upgrade-odb-run", panel_id,
            tuple(str(path) for path in paths), str(abaqus_command),
            bool(overwrite), context.connection if context.remote else None,
        )
        handle = self.app._submit_analysis(
            "upgrade-odb:{}:{}".format(panel_id, len(paths)),
            worker, key=key, coalesce=True)
        context.report_rejection(handle, self.app._odb_upgrade_failed, panel)

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

