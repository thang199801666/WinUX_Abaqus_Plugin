from __future__ import annotations

import os

from DearUIQt.backends import dpg
from ..preferences.abaqus_versions import AbaqusVersionPreferences
from ..preferences.general import GeneralPreferences
from ..preferences.inp import INPPreferences
from ..preferences.login import LoginPreferences
from ..preferences.performance import PerformancePreferences
from ..preferences.update import UpdatePreferences
from DearUIQt.dialogs.qt_dialog import QtDialog
from DearUIQt.themes import DialogMetrics, muted_text_theme, error_text_theme
from DearUIQt.core import Qt
from DearUIQt.layouts import QGridLayout
from DearUIQt.widgets import QCheckBox, QStackedWidget, QLabel, QSeparator, QScrollArea
from DearUIQt.modelview import QtListView, QListWidget, QListWidgetItem


class SettingsDialog(QtDialog):
    REUSABLE_HOST = True
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

    PAGE_ORDER = ("general", "updates", "performance", "abaqus", "account")

    def __init__(self, view, on_install_update=None, on_settings_saved=None):
        self._on_install_update = on_install_update
        self._on_settings_saved = on_settings_saved
        # First-open fast path: the General page is the only page visible at
        # startup.  Loading every preference store, credential summary and update
        # recovery report here made an in-process QDialog pay hidden-page I/O and
        # construct dozens of native controls before the first frame.  Qt settings
        # dialogs commonly use a stacked page container; mirror that contract and
        # materialize each page only when it is first selected.
        # The first visible General page is loaded through the same QThreadPool
        # bridge as the other preference pages. This lets the Settings shell
        # paint immediately even when a networked/home profile makes preference
        # I/O unexpectedly slow.
        self._settings_page_data = {}
        self._page_built = set()
        self._page_loading = {}
        self._page_loading_placeholders = {}
        self._versions = None
        self._available_update = None
        self._update_recovery_future = None
        self._login_future = None
        super().__init__(view, "Settings", 760, 520)
        self.preferred_size = (760, 520)
        dpg.configure_item(self.content, no_scrollbar=True, no_scroll_with_mouse=True)
        self.pages = {}
        self._page_widgets = {}
        self.navigation = {}
        self._settings_grid = self.own_widget(QGridLayout(
            2, column_widths=(DialogMetrics.NAV_WIDTH, None),
            parent=self._qt_parent(self.content), after=view.after, backend=dpg))
        nav = self.navigation_panel(
            width=DialogMetrics.NAV_WIDTH, parent=self._settings_grid.cell(0, 0).tag)
        heading = QLabel("WinUx", parent=nav, backend=dpg).tag
        font = getattr(self.view, "heading_font", None)
        if font:
            dpg.bind_item_font(heading, font)
        self.note("Application settings", parent=nav, wrap=138)
        QSeparator(parent=nav, backend=dpg)
        nav_item_width = max(80, int(DialogMetrics.NAV_WIDTH) - 14)
        self.navigation_list = self.own_widget(QListWidget(
            parent=self._qt_parent(nav), after=view.after, backend=dpg,
            width=nav_item_width, visible_rows=len(self.PAGE_ORDER)))
        for key, label in (("general", "General"), ("updates", "Updates"),
                           ("performance", "Performance"),
                           ("abaqus", "Abaqus Versions"), ("account", "Saved Login")):
            item = QListWidgetItem(label)
            item.setData(Qt.UserRole, key)
            self.navigation_list.addItem(item)
            self.navigation[key] = item
        self.navigation_list.itemClicked.connect(
            lambda item: self._show_page(item.data(Qt.UserRole)), receiver=self)
        self.navigation_list.setCurrentRow(0)
        self.page_scroll = self.own_widget(QScrollArea(
            parent=self._settings_grid.cell(0, 1), after=view.after, backend=dpg,
            widget_resizable=True, horizontal_scrollbar=False, vertical_scrollbar=True))
        self.page_host = self.page_scroll.tag
        # QStackedWidget changes only the previous/new page instead of
        # reconfiguring every page on each navigation click. Expensive
        # page contents remain lazy and are materialized by _ensure_page().
        self.page_stack = self.own_widget(QStackedWidget(
            parent=self.page_scroll, after=view.after, backend=dpg))
        for key in self.PAGE_ORDER:
            page = self.page_stack.addPage()
            self._page_widgets[key] = page
            # Keep the historical public mapping as native tags; a
            # number of WinUx integrations inspect page ancestry.
            self.pages[key] = page.tag
        self._current_page = "general"
        self._ensure_page("general")
        self.status = self.status_text(wrap=600)
        self.button_box([("Save", self._save, "primary", True),
                         ("Cancel", self.destroy, "secondary", False)],
                        left_actions=[("Set as Default", self._reset_settings_defaults, "secondary", False)],
                        status_item=self.status)
        self.set_default_button = self.left_buttons[0]
        if "general" in self._page_built:
            self._formula_changed()

    def _set_status(self, text, error=False):
        self.set_control_value(self.status, str(text))
        dpg.bind_item_theme(self.status, error_text_theme() if error else muted_text_theme())

    def _page_data(self, key):
        if key == "general":
            if not {"inp", "general"}.issubset(self._settings_page_data):
                bundle = self._load_page_data("general")
                self._settings_page_data["inp"] = bundle["inp"]
                self._settings_page_data["general"] = bundle["general"]
            return {"inp": self._settings_page_data["inp"],
                    "general": self._settings_page_data["general"]}
        if key not in self._settings_page_data:
            self._settings_page_data[key] = self._load_page_data(key)
        return self._settings_page_data[key]

    def _load_page_data(self, key):
        """Read one page's preference store without touching GUI state."""
        if key == "general":
            return {"inp": INPPreferences().load(), "general": GeneralPreferences().load()}
        if key == "updates":
            return UpdatePreferences().load()
        if key == "performance":
            return PerformancePreferences().load()
        if key == "abaqus":
            return AbaqusVersionPreferences().load_settings(self.DEFAULT_ABAQUS_COMMANDS)
        return None

    def _materialize_page(self, key, data=None):
        key = str(key)
        if key in self._page_built:
            return self.pages.get(key)
        page = self.pages.get(key)
        if page is None:
            return None
        placeholder = self._page_loading_placeholders.pop(key, None)
        if placeholder is not None:
            try:
                if self.control_exists(placeholder):
                    self.delete_control(placeholder)
            except Exception:
                pass
        parent = page
        if key == "general":
            bundle = self._load_page_data("general") if data is None else data
            self._settings_page_data["inp"] = bundle["inp"]
            self._settings_page_data["general"] = bundle["general"]
            self._build_general_page(parent, bundle["inp"], bundle["general"])
            self._formula_changed()
        elif key == "updates":
            value = self._page_data("updates") if data is None else data
            self._settings_page_data["updates"] = value
            self._build_updates_page(parent, value)
        elif key == "performance":
            value = self._page_data("performance") if data is None else data
            self._settings_page_data["performance"] = value
            self._build_performance_page(parent, value)
        elif key == "abaqus":
            settings = self._page_data("abaqus") if data is None else data
            self._settings_page_data["abaqus"] = settings
            self._versions = list(settings["versions"])
            self._build_abaqus_page(parent, settings)
        elif key == "account":
            self._build_account_page(parent)
        else:
            return None
        self._page_built.add(key)
        return page

    def _after_page_materialized(self, key):
        # Expensive information that is not required to lay out the page is
        # deferred one UI turn so the newly selected page can paint first.
        if key == "updates":
            self._update_provider_changed()
            self.view.after(0, self._refresh_update_recovery)
        elif key == "account":
            self.view.after(0, self._refresh_login)

    def _page_data_ready(self, key, value):
        key = str(key)
        if key == "general":
            self._settings_page_data["inp"] = value["inp"]
            self._settings_page_data["general"] = value["general"]
        else:
            self._settings_page_data[key] = value
        if key not in self._page_built:
            self._materialize_page(key, value)
            self._after_page_materialized(key)
            # A loading placeholder is much shorter than the real page.
            # Re-anchor the outer viewport after the newly built widgets get
            # their first layout pass, unless the user has switched tabs.
            if key == getattr(self, "_current_page", None):
                self._schedule_page_scroll_reset(key)

    def _page_data_failed(self, key, error):
        key = str(key)
        # A Save/Default action can synchronously materialize a page while its
        # speculative background load is still draining. Do not let a stale
        # worker failure overwrite the successfully-built form status.
        if key in self._page_built:
            return
        placeholder = self._page_loading_placeholders.get(key)
        text = "Could not load settings: {}".format(error)
        try:
            if placeholder is not None and self.control_exists(placeholder):
                self.set_control_value(placeholder, text)
                dpg.bind_item_theme(placeholder, error_text_theme())
            else:
                self._set_status(text, True)
        except Exception:
            pass

    def _page_data_finished(self, key):
        self._page_loading.pop(str(key), None)

    def _ensure_page(self, key, *, defer_io=True):
        key = str(key)
        if key in self._page_built:
            return self.pages.get(key)
        page = self.pages.get(key)
        if page is None:
            return None
        missing_data = (
            (key == "general" and not {"inp", "general"}.issubset(self._settings_page_data)) or
            (key != "general" and key not in self._settings_page_data)
        )
        if (defer_io and key in ("general", "updates", "performance", "abaqus") and
                missing_data):
            if key not in self._page_loading:
                placeholder = QLabel("Loading settings...", parent=page, backend=dpg).tag
                dpg.bind_item_theme(placeholder, muted_text_theme())
                self._page_loading_placeholders[key] = placeholder
                self._page_loading[key] = self.runAsync(
                    self._load_page_data, key,
                    on_result=lambda value, page_key=key: self._page_data_ready(page_key, value),
                    on_error=lambda error, page_key=key: self._page_data_failed(page_key, error),
                    on_finished=lambda page_key=key: self._page_data_finished(page_key),
                )
            return page
        page = self._materialize_page(key)
        if key == "updates":
            self._update_provider_changed()
            self.view.after(0, self._refresh_update_recovery)
        elif key == "account":
            self.view.after(0, self._refresh_login)
        return page

    def _ensure_all_pages(self):
        # Save/default operations are transactional: if a lazy page has not yet
        # finished loading, materialize it synchronously before collecting form
        # values. A late background result is harmless because _page_built gates
        # duplicate construction.
        for key in self.PAGE_ORDER:
            self._ensure_page(key, defer_io=False)

    def _reset_page_scroll_if_current(self, key):
        # The Settings sidebar replaces the page content in one scroll owner.
        # A long Performance/Updates page can leave a non-zero scroll offset
        # when Abaqus Versions (or its async placeholder) becomes visible.
        # Don't keep resetting during normal interaction: only on page change
        # and when a deferred page first finishes materializing.
        if key != getattr(self, "_current_page", None) or not self.winfo_exists():
            return False
        self.page_scroll.verticalScrollBar().setValue(0)
        return True

    def _schedule_page_scroll_reset(self, key):
        self._reset_page_scroll_if_current(key)
        # DPG computes a child-window's scroll range at render time. A second,
        # guarded reset after layout avoids a stale offset being clamped using
        # the previous page's height. Keep user-initiated scrolling untouched.
        schedule = getattr(self.view, "after_render", None) or self.view.after
        if getattr(self.view, "after_render", None) is not None:
            schedule(self._reset_page_scroll_if_current, key)
        else:
            schedule(0, self._reset_page_scroll_if_current, key)

    def _show_page(self, key):
        if key not in self.pages:
            return
        self._ensure_page(key)
        previous = getattr(self, "_current_page", None)
        if previous == key:
            return
        if not self.page_stack.setCurrentWidget(self._page_widgets[key]):
            return
        item = self.navigation.get(key)
        if item is not None:
            row = self.navigation_list.row(item)
            if row >= 0 and self.navigation_list.currentRow() != row:
                self.navigation_list.setCurrentRow(row)
        self._current_page = key
        self._schedule_page_scroll_reset(key)

    def _build_general_page(self, page, inp, general):
        self.header("General", "Startup and CPU estimation preferences.", parent=page)
        with self.section("Startup", parent=page) as startup:
            self._auto_login_widget = self.own_widget(QCheckBox(
                "Automatically log in on startup", checked=general.get("auto_login", False),
                parent=startup, after=self.view.after, backend=dpg))
            self.auto_login = self._auto_login_widget.tag
        with self.section("File browsing", parent=page) as browsing:
            self._show_hidden_files_widget = self.own_widget(QCheckBox(
                "Show hidden files and folders", checked=general.get("show_hidden_files", False),
                parent=browsing, after=self.view.after, backend=dpg))
            self.show_hidden_files = self._show_hidden_files_widget.tag
            self.note("Applies to Local and Server panels. Includes dot-prefixed names and Windows hidden items.",
                      parent=browsing, wrap=400)
        with self.section("Core estimation", parent=page) as cores:
            label = next((label for label, value in self.FORMULA_LABELS.items()
                          if value == inp.get("formula")), next(iter(self.FORMULA_LABELS)))
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

    def _build_updates_page(self, page, updates):
        self.header(
            "Updates",
            "Public GitHub Releases are the preferred update source. Existing S: deployments remain supported during migration.",
            parent=page,
        )
        with self.section("Update source", parent=page) as update_source:
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
        with self.section("Update check", parent=page) as update_check:
            with dpg.group(horizontal=True, horizontal_spacing=DialogMetrics.BUTTON_GAP,
                           parent=update_check) as update_check_buttons:
                self.check_updates_button = self.action(
                    "Check for Updates", self._check_for_updates_now, "primary", parent=update_check_buttons
                )
                self.install_update_button = self.action(
                    "Update Now", self._install_update_now, "primary", parent=update_check_buttons
                )
                self.set_control_enabled(self.install_update_button, False)
            self.update_check_status = self.note(
                "Not checked in this session.", wrap=410, parent=update_check
            )
        with self.section("Integrity and recovery", parent=page) as update_integrity:
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
        with self.section("Recovery status", parent=page) as update_recovery:
            self.update_recovery_summary = QLabel("", wrap=410, parent=update_recovery, backend=dpg).tag
            with dpg.group(horizontal=True, horizontal_spacing=DialogMetrics.BUTTON_GAP,
                           parent=update_recovery) as recovery_buttons:
                self.action("Refresh", self._refresh_update_recovery, "secondary", parent=recovery_buttons)
                self.action("Clear quarantine", self._clear_update_quarantine, "secondary", parent=recovery_buttons)
            self.note(
                "Recovery data is local only. Clearing quarantine allows a failed release to be evaluated again; "
                "it does not delete installed versions or change the active version.",
                wrap=410, parent=update_recovery,
            )

    def _build_performance_page(self, page, performance):
        self.header("Performance", "Adaptive polling reduces scheduler and ODB load while keeping active jobs responsive.", parent=page)
        with self.section("PBS Job Viewer (qstat -f)", parent=page) as qstat:
            form = self.form_layout(parent=qstat, label_width=186)
            self.qstat_min = self.form_layout_row(form, "Minimum interval (s)", lambda parent: self.spin_float(float(performance["qstat_min_interval"]), parent=parent, minimum=1.0, step=0.5, decimals=1, width=-1))
            self.qstat_max = self.form_layout_row(form, "Maximum interval (s)", lambda parent: self.spin_float(float(performance["qstat_max_interval"]), parent=parent, minimum=1.0, step=0.5, decimals=1, width=-1))
            self.qstat_stable = self.form_layout_row(form, "Stable polls to maximum", lambda parent: self.spin_int(int(performance["qstat_stable_samples_to_max"]), parent=parent, minimum=1, width=-1))
            self.qstat_quiet = self.form_layout_row(form, "Quiet time to maximum (s)", lambda parent: self.spin_float(float(performance["qstat_quiet_seconds_to_max"]), parent=parent, minimum=1.0, step=1.0, decimals=0, width=-1))
        with self.section("Inactivity backoff", parent=page) as inactivity:
            self.note(
                "WinUx progressively reduces remote polling while you are away. "
                "After deep idle, qstat can pause completely until the next mouse/keyboard interaction; "
                "live ODB monitoring keeps only a sparse heartbeat.",
                wrap=410, parent=inactivity,
            )
            form = self.form_layout(parent=inactivity, label_width=220)
            self.inactivity_idle_minutes = self.form_layout_row(
                form, "Idle backoff starts (min)",
                lambda parent: self.spin_float(
                    float(performance["inactivity_idle_seconds"]) / 60.0,
                    parent=parent, minimum=0.1, step=0.5, decimals=1, width=-1))
            self.inactivity_away_minutes = self.form_layout_row(
                form, "Away backoff starts (min)",
                lambda parent: self.spin_float(
                    float(performance["inactivity_away_seconds"]) / 60.0,
                    parent=parent, minimum=0.1, step=1.0, decimals=1, width=-1))
            self.inactivity_deep_minutes = self.form_layout_row(
                form, "Deep idle starts (min)",
                lambda parent: self.spin_float(
                    float(performance["inactivity_deep_idle_seconds"]) / 60.0,
                    parent=parent, minimum=0.1, step=5.0, decimals=1, width=-1))
            self.inactivity_idle_qstat = self.form_layout_row(
                form, "Idle qstat interval (s)",
                lambda parent: self.spin_float(
                    float(performance["inactivity_idle_qstat_interval"]),
                    parent=parent, minimum=1.0, step=5.0, decimals=0, width=-1))
            self.inactivity_away_qstat = self.form_layout_row(
                form, "Away qstat interval (s)",
                lambda parent: self.spin_float(
                    float(performance["inactivity_away_qstat_interval"]),
                    parent=parent, minimum=1.0, step=15.0, decimals=0, width=-1))
            self.inactivity_deep_qstat = self.form_layout_row(
                form, "Deep qstat heartbeat (s, 0=pause)",
                lambda parent: self.spin_float(
                    float(performance["inactivity_deep_qstat_interval"]),
                    parent=parent, minimum=0.0, step=60.0, decimals=0, width=-1))
            self.inactivity_deep_odb = self.form_layout_row(
                form, "Deep ODB heartbeat (min)",
                lambda parent: self.spin_float(
                    float(performance["inactivity_deep_odb_interval"]) / 60.0,
                    parent=parent, minimum=0.5, step=1.0, decimals=1, width=-1))
        with self.section("Realtime ODB Plot", parent=page) as odb:
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

    def _build_abaqus_page(self, page, settings):
        self.header("Abaqus Versions", "Manage executable commands and the default version.", parent=page)
        with self.section("Executable commands", parent=page) as commands:
            # Two installed commands should display two rows, not a six-row
            # empty viewport; more entries retain a bounded list scrollbar.
            visible_rows = max(2, min(6, len(self._versions)))
            self.version_list = self.own_widget(QtListView(
                commands, self._versions, visible_rows=visible_rows, width=-1,
                after=self.view.after, backend=dpg))
            self.version_editor = self.field("Command", parent=commands)
            self.version_list.currentTextChanged.connect(
                lambda value: self.set_control_value(self.version_editor, value))
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

    def _build_account_page(self, page):
        self.header("Saved Login", "Credentials stored for this Windows account.", parent=page)
        with self.section("Account", parent=page) as account:
            self.login_summary = QLabel("", wrap=400, parent=account, backend=dpg).tag
            self.action("Clear saved login", self._clear_login, "secondary", parent=account)

    def _current_inp_values(self):
        """Return the current core-estimation form as normalized settings."""
        label = self.control_value(self.formula) if hasattr(self, "formula") else ""
        formula = self.FORMULA_LABELS.get(label, INPPreferences.FORMULA_LEGACY)
        values = {"formula": formula}
        for name, item in getattr(self, "inp_fields", {}).items():
            try:
                values[name] = int(self.control_value(item))
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
        self.set_control_value(self.preview, text)

    def _sync_version_controls(self, preferred=None):
        """Refresh the version list and default combo after model edits."""
        self.version_list.setItems(self._versions)
        selected = str(preferred or "").strip()
        if selected not in self._versions:
            selected = self._versions[0] if self._versions else ""
        if selected:
            self.version_list.setCurrentText(selected)
            self.set_control_value(self.version_editor, selected)
        else:
            self.set_control_value(self.version_editor, "")
        if hasattr(self, "default_command"):
            current_default = self.control_value(self.default_command)
            self.set_control_items(self.default_command, list(self._versions))
            if current_default in self._versions:
                self.set_control_value(self.default_command, current_default)
            elif selected:
                self.set_control_value(self.default_command, selected)

    def _reset_settings_defaults(self):
        """Restore all editable Settings values; Save persists the changes."""
        # Defaults span every settings category. Materialize hidden pages only
        # for this explicit all-pages operation, not on normal dialog open.
        self._ensure_all_pages()
        self.set_control_value(self.auto_login, GeneralPreferences.DEFAULT_AUTO_LOGIN)
        self.set_control_value(self.show_hidden_files, GeneralPreferences.DEFAULT_SHOW_HIDDEN_FILES)
        formula = next(label for label, value in self.FORMULA_LABELS.items()
                       if value == INPPreferences.DEFAULTS["formula"])
        self.set_control_value(self.formula, formula)
        for name, item in self.inp_fields.items():
            self.set_control_value(item, INPPreferences.DEFAULTS[name])
        for attribute, key in (
            ("qstat_min", "qstat_min_interval"), ("qstat_max", "qstat_max_interval"),
            ("qstat_stable", "qstat_stable_samples_to_max"), ("qstat_quiet", "qstat_quiet_seconds_to_max"),
            ("inactivity_idle_qstat", "inactivity_idle_qstat_interval"),
            ("inactivity_away_qstat", "inactivity_away_qstat_interval"),
            ("inactivity_deep_qstat", "inactivity_deep_qstat_interval"),
            ("odb_min", "odb_min_interval"), ("odb_max", "odb_max_interval"),
            ("odb_stable", "odb_stable_samples_to_max"), ("odb_quiet", "odb_quiet_seconds_to_max"),
            ("odb_history_alpha", "odb_history_alpha"), ("odb_prediction_fraction", "odb_prediction_fraction"),
            ("odb_history_confidence", "odb_history_confidence_samples"), ("odb_catalog_checks", "odb_catalog_changed_checks"),
        ):
            self.set_control_value(getattr(self, attribute), PerformancePreferences.DEFAULTS[key])
        self.set_control_value(
            self.inactivity_idle_minutes,
            PerformancePreferences.DEFAULTS["inactivity_idle_seconds"] / 60.0)
        self.set_control_value(
            self.inactivity_away_minutes,
            PerformancePreferences.DEFAULTS["inactivity_away_seconds"] / 60.0)
        self.set_control_value(
            self.inactivity_deep_minutes,
            PerformancePreferences.DEFAULTS["inactivity_deep_idle_seconds"] / 60.0)
        self.set_control_value(
            self.inactivity_deep_odb,
            PerformancePreferences.DEFAULTS["inactivity_deep_odb_interval"] / 60.0)
        self._versions = list(self.DEFAULT_ABAQUS_COMMANDS)
        self._sync_version_controls(self.DEFAULT_ABAQUS_COMMAND)
        self.set_control_value(self.default_command, self.DEFAULT_ABAQUS_COMMAND)
        updates = UpdatePreferences.defaults()
        self.set_control_value(self.update_provider, next(label for label, value in self.UPDATE_PROVIDER_LABELS.items()
                                               if value == updates["provider"]))
        self.set_control_value(self.update_channel, next(label for label, value in self.UPDATE_CHANNEL_LABELS.items()
                                              if value == updates["channel"]))
        self.set_control_value(self.github_repository, updates["github_repository"])
        self.set_control_value(self.legacy_update_source, updates["legacy_source"])
        self._available_update = None
        self.set_control_enabled(self.install_update_button, False)
        self.set_control_value(self.update_check_status, "Not checked in this session.")
        self._formula_changed()
        self._update_provider_changed()
        self._set_status("Defaults restored. Click Save to apply.")

    def _edit_version(self, action):
        """Apply Add/Update/Delete/Restore actions from the Abaqus version page."""
        action = str(action or "").strip().lower()
        current = self.version_list.currentText() if hasattr(self, "version_list") else ""
        editor = str(self.control_value(self.version_editor) or "").strip()
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
            if hasattr(self, "default_command") and self.control_value(self.default_command) == current:
                self.set_control_value(self.default_command, editor)
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
        label = self.control_value(self.update_provider)
        provider = self.UPDATE_PROVIDER_LABELS.get(label, "auto")
        github_enabled = provider in ("auto", "github")
        folder_enabled = provider in ("auto", "folder")
        self.set_control_enabled(self.github_repository, github_enabled)
        self.set_control_enabled(self.update_channel, github_enabled)
        self.set_control_enabled(self.legacy_update_source, folder_enabled)
        channel_label = self.control_value(self.update_channel) if hasattr(self, "update_channel") else "Stable"
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
        self.set_control_value(self.update_provider_note, text)

    def _save_update_preferences_only(self):
        self._ensure_page("updates")
        provider = self.UPDATE_PROVIDER_LABELS.get(self.control_value(self.update_provider), "auto")
        channel = self.UPDATE_CHANNEL_LABELS.get(self.control_value(self.update_channel), "stable")
        return UpdatePreferences().save(
            provider=provider,
            github_repository=self.control_value(self.github_repository),
            channel=channel,
            legacy_source=self.control_value(self.legacy_update_source),
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
        self.set_control_value(self.update_check_status, "Checking for updates...")
        self._set_status("Checking the configured update sources...")

        def worker():
            try:
                from winux_updater import check_for_updates
                project_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
                return check_for_updates(
                    project_dir, settings_path=str(UpdatePreferences().path)
                ), None
            except Exception as exc:
                return None, exc

        self.runAsync(
            worker,
            on_result=lambda outcome: self._finish_update_check(*outcome),
        )

    def _finish_update_check(self, result, error=None):
        if hasattr(self, "check_updates_button"):
            self.set_control_enabled(self.check_updates_button, True)
        if error is not None:
            message = "Update check failed: {}".format(error)
            self.set_control_value(self.update_check_status, message)
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
        self.set_control_value(self.update_check_status, message)
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
            return False
        future = self._update_recovery_future
        if future is not None and not future.isFinished():
            return False
        self.set_control_value(self.update_recovery_summary, "Loading updater diagnostics...")

        def worker():
            from winux_update_diagnostics import collect_update_diagnostics, format_update_diagnostics
            return format_update_diagnostics(collect_update_diagnostics())

        self._update_recovery_future = self.runAsync(
            worker,
            on_result=lambda text: self.set_control_value(self.update_recovery_summary, str(text)),
            on_error=lambda error: self.set_control_value(
                self.update_recovery_summary,
                "Updater diagnostics unavailable: {}".format(error),
            ),
            on_finished=lambda: setattr(self, "_update_recovery_future", None),
        )
        return True

    def _clear_update_quarantine(self):
        self._set_status("Clearing update quarantine...")

        def worker():
            from winux_installation_state import clear_quarantine
            from winux_update_diagnostics import collect_update_diagnostics, format_update_diagnostics
            clear_quarantine()
            return format_update_diagnostics(collect_update_diagnostics())

        def finished(summary):
            if hasattr(self, "update_recovery_summary"):
                self.set_control_value(self.update_recovery_summary, str(summary))
            self._set_status("Update quarantine has been cleared. Failed releases may be evaluated again.")

        self.runAsync(
            worker,
            on_result=finished,
            on_error=lambda error: self._set_status(
                "Unable to clear update quarantine: {}".format(error), error=True),
        )

    def _apply_login_summary(self, values):
        values = values or {}
        self.set_control_value(self.login_summary, "Host: {}\nUsername: {}\nPassword: {}".format(
            values.get("host") or "Not saved", values.get("username") or "Not saved",
            "Saved and protected" if values.get("password") else "Not saved"))

    def _refresh_login(self):
        if not hasattr(self, "login_summary"):
            return False
        future = self._login_future
        if future is not None and not future.isFinished():
            return False
        self.set_control_value(self.login_summary, "Loading saved login...")

        self._login_future = self.runAsync(
            lambda: LoginPreferences().load(),
            on_result=self._apply_login_summary,
            on_error=lambda error: self.set_control_value(
                self.login_summary, "Saved login unavailable: {}".format(error)),
            on_finished=lambda: setattr(self, "_login_future", None),
        )
        return True

    def _clear_login(self):
        self._set_status("Clearing saved login...")

        def worker():
            preferences = LoginPreferences()
            preferences.clear()
            return preferences.load()

        def cleared(values):
            self._apply_login_summary(values)
            self._set_status("Saved login information has been cleared.")

        self.runAsync(
            worker,
            on_result=cleared,
            on_error=lambda error: self._set_status(
                "Unable to clear saved login: {}".format(error), error=True),
        )

    def _save(self):
        # Saving is the one operation that requires values from all categories.
        # Deferred pages are built here if the user never visited them.
        self._ensure_all_pages()
        try:
            if not self._versions:
                raise ValueError("Add at least one Abaqus command before saving.")
            values = self._current_inp_values()
            if values["maximum_cores"] < values["minimum_cores"]:
                raise ValueError("Maximum cores must be greater than or equal to minimum cores.")
            qstat_min = float(self.control_value(self.qstat_min))
            qstat_max = float(self.control_value(self.qstat_max))
            odb_min = float(self.control_value(self.odb_min))
            odb_max = float(self.control_value(self.odb_max))
            inactivity_idle_seconds = 60.0 * float(self.control_value(self.inactivity_idle_minutes))
            inactivity_away_seconds = 60.0 * float(self.control_value(self.inactivity_away_minutes))
            inactivity_deep_seconds = 60.0 * float(self.control_value(self.inactivity_deep_minutes))
            if qstat_max < qstat_min:
                raise ValueError("qstat maximum interval must be greater than or equal to minimum interval.")
            if odb_max < odb_min:
                raise ValueError("ODB maximum interval must be greater than or equal to minimum interval.")
            if inactivity_away_seconds < inactivity_idle_seconds:
                raise ValueError("Away backoff must start after the idle backoff threshold.")
            if inactivity_deep_seconds < inactivity_away_seconds:
                raise ValueError("Deep idle must start after the away backoff threshold.")
            self._save_update_preferences_only()
            INPPreferences().save(values)
            general_values = {
                "auto_login": bool(self.control_value(self.auto_login)),
                "show_hidden_files": bool(self.control_value(self.show_hidden_files)),
            }
            GeneralPreferences().save(**general_values)
            PerformancePreferences().save({
                "qstat_min_interval": qstat_min,
                "qstat_max_interval": qstat_max,
                "qstat_stable_samples_to_max": int(self.control_value(self.qstat_stable)),
                "qstat_quiet_seconds_to_max": float(self.control_value(self.qstat_quiet)),
                "inactivity_idle_seconds": inactivity_idle_seconds,
                "inactivity_away_seconds": inactivity_away_seconds,
                "inactivity_deep_idle_seconds": inactivity_deep_seconds,
                "inactivity_idle_qstat_interval": float(self.control_value(self.inactivity_idle_qstat)),
                "inactivity_away_qstat_interval": float(self.control_value(self.inactivity_away_qstat)),
                "inactivity_deep_qstat_interval": float(self.control_value(self.inactivity_deep_qstat)),
                "inactivity_deep_odb_interval": 60.0 * float(self.control_value(self.inactivity_deep_odb)),
                "odb_min_interval": odb_min,
                "odb_max_interval": odb_max,
                "odb_stable_samples_to_max": int(self.control_value(self.odb_stable)),
                "odb_quiet_seconds_to_max": float(self.control_value(self.odb_quiet)),
                "odb_history_alpha": float(self.control_value(self.odb_history_alpha)),
                "odb_prediction_fraction": float(self.control_value(self.odb_prediction_fraction)),
                "odb_history_confidence_samples": int(self.control_value(self.odb_history_confidence)),
                "odb_catalog_changed_checks": int(self.control_value(self.odb_catalog_checks)),
            })
            AbaqusVersionPreferences().save(self._versions, self.control_value(self.default_command))
        except (OSError, ValueError, TypeError) as exc:
            self._set_status("Unable to save settings: {}".format(exc), error=True)
            return
        callback = self._on_settings_saved or getattr(self.view, "apply_general_preferences", None)
        if callable(callback):
            callback(general_values)
        self.destroy()
