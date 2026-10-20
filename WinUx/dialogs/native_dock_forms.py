"""Native dock clients. Application/SSH/ODB work stays in the main process."""
from .console_form import ConsoleDialog
from DearUIQt import QtDialog
from ..ui.components.job_plots import JobPlotsWindow


def console_editor_state(panel):
    buffer = panel.buffer
    return {"draft": buffer.draft, "cursor": buffer.cursor,
            "history": list(buffer.history), "history_index": buffer.history_index,
            "saved_draft": buffer._saved_draft,
            "clear_base": panel._clear_base, "clear_prompt": panel._clear_prompt}


def restore_console_editor(panel, state):
    buffer = panel.buffer
    buffer.draft = str(state.get("draft", ""))
    buffer.cursor = max(0, min(len(buffer.draft), int(state.get("cursor", 0))))
    buffer.history = [str(value) for value in state.get("history", [])]
    buffer.history_index = max(0, min(len(buffer.history), int(state.get("history_index", len(buffer.history)))))
    buffer._saved_draft = str(state.get("saved_draft", ""))
    panel._clear_base = state.get("clear_base")
    panel._clear_prompt = str(state.get("clear_prompt", ""))
    panel._last_output = None
    panel._last_paint = None


class ConsoleDockForm(ConsoleDialog):
    def __init__(self, view, payload, emit):
        self._emit = emit
        self._output_state = str(payload.get("output", ""))
        self._completion_waiters = {}
        self._completion_counter = 0

        def request_completion(draft, cursor, done):
            self._completion_counter += 1
            request_id = self._completion_counter
            self._completion_waiters[request_id] = done
            emit("complete", request_id=request_id, draft=draft, cursor=int(cursor))
            return True

        def show_completion_list(draft, candidates, columns=80):
            emit("completion_list", draft=str(draft), candidates=list(candidates),
                 columns=int(columns))
            return True

        super().__init__(view, lambda: self._output_state,
                         lambda command: emit("command", value=command),
                         lambda: emit("interrupt"),
                         completion_callback=request_completion,
                         completion_list_callback=show_completion_list)
        restore_console_editor(self, payload.get("editor", {}))
        self._set_output(self._output_state)
        self._last_editor_state = None
        self.create_timer(100, self._sync_editor)

    def _sync_editor(self):
        state = console_editor_state(self)
        if state != self._last_editor_state:
            self._last_editor_state = state
            self._emit("editor", state=state)

    def request_dock(self):
        self._emit("dock_requested", state=console_editor_state(self))

    def handle_command(self, command, *args):
        if command == "request_dock":
            self.request_dock()
        elif command == "output":
            self._output_state = str(args[0])
            super().handle_command(command, *args)
        elif command == "completion_result":
            request_id, result = int(args[0]), args[1]
            callback = self._completion_waiters.pop(request_id, None)
            if callable(callback):
                callback(result)
        else:
            super().handle_command(command, *args)

    def destroy(self):
        if self.winfo_exists():
            self._sync_editor()
        super().destroy()


class _RemoteReferences:
    def __init__(self, emit):
        self.items = []
        self._emit = emit
        self.listeners = []

    def snapshot(self):
        return self.items

    def subscribe(self, callback):
        self.listeners.append(callback)

    def unsubscribe(self, callback):
        if callback in self.listeners:
            self.listeners.remove(callback)

    def set_enabled(self, series_id, enabled):
        self._emit("reference_enabled", series_id=series_id, enabled=bool(enabled))


class PlotDockForm(QtDialog):
    def __init__(self, view, payload, emit):
        super().__init__(view, payload.get("title", "Job Plots"), 900, 500, modal=False, footer=False)
        self.preferred_size = (900, 500)
        self._emit = emit
        self.references = _RemoteReferences(emit)
        self.panel = JobPlotsWindow(
            self.content, payload.get("job_id", ""), payload.get("job_name", ""),
            on_selection_change=lambda job, rows: emit("selection", ids=sorted(self.panel.selected_ids)),
            reference_library=self.references,
            on_reference_manage=lambda: emit("reference_manage"), after=view.after)
        self.panel.set_dock_mode("floating")
        self._catalog_snapshot = None
        self.apply_snapshot(payload.get("snapshot", {}))
        self.create_timer(33, self.panel.sync_layout)

    def apply_snapshot(self, snapshot):
        panel = self.panel
        rows = snapshot.get("catalog", [])
        # Applying a snapshot must not echo a selection command to the parent.
        callback, panel.on_selection_change = panel.on_selection_change, None
        try:
            self.references.items = snapshot.get("references", [])
            if rows != self._catalog_snapshot:
                panel.set_catalog({"historyOutputs": rows})
                self._catalog_snapshot = rows
            panel.set_selected_ids(snapshot.get("selected", []), notify=False)
            panel._sync_formula_dependencies(notify=False)
            panel.update_frame({"series": snapshot.get("series", [])})
            panel._refresh_references(sync_dependencies=False)
            panel.set_status(snapshot.get("status", "Waiting for ODB..."))
        finally:
            panel.on_selection_change = callback
        self._emit("plot_state", selected_count=len(panel.selected_ids),
                   point_count=sum(len(points) for points in panel._series_points.values()))

    def handle_command(self, command, *args):
        if command == "snapshot":
            self.apply_snapshot(args[0])
        elif command == "request_dock":
            self._emit("dock_requested")

    def _finalize_visual_destroy(self):
        # Keep the last chart frame intact until the runtime hides its HWND.
        self.panel.close()
        super()._finalize_visual_destroy()
