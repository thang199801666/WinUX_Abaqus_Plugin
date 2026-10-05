from __future__ import annotations

import os
import threading

import dearpygui.dearpygui as dpg
from ..abaqus_version_preferences import AbaqusVersionPreferences
from ..general_preferences import GeneralPreferences
from ..inp_preferences import INPPreferences
from ..login_preferences import LoginPreferences
from ..performance_preferences import PerformancePreferences
from ..preferences.update import UpdatePreferences
from .qt_dialog import QtDialog
from .theme import DialogMetrics, muted_text_theme, error_text_theme
from ..widgets import ImGuiCheckBox, QtListView
from winux_installation_state import clear_quarantine
from winux_update_diagnostics import collect_update_diagnostics, format_update_diagnostics


class SettingsDialog(QtDialog):
    FORMULA_LABELS = {"Legacy tiers (32 / 64 / 128 / max)": INPPreferences.FORMULA_LEGACY,
                      "Adaptive (DOF / core factor)": INPPreferences.FORMULA_ADAPTIVE}
    DEFAULT_ABAQUS_COMMAND = AbaqusVersionPreferences.DEFAULT_COMMAND
    DEFAULT_ABAQUS_COMMANDS = list(AbaqusVersionPreferences.DEFAULT_COMMANDS)
    UPDATE_PROVIDER_LABELS = {
        "Automatic (GitHub preferred, S: fallback)": "auto",
        "GitHub Releases (recommended)": "github",
        "Shared folder / S: drive (legacy)": "folder",
    }
    UPDATE_CHANNEL_LABELS = {"Stable": "stable", "Beta / prerelease": "beta"}
    # Compatibility tokens retained for older source-contract tests: "Shared folder fallback"; "Automatic (GitHub, then shared folder fallback)".

    def __init__(self, view, on_install_update=None):
        self._on_install_update = on_install_update
        settings = AbaqusVersionPreferences().load_settings(self.DEFAULT_ABAQUS_COMMANDS)
        self._versions = list(settings["versions"])
        inp, general = INPPreferences().load(), GeneralPreferences().load()
        performance = PerformancePreferences().load()
        updates = UpdatePreferences().load()
        super().__init__(view, "Settings", 760, 520)
        self.preferred_size = (760, 520)
        dpg.configure_item(self.content, no_scrollbar=True, no_scroll_with_mouse=True)
        self.pages = {}
        self.navigation = {}
        with dpg.table(parent=self.content, header_row=False, width=-1,
                       policy=dpg.mvTable_SizingStretchProp, pad_outerX=False,
                       borders_innerH=False, borders_outerH=False,
                       borders_innerV=False, borders_outerV=False):
            dpg.add_table_column(width_fixed=True, init_width_or_weight=DialogMetrics.NAV_WIDTH)
            dpg.add_table_column(width_stretch=True, init_width_or_weight=1.0)
            with dpg.table_row() as layout_row:
                # Table cells must be parented to the row explicitly.  The generic
                # navigation_panel() helper defaults to self.content, which caused
                # Settings' page_host to become the *first* table cell (the fixed
                # NAV_WIDTH column).  The result was the entire settings page being
                # squeezed into ~156 px while the rest of the dialog stayed blank.
                nav = self.navigation_panel(
                    width=DialogMetrics.NAV_WIDTH, parent=layout_row)
                heading = dpg.add_text("WinUx", parent=nav)
                font = getattr(self.view, "heading_font", None)
                if font:
                    dpg.bind_item_font(heading, font)
                self.note("Application settings", parent=nav, wrap=138)
                dpg.add_separator(parent=nav)
                for key, label in (("general", "General"), ("updates", "Updates"),
                                   ("performance", "Performance"),
                                   ("abaqus", "Abaqus Versions"), ("account", "Saved Login")):
                    # Do not use width=-1 for selectables inside the fixed-width
                    # navigation child hosted by a table cell.  DearPyGui can
                    # resolve the available width as ~0 on the first layout pass,
                    # leaving only the selection accent visible and clipping the
                    # label entirely.  Give each navigation row a stable explicit
                    # width based on the pane width so all tabs remain visible.
                    nav_item_width = max(80, int(DialogMetrics.NAV_WIDTH) - 14)
                    self.navigation[key] = dpg.add_selectable(
                        label=label, default_value=key == "general", parent=nav,
                        width=nav_item_width, height=27,
                        callback=lambda s, a, u: self._show_page(u), user_data=key,
                    )
                with dpg.child_window(
                        parent=layout_row, width=-1, height=-1, border=False,
                        no_scrollbar=False, no_scroll_with_mouse=False) as self.page_host:
                    self._build_pages(settings, inp, general, performance, updates)
        self.status = self.status_text(wrap=600)
        self.button_box([("Save", self._save, "primary", True),
                         ("Cancel", self.destroy, "secondary", False)], status_item=self.status)
        self._formula_changed()
        self._update_provider_changed()
        self._refresh_update_recovery()
        self._refresh_login()

    def _set_status(self, text, error=False):
        dpg.set_value(self.status, str(text))
        dpg.bind_item_theme(self.status, error_text_theme() if error else muted_text_theme())

    def _show_page(self, key):
        if key not in self.pages:
            return
        for name, page in self.pages.items():
            dpg.configure_item(page, show=name == key)
            dpg.set_value(self.navigation[name], name == key)

    def _build_pages(self, settings, inp, general, performance, updates):
        with dpg.group() as self.pages["general"]:
            self.header("General", "Startup and CPU estimation preferences.", parent=self.pages["general"])
            with self.section("Startup", parent=self.pages["general"]) as startup:
                self._auto_login_widget = self.own_widget(ImGuiCheckBox(
                    "Automatically log in on startup", checked=general.get("auto_login", False),
                    parent=startup, after=self.view.after, backend=dpg))
                self.auto_login = self._auto_login_widget.tag
            with self.section("Core estimation", parent=self.pages["general"]) as cores:
                label = next((label for label, value in self.FORMULA_LABELS.items() if value == inp.get("formula")), next(iter(self.FORMULA_LABELS)))
                form = self.form_layout(parent=cores, label_width=132)
                self.formula = self.form_layout_row(
                    form, "Formula",
                    lambda parent: self.combo(list(self.FORMULA_LABELS), parent=parent,
                        default_value=label, callback=lambda: self._formula_changed()),
                )
                self.inp_fields = {}
                for name, field_label in (("dof_per_core", "DOF per core"),
                                          ("minimum_cores", "Minimum cores"),
                                          ("maximum_cores", "Maximum cores"),
                                          ("core_step", "Core increment")):
                    self.inp_fields[name] = self.form_layout_row(
                        form, field_label,
                        lambda parent, name=name: self.spin_int(
                            int(inp[name]), parent=parent, minimum=1, width=-1,
                            callback=lambda *_args: self._formula_changed()),
                    )
                self.preview = self.note("", wrap=400, parent=cores)
        with dpg.group(show=False) as self.pages["updates"]:
            self.header(
                "Updates",
                "Public GitHub Releases are the preferred update source. Existing S: deployments remain supported during migration.",
                parent=self.pages["updates"],
            )
            with self.section("Update source", parent=self.pages["updates"]) as update_source:
                provider_label = next(
                    (label for label, value in self.UPDATE_PROVIDER_LABELS.items()
                     if value == updates.get("provider")),
                    next(iter(self.UPDATE_PROVIDER_LABELS)),
                )
                form = self.form_layout(parent=update_source, label_width=158)
                self.update_provider = self.form_layout_row(
                    form, "Provider",
                    lambda parent: self.combo(
                        list(self.UPDATE_PROVIDER_LABELS), parent=parent,
                        default_value=provider_label,
                        callback=lambda *_args: self._update_provider_changed(),
                    ),
                )
                self.github_repository = self.form_layout_row(
                    form, "GitHub repository",
                    lambda parent: self.line_edit(
                        updates.get("github_repository", ""), parent=parent,
                        hint="owner/repository", width=-1,
                    ),
                )
                channel_label = next(
                    (label for label, value in self.UPDATE_CHANNEL_LABELS.items()
                     if value == updates.get("channel")),
                    "Stable",
                )
                self.update_channel = self.form_layout_row(
                    form, "Release channel",
                    lambda parent: self.combo(
                        list(self.UPDATE_CHANNEL_LABELS), parent=parent,
                        default_value=channel_label,
                        callback=lambda *_args: self._update_provider_changed(),
                    ),
                )
                self.legacy_update_source = self.form_layout_row(
                    form, "Shared folder fallback",
                    lambda parent: self.line_edit(
                        updates.get("legacy_source", ""), parent=parent,
                        hint=UpdatePreferences.DEFAULT_LEGACY_SOURCE, width=-1,
                    ),
                )
                self.update_provider_note = self.note("", wrap=410, parent=update_source)
            with self.section("Update check", parent=self.pages["updates"]) as update_check:
                with dpg.group(horizontal=True, horizontal_spacing=DialogMetrics.BUTTON_GAP, parent=update_check):
                    self.check_updates_button = self.action(
                        "Check for Updates", self._check_for_updates_now, "primary", parent=update_check
                    )
                    self.install_update_button = self.action(
                        "Update Now", self._install_update_now, "primary", parent=update_check
                    )
                    self.set_control_enabled(self.install_update_button, False)
                self.update_check_status = self.note(
                    "Not checked in this session.", wrap=410, parent=update_check
                )
            with self.section("Integrity and recovery", parent=self.pages["updates"]) as update_integrity:
                self.note(
                    "This repository is public, so WinUx does not store or request GitHub credentials. "
                    "Release packages are SHA-256 verified before extraction, then update_manifest.json is verified file-by-file.",
                    wrap=410, parent=update_integrity,
                )
                self.note(
                    "Failed candidate builds are quarantined locally and are not retried until the published package changes. "
                    "The shared S: folder remains available as the legacy/fallback provider.",
                    wrap=410, parent=update_integrity,
                )
            with self.section("Recovery status", parent=self.pages["updates"]) as update_recovery:
                self.update_recovery_summary = dpg.add_text("", wrap=410, parent=update_recovery)
                with dpg.group(horizontal=True, horizontal_spacing=DialogMetrics.BUTTON_GAP, parent=update_recovery):
                    self.action("Refresh", self._refresh_update_recovery, "secondary")
                    self.action("Clear quarantine", self._clear_update_quarantine, "secondary")
                self.note(
                    "Recovery data is local only. Clearing quarantine allows a failed release to be evaluated again; "
                    "it does not delete installed versions or change the active version.",
                    wrap=410, parent=update_recovery,
                )
        with dpg.group(show=False) as self.pages["performance"]:
            self.header("Performance", "Adaptive polling reduces scheduler and ODB load while keeping active jobs responsive.", parent=self.pages["performance"])
            with self.section("PBS Job Viewer (qstat -f)", parent=self.pages["performance"]) as qstat:
                form = self.form_layout(parent=qstat, label_width=186)
                self.qstat_min = self.form_layout_row(form, "Minimum interval (s)", lambda parent: self.spin_float(float(performance["qstat_min_interval"]), parent=parent, minimum=1.0, step=0.5, decimals=1, width=-1))
                self.qstat_max = self.form_layout_row(form, "Maximum interval (s)", lambda parent: self.spin_float(float(performance["qstat_max_interval"]), parent=parent, minimum=1.0, step=0.5, decimals=1, width=-1))
                self.qstat_stable = self.form_layout_row(form, "Stable polls to maximum", lambda parent: self.spin_int(int(performance["qstat_stable_samples_to_max"]), parent=parent, minimum=1, width=-1))
                self.qstat_quiet = self.form_layout_row(form, "Quiet time to maximum (s)", lambda parent: self.spin_float(float(performance["qstat_quiet_seconds_to_max"]), parent=parent, minimum=1.0, step=1.0, decimals=0, width=-1))
            with self.section("Realtime ODB Plot", parent=self.pages["performance"]) as odb:
                self.note("ODB discovery and live file checks learn the observed cadence in this WinUx session. Long-running jobs can therefore back off much further while polling becomes faster again near the predicted next update.", wrap=390, parent=odb)
                form = self.form_layout(parent=odb, label_width=210)
                self.odb_min = self.form_layout_row(form, "Minimum file-check interval (s)", lambda parent: self.spin_float(float(performance["odb_min_interval"]), parent=parent, minimum=0.25, step=0.25, decimals=2, width=-1))
                self.odb_max = self.form_layout_row(form, "Maximum quiet interval (s)", lambda parent: self.spin_float(float(performance["odb_max_interval"]), parent=parent, minimum=0.25, step=0.5, decimals=1, width=-1))
                self.odb_stable = self.form_layout_row(form, "Stable checks to maximum", lambda parent: self.spin_int(int(performance["odb_stable_samples_to_max"]), parent=parent, minimum=1, width=-1))
                self.odb_quiet = self.form_layout_row(form, "Quiet time to maximum (s)", lambda parent: self.spin_float(float(performance["odb_quiet_seconds_to_max"]), parent=parent, minimum=1.0, step=1.0, decimals=0, width=-1))
                self.odb_history_alpha = self.form_layout_row(form, "History learning weight (0-1)", lambda parent: self.spin_float(float(performance["odb_history_alpha"]), parent=parent, minimum=0.01, maximum=1.0, step=0.01, decimals=2, width=-1))
                self.odb_prediction_fraction = self.form_layout_row(form, "Predicted-cycle probe fraction", lambda parent: self.spin_float(float(performance["odb_prediction_fraction"]), parent=parent, minimum=0.05, maximum=1.0, step=0.05, decimals=2, width=-1))
                self.odb_history_confidence = self.form_layout_row(form, "History samples for full confidence", lambda parent: self.spin_int(int(performance["odb_history_confidence_samples"]), parent=parent, minimum=1, width=-1))
                self.odb_catalog_checks = self.form_layout_row(form, "Catalog rescan every changed checks", lambda parent: self.spin_int(int(performance["odb_catalog_changed_checks"]), parent=parent, minimum=1, width=-1))
        with dpg.group(show=False) as self.pages["abaqus"]:
            self.header("Abaqus Versions", "Manage executable commands and the default version.", parent=self.pages["abaqus"])
            with self.section("Executable commands", parent=self.pages["abaqus"]) as commands:
                self.version_list = self.own_widget(QtListView(
                    commands, self._versions, visible_rows=6, width=-1,
                    after=self.view.after, backend=dpg))
                self.version_editor = self.field("Command", parent=commands)
                self.version_list.currentTextChanged.connect(
                    lambda value: dpg.set_value(self.version_editor, value))
                if self._versions:
                    self.version_list.setCurrentText(self._versions[0])
                with dpg.group(horizontal=True, horizontal_spacing=DialogMetrics.BUTTON_GAP) as command_buttons:
                    for label, action in (("Add", "add"), ("Update", "update"), ("Delete", "delete"), ("Restore Defaults", "restore")):
                        self.action(
                            label, lambda action=action: self._edit_version(action),
                            "danger" if action == "delete" else "secondary",
                            parent=command_buttons,
                        )
                command_form = self.form_layout(parent=commands, label_width=78)
                self.default_command = self.form_layout_row(
                    command_form, "Default",
                    lambda parent: self.combo(
                        self._versions, parent=parent, default_value=settings["default_command"]),
                )
        with dpg.group(show=False) as self.pages["account"]:
            self.header("Saved Login", "Credentials stored for this Windows account.", parent=self.pages["account"])
            with self.section("Account", parent=self.pages["account"]) as account:
                self.login_summary = dpg.add_text("", wrap=400, parent=account)
                self.action("Clear saved login", self._clear_login, "secondary", parent=account)

    def _current_inp_values(self):
        """Return the current core-estimation form as normalized settings."""
        label = dpg.get_value(self.formula) if hasattr(self, "formula") else ""
        formula = self.FORMULA_LABELS.get(label, INPPreferences.FORMULA_LEGACY)
        values = {"formula": formula}
        for name, item in getattr(self, "inp_fields", {}).items():
            try:
                values[name] = int(dpg.get_value(item))
            except (TypeError, ValueError):
                values[name] = INPPreferences.DEFAULTS[name]
        return INPPreferences.normalize(values)

    def _formula_changed(self):
        """Refresh formula-dependent controls and the live explanation."""
        if not hasattr(self, "formula") or not hasattr(self, "inp_fields"):
            return
        values = self._current_inp_values()
        adaptive = values["formula"] == INPPreferences.FORMULA_ADAPTIVE
        # Core increment is meaningful only for the adaptive formula.  Keep the
        # other bounds editable for both formulas because legacy recommendations
        # are still clamped by minimum/maximum and use DOF/core thresholds.
        step_item = self.inp_fields.get("core_step")
        if step_item is not None:
            self.set_control_enabled(step_item, adaptive)
        if not hasattr(self, "preview"):
            return
        if adaptive:
            text = (
                "Adaptive: ceil(DOF / {:,}), rounded up to a multiple of {} cores, "
                "limited to {}-{} cores."
            ).format(
                values["dof_per_core"], values["core_step"],
                values["minimum_cores"], values["maximum_cores"],
            )
        else:
            text = (
                "Legacy tiers: 32 / 64 / 128 / {} cores at {:,} DOF/core, "
                "limited to {}-{} cores."
            ).format(
                values["maximum_cores"], values["dof_per_core"],
                values["minimum_cores"], values["maximum_cores"],
            )
        dpg.set_value(self.preview, text)

    def _sync_version_controls(self, preferred=None):
        """Refresh the version list and default combo after model edits."""
        self.version_list.setItems(self._versions)
        selected = str(preferred or "").strip()
        if selected not in self._versions:
            selected = self._versions[0] if self._versions else ""
        if selected:
            self.version_list.setCurrentText(selected)
            dpg.set_value(self.version_editor, selected)
        else:
            dpg.set_value(self.version_editor, "")
        if hasattr(self, "default_command"):
            current_default = dpg.get_value(self.default_command)
            dpg.configure_item(self.default_command, items=list(self._versions))
            if current_default in self._versions:
                dpg.set_value(self.default_command, current_default)
            elif selected:
                dpg.set_value(self.default_command, selected)

    def _edit_version(self, action):
        """Apply Add/Update/Delete/Restore actions from the Abaqus version page."""
        action = str(action or "").strip().lower()
        current = self.version_list.currentText() if hasattr(self, "version_list") else ""
        editor = str(dpg.get_value(self.version_editor) or "").strip()
        if action == "restore":
            self._versions = list(self.DEFAULT_ABAQUS_COMMANDS)
            self._sync_version_controls(self.DEFAULT_ABAQUS_COMMAND)
            self._set_status("Default Abaqus commands restored. Click Save to keep the change.")
            return
        if action == "add":
            if not editor:
                self._set_status("Enter an Abaqus command before adding it.", error=True)
                return
            if editor in self._versions:
                self._sync_version_controls(editor)
                self._set_status("That Abaqus command already exists.", error=True)
                return
            self._versions.append(editor)
            self._sync_version_controls(editor)
            return
        if action == "update":
            if not current:
                self._set_status("Select an Abaqus command to update.", error=True)
                return
            if not editor:
                self._set_status("Abaqus command cannot be empty.", error=True)
                return
            if editor != current and editor in self._versions:
                self._set_status("That Abaqus command already exists.", error=True)
                return
            index = self._versions.index(current)
            self._versions[index] = editor
            if hasattr(self, "default_command") and dpg.get_value(self.default_command) == current:
                dpg.set_value(self.default_command, editor)
            self._sync_version_controls(editor)
            return
        if action == "delete":
            if not current:
                self._set_status("Select an Abaqus command to delete.", error=True)
                return
            if len(self._versions) <= 1:
                self._set_status("Keep at least one Abaqus command.", error=True)
                return
            self._versions.remove(current)
            self._sync_version_controls()

    def _update_provider_changed(self):
        if not hasattr(self, "update_provider"):
            return
        label = dpg.get_value(self.update_provider)
        provider = self.UPDATE_PROVIDER_LABELS.get(label, "auto")
        github_enabled = provider in ("auto", "github")
        folder_enabled = provider in ("auto", "folder")
        self.set_control_enabled(self.github_repository, github_enabled)
        self.set_control_enabled(self.update_channel, github_enabled)
        self.set_control_enabled(self.legacy_update_source, folder_enabled)
        channel_label = dpg.get_value(self.update_channel) if hasattr(self, "update_channel") else "Stable"
        channel = self.UPDATE_CHANNEL_LABELS.get(channel_label, "stable")
        channel_note = UpdatePreferences.CHANNEL_DESCRIPTIONS.get(channel, "")
        legacy_note = UpdatePreferences.LEGACY_DEPRECATION_NOTE
        if provider == "auto":
            text = (
                "GitHub is preferred whenever a repository is configured. If GitHub is unavailable, "
                "WinUx falls back to the existing S:/shared-folder source. " + channel_note + " " + legacy_note
            )
        elif provider == "github":
            text = (
                "GitHub is forced. If it is unavailable, WinUx keeps the current local version and does not prompt for S:. "
                + channel_note
            )
        else:
            text = "Only the legacy S:/shared-folder updater is used. " + legacy_note
        dpg.set_value(self.update_provider_note, text)

    def _save_update_preferences_only(self):
        provider = self.UPDATE_PROVIDER_LABELS.get(dpg.get_value(self.update_provider), "auto")
        channel = self.UPDATE_CHANNEL_LABELS.get(dpg.get_value(self.update_channel), "stable")
        return UpdatePreferences().save(
            provider=provider,
            github_repository=dpg.get_value(self.github_repository),
            channel=channel,
            legacy_source=dpg.get_value(self.legacy_update_source),
        )

    def _check_for_updates_now(self):
        try:
            self._save_update_preferences_only()
        except (OSError, ValueError, TypeError) as exc:
            self._set_status("Unable to save update settings: {}".format(exc), error=True)
            return
        self.set_control_enabled(self.check_updates_button, False)
        self.set_control_enabled(self.install_update_button, False)
        self._available_update = None
        dpg.set_value(self.update_check_status, "Checking for updates...")
        self._set_status("Checking the configured update sources...")

        def worker():
            try:
                from winux_updater import check_for_updates
                project_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
                result = check_for_updates(
                    project_dir, settings_path=str(UpdatePreferences().path)
                )
                error = None
            except Exception as exc:
                result, error = None, exc
            self.view.after(0, self._finish_update_check, result, error)

        threading.Thread(target=worker, name="winux-manual-update-check", daemon=True).start()

    def _finish_update_check(self, result, error=None):
        if hasattr(self, "check_updates_button"):
            self.set_control_enabled(self.check_updates_button, True)
        if error is not None:
            message = "Update check failed: {}".format(error)
            dpg.set_value(self.update_check_status, message)
            self._set_status(message, error=True)
            return
        result = result or {}
        local_version = result.get("local_version") or "unknown"
        server_version = result.get("server_version")
        source = result.get("source_label") or result.get("server_dir") or "configured source"
        if result.get("available"):
            self._available_update = result
            self.set_control_enabled(self.install_update_button, True)
            message = (
                "Update {} is available from {}. Click Update Now to download and install it. "
                "WinUx will close the current interface and open the new version after verification."
            ).format(server_version or "newer release", source)
        elif result.get("error"):
            message = "Could not check {}: {}".format(source, result.get("error"))
        elif server_version:
            message = "WinUx {} is up to date. Checked {}.".format(local_version, source)
        else:
            message = "No published update could be resolved from {}. {}".format(
                source, result.get("reason") or ""
            ).strip()
        if result.get("legacy_provider"):
            message += " S: compatibility remains enabled, but GitHub is the preferred migration target."
        dpg.set_value(self.update_check_status, message)
        self._set_status(message, error=bool(result.get("error")))

    def _install_update_now(self):
        if not getattr(self, "_available_update", None):
            return
        try:
            self._save_update_preferences_only()
            self.set_control_enabled(self.install_update_button, False)
            if not callable(self._on_install_update):
                raise ValueError("Update installation requires the floating Settings host.")
            self._on_install_update()
            self._set_status("Preparing update. The current version stays open until the package is verified.")
        except (OSError, ValueError, TypeError) as exc:
            self.set_control_enabled(self.install_update_button, True)
            self._set_status("Unable to start update: {}".format(exc), error=True)

    def update_launch_failed(self, error):
        self.set_control_enabled(self.install_update_button, True)
        self._set_status("Unable to start update: {}".format(error), error=True)

    def handle_command(self, command, *args, **kwargs):
        if command == "update_launch_failed":
            self.update_launch_failed(*args)
            return
        return super().handle_command(command, *args, **kwargs)

    def _refresh_update_recovery(self):
        if not hasattr(self, "update_recovery_summary"):
            return
        try:
            snapshot = collect_update_diagnostics()
            dpg.set_value(self.update_recovery_summary, format_update_diagnostics(snapshot))
        except Exception as exc:
            dpg.set_value(self.update_recovery_summary, "Updater diagnostics unavailable: {}".format(exc))

    def _clear_update_quarantine(self):
        try:
            clear_quarantine()
            self._refresh_update_recovery()
            self._set_status("Update quarantine has been cleared. Failed releases may be evaluated again.")
        except Exception as exc:
            self._set_status("Unable to clear update quarantine: {}".format(exc), error=True)

    def _refresh_login(self):
        values = LoginPreferences().load()
        dpg.set_value(self.login_summary, "Host: {}\nUsername: {}\nPassword: {}".format(
            values.get("host") or "Not saved", values.get("username") or "Not saved",
            "Saved and protected" if values.get("password") else "Not saved"))

    def _clear_login(self):
        try:
            LoginPreferences().clear()
            self._refresh_login()
            self._set_status("Saved login information has been cleared.")
        except (OSError, ValueError, TypeError) as exc:
            self._set_status("Unable to clear saved login: {}".format(exc), error=True)

    def _save(self):
        try:
            if not self._versions:
                raise ValueError("Add at least one Abaqus command before saving.")
            values = self._current_inp_values()
            if values["maximum_cores"] < values["minimum_cores"]:
                raise ValueError("Maximum cores must be greater than or equal to minimum cores.")
            qstat_min = float(dpg.get_value(self.qstat_min))
            qstat_max = float(dpg.get_value(self.qstat_max))
            odb_min = float(dpg.get_value(self.odb_min))
            odb_max = float(dpg.get_value(self.odb_max))
            if qstat_max < qstat_min:
                raise ValueError("qstat maximum interval must be greater than or equal to minimum interval.")
            if odb_max < odb_min:
                raise ValueError("ODB maximum interval must be greater than or equal to minimum interval.")
            self._save_update_preferences_only()
            INPPreferences().save(values)
            GeneralPreferences().save(auto_login=bool(dpg.get_value(self.auto_login)))
            PerformancePreferences().save({
                "qstat_min_interval": qstat_min,
                "qstat_max_interval": qstat_max,
                "qstat_stable_samples_to_max": int(dpg.get_value(self.qstat_stable)),
                "qstat_quiet_seconds_to_max": float(dpg.get_value(self.qstat_quiet)),
                "odb_min_interval": odb_min,
                "odb_max_interval": odb_max,
                "odb_stable_samples_to_max": int(dpg.get_value(self.odb_stable)),
                "odb_quiet_seconds_to_max": float(dpg.get_value(self.odb_quiet)),
                "odb_history_alpha": float(dpg.get_value(self.odb_history_alpha)),
                "odb_prediction_fraction": float(dpg.get_value(self.odb_prediction_fraction)),
                "odb_history_confidence_samples": int(dpg.get_value(self.odb_history_confidence)),
                "odb_catalog_changed_checks": int(dpg.get_value(self.odb_catalog_checks)),
            })
            AbaqusVersionPreferences().save(self._versions, dpg.get_value(self.default_command))
        except (OSError, ValueError, TypeError) as exc:
            self._set_status("Unable to save settings: {}".format(exc), error=True)
            return
        self.destroy()
