from __future__ import annotations

from datetime import datetime
import dearpygui.dearpygui as dpg
from ..job_manager_preferences import JobManagerPreferences
from ..abaqus_version_preferences import AbaqusVersionPreferences
from .qt_dialog import QtDialog
from .logic.job_manager import JobManagerLogic
from .theme import DialogMetrics


class JobManagerDialog(JobManagerLogic, QtDialog):
    """Per-input job configuration using the existing submission/schedule API."""

    MAX_VISIBLE_ROWS = 7
    ROW_HEIGHT = 28

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
        self._successful_job_names = set()
        self._submission_finished = self._close_requested = False
        self._submitting = False
        self.rows_by_path = {}
        self.preferred_size = self.initial_size(len(self.paths))
        QtDialog.__init__(self, view, "Abaqus Job Manager", *self.preferred_size)
        self.header("Selected input files ({})".format(len(self.paths)))
        with dpg.table(parent=self.content, header_row=True, scrollY=True,
                       height=-24, width=-1, resizable=True, row_background=True,
                       freeze_rows=1, borders_innerH=True, borders_outerH=True,
                       borders_innerV=True, borders_outerV=True,
                       policy=dpg.mvTable_SizingStretchProp) as self.table:
            for heading, width in (("Run", 32), ("Input file", None), ("Version", 100),
                                   ("CPUs", 52), ("Precision", 88), ("Overwrite", 74),
                                   ("Schedule", 108), ("Time", 180)):
                if width is None:
                    dpg.add_table_column(label=heading, width_stretch=True, init_width_or_weight=1)
                else:
                    dpg.add_table_column(label=heading, width_fixed=True, init_width_or_weight=width)
            for path in self.paths:
                with dpg.table_row():
                    row = {"run": self.checkbox(checked=True)}
                    name = dpg.add_text(path.name)
                    with dpg.tooltip(name):
                        dpg.add_text(str(path))
                    row["version"] = self.combo(self._versions, default_value=self._prefs["version"])
                    row["cpus"] = self.spin_int(int(self._prefs.get("cpus", 4)), minimum=1, width=-1)
                    row["precision"] = self.combo(("single", "double"), default_value=self._prefs.get("precision", "single"))
                    row["overwrite"] = self.checkbox(
                        checked=bool(self._prefs.get("overwrite", False)))
                    row["schedule"] = self.combo(self.SCHEDULE_OPTIONS, default_value="Now",
                        user_data=path, callback=self._schedule_changed)
                    row["time"] = self.line_edit("Runs immediately", enabled=False, width=-1,
                        user_data=path, callback=self._time_changed)
                    row["live"] = True
                    row["mode"] = "Now"
                    row["saved"] = {"Run After": "00:30:00", "Run At": ""}
                    self.rows_by_path[path] = row
        self.status = self.status_text(wrap=1000)
        self.run_button, _ = self.button_box([
            ("Run", self._run, "primary", True),
            ("Cancel", self.destroy, "secondary", False)],
            left_actions=[("Estimate cores", self._estimate, "secondary", False)])
        self.estimate_button = self.left_buttons[0]
        self._tick()

    def _schedule_changed(self, sender, value, path):
        row = self.rows_by_path[path]
        old = row["mode"]
        if old != "Now" and not (old == "Run At" and row["live"]):
            row["saved"][old] = dpg.get_value(row["time"])
        row["mode"] = value
        row["live"] = not bool(row["saved"]["Run At"])
        text = "Runs immediately" if value == "Now" else row["saved"][value]
        if value == "Run At" and row["live"]:
            text = datetime.now().strftime(self.RUN_AT_FORMAT)
        dpg.set_value(row["time"], text)
        dpg.configure_item(row["time"], enabled=value != "Now")

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
                if dpg.is_item_focused(row["time"]):
                    row["live"] = False
                else:
                    dpg.set_value(row["time"], datetime.now().strftime(self.RUN_AT_FORMAT))
        self.view.after(1000, self._tick)

    def _estimate(self):
        dpg.configure_item(self.estimate_button, enabled=False)
        dpg.set_value(self.status, "Estimating recommended CPU counts...")
        self.view.after(0, self._request_core_estimates)

    def _run(self):
        if self._submitting:
            return
        jobs = []
        try:
            for path in self.row_order:
                row = self.rows_by_path[path]
                if not dpg.get_value(row["run"]):
                    continue
                job = {name: dpg.get_value(row[name]) for name in ("version", "cpus", "precision", "overwrite")}
                if job["cpus"] < 1:
                    raise ValueError("CPUs must be a positive integer")
                job["path"] = path
                mode, text = dpg.get_value(row["schedule"]), dpg.get_value(row["time"]).strip()
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
            dpg.set_value(self.status, str(exc))
            return
        self._submitting = True
        dpg.configure_item(self.run_button, enabled=False)
        self.view.after(0, self._submit_from_native, jobs)

    def handle_command(self, command, *args):
        if command == "status":
            dpg.set_value(self.status, str(args[0]))
        elif command == "run_enabled":
            self._submitting = not bool(args[0])
            dpg.configure_item(self.run_button, enabled=bool(args[0]))
        elif command == "core_suggestions_ready":
            for path, value in dict(args[0] or {}).items():
                if path in self.rows_by_path:
                    dpg.set_value(self.rows_by_path[path]["cpus"], int(value))
            dpg.configure_item(self.estimate_button, enabled=True)
            dpg.set_value(self.status, args[1])
        elif command == "core_suggestions_failed":
            dpg.configure_item(self.estimate_button, enabled=True)
            dpg.set_value(self.status, "Estimate failed: {}".format(args[0]))
