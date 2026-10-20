"""Response-cost-aware polling with bounded jitter and interactive recovery."""
from __future__ import annotations

import random

from .adaptive_polling import AdaptivePollingPolicy


class CostAwarePollingPolicy(AdaptivePollingPolicy):
    """Budget quiet polling against observed query cost, within user limits.

    A 10% duty target means a two-second query gets roughly 18 seconds of idle
    time. The configured maximum always wins. Changes and user refreshes retain
    the minimum delay. Small bounded jitter spreads clients after idle periods.
    Query cost is an EWMA, so one slow response does not dictate the whole session.
    """

    def __init__(self, *args, target_duty=0.1, alpha=0.25, jitter=0.1,
                 random_source=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.target_duty = min(1.0, max(0.01, float(target_duty)))
        self.alpha = min(1.0, max(0.01, float(alpha)))
        self.jitter = min(0.25, max(0.0, float(jitter)))
        self._random = random_source or random.random
        self.query_seconds = None
        self._interactive = False
        self._fast_until = 0.0
        self._query_tokens = 2.0
        self._query_token_at = self._clock()

    def _refill_query_budget(self, now):
        elapsed = max(0.0, now - self._query_token_at)
        self._query_tokens = min(2.0, self._query_tokens + elapsed / self.min_interval)
        self._query_token_at = now

    def next_query_delay(self, now=None):
        """Allow one immediate follow-up, then bound refresh bursts by min interval."""
        now = self._clock() if now is None else float(now)
        self._refill_query_budget(now)
        return max(0.0, (1.0 - self._query_tokens) * self.min_interval)

    def record_query_start(self, now=None):
        now = self._clock() if now is None else float(now)
        self._refill_query_budget(now)
        self._query_tokens = max(0.0, self._query_tokens - 1.0)

    def record_cost(self, seconds):
        seconds = max(0.0, float(seconds))
        if self.query_seconds is None:
            self.query_seconds = seconds
        else:
            self.query_seconds += self.alpha * (seconds - self.query_seconds)

    def force_fast(self, now=None):
        self._interactive = True
        return super().force_fast(now=now)

    def hold_fast(self, seconds, now=None):
        """Keep successful polling fast while a scheduler mutation propagates."""
        now = self._clock() if now is None else float(now)
        self._fast_until = max(self._fast_until, now + max(0.0, float(seconds)))
        return self.force_fast(now=now)

    def observe(self, signature, now=None):
        now = self._clock() if now is None else float(now)
        changed = not self._has_signature or signature != self._signature
        super().observe(signature, now=now)
        interactive, self._interactive = self._interactive, False
        recovering = now < self._fast_until
        if changed or interactive or recovering:
            if recovering:
                # Quiet samples before PBS exposes the change must not build
                # backoff. Start a fresh quiet period when recovery expires.
                self._stable_samples = 0
                self._last_change_at = now
            self._current_interval = self.min_interval
            return self.current_interval
        # Either enough stable samples OR enough quiet time justifies backing
        # off. Averaging both forces more queries after the other has settled.
        progress = max(
            min(1.0, self._stable_samples / float(self.stable_samples_to_max)),
            min(1.0, max(0.0, now - self._last_change_at) / self.quiet_seconds_to_max))
        baseline = self.min_interval + (self.max_interval - self.min_interval) * progress
        cost_delay = (self.query_seconds or 0.0) * (1.0 / self.target_duty - 1.0)
        # Negative jitter must not violate the duty budget on expensive qstat.
        cost_floor = min(self.max_interval, max(self.min_interval, cost_delay))
        self._current_interval = max(cost_floor, self._spread(max(baseline, cost_delay)))
        return self.current_interval

    def _spread(self, delay):
        delay = min(self.max_interval, max(self.min_interval, delay))
        spread = 1.0 + self.jitter * (2.0 * self._random() - 1.0)
        return min(self.max_interval, max(self.min_interval, delay * spread))

    def on_error(self):
        self._current_interval = self._spread(super().on_error())
        return self.current_interval

    def snapshot(self, now=None):
        now = self._clock() if now is None else float(now)
        data = super().snapshot(now=now)
        data.update(query_seconds=self.query_seconds, target_duty=self.target_duty,
                    fast_recovery_seconds=max(0.0, self._fast_until - now))
        return data
