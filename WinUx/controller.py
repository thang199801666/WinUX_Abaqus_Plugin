from __future__ import annotations

import os
import sys
import tempfile
import threading
import time
import json
from datetime import datetime, timedelta
from pathlib import Path, PurePosixPath

from .diagnostics import (
    crash_guard,
    install_crash_logging,
    log_event,
    log_exception,
    log_runtime_snapshot,
    shutdown_crash_logging,
)
from .controllers import (
    ConnectionController, JobPollingController, JobPlotController,
    JobScheduleController, ScheduleManifestController, TransferController,
    SyncPreviewController, LocalWatchController, NavigationController,
    ServerNotepadController, FileClipboardController, ClipboardTransferController,
    JobSubmissionController, InpAnalysisController, OdbAnalysisController,
    JobActionsController, FileCommandController, ExplorerTransferInteractionMixin,
    build_controller_callbacks,
)
from .inp_preferences import INPPreferences
from .login_preferences import LoginPreferences
from .model import FileSystemModel
from .navigation_preferences import NavigationPreferences
from .preferences.sites import SitePreferences
from .server_model import (
    RemoteTextConflictError, SSHServerModel, prepare_ssh_runtime,
)
from .services import (
    platform_integration, presentation, windows_clipboard,
)
from .runtime import (
    BackgroundTaskManager, hide_registered_process_windows,
    terminate_registered_children,
)


def __getattr__(name):
    """Keep the historical ``controller.WinUXView`` import lazy-compatible."""
    if name == "WinUXView":
        from .view import WinUXView
        return WinUXView
    raise AttributeError(name)


