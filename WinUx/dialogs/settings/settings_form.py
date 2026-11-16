from __future__ import annotations

import os

from DearUIQt.backends import dpg
from ...preferences.abaqus_versions import AbaqusVersionPreferences
from ...preferences.general import GeneralPreferences
from ...preferences.appearance import (
    available_ui_font_families, available_ui_font_styles, resolve_ui_font_face_path,
    AVAILABLE_UI_THEMES, MIN_UI_FONT_SIZE, MAX_UI_FONT_SIZE,
)
from ...preferences.inp import INPPreferences
from ...preferences.login import LoginPreferences
from ...preferences.performance import PerformancePreferences
from ...preferences.update import UpdatePreferences
from DearUIQt.dialogs.qt_dialog import QtDialog
from DearUIQt.dialogs.font_dialog import QFontDialog
from DearUIQt.themes import DialogMetrics, muted_text_theme, error_text_theme
from DearUIQt.core import Qt
from DearUIQt.layouts import QGridLayout
from DearUIQt.widgets import QCheckBox, QStackedWidget, QLabel, QSeparator, QScrollArea
from DearUIQt.modelview import QtListView, QListWidget, QListWidgetItem
from .settings_file_colors import FileColorSettingsMixin


class SettingsDialog(FileColorSettingsMixin, QtDialog):
    REUSABLE_HOST = True
    NAV_WIDTH = DialogMetrics.NAV_WIDTH
    FORM_LABEL_WIDTH = DialogMetrics.LABEL_WIDTH
    FORM_EDITOR_WIDTH = 270
    WIDE_EDITOR_WIDTH = 330
    NUMERIC_EDITOR_WIDTH = 190
    PERFORMANCE_LABEL_WIDTH = 210
    NOTE_WRAP = 560
    FORMULA_LABELS = {"Legacy tiers (32 / 64 / 128 / max)": INPPreferences.FORMULA_LEGACY,
                      "Adaptive (DOF / core factor)": INPPreferences.FORMULA_ADAPTIVE}
    DEFAULT_ABAQUS_COMMAND = AbaqusVersionPreferences.DEFAULT_COMMAND
    DEFAULT_ABAQUS_COMMANDS = list(AbaqusVersionPreferences.DEFAULT_COMMANDS)
    UPDATE_PROVIDER_LABELS = {
        "GitHub Releases (recommended)": "github",
    }
    UPDATE_CHANNEL_LABELS = {"Stable": "stable", "Beta / prerelease": "beta"}

    PAGE_ORDER = ("general", "colors", "updates", "performance", "abaqus", "account")

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
        super().__init__(view, "Settings", 740, 470)
        self.setMinimumSize(680, 420)
        self.preferred_size = (740, 470)
        dpg.configure_item(self.content, no_scrollbar=True, no_scroll_with_mouse=True)
        self.pages = {}
        self._page_widgets = {}
        self.navigation = {}
        self._settings_grid = self.own_widget(QGridLayout(
            2, column_widths=(self.NAV_WIDTH, None),
            parent=self._qt_parent(self.content), after=view.after, backend=dpg))
        nav = self.navigation_panel(
            width=self.NAV_WIDTH, parent=self._settings_grid.cell(0, 0).tag)
        dpg.configure_item(nav, border=False)
        heading = QLabel("Preferences", parent=nav, backend=dpg).tag
        font = getattr(self.view, "heading_font", None)
        if font:
            dpg.bind_item_font(heading, font)
        QSeparator(parent=nav, backend=dpg)
        nav_item_width = max(80, self.NAV_WIDTH - 14)
        self.navigation_list = self.own_widget(QListWidget(
            parent=self._qt_parent(nav), after=view.after, backend=dpg,
            width=nav_item_width, visible_rows=len(self.PAGE_ORDER)))
        for key, label in (("general", "General"), ("colors", "File Colors"), ("updates", "Updates"),
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
                         status_item=self.status, status_above_buttons=True)
        self.set_default_button = self.left_buttons[0]
        if "general" in self._page_built:
            self._formula_changed()

    def _set_status(self, text, error=False):
        self.set_status_text(self.status, str(text), error=bool(error))
        self._apply_layout()

    def note(self, text, parent=None, wrap=0):
        item = super().note(text, parent=parent, wrap=wrap)
        if wrap:
            if not hasattr(self, '_wrapped_notes'):
                self._wrapped_notes = []
            self._wrapped_notes.append((item, wrap))
        return item

    def _apply_layout(self):
        super()._apply_layout()
        scroll = getattr(self, 'page_scroll', None)
        if scroll is None or not self.winfo_exists():
            return
        width = int(dpg.get_item_rect_size(scroll.tag)[0])
        if width <= 0:
            return
        # Notes live in a sidebar page, not across the entire dialog. Reserve
        # section padding and the scrollbar before wrapping their text.
        available = max(120, width - 36)
        for item, requested in getattr(self, '_wrapped_notes', ()):
            if dpg.does_item_exist(item):
                self._configure_layout_item(item, wrap=min(requested, available))

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
        if key == "colors":
            return GeneralPreferences().load()
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
        elif key == "colors":
            value = self._page_data('colors') if data is None else data
            self._settings_page_data['colors'] = value
            self._build_colors_page(parent, value)
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
        # Only account data needs a second-stage refresh. The Updates page is
        # intentionally self-contained and does not load recovery diagnostics
        # unless an internal diagnostic path asks for them.
        if key == "account":
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
        if (defer_io and key in ("general", "colors", "updates", "performance", "abaqus") and
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
        if key == "account":
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

    def _current_font_summary(self):
        family = str(getattr(self, "_ui_font_family_value", GeneralPreferences.DEFAULT_UI_FONT_FAMILY))
        style = str(getattr(self, "_ui_font_style_value", GeneralPreferences.DEFAULT_UI_FONT_STYLE))
        size = int(getattr(self, "_ui_font_size_value", GeneralPreferences.DEFAULT_UI_FONT_SIZE))
        return "{} - {} - {} px".format(family, style, size)

    def _refresh_font_summary(self):
        widget = getattr(self, "_font_summary_widget", None)
        if widget is not None:
            try:
                widget.setText(self._current_font_summary())
            except Exception:
                pass

    def _open_font_selector(self):
        """Open the single source of truth for application typography."""
        if getattr(self, "_font_selector_open_pending", False):
            return None
        self._font_selector_open_pending = True

        def create_font_selector():
            self._font_selector_open_pending = False
            if not self.winfo_exists():
                return None
            dialog = QFontDialog(
                self.view,
                families=available_ui_font_families(),
                styles_provider=available_ui_font_styles,
                face_resolver=resolve_ui_font_face_path,
                family=getattr(self, "_ui_font_family_value", GeneralPreferences.DEFAULT_UI_FONT_FAMILY),
                style=getattr(self, "_ui_font_style_value", GeneralPreferences.DEFAULT_UI_FONT_STYLE),
                size=int(getattr(self, "_ui_font_size_value", GeneralPreferences.DEFAULT_UI_FONT_SIZE)),
                minimum_size=MIN_UI_FONT_SIZE, maximum_size=MAX_UI_FONT_SIZE,
                on_selected=self._font_selector_selected,
                parent=self,
            )
            self.own_dialog(dialog)
            return dialog

        self.view.after(0, create_font_selector)
        return None

    def _font_selector_selected(self, selection):
        self._ui_font_family_value = str(selection.family)
        self._ui_font_style_value = str(selection.style)
        self._ui_font_size_value = int(selection.size)
        self._refresh_font_summary()
        self._set_status("Font selected: {}. Save to apply.".format(self._current_font_summary()))

    def _build_general_page(self, page, inp, general):
        self.header("General", "Startup, file handling and CPU estimation.", parent=page)
        with self.section("Startup", parent=page) as startup:
            self._auto_login_widget = self.own_widget(QCheckBox(
                "Automatically log in on startup", checked=general.get("auto_login", False),
                parent=startup, after=self.view.after, backend=dpg))
            self.auto_login = self._auto_login_widget.tag

        with self.section("Appearance", parent=page) as appearance:
            appearance_form = self.form_layout(
                parent=appearance, label_width=124, editor_width=self.FORM_EDITOR_WIDTH)
            self.ui_theme = self.form_layout_row(
                appearance_form, "Theme",
                lambda parent: self.combo(
                    list(AVAILABLE_UI_THEMES), parent=parent,
                    default_value=str(general.get("ui_theme", GeneralPreferences.DEFAULT_UI_THEME)),
                ),
            )
            self._ui_font_family_value = str(general.get(
                "ui_font_family", GeneralPreferences.DEFAULT_UI_FONT_FAMILY))
            self._ui_font_style_value = str(general.get(
                "ui_font_style", GeneralPreferences.DEFAULT_UI_FONT_STYLE))
            self._ui_font_size_value = int(general.get(
                "ui_font_size", GeneralPreferences.DEFAULT_UI_FONT_SIZE))
            self._font_summary_widget = self.own_widget(QLabel(
                self._current_font_summary(), parent=appearance,
                after=self.view.after, backend=dpg))
            self.action("Choose Font...", self._open_font_selector,
                        "secondary", parent=appearance, width=self.action_width("Choose Font..."))
            self.note(
                "Choose Light or Dark for the application theme. Use Font dialog to choose family, style and size. Save applies both immediately.",
                parent=appearance, wrap=self.NOTE_WRAP)

        with self.section("File browsing", parent=page) as browsing:
            self._show_hidden_files_widget = self.own_widget(QCheckBox(
                "Show hidden files and folders", checked=general.get("show_hidden_files", False),
                parent=browsing, after=self.view.after, backend=dpg))
            self.show_hidden_files = self._show_hidden_files_widget.tag
            self._file_colors_widget = self.own_widget(QCheckBox(
                "Color file names by type",
                checked=general.get('file_colors', GeneralPreferences.DEFAULT_FILE_COLORS),
                parent=browsing, after=self.view.after, backend=dpg))
            self.file_colors = self._file_colors_widget.tag
            self.action('Configure File Colors...', lambda: self._show_page('colors'),
                        'secondary', parent=browsing, width=168)
            self.note("Applies to both Local and Server file lists.",
                      parent=browsing, wrap=self.NOTE_WRAP)

        with self.section('File transfers', parent=page) as transfers:
            self._preserve_file_timestamps_widget = self.own_widget(QCheckBox(
                'Preserve source file modification times',
                checked=general.get('preserve_file_timestamps', GeneralPreferences.DEFAULT_PRESERVE_FILE_TIMESTAMPS),
                parent=transfers, after=self.view.after, backend=dpg))
            self.preserve_file_timestamps = self._preserve_file_timestamps_widget.tag
            self.note(
                'Used by Upload, Download, Quick Transfer and cross-panel copies when the target supports it.',
                parent=transfers, wrap=self.NOTE_WRAP)

        with self.section("CPU estimation", parent=page) as cores:
            label = next((label for label, value in self.FORMULA_LABELS.items()
                          if value == inp.get("formula")), next(iter(self.FORMULA_LABELS)))
            form = self.form_layout(
                parent=cores, label_width=124, editor_width=self.FORM_EDITOR_WIDTH)
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
            self.preview = self.note("", wrap=self.NOTE_WRAP, parent=cores)

    def _build_updates_page(self, page, updates):
        self.header(
            "Updates",
            "Check GitHub Releases and choose which release channel to follow.",
            parent=page,
        )

        # GitHub is the only normal update provider. Keep repository plumbing
        # internal so the page exposes only choices that matter to users.
        defaults = UpdatePreferences.defaults()
        self._update_repository_value = (
            updates.get("github_repository") or defaults.get("github_repository") or ""
        )

        project_dir = os.path.abspath(os.path.join(
            os.path.dirname(__file__), "..", "..", ".."
        ))
        try:
            from winux_runtime.update.manifest import read_version
            current_version = read_version(project_dir) or "Unknown"
        except (ImportError, OSError, ValueError, TypeError):
            current_version = "Unknown"

        with self.section("Version", parent=page) as update_section:
            form = self.form_layout(
                parent=update_section, label_width=116, editor_width=240)
            self.current_update_version = self.form_layout_row(
                form, "Current version",
                lambda parent: QLabel(
                    str(current_version), parent=parent, backend=dpg
                ).tag,
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
                ),
            )

            def update_actions(parent):
                with dpg.group(horizontal=True, horizontal_spacing=DialogMetrics.BUTTON_GAP,
                               parent=parent) as buttons:
                    self.check_updates_button = self.action(
                        "Check for Updates", self._check_for_updates_now, "primary", parent=buttons
                    )
                    self.install_update_button = self.action(
                        "Update Now", self._install_update_now, "primary", parent=buttons
                    )
                    self.set_control_enabled(self.install_update_button, False)
                return buttons

            self.form_layout_editor_row(form, update_actions)
            self.update_check_status = self.note(
                "Ready to check for updates.", wrap=self.NOTE_WRAP, parent=update_section
            )

    def _build_performance_page(self, page, performance):
        self.header(
            "Performance",
            "Polling intervals automatically back off while jobs or the workstation are idle.",
            parent=page,
        )
        with self.section("PBS Job Viewer", parent=page) as qstat:
            self.note("Controls qstat -f polling while the Job Viewer is active.",
                      wrap=self.NOTE_WRAP, parent=qstat)
            form = self.form_layout(
                parent=qstat, label_width=188, editor_width=self.NUMERIC_EDITOR_WIDTH)
            self.qstat_min = self.form_layout_row(form, "Minimum interval (s)", lambda parent: self.spin_float(float(performance["qstat_min_interval"]), parent=parent, minimum=1.0, step=0.5, decimals=1, width=-1))
            self.qstat_max = self.form_layout_row(form, "Maximum interval (s)", lambda parent: self.spin_float(float(performance["qstat_max_interval"]), parent=parent, minimum=1.0, step=0.5, decimals=1, width=-1))
            self.qstat_stable = self.form_layout_row(form, "Stable polls to maximum", lambda parent: self.spin_int(int(performance["qstat_stable_samples_to_max"]), parent=parent, minimum=1, width=-1))
            self.qstat_quiet = self.form_layout_row(form, "Quiet time to maximum (s)", lambda parent: self.spin_float(float(performance["qstat_quiet_seconds_to_max"]), parent=parent, minimum=1.0, step=1.0, decimals=0, width=-1))

        with self.section("Inactivity backoff", parent=page) as inactivity:
            self.note(
                "Remote polling is reduced while you are away; deep idle can pause qstat and keep only a sparse ODB heartbeat.",
                wrap=self.NOTE_WRAP, parent=inactivity,
            )
            form = self.form_layout(
                parent=inactivity, label_width=self.PERFORMANCE_LABEL_WIDTH,
                editor_width=self.NUMERIC_EDITOR_WIDTH)
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
                form, "Deep qstat heartbeat (s)",
                lambda parent: self.spin_float(
                    float(performance["inactivity_deep_qstat_interval"]),
                    parent=parent, minimum=0.0, step=60.0, decimals=0, width=-1))
            self.inactivity_deep_odb = self.form_layout_row(
                form, "Deep ODB heartbeat (min)",
                lambda parent: self.spin_float(
                    float(performance["inactivity_deep_odb_interval"]) / 60.0,
                    parent=parent, minimum=0.5, step=1.0, decimals=1, width=-1))

        with self.section("Realtime ODB Plot", parent=page) as odb:
            self.note(
                "Live ODB checks learn the observed update cadence and probe more often near the predicted next write.",
                wrap=self.NOTE_WRAP, parent=odb)
            form = self.form_layout(
                parent=odb, label_width=self.PERFORMANCE_LABEL_WIDTH,
                editor_width=self.NUMERIC_EDITOR_WIDTH)
            self.odb_min = self.form_layout_row(form, "Minimum file-check interval (s)", lambda parent: self.spin_float(float(performance["odb_min_interval"]), parent=parent, minimum=0.25, step=0.25, decimals=2, width=-1))
            self.odb_max = self.form_layout_row(form, "Maximum quiet interval (s)", lambda parent: self.spin_float(float(performance["odb_max_interval"]), parent=parent, minimum=0.25, step=0.5, decimals=1, width=-1))
            self.odb_stable = self.form_layout_row(form, "Stable checks to maximum", lambda parent: self.spin_int(int(performance["odb_stable_samples_to_max"]), parent=parent, minimum=1, width=-1))
            self.odb_quiet = self.form_layout_row(form, "Quiet time to maximum (s)", lambda parent: self.spin_float(float(performance["odb_quiet_seconds_to_max"]), parent=parent, minimum=1.0, step=1.0, decimals=0, width=-1))
            self.odb_history_alpha = self.form_layout_row(form, "History learning weight (0-1)", lambda parent: self.spin_float(float(performance["odb_history_alpha"]), parent=parent, minimum=0.01, maximum=1.0, step=0.01, decimals=2, width=-1))
            self.odb_prediction_fraction = self.form_layout_row(form, "Predicted-cycle probe fraction", lambda parent: self.spin_float(float(performance["odb_prediction_fraction"]), parent=parent, minimum=0.05, maximum=1.0, step=0.05, decimals=2, width=-1))
            self.odb_history_confidence = self.form_layout_row(form, "History samples for confidence", lambda parent: self.spin_int(int(performance["odb_history_confidence_samples"]), parent=parent, minimum=1, width=-1))
            self.odb_catalog_checks = self.form_layout_row(form, "Catalog rescan interval (changes)", lambda parent: self.spin_int(int(performance["odb_catalog_changed_checks"]), parent=parent, minimum=1, width=-1))

    def _build_abaqus_page(self, page, settings):
        self.header("Abaqus Versions", "Commands WinUx can use to launch Abaqus.", parent=page)
        with self.section("Executable commands", parent=page) as commands:
            visible_rows = max(3, min(5, len(self._versions)))
            self.version_list = self.own_widget(QtListView(
                commands, self._versions, visible_rows=visible_rows, width=-1,
                after=self.view.after, backend=dpg))
            command_form = self.form_layout(
                parent=commands, label_width=self.FORM_LABEL_WIDTH,
                editor_width=self.WIDE_EDITOR_WIDTH)
            self.version_editor = self.form_layout_row(
                command_form, "Command",
                lambda parent: self.line_edit("", parent=parent, width=-1,
                                              hint="e.g. abq2026"))
            self.version_list.currentTextChanged.connect(
                lambda value: self.set_control_value(self.version_editor, value))
            if self._versions:
                self.version_list.setCurrentText(self._versions[0])
            self._version_action_buttons = {}

            def command_actions(parent):
                with dpg.group(parent=parent, horizontal=True,
                               horizontal_spacing=DialogMetrics.BUTTON_GAP) as buttons:
                    for label, action in (("Add", "add"), ("Update", "update"),
                                          ("Delete", "delete"), ("Restore Defaults", "restore")):
                        self._version_action_buttons[action] = self.action(
                            label, lambda action=action: self._edit_version(action),
                            "danger" if action == "delete" else "secondary",
                            parent=buttons, width=112 if action == "restore" else 64)
                return buttons

            self.form_layout_editor_row(command_form, command_actions)

        with self.section("Default version", parent=page) as default:
            default_form = self.form_layout(
                parent=default, label_width=self.FORM_LABEL_WIDTH,
                editor_width=self.WIDE_EDITOR_WIDTH)
            self.default_command = self.form_layout_row(
                default_form, "Command",
                lambda parent: self.combo(
                    self._versions, parent=parent, default_value=settings["default_command"]),
            )
            self.note("Used for new jobs unless another version is selected.",
                      parent=default, wrap=self.NOTE_WRAP)

    def _build_account_page(self, page):
        self.header("Saved Login", "Credentials stored for this Windows account.", parent=page)
        with self.section("Saved credentials", parent=page) as account:
            form = self.form_layout(
                parent=account, label_width=self.FORM_LABEL_WIDTH,
                editor_width=self.WIDE_EDITOR_WIDTH)
            self.login_host_value = self.form_layout_row(
                form, "Host", lambda parent: QLabel("Not saved", parent=parent, backend=dpg).tag)
            self.login_username_value = self.form_layout_row(
                form, "Username", lambda parent: QLabel("Not saved", parent=parent, backend=dpg).tag)
            self.login_password_value = self.form_layout_row(
                form, "Password", lambda parent: QLabel("Not saved", parent=parent, backend=dpg).tag)

            def clear_login_action(parent):
                return self.action(
                    "Clear saved login", self._clear_login, "secondary",
                    parent=parent, width=132)

            self.form_layout_editor_row(form, clear_login_action)
            self.login_summary = self.note("", wrap=self.NOTE_WRAP, parent=account)

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
        self.set_control_value(self.ui_theme, GeneralPreferences.DEFAULT_UI_THEME)
        self._ui_font_family_value = GeneralPreferences.DEFAULT_UI_FONT_FAMILY
        self._ui_font_style_value = GeneralPreferences.DEFAULT_UI_FONT_STYLE
        self._ui_font_size_value = GeneralPreferences.DEFAULT_UI_FONT_SIZE
        self._refresh_font_summary()
        self.set_control_value(self.show_hidden_files, GeneralPreferences.DEFAULT_SHOW_HIDDEN_FILES)
        self.set_control_value(self.file_colors, GeneralPreferences.DEFAULT_FILE_COLORS)
        self.set_control_value(self.preserve_file_timestamps, GeneralPreferences.DEFAULT_PRESERVE_FILE_TIMESTAMPS)
        self._restore_color_defaults()
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
        self.set_control_value(self.update_channel, next(label for label, value in self.UPDATE_CHANNEL_LABELS.items()
                                              if value == updates["channel"]))
        self._update_repository_value = updates["github_repository"]
        self._available_update = None
        self.set_control_enabled(self.install_update_button, False)
        self.set_control_value(self.update_check_status, "Ready to check for updates.")
        self._formula_changed()
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
        # Compatibility hook retained for older callers. GitHub Releases is the
        # only normal provider now, so there is no provider UI to synchronize.
        return None

    def _save_update_preferences_only(self):
        self._ensure_page("updates")
        channel = self.UPDATE_CHANNEL_LABELS.get(
            self.control_value(self.update_channel), "stable"
        )
        repository = getattr(self, "_update_repository_value", "")
        if not repository:
            repository = UpdatePreferences.defaults().get("github_repository", "")
        return UpdatePreferences().save(
            provider="github",
            github_repository=repository,
            channel=channel,
            legacy_source="",
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
                from winux_runtime.update.updater import check_for_updates
                # settings_form.py lives at <deployment>/WinUx/dialogs/settings.
                # Go back to the deployment root that owns VERSION; using only
                # two parents resolves to <deployment>/WinUx and makes the local
                # version look missing, which can incorrectly offer an older
                # GitHub release as a recovery update.
                project_dir = os.path.abspath(os.path.join(
                    os.path.dirname(__file__), "..", "..", ".."
                ))
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

        # Never trust an ``available`` flag without reconciling the two explicit
        # versions.  This is a UI-side fail-safe against stale cache/provider
        # state: an equal or older remote build must never enable Update Now.
        relation = None
        if server_version and local_version not in (None, "", "unknown"):
            try:
                from winux_runtime.update.manifest import compare_versions
                relation = compare_versions(local_version, server_version)
            except (TypeError, ValueError):
                relation = None
        installable = bool(result.get("available"))
        if relation is not None and relation >= 0:
            installable = False
        if not installable:
            self._available_update = None
            self.set_control_enabled(self.install_update_button, False)

        if result.get("error"):
            message = "Could not check for updates: {}".format(result.get("error"))
        elif installable:
            self._available_update = result
            self.set_control_enabled(self.install_update_button, True)
            message = "WinUx {} is available.".format(server_version or "update")
        elif server_version and relation is not None:
            if relation > 0:
                message = "WinUx {} installed. Latest release: {}.".format(
                    local_version, server_version
                )
            elif relation == 0:
                message = "WinUx {} is up to date.".format(local_version)
            else:
                message = "WinUx {} was found but cannot be installed.".format(server_version)
        elif server_version:
            message = "Installed: {}. Latest release: {}.".format(
                local_version, server_version
            )
        else:
            message = "No update was found."
        self.set_control_value(self.update_check_status, message)
        # Full source/version details belong to the Updates page, not repeated
        # beside the global settings actions.
        summary = ("Update available." if installable else
                   "Update check failed." if result.get("error") else
                   "No update is needed." if server_version and relation is not None and relation >= 0 else
                   "No installable update found.")
        self._set_status(summary, error=bool(result.get("error")))

    def _install_update_now(self):
        candidate = getattr(self, "_available_update", None)
        if not candidate:
            return
        # Defense in depth: even if a stale UI callback survives a refresh, do
        # not launch the updater when the remembered remote version is not newer
        # than the local version used for that check.
        local_version = candidate.get("local_version")
        server_version = candidate.get("server_version")
        if local_version and server_version:
            try:
                from winux_runtime.update.manifest import compare_versions
                if compare_versions(local_version, server_version) >= 0:
                    self._available_update = None
                    self.set_control_enabled(self.install_update_button, False)
                    self._set_status(
                        "Update cancelled because the published version is not newer than the installed version."
                    )
                    return
            except (TypeError, ValueError):
                pass
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
            from winux_runtime.update.diagnostics import collect_update_diagnostics, format_update_diagnostics
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
            from winux_runtime.installation_state import clear_quarantine
            from winux_runtime.update.diagnostics import collect_update_diagnostics, format_update_diagnostics
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
        if hasattr(self, "login_host_value"):
            self.set_control_value(self.login_host_value, values.get("host") or "Not saved")
        if hasattr(self, "login_username_value"):
            self.set_control_value(self.login_username_value, values.get("username") or "Not saved")
        if hasattr(self, "login_password_value"):
            self.set_control_value(
                self.login_password_value,
                "Saved and protected" if values.get("password") else "Not saved")
        if hasattr(self, "login_summary"):
            self.set_control_value(self.login_summary, "")

    def _refresh_login(self):
        if not hasattr(self, "login_summary"):
            return False
        future = self._login_future
        if future is not None and not future.isFinished():
            return False
        self.set_control_value(self.login_summary, "Loading saved login...")

        def failed(error):
            self.set_control_value(
                self.login_summary, "Saved login unavailable: {}".format(error))

        self._login_future = self.runAsync(
            lambda: LoginPreferences().load(),
            on_result=self._apply_login_summary,
            on_error=failed,
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
            color_rules = self._collect_color_rules()
            self._save_update_preferences_only()
            INPPreferences().save(values)
            general_values = {
                "auto_login": bool(self.control_value(self.auto_login)),
                "show_hidden_files": bool(self.control_value(self.show_hidden_files)),
                "file_colors": bool(self.control_value(self.file_colors)),
                "file_color_rules": color_rules,
                "preserve_file_timestamps": bool(self.control_value(self.preserve_file_timestamps)),
                "ui_theme": str(self.control_value(self.ui_theme) or GeneralPreferences.DEFAULT_UI_THEME),
                "ui_font_family": str(getattr(self, "_ui_font_family_value", GeneralPreferences.DEFAULT_UI_FONT_FAMILY)).strip(),
                "ui_font_style": str(getattr(self, "_ui_font_style_value", GeneralPreferences.DEFAULT_UI_FONT_STYLE)).strip(),
                "ui_font_size": int(getattr(self, "_ui_font_size_value", GeneralPreferences.DEFAULT_UI_FONT_SIZE)),
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
