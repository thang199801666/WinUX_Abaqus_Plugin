from __future__ import annotations

import os
import sys
import tempfile
import threading
from pathlib import Path

from ..diagnostics import (
    crash_guard,
    install_crash_logging,
    log_event,
    log_exception,
    log_runtime_snapshot,
    shutdown_crash_logging,
)
# Keep the controller facade import-light. Feature/service controllers are
# resolved by their factory methods after the first viewport frame or on first use.
from ..controllers.explorer.transfer_interaction import ExplorerTransferInteractionMixin
from ..controllers.explorer.saved_navigation import SavedNavigationMixin
from ..controllers.console import ConsoleFacadeMixin
from .facades import (
    AnalysisFacadeMixin, ConnectionFacadeMixin, ExplorerFacadeMixin,
    JobsFacadeMixin, TransferFacadeMixin,
)
from ..controllers.callbacks import build_controller_callbacks
from ..preferences.performance import PerformancePreferences
from ..models import FileSystemModel
from ..preferences.navigation import NavigationPreferences
from ..preferences.sites import SitePreferences
from ..services.ssh_server import SSHServerModel, prepare_ssh_runtime
from ..services import windows_clipboard
from ..services.inactivity_polling import UserInactivityPolicy
from ..runtime import (
    BackgroundTaskManager, hide_registered_process_windows,
    terminate_registered_children,
)
from ..runtime.paths import safe_current_directory


def __getattr__(name):
    """Keep the historical ``controller.WinUXView`` import lazy-compatible."""
    if name == "WinUXView":
        from ..ui.main_window import WinUXView
        return WinUXView
    raise AttributeError(name)


