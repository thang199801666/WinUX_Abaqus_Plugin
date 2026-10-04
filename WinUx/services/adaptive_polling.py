"""Adaptive interval control for low-overhead remote polling.

The basic policy reacts immediately to state changes and backs off while a
remote source is quiet.  ``EventIntervalLearner`` adds a small session-local
predictor for events that have a natural cadence (for example, ODB creation or
ODB file writes).  It deliberately needs several observations before it fully
trusts the learned cadence so a single slow event cannot make the UI sluggish.
"""

from __future__ import annotations

import time


class AdaptivePollingPolicy:
    """Compute a bounded polling interval from change history.

    ``stable_samples_to_max`` controls the sample-count contribution while
    ``quiet_seconds_to_max`` controls the elapsed-time contribution.  Both are
    blended equally, so neither a burst of very fast samples nor a long sleep
    alone can immediately jump to the maximum interval.
    """

    def __init__(
        self,
        min_interval,
        max_interval,
        stable_samples_to_max=8,
        quiet_seconds_to_max=90.0,
        clock=None,
    ):
        self._clock = clock or time.monotonic
        self._signature = None
        self._has_signature = False
        self._stable_samples = 0
        self._poll_count = 0
        self._change_count = 0
        self._last_change_at = self._clock()
        self._current_interval = 0.0
        self.configure(
            min_interval=min_interval,
            max_interval=max_interval,
            stable_samples_to_max=stable_samples_to_max,
            quiet_seconds_to_max=quiet_seconds_to_max,
        )
        self._current_interval = self.min_interval

    def configure(
        self,
        *,
        min_interval=None,
        max_interval=None,
        stable_samples_to_max=None,
        quiet_seconds_to_max=None,
    ):
        minimum = float(
            getattr(self, "min_interval", 1.0)
            if min_interval is None else min_interval
        )
        maximum = float(
            getattr(self, "max_interval", minimum)
            if max_interval is None else max_interval
        )
        minimum = max(0.05, minimum)
        maximum = max(minimum, maximum)
        stable = int(
            getattr(self, "stable_samples_to_max", 8)
            if stable_samples_to_max is None else stable_samples_to_max
        )
        quiet = float(
            getattr(self, "quiet_seconds_to_max", 90.0)
            if quiet_seconds_to_max is None else quiet_seconds_to_max
        )
        self.min_interval = minimum
        self.max_interval = maximum
        self.stable_samples_to_max = max(1, stable)
        self.quiet_seconds_to_max = max(0.1, quiet)
        if getattr(self, "_current_interval", 0.0):
            self._current_interval = min(
                self.max_interval,
                max(self.min_interval, self._current_interval),
            )
        return self.current_interval

    @property
    def current_interval(self):
        return float(self._current_interval or self.min_interval)

    @property
    def poll_count(self):
        return self._poll_count

    @property
    def change_count(self):
        return self._change_count

    @property
    def stable_samples(self):
        return self._stable_samples

    def force_fast(self, now=None):
        """Reset backoff after a user action or known external change."""
        now = self._clock() if now is None else float(now)
        self._stable_samples = 0
        self._last_change_at = now
        self._current_interval = self.min_interval
        return self.current_interval

    def observe(self, signature, now=None):
        """Record a successful sample and return the next interval."""
        now = self._clock() if now is None else float(now)
        self._poll_count += 1

        if not self._has_signature:
            self._signature = signature
            self._has_signature = True
            self._stable_samples = 0
            self._last_change_at = now
            self._current_interval = self.min_interval
            return self.current_interval

        if signature != self._signature:
            self._signature = signature
            self._stable_samples = 0
            self._change_count += 1
            self._last_change_at = now
            self._current_interval = self.min_interval
            return self.current_interval

        self._stable_samples += 1
        sample_progress = min(
            1.0,
            float(self._stable_samples) / float(self.stable_samples_to_max),
        )
        quiet_age = max(0.0, now - self._last_change_at)
        time_progress = min(1.0, quiet_age / self.quiet_seconds_to_max)
        progress = 0.5 * sample_progress + 0.5 * time_progress
        self._current_interval = self.min_interval + (
            self.max_interval - self.min_interval
        ) * progress
        return self.current_interval

    def on_error(self):
        """Back off after a failed remote query without exceeding max."""
        self._current_interval = min(
            self.max_interval,
            max(self.min_interval, self.current_interval * 1.5),
        )
        return self.current_interval

    def snapshot(self, now=None):
        now = self._clock() if now is None else float(now)
        return {
            "interval": self.current_interval,
            "poll_count": self._poll_count,
            "change_count": self._change_count,
            "stable_samples": self._stable_samples,
            "quiet_seconds": max(0.0, now - self._last_change_at),
        }


