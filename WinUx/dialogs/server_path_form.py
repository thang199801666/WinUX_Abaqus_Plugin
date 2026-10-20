from __future__ import annotations

from DearUIQt.backends import dpg
from DearUIQt.dialogs.qt_dialog import QtDialog
from DearUIQt.modelview import QtListView


class ServerPathDialog(QtDialog):
    REUSABLE_HOST = True
    SEARCH_DELAY_MS = 120
    DIALOG_SIZE = (560, 300)
    VISIBLE_MATCH_ROWS = 5

    def __init__(self, view, initial, suggestion_provider, on_selected=None, task_submitter=None):
        self.suggestion_provider = suggestion_provider
        self.on_selected = on_selected
        self.task_submitter = task_submitter
        self._generation = 0
        self._finished = False
        super().__init__(view, "Server Folder", *self.DIALOG_SIZE)
        self.preferred_size = self.DIALOG_SIZE
        self.header("Choose server folder", "Enter a remote path or choose a matching folder.")
        form = self.form_layout(parent=self.content, label_width=88)
        self.entry = self.form_layout_row(
            form, "Remote path",
            lambda parent: self.line_edit(
                initial or "/", parent=parent,
                callback=lambda: self._schedule_search()),
        )
        self.listbox = self.own_widget(QtListView(
            self.content, [], width=-1, visible_rows=self.VISIBLE_MATCH_ROWS,
            after=self.view.after, backend=dpg))
        self.listbox.currentTextChanged.connect(self._selected)
        self.listbox.activated.connect(lambda key: self.finish(str(key)))
        # Put asynchronous search feedback in the button-box status slot rather
        # than reserving a dedicated row below the list.  This mirrors Qt's
        # compact file/folder choosers and keeps the list visually connected to
        # the path field even when only one suggestion is returned.
        self.status = self.status_text()
        self.button_box(
            [("Open", self._open_typed, "primary", True),
             ("Cancel", lambda: self.finish(None), "secondary", False)],
            status_item=self.status, status_left_padding=2,
        )
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
        self.set_status_text(self.status, "Searching...", error=False)
        self.request_search(generation, value)

    def request_search(self, generation, value):
        def worker():
            try:
                values, error = [str(item) for item in (self.suggestion_provider(value) or [])], None
            except Exception as exc:
                values, error = [], str(exc)
            return values, error
        if callable(self.task_submitter):
            def submitted_worker():
                values, error = worker()
                self.post("results", generation, value, values, error)
            self.task_submitter("server-path-search", submitted_worker,
                key="server-path-search:{}".format(id(self)), replace=True)
        else:
            self.runAsync(
                worker,
                on_result=lambda outcome: self.handle_command(
                    "results", generation, value, outcome[0], outcome[1]),
            )

    def handle_command(self, command, generation, value, values, error):
        if command == "results" and generation == self._generation:
            self.listbox.setItems(values)
            if error:
                self.set_status_text(self.status, str(error), error=True)
            else:
                count = len(values)
                label = "folder" if count == 1 else "folders"
                self.set_status_text(
                    self.status, "{} matching {}".format(count, label), error=False)

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
