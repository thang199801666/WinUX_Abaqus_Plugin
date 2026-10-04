from __future__ import annotations

import dearpygui.dearpygui as dpg
from ..abaqus_version_preferences import AbaqusVersionPreferences
from ..general_preferences import GeneralPreferences
from ..inp_preferences import INPPreferences
from ..login_preferences import LoginPreferences
from ..performance_preferences import PerformancePreferences
from .qt_dialog import QtDialog
from .theme import DialogMetrics, muted_text_theme, error_text_theme
from ..widgets import ImGuiCheckBox, QtListView


class SettingsDialog(QtDialog):
    FORMULA_LABELS = {"Legacy tiers (32 / 64 / 128 / max)": INPPreferences.FORMULA_LEGACY,
                      "Adaptive (DOF / core factor)": INPPreferences.FORMULA_ADAPTIVE}
    DEFAULT_ABAQUS_COMMAND = AbaqusVersionPreferences.DEFAULT_COMMAND
    DEFAULT_ABAQUS_COMMANDS = list(AbaqusVersionPreferences.DEFAULT_COMMANDS)

    def __init__(self, view):
        settings = AbaqusVersionPreferences().load_settings(self.DEFAULT_ABAQUS_COMMANDS)
        self._versions = list(settings["versions"])
        inp, general = INPPreferences().load(), GeneralPreferences().load()
        performance = PerformancePreferences().load()
        super().__init__(view, "Settings", 700, 440)
        self.preferred_size = (700, 440)
        dpg.configure_item(self.content, no_scrollbar=True, no_scroll_with_mouse=True)
        self.pages = {}
        self.navigation = {}
        with dpg.table(parent=self.content, header_row=False, width=-1,
                       policy=dpg.mvTable_SizingStretchProp, pad_outerX=False,
                       borders_innerH=False, borders_outerH=False,
                       borders_innerV=False, borders_outerV=False):
            dpg.add_table_column(width_fixed=True, init_width_or_weight=DialogMetrics.NAV_WIDTH)
            dpg.add_table_column(width_stretch=True, init_width_or_weight=1.0)
            with dpg.table_row():
                nav = self.navigation_panel(width=DialogMetrics.NAV_WIDTH)
                heading = dpg.add_text("WinUx", parent=nav)
                font = getattr(self.view, "heading_font", None)
                if font:
                    dpg.bind_item_font(heading, font)
                self.note("Application settings", parent=nav, wrap=138)
                dpg.add_separator(parent=nav)
                for key, label in (("general", "General"), ("performance", "Performance"),
                                   ("abaqus", "Abaqus Versions"), ("account", "Saved Login")):
                    self.navigation[key] = dpg.add_selectable(
                        label=label, default_value=key == "general", parent=nav,
                        callback=lambda s, a, u: self._show_page(u), user_data=key,
                    )
                with dpg.child_window(width=-1, height=-1, border=False,
                                      no_scrollbar=False, no_scroll_with_mouse=False) as self.page_host:
                    self._build_pages(settings, inp, general, performance)
        self.status = self.status_text(wrap=600)
        self.button_box([("Save", self._save, "primary", True),
                         ("Cancel", self.destroy, "secondary", False)], status_item=self.status)
        self._formula_changed()
        self._refresh_login()

    def _set_status(self, text, error=False):
        dpg.set_value(self.status, str(text))
        dpg.bind_item_theme(self.status, error_text_theme() if error else muted_text_theme())

    def _show_page(self, key):
        for name, page in self.pages.items():
            dpg.configure_item(page, show=name == key)
            dpg.set_value(self.navigation[name], name == key)

    def _build_pages(self, settings, inp, general, performance):
        with dpg.group() as self.pages["general"]:
            self.header("General", "Startup and CPU estimation preferences.", parent=self.pages["general"])
            with self.section("Startup", parent=self.pages["general"]) as startup:
                self._auto_login_widget = self.own_widget(ImGuiCheckBox(
                    "Automatically log in on startup", checked=general.get("auto_login", False),
                    parent=startup, after=self.view.after, backend=dpg))
                self.auto_login = self._auto_login_widget.tag
            with self.section("Core estimation", parent=self.pages["general"]) as cores:
                label = next((label for label, value in self.FORMULA_LABELS.items() if value == inp.get("formula")), next(iter(self.FORMULA_LABELS)))
                self.formula = self.labeled_widget("Formula", lambda: self.combo(list(self.FORMULA_LABELS), default_value=label,
                    callback=lambda: self._formula_changed()), parent=cores)
                self.inp_fields = {name: self.labeled_widget(label, lambda name=name: self.spin_int(int(inp[name]), minimum=1, width=-1,
                    callback=lambda *_args: self._formula_changed()), parent=cores) for name, label in (
                    ("dof_per_core", "DOF per core"), ("minimum_cores", "Minimum cores"),
                    ("maximum_cores", "Maximum cores"), ("core_step", "Core increment"))}
                self.preview = self.note("", wrap=400, parent=cores)
        with dpg.group(show=False) as self.pages["performance"]:
            self.header("Performance", "Adaptive polling reduces scheduler and ODB load while keeping active jobs responsive.", parent=self.pages["performance"])
            with self.section("PBS Job Viewer (qstat -f)", parent=self.pages["performance"]) as qstat:
                self.qstat_min = self.labeled_widget("Minimum interval (s)", lambda: self.spin_float(float(performance["qstat_min_interval"]), minimum=1.0, step=0.5, decimals=1, width=-1), parent=qstat)
                self.qstat_max = self.labeled_widget("Maximum interval (s)", lambda: self.spin_float(float(performance["qstat_max_interval"]), minimum=1.0, step=0.5, decimals=1, width=-1), parent=qstat)
                self.qstat_stable = self.labeled_widget("Stable polls to maximum", lambda: self.spin_int(int(performance["qstat_stable_samples_to_max"]), minimum=1, width=-1), parent=qstat)
                self.qstat_quiet = self.labeled_widget("Quiet time to maximum (s)", lambda: self.spin_float(float(performance["qstat_quiet_seconds_to_max"]), minimum=1.0, step=1.0, decimals=0, width=-1), parent=qstat)
            with self.section("Realtime ODB Plot", parent=self.pages["performance"]) as odb:
                self.note("ODB discovery and live file checks learn the observed cadence in this WinUx session. Long-running jobs can therefore back off much further while polling becomes faster again near the predicted next update.", wrap=390, parent=odb)
                self.odb_min = self.labeled_widget("Minimum file-check interval (s)", lambda: self.spin_float(float(performance["odb_min_interval"]), minimum=0.25, step=0.25, decimals=2, width=-1), parent=odb)
                self.odb_max = self.labeled_widget("Maximum quiet interval (s)", lambda: self.spin_float(float(performance["odb_max_interval"]), minimum=0.25, step=0.5, decimals=1, width=-1), parent=odb)
                self.odb_stable = self.labeled_widget("Stable checks to maximum", lambda: self.spin_int(int(performance["odb_stable_samples_to_max"]), minimum=1, width=-1), parent=odb)
                self.odb_quiet = self.labeled_widget("Quiet time to maximum (s)", lambda: self.spin_float(float(performance["odb_quiet_seconds_to_max"]), minimum=1.0, step=1.0, decimals=0, width=-1), parent=odb)
                self.odb_history_alpha = self.labeled_widget("History learning weight (0-1)", lambda: self.spin_float(float(performance["odb_history_alpha"]), minimum=0.01, maximum=1.0, step=0.01, decimals=2, width=-1), parent=odb)
                self.odb_prediction_fraction = self.labeled_widget("Predicted-cycle probe fraction", lambda: self.spin_float(float(performance["odb_prediction_fraction"]), minimum=0.05, maximum=1.0, step=0.05, decimals=2, width=-1), parent=odb)
                self.odb_history_confidence = self.labeled_widget("History samples for full confidence", lambda: self.spin_int(int(performance["odb_history_confidence_samples"]), minimum=1, width=-1), parent=odb)
                self.odb_catalog_checks = self.labeled_widget("Catalog rescan every changed checks", lambda: self.spin_int(int(performance["odb_catalog_changed_checks"]), minimum=1, width=-1), parent=odb)
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
                self.default_command = self.labeled_widget("Default", lambda: self.combo(self._versions,
                    default_value=settings["default_command"]), parent=commands)
        with dpg.group(show=False) as self.pages["account"]:
            self.header("Saved Login", "Credentials stored for this Windows account.", parent=self.pages["account"])
            with self.section("Account", parent=self.pages["account"]) as account:
                self.login_summary = dpg.add_text("", wrap=400, parent=account)
                self.action("Clear saved login", self._clear_login, "secondary", parent=account)

    def _current_inp_values(self):
        values = {name: dpg.get_value(item) for name, item in self.inp_fields.items()}
        values["formula"] = self.FORMULA_LABELS[dpg.get_value(self.formula)]
        return values

    def _formula_changed(self):
        adaptive = self.FORMULA_LABELS[dpg.get_value(self.formula)] == INPPreferences.FORMULA_ADAPTIVE
        self.set_control_enabled(self.inp_fields["core_step"], adaptive)
        values = self._current_inp_values()
        dpg.set_value(self.preview, ("ceil(DOF / {dof_per_core}), rounded up in steps of {core_step}; {minimum_cores}-{maximum_cores} cores."
            if adaptive else "Legacy tiers: 32 / 64 / 128 / {maximum_cores}; {dof_per_core} DOF/core, limited to {minimum_cores}-{maximum_cores}.").format(**values))

    def _edit_version(self, action):
        selected = self.version_list.currentText()
        value = dpg.get_value(self.version_editor).strip()
        default = dpg.get_value(self.default_command)
        if action == "restore":
            self._versions = list(self.DEFAULT_ABAQUS_COMMANDS)
            default = self.DEFAULT_ABAQUS_COMMAND
        elif action == "delete" and selected in self._versions:
            self._versions.remove(selected)
        elif action in ("add", "update"):
            if not value or (value in self._versions and value != selected):
                self._set_status("Enter a unique, non-empty command.", error=True)
                return
            if action == "update" and selected in self._versions:
                self._versions[self._versions.index(selected)] = value
                if default == selected:
                    default = value
            elif value not in self._versions:
                self._versions.append(value)
        self.version_list.setItems(self._versions)
        dpg.configure_item(self.default_command, items=self._versions)
        if default not in self._versions:
            default = self._versions[0] if self._versions else ""
        dpg.set_value(self.default_command, default)
        self._set_status("Click Save to persist changes.")

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
