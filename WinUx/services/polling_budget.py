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

    def record_cost(self, seconds):
        seconds = max(0.0, float(seconds))
        if self.query_seconds is None:
            self.query_seconds = seconds
        else:
            self.query_seconds += self.alpha * (seconds - self.query_seconds)

    def force_fast(self, now=None):
        self._interactive = True
        return super().force_fast(now=now)

    def observe(self, signature, now=None):
        changed = not self._has_signature or signature != self._signature
        baseline = super().observe(signature, now=now)
        interactive, self._interactive = self._interactive, False
        if changed or interactive:
            self._current_interval = self.min_interval
            return self.current_interval
        cost_delay = (self.query_seconds or 0.0) * (1.0 / self.target_duty - 1.0)
        self._current_interval = self._spread(max(baseline, cost_delay))
        return self.current_interval

    def _spread(self, delay):
        delay = min(self.max_interval, max(self.min_interval, delay))
        spread = 1.0 + self.jitter * (2.0 * self._random() - 1.0)
        return min(self.max_interval, max(self.min_interval, delay * spread))

    def on_error(self):
        self._current_interval = self._spread(super().on_error())
        return self.current_interval

    def snapshot(self, now=None):
        data = super().snapshot(now=now)
        data.update(query_seconds=self.query_seconds, target_duty=self.target_duty)
        return data
