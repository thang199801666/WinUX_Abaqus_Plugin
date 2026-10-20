"""Modeless native hosts for detached docks; no application work in children."""
from ..ui import FloatingDialogController
from .floating_adapters import ConsoleDialog


class _DockClose:
    def _failed(self, message, details="", stage=""):
        # During tear-off the embedded dock is intentionally kept painted until
        # first-present. A startup IPC failure therefore has a complete visual
        # fallback already on screen; logging + retiring the failed host is
        # preferable to interrupting the user with a modal error popup.
        if not getattr(self, "_ready", False):
            try:
                self._append_failure_log(message, details, stage)
                from ..diagnostics import log_event
                log_event("Dock host startup failed title={}: {}".format(
                    getattr(self, "title", type(self).__name__), message))
            except Exception:
                pass
            self._reuse_host = False
            self.destroy()
            return
        super()._failed(message, details=details, stage=stage)

    def _deliver_event(self, message):
        was_ready = self._ready
        super()._deliver_event(message)
        if (not was_ready and self._ready and self.winfo_exists()
                and getattr(self, "_drag_anchor", None) is not None):
            self.post("begin_dock_move")

    def _dock_target(self, screen_position):
        from ..platform.native_dock_gesture import client_position
        from ..platform.dialog_focus import window_state
        if (not all(window_state(self._owner_hwnd))
                or getattr(self.view, "_floating_focus_suppressed", False)):
            return None
        point = client_position(self._owner_hwnd, screen_position)
        if point is None:
            return None
        previous = getattr(self.view, "_native_dock_pointer_candidates", None)
        self.view._native_dock_pointer_candidates = (point,)
        try:
            if self._dock_kind == "console":
                target = getattr(self.view, "_console_dock_target_at_pointer", lambda: False)()
                return "bottom" if target else None
            return getattr(self.view, "_plot_dock_target_at_pointer", lambda: None)()
        finally:
            self.view._native_dock_pointer_candidates = previous

    def _hide_native_preview(self):
        if getattr(self, "_native_preview_active", False):
            self._native_preview_active = False
            getattr(self.view, "_hide_dock_drop_preview", lambda: None)()

    def _poll_dock_preview(self):
        from ..platform.native_dock_gesture import gesture_mode, cursor_position
        from ..platform.dialog_focus import foreground_hwnd
        if not self.winfo_exists():
            self._hide_native_preview()
            return
        if self._ready and gesture_mode(self._hwnd) == 1 and foreground_hwnd() == self._hwnd:
            target = self._dock_target(cursor_position())
            if target is not None:
                self._native_preview_active = True
                if self._dock_kind == "console":
                    self.view._set_console_dock_preview(True)
                else:
                    self.view._set_plot_dock_preview(True, target)
            else:
                self._hide_native_preview()
        else:
            self._hide_native_preview()
        self.view.after(25, self._poll_dock_preview)

    def _handle_dock_gesture(self, message):
        from ..platform.dialog_focus import foreground_hwnd, window_state
        self._hide_native_preview()
        foreground = foreground_hwnd()
        self._last_native_dock_gesture = {
            "action": message.get("action"), "position": message.get("position"),
            "foreground": foreground,
        }
        if (not self._ready or not self.winfo_exists()
                or foreground != self._hwnd
                or not all(window_state(self._owner_hwnd))
                or getattr(self.view, "_floating_focus_suppressed", False)):
            return
        action = message.get("action")
        target = self._dock_target(message.get("position")) if action == "drop" else None
        if action == "toggle" or (action == "drop" and target is not None):
            self._requested_dock_area = target
            # Console's client sends its final editor state before reattaching.
            # Use the same handshake for title double-click and pointer drop.
            self.post("request_dock")

    def _close_completed(self):
        self._hide_native_preview()
        if not getattr(self, "_dock_completion_sent", False):
            self._dock_completion_sent = True
            self.on_closed(self)


class ConsoleDockHost(_DockClose, ConsoleDialog):
    _dock_kind = "console"
    def __init__(self, view, panel, on_dock, on_closed, *, drag_anchor=None):
        from .native_dock_forms import console_editor_state
        self.panel, self.on_dock, self.on_closed = panel, on_dock, on_closed
        self._drag_anchor = drag_anchor
        self.output_callback, self.command_callback = panel.output_callback, panel.command_callback
        self.interrupt_callback, self.error_callback = panel.interrupt_callback, panel.error_callback
        self.completion_callback = getattr(panel, "completion_callback", None)
        self.completion_list_callback = getattr(panel, "completion_list_callback", None)
        output = str(self.output_callback() or "")
        self._last_output = output
        FloatingDialogController.__init__(self, view, "console_dock", "SSH Console",
            {"output": output, "editor": console_editor_state(panel),
             "_dock_drag_anchor": drag_anchor}, width=760, height=440,
            modal=False, resizable=True, fresh_host=True)
        view.after(0, self._poll_output)
        view.after(25, self._poll_dock_preview)

    def handle_event(self, event, message):
        if event == "dock_gesture":
            self._handle_dock_gesture(message)
        elif event in ("editor", "dock_requested"):
            from .native_dock_forms import restore_console_editor
            restore_console_editor(self.panel, message.get("state", {}))
            if event == "dock_requested":
                self.on_dock(self)
        else:
            super().handle_event(event, message)


class PlotDockHost(_DockClose, FloatingDialogController):
    _dock_kind = "plot"
    def __init__(self, view, panel, on_dock, on_closed, *, drag_anchor=None):
        self.panel, self.on_dock, self.on_closed = panel, on_dock, on_closed
        self._drag_anchor = drag_anchor
        self._revision = panel._native_revision
        super().__init__(view, "plot_dock", panel.label,
            {"job_id": panel.job_id, "job_name": panel.job_name,
             "title": panel.label, "snapshot": panel.native_snapshot(), "_dock_drag_anchor": drag_anchor},
            width=900, height=500, modal=False, resizable=True, fresh_host=True)
        view.after(100, self._poll_snapshot)
        view.after(25, self._poll_dock_preview)

    def _poll_snapshot(self):
        if not self.winfo_exists() or not self.panel.exists():
            return
        revision = self.panel._native_revision
        if revision != self._revision:
            self._revision = revision
            self.post_latest("snapshot", self.panel.native_snapshot())
        self.view.after(100, self._poll_snapshot)

    def handle_event(self, event, message):
        if event == "dock_gesture":
            self._handle_dock_gesture(message)
        elif event == "plot_state":
            self._rendered_plot_state = (int(message.get("selected_count", 0)),
                                         int(message.get("point_count", 0)))
        elif event == "selection":
            self.panel.set_selected_ids(message.get("ids", []))
        elif event == "reference_enabled":
            self.panel._set_reference_enabled(message["series_id"], message["enabled"])
        elif event == "reference_manage":
            self.panel._manage_references()
        elif event == "dock_requested":
            self.on_dock(self)
