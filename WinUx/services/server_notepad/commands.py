"""Server Notepad keyboard adapters and parent-process command dispatch."""
from __future__ import annotations


class ServerNotepadCommandMixin:
    """Keep event adapters and external command routing out of the Tk bootstrap.

    The mixin deliberately contains no widget construction or document storage.
    It translates keyboard/IPC events into the existing view operations so the
    established command surface and return values remain unchanged.
    """

    # ------------------------------------------------------------------
    # Keyboard shortcut adapters
    # ------------------------------------------------------------------
    def _shortcut_open(self, _event=None):
        self._open_server_path()
        return "break"

    def _shortcut_toggle_bookmark(self, _event=None):
        self._toggle_bookmark()
        return "break"

    def _shortcut_next_bookmark(self, _event=None):
        self._goto_bookmark(1)
        return "break"

    def _shortcut_previous_bookmark(self, _event=None):
        self._goto_bookmark(-1)
        return "break"

    def _shortcut_duplicate_line(self, _event=None):
        self._duplicate_current_line()
        return "break"

    def _shortcut_delete_line(self, _event=None):
        self._delete_current_line()
        return "break"

    def _shortcut_save(self, _event=None):
        self._save_active()
        return "break"

    def _shortcut_save_all(self, _event=None):
        self._save_all()
        return "break"

    def _shortcut_find(self, _event=None):
        self._show_find_replace(False)
        return "break"

    def _shortcut_replace(self, _event=None):
        self._show_find_replace(True)
        return "break"

    def _shortcut_goto(self, _event=None):
        self._goto_line()
        return "break"

    def _shortcut_reload(self, _event=None):
        self._reload_active()
        return "break"

    def _shortcut_close_tab(self, _event=None):
        self._close_active_tab()
        return "break"

    def _shortcut_find_next(self, _event=None):
        self._find_next(True)
        return "break"

    def _shortcut_find_previous(self, _event=None):
        self._find_next(False)
        return "break"

    def _shortcut_zoom_in(self, _event=None):
        self._zoom_in()
        return "break"

    def _shortcut_zoom_out(self, _event=None):
        self._zoom_out()
        return "break"

    def _shortcut_zoom_reset(self, _event=None):
        self._zoom_reset()
        return "break"

    def _shortcut_next_tab(self, _event=None):
        self._switch_tab(1)
        return "break"

    def _shortcut_previous_tab(self, _event=None):
        self._switch_tab(-1)
        return "break"

    # ------------------------------------------------------------------
    # Parent-process command dispatch
    # ------------------------------------------------------------------
    def handle_command(self, command, *args, **kwargs):
        del kwargs
        if command in ("show", "activate", "focus"):
            self._activate_native_window(center=False)
            doc = self._active_doc()
            if doc is not None and doc.loaded:
                doc.text.focus_set()
            return
        if command == "hide":
            self.withdraw()
            return
        if command == "queue_open":
            self._queue_open_ui(*args)
            return
        if command in ("open_snapshot", "load_succeeded"):
            self._load_succeeded_ui(*args)
            return
        if command == "save_succeeded":
            self._save_succeeded_ui(*args)
            return
        if command == "save_conflict":
            self._save_conflict_ui(*args)
            return
        if command == "operation_failed":
            self._operation_failed_ui(*args)
            return
        if command == "reload_succeeded":
            self._reload_succeeded_ui(*args)
            return
        if command in ("request_close", "close"):
            self._close_window_ui()
