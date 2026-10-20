from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path
from DearUIQt import QClipboard
from ..diagnostics import build_diagnostics_report, get_log_paths
from DearUIQt.dialogs.qt_dialog import QtDialog
from DearUIQt.layouts import QVBoxLayout


class DiagnosticsDialog(QtDialog):
    REUSABLE_HOST = True
    def __init__(self, view, report_provider=None):
        self._report_provider = report_provider or build_diagnostics_report
        self._report_future = None
        self._report_generation = 0
        super().__init__(view, "WinUx Diagnostics", 720, 480, modal=False)
        self.content_layout = QVBoxLayout(parent=self.content, after=view.after, spacing=6)
        self.setLayout(self.content_layout)
        self.header("Diagnostics", "Runtime, dependencies and crash-log information.",
                    parent=self.content_layout.tag)
        self.text = self.plain_text_edit("", readonly=True, width=-1,
                                        height=-30, parent=self.content_layout.tag)
        self.enter_editors.add(self.text)
        self.status = self.status_text(parent=self.content_layout.tag)
        self.button_box([("Close", self.destroy, "primary", True)],
            left_actions=[("Refresh", self.refresh, "secondary", False),
                          ("Copy", self.copy, "secondary", False),
                          ("Save Report", self.save, "secondary", False),
                          ("Open Logs", self.open_logs, "secondary", False)],
            status_item=self.status)
        self.set_control_value(self.status, "Loading diagnostics...")
        self.after_first_present(self.refresh)

    def refresh(self, *_args):
        if self._report_future is not None and not self._report_future.isFinished():
            return False
        self._report_generation += 1
        generation = self._report_generation
        self.set_control_value(self.status, "Loading diagnostics...")

        def ready(report):
            if generation == self._report_generation:
                self.set_control_value(self.text, str(report))
                self.set_control_value(self.status, "Diagnostics refreshed")

        def failed(error):
            if generation == self._report_generation:
                self.set_control_value(self.status, "Diagnostics refresh failed: {}".format(error))

        self._report_future = self.runAsync(self._report_provider, on_result=ready, on_error=failed)
        return True

    def copy(self):
        QClipboard().setText(str(self.control_value(self.text, "") or ""))
        self.set_control_value(self.status, "Report copied to clipboard")

    def save(self):
        directory = Path(get_log_paths().get("directory") or Path.home())
        target = directory / "winux_diagnostics_{}.txt".format(datetime.now().strftime("%Y%m%d_%H%M%S"))
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(str(self.control_value(self.text, "") or ""), encoding="utf-8")
            self.set_control_value(self.status, "Saved: {}".format(target))
        except OSError as exc:
            self.set_control_value(self.status, "Could not save report: {}".format(exc))

    def open_logs(self):
        directory = get_log_paths().get("directory")
        try:
            if not directory:
                raise OSError("Log directory is not available")
            os.startfile(directory)
        except (AttributeError, OSError) as exc:
            self.set_control_value(self.status, "Could not open logs: {}".format(exc))

    def handle_command(self, command, *args):
        if command == "refresh":
            self.refresh()
        elif command == "report":
            self._report_generation += 1
            self.set_control_value(self.text, str(args[0]))
            self.set_control_value(self.status, "Diagnostics refreshed")
