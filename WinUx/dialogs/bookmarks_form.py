from __future__ import annotations

import dearpygui.dearpygui as dpg
from .qt_dialog import QtDialog, QtTable
from .blocking_form import BlockingDialog


class BookmarksDialog(QtDialog):
    def __init__(self, view, entries, on_open, on_remove, on_rename, rename_prompt=None):
        self._rename_prompt = rename_prompt
        self._entries = []
        self._on_open, self._on_remove, self._on_rename = on_open, on_remove, on_rename
        super().__init__(view, "Bookmarks", 670, 360, modal=False)
        self.preferred_size = (640, 145 + 21 * max(1, min(10, len(entries or []))))
        self.header("Navigation bookmarks", "Saved Local and Server folders. Double-click to open.")
        self.table = QtTable(self.content, ("Location", "Name", "Path"), height=-30,
                             on_activate=lambda key: self._open_selected())
        self.status = self.status_text()
        self.button_box([("Rename", self._rename_selected, "secondary", False),
                         ("Remove", self._remove_selected, "danger", False),
                         ("Open", self._open_selected, "primary", True),
                         ("Close", self.destroy, "secondary", False)])
        self.refresh(entries)
        self.shortcuts[(dpg.mvKey_F2, False)] = self._rename_selected
        self.shortcuts[(dpg.mvKey_Delete, False)] = self._remove_selected

    @staticmethod
    def _entry_key(entry):
        return (str(entry.get("panel_id") or ""), str(entry.get("path") or ""))

    def refresh(self, entries):
        self._entries = [dict(entry) for entry in entries or []]
        self.table.set_rows([(self._entry_key(entry), (
            "Server" if entry.get("panel_id") == "server" else "Local",
            entry.get("label") or "", entry.get("path") or "")) for entry in self._entries])
        if not self.table.selected and self._entries:
            key = self._entry_key(self._entries[0])
            self.table.selected.add(key)
            dpg.set_value(self.table.items[key], True)
        dpg.set_value(self.status, "{} bookmark(s)".format(len(self._entries)))

    def _selected_entry(self):
        return next((dict(entry) for entry in self._entries
                     if self._entry_key(entry) in self.table.selected), None)

    def request_open(self, entry):
        self.view.after(0, self._on_open, dict(entry))

    def request_remove(self, entry):
        self.view.after(0, self._on_remove, dict(entry))

    def request_rename(self, entry, label):
        self.view.after(0, self._on_rename, dict(entry), str(label))

    def _open_selected(self):
        entry = self._selected_entry()
        if entry:
            self.request_open(entry)

    def _remove_selected(self):
        entry = self._selected_entry()
        if entry:
            self.request_remove(entry)

    def _rename_selected(self):
        entry = self._selected_entry()
        if entry:
            if callable(self._rename_prompt):
                self._rename_prompt(entry)
                return
            def renamed(value):
                if self.winfo_exists() and value and value.strip():
                    self.request_rename(entry, value.strip())
            self.own_dialog(BlockingDialog(self.view, "Rename Bookmark", "Bookmark name:",
                kind="input", initial=entry.get("label") or "", primary_text="Save", on_result=renamed))

    def handle_command(self, command, *args):
        if command == "refresh":
            self.refresh(*args)
        elif command == "status":
            dpg.set_value(self.status, str(args[0]))
