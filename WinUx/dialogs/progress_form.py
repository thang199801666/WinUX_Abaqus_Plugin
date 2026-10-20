from __future__ import annotations

import time
from DearUIQt.dialogs.qt_dialog import QtDialog
from .logic.formatting import format_size, format_time
from DearUIQt.themes import error_text_theme, muted_text_theme
from DearUIQt.widgets import QLabel, QProgressBar, QSpacer
from DearUIQt.layouts import QVBoxLayout


class ProgressDialog(QtDialog):
    REUSABLE_HOST = True
    def __init__(self, view, operation, cancel_event, items=None):
        self.operation = str(operation)
        self.cancel_event = cancel_event
        self.items = list(items or [])
        self.started_at = time.monotonic()
        self._failed = False
        self._cancelling = False
        super().__init__(view, self.operation, 510, 210, modal=False)
        self.preferred_size = (500, 192)
        self.content_layout = QVBoxLayout(parent=self.content, after=view.after, spacing=6)
        self.setLayout(self.content_layout)
        self.header(self.operation, "Transfer progress", parent=self.content_layout.tag)
        self._current_label = QLabel("Preparing transfer...", parent=self.content_layout, after=view.after)
        self._current_progress = QProgressBar(parent=self.content_layout, after=view.after)
        spacer = QSpacer(parent=self.content_layout, height=2)
        self._overall_label = QLabel("Overall: 0.0%", parent=self.content_layout, after=view.after)
        self._overall_progress = QProgressBar(parent=self.content_layout, after=view.after)
        self.current, self.current_bar = self._current_label.tag, self._current_progress.tag
        self.overall, self.overall_bar = self._overall_label.tag, self._overall_progress.tag
        self.stats = self.status_text("Speed: --   Estimated time: --")
        self.action_button = self.button_box(
            [("Cancel", self.cancel, "secondary", False)],
            status_item=self.stats,
        )[0]

    def update_progress(self, name, current_done, current_total, overall_done, overall_total):
        current_ratio = max(0, min(1, float(current_done or 0) / max(1, float(current_total or 0))))
        overall_ratio = max(0, min(1, float(overall_done or 0) / max(1, float(overall_total or 0))))
        speed = float(overall_done or 0) / max(.001, time.monotonic() - self.started_at)
        eta = max(0, float(overall_total or 0) - float(overall_done or 0)) / speed if speed else None
        self.post_latest("progress", "{}: {} ({:.1f}%)".format(self.operation, name, current_ratio*100),
            current_ratio, overall_ratio, "Speed: {}/s   Estimated time: {}".format(self._format_size(speed), self._format_time(eta)))

    def handle_command(self, command, *args):
        if command == "progress" and not self._failed and not self._cancelling:
            text, current, overall, stats = args
            self._current_label.setText(text)
            self._current_progress.setValue(current)
            self._overall_progress.setValue(overall)
            self._current_progress.setFormat("{:.1f}%".format(current*100))
            self._overall_progress.setFormat("{:.1f}%".format(overall*100))
            self._overall_label.setText("Overall: {:.1f}%".format(overall*100))
            self.set_control_value(self.stats, stats)
        elif command == "fail":
            self._failed = True
            self.set_control_value(self.current, "{} failed".format(self.operation))
            self.set_control_value(self.stats, args[0])
            self._current_progress.setState("error")
            self._overall_progress.setState("error")
            self._current_progress.setFormat("Failed")
            self._overall_progress.setFormat("Failed")
            self.set_control_theme(self.current, error_text_theme())
            self.set_control_theme(self.stats, error_text_theme())
            self.set_control_value(self.action_button, "Close")
            self.set_control_enabled(self.action_button, True)
        elif command == "cancelling":
            self._cancelling = True
            self.set_control_value(self.current, "Cancelling...")
            self.set_control_value(self.stats, "Waiting for the current transfer operation to stop...")
            self._current_progress.setState("paused")
            self._overall_progress.setState("paused")
            self.set_control_theme(self.current, muted_text_theme())
            self.set_control_theme(self.stats, muted_text_theme())
            self.set_control_enabled(self.action_button, False)

    def complete(self):
        self.view.after(0, self.destroy)

    def fail(self, message):
        self.post("fail", str(message))

    def cancel(self):
        if self._failed:
            self.destroy()
            return
        self.cancel_event.set()
        self._cancelling = True
        self.post("cancelling")

    def _close_from_escape(self):
        self.cancel()

    _format_size = staticmethod(format_size)
    _format_time = staticmethod(format_time)
