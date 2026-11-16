"""Backend-neutral, UI-thread-owned event dispatcher without a timer thread."""
import heapq
import threading
import time
from collections import deque

from .dispatcher_protocol import QAbstractEventDispatcher


class QEventDispatcher(QAbstractEventDispatcher):
    """Thread-safe posting/cancellation; callbacks execute only on the owner.

    Platform hosts combine ``nextDeadlineMs`` with their native event wait and
    install ``setWakeCallback`` to interrupt that wait for earlier worker work.
    This class never renders or blocks the GUI thread itself.
    """

    def __init__(self, *, clock=None):
        self._clock = time.monotonic if clock is None else clock
        self._owner_thread = threading.get_ident()
        self._lock = threading.Lock()
        self._deadlines = []
        self._callbacks = {}
        self._sequence = 0
        self._closed = False
        self._processing = False
        self._wake_callback = None
        self._wake_pending = False
        # Canonical keyed coalescing lives beside callback ownership so every
        # host (GUI or worker) observes the same lifetime/cancellation rules.
        self._coalesced_keys = {}
        self._token_keys = {}
        self._turn_history = deque(maxlen=256)
        self._callback_history = deque(maxlen=1024)
        self._queue_wait_history = deque(maxlen=1024)
        self._turn_serial = 0
        self._turn_totals = {
            "turns": 0,
            "ready": 0,
            "processed": 0,
            "deferred": 0,
            "cancelled": 0,
            "cancelled_or_missing": 0,
            "callback_executions": 0,
            "callback_errors": 0,
            "queue_wait_samples": 0,
        }

    def _discard_cancelled_head(self):
        # Caller holds _lock. Cancellation releases payloads immediately.
        while self._deadlines and self._deadlines[0][1] not in self._callbacks:
            heapq.heappop(self._deadlines)

    def setWakeCallback(self, callback):
        if callback is not None and not callable(callback):
            raise TypeError('wake callback must be callable or None')
        with self._lock:
            if self._closed:
                return False
            previous = self._wake_callback
            self._wake_callback = callback
            self._wake_pending = False
        del previous
        return True

    def after(self, delay_ms, callback, *args, priority=0, key=None):
        """Schedule a callback on the owner thread.

        ``priority`` follows Qt's posted-event convention: larger values run
        before lower values when callbacks become ready in the same dispatcher
        turn. Deadlines still dominate priority, so a future high-priority task
        never jumps ahead of already-due work.
        """
        if not callable(callback):
            raise TypeError('callback must be callable')
        due = self._clock() + max(0, int(delay_ms or 0)) / 1000.0
        priority = int(priority or 0)
        wake = None
        with self._lock:
            if self._closed:
                return None
            self._discard_cancelled_head()
            earlier = not self._deadlines or due < self._deadlines[0][0]
            if key is not None:
                existing = self._coalesced_keys.get(key)
                if existing is not None and existing in self._callbacks:
                    return None
                if existing is not None:
                    self._coalesced_keys.pop(key, None)
            self._sequence += 1
            token = self._sequence
            self._callbacks[token] = (callback, args, priority)
            if key is not None:
                self._coalesced_keys[key] = token
                self._token_keys[token] = key
            heapq.heappush(self._deadlines, (due, token))
            # Cross-thread ready work must wake a native wait even when an
            # owner-thread callback was already queued.  Otherwise a same-turn
            # callback can leave the owner sleeping while worker results pile up.
            cross_thread = threading.get_ident() != self._owner_thread
            ready_now = due <= self._clock()
            if ((earlier or ready_now) and not self._wake_pending and
                    self._wake_callback is not None and cross_thread):
                self._wake_pending = True
                wake = self._wake_callback
        if wake is not None:
            try:
                wake()
            except Exception:
                with self._lock:
                    self._wake_pending = False
                raise
        return token

    def post(self, callback, *args, priority=0, key=None):
        """Queue callback for the next dispatcher turn without inline delivery.

        ``key`` provides Qt-style posted-work coalescing: while one callback for
        the key is pending, duplicate posts are rejected.  The key is released
        immediately before delivery (or on cancellation), so callbacks may
        safely repost the same key for a later turn.
        """
        return self.after(0, callback, *args, priority=priority, key=key)

    def postCoalesced(self, key, callback, *args, priority=0):
        if key is None:
            raise ValueError('coalesced post key must not be None')
        return self.post(callback, *args, priority=priority, key=key)

    def postLatest(self, key, callback, *args, priority=0):
        """Post keyed work while retaining only the newest pending payload.

        Unlike :meth:`postCoalesced`, which rejects a duplicate key, this method
        updates the existing callback payload in place. The original deadline
        and queue position are retained, so a worker burst produces one GUI
        delivery with the latest value and no extra wake/render turn.
        """
        if key is None:
            raise ValueError('latest post key must not be None')
        if not callable(callback):
            raise TypeError('callback must be callable')
        priority = int(priority or 0)
        wake = None
        with self._lock:
            if self._closed:
                return None
            existing = self._coalesced_keys.get(key)
            if existing is not None and existing in self._callbacks:
                _old_callback, _old_args, old_priority = self._callbacks[existing]
                self._callbacks[existing] = (callback, args, max(int(old_priority), priority))
                return existing
            if existing is not None:
                self._coalesced_keys.pop(key, None)
            due = self._clock()
            self._discard_cancelled_head()
            earlier = not self._deadlines or due < self._deadlines[0][0]
            self._sequence += 1
            token = self._sequence
            self._callbacks[token] = (callback, args, priority)
            self._coalesced_keys[key] = token
            self._token_keys[token] = key
            heapq.heappush(self._deadlines, (due, token))
            cross_thread = threading.get_ident() != self._owner_thread
            if ((earlier or due <= self._clock()) and not self._wake_pending and
                    self._wake_callback is not None and cross_thread):
                self._wake_pending = True
                wake = self._wake_callback
        if wake is not None:
            try:
                wake()
            except Exception:
                with self._lock:
                    self._wake_pending = False
                raise
        return token

    def hasCoalescedKey(self, key):
        with self._lock:
            token = self._coalesced_keys.get(key)
            return token is not None and token in self._callbacks

    def after_cancel(self, token):
        if token is None:
            return False
        with self._lock:
            payload = self._callbacks.pop(token, None)
            if payload is None:
                return False
            key = self._token_keys.pop(token, None)
            if key is not None and self._coalesced_keys.get(key) == token:
                self._coalesced_keys.pop(key, None)
            self._discard_cancelled_head()
            if len(self._deadlines) > max(64, len(self._callbacks) * 2 + 32):
                self._deadlines[:] = [entry for entry in self._deadlines
                                      if entry[1] in self._callbacks]
                heapq.heapify(self._deadlines)
            self._turn_totals['cancelled'] += 1
        # Drop callback references outside the lock (finalizers may re-enter).
        return True

    def ownerThreadId(self):
        """Return the thread that owns callback delivery."""
        return self._owner_thread

    def isOwnerThread(self):
        return threading.get_ident() == self._owner_thread

    def remainingTime(self, token):
        """Return milliseconds until a callback deadline, or -1 if absent."""
        if token is None:
            return -1
        with self._lock:
            if self._closed or token not in self._callbacks:
                return -1
            now = self._clock()
            for due, queued_token in self._deadlines:
                if queued_token == token:
                    return max(0.0, due - now) * 1000.0
        return -1

    def nextDeadlineMs(self):
        """Time to the next callback, zero for due work, or None when empty."""
        with self._lock:
            self._discard_cancelled_head()
            if self._closed or not self._deadlines:
                return None
            return max(0.0, self._deadlines[0][0] - self._clock()) * 1000.0

    def hasPendingEvents(self):
        """Whether a callback is due now, not merely scheduled for the future."""
        delay = self.nextDeadlineMs()
        return delay is not None and delay <= 0

    def pendingCount(self):
        with self._lock:
            return len(self._callbacks)

    def isClosed(self):
        with self._lock:
            return self._closed

    @staticmethod
    def _percentile(values, percentile):
        if not values:
            return None
        ordered = sorted(float(v) for v in values)
        if len(ordered) == 1:
            return ordered[0]
        rank = (len(ordered) - 1) * (float(percentile) / 100.0)
        low = int(rank)
        high = min(len(ordered) - 1, low + 1)
        fraction = rank - low
        return ordered[low] * (1.0 - fraction) + ordered[high] * fraction

    @staticmethod
    def _safe_callback_label(callback, max_length=160):
        """Return a bounded label without retaining or repr()-ing callback owners."""
        try:
            module = getattr(callback, '__module__', None) or ''
            qualname = (getattr(callback, '__qualname__', None) or
                        getattr(callback, '__name__', None))
            if not qualname:
                call = getattr(type(callback), '__call__', None)
                qualname = (getattr(call, '__qualname__', None) or
                            getattr(type(callback), '__name__', 'callback'))
            label = ('%s.%s' % (module, qualname)).strip('.')
        except Exception:
            label = 'callback'
        if len(label) > int(max_length):
            label = label[:max(0, int(max_length) - 1)] + '…'
        return label

    def turnDiagnosticsSnapshot(self):
        """Return bounded dispatcher-turn latency/work diagnostics.

        The snapshot is observational only.  No callbacks are processed and no
        deadline/wake state is changed while collecting it.
        """
        with self._lock:
            history = tuple(self._turn_history)
            totals = dict(self._turn_totals)
        durations = [row[1] for row in history]
        return {
            'sample_count': len(history),
            'turns_total': int(totals.get('turns', 0)),
            'ready_total': int(totals.get('ready', 0)),
            'processed_total': int(totals.get('processed', 0)),
            'deferred_total': int(totals.get('deferred', 0)),
            'cancelled_total': int(totals.get('cancelled', 0)),
            'cancelled_or_missing_total': int(totals.get('cancelled_or_missing', 0)),
            'turn_duration_ms_p50': self._percentile(durations, 50.0),
            'turn_duration_ms_p95': self._percentile(durations, 95.0),
            'turn_duration_ms_max': max(durations) if durations else None,
            'last_turn': None if not history else {
                'serial': history[-1][0],
                'duration_ms': history[-1][1],
                'ready': history[-1][2],
                'processed': history[-1][3],
                'deferred': history[-1][4],
                'cancelled_or_missing': history[-1][5],
            },
        }


    def callbackDiagnosticsSnapshot(self):
        """Return bounded per-callback execution-duration diagnostics.

        Callback duration is measured independently from whole dispatcher-turn
        latency so one slow callback can be distinguished from a long turn that
        merely processed many fast callbacks.  Collection is observational and
        uses the dispatcher monotonic clock; no scheduler work is performed.
        """
        with self._lock:
            history = tuple(self._callback_history)
            totals = dict(self._turn_totals)
        durations = [row[1] for row in history]
        errors = [row for row in history if row[2]]
        queue_waits = [row[3] for row in history]
        return {
            'sample_count': len(history),
            'executions_total': int(totals.get('callback_executions', 0)),
            'errors_total': int(totals.get('callback_errors', 0)),
            'queue_wait_samples_total': int(totals.get('queue_wait_samples', 0)),
            'execution_duration_ms_p50': self._percentile(durations, 50.0),
            'execution_duration_ms_p95': self._percentile(durations, 95.0),
            'execution_duration_ms_max': max(durations) if durations else None,
            'queue_wait_ms_p50': self._percentile(queue_waits, 50.0),
            'queue_wait_ms_p95': self._percentile(queue_waits, 95.0),
            'queue_wait_ms_max': max(queue_waits) if queue_waits else None,
            'error_samples': len(errors),
            'last_callback': None if not history else {
                'serial': history[-1][0],
                'duration_ms': history[-1][1],
                'error': bool(history[-1][2]),
                'queue_wait_ms': history[-1][3],
                'priority': int(history[-1][5]) if len(history[-1]) > 5 else 0,
                'label': history[-1][6] if len(history[-1]) > 6 else None,
            },
        }

    def recentDiagnosticsSnapshot(self, window_seconds=5.0, *, exclude_recent_seconds=0.0):
        """Return bounded dispatcher metrics for a recent time window.

        ``exclude_recent_seconds`` makes it possible to build a non-overlapping
        baseline immediately preceding the current window.  This avoids recent
        stalls contaminating their own baseline while remaining sampler-free.
        """
        window = max(0.0, float(window_seconds))
        exclude = max(0.0, float(exclude_recent_seconds))
        now = self._clock()
        cutoff = now - window
        upper = now - exclude
        with self._lock:
            turns = tuple(row for row in self._turn_history
                          if len(row) > 6 and cutoff <= row[6] <= upper)
            callbacks = tuple(row for row in self._callback_history
                              if len(row) > 4 and cutoff <= row[4] <= upper)
        turn_durations = [row[1] for row in turns]
        callback_durations = [row[1] for row in callbacks]
        queue_waits = [row[3] for row in callbacks]
        return {
            'window_seconds': window,
            'exclude_recent_seconds': exclude,
            'turn_sample_count': len(turns),
            'callback_sample_count': len(callbacks),
            'turn_duration_ms_p50': self._percentile(turn_durations, 50.0),
            'turn_duration_ms_p95': self._percentile(turn_durations, 95.0),
            'callback_duration_ms_p50': self._percentile(callback_durations, 50.0),
            'callback_duration_ms_p95': self._percentile(callback_durations, 95.0),
            'queue_wait_ms_p50': self._percentile(queue_waits, 50.0),
            'queue_wait_ms_p95': self._percentile(queue_waits, 95.0),
            'queue_wait_ms_max': max(queue_waits) if queue_waits else None,
        }

    def priorityDiagnosticsSnapshot(self, *, window_seconds=30.0,
                                    starvation_threshold_ms=50.0,
                                    min_samples=1):
        """Return recent queue-wait diagnostics grouped by callback priority.

        This view distinguishes low-priority starvation from a dispatcher-wide
        stall without changing delivery order.  Samples are retained in the
        existing bounded callback history; no sampler or timer is created.
        """
        window = max(0.0, float(window_seconds))
        threshold = max(0.0, float(starvation_threshold_ms))
        required = max(0, int(min_samples))
        cutoff = self._clock() - window
        with self._lock:
            rows = tuple(row for row in self._callback_history
                         if len(row) > 5 and row[4] >= cutoff)
        grouped = {}
        for row in rows:
            priority = int(row[5])
            grouped.setdefault(priority, []).append(float(row[3]))
        priorities = {}
        for priority, waits in sorted(grouped.items(), reverse=True):
            starved = sum(1 for value in waits if value > threshold)
            count = len(waits)
            priorities[str(priority)] = {
                'priority': priority,
                'sample_count': count,
                'queue_wait_ms_p50': self._percentile(waits, 50.0),
                'queue_wait_ms_p95': self._percentile(waits, 95.0),
                'queue_wait_ms_max': max(waits) if waits else None,
                'starvation_threshold_ms': threshold,
                'starved_samples': starved,
                'starvation_fraction': (float(starved) / count) if count else 0.0,
                'ready': count >= required,
            }
        return {
            'window_seconds': window,
            'min_samples': required,
            'starvation_threshold_ms': threshold,
            'sample_count': len(rows),
            'priorities': priorities,
        }

    def priorityComparisonSnapshot(self, *, current_window_seconds=5.0,
                                   baseline_window_seconds=30.0,
                                   min_current_samples=3,
                                   min_baseline_samples=8):
        """Compare per-priority queue-wait percentiles against a non-overlap baseline."""
        current_window = max(0.0, float(current_window_seconds))
        baseline_window = max(0.0, float(baseline_window_seconds))
        now = self._clock()
        current_cutoff = now - current_window
        baseline_cutoff = now - baseline_window
        baseline_upper = now - current_window
        with self._lock:
            rows = tuple(self._callback_history)
        current_groups, baseline_groups = {}, {}
        for row in rows:
            if len(row) <= 5:
                continue
            ts, priority, wait = float(row[4]), int(row[5]), float(row[3])
            if ts >= current_cutoff:
                current_groups.setdefault(priority, []).append(wait)
            elif baseline_cutoff <= ts <= baseline_upper:
                baseline_groups.setdefault(priority, []).append(wait)
        priorities = {}
        all_priorities = sorted(set(current_groups) | set(baseline_groups), reverse=True)
        current_required = max(0, int(min_current_samples))
        baseline_required = max(0, int(min_baseline_samples))
        for priority in all_priorities:
            current = current_groups.get(priority, [])
            baseline = baseline_groups.get(priority, [])
            current_p95 = self._percentile(current, 95.0)
            baseline_p95 = self._percentile(baseline, 95.0)
            delta = None
            ratio = None
            if current_p95 is not None and baseline_p95 is not None:
                delta = float(current_p95) - float(baseline_p95)
                if float(baseline_p95) > 0.0:
                    ratio = float(current_p95) / float(baseline_p95)
            priorities[str(priority)] = {
                'priority': priority,
                'ready': len(current) >= current_required and len(baseline) >= baseline_required,
                'current_sample_count': len(current),
                'baseline_sample_count': len(baseline),
                'current_queue_wait_ms_p95': current_p95,
                'baseline_queue_wait_ms_p95': baseline_p95,
                'queue_wait_p95_delta_ms': delta,
                'queue_wait_p95_ratio': ratio,
            }
        return {
            'current_window_seconds': current_window,
            'baseline_window_seconds': baseline_window,
            'min_current_samples': current_required,
            'min_baseline_samples': baseline_required,
            'priorities': priorities,
        }

    def priorityRegressionSnapshot(self, *, current_window_seconds=5.0,
                                   baseline_window_seconds=30.0,
                                   min_current_samples=3, min_baseline_samples=8,
                                   max_p95_ratio=2.5, max_p95_delta_ms=25.0):
        comparison = self.priorityComparisonSnapshot(
            current_window_seconds=current_window_seconds,
            baseline_window_seconds=baseline_window_seconds,
            min_current_samples=min_current_samples,
            min_baseline_samples=min_baseline_samples)
        breached = []
        for key, row in comparison['priorities'].items():
            if not row.get('ready'):
                continue
            ratio = row.get('queue_wait_p95_ratio')
            delta = row.get('queue_wait_p95_delta_ms')
            if ((ratio is not None and float(ratio) > float(max_p95_ratio)) or
                    (delta is not None and float(delta) > float(max_p95_delta_ms))):
                breached.append(int(row['priority']))
        return {
            'ready': any(row.get('ready') for row in comparison['priorities'].values()),
            'threshold_breached': bool(breached),
            'breached_priorities': breached,
            'thresholds': {
                'max_p95_ratio': float(max_p95_ratio),
                'max_p95_delta_ms': float(max_p95_delta_ms),
            },
            'comparison': comparison,
        }


    @staticmethod
    def _callback_category(label, depth=2):
        parts = [part for part in str(label or 'callback').split('.') if part]
        depth = max(1, int(depth or 1))
        return '.'.join(parts[:depth]) if parts else 'callback'

    def callbackCategoryDiagnosticsSnapshot(self, *, window_seconds=30.0, category_depth=2):
        """Aggregate recent callback latency by a safe module/qualname category."""
        cutoff = self._clock() - max(0.0, float(window_seconds))
        with self._lock:
            rows = tuple(row for row in self._callback_history
                         if len(row) > 6 and float(row[4]) >= cutoff)
        groups = {}
        for row in rows:
            category = self._callback_category(row[6], category_depth)
            item = groups.setdefault(category, {'waits': [], 'durations': [], 'errors': 0})
            item['waits'].append(float(row[3]))
            item['durations'].append(float(row[1]))
            item['errors'] += int(bool(row[2]))
        categories = {}
        for category, item in sorted(groups.items()):
            waits = item['waits']; durations = item['durations']
            categories[category] = {
                'sample_count': len(waits),
                'queue_wait_ms_p50': self._percentile(waits, 50.0),
                'queue_wait_ms_p95': self._percentile(waits, 95.0),
                'queue_wait_ms_max': max(waits) if waits else None,
                'callback_duration_ms_p95': self._percentile(durations, 95.0),
                'error_count': int(item['errors']),
            }
        return {
            'window_seconds': max(0.0, float(window_seconds)),
            'category_depth': max(1, int(category_depth or 1)),
            'sample_count': len(rows),
            'categories': categories,
        }

    def callbackCategoryComparisonSnapshot(self, *, current_window_seconds=5.0,
                                           baseline_window_seconds=30.0,
                                           min_current_samples=3,
                                           min_baseline_samples=8,
                                           category_depth=2):
        """Compare callback-category latency against a non-overlap baseline."""
        current_window = max(0.0, float(current_window_seconds))
        baseline_window = max(0.0, float(baseline_window_seconds))
        now = self._clock()
        current_cutoff = now - current_window
        baseline_cutoff = now - baseline_window
        baseline_upper = now - current_window
        with self._lock:
            rows = tuple(self._callback_history)
        current_groups, baseline_groups = {}, {}
        for row in rows:
            if len(row) <= 6:
                continue
            ts = float(row[4])
            category = self._callback_category(row[6], category_depth)
            item = (float(row[3]), float(row[1]))
            if ts >= current_cutoff:
                current_groups.setdefault(category, []).append(item)
            elif baseline_cutoff <= ts <= baseline_upper:
                baseline_groups.setdefault(category, []).append(item)
        current_required = max(0, int(min_current_samples))
        baseline_required = max(0, int(min_baseline_samples))
        categories = {}
        for category in sorted(set(current_groups) | set(baseline_groups)):
            current = current_groups.get(category, [])
            baseline = baseline_groups.get(category, [])
            current_wait = [row[0] for row in current]
            baseline_wait = [row[0] for row in baseline]
            current_duration = [row[1] for row in current]
            baseline_duration = [row[1] for row in baseline]
            current_wait_p95 = self._percentile(current_wait, 95.0)
            baseline_wait_p95 = self._percentile(baseline_wait, 95.0)
            current_cb_p95 = self._percentile(current_duration, 95.0)
            baseline_cb_p95 = self._percentile(baseline_duration, 95.0)
            wait_delta = None
            wait_ratio = None
            callback_delta = None
            if current_wait_p95 is not None and baseline_wait_p95 is not None:
                wait_delta = float(current_wait_p95) - float(baseline_wait_p95)
                if float(baseline_wait_p95) > 0.0:
                    wait_ratio = float(current_wait_p95) / float(baseline_wait_p95)
            if current_cb_p95 is not None and baseline_cb_p95 is not None:
                callback_delta = float(current_cb_p95) - float(baseline_cb_p95)
            categories[category] = {
                'category': category,
                'ready': len(current) >= current_required and len(baseline) >= baseline_required,
                'current_sample_count': len(current),
                'baseline_sample_count': len(baseline),
                'current_queue_wait_ms_p95': current_wait_p95,
                'baseline_queue_wait_ms_p95': baseline_wait_p95,
                'queue_wait_p95_delta_ms': wait_delta,
                'queue_wait_p95_ratio': wait_ratio,
                'current_callback_duration_ms_p95': current_cb_p95,
                'baseline_callback_duration_ms_p95': baseline_cb_p95,
                'callback_duration_p95_delta_ms': callback_delta,
            }
        return {
            'current_window_seconds': current_window,
            'baseline_window_seconds': baseline_window,
            'category_depth': max(1, int(category_depth or 1)),
            'min_current_samples': current_required,
            'min_baseline_samples': baseline_required,
            'categories': categories,
        }

    def callbackCategoryRegressionSnapshot(self, *, current_window_seconds=5.0,
                                           baseline_window_seconds=30.0,
                                           min_current_samples=3,
                                           min_baseline_samples=8,
                                           category_depth=2,
                                           max_p95_ratio=2.5,
                                           max_p95_delta_ms=25.0,
                                           max_callback_p95_delta_ms=8.0):
        comparison = self.callbackCategoryComparisonSnapshot(
            current_window_seconds=current_window_seconds,
            baseline_window_seconds=baseline_window_seconds,
            min_current_samples=min_current_samples,
            min_baseline_samples=min_baseline_samples,
            category_depth=category_depth)
        breached = []
        checks = {}
        for category, row in comparison['categories'].items():
            if not row.get('ready'):
                continue
            ratio = row.get('queue_wait_p95_ratio')
            wait_delta = row.get('queue_wait_p95_delta_ms')
            callback_delta = row.get('callback_duration_p95_delta_ms')
            item_checks = {
                'queue_wait_p95_ratio': bool(ratio is not None and float(ratio) > float(max_p95_ratio)),
                'queue_wait_p95_delta_ms': bool(wait_delta is not None and float(wait_delta) > float(max_p95_delta_ms)),
                'callback_duration_p95_delta_ms': bool(callback_delta is not None and float(callback_delta) > float(max_callback_p95_delta_ms)),
            }
            checks[category] = item_checks
            if any(item_checks.values()):
                breached.append(category)
        return {
            'ready': any(row.get('ready') for row in comparison['categories'].values()),
            'threshold_breached': bool(breached),
            'breached_categories': breached,
            'checks': checks,
            'thresholds': {
                'max_p95_ratio': float(max_p95_ratio),
                'max_p95_delta_ms': float(max_p95_delta_ms),
                'max_callback_p95_delta_ms': float(max_callback_p95_delta_ms),
            },
            'comparison': comparison,
        }

    def callbackCategorySustainedRegressionSnapshot(self, *,
                                                     current_window_seconds=15.0,
                                                     baseline_window_seconds=60.0,
                                                     min_current_samples=8,
                                                     min_baseline_samples=24,
                                                     category_depth=2,
                                                     max_p95_ratio=2.5,
                                                     max_p95_delta_ms=25.0,
                                                     max_callback_p95_delta_ms=8.0,
                                                     top_limit=5):
        """Return long-window category regression inputs for watchdog hysteresis.

        The dispatcher remains stateless: this method only evaluates a longer
        current window and ranks breached categories. Consecutive breach/recovery
        hysteresis remains owned by the watchdog.
        """
        regression = self.callbackCategoryRegressionSnapshot(
            current_window_seconds=current_window_seconds,
            baseline_window_seconds=baseline_window_seconds,
            min_current_samples=min_current_samples,
            min_baseline_samples=min_baseline_samples,
            category_depth=category_depth,
            max_p95_ratio=max_p95_ratio,
            max_p95_delta_ms=max_p95_delta_ms,
            max_callback_p95_delta_ms=max_callback_p95_delta_ms)
        rows = []
        comparison = (regression.get('comparison') or {}).get('categories') or {}
        checks = regression.get('checks') or {}
        for category in regression.get('breached_categories') or ():
            row = comparison.get(category) or {}
            ratio = row.get('queue_wait_p95_ratio')
            wait_delta = row.get('queue_wait_p95_delta_ms')
            callback_delta = row.get('callback_duration_p95_delta_ms')
            score = max(
                float(ratio or 0.0) / max(1e-9, float(max_p95_ratio)),
                float(wait_delta or 0.0) / max(1e-9, float(max_p95_delta_ms)),
                float(callback_delta or 0.0) / max(1e-9, float(max_callback_p95_delta_ms)))
            rows.append({
                'category': category,
                'score': score,
                'checks': dict(checks.get(category) or {}),
                'current_sample_count': int(row.get('current_sample_count', 0) or 0),
                'baseline_sample_count': int(row.get('baseline_sample_count', 0) or 0),
                'queue_wait_p95_ratio': ratio,
                'queue_wait_p95_delta_ms': wait_delta,
                'callback_duration_p95_delta_ms': callback_delta,
            })
        rows.sort(key=lambda item: (-float(item.get('score', 0.0)), item.get('category', '')))
        limit = max(0, int(top_limit))
        return {
            'ready': bool(regression.get('ready')),
            'threshold_breached': bool(regression.get('threshold_breached')),
            'breached_category_count': len(regression.get('breached_categories') or ()),
            'breached_categories': list(regression.get('breached_categories') or ()),
            'top_regressed_categories': rows[:limit] if limit else [],
            'current_window_seconds': float(current_window_seconds),
            'baseline_window_seconds': float(baseline_window_seconds),
            'regression': regression,
        }

    def sustainedStarvationSnapshot(self, *, window_seconds=30.0,
                                    starvation_threshold_ms=50.0,
                                    min_samples=5, min_starvation_fraction=0.5):
        """Identify priorities suffering sustained, not merely bursty, queue starvation."""
        recent = self.priorityDiagnosticsSnapshot(
            window_seconds=window_seconds,
            starvation_threshold_ms=starvation_threshold_ms,
            min_samples=min_samples)
        fraction_threshold = min(1.0, max(0.0, float(min_starvation_fraction)))
        sustained = []
        for key, row in (recent.get('priorities') or {}).items():
            if row.get('ready') and float(row.get('starvation_fraction', 0.0) or 0.0) >= fraction_threshold:
                sustained.append(int(row.get('priority', key)))
        return {
            'ready': any(row.get('ready') for row in (recent.get('priorities') or {}).values()),
            'threshold_breached': bool(sustained),
            'sustained_priorities': sorted(sustained, reverse=True),
            'min_starvation_fraction': fraction_threshold,
            'diagnostics': recent,
        }

    def longQueueWaitCallbacksSnapshot(self, *, window_seconds=30.0,
                                       threshold_ms=50.0, limit=8):
        """Return bounded labels for callbacks with the longest recent queue waits."""
        cutoff = self._clock() - max(0.0, float(window_seconds))
        with self._lock:
            rows = tuple(row for row in self._callback_history
                         if len(row) > 6 and float(row[4]) >= cutoff and
                         float(row[3]) >= float(threshold_ms))
        rows = sorted(rows, key=lambda row: float(row[3]), reverse=True)[:max(0, int(limit))]
        return {
            'window_seconds': max(0.0, float(window_seconds)),
            'threshold_ms': max(0.0, float(threshold_ms)),
            'count': len(rows),
            'callbacks': [
                {
                    'serial': int(row[0]),
                    'label': row[6],
                    'priority': int(row[5]),
                    'queue_wait_ms': float(row[3]),
                    'duration_ms': float(row[1]),
                    'error': bool(row[2]),
                } for row in rows
            ],
        }

    def queueWaitComparisonSnapshot(self, *, current_window_seconds=5.0,
                                    baseline_window_seconds=30.0,
                                    min_current_samples=5,
                                    min_baseline_samples=20):
        """Compare recent queue wait with a longer retained dispatcher window."""
        current = self.recentDiagnosticsSnapshot(current_window_seconds)
        baseline = self.recentDiagnosticsSnapshot(
            baseline_window_seconds, exclude_recent_seconds=current_window_seconds)
        current_samples = int(current.get('callback_sample_count', 0) or 0)
        baseline_samples = int(baseline.get('callback_sample_count', 0) or 0)
        ready = (current_samples >= max(0, int(min_current_samples)) and
                 baseline_samples >= max(0, int(min_baseline_samples)))
        current_p95 = current.get('queue_wait_ms_p95')
        baseline_p95 = baseline.get('queue_wait_ms_p95')
        delta = None
        ratio = None
        if current_p95 is not None and baseline_p95 is not None:
            delta = float(current_p95) - float(baseline_p95)
            if float(baseline_p95) > 0.0:
                ratio = float(current_p95) / float(baseline_p95)
        return {
            'ready': bool(ready),
            'min_current_samples': max(0, int(min_current_samples)),
            'min_baseline_samples': max(0, int(min_baseline_samples)),
            'current': current,
            'baseline': baseline,
            'queue_wait_p95_delta_ms': delta,
            'queue_wait_p95_ratio': ratio,
        }

    def queueWaitRegressionSnapshot(self, *, current_window_seconds=5.0,
                                    baseline_window_seconds=30.0,
                                    min_current_samples=5,
                                    min_baseline_samples=20,
                                    max_p95_ratio=2.0,
                                    max_p95_delta_ms=20.0):
        """Evaluate sample-gated queue-wait regression thresholds."""
        comparison = self.queueWaitComparisonSnapshot(
            current_window_seconds=current_window_seconds,
            baseline_window_seconds=baseline_window_seconds,
            min_current_samples=min_current_samples,
            min_baseline_samples=min_baseline_samples)
        ready = bool(comparison.get('ready'))
        ratio = comparison.get('queue_wait_p95_ratio')
        delta = comparison.get('queue_wait_p95_delta_ms')
        checks = {
            'queue_wait_p95_ratio': bool(ready and ratio is not None and
                                         float(ratio) > float(max_p95_ratio)),
            'queue_wait_p95_delta_ms': bool(ready and delta is not None and
                                            float(delta) > float(max_p95_delta_ms)),
        }
        return {
            'ready': ready,
            'threshold_breached': bool(ready and any(checks.values())),
            'checks': checks,
            'thresholds': {
                'max_p95_ratio': float(max_p95_ratio),
                'max_p95_delta_ms': float(max_p95_delta_ms),
            },
            'comparison': comparison,
        }

    def compactDiagnosticsSnapshot(self):
        """Compact JSON-friendly dispatcher state for watchdog/crash reports."""
        core = self.diagnosticsSnapshot()
        turns = core.get('turns', {}) or {}
        callbacks = core.get('callbacks', {}) or {}
        return {
            'closed': bool(core.get('closed')),
            'pending': int(core.get('pending_count', 0) or 0),
            'due': int(core.get('due_count', 0) or 0),
            'next_ms': core.get('next_deadline_ms'),
            'turn_p95_ms': turns.get('turn_duration_ms_p95'),
            'turn_max_ms': turns.get('turn_duration_ms_max'),
            'callback_p95_ms': callbacks.get('execution_duration_ms_p95'),
            'callback_max_ms': callbacks.get('execution_duration_ms_max'),
            'callback_errors': int(callbacks.get('errors_total', 0) or 0),
            'queue_wait_p95_ms': callbacks.get('queue_wait_ms_p95'),
            'queue_wait_regression': self.queueWaitRegressionSnapshot(),
            'priority_wait_30s': self.priorityDiagnosticsSnapshot(window_seconds=30.0),
            'priority_regression': self.priorityRegressionSnapshot(),
            'category_regression': self.callbackCategoryRegressionSnapshot(),
            'long_queue_wait_callbacks': self.longQueueWaitCallbacksSnapshot(),
            'recent_5s': self.recentDiagnosticsSnapshot(5.0),
        }

    def diagnosticsSnapshot(self):
        """Return a side-effect-free scheduler snapshot for live diagnostics."""
        with self._lock:
            self._discard_cancelled_head()
            now = self._clock()
            next_ms = None
            due_count = 0
            if self._deadlines and not self._closed:
                next_ms = max(0.0, self._deadlines[0][0] - now) * 1000.0
                due_count = sum(1 for due, token in self._deadlines
                                if token in self._callbacks and due <= now)
            priorities = [payload[2] for payload in self._callbacks.values()]
            base = {
                'owner_thread_id': self._owner_thread,
                'is_owner_thread': threading.get_ident() == self._owner_thread,
                'closed': bool(self._closed),
                'processing': bool(self._processing),
                'wake_pending': bool(self._wake_pending),
                'pending_count': len(self._callbacks),
                'due_count': due_count,
                'next_deadline_ms': next_ms,
                'highest_priority': max(priorities) if priorities else None,
                'lowest_priority': min(priorities) if priorities else None,
                'coalesced_count': len(self._coalesced_keys),
            }
        base['turns'] = self.turnDiagnosticsSnapshot()
        base['callbacks'] = self.callbackDiagnosticsSnapshot()
        return base

    def processEvents(self, max_callbacks=256, time_budget_ms=8.0, *, on_error=None):
        """Deliver one bounded owner-thread turn.

        Ready callbacks are snapshotted at turn start. Higher-priority ready
        callbacks run first; FIFO order is preserved within each priority. A
        callback remains cancellable until its own delivery begins. Work posted
        re-entrantly is deferred to the next turn, matching Qt's event-loop
        fairness rather than recursively draining newly posted work.
        """
        if threading.get_ident() != self._owner_thread:
            raise RuntimeError('event processing requires the owning thread')
        limit = None if max_callbacks is None else max(0, int(max_callbacks))
        budget = None if time_budget_ms is None else max(0, float(time_budget_ms)) / 1000.0
        started = self._clock()
        with self._lock:
            if self._closed or self._processing:
                return 0
            self._wake_pending = False
            self._processing = True
            sequence_limit = self._sequence
            ready = []
            self._discard_cancelled_head()
            while self._deadlines:
                due, token = self._deadlines[0]
                if due > started or token > sequence_limit:
                    break
                heapq.heappop(self._deadlines)
                payload = self._callbacks.get(token)
                if payload is not None:
                    ready.append((-(payload[2]), token, due))
            ready.sort()
        processed, error = 0, None
        deferred = []
        missing = 0
        ready_count = len(ready)
        try:
            for index, (_neg_priority, token, due) in enumerate(ready):
                if limit is not None and processed >= limit:
                    deferred.extend((d, t) for _p, t, d in ready[index:])
                    break
                if budget is not None and processed and self._clock() - started >= budget:
                    deferred.extend((d, t) for _p, t, d in ready[index:])
                    break
                with self._lock:
                    if self._closed:
                        break
                    payload = self._callbacks.pop(token, None)
                    key = self._token_keys.pop(token, None)
                    if key is not None and self._coalesced_keys.get(key) == token:
                        self._coalesced_keys.pop(key, None)
                if payload is None:
                    missing += 1
                    continue
                callback, args, _priority = payload
                callback_started = self._clock()
                queue_wait_ms = max(0.0, callback_started - due) * 1000.0
                callback_failed = False
                try:
                    callback(*args)
                except Exception as exc:
                    callback_failed = True
                    if on_error is None:
                        if error is None:
                            error = exc
                    else:
                        try:
                            on_error(callback, exc)
                        except Exception as handler_error:
                            if error is None:
                                error = handler_error
                finally:
                    callback_finished = self._clock()
                    callback_duration_ms = max(0.0, callback_finished - callback_started) * 1000.0
                    with self._lock:
                        callback_serial = int(self._turn_totals.get('callback_executions', 0)) + 1
                        self._turn_totals['callback_executions'] = callback_serial
                        if callback_failed:
                            self._turn_totals['callback_errors'] += 1
                        self._turn_totals['queue_wait_samples'] += 1
                        callback_label = self._safe_callback_label(callback)
                        self._callback_history.append((
                            callback_serial, float(callback_duration_ms), bool(callback_failed),
                            float(queue_wait_ms), float(callback_finished), int(_priority),
                            callback_label))
                        self._queue_wait_history.append((
                            callback_serial, float(queue_wait_ms), float(callback_started)))
                processed += 1
        finally:
            finished = self._clock()
            duration_ms = max(0.0, finished - started) * 1000.0
            deferred_count = len(deferred)
            with self._lock:
                if not self._closed:
                    for due, token in deferred:
                        if token in self._callbacks:
                            heapq.heappush(self._deadlines, (due, token))
                self._turn_serial += 1
                self._turn_history.append((
                    int(self._turn_serial), float(duration_ms), int(ready_count),
                    int(processed), int(deferred_count), int(missing), float(finished)))
                self._turn_totals['turns'] += 1
                self._turn_totals['ready'] += int(ready_count)
                self._turn_totals['processed'] += int(processed)
                self._turn_totals['deferred'] += int(deferred_count)
                self._turn_totals['cancelled_or_missing'] += int(missing)
                self._processing = False
        if error is not None:
            raise error
        return processed

    def close(self):
        """Reject new posts and release payloads without waiting for deadlines."""
        with self._lock:
            self._closed = True
            callbacks, self._callbacks = self._callbacks, {}
            self._deadlines.clear()
            self._coalesced_keys.clear()
            self._token_keys.clear()
            wake_callback = self._wake_callback
            self._wake_callback = None
            self._wake_pending = False
        callbacks.clear()
        del wake_callback


__all__ = ['QEventDispatcher']
