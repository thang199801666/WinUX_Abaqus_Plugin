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
            # New runtimes begin the move locally as soon as the HWND is
            # revealed.  Keep this idempotent parent-side fallback for an older
            # or recycled runtime, and pass the anchor so a late start still
            # snaps the grabbed title point back under the cursor.
            self.post("begin_dock_move", self._drag_anchor)

    def _dock_target(self, screen_position):
        from ..platform.native_dock_gesture import (
            client_position, screen_point_in_client)
        from ..platform.dialog_focus import window_state
        if (not all(window_state(self._owner_hwnd))
                or getattr(self.view, "_floating_focus_suppressed", False)):
            return None

        # A native tear-off is observed in *desktop* coordinates.  Never mix in
        # QCursor.localPos(), transformed screen candidates, or the previous DPG
        # mouse position here.  Those values can remain frozen over the old dock
        # while USER32 owns the floating-window move loop, which used to leave a
        # blue preview visible and dock the widget even with the real cursor far
        # outside WinUx.
        if not screen_point_in_client(self._owner_hwnd, screen_position):
            return None
        point = client_position(self._owner_hwnd, screen_position)
        if point is None:
            return None
        try:
            point = (float(point[0]), float(point[1]))
        except Exception:
            return None

        # DPG builds differ in whether viewport-front draw geometry is exposed
        # as owner-client coordinates or viewport-global/screen coordinates.
        # Both candidates below come directly from USER32 for the *same* live
        # cursor sample; unlike QCursor.localPos() neither can go stale while the
        # floating HWND owns the native move loop.  The strict client-rectangle
        # gate above prevents the old false-positive docking outside WinUx.
        screen_point = (float(screen_position[0]), float(screen_position[1]))
        candidates = (point, screen_point)
        previous = getattr(self.view, "_native_dock_pointer_candidates", None)
        self.view._native_dock_pointer_candidates = candidates
        try:
            if self._dock_kind == "console":
                return getattr(
                    self.view, "_console_dock_target_at_pointer", lambda: None)()
            return getattr(
                self.view, "_plot_dock_target_at_pointer", lambda: None)()
        finally:
            self.view._native_dock_pointer_candidates = previous

    def _dock_pointer_inside_site(self, screen_position):
        """Hit-test the dock workspace in the same owner-client space as guides."""
        from ..platform.native_dock_gesture import (
            client_position, screen_point_in_client)
        if not screen_point_in_client(self._owner_hwnd, screen_position):
            return False
        point = client_position(self._owner_hwnd, screen_position)
        if point is None:
            return False
        try:
            point = (float(point[0]), float(point[1]))
        except Exception:
            return False
        screen_point = (float(screen_position[0]), float(screen_position[1]))
        previous = getattr(self.view, "_native_dock_pointer_candidates", None)
        self.view._native_dock_pointer_candidates = (point, screen_point)
        try:
            checker = getattr(self.view, "_dock_pointer_inside_site", None)
            return bool(checker()) if callable(checker) else False
        finally:
            self.view._native_dock_pointer_candidates = previous

    def _hide_native_preview(self):
        # Clear both the visual overlay and the semantic target.  Keeping the
        # previous target alive after the pointer exits the preview is dangerous:
        # a subsequent mouse-up can otherwise dock against stale state.
        self._native_preview_active = False
        self._native_preview_target = None
        getattr(self.view, "_hide_dock_drop_preview", lambda: None)()

    def _poll_dock_preview(self):
        from ..platform.native_dock_gesture import gesture_mode, cursor_position
        if not self.winfo_exists():
            self._hide_native_preview()
            return

        # HWND move state is the authoritative signal.  Do not require the
        # floating window to be the foreground HWND: drag-through reveal uses
        # SW_SHOWNOACTIVATE and SetForegroundWindow is advisory on Windows, so
        # the OS can legitimately move the window while foreground ownership
        # remains with WinUx.  The old foreground gate made live drop feedback
        # silently disappear in exactly that case.
        moving = bool(self._ready and gesture_mode(self._hwnd) == 1)
        if moving:
            prepare = getattr(self.view, "_ensure_dock_drop_preview", None)
            if callable(prepare):
                prepare()
            screen_position = cursor_position()
            target = self._dock_target(screen_position)
            # Once native title-bar movement starts, keep the four-way guide
            # visible at the center of WinUx for the entire gesture.  A large
            # result preview appears only while the pointer is actually inside
            # one guide; target=None therefore means guides-only, not hidden.
            self._native_preview_active = True
            self._native_preview_target = target
            if self._dock_kind == "console":
                self.view._set_console_dock_preview(True, target)
            else:
                self.view._set_plot_dock_preview(True, target)
        else:
            self._hide_native_preview()
        # One poll per ~60 Hz frame keeps the preview visually attached to the
        # cursor without adding renderer work when no native move is active.
        self.view.after(16, self._poll_dock_preview)

    def _handle_dock_gesture(self, message):
        from ..platform.dialog_focus import foreground_hwnd, window_state
        self._hide_native_preview()
        foreground = foreground_hwnd()
        self._last_native_dock_gesture = {
            "action": message.get("action"), "position": message.get("position"),
            "foreground": foreground,
        }
        # The gesture event is emitted by this host's own native WNDPROC after
        # the USER32 move loop returns.  Requiring foreground ownership here is
        # both redundant and incorrect for SW_SHOWNOACTIVATE drag-through
        # windows; Windows may leave the owner as foreground throughout a valid
        # move.  Validate the live host and owner instead.
        if (not self._ready or not self.winfo_exists()
                or not all(window_state(self._owner_hwnd))
                or getattr(self.view, "_floating_focus_suppressed", False)):
            return
        action = message.get("action")
        target = None
        if action == "drop":
            # Re-hit-test against the cursor *now*.  The event position crosses
            # a process/IPC boundary and may be one move message old; cached
            # preview state is never sufficient evidence to dock.
            try:
                from ..platform.native_dock_gesture import cursor_position
                position = cursor_position()
            except Exception:
                position = None
            target = self._dock_target(position)
        if action == "toggle" or (action == "drop" and target is not None):
            self._requested_dock_area = target
            self._requested_dock_scope = (
                getattr(self.view, "_dock_preview_scope", None)
                if action == "drop" else None)
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
    def __init__(self, view, panel, on_dock, on_closed, *, drag_anchor=None, visible=True):
        from .native_dock_forms import console_editor_state
        self.panel, self.on_dock, self.on_closed = panel, on_dock, on_closed
        self._drag_anchor = drag_anchor
        self.output_callback, self.command_callback = panel.output_callback, panel.command_callback
        self.interrupt_callback, self.error_callback = panel.interrupt_callback, panel.error_callback
        self.completion_callback = getattr(panel, "completion_callback", None)
        self.completion_list_callback = getattr(panel, "completion_list_callback", None)
        self.raw_output_callback = getattr(panel, "raw_output_callback", None)
        self.raw_input_callback = getattr(panel, "raw_input_callback", None)
        self.resize_callback = getattr(panel, "resize_callback", None)
        self.refresh_callback = getattr(panel, 'refresh_callback', None)
        output = str(self.output_callback() or "")
        raw_output = (self.raw_output_callback() or "") if callable(self.raw_output_callback) else ""
        self._last_output = output
        self._last_raw_output = raw_output
        FloatingDialogController.__init__(self, view, "console_dock", "SSH Console",
            {"output": output, "raw_output": raw_output, "editor": console_editor_state(panel),
             "_dock_drag_anchor": drag_anchor}, width=760, height=440,
            modal=False, resizable=True, visible=visible, fresh_host=False, fast_publish=True)
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
    def __init__(self, view, panel, on_dock, on_closed, *, drag_anchor=None,
                 visible=True, saved_geometry=None):
        self.panel, self.on_dock, self.on_closed = panel, on_dock, on_closed
        self._drag_anchor = drag_anchor
        self._revision = panel._native_revision
        payload = {"job_id": panel.job_id, "job_name": panel.job_name,
                   "title": panel.label, "snapshot": panel.native_snapshot(),
                   "_dock_drag_anchor": drag_anchor}
        if isinstance(saved_geometry, dict) and saved_geometry:
            payload["_saved_geometry"] = dict(saved_geometry)
        super().__init__(view, "plot_dock", panel.label, payload,
            width=900, height=500, modal=False, resizable=True, visible=visible,
            fresh_host=False, fast_publish=True)
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
        elif event == 'palette':
            self.panel.set_palette(message.get('palette', 'default'))
        elif event == "reference_manage":
            self.panel._manage_references()
        elif event == "dock_requested":
            self.on_dock(self)
