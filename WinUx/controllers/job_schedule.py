"""Job schedule execution and editing coordination.

This module owns the active run/delete schedule lifecycle while the main
``WinUXController`` remains a compatibility facade for UI callbacks and tests.
Durable persistence stays isolated in :mod:`schedule_manifest`.
"""
from __future__ import annotations

import threading
from datetime import datetime, timedelta
from pathlib import Path

from ..diagnostics import log_exception
from ..services import presentation


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
                    if task.get("retry_at", task["target"]) <= now
                    and not task["cancel"].is_set()
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
                live_ids = {str(job.job_id) for job in self.server.list_jobs()}
                if str(task["job_id"]) not in live_ids:
                    self.finish_deletion(task)
                    return
            self.server.cancel_job(task["job_id"])
            task["delete_requested"] = True
            task["retry_at"] = datetime.now() + timedelta(seconds=5)
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
        """Drop delete schedules as soon as qstat no longer contains the job."""
        live_ids = {str(job.job_id) for job in jobs}
        with self.delete_lock:
            completed = [
                task for job_id, task in self.delete_tasks.items()
                if job_id not in live_ids and task.get("delete_requested")
            ]
            for task in completed:
                self.delete_tasks.pop(task["job_id"], None)
                self.app._job_edit_settings.pop(task["job_id"], None)
                task["cancel"].set()
                self.record_status(task, "delete", "Complete")
                self.app._remove_shared_schedule(task.get("schedule_id"))

    def schedule_deletion(self, job_id, job_name, settings):
        """Replace a job's delete schedule with the settings from Edit Job."""
        with self.history_lock:
            self.history.pop("delete|{}".format(job_id), None)
        with self.delete_lock:
            previous = self.delete_tasks.pop(job_id, None)
        if previous:
            previous["cancel"].set()

        if settings.get("delete_after_enabled"):
            value = str(settings["delete_after"] or "").strip()
            parts = value.split(":")
            if len(parts) not in (2, 3) or any(not part.isdigit() for part in parts):
                raise ValueError("Delete After must use HH:MM[:SS]")
            hours = int(parts[0])
            minutes = int(parts[1])
            seconds = int(parts[2]) if len(parts) == 3 else 0
            if minutes > 59 or seconds > 59 or (hours == 0 and minutes == 0 and seconds == 0):
                raise ValueError("Delete After must be greater than 00:00")
            delete_time = datetime.now() + timedelta(
                hours=hours, minutes=minutes, seconds=seconds)
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
        self.app._save_shared_schedule(task, "delete")
        with self.delete_lock:
            self.delete_tasks[job_id] = task
        self.wakeup.set()

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

    def rows(self):
        now = datetime.now()
        with self.run_lock:
            run_tasks = [dict(task) for task in self.run_tasks.values() if not task["cancel"].is_set()]
        with self.delete_lock:
            delete_tasks = [dict(task) for task in self.delete_tasks.values() if not task["cancel"].is_set()]
        with self.history_lock:
            history = [dict(task) for task in self.history.values()]
        rows = []
        for task in run_tasks:
            rows.append((
                task["job_name"], task["mode"],
                task["target"].strftime("%Y-%m-%d %H:%M:%S"),
                presentation.remaining_time(task["target"], now),
                "Waiting", "run", task["key"]))
        for task in delete_tasks:
            rows.append((
                "{} ({})".format(task["job_name"], task["job_id"]),
                task["mode"], task["delete_time"],
                presentation.remaining_time(task["target"], now),
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
                    if overdue:
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

        is_after = "After" in task["mode"]
        if is_after:
            initial = task["mode"].rsplit(" ", 1)[-1]
            prompt = "Enter duration (HH:MM:SS):"
        else:
            initial = task["target"].strftime("%Y-%m-%d %H:%M:%S")
            prompt = "Enter date/time (YYYY-MM-DD HH:MM:SS):"
        self.view.ask_text_async(
            "Edit Job Schedule", prompt, initial,
            lambda value: self.apply_edit(kind, key, task, is_after, value))

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

    def apply_edit(self, kind, key, original_task, is_after, value):
        if value is None:
            return
        if is_after:
            try:
                parts = str(value or "").strip().split(":")
                if len(parts) not in (2, 3) or any(not part.isdigit() for part in parts):
                    raise ValueError
                hours = int(parts[0])
                minutes = int(parts[1])
                seconds = int(parts[2]) if len(parts) == 3 else 0
                if minutes > 59 or seconds > 59 or (hours == 0 and minutes == 0 and seconds == 0):
                    raise ValueError
            except ValueError:
                self.view.show_error(
                    "Job Schedule",
                    "Duration must use HH:MM:SS and be greater than 00:00:00")
                return
            target = datetime.now() + timedelta(hours=hours, minutes=minutes, seconds=seconds)
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
                "delete_after_enabled": is_after,
                "delete_after": value if is_after else "00:30",
                "delete_at_enabled": not is_after,
                "delete_at": value if not is_after else target.strftime("%Y-%m-%d %H:%M:%S"),
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
