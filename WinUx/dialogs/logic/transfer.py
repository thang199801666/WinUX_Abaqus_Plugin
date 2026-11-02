"""UI-neutral transfer-center task and row state."""
from __future__ import annotations

import time
import weakref

from .formatting import format_size, format_time


class TransferItemRow:
    """Thread-neutral transfer row model; rendering belongs to the front end."""

    STATISTICS_INTERVAL = .2

    def __init__(self, task, name, placeholder=False):
        self.task = task
        self.name = str(name)
        self.placeholder = bool(placeholder)
        self.state = "queued"
        self._sample_time = None
        self._sample_done = 0.0
        self._smoothed_speed = 0.0
        self._last_statistics_time = None
        self.row_id = task.center._next_row_id()
        self.task.center._row_to_task[self.row_id] = task
        self.task.center.post("add_row", self.row_id, self.task.operation, self.name)

    def exists(self):
        return self.row_id in self.task.center._row_to_task

    def rename(self, name):
        old_name = self.name
        self.name = str(name)
        self.task._unindex_row(self, old_name)
        self.task._index_row(self)
        self.placeholder = False
        if self.exists():
            self.task.center.update_row(self.row_id, name=self.name)

    def set_status(self, state, label):
        self.state = state
        if self.exists():
            self.task.center.update_row(self.row_id, status=str(label), state=self.state)

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
            self._last_statistics_time = None
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

        status = "Finalizing..." if ratio >= 1.0 else "Running"
        values = {}
        if (self._last_statistics_time is None or ratio >= 1.0 or
                now - self._last_statistics_time >= self.STATISTICS_INTERVAL):
            self._last_statistics_time = now
            speed = self._smoothed_speed
            remaining = max(0.0, total - done)
            eta = remaining / speed if speed > 0.0 else None
            size_text = '{} / {}'.format(format_size(done), format_size(total))
            if speed > 0.0 and ratio < 1.0:
                statistics = '{} | {}/s | {} remaining'.format(size_text, format_size(speed), format_time(eta))
            elif ratio >= 1.0:
                statistics = '{} | Finishing transfer...'.format(size_text)
            else:
                statistics = '{} | Measuring speed...'.format(size_text)
            values['statistics'] = statistics
        self.task.center.update_row(
            self.row_id,
            ratio=ratio,
            status=status,
            state="finalizing" if ratio >= 1.0 else "running",
            **values,
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
            statistics="",
            action="Done",
            action_enabled=False,
            state="completed",
        )

    def finish(self, cancelled=False):
        if not self.exists():
            return
        if cancelled and self.state != "completed":
            self.state = "cancelled"
            self.task.center.update_row(
                self.row_id,
                status="Cancelled", action="Dismiss", action_enabled=True,
                state="cancelled")
        elif not cancelled:
            self.mark_completed()

    def fail(self, message):
        if not self.exists():
            return
        self.state = "failed"
        self.task.center.update_row(
            self.row_id,
            status="Failed", statistics=str(message),
            action="Dismiss", action_enabled=True,
            state="failed")

    def destroy(self):
        self.task._unindex_row(self, self.name)
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
        self._rows_by_name = {}
        self._rows_by_leaf = {}
        self._active_row = None
        self._retry_callback = None
        self._retry_pending = False
        self._progress_delivery = None
        self._build_rows()

    def set_progress_delivery(self, delivery):
        self._progress_delivery = weakref.ref(delivery)

    def flush_progress(self, time_budget_ms=3):
        delivery = self._progress_delivery() if self._progress_delivery is not None else None
        if delivery is not None:
            delivery.flush_progress(time_budget_ms=time_budget_ms)

    def set_retry(self, callback):
        self._retry_callback = callback

    def retry_ready(self):
        self._retry_pending = False
        if self.state != 'failed' or not callable(self._retry_callback):
            return
        for row in self.rows:
            if row.exists() and row.state in ('failed', 'skipped'):
                self.center.update_row(row.row_id, action='Retry', action_enabled=True)

    def request_retry(self):
        if self.state != 'failed' or self._retry_pending or not callable(self._retry_callback):
            return False
        self._retry_pending = True
        for row in self.rows:
            if row.exists() and row.state in ('failed', 'skipped'):
                self.center.update_row(row.row_id, action_enabled=False)
        try:
            self._retry_callback(self)
        except Exception:
            self.retry_ready()
            raise
        return True

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
                self._append_row(item)
        else:
            self._append_row('Preparing...', placeholder=True)

    def _index_row(self, row):
        self._rows_by_name[row.name] = row
        leaf = self._leaf_name(row.name)
        previous = self._rows_by_leaf.get(leaf)
        if previous is None:
            self._rows_by_leaf[leaf] = row
        elif isinstance(previous, list):
            if row not in previous:
                previous.append(row)
        elif previous is not row:
            self._rows_by_leaf[leaf] = [previous, row]

    def _unindex_row(self, row, name):
        if self._rows_by_name.get(name) is row:
            self._rows_by_name.pop(name, None)
        leaf = self._leaf_name(name)
        previous = self._rows_by_leaf.get(leaf)
        if previous is row:
            self._rows_by_leaf.pop(leaf, None)
        elif isinstance(previous, list) and row in previous:
            previous.remove(row)
            if len(previous) == 1:
                self._rows_by_leaf[leaf] = previous[0]

    def _append_row(self, name, placeholder=False):
        row = TransferItemRow(self, name, placeholder=placeholder)
        self.rows.append(row)
        self._index_row(row)
        return row

    def winfo_exists(self):
        return any(row.exists() for row in self.rows)

    def set_preparing(self, message):
        """Show preflight work while cancellation is already available."""
        if self.state != "running":
            return
        for row in self.rows:
            if row.exists() and row.state == "queued":
                row.set_status("queued", message)

    def _row_for_name(self, name):
        name = str(name or "Preparing...")
        if (len(self.rows) == 1 and self.rows[0].placeholder and
                self.rows[0].state == "queued"):
            self.rows[0].rename(name)
            return self.rows[0]

        leaf = self._leaf_name(name)
        exact = self._rows_by_name.get(name)
        if exact is not None:
            return exact
        if self._active_row is not None and self._leaf_name(self._active_row.name) == leaf:
            return self._active_row
        matches = self._rows_by_leaf.get(leaf)
        if isinstance(matches, list):
            return next(
                (row for row in matches
                  if row.state not in ("completed", "failed", "cancelled")),
                matches[-1],
            )
        if matches is not None:
            return matches
        return self._append_row(name)

    def update_progress(
            self, name, current_done, current_total,
            overall_done, overall_total):
        del overall_done, overall_total
        if self.state != "running" or not self.winfo_exists():
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
                    action_enabled=True, state="skipped")
            else:
                self.center.update_row(
                    row.row_id,
                    action="Dismiss", action_enabled=True,
                    state=row.state)
        self.center.task_failed(self)
        self.retry_ready()

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
                status="Cancelling...", action_enabled=False,
                state="cancelling")


class TransferCenterLogic:
    """Task/state operations shared by native, DPG and floating front ends."""

    WIDTH = 700
    HEIGHT = 245
    AUTO_REMOVE_DELAY_MS = 120

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
        elif task.state == 'failed' and callable(task._retry_callback):
            row = next((row for row in task.rows if row.row_id == row_id), None)
            if row is not None and row.state in ('failed', 'skipped'):
                task.request_retry()
            else:
                self.remove_task(task)
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
        visible = getattr(self, 'isVisible', None)
        if not callable(visible) or not visible():
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
        task._retry_callback = None
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
                    row.row_id, status="Cancelling...", action_enabled=False,
                    state="cancelling")
