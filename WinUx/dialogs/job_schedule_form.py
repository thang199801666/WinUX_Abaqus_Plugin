from __future__ import annotations

import dearpygui.dearpygui as dpg
from .qt_dialog import QtDialog
from .theme import DialogMetrics


class JobScheduleDialog(QtDialog):
    def __init__(self, view, schedule_provider, schedule_command):
        self.schedule_provider, self.schedule_command = schedule_provider, schedule_command
        self._snapshot = None
        self._row_items = []
        super().__init__(view, "Job Schedule", 840, 400)
        self.header("Job schedule", "Review pending and recent scheduled actions.")
        with dpg.table(parent=self.content, header_row=True, scrollY=True, height=-30,
                       width=-1, resizable=True, row_background=True, freeze_rows=1,
                       borders_innerH=True, borders_outerH=True,
                       borders_innerV=True, borders_outerV=True,
                       policy=dpg.mvTable_SizingStretchProp) as self.table:
            columns = (("Job", None), ("Action", 92), ("Scheduled time", 164),
                       ("Remaining", 94), ("Status", 96), ("Commands", 152))
            for label, width in columns:
                if width is None:
                    dpg.add_table_column(label=label, width_stretch=True, init_width_or_weight=1)
                else:
                    dpg.add_table_column(label=label, width_fixed=True, init_width_or_weight=width)
            self.style_table(self.table)
        self.status = self.status_text("Updates automatically")
        self.button_box([("Refresh", self.refresh, "secondary", False),
                         ("Close", self.destroy, "secondary", False)])
        self._tick()

    def _tick(self):
        if self.winfo_exists():
            self.refresh()
            self.view.after(1000, self._tick)

    def refresh(self):
        if self.winfo_exists():
            self.set_rows([tuple(row) for row in (self.schedule_provider() or [])])

    def set_rows(self, rows):
        rows = [tuple(row) for row in rows]
        identities = [(str(row[5]), str(row[6])) for row in rows]
        previous = [] if self._snapshot is None else [(str(row[5]), str(row[6])) for row in self._snapshot]
        if identities != previous:
            for item in dpg.get_item_children(self.table, 1) or []:
                self.delete_owned_item(item)
            self._row_items = []
            for row in rows:
                with dpg.table_row(parent=self.table):
                    cells = [dpg.add_text(str(value)) for value in row[:5]]
                    kind, key = str(row[5]), str(row[6])
                    with dpg.group(horizontal=True, horizontal_spacing=DialogMetrics.BUTTON_GAP) as command_group:
                        edit = self.action(
                            "Edit", lambda kind=kind, key=key: self.request_action("edit", kind, key),
                            "secondary", parent=command_group, width=64,
                        )
                        cancel = self.action(
                            "Cancel", lambda kind=kind, key=key: self.request_action("cancel", kind, key),
                            "danger", parent=command_group, width=72,
                        )
                    self._row_items.append((cells, edit, cancel))
        rebuilt = identities != previous
        for index, (row, (cells, edit, cancel)) in enumerate(zip(rows, self._row_items)):
            old_row = None if rebuilt else self._snapshot[index]
            for column, (cell, value) in enumerate(zip(cells, row[:5])):
                text = str(value)
                if old_row is not None and str(old_row[column]) != text:
                    dpg.set_value(cell, text)
            waiting = str(row[4]).casefold() == "waiting"
            if old_row is None or (str(old_row[4]).casefold() == "waiting") != waiting:
                dpg.configure_item(edit, enabled=waiting)
                dpg.configure_item(cancel, enabled=waiting)
        self._snapshot = rows
        if rebuilt or not previous:
            text = "{} scheduled action(s) | Updates automatically".format(len(rows))
            if dpg.get_value(self.status) != text:
                dpg.set_value(self.status, text)

    def request_refresh(self):
        self.view.after(0, self.refresh)

    def request_action(self, action, kind, key):
        self.view.after(0, self.schedule_command, str(action), str(kind), str(key))

    def handle_command(self, command, *args):
        if command == "set_rows":
            self.set_rows(*args)
