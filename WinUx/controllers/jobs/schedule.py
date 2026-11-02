"""Job schedule execution and editing coordination.

This module owns the active run/delete schedule lifecycle while the main
``WinUXController`` remains a compatibility facade for UI callbacks and tests.
Durable persistence stays isolated in :mod:`schedule_manifest`.
"""
from __future__ import annotations

import threading
from datetime import datetime, timedelta
from pathlib import Path

from ...diagnostics import log_exception
from ...services import presentation


class JobScheduleController:
    """Own due-work execution, schedule editing and in-memory schedule state."""

    def __init__(self, app, *, adopt_existing=False):
        self.app = app
        # When old tests/callers construct WinUXController with __new__, adopt
        # any compatibility state they already installed instead of replacing it.
        self.run_lock = getattr(app, "_job_run_lock", None) if adopt_existing else None
        self.run_tasks = getattr(app, "_job_run_tasks", None) if adopt_existing else None
        self.delete_lock = getattr(app, "_job_delete_lock", None) if adopt_existing else None
        self.delete_tasks = getattr(app, "_job_delete_tasks", None) if adopt_existing else None
        self.wakeup = getattr(app, "_schedule_wakeup", None) if adopt_existing else None
        self.history = getattr(app, "_job_schedule_history", None) if adopt_existing else None
        self.history_lock = getattr(app, "_job_schedule_history_lock", None) if adopt_existing else None

        self.run_lock = self.run_lock or threading.Lock()
        self.run_tasks = self.run_tasks if self.run_tasks is not None else {}
        self.delete_lock = self.delete_lock or threading.Lock()
        self.delete_tasks = self.delete_tasks if self.delete_tasks is not None else {}
        self.wakeup = self.wakeup or threading.Event()
        self.history = self.history if self.history is not None else {}
        self.history_lock = self.history_lock or threading.Lock()
        self.thread = getattr(app, "_schedule_thread", None) if adopt_existing else None
        self._publish_compatibility_state()

    @property
    def server(self):
        return self.app.server

    @property
    def view(self):
        return self.app.view

    def _publish_compatibility_state(self):
        self.app._job_run_lock = self.run_lock
        self.app._job_run_tasks = self.run_tasks
        self.app._job_delete_lock = self.delete_lock
        self.app._job_delete_tasks = self.delete_tasks
        self.app._schedule_wakeup = self.wakeup
        self.app._job_schedule_history = self.history
        self.app._job_schedule_history_lock = self.history_lock
        self.app._schedule_thread = self.thread

    @staticmethod
    def _duration_seconds(value, label="Duration"):
        text = str(value or "").strip()
        parts = text.split(":")
        if len(parts) not in (2, 3) or any(not part.isdigit() for part in parts):
            raise ValueError("{} must use HH:MM[:SS]".format(label))
        hours = int(parts[0])
        minutes = int(parts[1])
        seconds = int(parts[2]) if len(parts) == 3 else 0
        if minutes > 59 or seconds > 59 or (hours == 0 and minutes == 0 and seconds == 0):
            raise ValueError("{} must be greater than 00:00".format(label))
        return hours * 3600 + minutes * 60 + seconds

    @staticmethod
    def _elapsed_seconds(value):
        text = str(value or "").strip()
        if not text:
            return 0
        days = 0
        if "-" in text:
            day_text, text = text.split("-", 1)
            if not day_text.isdigit():
                return 0
            days = int(day_text)
        parts = text.split(":")
        if len(parts) == 3 and all(part.isdigit() for part in parts):
            hours, minutes, seconds = map(int, parts)
        elif len(parts) == 2 and all(part.isdigit() for part in parts):
            hours = 0
            minutes, seconds = map(int, parts)
        else:
            return 0
        if minutes > 59 or seconds > 59:
            return 0
        return days * 86400 + hours * 3600 + minutes * 60 + seconds

    @staticmethod
    def _format_seconds(seconds):
        seconds = max(0, int(seconds or 0))
        hours, remainder = divmod(seconds, 3600)
        minutes, seconds = divmod(remainder, 60)
        return "{:02d}:{:02d}:{:02d}".format(hours, minutes, seconds)

    def start(self):
        if self.thread is not None and self.thread.is_alive():
            return self.thread
        self.thread = threading.Thread(
            target=self.loop,
            name="winux-scheduler",
            daemon=True,
        )
        self.app._schedule_thread = self.thread
        self.thread.start()
        return self.thread

    def loop(self):
        """Run due schedules without ever expiring work while SSH is offline."""
        while not self.app._closing:
            now = datetime.now()
            with self.run_lock:
                due_run = [
                    task for task in tuple(self.run_tasks.values())
                    if task.get("retry_at", task["target"]) <= now
                    and not task["cancel"].is_set()
                ]
            with self.delete_lock:
                due_delete = [
                    task for task in tuple(self.delete_tasks.values())
                    if not task["cancel"].is_set()
                    and (
                        (task.get("runtime_limit_seconds") is not None
                         and bool(task.get("runtime_due"))
                         and task.get("retry_at", now) <= now)
                        or
                        (task.get("runtime_limit_seconds") is None
                         and task.get("retry_at", task["target"]) <= now)
                    )
                ]

            if (due_run or due_delete) and not self.server.connected:
                self.app._connection_online.clear()
                self.app._start_reconnect()
                try:
                    self.view.after(
                        0, self.status_message,
                        "Scheduled work is waiting for the SSH connection")
                except Exception:
                    pass
                self.wakeup.wait(5.0)
                self.wakeup.clear()
                continue

            for task in due_run:
                self.execute_run(task)
            for task in due_delete:
                self.execute_delete(task)
            self.wakeup.wait(1.0)
            self.wakeup.clear()

    def execute_run(self, task):
        with self.run_lock:
            if self.run_tasks.get(task["key"]) is not task:
                return
        try:
            if self.app._closing or not self.server.connected:
                raise RuntimeError("SSH is not connected")
            self.server.submit_abaqus_job(**task["job"])
            self.view.after(0, self.app._refresh_jobs_now)
            self.record_status(task, "run", "Complete")
        except Exception as exc:
            log_exception("Scheduled run failed", (type(exc), exc, exc.__traceback__))
            if not self.server.connected:
                task.pop("retry_at", None)
                task["catch_up"] = True
                self.app._connection_online.clear()
                self.app._start_reconnect()
                message = "Scheduled run waiting for connection"
            else:
                task["retry_at"] = datetime.now() + timedelta(seconds=30)
                message = "Scheduled run retrying: {}".format(exc)
            self.view.after(0, self.status_message, message)
            self.wakeup.set()
            return
        else:
            with self.run_lock:
                self.run_tasks.pop(task["key"], None)
            self.app._remove_shared_schedule(task.get("schedule_id"))
            self.view.after(0, self.status_message, "Scheduled run completed")

    def execute_delete(self, task):
        with self.delete_lock:
            if self.delete_tasks.get(task["job_id"]) is not task:
                return
        try:
            if self.app._closing or not self.server.connected:
                raise RuntimeError("SSH is not connected")
            if task.get("delete_requested"):
                # The shared Job Viewer snapshot reconciles deletion. Do not
                # race a second qstat or send qdel again while PBS is removing it.
                task["retry_at"] = datetime.now() + timedelta(seconds=5)
                return
            self.server.cancel_job(task["job_id"])
            task["delete_requested"] = True
            task["retry_at"] = datetime.now() + timedelta(seconds=5)
            self.view.after(0, self.app._refresh_jobs_now)
            self.view.after(
                0, self.status_message,
                "Waiting for job {} to disappear".format(task["job_id"]))
            self.wakeup.set()
        except Exception as exc:
            log_exception("Scheduled delete failed", (type(exc), exc, exc.__traceback__))
            if not self.server.connected:
                task.pop("retry_at", None)
                task["catch_up"] = True
                self.app._connection_online.clear()
                self.app._start_reconnect()
                message = "Scheduled delete waiting for connection"
            else:
                task["retry_at"] = datetime.now() + timedelta(seconds=30)
                message = "Scheduled delete retrying: {}".format(exc)
            self.view.after(0, self.status_message, message)
            self.wakeup.set()

    def status_message(self, message):
        if not self.app._closing and self.view.winfo_exists():
            self.view.right.status.set(str(message))

    def reconcile_deletions(self, jobs):
        """Reconcile delete schedules against the authoritative qstat snapshot.

        Fixed-date schedules are retired when a job disappears. Runtime-limit
        schedules additionally compare the PBS-reported ``resources_used.walltime``
        (exposed as ``JobItem.elapsed``) against the requested maximum run time.
        This means queued/held time is not counted by WinUx; deletion becomes due
        only when PBS says the job has actually accumulated the requested runtime.
        """
        live_jobs = {str(job.job_id): job for job in (jobs or ())}
        live_ids = set(live_jobs)
        retired = []
        runtime_due = False
        runtime_changed = False
        with self.delete_lock:
            for job_id, task in tuple(self.delete_tasks.items()):
                key = str(job_id)
                job = live_jobs.get(key)
                if job is None:
                    self.delete_tasks.pop(job_id, None)
                    self.app._job_edit_settings.pop(key, None)
                    if job_id != key:
                        self.app._job_edit_settings.pop(job_id, None)
                    task["cancel"].set()
                    retired.append(task)
                    continue

                limit = task.get("runtime_limit_seconds")
                if limit is None:
                    continue
                elapsed = self._elapsed_seconds(getattr(job, "elapsed", ""))
                if task.get("runtime_elapsed_seconds") != elapsed:
                    task["runtime_elapsed_seconds"] = elapsed
                    runtime_changed = True
                if elapsed >= int(limit) and not task.get("delete_requested"):
                    if not task.get("runtime_due"):
                        task["runtime_due"] = True
                        runtime_changed = True
                    task["retry_at"] = datetime.now()
                    runtime_due = True

        for task in retired:
            if task.get("delete_requested"):
                self.record_status(task, "delete", "Complete")
            else:
                with self.history_lock:
                    self.history.pop("delete|{}".format(task.get("job_id")), None)
            self.app._remove_shared_schedule(task.get("schedule_id"))

        if runtime_due:
            self.wakeup.set()
        if retired or runtime_changed:
            try:
                self.view.after(0, self.refresh_dialog)
            except Exception:
                pass
        return len(retired)

    def schedule_deletion(self, job_id, job_name, settings):
        """Replace a job's delete schedule with the settings from Edit Job."""
        job_id = str(job_id)
        with self.history_lock:
            self.history.pop("delete|{}".format(job_id), None)
        with self.delete_lock:
            previous = self.delete_tasks.pop(job_id, None)
        if previous:
            previous["cancel"].set()

        runtime_limit_seconds = None
        runtime_limit = ""
        runtime_elapsed_seconds = 0
        runtime_due = False
        if settings.get("delete_runtime_enabled"):
            runtime_limit = str(settings.get("delete_runtime") or "").strip()
            runtime_limit_seconds = self._duration_seconds(runtime_limit, "Run Time Limit")
            runtime_elapsed_seconds = self._elapsed_seconds(
                settings.get("runtime_elapsed", ""))
            runtime_due = runtime_elapsed_seconds >= runtime_limit_seconds
            delete_time = datetime.now()
            mode = "Run Time Limit {}".format(
                self._format_seconds(runtime_limit_seconds))
        elif settings.get("delete_after_enabled"):
            value = str(settings["delete_after"] or "").strip()
            duration_seconds = self._duration_seconds(value, "Delete After")
            delete_time = datetime.now() + timedelta(seconds=duration_seconds)
            mode = "Delete After {}".format(value)
        elif settings.get("delete_at_enabled"):
            delete_text = str(settings["delete_at"])
            try:
                delete_time = datetime.strptime(delete_text, "%Y-%m-%d %H:%M:%S")
            except ValueError:
                delete_time = datetime.strptime(delete_text, "%H:%M:%S %m-%d-%Y")
            mode = "Delete At Time"
        else:
            return

        task = {
            "job_id": job_id,
            "job_name": job_name,
            "mode": mode,
            "delete_time": delete_time.strftime("%Y-%m-%d %H:%M:%S"),
            "target": delete_time,
            "cancel": threading.Event(),
            "owner": self.server.username,
            "schedule_id": "delete|{}".format(job_id),
        }
        if runtime_limit_seconds is not None:
            task.update({
                "runtime_limit_seconds": runtime_limit_seconds,
                "runtime_limit": self._format_seconds(runtime_limit_seconds),
                "runtime_elapsed_seconds": runtime_elapsed_seconds,
                "runtime_due": runtime_due,
            })
            if runtime_due:
                task["retry_at"] = datetime.now()

        self.app._save_shared_schedule(task, "delete")
        with self.delete_lock:
            self.delete_tasks[job_id] = task
        self.wakeup.set()
        # Runtime limits depend on PBS elapsed time. Ask the single qstat poller
        # for a fresh snapshot immediately instead of waiting for its backoff.
        if runtime_limit_seconds is not None:
            try:
                self.app._refresh_jobs_now()
            except Exception:
                pass

    def finish_deletion(self, task):
        with self.delete_lock:
            if self.delete_tasks.get(task["job_id"]) is task:
                self.delete_tasks.pop(task["job_id"], None)
                self.app._job_edit_settings.pop(task["job_id"], None)
        self.record_status(task, "delete", "Complete")
        self.app._remove_shared_schedule(task.get("schedule_id"))
        if not self.app._closing:
            try:
                self.view.after(0, self.app._refresh_jobs_now)
            except Exception:
                pass

    def pending_deletions(self):
        with self.delete_lock:
            return [
                dict(task) for task in self.delete_tasks.values()
                if not task["cancel"].is_set()
            ]

    def rows(self, *, blocking=True):
        """Snapshot schedules; return None on contention for UI close requests."""
        now = datetime.now()
        snapshots = []
        for lock, mapping, pending in (
                (self.run_lock, self.run_tasks, True),
                (self.delete_lock, self.delete_tasks, True),
                (self.history_lock, self.history, False)):
            if not lock.acquire(blocking):
                return None
            try:
                snapshots.append([dict(task) for task in mapping.values()
                                  if not pending or not task["cancel"].is_set()])
            finally:
                lock.release()
        run_tasks, delete_tasks, history = snapshots
        rows = []
        for task in run_tasks:
            rows.append((
                task["job_name"], task["mode"],
                task["target"].strftime("%Y-%m-%d %H:%M:%S"),
                presentation.remaining_time(task["target"], now),
                "Waiting", "run", task["key"]))
        for task in delete_tasks:
            if task.get("runtime_limit_seconds") is not None:
                limit = int(task.get("runtime_limit_seconds") or 0)
                elapsed = int(task.get("runtime_elapsed_seconds") or 0)
                scheduled = "Run time {}".format(
                    task.get("runtime_limit") or self._format_seconds(limit))
                remaining = self._format_seconds(max(0, limit - elapsed))
            else:
                scheduled = task["delete_time"]
                remaining = presentation.remaining_time(task["target"], now)
            rows.append((
                "{} ({})".format(task["job_name"], task["job_id"]),
                task["mode"], scheduled, remaining,
                "Waiting", "delete", task["job_id"]))
        for task in history:
            rows.append((
                task["job_name"], task["mode"],
                task["target"].strftime("%Y-%m-%d %H:%M:%S"),
                "00:00:00", task["status"], task["kind"], task["key"]))
        return sorted(rows, key=lambda row: row[2])

    def record_status(self, task, kind, status):
        key = "{}|{}".format(kind, task.get("key", task.get("job_id")))
        record = {
            "key": str(task.get("key", task.get("job_id"))),
            "kind": kind,
            "status": status,
            "mode": task["mode"],
            "target": task["target"],
            "job_name": task.get("job_name") or str(task.get("path", "")),
        }
        if kind == "delete":
            record["job_name"] = "{} ({})".format(task["job_name"], task["job_id"])
        with self.history_lock:
            self.history[key] = record

    def install_shared(self, entries):
        for entry in entries:
            try:
                target = datetime.fromisoformat(str(entry["target"]))
                overdue = target <= datetime.now()
                kind = str(entry.get("kind"))
                if kind == "run":
                    task = {
                        "key": str(entry["schedule_id"]).split("|", 1)[-1],
                        "schedule_id": entry["schedule_id"],
                        "path": Path(entry["path"]),
                        "job": entry["job"],
                        "job_name": entry.get("job_name", ""),
                        "owner": entry.get("owner", ""),
                        "mode": entry.get("mode", "Run At"),
                        "target": target,
                        "cancel": threading.Event(),
                    }
                    if overdue:
                        task["retry_at"] = datetime.now()
                        task["catch_up"] = True
                    with self.run_lock:
                        if task["key"] in self.run_tasks:
                            continue
                        self.run_tasks[task["key"]] = task
                    self.wakeup.set()
                elif kind == "delete":
                    job_id = str(entry["job_id"])
                    runtime_limit_seconds = entry.get("runtime_limit_seconds")
                    if runtime_limit_seconds is not None:
                        runtime_limit_seconds = int(runtime_limit_seconds)
                    task = {
                        "schedule_id": str(entry["schedule_id"]),
                        "job_id": job_id,
                        "job_name": entry.get("job_name", ""),
                        "owner": entry.get("owner", ""),
                        "mode": entry.get("mode", "Delete At Time"),
                        "delete_time": target.strftime("%Y-%m-%d %H:%M:%S"),
                        "target": target,
                        "cancel": threading.Event(),
                    }
                    if runtime_limit_seconds is not None:
                        runtime_limit = str(entry.get("runtime_limit") or
                                            self._format_seconds(runtime_limit_seconds))
                        task.update({
                            "runtime_limit_seconds": runtime_limit_seconds,
                            "runtime_limit": runtime_limit,
                            "runtime_elapsed_seconds": 0,
                            "runtime_due": False,
                        })
                        self.app._job_edit_settings[job_id] = {
                            "mode": "Run Time Limit",
                            "delete_runtime_enabled": True,
                            "delete_runtime": runtime_limit,
                            "runtime_elapsed": "00:00:00",
                            "delete_after_enabled": False,
                            "delete_after": "00:30",
                            "delete_at_enabled": False,
                            "delete_at": target.strftime("%Y-%m-%d %H:%M:%S"),
                        }
                    elif overdue:
                        task["retry_at"] = datetime.now()
                        task["catch_up"] = True
                    with self.delete_lock:
                        if job_id in self.delete_tasks:
                            continue
                        self.delete_tasks[job_id] = task
                    self.wakeup.set()
            except (KeyError, TypeError, ValueError, OSError):
                continue

    def command(self, action, kind, key):
        action = str(action).casefold()
        key = str(key)
        kind = str(kind).casefold()
        lock = self.run_lock if kind == "run" else self.delete_lock
        tasks = self.run_tasks if kind == "run" else self.delete_tasks
        with lock:
            task = tasks.get(key)
        if not task:
            return
        owner = str(task.get("owner", "")).casefold()
        current_user = str(self.server.username or "").casefold()
        if owner and owner != current_user:
            self.view.show_error(
                "Job Schedule",
                "Only user '{}' can edit or cancel this schedule.".format(task.get("owner")))
            return
        if action == "cancel":
            self.view.confirm_action_async(
                "Cancel Schedule", "Cancel this scheduled job?",
                lambda confirmed: self.cancel(kind, key) if confirmed else None)
            return
        if action == "_cancel_confirmed":
            self.cancel(kind, key)
            return
        if action == "cancel_now":
            with lock:
                removed = tasks.pop(key, None)
            if removed:
                removed["cancel"].set()
                self.record_status(removed, kind, "Cancel")
                self.app._remove_shared_schedule(removed.get("schedule_id"))
            if kind == "delete":
                self.app._job_edit_settings.pop(key, None)
            self.view.after(0, self.refresh_dialog)
            return
        if action != "edit":
            return

        is_runtime = task.get("runtime_limit_seconds") is not None
        is_after = (not is_runtime and "After" in task["mode"])
        if is_runtime:
            initial = str(task.get("runtime_limit") or self._format_seconds(
                task.get("runtime_limit_seconds", 0)))
            prompt = "Enter maximum run time (HH:MM:SS):"
            edit_mode = "runtime"
        elif is_after:
            initial = task["mode"].rsplit(" ", 1)[-1]
            prompt = "Enter duration (HH:MM:SS):"
            edit_mode = "after"
        else:
            initial = task["target"].strftime("%Y-%m-%d %H:%M:%S")
            prompt = "Enter date/time (YYYY-MM-DD HH:MM:SS):"
            edit_mode = "at"
        self.view.ask_text_async(
            "Edit Job Schedule", prompt, initial,
            lambda value: self.apply_edit(kind, key, task, edit_mode, value))

    def refresh_dialog(self):
        dialog = getattr(self.view, "job_schedule_dialog", None)
        if dialog is not None and dialog.winfo_exists():
            dialog.refresh()

    def cancel(self, kind, key):
        lock = self.run_lock if kind == "run" else self.delete_lock
        tasks = self.run_tasks if kind == "run" else self.delete_tasks
        with lock:
            removed = tasks.pop(key, None)
        if removed:
            removed["cancel"].set()
            self.record_status(removed, kind, "Cancel")
            if kind == "delete":
                self.app._job_edit_settings.pop(key, None)
            self.app._remove_shared_schedule(removed.get("schedule_id"))
        self.view.after(0, self.refresh_dialog)

    def apply_edit(self, kind, key, original_task, edit_mode, value):
        if value is None:
            return
        runtime_mode = edit_mode == "runtime"
        is_after = edit_mode is True or edit_mode == "after"
        if runtime_mode or is_after:
            try:
                duration_seconds = self._duration_seconds(value)
            except ValueError:
                self.view.show_error(
                    "Job Schedule",
                    "Duration must use HH:MM:SS and be greater than 00:00:00")
                return
            target = datetime.now() + timedelta(seconds=duration_seconds)
        else:
            try:
                target = datetime.strptime(value, "%Y-%m-%d %H:%M:%S")
                if target <= datetime.now():
                    raise ValueError
            except ValueError:
                message = (
                    "Run At must use YYYY-MM-DD HH:MM:SS and be in the future"
                    if kind == "run" else
                    "Delete At must use YYYY-MM-DD HH:MM:SS and be in the future")
                self.view.show_error("Job Schedule", message)
                return

        if kind == "delete":
            with self.delete_lock:
                if self.delete_tasks.get(key) is not original_task:
                    return
            settings = {
                "mode": ("Run Time Limit" if runtime_mode else
                         "Delete After" if is_after else "Delete At"),
                "delete_runtime_enabled": runtime_mode,
                "delete_runtime": str(value) if runtime_mode else "00:30",
                "runtime_elapsed": self._format_seconds(
                    original_task.get("runtime_elapsed_seconds", 0)),
                "delete_after_enabled": is_after,
                "delete_after": str(value) if is_after else "00:30",
                "delete_at_enabled": not runtime_mode and not is_after,
                "delete_at": (str(value) if not runtime_mode and not is_after
                              else target.strftime("%Y-%m-%d %H:%M:%S")),
            }
            self.app._job_edit_settings[key] = settings
            self.schedule_deletion(key, original_task["job_name"], settings)
            self.view.after(0, self.refresh_dialog)
        else:
            replacement = dict(original_task)
            replacement.update({
                "key": "{}|{}".format(original_task["path"], target.isoformat()),
                "mode": "Run After {}".format(value) if is_after else "Run At",
                "target": target,
                "cancel": threading.Event(),
            })
            replacement["schedule_id"] = "run|{}".format(replacement["key"])
            self.app._save_shared_schedule(replacement, "run")
            self.app._remove_shared_schedule(original_task.get("schedule_id"))
            with self.run_lock:
                if self.run_tasks.get(key) is not original_task:
                    return
                self.run_tasks.pop(key, None)
                self.run_tasks[replacement["key"]] = replacement
            original_task["cancel"].set()
            self.wakeup.set()
            self.view.after(0, self.refresh_dialog)

    def schedule_run(self, path, job, run_at, schedule_mode, dialog):
        """Register one future Abaqus submission; return True when consumed."""
        if run_at is None or run_at <= datetime.now():
            return False
        key = "{}|{}".format(path, run_at.isoformat())
        with self.run_lock:
            if key in self.run_tasks:
                return True
        task = {
            "key": key,
            "path": path,
            "job": job,
            "job_name": path.stem,
            "mode": schedule_mode,
            "target": run_at,
            "cancel": threading.Event(),
            "owner": self.server.username,
            "schedule_id": "run|{}".format(key),
        }
        self.app._save_shared_schedule(task, "run")
        with self.history_lock:
            self.history.pop("run|{}".format(key), None)
        with self.run_lock:
            previous = self.run_tasks.get(key)
            self.run_tasks[key] = task
        if previous:
            previous["cancel"].set()
        self.view.after(0, dialog.submission_scheduled, path, run_at)
        self.wakeup.set()
        return True