class WinUXController(ExplorerTransferInteractionMixin):
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
        from .view import WinUXView

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
        self._file_clipboard = FileClipboardController(self)
        self._clipboard_transfer = ClipboardTransferController(self)
        self._submit_background(
            "clipboard-cache-cleanup", self._cleanup_old_clipboard_cache)
        self.transfer_cancel = threading.Event()
        # Transfer I/O orchestration is isolated from pointer/drag routing.
        # Existing controller callbacks remain compatibility wrappers.
        self._transfers = TransferController(self)
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
        self._reconnect_lock = threading.Lock()
        self._reconnect_active = False
        # One connection supervisor owns reconnect attempts. Other features
        # only signal it and wait for this event instead of opening/retrying
        # SSH independently.
        self._connection_online = threading.Event()
        self._connection_generation = 0
        self._connection = ConnectionController(self, adopt_existing=True)
        self._job_polling = JobPollingController(self, adopt_existing=True)
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
        self._schedule_execution = JobScheduleController(self)
        # Durable local recovery + shared server manifest synchronization now
        # has one focused owner. Execution timing/tasks remain in the scheduler
        # while persistence is isolated behind this compatibility facade.
        self._schedule_manifest = ScheduleManifestController(self)

        # Realtime Job Viewer plot/ODB state has a focused owner.  The facade
        # methods below remain for callback/backward compatibility while this
        # component owns watcher threads, selection snapshots and adaptive ODB
        # discovery history.
        self._job_plots = JobPlotController(self)

        # Native Windows directory notifications keep only the local panel in
        # sync with Explorer and other applications.  Refresh work is
        # coalesced and always marshalled back to Dear PyGui's UI thread.
        self._local_watch = LocalWatchController(self)
        self._navigation = NavigationController(self)

        callbacks = build_controller_callbacks(self)
        self.view = WinUXView(callbacks)
        self.view.add_watchdog_snapshot_provider(
            "background_tasks", self._background_tasks.snapshot)
        self.view.add_watchdog_snapshot_provider(
            "transfer_tasks", self._transfer_tasks.snapshot)
        self.view.add_watchdog_snapshot_provider(
            "analysis_tasks", self._analysis_tasks.snapshot)
        log_event("View construction finished")
        for panel in self.view.panels:
            panel._sort = self.navigation_preferences.load_sort(panel.panel_id)
            if panel._sort:
                panel.set_sort_indicator(*panel._sort)
        saved_local = self.navigation_preferences.load_local()
        self.initial_local = Path(saved_local) if saved_local else Path.cwd()
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
            component = JobScheduleController(self, adopt_existing=True)
            self._schedule_execution = component
        return component

    def _transfer_controller(self):
        component = getattr(self, "_transfers", None)
        if component is None:
            component = TransferController(self)
            self._transfers = component
        return component

    def _connection_controller(self):
        component = getattr(self, "_connection", None)
        if component is None:
            component = ConnectionController(self, adopt_existing=True)
            self._connection = component
        return component

    def _job_polling_controller(self):
        component = getattr(self, "_job_polling", None)
        if component is None:
            component = JobPollingController(self, adopt_existing=True)
            self._job_polling = component
        return component

    def _start_background_services(self):
        """Start non-visual services after the first viewport frame."""
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

        schedules = [row for row in self.job_schedules() if row[4] == "Waiting"]
        if schedules:
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
        self.view.confirm_action_async(
            "Confirm Close App",
            message,
            self._close_confirmation_finished,
            primary_text="Exit",
            secondary_text="Cancel",
            intent="danger",
        )

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

    def _navigation_controller(self):
        component = getattr(self, "_navigation", None)
        if component is None:
            component = NavigationController(self)
            self._navigation = component
        return component

    def _load_initial_local_async(self):
        return self._navigation_controller().load_initial()

    def _initial_local_loaded(self, path, items):
        return self._navigation_controller().initial_loaded(path, items)

    def _initial_local_failed(self, error):
        return self._navigation_controller().initial_failed(error)

    def _local_watch_controller(self):
        component = getattr(self, "_local_watch", None)
        if component is None:
            component = LocalWatchController(self)
            self._local_watch = component
        return component

    @staticmethod
    def _same_local_path(first, second):
        return LocalWatchController.same_path(first, second)

    def _watch_local_path(self, path):
        return self._local_watch_controller().watch(path)

    def _stop_local_watcher(self, wait=True):
        return self._local_watch_controller().stop(wait=wait)

    def _local_watcher_error(self, path, error):
        return self._local_watch_controller().report_error(path, error)

    def _local_directory_changed(self, path, generation):
        return self._local_watch_controller().changed(path, generation)

    def _local_listview_is_busy(self):
        return self._local_watch_controller().is_busy()

    def _begin_local_watch_refresh(self, path, generation):
        return self._local_watch_controller().begin_refresh(path, generation)

    def _complete_local_watch_refresh(self, path, generation, items, error):
        return self._local_watch_controller().complete_refresh(path, generation, items, error)

    def _auto_login_from_preferences(self):
        return self._connection_controller().auto_login_from_preferences()


    def choose_path(self, panel):
        if panel.panel_id == "local":
            self.view.show_local_folder_dialog(
                initial=str(panel.current_path),
                on_selected=lambda selected: self.open_path(panel, selected),
            )
            return
        if not self._ensure_server_online():
            return
        self.view.show_server_path(
            initial=str(panel.current_path),
            suggestion_provider=self._suggest_server_paths,
            on_selected=lambda selected: self.open_path(panel, selected),
            task_submitter=self._submit_background,
        )

    def _suggest_server_paths(self, value):
        """Return remote folders whose names match the typed path fragment."""
        typed = str(value).strip().replace("\\", "/")
        if not typed:
            typed = str(self.server.home)
        elif not typed.startswith("/"):
            return self.server.search_directories(typed, limit=100)
        trailing_separator = typed.endswith("/")
        normalized = self.server.normalize(typed)
        if trailing_separator or str(normalized) == "/":
            parent, fragment = normalized, ""
        else:
            parent, fragment = normalized.parent, normalized.name.casefold()
        folders = []
        for item in self.server.list_directory(parent):
            if item.is_dir and fragment in item.name.casefold():
                folders.append(str(item.path))
        return folders[:100]

    def login(self, dialog, values, automatic=False):
        return self._connection_controller().login(
            dialog, values, automatic=automatic)


    def _login_failed(self, dialog, error, automatic=False):
        return self._connection_controller().login_failed(
            dialog, error, automatic=automatic)


    def _login_succeeded(self, dialog, folder, items, automatic=False):
        return self._connection_controller().login_succeeded(
            dialog, folder, items, automatic=automatic)


    @staticmethod
    def _job_poll_signature(jobs):
        return JobPollingController.signature(jobs)


    @staticmethod
    def _configure_job_poll_policy(policy, settings):
        return JobPollingController.configure_policy(policy, settings)


    def _start_job_polling(self):
        return self._job_polling_controller().start()


    def _start_reconnect(self):
        return self._connection_controller().start_reconnect()


    def _ensure_server_online(self):
        return self._connection_controller().ensure_online()


    def _connection_restored(self, generation):
        return self._connection_controller().restored(generation)


    def _stop_job_polling(self):
        return self._job_polling_controller().stop()


    def _schedule_loop(self):
        return self._schedule_execution_controller().loop()

    def _execute_scheduled_run(self, task):
        return self._schedule_execution_controller().execute_run(task)

    def _execute_scheduled_delete(self, task):
        return self._schedule_execution_controller().execute_delete(task)

    def _schedule_status_message(self, message):
        return self._schedule_execution_controller().status_message(message)

    def _apply_job_update(self, cancel, jobs):
        return self._job_polling_controller().apply_update(cancel, jobs)


    def _reconcile_job_deletions(self, jobs):
        return self._schedule_execution_controller().reconcile_deletions(jobs)

    def _selected_job_values(self):
        return self.view.selected_job_values()

    def _job_actions_controller(self):
        component = getattr(self, "_job_actions", None)
        if component is None:
            component = JobActionsController(self)
            self._job_actions = component
        return component

    def _continue_job_command(self, action, values):
        return self._job_actions_controller()._continue_job_command(action, values)

    def _job_modal_command(self, action, values):
        return self._job_actions_controller()._job_modal_command(action, values)

    # Job Viewer realtime plot/ODB compatibility facade.  Stateful logic lives
    # in ``controllers.job_plot.JobPlotController`` so this application
    # controller no longer owns plot worker state directly.
    def _job_plot_selection_changed(self, job_id, items):
        return self._job_plots.selection_changed(job_id, items)

    def _job_plot_closed(self, job_id):
        return self._job_plots.closed(job_id)

    def _stop_all_job_plots(self):
        job_plots = getattr(self, "_job_plots", None)
        if job_plots is not None:
            return job_plots.stop_all()
        return None

    def _apply_job_plot_payload(self, job_id, payload):
        return self._job_plots.apply_payload(job_id, payload)

    def _job_plot_selection_snapshot(self, job_id):
        return self._job_plots.selection_snapshot(job_id)

    @staticmethod
    def _odb_adaptive_settings():
        return JobPlotController.adaptive_settings()

    def _odb_discovery_delay(self, policy, started_at, settings):
        return self._job_plots.discovery_delay(policy, started_at, settings)

    def _remember_odb_appearance_wait(self, seconds, settings):
        return self._job_plots.remember_appearance_wait(seconds, settings)

    def _job_plot_watch_loop(self, job_id, job_name, cancel):
        return self._job_plots.watch_loop(job_id, job_name, cancel)

    def _open_job_plots(self, values):
        return self._job_plots.open(values)

    def _job_odb_failed(self, title, message):
        return self._job_plots.odb_failed(title, message)

    def _job_odb_resolved(self, action, job_id, job_name, path):
        return self._job_plots.odb_resolved(action, job_id, job_name, path)

    def _job_odb_command(self, action, values):
        return self._job_plots.odb_command(action, values)

    def job_command(self, action):
        return self._job_actions_controller().job_command(action)

    def _refresh_jobs_now(self):
        return self._job_polling_controller().refresh_now()


    def _schedule_job_deletion(self, job_id, job_name, settings):
        return self._schedule_execution_controller().schedule_deletion(
            job_id, job_name, settings)

    def _finish_job_deletion(self, task):
        return self._schedule_execution_controller().finish_deletion(task)

    def _pending_job_deletions(self):
        return self._schedule_execution_controller().pending_deletions()

    def job_schedules(self):
        return self._schedule_execution_controller().rows()

    def _record_schedule_status(self, task, kind, status):
        return self._schedule_execution_controller().record_status(
            task, kind, status)

    @staticmethod
    def _remaining_time(target, now):
        return presentation.remaining_time(target, now)

    def _schedule_manifest_entry(self, task, kind):
        return self._schedule_manifest.manifest_entry(task, kind)

    def _persist_schedule_recovery_queue(self):
        return self._schedule_manifest.persist_recovery_queue()

    def _flush_schedule_manifest_async(self):
        return self._schedule_manifest.flush_async()

    def _save_shared_schedule(self, task, kind):
        return self._schedule_manifest.save(task, kind)

    def _remove_shared_schedule(self, schedule_id):
        return self._schedule_manifest.remove(schedule_id)

    def _restore_shared_schedules(self):
        return self._schedule_manifest.restore()

    def _install_shared_schedules(self, entries):
        return self._schedule_execution_controller().install_shared(entries)

    def job_schedule_command(self, action, kind, key):
        return self._schedule_execution_controller().command(action, kind, key)

    def _refresh_schedule_dialog(self):
        return self._schedule_execution_controller().refresh_dialog()

    def _cancel_job_schedule(self, kind, key):
        return self._schedule_execution_controller().cancel(kind, key)

    def _apply_job_schedule_edit(
            self, kind, key, original_task, is_after, value):
        return self._schedule_execution_controller().apply_edit(
            kind, key, original_task, is_after, value)

    def open_path(self, panel, value, record_history=True):
        return self._navigation_controller().open(panel, value, record_history)

    def _local_path_loaded(self, panel, path, items, record_history, generation):
        return self._navigation_controller().local_loaded(panel, path, items, record_history, generation)

    def _local_path_failed(self, panel, path, generation, error):
        return self._navigation_controller().local_failed(panel, path, generation, error)

    def _server_path_loaded(self, panel, path, items, record_history, generation):
        return self._navigation_controller().server_loaded(panel, path, items, record_history, generation)

    def _server_path_failed(self, panel, path, generation, error):
        return self._navigation_controller().server_failed(panel, path, generation, error)

    def console_command(self, command):
        if not self._ensure_server_online():
            return False
        try:
            self.server.send_shell_command(command)
            return True
        except Exception as exc:
            self.view.show_error("Console", str(exc))
            return False

    def console_interrupt(self):
        if not self.server.connected:
            return False
        try:
            self.server.interrupt_shell()
            return True
        except Exception as exc:
            self.view.show_error("Console", str(exc))
            return False

    def navigate(self, panel, action):
        if action == "refresh":
            return self.open_path(panel, panel.current_path, False)
        if action == "parent":
            return self.open_path(panel, panel.current_path.parent)
        if action == "home":
            return self.open_path(panel, self.server.home if panel.panel_id == "server" else Path.home())
        step = -1 if action == "back" else 1
        target = panel.history_index + step
        if 0 <= target < len(panel.history):
            panel.history_index = target
            self.open_path(panel, panel.history[target], False)

    # ------------------------------------------------------------------
    # WinSCP-style saved navigation / site profiles
    def _bookmark_entries(self):
        entries = []
        for item in self.navigation_preferences.load_bookmarks("local"):
            entry = dict(item)
            entry["panel_id"] = "local"
            entries.append(entry)
        if self.server.connected:
            for item in self.navigation_preferences.load_bookmarks(
                    "server", host=self.server.host,
                    username=self.server.username):
                entry = dict(item)
                entry.update({
                    "panel_id": "server",
                    "host": self.server.host,
                    "username": self.server.username,
                })
                entries.append(entry)
        return entries

    @staticmethod
    def _bookmark_label(path, panel_id):
        try:
            value = (PurePosixPath(str(path)) if panel_id == "server"
                     else Path(str(path)))
            return value.name or str(value)
        except Exception:
            return str(path)

    def bookmark_command(self, action):
        action = str(action or "")
        if action == "add_local":
            panel = self.view.left
            path = panel.current_path
            self.navigation_preferences.add_bookmark(
                "local", path,
                label=self._bookmark_label(path, "local"))
            panel.status.set("Bookmarked {}".format(path))
            self._refresh_bookmarks_dialog()
            return
        if action == "add_server":
            if not self._ensure_server_online():
                return
            panel = self.view.right
            path = panel.current_path
            self.navigation_preferences.add_bookmark(
                "server", path,
                label=self._bookmark_label(path, "server"),
                host=self.server.host, username=self.server.username)
            panel.status.set("Bookmarked {}".format(path))
            self._refresh_bookmarks_dialog()
            return
        if action == "manage":
            self.view.show_bookmarks(
                self._bookmark_entries(), self._open_bookmark,
                self._remove_bookmark, self._rename_bookmark)

    def _refresh_bookmarks_dialog(self):
        dialog = getattr(self.view, "bookmarks_dialog", None)
        if dialog is not None and dialog.winfo_exists():
            dialog.refresh(self._bookmark_entries())

    def _open_bookmark(self, entry):
        panel_id = str(entry.get("panel_id") or "local")
        path = str(entry.get("path") or "")
        if not path:
            return
        if panel_id == "server":
            if not self._ensure_server_online():
                return
            expected_host = str(entry.get("host") or self.server.host)
            expected_user = str(entry.get("username") or self.server.username)
            if (expected_host.casefold() != str(self.server.host).casefold() or
                    expected_user.casefold() != str(self.server.username).casefold()):
                self.view.show_message(
                    "Bookmarks",
                    "This bookmark belongs to {}@{}. Connect to that site first.".format(
                        expected_user, expected_host))
                return
            self.open_path(self.view.right, self.server.normalize(path))
        else:
            self.open_path(self.view.left, Path(path))

    def _remove_bookmark(self, entry):
        panel_id = str(entry.get("panel_id") or "local")
        path = str(entry.get("path") or "")
        self.navigation_preferences.remove_bookmark(
            panel_id, path,
            host=entry.get("host") or self.server.host,
            username=entry.get("username") or self.server.username)
        self._refresh_bookmarks_dialog()

    def _rename_bookmark(self, entry, label):
        panel_id = str(entry.get("panel_id") or "local")
        path = str(entry.get("path") or "")
        self.navigation_preferences.rename_bookmark(
            panel_id, path, label,
            host=entry.get("host") or self.server.host,
            username=entry.get("username") or self.server.username)
        self._refresh_bookmarks_dialog()

    def site_manager(self):
        self.view.show_site_manager(
            self.site_preferences.load(), self._save_site_profile,
            self._delete_site_profile, self._connect_site_profile)

    def _refresh_site_manager(self, selected_id=None):
        dialog = getattr(self.view, "site_manager_dialog", None)
        if dialog is not None and dialog.winfo_exists():
            dialog.refresh(self.site_preferences.load(), selected_id)

    def _save_site_profile(self, values):
        dialog = getattr(self.view, "site_manager_dialog", None)
        try:
            saved = self.site_preferences.save_site(values)
        except (OSError, ValueError) as exc:
            if dialog is not None and dialog.winfo_exists():
                dialog.show_error(str(exc))
            return
        self._refresh_site_manager(saved.get("id"))

    def _delete_site_profile(self, site):
        site_id = str(site.get("id") or "")
        if not site_id:
            return

        def complete(confirmed):
            if not confirmed:
                return
            self.site_preferences.delete(site_id)
            self._refresh_site_manager()

        self.view.confirm_action_async(
            "Delete Site?",
            "Delete the saved site profile '{}'?\n\nStored passwords are managed separately and will not be deleted.".format(
                site.get("name") or site.get("host") or "Site"),
            complete,
            primary_text="Delete", secondary_text="Cancel", intent="danger")

    def _connect_site_profile(self, values):
        dialog = getattr(self.view, "site_manager_dialog", None)
        try:
            saved = self.site_preferences.save_site(values)
        except (OSError, ValueError) as exc:
            if dialog is not None and dialog.winfo_exists():
                dialog.show_error(str(exc))
            return
        username = str(saved.get("username") or "")
        password = LoginPreferences().password_for(username) if username else ""
        if not username or not password:
            if dialog is not None and dialog.winfo_exists():
                dialog.show_error(
                    "This site has no saved username/password. Use Log-In once and "
                    "enable 'Remember password', then connect from Site Manager.")
            return
        if dialog is not None and dialog.winfo_exists():
            dialog.destroy()
        self.login(None, {
            "host": saved["host"],
            "port": saved["port"],
            "username": username,
            "password": password,
            "remember": True,
            "remote_path": saved.get("remote_path") or "",
        })

    # ------------------------------------------------------------------
    # Current-directory synchronization preview
    def _sync_preview_controller(self):
        component = getattr(self, "_sync_preview", None)
        if component is None:
            component = SyncPreviewController(self)
            self._sync_preview = component
        return component

    @staticmethod
    def _sync_item_fields(item):
        return SyncPreviewController.item_fields(item)

    @classmethod
    def _build_sync_rows(cls, local_items, server_items, local_root, server_root):
        return SyncPreviewController.build_rows(
            local_items, server_items, local_root, server_root)

    def sync_preview(self):
        return self._sync_preview_controller().preview()

    def _sync_preview_ready(self, rows, local_root, server_root):
        return self._sync_preview_controller().ready(rows, local_root, server_root)

    def _sync_transfer_rows(self, rows):
        return self._sync_preview_controller().transfer_rows(rows)

    def _server_notepad_controller(self):
        component = getattr(self, "_server_notepad", None)
        if component is None:
            component = ServerNotepadController(self)
            self._server_notepad = component
        return component

    def edit_server_file(self, panel, selected_paths=None):
        return self._server_notepad_controller().edit(panel, selected_paths)

    def _load_server_notepad(self, dialog, path):
        return self._server_notepad_controller().load(dialog, path)

    def _server_notepad_stream_finished(self, dialog, snapshot):
        return self._server_notepad_controller().stream_finished(dialog, snapshot)

    def _server_notepad_loaded(self, dialog, snapshot):
        return self._server_notepad_controller().loaded(dialog, snapshot)

    def _save_server_notepad(self, dialog, path, text, encoding, expected_signature, force):
        return self._server_notepad_controller().save(
            dialog, path, text, encoding, expected_signature, force)

    def _server_notepad_saved(self, dialog, snapshot):
        return self._server_notepad_controller().saved(dialog, snapshot)

    def _reload_server_notepad(self, dialog, path):
        return self._server_notepad_controller().reload(dialog, path)

    def double_click(self, panel, event):
        if isinstance(event, (int, str)):
            item = panel.item_for_row(event)
        elif hasattr(event, "path"):
            item = event
        else:
            item = None
        if item is None:
            return
        path = item.data.get("path") or item.path
        if panel.panel_id == "server" and not item.is_dir:
            # Server files use the WinUx internal editor on double-click.
            # Keep the explicit context-menu ``Open`` command available for
            # users who intentionally want the legacy download + OS-default
            # application behavior.  Passing the activated path explicitly
            # also avoids relying on whatever selection state remains after
            # the double-click gesture.
            self.edit_server_file(panel, [path])
            return
        self.open_path(panel, path)

    def _open_remote_file(self, panel, remote_path, size):
        if size > 10 * 1024 * 1024 and not self.view.confirm_action(
                "Large file",
                "File size larger than 10MB. Download and open this file?"):
            return
        panel.status.set("Downloading {}...".format(remote_path.name))

        def worker():
            try:
                temp_folder = Path(tempfile.mkdtemp(prefix="WinUX_"))
                self.server.download([remote_path], temp_folder)
                local_path = temp_folder / remote_path.name
            except Exception as exc:
                self.view.after(0, self.view.show_error,
                                "Open remote file failed", str(exc))
                return
            self.view.after(0, self._remote_file_downloaded,
                            panel, local_path)

        self._submit_transfer("open-remote-file", worker)

    def _remote_file_downloaded(self, panel, local_path):
        try:
            self._launch(local_path)
            panel.status.set("Opened {}".format(local_path.name))
        except OSError as exc:
            self.view.show_error("Open remote file failed", str(exc))

    def _file_clipboard_controller(self):
        component = getattr(self, "_file_clipboard", None)
        if component is None:
            component = FileClipboardController(self)
            self._file_clipboard = component
        return component

    def _clipboard_transfer_controller(self):
        component = getattr(self, "_clipboard_transfer", None)
        if component is None:
            component = ClipboardTransferController(self)
            self._clipboard_transfer = component
        return component

    def _cleanup_old_clipboard_cache(self):
        return self._file_clipboard_controller().cleanup_cache()

    def _reset_internal_clipboard(self):
        return self._file_clipboard_controller().reset()

    def _begin_internal_clipboard(self, panel_id, paths, move):
        return self._file_clipboard_controller().begin(panel_id, paths, move)

    @staticmethod
    def _clipboard_item_names(paths):
        return FileClipboardController.item_names(paths)

    def _publish_file_clipboard(self, panel, paths, move):
        return self._file_clipboard_controller().publish(panel, paths, move)

    def _prepare_server_file_clipboard(self, panel, remote_paths, move, generation, token):
        return self._file_clipboard_controller().prepare_server(panel, remote_paths, move, generation, token)

    def _server_clipboard_prepare_failed(self, panel, generation, stage_dir, dialog, error):
        return self._file_clipboard_controller().prepare_failed(panel, generation, stage_dir, dialog, error)

    def _server_clipboard_prepare_finished(self, panel, generation, token, start_sequence, remote_paths, staged_paths, move, stage_dir, dialog):
        return self._file_clipboard_controller().prepare_finished(panel, generation, token, start_sequence, remote_paths, staged_paths, move, stage_dir, dialog)

    def _monitor_server_cut_paste(self, remote_paths, staged_paths):
        return self._file_clipboard_controller().monitor_cut(remote_paths, staged_paths)

    def _server_cut_committed_to_explorer(self, count):
        return self._file_clipboard_controller().cut_committed(count)

    def _resolve_file_clipboard(self):
        return self._file_clipboard_controller().resolve()

    def _paste_file_clipboard(self, target_panel):
        return self._file_clipboard_controller().paste(target_panel)

    def _start_clipboard_transfer(self, target_panel, source_panel_id, sources, move, internal, source_sequence):
        return self._clipboard_transfer_controller().start(target_panel, source_panel_id, sources, move, internal, source_sequence)

    def _clipboard_transfer_failed(self, target_panel, progress_dialog, error):
        return self._clipboard_transfer_controller().failed(target_panel, progress_dialog, error)

    def _clipboard_transfer_finished(self, target_panel, progress_dialog, move, internal, source_sequence):
        return self._clipboard_transfer_controller().finished(target_panel, progress_dialog, move, internal, source_sequence)

    def _file_command_controller(self):
        component = getattr(self, "_file_commands", None)
        if component is None:
            component = FileCommandController(self)
            self._file_commands = component
        return component

    def command(self, panel, action, selected_paths=None):
        return self._file_command_controller().command(panel, action, selected_paths)

    @staticmethod
    def _delete_warning_message(paths, location):
        return FileCommandController._delete_warning_message(paths, location)

    def _delete_local_items(self, panel, paths):
        return self._file_command_controller()._delete_local_items(panel, paths)

    def _delete_server_items(self, panel, paths):
        return self._file_command_controller()._delete_server_items(panel, paths)

    def _server_delete_finished(self, panel, deleted_count):
        return self._file_command_controller()._server_delete_finished(panel, deleted_count)

    def _server_delete_failed(self, panel, error):
        return self._file_command_controller()._server_delete_failed(panel, error)

    def _job_submission_controller(self):
        component = getattr(self, "_job_submission", None)
        if component is None:
            component = JobSubmissionController(self)
            self._job_submission = component
        return component

    def run_job(self, panel):
        return self._job_submission_controller().run_job(panel)

    def _compute_job_cores(self, dialog, paths):
        return self._job_submission_controller()._compute_job_cores(dialog, paths)

    def _inp_analysis_controller(self):
        component = getattr(self, "_inp_analysis", None)
        if component is None:
            component = InpAnalysisController(self)
            self._inp_analysis = component
        return component

    def check_inp(self, panel):
        return self._inp_analysis_controller().check_inp(panel)

    def _inp_check_succeeded(self, panel, summary):
        return self._inp_analysis_controller()._inp_check_succeeded(panel, summary)

    def _inp_check_failed(self, panel, error):
        return self._inp_analysis_controller()._inp_check_failed(panel, error)

    def _odb_analysis_controller(self):
        component = getattr(self, "_odb_analysis", None)
        if component is None:
            component = OdbAnalysisController(self)
            self._odb_analysis = component
        return component

    def check_odb(self, panel, selected_paths=None):
        return self._odb_analysis_controller().check_odb(panel, selected_paths)

    def _odb_check_succeeded(self, panel, result):
        return self._odb_analysis_controller()._odb_check_succeeded(panel, result)

    def _odb_check_failed(self, panel, error):
        return self._odb_analysis_controller()._odb_check_failed(panel, error)

    def extract_odb(self, panel, selected_paths=None):
        return self._odb_analysis_controller().extract_odb(panel, selected_paths)

    def _odb_extract_catalog_ready(self, panel, path, catalog):
        return self._odb_analysis_controller()._odb_extract_catalog_ready(panel, path, catalog)

    def _extract_odb_selected(self, panel, path, selection):
        return self._odb_analysis_controller()._extract_odb_selected(panel, path, selection)

    def _odb_extract_succeeded(self, panel, result):
        return self._odb_analysis_controller()._odb_extract_succeeded(panel, result)

    def _odb_extract_failed(self, panel, error):
        return self._odb_analysis_controller()._odb_extract_failed(panel, error)

    def transfer_selected(self, source_panel, paths=None):
        return self._transfer_controller().transfer_selected(source_panel, paths)

    def quick_transfer(self, source_panel, extension):
        return self._transfer_controller().quick_transfer(source_panel, extension)

    def _quick_transfer_conflict_failed(self, source_panel, error):
        return self._transfer_controller().quick_conflict_failed(source_panel, error)

    def _quick_transfer_conflicts_ready(
            self, source_panel, target_panel, sources, destination,
            extension, action, conflicts):
        return self._transfer_controller().quick_conflicts_ready(
            source_panel, target_panel, sources, destination,
            extension, action, conflicts)

    def _continue_quick_transfer_after_overwrite(
            self, accepted, source_panel, target_panel, sources, destination,
            extension, action):
        return self._transfer_controller().continue_quick_after_overwrite(
            accepted, source_panel, target_panel, sources, destination,
            extension, action)

    def _start_quick_transfer(
            self, source_panel, target_panel, sources, destination,
            extension, action):
        return self._transfer_controller().start_quick_transfer(
            source_panel, target_panel, sources, destination,
            extension, action)

    def _submit_jobs(self, dialog, jobs):
        return self._job_submission_controller()._submit_jobs(dialog, jobs)

    def active_command(self, action):
        panel = next(
            (item for item in self.view.panels if item.is_focused),
            self.view.left,
        )
        self.command(panel, action)

    def _finish_inline_rename(self, panel, path, new_name):
        return self._file_command_controller()._finish_inline_rename(panel, path, new_name)

    def _complete_inline_rename(self, panel, renamed):
        return self._file_command_controller()._complete_inline_rename(panel, renamed)

    def _begin_created_rename(self, panel, created):
        return self._file_command_controller()._begin_created_rename(panel, created)

    def cancel(self):
        self.transfer_cancel.set()
        self._drag_target_panel = None
        self._drag_target_destination = None
        self._drag_target_point = None
        self._reset_internal_clipboard()
        self.view.clear_job_selection()
        for panel in self.view.panels:
            panel.clear_selection()
            panel.cancel_drag()
            panel.status.set("Operation cancelled" if panel.panel_id == "local" else
                             ("Connected to {}".format(self.server.host)
                              if self.server.connected else "SSH server disconnected"))

    def _opposite_panel(self, source_panel):
        return self._transfer_controller().opposite_panel(source_panel)

    def _process_queued_drop(
            self, source_panel, target_panel, destination, copy_requested,
            raw_sources, progress_dialog=None, cancel_event=None):
        return self._transfer_controller().process_queued_drop(
            source_panel, target_panel, destination, copy_requested,
            raw_sources, progress_dialog, cancel_event)

    def _drop_conflict_failed(self, source_panel, error, progress_dialog=None):
        return self._transfer_controller().drop_conflict_failed(
            source_panel, error, progress_dialog)

    def _drop_conflicts_ready(
            self, source_panel, target_panel, sources, destination,
            copy_requested, conflicts, progress_dialog=None,
            cancel_event=None):
        return self._transfer_controller().drop_conflicts_ready(
            source_panel, target_panel, sources, destination, copy_requested,
            conflicts, progress_dialog, cancel_event)

    @staticmethod
    def _format_conflict_message(conflicts):
        return TransferController.format_conflict_message(conflicts)

    def _continue_drop_after_overwrite(
            self, accepted, source_panel, target_panel, sources, destination,
            copy_requested, progress_dialog=None, cancel_event=None):
        return self._transfer_controller().continue_drop_after_overwrite(
            accepted, source_panel, target_panel, sources, destination,
            copy_requested, progress_dialog, cancel_event)

    def _start_drop_transfer(
            self, source_panel, target_panel, sources, destination,
            copy_requested, progress_dialog=None, cancel_event=None):
        return self._transfer_controller().start_drop_transfer(
            source_panel, target_panel, sources, destination, copy_requested,
            progress_dialog, cancel_event)

    def _cross_panel_conflicts(self, target_panel, sources, destination):
        return self._transfer_controller().cross_panel_conflicts(
            target_panel, sources, destination)

    def _drop_target(self, x_root, y_root):
        return self._transfer_controller().drop_target(x_root, y_root)

    def _drop_is_valid(self, source_panel, target_panel, sources, destination):
        return self._transfer_controller().drop_is_valid(
            source_panel, target_panel, sources, destination)

    def _transfer_failed(self, error, progress_dialog=None):
        return self._transfer_controller().transfer_failed(error, progress_dialog)

    def _transfer_succeeded(self, progress_dialog=None):
        return self._transfer_controller().transfer_succeeded(progress_dialog)

    def sort_changed(self, panel, column, descending):
        self.navigation_preferences.save_sort(
            panel.panel_id, column, descending)

    def _refresh_all(self):
        self.open_path(self.view.left, self.view.left.current_path, False)
        if self.server.connected:
            self.open_path(self.view.right, self.view.right.current_path, False)

    @staticmethod
    def _select_path(panel, path):
        panel.select_path(path)

    @staticmethod
    def _launch(path):
        return platform_integration.launch_path(path)
