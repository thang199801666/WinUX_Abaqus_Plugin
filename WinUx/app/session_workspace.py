"""Runtime resources owned by WinUx login-session tabs.

Session metadata lives in :mod:`WinUx.app.session`; this registry owns the
mutable runtime objects that must never leak between tabs (SSHServerModel,
Explorer snapshot, Job Viewer snapshot).  Passwords remain encapsulated by the
SSHServerModel and are never exposed by snapshots/diagnostics.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import PurePosixPath
import threading


@dataclass
class SessionWorkspace:
    session_id: str
    server: object
    remote_path: object = None
    directory_items: tuple = field(default_factory=tuple)
    history: tuple = field(default_factory=tuple)
    history_index: int = -1
    jobs: tuple = field(default_factory=tuple)

    def label(self, snapshot=None):
        if snapshot is not None:
            label = getattr(snapshot, "account_label", "")
            if label:
                return label
        host = str(getattr(self.server, "host", "") or "")
        username = str(getattr(self.server, "username", "") or "")
        return "{}@{}".format(username, host) if username and host else (host or username or self.session_id[:8])


class SessionWorkspaceRegistry:
    """Thread-safe map from logical session id to mutable runtime resources."""

    def __init__(self):
        self._lock = threading.RLock()
        self._items = {}

    def add(self, session_id, server):
        session_id = str(session_id)
        with self._lock:
            value = SessionWorkspace(session_id=session_id, server=server)
            self._items[session_id] = value
            return value

    def get(self, session_id):
        with self._lock:
            return self._items.get(str(session_id))

    def server_for(self, session_id):
        value = self.get(session_id)
        return None if value is None else value.server

    def remove(self, session_id):
        with self._lock:
            return self._items.pop(str(session_id), None)

    def values(self):
        with self._lock:
            return tuple(self._items.values())

    def capture_view(self, view, session_id, *, remote_path=None):
        value = self.get(session_id)
        if value is None or view is None:
            return value
        try:
            panel = view.right
            value.remote_path = remote_path if remote_path is not None else panel.current_path
            sources = []
            for item in tuple(getattr(panel, "_source_items", ()) or ()):
                source = (getattr(item, "data", None) or {}).get("source")
                if source is not None:
                    sources.append(source)
            value.directory_items = tuple(sources)
            value.history = tuple(getattr(panel, "history", ()) or ())
            value.history_index = int(getattr(panel, "history_index", -1) or -1)
        except Exception:
            pass
        try:
            value.jobs = tuple(getattr(view, "_compact_last_jobs", ()) or ())
        except Exception:
            pass
        return value

    def restore_view(self, view, snapshot, *, connected=False):
        value = self.get(getattr(snapshot, "session_id", ""))
        if value is None or view is None:
            return False
        path = value.remote_path or getattr(snapshot, "current_path", "") or getattr(snapshot, "home", "")
        if not path:
            path = PurePosixPath("/")
        items = tuple(value.directory_items or ())
        try:
            if items:
                view.display_server_directory(
                    path, items, getattr(snapshot, "host", ""),
                    reset_history=True, record_history=False)
                view.right.history = list(value.history)
                view.right.history_index = int(value.history_index)
            else:
                view.clear_server_session()
                try:
                    view.right.current_path = path
                    if view.right.toolbar:
                        view.right.toolbar.set_path_text(str(path))
                except Exception:
                    pass
            view.set_server_connection_state(bool(connected))
            if not connected:
                try:
                    view.right.status.set("Disconnected - select tab to reconnect")
                except Exception:
                    pass
        except Exception:
            return False
        try:
            view.display_jobs(value.jobs)
        except Exception:
            pass
        return True


__all__ = ["SessionWorkspace", "SessionWorkspaceRegistry"]
