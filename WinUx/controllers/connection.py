"""SSH connection lifecycle orchestration for WinUx.

The public :class:`WinUXController` remains the compatibility facade.  This
component owns auto-login, explicit login and the single reconnect supervisor
while publishing the historical state attributes on the facade so existing
callbacks/components continue to work unchanged.
"""
from __future__ import annotations

import random
import threading
import time

from ..diagnostics import log_exception
from ..general_preferences import GeneralPreferences
from ..login_preferences import LoginPreferences


class ConnectionController:
    """Own the single SSH login/reconnect lifecycle."""

    def __init__(self, app, adopt_existing=False):
        self.app = app
        if not adopt_existing or not hasattr(app, "_reconnect_lock"):
            app._reconnect_lock = threading.Lock()
        if not adopt_existing or not hasattr(app, "_reconnect_active"):
            app._reconnect_active = False
        if not adopt_existing or not hasattr(app, "_connection_online"):
            app._connection_online = threading.Event()
        if not adopt_existing or not hasattr(app, "_connection_generation"):
            app._connection_generation = 0

    @property
    def view(self):
        return self.app.view

    @property
    def server(self):
        return self.app.server

    def auto_login_from_preferences(self):
        """Connect with the last DPAPI-protected login when enabled."""
        if self.app._closing or self.server.connected:
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
        # Connecting replaces the existing SSH client, so stop its polling
        # worker before the login thread closes that connection.
        self.app._stop_job_polling()
        with self.app._reconnect_lock:
            self.app._connection_generation += 1
        self.app._connection_online.clear()

        def worker():
            try:
                home = self.server.connect(
                    values["host"], values["port"], values["username"],
                    values["password"])
                requested_folder = str(values.get("remote_path") or "").strip()
                folder = requested_folder or self.app.navigation_preferences.load_server(
                    values["host"], values["username"])
                folder = self.server.normalize(folder) if folder else home
                try:
                    items = self.server.list_directory(folder)
                except OSError:
                    folder = home
                    items = self.server.list_directory(folder)
            except Exception as exc:
                self.view.after(
                    0,
                    lambda error=str(exc): self.login_failed(
                        dialog, error, automatic=automatic
                    ),
                )
                return
            self.view.after(
                0,
                lambda: self.login_succeeded(
                    dialog, folder, items, automatic=automatic
                ),
            )

        self.app._submit_background("ssh-login", worker)

    def login_failed(self, dialog, error, automatic=False):
        self.app._connection_online.clear()
        if dialog is not None:
            try:
                if dialog.winfo_exists():
                    dialog.set_error("Login failed: {}".format(error))
                    return
            except Exception:
                pass
        if automatic:
            self.view.show_server_disconnected()
            self.view.right.status.set("Auto login failed")

    def login_succeeded(self, dialog, folder, items, automatic=False):
        self.app._connection_online.set()
        if dialog is not None:
            try:
                if dialog.winfo_exists():
                    try:
                        dialog.save_preferences()
                    except Exception:
                        # A profile/DPAPI write failure must not turn a successful
                        # SSH connection into a failed login or leave a modal open.
                        pass
                    dialog.grab_release()
                    # Successful Login is a user-completed modal workflow: if
                    # the login dialog still owns foreground focus, return that
                    # focus to WinUx after the child HWND disappears.  The
                    # dialog controller deliberately avoids doing this for
                    # generic closes so Alt-Tab and modeless workflows remain
                    # non-intrusive.
                    try:
                        dialog.destroy(return_focus=True)
                    except TypeError:
                        # Compatibility with legacy/injected dialog adapters.
                        dialog.destroy()
            except Exception:
                pass
        self.view.display_server_directory(
            folder, items, self.server.host, reset_history=True)
        self.app._server_current_path = folder
        self.app._flush_schedule_manifest_async()
        self.app._restore_shared_schedules()
        # The folder shown immediately after login is loaded directly here
        # rather than through NavigationController.server_loaded().  Keep the
        # interactive console in sync at startup as well, otherwise the path
        # bar can show Batch-3 while the shell remains at ~ or its parent.
        try:
            self.server.set_shell_directory(folder)
        except Exception:
            pass
        self.app.navigation_preferences.save_server(
            self.server.host, self.server.username, folder)
        self.app._start_job_polling()

    def start_reconnect(self):
        """Start the one clean connection supervisor for an established login.

        The supervisor never gives up while WinUx is open. A healthy Transport
        is repaired in-place by ``server.reconnect()`` (for example reopening
        SFTP); a new TCP/SSH login is created only when the Transport is truly
        dead. All other features remain offline and wait for this supervisor.
        """
        if self.app._closing:
            return
        if not hasattr(self.app, "_connection_online"):
            self.app._connection_online = threading.Event()
        if self.server.connected:
            self.app._connection_online.set()
            return
        self.app._connection_online.clear()
        with self.app._reconnect_lock:
            if (self.app._reconnect_active or self.app._closing or
                    self.server.connected):
                return
            self.app._reconnect_active = True
            generation = self.app._connection_generation

        def worker():
            attempt = 0
            disconnected_notice_sent = False
            try:
                while (not self.app._closing and
                       generation == self.app._connection_generation):
                    if self.server.connected:
                        self.app._connection_online.set()
                        self.view.after(0, self.restored, generation)
                        return
                    attempt += 1
                    try:
                        self.server.reconnect()
                    except Exception as exc:
                        self.app._connection_online.clear()
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
                        # Exponential backoff with a ceiling. The supervisor
                        # continues indefinitely, but never hammers sshd.
                        base_delay = min(
                            3.0 * (2 ** min(attempt - 1, 5)), 60.0)
                        delay = base_delay * random.uniform(0.8, 1.2)
                        deadline = time.monotonic() + delay
                        while (not self.app._closing and
                               generation == self.app._connection_generation and
                               time.monotonic() < deadline):
                            # Another operation may have repaired the same
                            # session while the supervisor is backing off.
                            if self.server.connected:
                                self.app._connection_online.set()
                                self.view.after(0, self.restored, generation)
                                return
                            time.sleep(min(
                                0.25, max(0.0, deadline - time.monotonic())))
                        continue

                    self.app._connection_online.set()
                    # Flush locally durable schedule mutations, then rehydrate
                    # shared schedules. Overdue entries are catch-up work, not
                    # expired work.
                    self.app._flush_schedule_manifest_async()
                    self.app._restore_shared_schedules()
                    self.app._schedule_wakeup.set()
                    wakeup = self.app._job_poll_wakeup
                    if wakeup is not None:
                        wakeup.set()
                    self.view.after(0, self.restored, generation)
                    return
            finally:
                with self.app._reconnect_lock:
                    self.app._reconnect_active = False

        handle = self.app._submit_background(
            "connection-supervisor", worker,
            key="connection-supervisor", coalesce=True)
        if handle.state == "rejected":
            # The bounded worker queue can be saturated during a burst of UI
            # work. Do not leave the supervisor latched active when its worker
            # never started; schedule a lightweight retry on the UI loop.
            with self.app._reconnect_lock:
                self.app._reconnect_active = False
            try:
                self.view.after(500, self.app._start_reconnect)
            except Exception:
                pass

    def ensure_online(self):
        """Return True when usable; otherwise start transparent recovery."""
        if self.server.connected:
            self.app._connection_online.set()
            return True
        if self.server.host and self.server.username:
            self.app._connection_online.clear()
            self.app._start_reconnect()
            try:
                self.view.right.status.set("SSH disconnected - reconnecting...")
            except Exception:
                pass
            return False
        self.view.show_login()
        return False

    def restored(self, generation):
        if (self.app._closing or
                generation != self.app._connection_generation or
                not self.server.connected):
            return
        self.app._connection_online.set()
        self.app._schedule_wakeup.set()
        self.app._flush_schedule_manifest_async()
        folder = self.app._server_current_path or self.server.home
        # Never perform wire I/O from Dear PyGui's render thread. A reconnect
        # can complete while a transfer owns the serialized SSH lock.
        self.app.open_path(self.view.right, folder, False)
