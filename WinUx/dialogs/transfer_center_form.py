from __future__ import annotations

import itertools
import threading
import dearpygui.dearpygui as dpg
from .qt_dialog import QtDialog
from .theme import DialogMetrics
from .logic.transfer import TransferCenterLogic, TransferTaskHandle, TransferItemRow

_TransferItemRow = TransferItemRow


class TransferCenterDialog(TransferCenterLogic, QtDialog):
    """Modeless DPG transfer center; coalesced task updates retain old handles."""

    def __init__(self, view, on_cancel_all=None, on_clear_finished=None, on_row_action=None):
        self._on_cancel_all = on_cancel_all
        self._on_clear_finished = on_clear_finished
        self._on_row_action = on_row_action
        self.tasks = []
        self._active_batch_failed = False
        self._row_ids = itertools.count(1)
        self._row_to_task = {}
        self._row_update_lock = threading.Lock()
        self._pending_row_updates = {}
        self._row_update_scheduled = False
        self.row_widgets = {}
        QtDialog.__init__(self, view, "Transfer Center", 760, 340, modal=False)
        self.header("Transfers", "Per-file progress and queue controls.")
        self.button_box([("Cancel All", self.request_cancel_all, "danger", False),
                         ("Clear Finished", self.request_clear_finished, "secondary", False),
                         ("Hide", self.hide, "secondary", False)])
        self.hide()

    def _close_from_escape(self):
        self.hide()

    def request_cancel_all(self):
        if callable(self._on_cancel_all):
            self._on_cancel_all()
        else:
            super().request_cancel_all()

    def request_clear_finished(self):
        if callable(self._on_clear_finished):
            self._on_clear_finished()
        else:
            super().request_clear_finished()

    def _request_row_action(self, row_id):
        if callable(self._on_row_action):
            self._on_row_action(row_id)
        else:
            super()._request_row_action(row_id)

    def handle_command(self, command, *args):
        if command == "add_row":
            row_id, operation, name = args
            with dpg.group(parent=self.content) as group:
                title = dpg.add_text("{}: {}".format(operation, name))
                with dpg.table(header_row=False, width=-1):
                    dpg.add_table_column(width_stretch=True)
                    dpg.add_table_column(width_fixed=True, init_width_or_weight=94)
                    with dpg.table_row() as row_parent:
                        progress = self.progress_bar(
                            0.0, parent=row_parent, overlay="0%")
                        action = self.action(
                            "Cancel",
                            lambda _row_id=row_id: self._request_row_action(_row_id),
                            "secondary",
                            False,
                            parent=row_parent,
                            width=94,
                            height=DialogMetrics.BUTTON_HEIGHT,
                        )
                stats = self.status_text("Queued", parent=group, wrap=650)
                dpg.add_separator()
            self.row_widgets[row_id] = {"group": group, "title": title,
                "progress": progress, "stats": stats, "action": action,
                "operation": operation, "name": name, "status": "Queued", "statistics": ""}
        elif command == "remove_row":
            row = self.row_widgets.pop(args[0], None)
            if row:
                dpg.delete_item(row["group"])
        elif command == "flush_row_updates":
            for row_id, values in self._take_pending_row_updates():
                row = self.row_widgets.get(row_id)
                if not row:
                    continue
                for key in ("name", "status", "statistics"):
                    if key in values:
                        row[key] = values[key]
                dpg.set_value(row["title"], "{}: {}".format(row["operation"], row["name"]))
                dpg.set_value(row["stats"], "{} | {}".format(row["status"], row["statistics"]))
                if "ratio" in values:
                    dpg.set_value(row["progress"], values["ratio"])
                    dpg.configure_item(row["progress"], overlay="{:.1f}%".format(values["ratio"]*100))
                if "action" in values:
                    wrapper = self._control_wrappers.get(row["action"])
                    if wrapper is not None:
                        wrapper.setText(values["action"])
                    else:
                        dpg.configure_item(row["action"], label=values["action"])
                if "action_enabled" in values:
                    self.set_control_enabled(row["action"], bool(values["action_enabled"]))

    def destroy(self):
        self.cancel_all(update_ui=False)
        QtDialog.destroy(self)


__all__ = ["TransferCenterDialog", "TransferTaskHandle"]
