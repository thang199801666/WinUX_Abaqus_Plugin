from __future__ import annotations

import time
from datetime import datetime
import dearpygui.dearpygui as dpg
from .qt_dialog import QtDialog
from .logic.job_schedule import JobEditScheduleLogic
from .theme import DialogPalette


class JobEditDialog(JobEditScheduleLogic, QtDialog):
    """Dear PyGui editor, retaining the existing schedule parsing contract."""

    def __init__(self, view, values, settings=None, on_result=None):
        self.on_result = on_result
        self.result = {"done": False, "value": None}
        mode, after, at = self._initial_delete_values(settings)
        QtDialog.__init__(self, view, "Edit Job", 640, 500)
        self.preferred_size = (590, 390)
        self.header("Edit job", "Update the automatic deletion schedule.")
        with self.section("Job summary") as summary:
            with dpg.table(parent=summary, header_row=False, width=-1):
                for _ in range(4):
                    dpg.add_table_column()
                for left, right in ((0, 4), (2, 3), (5, 1)):
                    with dpg.table_row():
                        for index in (left, right):
                            dpg.add_text(self.JOB_FIELDS[index][0], color=DialogPalette.MUTED)
                            dpg.add_text(str(values[index]) if index < len(values) else "-")
        with self.section("Automatic deletion") as schedule:
            self.mode = self.radio_group(
                self.DELETE_MODES,
                current=mode,
                horizontal=True,
                parent=schedule,
                callback=lambda: self._tick(schedule=False),
            )
            self.after = self.field("Delete After", after, parent=schedule, callback=lambda: self._tick(schedule=False))
            self.at = self.field("Delete At", at, parent=schedule, callback=lambda: self._tick(schedule=False))
            self.note("HH:MM[:SS] | YYYY-MM-DD HH:MM:SS", parent=schedule)
        self.error = self.status_text(error=True)
        self.save_button = self.button_box([("Save", self._save, "primary", True),
            ("Cancel", lambda: self.finish(None), "secondary", False)])[0]
        self._tick()

    def _tick(self, schedule=True):
        if not self.winfo_exists():
            return
        after_mode = dpg.get_value(self.mode) == "Delete After"
        dpg.configure_item(self.after, enabled=after_mode)
        dpg.configure_item(self.at, enabled=not after_mode)
        try:
            if after_mode:
                dpg.set_value(self.at, self._delete_at_from_duration(dpg.get_value(self.after)))
            elif self._parse_delete_at(dpg.get_value(self.at)) <= datetime.now():
                raise ValueError("Delete At must be in the future")
            error = ""
        except ValueError as exc:
            error = str(exc)
        dpg.set_value(self.error, error)
        dpg.configure_item(self.save_button, enabled=not error)
        if schedule:
            self.view.after(1000, self._tick)

    def _save(self):
        self._tick(schedule=False)
        if dpg.get_value(self.error):
            return
        mode = dpg.get_value(self.mode)
        after = dpg.get_value(self.after).strip()
        at = self._delete_at_from_duration(after) if mode == "Delete After" else self._parse_delete_at(dpg.get_value(self.at)).strftime(self.DELETE_AT_FORMAT)
        self.finish({"mode": mode, "delete_after_enabled": mode == "Delete After",
                     "delete_after": after, "delete_at_enabled": mode == "Delete At", "delete_at": at})

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
        while not self.result["done"] and self.winfo_exists() and dpg.is_dearpygui_running():
            if deadline is not None and time.monotonic() >= deadline:
                break
            self.view.update()
        return self.result["value"]
