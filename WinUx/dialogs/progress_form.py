from __future__ import annotations

import time
import dearpygui.dearpygui as dpg
from .qt_dialog import QtDialog
from .logic.formatting import format_size, format_time
from .theme import error_text_theme, muted_text_theme
from ..widgets import QLabel, QProgressBar


class ProgressDialog(QtDialog):
    def __init__(self, view, operation, cancel_event, items=None):
        self.operation = str(operation)
        self.cancel_event = cancel_event
        self.items = list(items or [])
        self.started_at = time.monotonic()
        self._failed = False
        self._cancelling = False
        super().__init__(view, self.operation, 510, 210, modal=False)
        self.preferred_size = (500, 192)
        self.header(self.operation, "Transfer progress")
        self._current_label = self.own_widget(QLabel("Preparing transfer...", parent=self.content, after=view.after))
        self._current_progress = self.own_widget(QProgressBar(parent=self.content, after=view.after))
        dpg.add_spacer(parent=self.content, height=2)
        self._overall_label = self.own_widget(QLabel("Overall: 0.0%", parent=self.content, after=view.after))
        self._overall_progress = self.own_widget(QProgressBar(parent=self.content, after=view.after))
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
            dpg.set_value(self.stats, stats)
        elif command == "fail":
            self._failed = True
            dpg.set_value(self.current, "{} failed".format(self.operation))
            dpg.set_value(self.stats, args[0])
            self._current_progress.setState("error")
            self._overall_progress.setState("error")
            self._current_progress.setFormat("Failed")
            self._overall_progress.setFormat("Failed")
            dpg.bind_item_theme(self.current, error_text_theme())
            dpg.bind_item_theme(self.stats, error_text_theme())
            dpg.configure_item(self.action_button, label="Close", enabled=True, callback=lambda: self.destroy())
        elif command == "cancelling":
            self._cancelling = True
            dpg.set_value(self.current, "Cancelling...")
            dpg.set_value(self.stats, "Waiting for the current transfer operation to stop...")
            self._current_progress.setState("paused")
            self._overall_progress.setState("paused")
            dpg.bind_item_theme(self.current, muted_text_theme())
            dpg.bind_item_theme(self.stats, muted_text_theme())
            dpg.configure_item(self.action_button, enabled=False)

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
