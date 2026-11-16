"""SSH connection/session lifecycle orchestration for WinUx.

One successful login owns exactly one logical WinUx session.  SSH transport
repair/reconnect stays inside that same session; explicit login replacement or
logout invalidates the session generation so stale remote work cannot publish
into a different account/server context.
"""
from __future__ import annotations

import random
import threading
import time

from ..app.session import AppSessionManager, SessionState
from ..app.session_workspace import SessionWorkspaceRegistry
from ..diagnostics import log_event, log_exception
from ..preferences.general import GeneralPreferences
from ..preferences.login import LoginPreferences
from ..preferences.performance import PerformancePreferences
from ..services.inactivity_polling import UserInactivityPolicy
from ..services.ssh_server import SSHServerModel


class ConnectionController:
    """Own WinUx multi-session tabs and the active reconnect supervisor."""

    def __init__(self, app, adopt_existing=False):
        self.app = app
        if not adopt_existing or not hasattr(app, "_reconnect_lock"):
            app._reconnect_lock = threading.Lock()
        if not adopt_existing or not hasattr(app, "_reconnect_active"):
            app._reconnect_active = False
        if not adopt_existing or not hasattr(app, "_connection_online"):
            app._connection_online = threading.Event()
        if not hasattr(app, "session_manager"):
            app.session_manager = AppSessionManager(
                initial_generation=getattr(app, "_connection_generation", 0))
        if not hasattr(app, "_session_workspaces"):
            app._session_workspaces = SessionWorkspaceRegistry()
        if not adopt_existing or not hasattr(app, "_connection_generation"):
            app._connection_generation = app.session_manager.generation
        else:
            # SessionManager is now the source of truth.  Preserve a legacy
            # injected generation when adopting old test/controller state.
            app._connection_generation = app.session_manager.generation
        if not hasattr(app, "_inactivity_policy"):
            app._inactivity_policy = UserInactivityPolicy(
                settings=PerformancePreferences().load())

    @property
    def view(self):
        return self.app.view

    @property
    def server(self):
        return self.app.server

    @property
    def sessions(self):
        return self.app.session_manager

    @property
    def workspaces(self):
        return self.app._session_workspaces

    def _new_server(self):
        factory = getattr(self.app, "_session_server_factory", None)
        if callable(factory):
            return factory()
        # Production WinUx always uses SSHServerModel. Focused tests frequently
        # inject a no-argument fake; instantiate it when safe so multi-session
        # behavior can still be exercised without Paramiko.
        current = getattr(self.app, "server", None)
        if isinstance(current, SSHServerModel) or current is None:
            return SSHServerModel()
        try:
            return type(current)()
        except Exception:
            return current

    def session_snapshot(self):
        provider = getattr(self.app, "_session_runtime_snapshot", None)
        if callable(provider):
            return provider()
        return self.sessions.snapshot()

    def _sync_generation(self):
        self.app._connection_generation = self.sessions.generation
        return self.app._connection_generation

    def _publish_session_state(self):
        self._sync_generation()
        if self.app._closing:
            return
        snapshot = self.sessions.snapshot()
        setter = getattr(self.view, "set_session_state", None)
        if callable(setter):
            try:
                current = self.sessions.current
                setter(current.as_dict() if current is not None else None)
            except Exception:
                pass
        tabs = getattr(self.view, "set_session_tabs", None)
        if callable(tabs):
            try:
                tabs(snapshot)
            except Exception:
                pass

    def _capture_active_workspace(self):
        current = self.sessions.current
        if current is None:
            return None
        try:
            return self.workspaces.capture_view(
                self.view, current.session_id,
                remote_path=getattr(self.app, "_server_current_path", None))
        except Exception:
            return self.workspaces.get(current.session_id)

    def _deactivate_remote_runtime(
            self, *, session=None, clear_view=True, disconnect=False, server=None):
        """Release active UI/work ownership for one tab.

        Switching tabs deliberately keeps the tab's SSHServerModel alive while
        stopping polling/navigation/analysis work tied to the visible workspace.
        Closing a tab passes ``disconnect=True`` and tears down only that tab's
        transport.
        """
        try:
            self.app._stop_job_polling()
        except Exception:
            pass
        stop_plots = getattr(self.app, "_stop_all_job_plots", None)
        if callable(stop_plots):
            try:
                stop_plots()
            except Exception:
                pass

        scope = self.sessions.task_scope(session)
        if scope is not None:
            # Switching tabs invalidates visible/UI-bound work, but an active
            # file transfer belongs to the logical login session rather than
            # to the currently visible tab. Let it continue in the background.
            # Closing the session (disconnect=True) must still cancel it.
            task_managers = ["_background_tasks", "_analysis_tasks"]
            if disconnect:
                task_managers.append("_transfer_tasks")
            for name in task_managers:
                manager = getattr(self.app, name, None)
                cancel_scope = getattr(manager, "cancel_scope", None)
                if callable(cancel_scope):
                    try:
                        cancel_scope(scope)
                    except Exception:
                        pass

        # Never call the dialog-level cancel_all() here.  The transfer center is
        # shared by the whole application and may contain local-only work or
        # work owned by another login session.  Session-owned task lanes below
        # cancel only the matching scope.

        schedule = getattr(self.app, "_schedule_execution", None)
        reset_schedule = getattr(schedule, "reset_for_session", None)
        if callable(reset_schedule):
            try:
                reset_schedule()
            except Exception:
                pass

        notepad = getattr(self.app, "_server_notepad", None)
        close_notepad = getattr(notepad, "close", None)
        if callable(close_notepad):
            try:
                close_notepad()
            except Exception:
                pass

        self.app._connection_online.clear()
        self.app._server_nav_generation += 1
        with self.app._reconnect_lock:
            self.app._reconnect_active = False

        if disconnect:
            target_server = server or self.server
            try:
                target_server.request_shutdown(clear_identity=True)
            except TypeError:
                try:
                    target_server.request_shutdown()
                except Exception:
                    pass
            except Exception:
                pass

        if clear_view:
            clear = getattr(self.view, "clear_server_session", None)
            if callable(clear):
                try:
                    clear()
                except Exception:
                    pass
            else:
                try:
                    self.view.show_server_disconnected()
                except Exception:
                    pass

    def _retire_remote_runtime(
            self, *, session=None, clear_identity=True, clear_view=True):
        """Compatibility wrapper: fully close the active tab's runtime."""
        return self._deactivate_remote_runtime(
            session=session, clear_view=clear_view, disconnect=True,
            server=self.workspaces.server_for(getattr(session, "session_id", ""))
                   if session is not None else self.server)

    def auto_login_from_preferences(self):
        """Connect with the last DPAPI-protected login when enabled."""
        if self.app._closing or self.server.connected or self.sessions.has_session():
            return
        try:
            if not GeneralPreferences().load_auto_login():
                return
            saved = LoginPreferences().load()
        except Exception:
            return

        values = {
            "host": str(saved.get("host", "")).strip(),
            "port": str(saved.get("port", "22")).strip(),
            "username": str(saved.get("username", "")).strip(),
            "password": str(saved.get("password", "")),
            "remember": True,
        }
        if not values["host"] or not values["username"]:
            self.view.right.status.set("Auto login skipped: no saved account")
            return
        if not values["password"]:
            self.view.right.status.set("Auto login skipped: password not saved")
            return
        try:
            int(values["port"])
        except ValueError:
            self.view.right.status.set("Auto login skipped: invalid saved port")
            return

        self.view.right.status.set(
            "Connecting to {}...".format(values["host"])
        )
        self.login(None, values, automatic=True)

    def login(self, dialog, values, automatic=False):
        """Create a new Photoshop-style session tab and authenticate it."""
        if self.app._closing:
            return

        current = self.sessions.current
        if current is not None and current.state == SessionState.CONNECTING:
            message = "A login is already in progress."
            if dialog is not None:
                try:
                    if dialog.winfo_exists():
                        dialog.set_error(message)
                        return
                except Exception:
                    pass
            try:
                self.view.right.status.set(message)
            except Exception:
                pass
            return

        previous = self.sessions.current
        previous_server = self.server if previous is not None else None
        if previous is not None:
            self._capture_active_workspace()
            self._deactivate_remote_runtime(
                session=previous, clear_view=True, disconnect=False,
                server=previous_server)

        session = self.sessions.begin_tab_login(
            values.get("host"), values.get("port", 22), values.get("username"),
            automatic=automatic)
        server = self._new_server()
        self.workspaces.add(session.session_id, server)
        self.app.server = server
        self.app._server_current_path = None
        self._sync_generation()
        self._publish_session_state()
        try:
            self.view.right.status.set(
                "Connecting to {}...".format(session.host))
        except Exception:
            pass

        log_event(
            "SSH session tab {} login started for {}".format(
                session.short_id, session.account_label))

        def worker():
            try:
                try:
                    home = server.connect(
                        values["host"], values["port"], values["username"],
                        values["password"], session_id=session.session_id)
                except TypeError as exc:
                    if "session_id" not in str(exc):
                        raise
                    home = server.connect(
                        values["host"], values["port"], values["username"],
                        values["password"])
                    try:
                        server.session_id = session.session_id
                    except Exception:
                        pass
                if not self.sessions.is_open(session.session_id):
                    try:
                        server.request_shutdown(clear_identity=True)
                    except Exception:
                        pass
                    return
                requested_folder = str(values.get("remote_path") or "").strip()
                folder = requested_folder or self.app.navigation_preferences.load_server(
                    values["host"], values["username"])
                folder = server.normalize(folder) if folder else home
                try:
                    items = server.list_directory(folder)
                except OSError:
                    folder = home
                    items = server.list_directory(folder)
            except Exception as exc:
                self.view.after(
                    0, lambda error=str(exc), sid=session.session_id:
                    self.login_failed(dialog, error, automatic=automatic, session_id=sid))
                return
            self.view.after(
                0, lambda sid=session.session_id:
                self.login_succeeded(
                    dialog, folder, items, automatic=automatic, session_id=sid))

        # The login transaction belongs to the new tab but must be allowed to
        # finish independently of the current-token guard used by ordinary
        # remote operations. Closing the tab still cancels this scope.
        handle = self.app._submit_background(
            "ssh-login", worker, scope=session.task_scope)
        if getattr(handle, "state", None) == "rejected":
            self.login_failed(
                dialog, "Background queue is full; try again",
                automatic=automatic, session_id=session.session_id)

    def login_failed(self, dialog, error, automatic=False, session_id=None):
        current = self.sessions.current
        if session_id is None and current is not None:
            session_id = current.session_id
        if session_id is None or not self.sessions.is_open(session_id):
            return
        was_current = self.sessions.current_id == str(session_id)
        workspace = self.workspaces.get(session_id)
        ended = self.sessions.fail(session_id, error)
        self._sync_generation()
        if workspace is not None:
            try:
                workspace.server.request_shutdown(clear_identity=True)
            except Exception:
                pass
            self.workspaces.remove(session_id)
        if ended is not None:
            log_event(
                "SSH session tab {} login failed for {}".format(
                    ended.short_id, ended.account_label))
        if was_current:
            self._activate_fallback_session()
        else:
            self._publish_session_state()
        self._update_connection_indicator()
        if dialog is not None:
            try:
                if dialog.winfo_exists():
                    dialog.set_error("Login failed: {}".format(error))
                    return
            except Exception:
                pass
        if automatic and not self.sessions.current:
            self.view.show_server_disconnected()
            self.view.right.status.set("Auto login failed")

    def login_succeeded(
            self, dialog, folder, items, automatic=False, session_id=None):
        session_id = str(session_id or self.sessions.current_id or "")
        snapshot = self.sessions.get(session_id)
        workspace = self.workspaces.get(session_id)
        if snapshot is None or workspace is None:
            return
        server = workspace.server
        if getattr(server, "session_id", None) not in (None, session_id):
            return

        active = self.sessions.activate(
            session_id, home=server.home, current_path=folder)
        if active is None:
            return
        workspace.remote_path = folder
        workspace.directory_items = tuple(items or ())
        workspace.history = (folder,)
        workspace.history_index = 0
        log_event(
            "SSH session tab {} authenticated for {}".format(
                active.short_id, active.account_label))

        # Finish the Login QDialog visibility transaction before allowing the
        # session-tab strip to mutate the main retained tree.  set_session_tabs()
        # also serializes this boundary defensively, but ordering the producer
        # correctly keeps native multi-viewport presentation deterministic.
        if dialog is not None:
            try:
                if dialog.winfo_exists():
                    try:
                        dialog.save_preferences()
                    except Exception:
                        pass
                    dialog.grab_release()
                    try:
                        dialog.destroy(return_focus=True)
                    except TypeError:
                        dialog.destroy()
            except Exception:
                pass

        self._publish_session_state()

        # A login may finish after its tab ceased to be active in an injected
        # host. Cache the result but never paint it into another tab.
        if not self.sessions.is_current(session_id):
            return
        self.app.server = server
        self.app._server_current_path = folder
        self.app._connection_online.set()
        self.view.display_server_directory(
            folder, items, server.host, reset_history=True)
        self.app._flush_schedule_manifest_async()
        self.app._restore_shared_schedules()
        try:
            server.set_shell_directory(folder)
        except Exception:
            pass
        self.app.navigation_preferences.save_server(
            server.host, server.username, folder)
        self.app._start_job_polling()
        self._update_connection_indicator()

    def activate_session(self, session_id):
        """Switch the visible workspace to an already-open login tab."""
        session_id = str(session_id or "")
        target = self.sessions.get(session_id)
        workspace = self.workspaces.get(session_id)
        if target is None or workspace is None:
            return False
        current = self.sessions.current
        if current is not None and current.session_id == session_id:
            return True
        if current is not None and current.state == SessionState.CONNECTING:
            # Keep the authentication transaction deterministic. A connecting
            # tab becomes switchable immediately after success/failure.
            self._publish_session_state()
            return False

        if current is not None:
            self._capture_active_workspace()
            current_workspace = self.workspaces.get(current.session_id)
            self._deactivate_remote_runtime(
                session=current, clear_view=True, disconnect=False,
                server=current_workspace.server if current_workspace else self.server)

        selected = self.sessions.select(session_id)
        if selected is None:
            return False
        self.app.server = workspace.server
        self.app._server_current_path = (
            workspace.remote_path or selected.current_path or selected.home or None)
        self._sync_generation()
        connected = bool(getattr(workspace.server, "connected", False))
        self.workspaces.restore_view(self.view, selected, connected=connected)
        self._publish_session_state()

        if connected:
            selected = self.sessions.restore(
                session_id, home=workspace.server.home,
                current_path=self.app._server_current_path or workspace.server.home)
            self.app._connection_online.set()
            self._publish_session_state()
            try:
                self.app._flush_schedule_manifest_async()
                self.app._restore_shared_schedules()
            except Exception:
                pass
            try:
                self.app._start_job_polling()
            except Exception:
                pass
            # Cached rows make the tab switch immediate; refresh asynchronously
            # afterward so remote changes that occurred in the background appear.
            folder = self.app._server_current_path or workspace.server.home
            try:
                self.view.after_render(
                    self.app.open_path, self.view.right, folder, False)
            except Exception:
                pass
        elif getattr(workspace.server, "host", "") and getattr(workspace.server, "username", ""):
            self.start_reconnect()
        self._update_connection_indicator()
        return True

    def _activate_fallback_session(self, preferred_index=None):
        remaining = list(self.sessions.open_sessions())
        if not remaining:
            self.app.server = self._new_server()
            self.app._server_current_path = None
            self.app._connection_online.clear()
            try:
                self.view.clear_server_session()
                self.view.right.status.set("Not connected")
            except Exception:
                pass
            self._publish_session_state()
            return False
        index = len(remaining) - 1 if preferred_index is None else min(
            max(0, int(preferred_index)), len(remaining) - 1)
        return self.activate_session(remaining[index].session_id)

    def close_session(self, session_id):
        """Close exactly one session tab; sibling logins stay open."""
        session_id = str(session_id or "")
        target = self.sessions.get(session_id)
        workspace = self.workspaces.get(session_id)
        if target is None:
            return False
        index = self.sessions.index_of(session_id)
        was_current = self.sessions.current_id == session_id
        if was_current:
            self._capture_active_workspace()
            self._deactivate_remote_runtime(
                session=target, clear_view=True, disconnect=True,
                server=workspace.server if workspace else self.server)
        else:
            scope = self.sessions.task_scope(target)
            if scope is not None:
                for name in ("_background_tasks", "_transfer_tasks", "_analysis_tasks"):
                    manager = getattr(self.app, name, None)
                    cancel_scope = getattr(manager, "cancel_scope", None)
                    if callable(cancel_scope):
                        try:
                            cancel_scope(scope)
                        except Exception:
                            pass
            if workspace is not None:
                try:
                    workspace.server.request_shutdown(clear_identity=True)
                except Exception:
                    pass
        ended = self.sessions.close(session_id, reason="tab_closed")
        self.workspaces.remove(session_id)
        self._sync_generation()
        if ended is not None:
            log_event(
                "SSH session tab {} closed ({})".format(
                    ended.short_id, ended.account_label or "unknown account"))
        if was_current:
            self._activate_fallback_session(index)
        else:
            self._publish_session_state()
        return True

    def logout(self):
        """Log out/close the active session tab without closing WinUx."""
        current = self.sessions.current
        if current is None:
            return False
        return self.close_session(current.session_id)

    def start_reconnect(self):
        """Repair the current logical session; never create a new session id."""
        if self.app._closing:
            return
        current = self.sessions.current
        if current is None or current.state == SessionState.CONNECTING:
            return
        session_id = current.session_id
        generation = current.generation
        server = self.server

        self.view.after(0, self._update_connection_indicator)
        if not hasattr(self.app, "_connection_online"):
            self.app._connection_online = threading.Event()
        if server.connected:
            self.sessions.restore(
                session_id, home=server.home,
                current_path=self.app._server_current_path or server.home)
            self._publish_session_state()
            self.app._connection_online.set()
            return
        self.app._connection_online.clear()
        self.sessions.mark_reconnecting(session_id)
        self._publish_session_state()
        with self.app._reconnect_lock:
            if (self.app._reconnect_active or self.app._closing or
                    server.connected or
                    not self.sessions.is_current(session_id, generation=generation)):
                return
            self.app._reconnect_active = True

        def session_current():
            return (not self.app._closing and
                    self.sessions.is_current(session_id, generation=generation) and
                    generation == self.app._connection_generation)

        def worker():
            attempt = 0
            disconnected_notice_sent = False
            try:
                while session_current():
                    if server.connected:
                        self.app._connection_online.set()
                        self.view.after(0, self.restored, generation, session_id)
                        return

                    inactivity = self.app._inactivity_policy
                    inactivity.configure(PerformancePreferences().load())
                    if inactivity.stage() == inactivity.DEEP_IDLE:
                        resume_generation = inactivity.resume_generation
                        inactivity.wait_for_resume(resume_generation, timeout=30.0)
                        continue

                    attempt += 1
                    try:
                        server.reconnect()
                    except Exception as exc:
                        self.app._connection_online.clear()
                        self.sessions.mark_reconnecting(session_id, str(exc))
                        log_exception(
                            "SSH reconnect attempt {} failed".format(attempt),
                            (type(exc), exc, exc.__traceback__),
                        )
                        if not disconnected_notice_sent:
                            disconnected_notice_sent = True
                            try:
                                self.view.after(
                                    0, self.view.show_server_disconnected)
                            except Exception:
                                pass
                        base_delay = min(
                            3.0 * (2 ** min(attempt - 1, 5)), 60.0)
                        delay = base_delay * random.uniform(0.8, 1.2)
                        deadline = time.monotonic() + delay
                        while session_current() and time.monotonic() < deadline:
                            if server.connected:
                                self.app._connection_online.set()
                                self.view.after(
                                    0, self.restored, generation, session_id)
                                return
                            time.sleep(min(
                                0.25, max(0.0, deadline - time.monotonic())))
                        continue

                    if not session_current():
                        return
                    self.app._connection_online.set()
                    self.app._flush_schedule_manifest_async()
                    self.app._restore_shared_schedules()
                    self.app._schedule_wakeup.set()
                    wakeup = self.app._job_poll_wakeup
                    if wakeup is not None:
                        wakeup.set()
                    self.view.after(0, self.restored, generation, session_id)
                    return
            finally:
                with self.app._reconnect_lock:
                    self.app._reconnect_active = False

        submit = getattr(self.app, "_submit_remote_background", self.app._submit_background)
        handle = submit(
            "connection-supervisor", worker,
            key="connection-supervisor", coalesce=True)
        if handle.state == "rejected":
            with self.app._reconnect_lock:
                self.app._reconnect_active = False
            try:
                self.view.after(500, self.app._start_reconnect)
            except Exception:
                pass

    def ensure_online(self):
        """Return True when this session is usable; otherwise recover/show login."""
        current = self.sessions.current
        if current is None:
            self.app._connection_online.clear()
            self.view.show_login()
            return False
        if current.state == SessionState.CONNECTING:
            return False
        if self.server.connected:
            self.app._connection_online.set()
            if current.state != SessionState.ACTIVE:
                self.sessions.restore(
                    current.session_id, home=self.server.home,
                    current_path=self.app._server_current_path or self.server.home)
                self._publish_session_state()
            return True
        if self.server.host and self.server.username:
            self.app._connection_online.clear()
            self.app._start_reconnect()
            try:
                self.view.right.status.set("SSH disconnected - reconnecting...")
            except Exception:
                pass
            return False
        self.logout()
        self.view.show_login()
        return False

    def restored(self, generation, session_id=None):
        current = self.sessions.current
        if current is None:
            return
        session_id = session_id or current.session_id
        if (self.app._closing or
                generation != self.app._connection_generation or
                not self.sessions.is_current(session_id, generation=generation) or
                not self.server.connected):
            return
        restored = self.sessions.restore(
            session_id, home=self.server.home,
            current_path=self.app._server_current_path or self.server.home)
        if restored is None:
            return
        self._publish_session_state()
        self.app._connection_online.set()
        self._update_connection_indicator()
        self.app._schedule_wakeup.set()
        self.app._flush_schedule_manifest_async()
        folder = self.app._server_current_path or self.server.home
        self.app.open_path(self.view.right, folder, False)

    def _update_connection_indicator(self):
        """UI-thread delivery reads current state, never an old worker snapshot."""
        if self.app._closing:
            return
        setter = getattr(self.view, "set_server_connection_state", None)
        if callable(setter):
            manager = getattr(self.app, "session_manager", None)
            if manager is None:
                # Compatibility for focused legacy/injected controller tests.
                connected = bool(self.server.connected)
            else:
                current = manager.current
                connected = bool(
                    current is not None and current.state == SessionState.ACTIVE and
                    self.server.connected)
            setter(connected)