class EventIntervalLearner:
    """Learn recurring event intervals and turn them into safe poll delays.

    The learner keeps an EWMA of observed event spacing plus an EWMA absolute
    deviation.  ``recommend`` blends the normal adaptive delay with a
    prediction of the next event.  Confidence ramps up over several samples,
    so early/atypical observations cannot immediately stretch polling to the
    maximum.
    """

    def __init__(
        self,
        alpha=0.35,
        prediction_fraction=0.25,
        confidence_samples=3,
    ):
        self.mean_interval = None
        self.deviation = 0.0
        self.samples = 0
        self.configure(
            alpha=alpha,
            prediction_fraction=prediction_fraction,
            confidence_samples=confidence_samples,
        )

    def configure(
        self,
        *,
        alpha=None,
        prediction_fraction=None,
        confidence_samples=None,
    ):
        if alpha is not None:
            self.alpha = min(1.0, max(0.01, float(alpha)))
        elif not hasattr(self, "alpha"):
            self.alpha = 0.35
        if prediction_fraction is not None:
            self.prediction_fraction = min(
                1.0, max(0.05, float(prediction_fraction)))
        elif not hasattr(self, "prediction_fraction"):
            self.prediction_fraction = 0.25
        if confidence_samples is not None:
            self.confidence_samples = max(1, int(confidence_samples))
        elif not hasattr(self, "confidence_samples"):
            self.confidence_samples = 3

    @property
    def confidence(self):
        return min(1.0, float(self.samples) / float(self.confidence_samples))

    def observe_interval(self, seconds):
        value = float(seconds)
        if value <= 0.0:
            return self.mean_interval
        if self.mean_interval is None:
            self.mean_interval = value
            self.deviation = 0.0
        else:
            previous = self.mean_interval
            error = abs(value - previous)
            self.mean_interval = previous + self.alpha * (value - previous)
            self.deviation = self.deviation + self.alpha * (
                error - self.deviation)
        self.samples += 1
        return self.mean_interval

    def recommend(self, age, baseline, minimum, maximum):
        """Return a bounded delay that anticipates the next learned event."""
        minimum = max(0.05, float(minimum))
        maximum = max(minimum, float(maximum))
        baseline = min(maximum, max(minimum, float(baseline)))
        if self.mean_interval is None or self.samples <= 0:
            return baseline

        age = max(0.0, float(age))
        mean = max(minimum, float(self.mean_interval))
        # Start probing before the mean by roughly one learned deviation. This
        # is intentionally conservative when cadence is noisy.
        expected_age = max(minimum, mean - max(0.0, self.deviation))
        remaining = expected_age - age
        probe = min(
            maximum,
            max(minimum, mean * self.prediction_fraction),
        )
        if remaining > minimum:
            predicted = min(max(probe, remaining * 0.5), remaining)
        else:
            # Once the predicted time is reached, keep checking at the learned
            # probe cadence instead of falling all the way back to a 1 Hz loop.
            predicted = probe
        predicted = min(maximum, max(minimum, predicted))
        confidence = self.confidence
        return min(
            maximum,
            max(
                minimum,
                baseline + (predicted - baseline) * confidence,
            ),
        )

    def snapshot(self):
        return {
            "mean_interval": self.mean_interval,
            "deviation": self.deviation,
            "samples": self.samples,
            "confidence": self.confidence,
        }
