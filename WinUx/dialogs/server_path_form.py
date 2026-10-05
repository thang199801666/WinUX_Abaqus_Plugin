from __future__ import annotations

import threading
import dearpygui.dearpygui as dpg
from .qt_dialog import QtDialog
from ..widgets import QtListView


class ServerPathDialog(QtDialog):
    SEARCH_DELAY_MS = 120

    def __init__(self, view, initial, suggestion_provider, on_selected=None, task_submitter=None):
        self.suggestion_provider = suggestion_provider
        self.on_selected = on_selected
        self.task_submitter = task_submitter
        self._generation = 0
        self._finished = False
        super().__init__(view, "Server Folder", 520, 340)
        self.preferred_size = (510, 315)
        self.header("Choose server folder", "Enter a remote path or choose a matching folder.")
        form = self.form_layout(parent=self.content, label_width=88)
        self.entry = self.form_layout_row(
            form, "Remote path",
            lambda parent: self.line_edit(
                initial or "/", parent=parent,
                callback=lambda: self._schedule_search()),
        )
        self.listbox = self.own_widget(QtListView(
            self.content, [], width=-1, visible_rows=8,
            after=self.view.after, backend=dpg))
        self.listbox.currentTextChanged.connect(self._selected)
        self.listbox.activated.connect(lambda key: self.finish(str(key)))
        self.status = self.status_text()
        self.button_box([("Open", self._open_typed, "primary", True),
                         ("Cancel", lambda: self.finish(None), "secondary", False)])
        dpg.focus_item(self.entry)
        self._schedule_search(immediate=True)

    def _selected(self, value):
        if not value:
            return
        dpg.set_value(self.entry, str(value))
        self._schedule_search()

    def _schedule_search(self, immediate=False):
        self._generation += 1
        generation = self._generation
        self.view.after(0 if immediate else self.SEARCH_DELAY_MS,
                        self._start_search, generation)

    def _start_search(self, generation):
        if not self.winfo_exists() or generation != self._generation:
            return
        value = dpg.get_value(self.entry).strip()
        dpg.set_value(self.status, "Searching...")
        self.request_search(generation, value)

    def request_search(self, generation, value):
        def worker():
            try:
                values, error = [str(item) for item in (self.suggestion_provider(value) or [])], None
            except Exception as exc:
                values, error = [], str(exc)
            self.post("results", generation, value, values, error)
        if callable(self.task_submitter):
            self.task_submitter("server-path-search", worker,
                key="server-path-search:{}".format(id(self)), replace=True)
        else:
            threading.Thread(target=worker, name="winux-server-path-search", daemon=True).start()

    def handle_command(self, command, generation, value, values, error):
        if command == "results" and generation == self._generation:
            self.listbox.setItems(values)
            dpg.set_value(self.status, str(error) if error else "{} matching folder(s)".format(len(values)))

    def _open_typed(self):
        self.finish(dpg.get_value(self.entry).strip() or None)

    def finish(self, value):
        if self._finished:
            return
        self._finished = True
        self._generation += 1
        try:
            if value and callable(self.on_selected):
                self.on_selected(str(value))
        finally:
            self.destroy()

    def wait(self):
        return None
