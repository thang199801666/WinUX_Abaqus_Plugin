"""Startup and local/server directory navigation off the render thread."""
from __future__ import annotations

from pathlib import Path


class NavigationController:
    def __init__(self, app):
        self.app = app

    @property
    def view(self):
        return self.app.view

    @property
    def model(self):
        return self.app.model

    @property
    def server(self):
        return self.app.server

    def load_initial(self):
        def worker():
            if self.app._closing or not self.app._initial_load_pending:
                return
            current = Path.cwd()
            path = self.app.initial_local
            if not path.is_dir():
                path = current
            try:
                items = self.model.list_directory(path)
            except OSError:
                path = current
                try:
                    items = self.model.list_directory(path)
                except OSError as exc:
                    self.view.after(
                        0, lambda error=str(exc): self.app._initial_local_failed(error))
                    return
            self.view.after(
                0, lambda loaded_path=path, loaded_items=items:
                self.app._initial_local_loaded(loaded_path, loaded_items))

        self.app._submit_background("initial-local-load", worker)

    def initial_loaded(self, path, items):
        if (self.app._closing or not self.app._initial_load_pending or
                not self.view.winfo_exists()):
            return
        self.app._initial_load_pending = False
        self.view.left.display(path, items)
        self.app.navigation_preferences.save_local(path)
        self.app._watch_local_path(path)
        self.view.left.focus()

    def initial_failed(self, error):
        if (self.app._closing or not self.app._initial_load_pending or
                not self.view.winfo_exists()):
            return
        self.app._initial_load_pending = False
        self.view.left.status.set("Unable to load folder")
        self.view.show_error("WinUx", error)

    def open(self, panel, value, record_history=True):
        if self.app._closing:
            return
        if panel.panel_id == "local":
            # A user navigation wins over a still-running startup load.
            self.app._initial_load_pending = False
        try:
            if panel.panel_id == "server":
                if not self.app._ensure_server_online():
                    return
                path = self.server.normalize(value)
                self.app._server_nav_generation += 1
                generation = self.app._server_nav_generation
                connection_generation = getattr(self.app, "_connection_generation", None)
                try:
                    panel.status.set("Loading {}...".format(path))
                except Exception:
                    pass

                def worker():
                    # Skip obsolete requests before they enter the serialized
                    # SSH operation queue.  This keeps rapid Back/Refresh
                    # clicks from creating unnecessary network backlog.
                    if not self._server_request_current(generation, connection_generation):
                        return
                    try:
                        items = self.server.list_directory(path)
                        if not self._server_request_current(generation, connection_generation):
                            return
                        # Shell alignment is also wire I/O; keep it off the UI
                        # thread.  Failure is non-fatal for directory browsing.
                        try:
                            # rev30: do not inject automatic cd commands into the user SSH console.
                            pass
                        except Exception:
                            pass
                    except Exception as exc:
                        self.view.after(
                            0, self._deliver_server_error, panel, path,
                            generation, connection_generation, str(exc))
                        return
                    self.view.after(
                        0, self._deliver_server_result, panel, path, list(items),
                        bool(record_history), generation, connection_generation)

                self.app._submit_background(
                    "server-navigation", worker, key="server-navigation",
                    replace=True)
                return
            path = self.model.normalize(value)
            self.app._local_nav_generation += 1
            generation = self.app._local_nav_generation
            try:
                panel.status.set("Loading {}...".format(path))
            except Exception:
                pass

            def local_worker():
                if self.app._closing or generation != self.app._local_nav_generation:
                    return
                try:
                    # Even a file-vs-directory probe can block on a network
                    # drive. Keep every filesystem query off the UI thread.
                    if path.is_file():
                        self.view.after(0, self._launch_file, panel, path, generation)
                        return
                    items = self.model.list_directory(path)
                except (OSError, ValueError) as exc:
                    self.view.after(
                        0, self.app._local_path_failed, panel, path, generation,
                        str(exc))
                    return
                if self.app._closing or generation != self.app._local_nav_generation:
                    return
                self.view.after(
                    0, self.app._local_path_loaded, panel, path, list(items),
                    bool(record_history), generation)

            self.app._submit_background(
                "local-navigation", local_worker, key="local-navigation",
                replace=True)
        except (OSError, ValueError) as exc:
            self.view.show_error("WinUx", str(exc))

    def _server_request_current(self, generation, connection_generation):
        return (
            not self.app._closing
            and generation == self.app._server_nav_generation
            and connection_generation == getattr(self.app, "_connection_generation", None)
        )

    def _deliver_server_result(self, panel, path, items, record_history,
                               generation, connection_generation):
        if self._server_request_current(generation, connection_generation):
            self.app._server_path_loaded(panel, path, items, record_history, generation)

    def _deliver_server_error(self, panel, path, generation, connection_generation, error):
        if self._server_request_current(generation, connection_generation):
            self.app._server_path_failed(panel, path, generation, error)

    def _launch_file(self, panel, path, generation):
        if self.app._closing or generation != self.app._local_nav_generation:
            return
        try:
            self.app._launch(path)
            panel.status.set("Opened {}".format(path.name))
        except (OSError, ValueError) as exc:
            self.view.show_error("WinUx", str(exc))

    def local_loaded(
            self, panel, path, items, record_history, generation):
        if (self.app._closing or generation != self.app._local_nav_generation or
                not self.view.winfo_exists()):
            return
        panel.display(path, items, bool(record_history))
        self.app.navigation_preferences.save_local(path)
        self.app._watch_local_path(path)
        try:
            panel.focus()
        except Exception:
            pass

    def local_failed(self, panel, path, generation, error):
        if (self.app._closing or generation != self.app._local_nav_generation or
                not self.view.winfo_exists()):
            return
        try:
            panel.status.set("Local refresh failed")
        except Exception:
            pass
        self.view.show_error(
            "WinUx", "Could not load {}:\n{}".format(path, error))

    def server_loaded(
            self, panel, path, items, record_history, generation):
        if (self.app._closing or generation != self.app._server_nav_generation or
                not self.server.connected or not self.view.winfo_exists()):
            return
        self.view.display_server_directory(
            path, items, self.server.host,
            record_history=bool(record_history))
        self.app._server_current_path = path
        # Keep the interactive SSH console cwd aligned with the folder shown in
        # Server Files. The model suppresses only this app-generated command
        # echo; the resulting shell prompt remains visible.
        try:
            self.server.set_shell_directory(path)
        except Exception:
            # Directory browsing must remain usable even if the interactive
            # shell is temporarily unavailable during reconnect.
            pass
        self.app.navigation_preferences.save_server(
            self.server.host, self.server.username, path)
        try:
            panel.focus()
        except Exception:
            pass

    def server_failed(self, panel, path, generation, error):
        if (self.app._closing or generation != self.app._server_nav_generation or
                not self.view.winfo_exists()):
            return
        try:
            panel.status.set("Server refresh failed")
        except Exception:
            pass
        if not self.server.connected:
            self.app._start_reconnect()
            return
        self.view.show_error(
            "WinUx", "Could not load {}:\n{}".format(path, error))

