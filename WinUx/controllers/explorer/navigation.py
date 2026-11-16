"""Startup and local/server directory navigation off the render thread."""
from __future__ import annotations

from pathlib import Path

from ...runtime.paths import safe_current_directory


class NavigationController:
    def __init__(self, app):
        self.app = app
        self._initial_focus_serial = None
        self._focus_serial_by_request = {}

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
        listview = getattr(getattr(self.view, "left", None), "listview", None)
        self._initial_focus_serial = (
            listview.interactionSerial() if listview is not None and hasattr(listview, "interactionSerial") else None
        )
        def worker():
            if self.app._closing or not self.app._initial_load_pending:
                return ("cancelled", None, None)
            current = safe_current_directory()
            path = self.app.initial_local
            try:
                usable = path.is_dir()
            except (OSError, ValueError):
                usable = False
            if not usable:
                path = current
            try:
                items = self.model.list_directory(path)
            except (OSError, ValueError):
                path = current
                try:
                    items = self.model.list_directory(path)
                except (OSError, ValueError) as exc:
                    return ("error", str(exc), None)
            return ("loaded", path, items)

        def completed(handle):
            # ``on_done`` is always delivered by the single UI dispatcher; the
            # filesystem worker never touches a retained widget directly.
            if self.app._closing or not self.app._initial_load_pending:
                return
            if handle.state == "failed":
                self.app._initial_local_failed(str(handle.exception or "Unable to load folder"))
                return
            result = handle.result
            if not isinstance(result, tuple) or not result:
                return
            status = result[0]
            if status == "loaded":
                self.app._initial_local_loaded(result[1], result[2])
            elif status == "error":
                self.app._initial_local_failed(str(result[1] or "Unable to load folder"))

        self.app._submit_background(
            "initial-local-load", worker, on_done=completed)

    def initial_loaded(self, path, items):
        if (self.app._closing or not self.app._initial_load_pending or
                not self.view.winfo_exists()):
            return
        self.app._initial_load_pending = False
        self.view.left.display(path, items)
        self.app.navigation_preferences.save_local(path)
        self.app._watch_local_path(path)
        listview = getattr(self.view.left, "listview", None)
        current_serial = (listview.interactionSerial()
                          if listview is not None and hasattr(listview, "interactionSerial") else None)
        if self._initial_focus_serial is None or current_serial == self._initial_focus_serial:
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
                server = self.server
                path = server.normalize(value)
                self.app._server_nav_generation += 1
                generation = self.app._server_nav_generation
                listview = getattr(panel, "listview", None)
                self._focus_serial_by_request[("server", generation)] = (
                    listview.interactionSerial() if listview is not None and hasattr(listview, "interactionSerial") else None)
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
                        return ("cancelled", None)
                    try:
                        items = server.list_directory(path)
                        if not self._server_request_current(generation, connection_generation):
                            return ("cancelled", None)
                        # Shell alignment is also wire I/O; keep it off the UI
                        # thread.  Failure is non-fatal for directory browsing.
                        try:
                            # rev30: do not inject automatic cd commands into the user SSH console.
                            pass
                        except Exception:
                            pass
                    except Exception as exc:
                        return ("error", str(exc))
                    return ("loaded", list(items))

                def completed(handle):
                    # BackgroundTaskManager marshals this callback through the
                    # one application UiDispatcher. The SSH worker never calls
                    # view.after()/retained UI APIs directly.
                    if not self._server_request_current(generation, connection_generation):
                        return
                    if handle.state == "failed":
                        self._deliver_server_error(
                            panel, path, generation, connection_generation,
                            str(handle.exception or "Unable to load server folder"))
                        return
                    result = handle.result
                    if not isinstance(result, tuple) or not result:
                        return
                    status, payload = result
                    if status == "loaded":
                        self._deliver_server_result(
                            panel, path, payload, bool(record_history),
                            generation, connection_generation)
                    elif status == "error":
                        self._deliver_server_error(
                            panel, path, generation, connection_generation,
                            str(payload or "Unable to load server folder"))

                submit = getattr(
                    self.app, "_submit_remote_background", self.app._submit_background)
                submit(
                    "server-navigation", worker, key="server-navigation",
                    replace=True, on_done=completed)
                return
            path = self.model.normalize(value)
            self.app._local_nav_generation += 1
            generation = self.app._local_nav_generation
            listview = getattr(panel, "listview", None)
            self._focus_serial_by_request[("local", generation)] = (
                listview.interactionSerial() if listview is not None and hasattr(listview, "interactionSerial") else None)
            try:
                panel.status.set("Loading {}...".format(path))
            except Exception:
                pass

            def local_worker():
                if self.app._closing or generation != self.app._local_nav_generation:
                    return ("cancelled", None)
                try:
                    # Even a file-vs-directory probe can block on a network
                    # drive. Keep every filesystem query off the UI thread.
                    if path.is_file():
                        return ("file", None)
                    items = self.model.list_directory(path)
                except (OSError, ValueError) as exc:
                    return ("error", str(exc))
                if self.app._closing or generation != self.app._local_nav_generation:
                    return ("cancelled", None)
                return ("loaded", list(items))

            def local_completed(handle):
                if self.app._closing or generation != self.app._local_nav_generation:
                    return
                if handle.state == "failed":
                    self.app._local_path_failed(
                        panel, path, generation,
                        str(handle.exception or "Unable to load folder"))
                    return
                result = handle.result
                if not isinstance(result, tuple) or not result:
                    return
                status, payload = result
                if status == "file":
                    self._launch_file(panel, path, generation)
                elif status == "loaded":
                    self.app._local_path_loaded(
                        panel, path, payload, bool(record_history), generation)
                elif status == "error":
                    self.app._local_path_failed(
                        panel, path, generation, str(payload or "Unable to load folder"))

            self.app._submit_background(
                "local-navigation", local_worker, key="local-navigation",
                replace=True, on_done=local_completed)
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
            listview = getattr(panel, "listview", None)
            if (path == getattr(panel, "current_path", None) and listview is not None
                    and any(bool(getattr(listview, name, False)) for name in (
                        "_rename_active", "_mouse_down", "_rubber_active",
                        "_drag_started", "_item_drag_active"))):
                # An SSH listing may finish while the user is editing/dragging.
                # Keep it off the live gesture; generation checks also discard
                # this retry if navigation or the connection changes meanwhile.
                self.view.after(120, self._deliver_server_result, panel, path,
                                items, record_history, generation, connection_generation)
                return
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

    def _may_restore_focus(self, panel, kind, generation):
        expected = self._focus_serial_by_request.pop((kind, generation), None)
        listview = getattr(panel, "listview", None)
        if expected is None or listview is None or not hasattr(listview, "interactionSerial"):
            return True
        return listview.interactionSerial() == expected

    def local_loaded(
            self, panel, path, items, record_history, generation):
        if (self.app._closing or generation != self.app._local_nav_generation or
                not self.view.winfo_exists()):
            return
        panel.display(path, items, bool(record_history))
        self.app.navigation_preferences.save_local(path)
        self.app._watch_local_path(path)
        if self._may_restore_focus(panel, "local", generation):
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
        same_directory = path == getattr(panel, "current_path", None)
        self.view.display_server_directory(
            path, items, self.server.host,
            record_history=bool(record_history))
        self.app._server_current_path = path
        manager = getattr(self.app, "session_manager", None)
        if manager is not None:
            try:
                manager.update_path(path)
            except Exception:
                pass
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
        if not same_directory and self._may_restore_focus(panel, "server", generation):
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
