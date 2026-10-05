from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path
import dearpygui.dearpygui as dpg
from ..diagnostics import build_diagnostics_report, get_log_paths
from .qt_dialog import QtDialog


class DiagnosticsDialog(QtDialog):
    def __init__(self, view, report_provider=None):
        self._report_provider = report_provider or build_diagnostics_report
        super().__init__(view, "WinUx Diagnostics", 720, 480, modal=False)
        self.header("Diagnostics", "Runtime, dependencies and crash-log information.")
        self.text = self.plain_text_edit("", readonly=True, width=-1,
                                        height=-30, parent=self.content)
        self.enter_editors.add(self.text)
        self.status = self.status_text()
        self.button_box([("Close", self.destroy, "primary", True)],
            left_actions=[("Refresh", self.refresh, "secondary", False),
                          ("Copy", self.copy, "secondary", False),
                          ("Save Report", self.save, "secondary", False),
                          ("Open Logs", self.open_logs, "secondary", False)],
            status_item=self.status)
        self.refresh()

    def refresh(self, *_args):
        dpg.set_value(self.text, self._report_provider())
        dpg.set_value(self.status, "Diagnostics refreshed")

    def copy(self):
        dpg.set_clipboard_text(dpg.get_value(self.text))
        dpg.set_value(self.status, "Report copied to clipboard")

    def save(self):
        directory = Path(get_log_paths().get("directory") or Path.home())
        target = directory / "winux_diagnostics_{}.txt".format(datetime.now().strftime("%Y%m%d_%H%M%S"))
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(dpg.get_value(self.text), encoding="utf-8")
            dpg.set_value(self.status, "Saved: {}".format(target))
        except OSError as exc:
            dpg.set_value(self.status, "Could not save report: {}".format(exc))

    def open_logs(self):
        directory = get_log_paths().get("directory")
        try:
            if not directory:
                raise OSError("Log directory is not available")
            os.startfile(directory)
        except (AttributeError, OSError) as exc:
            dpg.set_value(self.status, "Could not open logs: {}".format(exc))

    def handle_command(self, command, *args):
        if command == "refresh":
            self.refresh()
        elif command == "report":
            dpg.set_value(self.text, str(args[0]))
            dpg.set_value(self.status, "Diagnostics refreshed")