class WinUXController(
        ConnectionFacadeMixin, JobsFacadeMixin, ExplorerFacadeMixin,
        AnalysisFacadeMixin, TransferFacadeMixin, ConsoleFacadeMixin,
        SavedNavigationMixin, ExplorerTransferInteractionMixin):
    JOB_POLL_INTERVAL_SECONDS = 5  # compatibility/default; adaptive limits live in Performance settings
    # after(0) callbacks are drained in the current UI iteration. Transfers
    # accepted from an overwrite modal must start after the next render frame,
    # once Dear PyGui has completely released the old modal window.
    POST_MODAL_TRANSFER_DELAY_MS = 20
    LOCAL_WATCH_DEBOUNCE_MS = 250
    LOCAL_WATCH_BUSY_RETRY_MS = 120

    @crash_guard("WinUXController initialization failed")
    def __init__(self):
        log_event("WinUXController initialization started")
        # Delay loading Dear PyGui until crash/native-fault capture has been
        # installed by the decorator above.
        from ..ui.main_window import WinUXView

        log_runtime_snapshot("GUI stack loaded")
        log_event("View construction started")
        self.model = FileSystemModel()
        self.server = SSHServerModel()
        self.navigation_preferences = NavigationPreferences()
        self.site_preferences = SitePreferences()
        self.clipboard = []
        self.clipboard_move = False
        self.clipboard_panel_id = None
        # The in-process clipboard remains the authoritative representation for
        # local<->server operations.  A matching token is published beside
        # CF_HDROP so Windows Explorer can participate without making remote
        # paths look like local files to the controller.
        self._clipboard_token = None
        self._clipboard_generation = 0
        self._clipboard_expected_sequence = windows_clipboard.sequence_number()
        self._clipboard_prepare_cancel = None
        self._clipboard_prepare_pending = False
        self._clipboard_cache_root = Path(tempfile.gettempdir()) / "WinUx" / "Clipboard"
        # One bounded daemon pool owns short-lived filesystem/SSH/job work.
        # Long-running service loops (scheduler/poller/native watchers) remain
        # dedicated threads because they intentionally occupy a worker forever.
        self._background_tasks = BackgroundTaskManager(
            max_workers=6, max_pending=128, name="winux-bg")
        # Long file transfers have their own small lane so a stalled/slow SFTP
        # stream cannot occupy every general-purpose worker.
        self._transfer_tasks = BackgroundTaskManager(
            max_workers=2, max_pending=32, name="winux-xfer")
        # Abaqus ODB post-processing can spend minutes opening/scanning a large
        # database. Keep it off both the responsive navigation/job pool and the
        # transfer lane so one Check ODB operation cannot starve either.
        self._analysis_tasks = BackgroundTaskManager(
            max_workers=1, max_pending=4, name="winux-analysis")
        self._file_clipboard = None
        self._clipboard_transfer = None
        # Clipboard cache maintenance is startup housekeeping, not a dependency
        # of the first viewport. Schedule it with the other post-frame services
        # so task-pool threads are not created while the main window is building.
        self.transfer_cancel = threading.Event()
        # Transfer I/O orchestration is isolated from pointer/drag routing.
        # Existing controller callbacks remain compatibility wrappers.
        self._transfers = None
        # Last destination resolved while a drag is active. Dear PyGui can
        # briefly report invalid item rectangles immediately after native
        # mouse capture is released, so the drop path must not depend on a
        # second hit-test in the following frame.
        self._drag_target_panel = None
        self._drag_target_destination = None
        self._drag_target_point = None
        self._job_poll_cancel = None
        self._job_poll_policy = None
        self._job_poll_wakeup = None
        self._job_poll_force_fast = None
        # One app-wide inactivity clock coordinates qstat, live ODB polling and
        # reconnect backoff.  It is fed by QApplication native input, so remote
        # workers never need their own UI/input polling thread.
        self._inactivity_policy = UserInactivityPolicy(
            settings=PerformancePreferences().load())
        self._reconnect_lock = threading.Lock()
        self._reconnect_active = False
        # One connection supervisor owns reconnect attempts. Other features
        # only signal it and wait for this event instead of opening/retrying
        # SSH independently.
        self._connection_online = threading.Event()
        self._connection_generation = 0
        self._connection = None
        self._job_polling = None
        self._server_current_path = None
        self._server_nav_generation = 0
        self._local_nav_generation = 0
        self._closing = False
        self._close_confirmation_pending = False
        self._job_edit_settings = {}
        # Active run/delete schedule execution has one focused owner.  The
        # component publishes the historical task/lock attributes back onto
        # this facade so existing callbacks, tests and shutdown code remain
        # compatible while execution/editing logic lives outside controller.py.
        self._schedule_execution = None
        # Durable local recovery + shared server manifest synchronization now
        # has one focused owner. Execution timing/tasks remain in the scheduler
        # while persistence is isolated behind this compatibility facade.
        self._schedule_manifest = None

        # Realtime Job Viewer plot/ODB state has a focused owner.  The facade
        # methods below remain for callback/backward compatibility while this
        # component owns watcher threads, selection snapshots and adaptive ODB
        # discovery history.
        self._job_plots = None

        # Native Windows directory notifications keep only the local panel in
        # sync with Explorer and other applications.  Refresh work is
        # coalesced and always marshalled back to Dear PyGui's UI thread.
        self._local_watch = None
        self._navigation = None

        callbacks = build_controller_callbacks(self)
        self.view = WinUXView(callbacks)
        self.view.add_watchdog_snapshot_provider(
            "background_tasks", self._background_tasks.snapshot)
        self.view.add_watchdog_snapshot_provider(
            "transfer_tasks", self._transfer_tasks.snapshot)
        self.view.add_watchdog_snapshot_provider(
            "analysis_tasks", self._analysis_tasks.snapshot)
        self.view.add_watchdog_snapshot_provider(
            "remote_polling_activity", self._inactivity_policy.snapshot)
        log_event("View construction finished")
        for panel in self.view.panels:
            panel._sort = self.navigation_preferences.load_sort(panel.panel_id)
            if panel._sort:
                panel.set_sort_indicator(*panel._sort)
        saved_local = self.navigation_preferences.load_local()
        if saved_local:
            try:
                self.initial_local = Path(saved_local)
            except (OSError, RuntimeError, TypeError, ValueError):
                self.initial_local = safe_current_directory()
        else:
            self.initial_local = safe_current_directory()
        self._initial_load_pending = True
        self.view.left.status.set("Loading...")
        # Enter Tk's event loop before touching the filesystem so the window
        # appears immediately even when the last folder is slow to enumerate.
        self.view.after(0, self._load_initial_local_async)
        self.view.after(0, self._start_background_services)
        # Auto login starts only after the first UI turn so the main window is
        # already visible and can report connection progress without opening a
        # login dialog.
        self.view.after(0, self._auto_login_from_preferences)
        self.view.protocol("WM_DELETE_WINDOW", self.close)
        log_event("WinUXController initialization finished")

    def _submit_background(
            self, name, callback, *args, key=None, coalesce=False,
            replace=False, cancel_event=None, **kwargs):
        """Submit one bounded daemon task without ever blocking the UI thread."""
        handle = self._background_tasks.submit(
            name, callback, *args, key=key, coalesce=coalesce,
            replace=replace, cancel_event=cancel_event, **kwargs)
        if handle.state == "rejected":
            log_event("Background task rejected: {}".format(name))
        return handle

    def _submit_transfer(
            self, name, callback, *args, cancel_event=None, **kwargs):
        """Submit long-running copy/SFTP work to the isolated transfer lane."""
        handle = self._transfer_tasks.submit(
            name, callback, *args, cancel_event=cancel_event, **kwargs)
        if handle.state == "rejected":
            log_event("Transfer task rejected: {}".format(name))
        return handle

    def _submit_analysis(
            self, name, callback, *args, cancel_event=None, **kwargs):
        """Submit long-running Abaqus post-processing without starving UI work."""
        handle = self._analysis_tasks.submit(
            name, callback, *args, cancel_event=cancel_event, **kwargs)
        if handle.state == "rejected":
            log_event("Analysis task rejected: {}".format(name))
        return handle

    def _schedule_execution_controller(self):
        """Return the schedule component, lazily adopting legacy test state."""
        component = getattr(self, "_schedule_execution", None)
        if component is None:
            from ..controllers.jobs.schedule import JobScheduleController
            component = JobScheduleController(self, adopt_existing=True)
            self._schedule_execution = component
        return component

    def _transfer_controller(self):
        component = getattr(self, "_transfers", None)
        if component is None:
            from ..controllers.transfer.controller import TransferController
            component = TransferController(self)
            self._transfers = component
        return component

    def _connection_controller(self):
        component = getattr(self, "_connection", None)
        if component is None:
            from ..controllers.connection import ConnectionController
            component = ConnectionController(self, adopt_existing=True)
            self._connection = component
        return component

    def _job_polling_controller(self):
        component = getattr(self, "_job_polling", None)
        if component is None:
            from ..controllers.jobs.polling import JobPollingController
            component = JobPollingController(self, adopt_existing=True)
            self._job_polling = component
        return component

    def _start_background_services(self):
        """Start non-visual services after the first viewport frame."""
        self._submit_background(
            "clipboard-cache-cleanup", self._cleanup_old_clipboard_cache)
        prepare_ssh_runtime()
        self._schedule_execution_controller().start()

    def run(self):
        install_crash_logging()
        log_event("Controller main loop started")
        failed = False
        try:
            self.view.mainloop()
        except Exception:
            failed = True
            log_exception(
                "Controller main loop failed",
                sys.exc_info(),
                fatal=True,
            )
            raise
        finally:
            # Keep hooks and file handles alive while an exception propagates
            # through an embedding launcher. The outer entry point or atexit
            # will flush/close them after it records its own context.
            if not failed:
                shutdown_crash_logging("Controller main loop finished")

    def close(self):
        if self._closing or self._close_confirmation_pending:
            return

        snapshot = self.job_schedules(blocking=False)
        schedules = [row for row in (snapshot or []) if row[4] == "Waiting"]
        if snapshot is None:
            message = (
                "Schedule information is being updated. Any pending server "
                "schedules will continue running after WinUx closes. Exit anyway?")
        elif schedules:
            details = "\n".join(
                "{} | {} | {}".format(item[0], item[1], item[2])
                for item in schedules)
            message = (
                "The following job schedules are pending:\n\n{}\n\n"
                "These schedules will continue running on the Linux server "
                "after WinUx closes. Exit anyway?"
            ).format(details)
        else:
            message = "Are you sure you want to exit WinUx?"

        self._close_confirmation_pending = True
        try:
            self.view.confirm_action_async(
                "Confirm Close App",
                message,
                self._close_confirmation_finished,
                primary_text="Exit",
                secondary_text="Cancel",
                intent="danger",
            )
        except Exception:
            # A launch/import error must not permanently disable Exit retries.
            self._close_confirmation_pending = False
            raise

    def _close_confirmation_finished(self, confirmed):
        self._close_confirmation_pending = False
        if confirmed:
            self._finish_close()

    @staticmethod
    def _cancel_task_map_for_shutdown(lock, mapping):
        """Cancel a task map without ever waiting for a worker-held lock.

        Close is executed on Dear PyGui's render thread.  Even a normally tiny
        Python lock is unacceptable here: a worker can be pre-empted while it
        owns the lock and Windows then reports the viewport as Not Responding.
        Workers also observe ``self._closing``, so failing to acquire a lock is
        harmless during process shutdown.
        """
        tasks = ()
        acquired = False
        try:
            acquired = lock.acquire(False)
            if acquired:
                tasks = tuple(mapping.values())
                mapping.clear()
        except Exception:
            tasks = ()
        finally:
            if acquired:
                try:
                    lock.release()
                except Exception:
                    pass
        for task in tasks:
            cancel = task.get("cancel") if isinstance(task, dict) else None
            if cancel is not None:
                try:
                    cancel.set()
                except Exception:
                    pass

    @staticmethod
    def _force_process_exit_enabled():
        """Return whether user-confirmed Exit should terminate this process.

        WinUx is normally launched as its own disposable process from the
        Abaqus plug-in/launcher.  In those production paths, leaving shutdown
        up to GLFW/Tk/Python teardown can keep the process alive with a hidden
        viewport, which appears as a stuck taskbar preview/ghost window even
        though the main UI has already disappeared.

        Production therefore defaults to a bounded hard-exit path after the
        viewport has been hidden and child helpers have been signalled.  Tests
        and any deliberate embedded/library hosts can opt out.
        """
        env = os.environ
        # Explicit production/launcher intent wins even under a test harness;
        # shutdown tests patch os._exit and rely on this exact contract.
        if str(env.get("WINUX_STANDALONE_PROCESS", "")).strip() == "1":
            return True
        if env.get("PYTEST_CURRENT_TEST"):
            return False
        if str(env.get("WINUX_ALLOW_EMBEDDED_CLOSE", "")).strip() == "1":
            return False
        if str(env.get("WINUX_DISABLE_HARD_EXIT", "")).strip() == "1":
            return False
        return True

    def _finish_close(self):
        if self._closing:
            return
        log_event("User-confirmed application shutdown started")
        self._closing = True

        # The Abaqus plug-in launches WinUX in its own ``abaqus python`` /
        # SMAPython process.  Never perform potentially blocking teardown in
        # the render callback.  First make the viewport disappear and reject
        # all future UI work; then signal background activity.
        try:
            self.view.request_shutdown()
        except Exception:
            # Closing must remain one-way even if the GUI backend is already
            # partly torn down.
            pass

        # Child dialogs/prewarm workers live in independent DPG/Tk processes.
        # Hide their HWNDs synchronously before the main owner disappears so
        # Windows cannot promote a briefly orphaned helper to a grey taskbar
        # button while its IPC close is still being processed.
        try:
            hide_registered_process_windows()
        except Exception:
            pass

        self._stop_job_polling()
        self._stop_all_job_plots()
        notepad = getattr(self, "_server_notepad", None)
        if notepad is not None:
            notepad.close()
        file_clipboard = getattr(self, "_file_clipboard", None)
        if file_clipboard is not None:
            file_clipboard.close()
        online_event = getattr(self, "_connection_online", None)
        if online_event is not None:
            online_event.clear()
        self._schedule_wakeup.set()
        self._reconnect_active = False
        self._cancel_task_map_for_shutdown(
            self._job_delete_lock, self._job_delete_tasks)
        self._cancel_task_map_for_shutdown(
            self._job_run_lock, self._job_run_tasks)

        # transfer_cancel historically points only at the most recently
        # started transfer. Transfer Center owns every active task, so cancel
        # both to cover queued/parallel operations and Hot Download.
        self.transfer_cancel.set()
        transfer_center = getattr(self.view, "transfer_center_dialog", None)
        if transfer_center is not None:
            try:
                transfer_center.cancel_all(update_ui=False)
            except Exception:
                pass
        if self._clipboard_prepare_cancel is not None:
            self._clipboard_prepare_cancel.set()
        try:
            self._background_tasks.close(cancel_pending=True)
            self._transfer_tasks.close(cancel_pending=True)
            self._analysis_tasks.close(cancel_pending=True)
        except Exception:
            pass

        # Break the SSH transport without acquiring the serialized wire lock.
        # This wakes Paramiko/SFTP workers that are blocked in recv/send.
        try:
            self.server.request_shutdown()
        except Exception:
            pass

        # The production WinUX process is disposable and is deliberately
        # separate from Abaqus/CAE.  Python/Tk/GLFW teardown is not reliable
        # enough to be allowed to keep SMAPython alive after the user has
        # confirmed Exit.  In standalone mode terminate this child process
        # immediately after cancellation/socket shutdown.  The OS releases the
        # remaining GLFW/Tk/Paramiko resources and no Abaqus process is touched.
        if self._force_process_exit_enabled():
            # request_shutdown()/dialog close above are intentionally non-
            # blocking. Give UI children one bounded grace window to consume
            # that close, then kill any remaining *process tree* (the floating
            # worker may be cmd.exe -> abaqus python). This happens after the
            # viewport is hidden, so exit remains visually instantaneous while
            # no orphan HWND survives into the taskbar.
            try:
                terminate_registered_children(
                    grace_timeout=0.12, force_timeout=0.25)
            except Exception:
                pass
            os._exit(0)

        # Library/test embedding keeps the graceful path. These operations are
        # best effort and are intentionally reached only when hard process exit
        # is disabled.
        try:
            self._stop_local_watcher(wait=False)
        except Exception:
            pass
