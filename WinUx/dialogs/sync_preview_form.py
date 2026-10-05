from __future__ import annotations

import dearpygui.dearpygui as dpg
from .qt_dialog import QtDialog, QtTable


class SyncPreviewDialog(QtDialog):
    def __init__(self, view, rows, local_path, server_path, on_refresh, on_transfer):
        self._rows = []
        self._on_refresh, self._on_transfer = on_refresh, on_transfer
        super().__init__(view, "Directory Synchronization Preview", 820, 470, modal=False)
        self.header("Directory synchronization", "Review differences before starting a transfer.")
        paths_form = self.form_layout(parent=self.content, label_width=54)
        self.local_path = self.form_layout_row(
            paths_form, "Local", lambda parent: dpg.add_text("", parent=parent, wrap=690))
        self.server_path = self.form_layout_row(
            paths_form, "Server", lambda parent: dpg.add_text("", parent=parent, wrap=690))
        self.table = QtTable(self.content, (
            {"key": "name", "label": "Name", "stretch": 2.2, "sortable": False},
            {"key": "status", "label": "Status", "width": 112, "sortable": False},
            {"key": "local", "label": "Local", "width": 88, "sortable": False},
            {"key": "server", "label": "Server", "width": 88, "sortable": False},
            {"key": "action", "label": "Recommended action", "width": 156, "sortable": False},
        ), height=-30, multiple=True)
        self.status = self.status_text()
        self.button_box([("Refresh", self.request_refresh, "secondary", False),
                         ("Transfer", self._transfer_selected, "primary", True),
                         ("Close", self.destroy, "secondary", False)],
                        status_item=self.status)
        self.refresh(rows, local_path, server_path)

    @staticmethod
    def _size_text(value, exists=True):
        if not exists:
            return "-"
        size = float(value or 0)
        for unit in ("B", "KB", "MB", "GB", "TB"):
            if size < 1024 or unit == "TB":
                return ("{:.0f} {}" if unit == "B" else "{:.1f} {}").format(size, unit)
            size /= 1024

    def refresh(self, rows, local_path, server_path):
        # Refresh may reorder differences; index-based selections must never
        # silently apply to a different file after a new scan.
        self.table.selected.clear()
        self._rows = [dict(row) for row in rows or []]
        dpg.set_value(self.local_path, str(local_path))
        dpg.set_value(self.server_path, str(server_path))
        self.table.set_rows([(i, (row.get("name") or "", row.get("status") or "",
            self._size_text(row.get("local_size"), bool(row.get("local_exists"))),
            self._size_text(row.get("server_size"), bool(row.get("server_exists"))),
            row.get("action") or "Review")) for i, row in enumerate(self._rows)])
        self.set_status("{} difference(s) | {} recommended transfer(s)".format(len(self._rows),
            sum(row.get("action") in ("Upload", "Download") for row in self._rows)))

    def set_status(self, text):
        dpg.set_value(self.status, str(text))

    def request_refresh(self):
        self.view.after(0, self._on_refresh)

    def request_transfer(self, rows):
        self.view.after(0, self._on_transfer, list(rows or []))

    def _transfer_selected(self):
        rows = [dict(row) for i, row in enumerate(self._rows) if i in self.table.selected]
        if not rows:
            rows = [dict(row) for row in self._rows if row.get("action") in ("Upload", "Download")]
        if rows:
            self.request_transfer(rows)
        else:
            self.set_status("No recommended transfers are available.")

    def handle_command(self, command, *args):
        if command == "refresh":
            self.refresh(*args)
        elif command == "status":
            self.set_status(*args)
