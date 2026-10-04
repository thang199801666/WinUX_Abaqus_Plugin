"""Server Notepad opening, streaming and transactional-save coordination."""
from __future__ import annotations

import time
import threading
from pathlib import PurePosixPath

from ..services.server_text import RemoteTextConflictError


class _StreamCancelled(RuntimeError):
    pass


class ServerNotepadController:
    def __init__(self, app):
        self.app = app
        self._read_lock = threading.Lock()
        self._reads = {}

    def close(self):
        with self._read_lock:
            reads = tuple(self._reads.values())
            self._reads.clear()
        for cancel in reads:
            cancel.set()

    @property
    def view(self):
        return self.app.view

    @property
    def server(self):
        return self.app.server

    def edit(self, panel, selected_paths=None):
        """Queue one server-side text file in the standalone Server Notepad.

        The Tk window is created immediately.  It then requests queued files
        one-at-a-time, so SFTP reads and editor-buffer population are strictly
        sequential instead of preloading every selected/opened file.
        """
        if self.app._closing or panel.panel_id != "server":
            return
        paths = list(selected_paths or panel.selected_paths())
        if len(paths) != 1:
            self.view.show_error(
                "Server Notepad", "Select exactly one server file to edit.")
            return
        if not self.app._ensure_server_online():
            return

        path = self.server.normalize(paths[0])
        panel.status.set("Queued {} in Server Notepad...".format(path.name))
        try:
            self.view.show_server_notepad(
                path,
                on_load=self.app._load_server_notepad,
                on_save=self.app._save_server_notepad,
                on_reload=self.app._reload_server_notepad,
            )
        except Exception as exc:
            panel.status.set("Could not open Server Notepad")
            self.view.show_error("Server Notepad", str(exc))

    def load(self, dialog, path):
        return self._stream(dialog, path, "load", retry_missing=True)

    def reload(self, dialog, path):
        return self._stream(dialog, path, "reload", retry_missing=False)

    @staticmethod
    def _is_missing(error):
        if isinstance(error, FileNotFoundError):
            return True
        if isinstance(error, OSError) and getattr(error, "errno", None) == 2:
            return True
        text = str(error or "").casefold()
        return "[errno 2]" in text or "no such file" in text

    def _stream(self, dialog, path, operation, retry_missing):
        if self.app._closing or not dialog.winfo_exists():
            return
        if not self.server.connected:
            dialog.operation_failed("Server connection is not available", str(path), operation)
            return
        remote_path = self.server.normalize(path)
        connection = getattr(self.app, "_connection_generation", None)
        key = ("server-notepad-read", id(dialog), str(remote_path))
        cancel = threading.Event()
        with self._read_lock:
            previous = self._reads.get(key)
            if previous is not None:
                previous.set()
            self._reads[key] = cancel
        if operation == "load":
            self.view.right.status.set("Opening {} in Server Notepad...".format(remote_path.name))

        def check_live():
            if cancel.is_set() or self.app._closing or not dialog.winfo_exists():
                raise _StreamCancelled("Server Notepad read cancelled")
            if connection != getattr(self.app, "_connection_generation", None):
                raise RuntimeError("Server connection changed; reopen the file")

        def worker():
            started = time.perf_counter()
            final = {}

            def begin(metadata):
                check_live()
                if not dialog.stream_begin(operation, metadata):
                    raise RuntimeError("Server Notepad window is no longer available")

            def chunk(text, source_bytes):
                check_live()
                if not dialog.stream_chunk(operation, str(remote_path), text, source_bytes):
                    raise RuntimeError("Server Notepad window is no longer available")

            def end(metadata):
                check_live()
                compact = dict(metadata or {})
                compact["load_seconds"] = max(0.0, time.perf_counter() - started)
                final.update(compact)
                if not dialog.stream_end(operation, compact):
                    raise RuntimeError("Server Notepad window is no longer available")

            error = None
            try:
                for attempt in range(2 if retry_missing else 1):
                    check_live()
                    try:
                        self.server.stream_text_snapshot(remote_path, begin, chunk, end)
                        break
                    except Exception as exc:
                        if retry_missing and attempt == 0 and self._is_missing(exc):
                            # Cancellable, bounded retry for an atomic replace.
                            cancel.wait(0.15)
                            continue
                        raise
            except _StreamCancelled:
                cancel.set()
            except Exception as exc:
                error = "{}\n\nRemote path: {}".format(exc, remote_path)
            self.view.after(0, self._finish_read, key, cancel, dialog,
                            operation, str(remote_path), final, error, connection)

        handle = self.app._submit_background(
            "server-notepad-{}".format(operation), worker, key=key,
            replace=True, cancel_event=cancel)
        if getattr(handle, "state", None) == "rejected":
            self._finish_read(key, cancel, dialog, operation, str(remote_path), {},
                              "Background queue is full; try opening the file again", connection)

    def _finish_read(self, key, cancel, dialog, operation, path, snapshot, error, connection):
        with self._read_lock:
            if self._reads.get(key) is not cancel:
                return
            self._reads.pop(key, None)
        if cancel.is_set() or self.app._closing or not dialog.winfo_exists():
            return
        if connection != getattr(self.app, "_connection_generation", None):
            error = "Server connection changed; reopen the file"
        if error is not None:
            dialog.operation_failed(error, path, operation)
        elif operation == "load":
            self.app._server_notepad_stream_finished(dialog, snapshot)

    def stream_finished(self, dialog, snapshot):
        if self.app._closing or not dialog.winfo_exists():
            return
        path = PurePosixPath(str((snapshot or {}).get("path") or ""))
        self.view.right.status.set(
            "Editing {} directly on server".format(path.name))

    def loaded(self, dialog, snapshot):
        if self.app._closing or not dialog.winfo_exists():
            return
        path = PurePosixPath(str(snapshot.get("path") or ""))
        self.view.right.status.set(
            "Editing {} directly on server".format(path.name))
        dialog.load_succeeded(snapshot)

    def save(
            self, dialog, path, text, encoding, expected_signature, force):
        if self.app._closing:
            return
        if not self.server.connected:
            dialog.operation_failed("Server connection is not available")
            return
        connection = getattr(self.app, "_connection_generation", None)

        def worker():
            try:
                if self.app._closing:
                    return
                if connection != getattr(self.app, "_connection_generation", None):
                    raise RuntimeError("Server connection changed; reload the file before saving")
                snapshot = self.server.write_text_snapshot(
                    path, text, expected_signature, encoding=encoding,
                    force=force)
            except RemoteTextConflictError as exc:
                self.view.after(
                    0, dialog.save_conflict, str(exc), str(path))
                return
            except Exception as exc:
                self.view.after(
                    0, dialog.operation_failed, str(exc), str(path))
                return
            self.view.after(
                0, self.app._server_notepad_saved, dialog, snapshot)

        handle = self.app._submit_background(
            "server-notepad-save", worker,
            key=("server-notepad-save", id(dialog), str(path)), replace=False)
        if getattr(handle, "state", None) == "rejected" and dialog.winfo_exists():
            dialog.operation_failed("Background queue is full; try saving again", str(path), "save")

    def saved(self, dialog, snapshot):
        if self.app._closing:
            return
        if dialog.winfo_exists():
            dialog.save_succeeded(snapshot)
        # Saving may change Size/Modified columns in the visible server pane.
        if self.server.connected:
            self.app.open_path(
                self.view.right, self.view.right.current_path, False)

