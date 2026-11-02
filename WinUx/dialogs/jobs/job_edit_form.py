from __future__ import annotations

import time
from datetime import datetime
from DearUIQt.dialogs.qt_dialog import QtDialog
from ..logic.job_schedule import JobEditScheduleLogic


class JobEditDialog(JobEditScheduleLogic, QtDialog):
    """Dear PyGui editor, retaining the existing schedule parsing contract."""

    REUSABLE_HOST = True
    DIALOG_WIDTH = 420
    DIALOG_HEIGHT = 460

    def __init__(self, view, values, settings=None, on_result=None):
        self.on_result = on_result
        self.result = {"done": False, "value": None}
        mode, after, at, runtime_limit = self._initial_delete_values(settings)
        QtDialog.__init__(self, view, "Edit Job", self.DIALOG_WIDTH, self.DIALOG_HEIGHT, compact=True)
        self.preferred_size = (self.DIALOG_WIDTH, self.DIALOG_HEIGHT)
        self._current_elapsed_text = str(values[5]) if len(values) > 5 else ""
        self._current_elapsed_seconds = self._elapsed_seconds(self._current_elapsed_text)
        self.header("Edit job", "Set when this running job should be deleted.")
        with self.section("Job summary") as summary:
            order = (0, 4, 2, 3, 5, 1)
            self.summary_grid(
                [(self.JOB_FIELDS[index][0],
                  str(values[index]) if index < len(values) else "-")
                 for index in order],
                parent=summary, columns=2, label_width=50,
            )
        with self.section("Automatic deletion") as schedule:
            self.mode = self.radio_group(
                self.DELETE_MODES,
                current=mode,
                horizontal=True,
                parent=schedule,
                callback=lambda: self._tick(schedule=False),
            )
            form = self.form_layout(parent=schedule, label_width=92)
            self.runtime_limit = self.form_layout_row(
                form, "Run Time Limit",
                lambda parent: self.line_edit(
                    runtime_limit, parent=parent, callback=lambda: self._tick(schedule=False)),
            )
            self.after = self.form_layout_row(
                form, "Delete After",
                lambda parent: self.line_edit(
                    after, parent=parent, callback=lambda: self._tick(schedule=False)),
            )
            self.at = self.form_layout_row(
                form, "Delete At",
                lambda parent: self.line_edit(
                    at, parent=parent, callback=lambda: self._tick(schedule=False)),
            )
            self.form_layout_row(
                form, "",
                lambda parent: self.note(
                    "Duration: HH:MM[:SS]  |  Date: YYYY-MM-DD HH:MM:SS", parent=parent),
            )
        self.runtime_status = self.status_text()
        self.error = self.status_text(error=True)
        self.save_button = self.button_box([("Save", self._save, "primary", True),
            ("Cancel", lambda: self.finish(None), "secondary", False)])[0]
        self._clock_timer = self.create_timer(1000, lambda: self._tick(schedule=False))
        self._tick(schedule=False)

    def _tick(self, schedule=True):
        if not self.winfo_exists():
            return
        mode = self.control_value(self.mode)
        runtime_mode = mode == "Run Time Limit"
        after_mode = mode == "Delete After"
        at_mode = mode == "Delete At"
        self.set_control_enabled(self.runtime_limit, runtime_mode)
        self.set_control_enabled(self.after, after_mode)
        self.set_control_enabled(self.at, at_mode)
        runtime_status = ""
        try:
            if runtime_mode:
                limit_seconds = self._duration_seconds(
                    self.control_value(self.runtime_limit, ""))
                if self._current_elapsed_seconds >= limit_seconds:
                    runtime_status = (
                        "Current run time {} already reached this limit; "
                        "the job will be deleted immediately.".format(
                            self._format_duration(self._current_elapsed_seconds)))
                else:
                    runtime_status = (
                        "Current run time: {}  |  Remaining: {}".format(
                            self._format_duration(self._current_elapsed_seconds),
                            self._format_duration(
                                limit_seconds - self._current_elapsed_seconds)))
            elif after_mode:
                self.set_control_value(
                    self.at, self._delete_at_from_duration(self.control_value(self.after, "")))
            elif self._parse_delete_at(self.control_value(self.at, "")) <= datetime.now():
                raise ValueError("Delete At must be in the future")
            error = ""
        except ValueError as exc:
            error = str(exc)
        self.set_status_text(self.runtime_status, runtime_status)
        self.set_status_text(self.error, error, error=True)
        self.set_control_enabled(self.save_button, not error)

    def _save(self):
        self._tick(schedule=False)
        if self.control_value(self.error, ""):
            return
        mode = self.control_value(self.mode)
        after = str(self.control_value(self.after, "") or "").strip()
        runtime_limit = str(self.control_value(self.runtime_limit, "") or "").strip()
        if mode == "Delete After":
            at = self._delete_at_from_duration(after)
        elif mode == "Delete At":
            at = self._parse_delete_at(
                self.control_value(self.at, "")).strftime(self.DELETE_AT_FORMAT)
        else:
            at = str(self.control_value(self.at, "") or "").strip()
        self.finish({
            "mode": mode,
            "delete_runtime_enabled": mode == "Run Time Limit",
            "delete_runtime": runtime_limit,
            "runtime_elapsed": self._current_elapsed_text,
            "delete_after_enabled": mode == "Delete After",
            "delete_after": after,
            "delete_at_enabled": mode == "Delete At",
            "delete_at": at,
        })

    def finish(self, value):
        if self.result["done"]:
            return
        self.result.update(done=True, value=value)
        try:
            if callable(self.on_result):
                self.on_result(value)
        finally:
            self.destroy()

    _window_finished = finish

    def wait(self, timeout=None):
        deadline = None if timeout is None else time.monotonic() + timeout
        while not self.result["done"] and self.winfo_exists() and self.runtime_running():
            if deadline is not None and time.monotonic() >= deadline:
                break
            self.view.update()
        return self.result["value"]
