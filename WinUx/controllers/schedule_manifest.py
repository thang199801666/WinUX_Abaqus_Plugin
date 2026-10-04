"""Durable shared schedule manifest coordination.

The application keeps scheduled run/delete execution in the main job scheduler
for now.  This component owns only the persistence boundary: the local recovery
journal, serialized remote manifest access and reconnect-safe flush/restore.
Keeping persistence separate avoids coupling durable state recovery to the UI
controller while preserving the existing scheduler execution semantics.
"""
from __future__ import annotations

import threading
from pathlib import Path, PurePosixPath

from ..diagnostics import log_event, log_exception
from ..preferences.storage import JsonPreferenceStore


class ScheduleManifestController:
    """Own local recovery + remote shared schedule manifest state."""

    def __init__(self, app):
        self.app = app
        self._manifest_lock = threading.Lock()
        self._queue_lock = threading.RLock()
        self._recovery_store = JsonPreferenceStore("schedule_recovery.json")
        recovery = self._recovery_store.load()
        saves = recovery.get("pending_saves", {})
        removals = recovery.get("pending_removals", [])
        self._pending_saves = dict(saves) if isinstance(saves, dict) else {}
        self._pending_removals = set(str(value) for value in removals if value)

    @property
    def server(self):
        return self.app.server

    @property
    def view(self):
        return self.app.view

    def manifest_entry(self, task, kind):
        def serializable(value):
            if isinstance(value, (Path, PurePosixPath)):
                return str(value)
            if isinstance(value, dict):
                return {
                    str(key): serializable(item)
                    for key, item in value.items()
                }
            if isinstance(value, (list, tuple)):
                return [serializable(item) for item in value]
            return value

        entry = {
            "schedule_id": task.get("schedule_id"),
            "kind": kind,
            "job_name": task.get("job_name", ""),
            "owner": task.get("owner", self.server.username),
            "target": task["target"].isoformat(),
            "mode": task.get("mode", ""),
            "status": "Waiting",
        }
        if kind == "run":
            entry.update({"path": str(task["path"]), "job": serializable(task["job"])})
        else:
            entry["job_id"] = str(task["job_id"])
        return entry

    def persist_recovery_queue(self):
        with self._queue_lock:
            payload = {
                "pending_saves": dict(self._pending_saves),
                "pending_removals": sorted(self._pending_removals),
            }
        self._recovery_store.save(payload, suppress_errors=True)

    def flush_async(self):
        """Flush queued mutations when the application's one SSH session is online."""
        if self.app._closing:
            return

        def worker():
            if self.app._closing:
                return
            if not self.server.connected:
                self.app._connection_online.clear()
                self.app._start_reconnect()
                return
            with self._queue_lock:
                saves = dict(self._pending_saves)
                removals = set(self._pending_removals)
            if not saves and not removals:
                return
            try:
                with self._manifest_lock:
                    self.server.ensure_schedule_storage()
                    entries = self.server.read_schedule_manifest()
                    changed_ids = set(removals) | set(saves)
                    entries = [
                        item
                        for item in entries
                        if str(item.get("schedule_id") or "") not in changed_ids
                    ]
                    entries.extend(saves.values())
                    self.server.write_schedule_manifest(entries)
            except Exception as exc:
                log_exception(
                    "Could not synchronize schedule manifest",
                    (type(exc), exc, exc.__traceback__),
                )
                if not self.server.connected:
                    self.app._connection_online.clear()
                    self.app._start_reconnect()
                else:
                    try:
                        self.view.after(2000, self.flush_async)
                    except Exception:
                        pass
                return

            with self._queue_lock:
                for schedule_id, entry in saves.items():
                    if self._pending_saves.get(schedule_id) == entry:
                        self._pending_saves.pop(schedule_id, None)
                for schedule_id in removals:
                    self._pending_removals.discard(schedule_id)
            self.persist_recovery_queue()

        handle = self.app._submit_background(
            "sync-schedules", worker, key="sync-schedules", coalesce=True
        )
        if handle.state == "rejected":
            # The local journal remains authoritative; retry once bounded worker
            # capacity returns rather than relying on another user action.
            try:
                self.view.after(1000, self.flush_async)
            except Exception:
                pass

    def save(self, task, kind):
        schedule_id = str(task.get("schedule_id") or "")
        if not schedule_id:
            return False
        entry = self.manifest_entry(task, kind)
        with self._queue_lock:
            self._pending_removals.discard(schedule_id)
            self._pending_saves[schedule_id] = entry
        self.persist_recovery_queue()
        self.flush_async()
        return True

    def remove(self, schedule_id):
        schedule_id = str(schedule_id or "")
        if not schedule_id:
            return
        with self._queue_lock:
            self._pending_saves.pop(schedule_id, None)
            self._pending_removals.add(schedule_id)
        self.persist_recovery_queue()
        self.flush_async()

    def restore(self):
        def worker():
            with self._queue_lock:
                pending_saves = dict(self._pending_saves)
                pending_removals = set(self._pending_removals)
            entries = []
            if self.server.connected:
                try:
                    with self._manifest_lock:
                        self.server.ensure_schedule_storage()
                        entries = self.server.read_schedule_manifest()
                except Exception as exc:
                    log_exception(
                        "Could not restore shared schedules",
                        (type(exc), exc, exc.__traceback__),
                    )
                    if not self.server.connected:
                        self.app._connection_online.clear()
                        self.app._start_reconnect()
            # Recovery mutations not yet flushed are authoritative. Completed
            # schedules queued for removal must not resurrect after reconnect.
            merged = {
                str(item.get("schedule_id") or ""): item
                for item in entries
                if item.get("schedule_id")
                and str(item.get("schedule_id")) not in pending_removals
            }
            merged.update(pending_saves)
            restored = list(merged.values())
            log_event(
                "Restored {} shared/recovery schedule(s)".format(len(restored))
            )
            self.view.after(0, self.app._install_shared_schedules, restored)

        handle = self.app._submit_background(
            "load-schedules", worker, key="load-schedules", coalesce=True
        )
        if handle.state == "rejected":
            try:
                self.view.after(1000, self.restore)
            except Exception:
                pass
