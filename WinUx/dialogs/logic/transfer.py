"""UI-neutral transfer-center task and row state."""
from __future__ import annotations

import time

from .formatting import format_size, format_time


class TransferItemRow:
    """Thread-neutral transfer row model; rendering belongs to the front end."""

    def __init__(self, task, name, placeholder=False):
        self.task = task
        self.name = str(name)
        self.placeholder = bool(placeholder)
        self.state = "queued"
        self._sample_time = None
        self._sample_done = 0.0
        self._smoothed_speed = 0.0
        self.row_id = task.center._next_row_id()
        self.task.center._row_to_task[self.row_id] = task
        self.task.center.post("add_row", self.row_id, self.task.operation, self.name)

    def exists(self):
        return self.row_id in self.task.center._row_to_task

    def rename(self, name):
        self.name = str(name)
        self.placeholder = False
        if self.exists():
            self.task.center.update_row(self.row_id, name=self.name)

    def set_status(self, state, label):
        self.state = state
        if self.exists():
            self.task.center.update_row(self.row_id, status=str(label))

    def update_progress(self, current_done, current_total):
        if not self.exists():
            return

        done = max(0.0, float(current_done or 0.0))
        total = max(0.0, float(current_total or 0.0))
        ratio = 1.0 if total <= 0.0 and done >= total else min(
            1.0, done / max(1.0, total))

        now = time.monotonic()
        if self._sample_time is None:
            self._sample_time = now
            self._sample_done = done
        elif done < self._sample_done:
            self._sample_time = now
            self._sample_done = done
            self._smoothed_speed = 0.0
        else:
            elapsed = now - self._sample_time
            delta = done - self._sample_done
            if elapsed >= 0.05 and delta >= 0.0:
                sample_speed = delta / max(elapsed, 0.001)
                if sample_speed > 0.0:
                    if self._smoothed_speed <= 0.0:
                        self._smoothed_speed = sample_speed
                    else:
                        self._smoothed_speed = (
                            self._smoothed_speed * 0.72 + sample_speed * 0.28)
                self._sample_time = now
                self._sample_done = done

        speed = self._smoothed_speed
        remaining = max(0.0, total - done)
        eta = remaining / speed if speed > 0.0 else None
        size_text = "{} / {}".format(format_size(done), format_size(total))
        if speed > 0.0 and ratio < 1.0:
            statistics = "{} | {}/s | {} remaining".format(
                size_text, format_size(speed), format_time(eta))
        elif ratio >= 1.0:
            statistics = "{} | Finishing transfer...".format(size_text)
        else:
            statistics = "{} | Measuring speed...".format(size_text)

        status = "Finalizing..." if ratio >= 1.0 else "Running"
        self.task.center.update_row(
            self.row_id,
            ratio=ratio,
            statistics=statistics,
            status=status,
        )
        self.state = "finalizing" if ratio >= 1.0 else "running"

    def mark_completed(self):
        if not self.exists() or self.state == "completed":
            return
        self.state = "completed"
        self.task.center.update_row(
            self.row_id,
            ratio=1.0,
            status="Completed",
            statistics="Completed",
            action="Done",
            action_enabled=False,
        )

    def finish(self, cancelled=False):
        if not self.exists():
            return
        if cancelled and self.state != "completed":
            self.state = "cancelled"
            self.task.center.update_row(
                self.row_id,
                status="Cancelled", action="Dismiss", action_enabled=True)
        elif not cancelled:
            self.mark_completed()

    def fail(self, message):
        if not self.exists():
            return
        self.state = "failed"
        self.task.center.update_row(
            self.row_id,
            status="Failed", statistics=str(message),
            action="Dismiss", action_enabled=True)

    def destroy(self):
        self.task.center._row_to_task.pop(self.row_id, None)
        self.task.center.post("remove_row", self.row_id)


