"""Debounced local-directory refresh and watcher lifecycle coordination."""
from __future__ import annotations

import os
import threading
from pathlib import Path

from ..diagnostics import log_event
from ..services.local_file_watcher import LocalFileSystemWatcher


class LocalWatchController:
    def __init__(self, app, watcher=None):
        self.app = app
        self._lock = threading.RLock()
        self._install_lock = threading.Lock()
        self._generation = 0
        self._path = None
        self._scheduled = False
        self._active = False
        self._pending = False
        self._watcher = watcher or LocalFileSystemWatcher(on_error=self.report_error)

    @property
    def view(self):
        return self.app.view

    @property
    def model(self):
        return self.app.model

    @staticmethod
    def same_path(first, second):
        try:
            left = os.path.normcase(os.path.abspath(os.fspath(first)))
            right = os.path.normcase(os.path.abspath(os.fspath(second)))
        except (TypeError, ValueError):
            return False
        return left == right

    def watch(self, path):
        if self.app._closing:
            return
        target = Path(path)
        with self._lock:
            if (self.same_path(target, self._path) and
                    self._watcher.running):
                return
            self._generation += 1
            generation = self._generation
            self._path = target
            self._scheduled = False
            self._active = False
            self._pending = False

        # Signalling is non-blocking. Validation and joining an old native
        # watcher belong to the bounded worker pool, never the render thread.
        self._watcher.close(wait=False)
        def install():
            with self._install_lock:
                if not self._is_current(generation):
                    return
                try:
                    self._watcher.watch(
                        target, lambda changed_path: self.changed(changed_path, generation))
                except (OSError, ValueError) as exc:
                    self.report_error(target, exc)
                finally:
                    if not self._is_current(generation):
                        self._watcher.close(wait=False)
        handle = self.app._submit_background(
            "local-watch-install", install, key="local-watch-install", replace=True)
        if getattr(handle, "state", None) == "rejected":
            self.report_error(target, RuntimeError("Background queue is full"))

    def _is_current(self, generation):
        return not self.app._closing and generation == self._generation

    def stop(self, wait=True):
        with self._lock:
            self._generation += 1
            self._path = None
            self._scheduled = False
            self._active = False
            self._pending = False
        # Shutdown uses wait=False. An in-flight install notices the changed
        # generation and releases its watcher before leaving the worker.
        self._watcher.close(wait=wait)

    def report_error(self, path, error):
        log_event(
            "Local directory watcher stopped for {}: {}".format(path, error)
        )
        if self.app._closing or not hasattr(self.app, "view"):
            return

        def report():
            if (self.app._closing or
                    not self.same_path(
                        path, getattr(self.view.left, "current_path", None))):
                return
            self.view.left.status.set("Folder watcher unavailable")

        self.view.after(0, report)

    def changed(self, path, generation):
        """Coalesce native watcher bursts without touching DPG off-thread."""
        with self._lock:
            if (not self._is_current(generation) or
                    not self.same_path(path, self._path)):
                return
            self._pending = True
            if (self._scheduled or
                    self._active):
                return
            self._scheduled = True
        self.view.after(
            self.app.LOCAL_WATCH_DEBOUNCE_MS,
            self.begin_refresh,
            Path(path),
            generation,
        )

    def is_busy(self):
        listview = getattr(getattr(self.view, "left", None), "listview", None)
        if listview is None:
            return False
        return any(bool(getattr(listview, name, False)) for name in (
            "_rename_active",
            "_mouse_down",
            "_rubber_active",
            "_drag_started",
            "_item_drag_active",
        ))

    def begin_refresh(self, path, generation):
        if self.app._closing:
            return
        with self._lock:
            if generation != self._generation:
                return
            if not self.same_path(
                    path, getattr(self.view.left, "current_path", None)):
                self._scheduled = False
                self._pending = False
                return
            if self._active:
                self._scheduled = False
                self._pending = True
                return
            if self.is_busy():
                self._scheduled = True
                self.view.after(
                    self.app.LOCAL_WATCH_BUSY_RETRY_MS,
                    self.begin_refresh,
                    path,
                    generation,
                )
                return
            self._scheduled = False
            self._active = True
            self._pending = False

        def worker():
            if not self._is_current(generation):
                return
            try:
                items = self.model.list_directory(path)
                error = None
            except (OSError, ValueError) as exc:
                items = None
                error = exc
            self.view.after(
                0,
                self.complete_refresh,
                path,
                generation,
                items,
                error,
            )

        handle = self.app._submit_background(
            "local-watch-refresh", worker, key=("local-watch-refresh", generation),
            coalesce=True)
        if getattr(handle, "state", None) == "rejected":
            with self._lock:
                if not self._is_current(generation):
                    return
                self._active = False
            self.changed(path, generation)

    def complete_refresh(
            self, path, generation, items, error):
        if self.app._closing:
            return
        with self._lock:
            if generation != self._generation:
                return
            if (self.same_path(path, getattr(self.view.left, "current_path", None))
                    and self.is_busy()):
                # A rename/drag may begin after the read started. Keep the
                # completed snapshot out of the active editor until it exits.
                self.view.after(self.app.LOCAL_WATCH_BUSY_RETRY_MS,
                                self.complete_refresh, path, generation, items, error)
                return
            self._active = False
            pending = self._pending
            self._pending = False

        if self.same_path(
                path, getattr(self.view.left, "current_path", None)):
            if error is None and items is not None:
                scroll_y = self.view.left.refresh_directory(path, items)
                if scroll_y is not None:
                    # set_items() can finalize its scroll range one frame later.
                    self.view.after(0, self._restore_scroll, path, generation, scroll_y)
                    self.view.after(40, self._restore_scroll, path, generation, scroll_y)
            elif isinstance(error, (FileNotFoundError, NotADirectoryError)):
                self.view.left.status.set("Current folder is no longer available")

        if pending:
            with self._lock:
                if (generation != self._generation or
                        self._scheduled or
                        self._active):
                    return
                self._scheduled = True
            self.view.after(
                self.app.LOCAL_WATCH_DEBOUNCE_MS,
                self.begin_refresh,
                path,
                generation,
            )

    def _restore_scroll(self, path, generation, scroll_y):
        if (self._is_current(generation) and
                self.same_path(path, getattr(self.view.left, "current_path", None))):
            self.view.left.restore_vertical_scroll(scroll_y)

