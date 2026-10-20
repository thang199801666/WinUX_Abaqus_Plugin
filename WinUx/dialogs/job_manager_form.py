from __future__ import annotations

from datetime import datetime
from DearUIQt.backends import dpg
from ..preferences.job_manager import JobManagerPreferences
from ..preferences.abaqus_versions import AbaqusVersionPreferences
from DearUIQt.dialogs.qt_dialog import QtDialog
from DearUIQt.widgets import QLabel, QSpacer
from DearUIQt.modelview import QTableWidget
from DearUIQt.layouts import QVBoxLayout, QHBoxLayout
from .logic.job_manager import JobManagerLogic
from DearUIQt.themes import DialogMetrics
from DearUIQt.themes import METRICS, compact_stack_theme, aligned_cell_theme


class JobManagerDialog(JobManagerLogic, QtDialog):
    """Per-input job configuration using the existing submission/schedule API."""

    REUSABLE_HOST = True

    MAX_VISIBLE_ROWS = 7
    # Visual table row height.  Controls are 26 px high and are centered
    # inside a 32 px row, matching Qt/QTableView editor geometry.
    ROW_HEIGHT = METRICS.control_height + 6

    @classmethod
    def initial_size(cls, count):
        rows = max(1, min(cls.MAX_VISIBLE_ROWS, count))
        height = DialogMetrics.FOOTER_HEIGHT + 2 * DialogMetrics.WINDOW_PAD_Y + 92 + rows * cls.ROW_HEIGHT
        return 1010, max(180, height)

    def __init__(self, view, paths, run_callback, compute_callback):
        self.paths = sorted(list(paths), key=self._input_file_sort_key)
        self.row_order = list(self.paths)
        self.run_callback, self.compute_callback = run_callback, compute_callback
        self._prefs = JobManagerPreferences().load()
        settings = AbaqusVersionPreferences().load_settings()
        self._versions = settings["versions"] or [AbaqusVersionPreferences.DEFAULT_COMMAND]
        if self._prefs.get("version") not in self._versions:
            self._prefs["version"] = settings["default_command"]
        self._pending_queue_job_names = set()
        self._submission_finished = self._close_requested = False
        self._submitting = False
        self.rows_by_path = {}
        self.preferred_size = self.initial_size(len(self.paths))
        QtDialog.__init__(self, view, "Abaqus Job Manager", *self.preferred_size)
        self.header("Selected input files ({})".format(len(self.paths)))
        self.table_widget = self.own_widget(QTableWidget(
            0, 8, parent=self._qt_parent(self.content), after=view.after, backend=dpg,
            header_row=True, scroll_y=True, height=-1, width=-1, resizable=True,
            row_background=True, freeze_rows=1, grid_lines=True,
            sizing_policy=dpg.mvTable_SizingStretchProp))
        self.table = self.table_widget.tag
        self.table_widget.setHorizontalHeaderLabels((
            "Run", "Input file", "Version", "CPUs", "Precision",
            "Overwrite", "Schedule", "Time",
        ))
        for column, width in enumerate((38, None, 108, 58, 92, 82, 112, 160)):
            if width is None:
                self.table_widget.setColumnStretch(column, 1.0)
            else:
                self.table_widget.setColumnWidth(column, width)
        self.style_table(self.table)

        for path in self.paths:
            table_row = self.table_widget.rowCount()
            self.table_widget.insertRow(table_row)
            native_row = self.table_widget.nativeRow(table_row)

            # Table padding supplies 3 px above/below each 26 px editor.
            # Retain the historical native alignment inside QTableWidget cell
            # hosts so the model/view migration does not alter dialog geometry.
            def cell(column, top=0):
                layout = QVBoxLayout(parent=native_row, spacing=0, backend=dpg)
                dpg.bind_item_theme(layout.tag, aligned_cell_theme())
                if top:
                    QSpacer(0, top, parent=layout, backend=dpg)
                self.table_widget.setCellWidget(table_row, column, layout)
                return layout

            def centered_checkbox_cell(column, column_width, *, checked=False):
                holder = cell(column, (METRICS.control_height - METRICS.check_size) // 2)
                usable = max(0, int(column_width))
                lead = max(0, (usable - METRICS.check_size) // 2)
                lane_layout = QHBoxLayout(parent=holder, spacing=0, backend=dpg)
                dpg.bind_item_theme(lane_layout.tag, compact_stack_theme())
                if lead:
                    QSpacer(lead, 0, parent=lane_layout, backend=dpg)
                tag = self.checkbox(checked=checked, parent=lane_layout)
                return tag

            row = {"run": centered_checkbox_cell(0, 38, checked=True)}

            name_cell = cell(1, (METRICS.control_height - METRICS.check_size) // 2)
            name_widget = QLabel(path.name, parent=name_cell, backend=dpg)
            row["name"] = name_widget.tag
            with dpg.tooltip(name_widget.tag):
                QLabel(str(path), backend=dpg)

            version_cell = cell(2)
            row["version"] = self.combo(
                self._versions, parent=version_cell.tag, default_value=self._prefs["version"])

            cpu_cell = cell(3)
            row["cpus"] = self.spin_int(
                int(self._prefs.get("cpus", 4)), parent=cpu_cell, minimum=1, width=-1)

            precision_cell = cell(4)
            row["precision"] = self.combo(
                ("single", "double"), parent=precision_cell.tag,
                default_value=self._prefs.get("precision", "single"))

            row["overwrite"] = centered_checkbox_cell(
                5, 82, checked=bool(self._prefs.get("overwrite", False)))

            schedule_cell = cell(6)
            row["schedule"] = self.combo(
                self.SCHEDULE_OPTIONS, parent=schedule_cell.tag, default_value="Now",
                user_data=path, callback=self._schedule_changed)

            time_cell = cell(7)
            row["time"] = self.line_edit(
                "Runs immediately", parent=time_cell, enabled=False, width=-1,
                user_data=path, callback=self._time_changed)
            row["live"] = True
            row["mode"] = "Now"
            row["saved"] = {"Run After": "00:30:00", "Run At": ""}
            self.rows_by_path[path] = row
        # Status belongs to the QDialogButtonBox middle slot rather than below
        # the table.  This prevents the body child from becoming a few pixels
        # taller than its viewport (and showing a stray vertical scrollbar).
        self.status = self.status_text(wrap=1000)
        self.run_button, _ = self.button_box([
            ("Run", self._run, "primary", True),
            ("Cancel", self.destroy, "secondary", False)],
            left_actions=[("Estimate cores", self._estimate, "secondary", False)],
            status_item=self.status,
            status_left_padding=14)
        self.estimate_button = self.left_buttons[0]
        self._clock_timer = self.create_timer(1000, self._tick)
        self._tick()

    def _schedule_changed(self, sender, value, path):
        row = self.rows_by_path[path]
        old = row["mode"]
        if old != "Now" and not (old == "Run At" and row["live"]):
            row["saved"][old] = self.control_value(row["time"])
        row["mode"] = value
        row["live"] = not bool(row["saved"]["Run At"])
        text = "Runs immediately" if value == "Now" else row["saved"][value]
        if value == "Run At" and row["live"]:
            text = datetime.now().strftime(self.RUN_AT_FORMAT)
        self._control_wrappers[row["time"]].setText(text)
        self.set_control_enabled(row["time"], value != "Now")

    def _time_changed(self, sender, value, path):
        row = self.rows_by_path[path]
        row["live"] = False
        if row["mode"] != "Now":
            row["saved"][row["mode"]] = value

    def _tick(self):
        if not self.winfo_exists():
            return
        for row in self.rows_by_path.values():
            if row["mode"] == "Run At" and row["live"]:
                if bool(getattr(self.control_wrapper(row["time"]), "hasFocus", lambda: False)()):
                    row["live"] = False
                else:
                    self._control_wrappers[row["time"]].setText(datetime.now().strftime(self.RUN_AT_FORMAT))

    def _estimate(self):
        self.set_control_enabled(self.estimate_button, False)
        self.set_control_value(self.status, "Estimating recommended CPU counts...")
        self.view.after(0, self._request_core_estimates)

    def _run(self):
        if self._submitting:
            return
        jobs = []
        try:
            for path in self.row_order:
                row = self.rows_by_path[path]
                if not self.control_value(row["run"]):
                    continue
                job = {name: self.control_value(row[name]) for name in ("version", "cpus", "precision", "overwrite")}
                if job["cpus"] < 1:
                    raise ValueError("CPUs must be a positive integer")
                job["path"] = path
                mode = self.control_value(row["schedule"])
                text = str(self.control_value(row["time"], "") or "").strip()
                if mode == "Run After":
                    job["_run_at"] = datetime.now() + self._parse_run_after(text)
                    job["_schedule_mode"] = "Run After " + text
                elif mode == "Run At":
                    job["_run_at"] = self._resolve_run_at_clock(text, live=row["live"])
                    job["_schedule_mode"] = "Run At"
                jobs.append(job)
            if not jobs:
                raise ValueError("No valid jobs selected.")
        except ValueError as exc:
            self.set_control_value(self.status, str(exc))
            return
        self._submitting = True
        self.set_control_value(self.status, "Preparing submission...")
        self.set_control_enabled(self.run_button, False)
        self.view.after(0, self._submit_from_native, jobs)

    def handle_command(self, command, *args):
        if command == "status":
            self.set_control_value(self.status, str(args[0]))
        elif command == "run_enabled":
            self._submitting = not bool(args[0])
            self.set_control_enabled(self.run_button, bool(args[0]))
        elif command == "core_suggestions_ready":
            for path, value in dict(args[0] or {}).items():
                if path in self.rows_by_path:
                    self.set_control_value(self.rows_by_path[path]["cpus"], int(value))
            self.set_control_enabled(self.estimate_button, True)
            self.set_control_value(self.status, args[1])
        elif command == "core_suggestions_failed":
            self.set_control_enabled(self.estimate_button, True)
            self.set_control_value(self.status, "Estimate failed: {}".format(args[0]))
