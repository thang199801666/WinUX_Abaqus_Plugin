"""Main viewport lifecycle, frame scheduling and deterministic shutdown."""
from __future__ import annotations

import ctypes as _ctypes_stdlib
import os
import sys
import time
from ctypes import wintypes


def _view_ctypes():
    """Honor historical monkey-patches applied through ``WinUx.view.ctypes``."""
    module = sys.modules.get("WinUx.ui.main_window") or sys.modules.get("WinUx.view")
    return getattr(module, "ctypes", _ctypes_stdlib) if module is not None else _ctypes_stdlib

from DearUIQt.input_gate import native_background_input_blocked, release_pointer_input

from ...components import ExplorerListView, reset_component_runtime_resources
from ....diagnostics import crash_guard, log_event, log_exception
from ....preferences.general import GeneralPreferences
from ....runtime.dpg_callbacks import invoke_callback_job


class ViewLifecycleMixin:
    @crash_guard("Dear PyGui view lifecycle failed")
    def run(self):
        log_event("Dear PyGui viewport startup began")
        try:
            self._gui_runtime.show()
            log_event("Dear PyGui viewport shown")

            # Dear PyGui does not know the final native client/content
            # dimensions until at least one frame has been rendered. Applying
            # the layout before that first frame uses provisional sizes.
            if self._gui_runtime.isRunning():
                self._gui_runtime.renderFrame()
            log_event("Dear PyGui first frame rendered")

            self._pending_viewport_size = None
            self._resize_last_event = 0.0
            self._layout_dirty = True
            self._apply_split_layout(force=True)

            # Commit fitted dimensions before entering normal event processing.
            if self._gui_runtime.isRunning():
                self._gui_runtime.renderFrame()

            log_event("Dear PyGui render loop started")
            # Querying the native context can itself fail if GLFW/DPG was torn
            # down asynchronously by the host. Treat that as an orderly loop
            # termination instead of letting a Python exception escape run().
            while self._alive:
                try:
                    running = bool(self._gui_runtime.isRunning())
                except Exception:
                    log_exception(
                        "Dear PyGui running-state query failed",
                        sys.exc_info(), fatal=False)
                    break
                if not running:
                    break
                self._wait_for_ui_frame()
                self.update()

            reason = (
                "application shutdown was requested"
                if not self._alive
                else "Dear PyGui reported that it was no longer running"
            )
            log_event("Dear PyGui render loop ended: {}".format(reason))
        finally:
            if self._watchdog is not None:
                self._watchdog.close()
            self._dispatcher.close()
            self._destroy_components()
            try:
                if self._gui_runtime.isRunning():
                    self._gui_runtime.stop()
            except Exception:
                log_exception(
                    "Failed to stop Dear PyGui during cleanup",
                    sys.exc_info(),
                    fatal=False,
                )
            try:
                preview = getattr(self, "_dock_drop_preview", None)
                if preview is not None:
                    try:
                        preview.destroy()
                    except Exception:
                        pass
                reset_component_runtime_resources()
            except Exception:
                log_exception(
                    "Failed to reset Dear PyGui component caches",
                    sys.exc_info(),
                    fatal=False,
                )
            try:
                self._gui_runtime.destroy()
                log_event("Dear PyGui context destroyed")
            except Exception:
                log_exception(
                    "Failed to destroy Dear PyGui context",
                    sys.exc_info(),
                    fatal=False,
                )

    def mainloop(self):
        self.run()

    def apply_general_preferences(self, values=None):
        values = self._general_preferences.load() if values is None else values
        self._show_hidden_files = bool(values.get("show_hidden_files", False))
        self._file_colors = bool(values.get('file_colors', GeneralPreferences.DEFAULT_FILE_COLORS))
        self._file_color_rules = values.get('file_color_rules', self._file_color_rules)
        self._preserve_file_timestamps = bool(values.get('preserve_file_timestamps', self._preserve_file_timestamps))
        for panel in self.panels:
            panel.set_show_hidden_files(self._show_hidden_files)
            panel.set_file_colors(self._file_colors, self._file_color_rules)

    def _safe_frame_step(self, name, callback, *args, **kwargs):
        """Run one non-critical per-frame UI step without killing the app.

        Docking, splitters, cursor feedback and retained-list geometry all
        reference items whose lifetime can end between callbacks.  A single
        stale tag should degrade one interaction, not terminate WinUx.  Errors
        are retried on later frames and logged at most once every 15 seconds
        per step to avoid a failing optional visual path flooding the logs.
        """
        default = kwargs.pop("default", None)
        try:
            result = callback(*args, **kwargs)
        except Exception:
            now = time.monotonic()
            state = self._frame_step_errors.get(name)
            last_log = state[0] if state else 0.0
            failures = (state[1] if state else 0) + 1
            if not state or now - last_log >= 15.0:
                log_exception(
                    "Non-fatal UI frame step failed: {}".format(name),
                    sys.exc_info(), fatal=False)
                last_log = now
            self._frame_step_errors[name] = (last_log, failures)
            return default
        else:
            self._frame_step_errors.pop(name, None)
            return result

    def _wake_ui_frame(self):
        """Wake an idle GUI immediately for worker completions, without polling."""
        self._frame_clock.work()
        hwnd = int(getattr(self, '_main_viewport_hwnd', 0) or 0)
        if hwnd:
            from ...native.floating_viewport import wake_native_window
            wake_native_window(hwnd)

    def _wait_for_ui_frame(self):
        from ...native.message_pump import wait_native_messages
        hwnd = self._find_main_viewport_hwnd()
        while self._alive:
            # Timer delivery is independent of painting: blink/status timers
            # must run on time without repainting the entire workspace.
            self._safe_frame_step('idle UI dispatcher drain', self._drain_queue)
            if not self._alive:
                return
            foreground, minimized = True, False
            if hwnd and os.name == 'nt':
                user32 = _view_ctypes().windll.user32
                user32.GetForegroundWindow.restype = wintypes.HWND
                minimized = bool(user32.IsIconic(wintypes.HWND(hwnd)))
                active = int(user32.GetForegroundWindow() or 0)
                if active and active != int(hwnd):
                    pid = wintypes.DWORD()
                    user32.GetWindowThreadProcessId(wintypes.HWND(active), _view_ctypes().byref(pid))
                    foreground = int(pid.value) == os.getpid()
            runtime = getattr(self, '_gui_runtime', None)
            presentation_pending = getattr(runtime, 'hasPendingPresentation', lambda: False)()
            urgent = (self._layout_dirty or self._startup_layout_frames > 0 or
                      bool(self._after_render_callbacks) or self._dispatcher.has_immediate_work() or
                      presentation_pending)
            dragging = any(getattr(panel.listview, '_item_drag_active', False)
                           for panel in getattr(self, 'panels', ()))
            center = getattr(self, 'transfer_center_dialog', None)
            transferring = bool(center is not None and center.isVisible() and center._has_active_tasks())
            delay = self._frame_clock.delay(foreground=foreground, minimized=minimized,
                                           urgent=urgent, dragging=dragging, transferring=transferring)
            if delay <= .001:
                return
            deadline = self._dispatcher.next_deadline_ms()
            if deadline is not None:
                delay = min(delay, deadline / 1000.0)
            if not wait_native_messages(max(1, int(delay * 1000)), on_input=self._frame_clock.input):
                self._alive = False
                return

    def update(self):
        if self._watchdog is not None:
            self._safe_frame_step("watchdog heartbeat", self._watchdog.beat)

        # Native dialogs do not belong to Dear PyGui's item tree. Treat them
        # as a real Qt foreground surface, but do not let a transient native
        # focus/query failure terminate the entire render loop.
        native_input_blocked = bool(self._safe_frame_step(
            "native input gate", native_background_input_blocked,
            default=False))
        if native_input_blocked:
            self._safe_frame_step(
                "cancel splitter interactions", self._cancel_splitter_interactions)
            self._safe_frame_step(
                "release pointer input", release_pointer_input)
            self._safe_frame_step(
                "discard blocked DPG callbacks", self._drain_dpg_callbacks,
                True)
        else:
            # Splitter arbitration must happen before Dear PyGui's global
            # ListView callbacks are drained; otherwise the same physical press
            # can become both a divider resize and a file drag/drop.
            self._safe_frame_step(
                "pre-dispatch splitter input", self._pre_dispatch_splitter_input)
            self._safe_frame_step(
                "DPG callback dispatch", self._drain_dpg_callbacks)
            self._safe_frame_step(
                "file panel splitter input", self._update_file_panel_splitter_input)
        if not self._alive:
            return
        if self._console_native_wndproc_callback is None:
            self._safe_frame_step(
                "console character hook", self._install_console_character_hook)
        self._safe_frame_step("UI dispatcher drain", self._drain_queue)
        if not self._alive:
            return
        if self._startup_layout_frames > 0:
            self._startup_layout_frames -= 1
            self._layout_dirty = True
            self._safe_frame_step(
                "startup split layout", self._apply_split_layout, force=True)
        elif self._layout_dirty:
            self._safe_frame_step("split layout", self._apply_split_layout)
        if not native_input_blocked:
            # QTabBar-like drag/reorder must claim the pointer before splitters
            # or Explorer panes poll global mouse state, otherwise a tab tear-
            # off can simultaneously resize/select widgets underneath it.
            dock_manager = getattr(self, "plot_dock_manager", None)
            if dock_manager is not None:
                self._safe_frame_step(
                    "dock manager interaction", dock_manager.update_interaction)
            # All of these paths are interaction polish around transient DPG
            # items.  A stale tag after close/dock/resize is recoverable on the
            # next frame and must not be fatal to the application.
            for name, callback in (
                ("floating plot resize", self._update_floating_plot_resize_interaction),
                ("floating console resize", self._update_floating_console_resize_interaction),
                ("horizontal splitter input", self._update_horizontal_splitter_input),
                ("job plot splitter input", self._update_job_plot_splitter_input),
                ("console splitter input", self._update_console_splitter_input),
                ("floating plot docking", self._update_floating_plot_docking),
                ("floating console docking", self._update_floating_console_docking),
            ):
                self._safe_frame_step(name, callback)
            # Inline rename focus/selection cannot depend on per-ListView frame
            # callbacks: Dear PyGui provides only one callback slot per frame.
            for index, panel in enumerate(tuple(self.panels)):
                self._safe_frame_step(
                    "inline rename focus {}".format(index),
                    panel.listview._process_inline_rename_focus)
        self._safe_frame_step("job plot window sync", self._sync_job_plot_windows)
        self._safe_frame_step(
            "horizontal panel divider sync", self._sync_horizontal_panel_divider)

        # Rendering itself is intentionally still a hard boundary. If native
        # Dear PyGui cannot render a frame, continuing to call into that context
        # can cause an access violation; let the outer crash logger own that
        # exceptional case instead of spinning on an invalid context.
        running = False
        try:
            running = bool(self._gui_runtime.isRunning())
        except Exception:
            log_exception(
                "Dear PyGui running-state query failed during frame",
                sys.exc_info(), fatal=False)
            self._alive = False
        if running:
            self._rendering = True
            try:
                self._gui_runtime.renderFrame()
            finally:
                self._rendering = False
                self._render_generation += 1
            # Use freshly rendered geometry and service deferred layouts here.
            # Stale list/scroller resources can be recreated next frame, so
            # isolate them from the native render-loop lifetime.
            listviews = [panel.listview for panel in tuple(self.panels)]
            jobs_view = getattr(getattr(self, "jobs_view", None), "listview", None)
            if jobs_view is not None:
                listviews.append(jobs_view)
            for index, listview in enumerate(listviews):
                if getattr(listview, "_resize_layout_pending", False):
                    self._safe_frame_step(
                        "list layout {}".format(index), listview._layout_all)
                overlay = getattr(listview, "_scroller_arrow_overlay", None)
                if overlay is not None:
                    self._safe_frame_step(
                        "scroller overlay {}".format(index), overlay.update)
            self._safe_frame_step(
                "after-render callbacks", self._drain_after_render_callbacks)
        # GLFW may restore its arrow cursor while rendering. Apply splitter
        # feedback only when Dear PyGui owns pointer input; otherwise the
        # foreground native dialog is authoritative for cursor feedback.
        if not native_input_blocked:
            for name, callback in (
                ("file splitter cursor", self._update_file_panel_splitter_cursor),
                ("horizontal splitter cursor", self._update_horizontal_splitter_cursor),
                ("job plot splitter cursor", self._update_job_plot_splitter_cursor),
                ("console splitter cursor", self._update_console_splitter_cursor),
                ("floating plot resize cursor", self._apply_floating_plot_resize_cursor),
            ):
                self._safe_frame_step(name, callback)
        if self._watchdog is not None:
            self._safe_frame_step("watchdog heartbeat", self._watchdog.beat)


        self._frame_clock.presented()

    def after(self, delay, callback, *args):
        return self._dispatcher.after(delay, callback, *args)

    def after_cancel(self, token):
        """Cancel a delayed GUI callback, matching Qt/Tk host scheduler APIs."""
        return self._dispatcher.after_cancel(token)

    def after_render(self, callback, *args):
        """Run a callback after at least one future Dear PyGui frame.

        When called from inside a DPG callback, the current frame is still
        rendering. Target the frame after the next one so queued modal deletion
        can be drained first and committed by rendering before a replacement
        modal is created.
        """
        if not callable(callback) or not self._alive:
            return None
        frames_ahead = 2 if self._rendering else 1
        target_generation = self._render_generation + frames_ahead
        self._after_render_callbacks.append(
            (target_generation, callback, args)
        )
        return target_generation

    def _drain_after_render_callbacks(self):
        if not self._after_render_callbacks:
            return
        while (self._after_render_callbacks and
               self._after_render_callbacks[0][0] <= self._render_generation):
            _generation, callback, args = self._after_render_callbacks.popleft()
            try:
                callback(*args)
            except Exception:
                self._handle_ui_callback_error(callback, sys.exc_info())

    def _drain_queue(self):
        # Bound worker-result processing per frame so a burst of completed
        # background work cannot starve Dear PyGui rendering/input.
        self._dispatcher.drain(
            self._handle_ui_callback_error,
            max_callbacks=256,
            time_budget_ms=6.0,
        )

    def add_watchdog_snapshot_provider(self, name, callback):
        if self._watchdog is not None:
            self._watchdog.add_snapshot_provider(name, callback)

    def _drain_dpg_callbacks(self, discard=False):
        """Dispatch or discard Dear PyGui callbacks on the UI thread.

        Native dialogs are separate top-level HWNDs. Dear PyGui's global
        handlers can still enqueue callbacks from physical mouse state even
        while WinUX is disabled or covered by a native dialog.  While the
        native input gate owns the pointer, drop those background callbacks
        rather than replaying them after the dialog closes.
        """
        try:
            queued = self._gui_runtime.callbackQueue() or ()
        except Exception:
            # Context teardown can race a final callback-queue poll. Missing one
            # batch during shutdown is safer than terminating the application.
            log_exception(
                "Dear PyGui callback queue retrieval failed",
                sys.exc_info(), fatal=False)
            return
        self._dpg_callbacks.extend(queued)
        if discard:
            self._preserve_native_close_requests()
            self._dpg_callbacks.clear()
            return
        # A shared deque permits a blocking modal to pump input recursively
        # without replaying the outer callback batch or starving its buttons.
        # Bound callback execution per frame: a burst of redraw/hover callbacks
        # must not delay frame presentation or an incoming dialog interaction.
        # The unprocessed FIFO tail is retained for the next rendered frame.
        from time import monotonic as _monotonic
        drain_started = _monotonic()
        processed = 0
        while self._dpg_callbacks and self._alive:
            if processed >= 256 or (processed and _monotonic() - drain_started >= 0.006):
                break
            # A callback can itself open a native modal. Stop immediately and
            # discard the remainder of the same physical input batch.
            native_gate = globals().get("native_background_input_blocked")
            blocked = False
            if callable(native_gate):
                try:
                    blocked = bool(native_gate())
                except Exception:
                    log_exception(
                        "Native input gate query failed while draining callbacks",
                        sys.exc_info(), fatal=False)
            if blocked:
                self._preserve_native_close_requests()
                self._dpg_callbacks.clear()
                break
            job = self._dpg_callbacks.popleft()
            processed += 1
            try:
                # Always use WinUx's bounded callback invoker. Dear PyGui's
                # public run_callbacks() counts optional positional parameters
                # as required payload slots and can over-index native jobs,
                # raising ``IndexError: tuple index out of range`` for valid
                # callbacks used by the file/folder selector.
                invoke_callback_job(job)
            except Exception:
                callback = job[0] if isinstance(job, (tuple, list)) and job else None
                self._handle_ui_callback_error(callback, sys.exc_info())

    def _preserve_native_close_requests(self):
        """Keep OS Close events when dropping stale background pointer input.

        DPG puts its viewport-exit callback in the same queue as widget mouse
        handlers. The post-Esc modal release guard must consume the latter, but
        dropping WM_CLOSE means the user gets no confirmation at all. Marshal
        one close request onto the independent UI dispatcher instead.
        """
        if any(isinstance(job, (tuple, list)) and job
               and job[0] == self._request_close for job in self._dpg_callbacks):
            self.after(0, self._request_close)

    def _handle_ui_callback_error(self, callback, exc_info):
        callback_name = getattr(
            callback,
            "__qualname__",
            getattr(callback, "__name__", repr(callback)),
        )
        log_exception(
            "UI queue callback failed: {}".format(callback_name),
            exc_info,
            fatal=False,
        )
        try:
            self.show_error("WinUX", str(exc_info[1]))
        except Exception:
            # Error reporting is best-effort. A broken/closing dialog backend
            # must never turn an already-contained callback exception into an
            # application-ending second exception.
            log_exception(
                "Failed to display a UI callback error",
                sys.exc_info(),
                fatal=False,
            )

    def protocol(self, name, callback=None):
        if name == "WM_DELETE_WINDOW":
            self._close_callback = callback

    def winfo_exists(self):
        return self._alive

    def _hide_native_viewport(self):
        """Hide the OS viewport without entering Dear PyGui teardown."""
        if os.name != "nt":
            return
        try:
            from ....platform import find_process_window
            hwnd = int(find_process_window("WinUX") or 0)
            if not hwnd:
                return
            user32 = _view_ctypes().windll.user32
            user32.ShowWindow.argtypes = [wintypes.HWND, _view_ctypes().c_int]
            user32.ShowWindow.restype = wintypes.BOOL
            user32.ShowWindow(wintypes.HWND(hwnd), 0)  # SW_HIDE
        except Exception:
            pass

    def request_shutdown(self):
        """Make Close instantaneous and leave heavyweight teardown later.

        This method intentionally does *not* call ``dpg.stop_dearpygui`` or
        the renderer context-destroy API.  Calling those APIs while the UI dispatcher is
        inside a callback has produced SMAPython/GLFW deadlocks on Windows.
        The normal render-loop ``finally`` performs graceful teardown when the
        process is embedded; standalone WinUX is terminated by the controller
        after this method returns.
        """
        if not self._alive:
            return
        self._save_compact_job_monitor_geometry()
        # Capture the final dock placement before any hosts/widgets are hidden
        # or destroyed during shutdown.
        self._persist_dock_state()
        log_event("View shutdown requested")
        self._alive = False
        self._hide_native_viewport()
        self._release_horizontal_splitter_cursor_provider()

        chooser = getattr(self, "_local_folder_dialog", None)
        if chooser is not None:
            try:
                chooser.destroy()
            except Exception:
                pass

        from ....dialogs.floating_dialog import close_floating_dialogs
        close_floating_dialogs(self)
        # Same-process dialogs must be terminally deleted while the Dear PyGui
        # context and QApplication dispatcher are still alive. Retained tools
        # normally hide on Close; application shutdown is their one hard delete.
        from ...hosting.inprocess_dialog import close_inprocess_dialogs
        close_inprocess_dialogs(self)
        application = getattr(self, "_qapplication", None)
        if application is not None:
            try:
                application.delete()
            except Exception:
                pass
            self._qapplication = None
        # Process-isolated windows are closed without waiting on the render thread.
        for name in ("login_dialog",
                     "transfer_center_dialog", "server_notepad_dialog"):
            dialog = getattr(self, name, None)
            if dialog is None:
                continue
            try:
                dialog.destroy(wait=False)
            except TypeError:
                try:
                    dialog.destroy()
                except Exception:
                    pass
            except Exception:
                pass

        if self._watchdog is not None:
            self._watchdog.close()
        self._dispatcher.close()
        self._after_render_callbacks.clear()
        self._dpg_callbacks.clear()

    def destroy(self):
        # Compatibility API used by older callers.  Request shutdown first,
        # then stop DPG only when control is outside a render callback.
        self.request_shutdown()
        try:
            if not self._rendering and self._gui_runtime.isRunning():
                self._gui_runtime.stop()
        except Exception:
            pass

    def _destroy_components(self):
        """Release ListView resources in reverse native-hook order."""
        if self._components_destroyed:
            return
        self._components_destroyed = True
        chooser = getattr(self, "_local_folder_dialog", None)
        if chooser is not None:
            try:
                chooser.destroy()
            except Exception:
                pass
        self._end_file_panel_splitter_drag()
        if getattr(self, "_horizontal_splitter_dragging", False):
            self._end_horizontal_splitter_drag()
        if getattr(self, "_plot_splitter_dragging", False):
            self._end_job_plot_splitter_drag()
        if getattr(self, "_console_splitter_dragging", False):
            self._end_console_splitter_drag()
        self._release_horizontal_splitter_cursor_provider()

        self._cancel_console_float_interaction()
        console_panel = getattr(self, "console_panel", None)
        if console_panel is not None:
            try:
                console_panel.destroy()
            except Exception:
                log_exception(
                    "Failed to destroy the SSH Console dock panel",
                    sys.exc_info(), fatal=False)
        console_dock = getattr(self, "console_dock", None)
        if console_dock is not None:
            try:
                console_dock.close()
            except Exception:
                log_exception(
                    "Failed to destroy the SSH Console dock widget",
                    sys.exc_info(), fatal=False)

        login = getattr(self, "login_dialog", None)
        if login is not None:
            try:
                login.destroy(wait=False)
            except Exception:
                log_exception(
                    "Failed to close the native SSH Login dialog",
                    sys.exc_info(),
                    fatal=False,
                )

        transfer_center = getattr(self, "transfer_center_dialog", None)
        if transfer_center is not None:
            try:
                transfer_center.destroy(wait=False)
            except Exception:
                log_exception(
                    "Failed to close the native Transfer Center",
                    sys.exc_info(),
                    fatal=False,
                )

        for plot_panel in list(getattr(self, "job_plot_windows", {}).values()):
            try:
                plot_panel.close(notify=False)
            except Exception:
                pass
        getattr(self, "job_plot_windows", {}).clear()
        dock_manager = getattr(self, "plot_dock_manager", None)
        if dock_manager is not None:
            try:
                dock_manager.close()
            except Exception:
                pass

        owners = [
            getattr(self, "left", None),
            getattr(self, "right", None),
            getattr(self, "jobs_view", None),
        ]
        for owner in reversed(owners):
            listview = getattr(owner, "listview", None)
            if listview is None:
                continue
            try:
                listview.destroy()
            except Exception:
                log_exception(
                    "Failed to destroy a ListView component",
                    sys.exc_info(),
                    fatal=False,
                )

    def _release_horizontal_splitter_cursor_provider(self):
        provider = ExplorerListView._external_cursor_provider
        if getattr(provider, "__self__", None) is self:
            ExplorerListView._external_cursor_provider = None

    def _request_close(self):
        if callable(self._close_callback):
            self._close_callback()
        else:
            self._alive = False