class TransferTaskHandle:
    """Progress-dialog compatible task handle backed by per-file rows."""

    def __init__(self, center, operation, cancel_event, items=None):
        self.center = center
        self.operation = str(operation)
        self.cancel_event = cancel_event
        self.items = self._deduplicate_items(items)
        self.started_at = time.monotonic()
        self.state = "running"
        self.rows = []
        self._active_row = None
        self._build_rows()

    @staticmethod
    def _deduplicate_items(items):
        result = []
        seen = set()
        for item in items or []:
            name = str(item)
            if not name or name in seen:
                continue
            seen.add(name)
            result.append(name)
        return result

    @staticmethod
    def _leaf_name(value):
        return str(value).replace("\\", "/").rstrip("/").rsplit("/", 1)[-1]

    def _build_rows(self):
        if self.items:
            for item in self.items:
                self.rows.append(TransferItemRow(self, item))
        else:
            self.rows.append(TransferItemRow(self, "Preparing...", placeholder=True))

    def winfo_exists(self):
        return any(row.exists() for row in self.rows)

    def _row_for_name(self, name):
        name = str(name or "Preparing...")
        if (len(self.rows) == 1 and self.rows[0].placeholder and
                self.rows[0].state == "queued"):
            self.rows[0].rename(name)
            return self.rows[0]

        leaf = self._leaf_name(name)
        if self._active_row is not None:
            if (self._active_row.name == name or
                    self._leaf_name(self._active_row.name) == leaf):
                return self._active_row

        exact_matches = [row for row in self.rows if row.name == name]
        if exact_matches:
            return next(
                (row for row in exact_matches
                 if row.state not in ("completed", "failed", "cancelled")),
                exact_matches[-1],
            )
        leaf_matches = [
            row for row in self.rows if self._leaf_name(row.name) == leaf]
        if leaf_matches:
            return next(
                (row for row in leaf_matches
                 if row.state not in ("completed", "failed", "cancelled")),
                leaf_matches[-1],
            )

        row = TransferItemRow(self, name)
        self.rows.append(row)
        return row

    def update_progress(
            self, name, current_done, current_total,
            overall_done, overall_total):
        del overall_done, overall_total
        if not self.winfo_exists() or self.state != "running":
            return
        row = self._row_for_name(name)
        if (self._active_row is not None and self._active_row is not row and
                self._active_row.state in ("running", "finalizing")):
            self._active_row.mark_completed()
        self._active_row = row
        row.update_progress(current_done, current_total)

    def complete(self):
        if not self.winfo_exists() or self.state not in ("running", "cancelling"):
            return
        cancelled = self.cancel_event.is_set()
        self.state = "cancelled" if cancelled else "completed"
        for row in self.rows:
            row.finish(cancelled=cancelled)
        self.center.task_finished(self)
        if self.state == "completed":
            self.center.schedule_auto_remove(self)

    def fail(self, message):
        if not self.winfo_exists():
            return
        if self.cancel_event.is_set() or str(message) == "Operation cancelled":
            self.state = "cancelled"
            for row in self.rows:
                row.finish(cancelled=True)
            self.center.task_finished(self)
            return

        self.state = "failed"
        failed_row = self._active_row
        if failed_row is None or failed_row.state == "completed":
            failed_row = next(
                (row for row in self.rows if row.state != "completed"),
                self._active_row or self.rows[0],
            )
        for row in self.rows:
            if row is failed_row:
                row.fail(message)
            elif row.state in ("queued", "running", "finalizing"):
                row.state = "skipped"
                self.center.update_row(
                    row.row_id,
                    status="Not started", action="Dismiss",
                    action_enabled=True)
            else:
                self.center.update_row(
                    row.row_id,
                    action="Dismiss", action_enabled=True)
        self.center.task_failed(self)

    def cancel(self, *_args):
        if self.state != "running":
            return
        self.state = "cancelling"
        self.cancel_event.set()
        for row in self.rows:
            if not row.exists() or row.state == "completed":
                continue
            row.state = "cancelling"
            self.center.update_row(
                row.row_id,
                status="Cancelling...", action_enabled=False)


class TransferCenterLogic:
    """Task/state operations shared by native, DPG and floating front ends."""

    WIDTH = 700
    HEIGHT = 245
    AUTO_REMOVE_DELAY_MS = 900

    def _next_row_id(self):
        return next(self._row_ids)

    def update_row(self, row_id, **values):
        if not self.winfo_exists():
            return False
        with self._row_update_lock:
            pending = self._pending_row_updates.setdefault(row_id, {})
            pending.update(values)
            if self._row_update_scheduled:
                return True
            self._row_update_scheduled = True
        if not self.post("flush_row_updates"):
            with self._row_update_lock:
                self._row_update_scheduled = False
            return False
        return True

    def _take_pending_row_updates(self):
        with self._row_update_lock:
            updates = list(self._pending_row_updates.items())
            self._pending_row_updates = {}
            self._row_update_scheduled = False
        return updates

    def _request_row_action(self, row_id):
        try:
            self.view.after(0, self._handle_row_action, row_id)
        except Exception:
            pass

    def _handle_row_action(self, row_id):
        task = self._row_to_task.get(row_id)
        if task is None:
            return
        if task.state in ("running", "cancelling"):
            task.cancel()
        else:
            self.remove_task(task)
            self._hide_if_idle()

    def request_cancel_all(self):
        try:
            self.view.after(0, self.cancel_all)
        except Exception:
            pass

    def request_clear_finished(self):
        try:
            self.view.after(0, self.clear_finished)
        except Exception:
            pass

    def clear_finished(self):
        for task in list(self.tasks):
            if task.state in ("completed", "failed", "cancelled"):
                self.remove_task(task)
        self._hide_if_idle()

    def _has_active_tasks(self):
        return any(
            task.state in ("running", "cancelling") and task.winfo_exists()
            for task in self.tasks)

    def _has_attention_tasks(self):
        return any(
            task.state in ("failed", "cancelled") and task.winfo_exists()
            for task in self.tasks)

    def add_task(self, operation, cancel_event, items=None):
        if not self._has_active_tasks():
            self._active_batch_failed = False
        task = TransferTaskHandle(self, operation, cancel_event, items)
        self.tasks.append(task)
        self.show()
        return task

    def schedule_auto_remove(self, task):
        try:
            self.view.after(
                self.AUTO_REMOVE_DELAY_MS,
                self._auto_remove_completed_task,
                task,
            )
        except Exception:
            self.remove_task(task)
            self._hide_if_idle()

    def _auto_remove_completed_task(self, task):
        if task not in self.tasks or task.state != "completed":
            return
        self.remove_task(task)
        self._hide_if_idle()

    def _hide_if_idle(self):
        if self._has_active_tasks() or self._has_attention_tasks():
            return
        self.hide()

    def task_finished(self, task):
        if task not in self.tasks:
            return
        if task.state == "cancelled":
            self.show()

    def task_failed(self, task):
        if task not in self.tasks:
            return
        self._active_batch_failed = True
        self.show()

    def remove_task(self, task):
        if task in self.tasks:
            self.tasks.remove(task)
        for row in list(getattr(task, "rows", [])):
            row.destroy()

    def cancel_all(self, update_ui=True):
        for task in list(self.tasks):
            if task.state not in ("running", "cancelling"):
                continue
            task.cancel_event.set()
            if task.state == "running":
                task.state = "cancelling"
            if not update_ui:
                continue
            for row in task.rows:
                if not row.exists() or row.state == "completed":
                    continue
                row.state = "cancelling"
                self.update_row(
                    row.row_id, status="Cancelling...", action_enabled=False)
