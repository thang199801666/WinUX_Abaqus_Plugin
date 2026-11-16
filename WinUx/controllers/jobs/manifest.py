"""Durable shared schedule manifest coordination.

Scheduled mutations are journaled per logical login account.  A reconnect stays
inside the same application session and therefore reuses the same queue; a new
login cannot flush pending work that belongs to another server/account.
"""
from __future__ import annotations

import threading
from pathlib import Path, PurePosixPath

from ...diagnostics import log_event, log_exception
from ...preferences.storage import JsonPreferenceStore
from ...runtime.operation_context import OperationContext


class ScheduleManifestController:
    """Own local recovery + remote shared schedule manifest state."""

    RECOVERY_SCHEMA_VERSION = 2
    LEGACY_ACCOUNT = "__legacy__"

    def __init__(self, app):
        self.app = app
        self._manifest_lock = threading.Lock()
        self._queue_lock = threading.RLock()
        self._recovery_store = JsonPreferenceStore("schedule_recovery.json")
        self._queues = {}
        # Coalesce delayed retries by logical account. Without this guard, a
        # prolonged SSH failure can enqueue many after() callbacks, and a stale
        # retry from session A could otherwise run after session B becomes active.
        self._retry_pending = set()
        recovery = self._recovery_store.load()
        self._load_recovery(recovery)

    @property
    def server(self):
        return self.app.server

    @property
    def view(self):
        return self.app.view

    def _load_recovery(self, recovery):
        accounts = recovery.get("accounts", {}) if isinstance(recovery, dict) else {}
        if isinstance(accounts, dict):
            for account_key, payload in accounts.items():
                if not isinstance(payload, dict):
                    continue
                saves = payload.get("pending_saves", {})
                removals = payload.get("pending_removals", [])
                self._queues[str(account_key)] = {
                    "saves": dict(saves) if isinstance(saves, dict) else {},
                    "removals": set(str(value) for value in removals if value),
                }

        # Upgrade the pre-session journal lazily.  The old format had no account
        # identity, so the only safe migration is to claim it when the first
        # real logged-in account restores/flushes after upgrading WinUx.
        legacy_saves = recovery.get("pending_saves", {}) if isinstance(recovery, dict) else {}
        legacy_removals = recovery.get("pending_removals", []) if isinstance(recovery, dict) else []
        if isinstance(legacy_saves, dict) or isinstance(legacy_removals, (list, tuple, set)):
            saves = dict(legacy_saves) if isinstance(legacy_saves, dict) else {}
            removals = set(str(value) for value in legacy_removals if value)
            if saves or removals:
                existing = self._queues.setdefault(
                    self.LEGACY_ACCOUNT, {"saves": {}, "removals": set()})
                existing["saves"].update(saves)
                existing["removals"].update(removals)

    def _account_key(self):
        manager = getattr(self.app, "session_manager", None)
        current = getattr(manager, "current", None) if manager is not None else None
        if current is not None:
            host = str(getattr(current, "host", "") or "").strip().lower()
            username = str(getattr(current, "username", "") or "").strip()
            try:
                port = int(getattr(current, "port", 22) or 22)
            except (TypeError, ValueError):
                port = 22
        else:
            host = str(getattr(self.server, "host", "") or "").strip().lower()
            username = str(getattr(self.server, "username", "") or "").strip()
            try:
                port = int(getattr(self.server, "_port", 22) or 22)
            except (TypeError, ValueError):
                port = 22
        if not host or not username:
            return None
        return "{}|{}|{}".format(host, port, username)

    def _queue_locked(self, account_key, *, create=False, claim_legacy=False):
        if not account_key:
            return None
        if claim_legacy and self.LEGACY_ACCOUNT in self._queues:
            legacy = self._queues.pop(self.LEGACY_ACCOUNT)
            target = self._queues.setdefault(
                account_key, {"saves": {}, "removals": set()})
            target["saves"].update(legacy.get("saves", {}))
            target["removals"].update(legacy.get("removals", set()))
        if create:
            return self._queues.setdefault(
                account_key, {"saves": {}, "removals": set()})
        return self._queues.get(account_key)


    def _schedule_retry(self, operation, account_key, delay_ms, callback):
        key = (str(operation), str(account_key or ""))
        if not key[1]:
            return False
        with self._queue_lock:
            if key in self._retry_pending:
                return False
            self._retry_pending.add(key)

        def deliver():
            with self._queue_lock:
                self._retry_pending.discard(key)
            if self.app._closing or account_key != self._account_key():
                return
            callback()

        try:
            self.view.after(max(0, int(delay_ms)), deliver)
            return True
        except Exception:
            with self._queue_lock:
                self._retry_pending.discard(key)
            return False

    def manifest_entry(self, task, kind):
        def serializable(value):
            if isinstance(value, (Path, PurePosixPath)):
                return str(value)
            if isinstance(value, dict):
                return {str(key): serializable(item) for key, item in value.items()}
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
            if task.get("runtime_limit_seconds") is not None:
                entry["runtime_limit_seconds"] = int(task["runtime_limit_seconds"])
                entry["runtime_limit"] = str(task.get("runtime_limit") or "")
        return entry

    def persist_recovery_queue(self):
        with self._queue_lock:
            accounts = {}
            for key, queue in self._queues.items():
                saves = dict(queue.get("saves", {}))
                removals = sorted(queue.get("removals", set()))
                if saves or removals:
                    accounts[str(key)] = {
                        "pending_saves": saves,
                        "pending_removals": removals,
                    }
            payload = {
                "schema_version": self.RECOVERY_SCHEMA_VERSION,
                "accounts": accounts,
            }
        self._recovery_store.save(payload, suppress_errors=True)

    def flush_async(self):
        """Flush only the journal belonging to the current logical account."""
        if self.app._closing:
            return
        account_key = self._account_key()
        if not account_key:
            return
        context = OperationContext(self.app, remote=True)
        server = context.server

        with self._queue_lock:
            self._queue_locked(account_key, create=True, claim_legacy=True)
        self.persist_recovery_queue()

        def worker():
            if not context.current() or account_key != self._account_key():
                return
            if server is None or not server.connected:
                self.app._connection_online.clear()
                self.app._start_reconnect()
                return
            with self._queue_lock:
                queue = self._queue_locked(account_key)
                saves = dict(queue.get("saves", {})) if queue else {}
                removals = set(queue.get("removals", set())) if queue else set()
            if not saves and not removals:
                return
            try:
                with self._manifest_lock:
                    server.ensure_schedule_storage()
                    entries = server.read_schedule_manifest()
                    changed_ids = set(removals) | set(saves)
                    entries = [
                        item for item in entries
                        if str(item.get("schedule_id") or "") not in changed_ids
                    ]
                    entries.extend(saves.values())
                    if not context.current() or account_key != self._account_key():
                        return
                    server.write_schedule_manifest(entries)
            except Exception as exc:
                log_exception(
                    "Could not synchronize schedule manifest",
                    (type(exc), exc, exc.__traceback__),
                )
                if server is None or not server.connected:
                    self.app._connection_online.clear()
                    self.app._start_reconnect()
                else:
                    self._schedule_retry("flush", account_key, 2000, self.flush_async)
                return

            if not context.current() or account_key != self._account_key():
                return
            with self._queue_lock:
                queue = self._queue_locked(account_key)
                if queue is not None:
                    for schedule_id, entry in saves.items():
                        if queue["saves"].get(schedule_id) == entry:
                            queue["saves"].pop(schedule_id, None)
                    for schedule_id in removals:
                        queue["removals"].discard(schedule_id)
                    if not queue["saves"] and not queue["removals"]:
                        self._queues.pop(account_key, None)
            self.persist_recovery_queue()

        handle = context.submit_background(
            "sync-schedules", worker, key="sync-schedules", coalesce=True
        )
        if handle.state == "rejected":
            self._schedule_retry("flush", account_key, 1000, self.flush_async)

    def save(self, task, kind):
        schedule_id = str(task.get("schedule_id") or "")
        account_key = self._account_key()
        if not schedule_id or not account_key:
            return False
        entry = self.manifest_entry(task, kind)
        with self._queue_lock:
            queue = self._queue_locked(account_key, create=True, claim_legacy=True)
            queue["removals"].discard(schedule_id)
            queue["saves"][schedule_id] = entry
        self.persist_recovery_queue()
        self.flush_async()
        return True

    def remove(self, schedule_id):
        schedule_id = str(schedule_id or "")
        account_key = self._account_key()
        if not schedule_id or not account_key:
            return
        with self._queue_lock:
            queue = self._queue_locked(account_key, create=True, claim_legacy=True)
            queue["saves"].pop(schedule_id, None)
            queue["removals"].add(schedule_id)
        self.persist_recovery_queue()
        self.flush_async()

    def restore(self):
        account_key = self._account_key()
        if not account_key:
            return
        context = OperationContext(self.app, remote=True)
        server = context.server
        with self._queue_lock:
            self._queue_locked(account_key, create=True, claim_legacy=True)
        self.persist_recovery_queue()

        def worker():
            if not context.current() or account_key != self._account_key():
                return
            with self._queue_lock:
                queue = self._queue_locked(account_key)
                pending_saves = dict(queue.get("saves", {})) if queue else {}
                pending_removals = set(queue.get("removals", set())) if queue else set()
            entries = []
            if server is not None and server.connected:
                try:
                    with self._manifest_lock:
                        server.ensure_schedule_storage()
                        entries = server.read_schedule_manifest()
                except Exception as exc:
                    log_exception(
                        "Could not restore shared schedules",
                        (type(exc), exc, exc.__traceback__),
                    )
                    if server is None or not server.connected:
                        self.app._connection_online.clear()
                        self.app._start_reconnect()
            merged = {
                str(item.get("schedule_id") or ""): item
                for item in entries
                if item.get("schedule_id")
                and str(item.get("schedule_id")) not in pending_removals
            }
            merged.update(pending_saves)
            restored = list(merged.values())
            if not context.current() or account_key != self._account_key():
                return
            log_event("Restored {} shared/recovery schedule(s)".format(len(restored)))
            context.post(0, self.app._install_shared_schedules, restored)

        handle = context.submit_background(
            "load-schedules", worker, key="load-schedules", coalesce=True
        )
        if handle.state == "rejected":
            self._schedule_retry("restore", account_key, 1000, self.restore)
