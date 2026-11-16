"""Typed, side-effect-free performance policy shared by runtime/tests/watchdogs."""
from __future__ import annotations

from dataclasses import asdict, dataclass, replace


@dataclass(frozen=True)
class QPerformancePolicy:
    """Release/runtime performance thresholds.

    The policy contains only primitive values so it is safe to serialize into
    crash reports and performance envelopes.  It owns no timers, dispatchers,
    windows or callbacks.
    """

    max_idle_render_rate_hz: float = 2.0
    min_idle_fraction: float = 0.80
    max_dispatcher_queue_wait_p95_ms: float = 50.0
    max_dispatcher_callback_p95_ms: float = 16.0
    min_dispatcher_samples: int = 5

    current_window_seconds: float = 5.0
    baseline_window_seconds: float = 30.0
    min_current_samples: int = 5
    min_baseline_samples: int = 20

    max_queue_wait_p95_ratio: float = 2.0
    max_queue_wait_p95_delta_ms: float = 20.0
    max_priority_p95_ratio: float = 2.5
    max_priority_p95_delta_ms: float = 25.0
    max_category_p95_ratio: float = 2.5
    max_category_p95_delta_ms: float = 25.0
    max_category_callback_p95_delta_ms: float = 8.0

    category_sustained_current_window_seconds: float = 15.0
    category_sustained_baseline_window_seconds: float = 60.0
    category_sustained_min_current_samples: int = 8
    category_sustained_min_baseline_samples: int = 24
    category_sustained_top_limit: int = 5
    category_watchdog_breach_checks: int = 2
    category_watchdog_recovery_checks: int = 3

    starvation_threshold_ms: float = 50.0
    min_starvation_samples: int = 5
    min_starvation_fraction: float = 0.50

    max_render_rate_ratio: float = 1.50
    max_idle_fraction_drop: float = 0.15
    max_frame_wait_p95_delta_ms: float = 8.0


    @classmethod
    def preset(cls, name="release", **overrides):
        """Return an immutable named policy without mutating process-global state.

        ``interactive`` prioritizes input responsiveness, ``idle`` is strict
        about unnecessary rendering, and ``release`` is the stable acceptance
        contract used by default.  Callers receive a new value object each time.
        """
        key = str(name or "release").strip().lower()
        presets = {
            "release": {},
            "interactive": {
                "max_idle_render_rate_hz": 3.0,
                "min_idle_fraction": 0.70,
                "max_dispatcher_queue_wait_p95_ms": 32.0,
                "max_dispatcher_callback_p95_ms": 12.0,
                "current_window_seconds": 3.0,
                "min_current_samples": 4,
                "max_queue_wait_p95_ratio": 1.75,
                "max_queue_wait_p95_delta_ms": 14.0,
            },
            "idle": {
                "max_idle_render_rate_hz": 1.0,
                "min_idle_fraction": 0.90,
                "max_dispatcher_queue_wait_p95_ms": 75.0,
                "max_dispatcher_callback_p95_ms": 20.0,
                "current_window_seconds": 10.0,
                "baseline_window_seconds": 60.0,
                "min_current_samples": 5,
                "min_baseline_samples": 20,
                "max_render_rate_ratio": 1.25,
                "max_idle_fraction_drop": 0.08,
            },
        }
        if key not in presets:
            raise ValueError("unknown performance policy preset: {}".format(name))
        policy = cls(**presets[key])
        if overrides:
            allowed = cls.__dataclass_fields__
            unknown = sorted(set(overrides) - set(allowed))
            if unknown:
                raise TypeError("unknown performance policy field(s): {}".format(', '.join(unknown)))
            policy = replace(policy, **overrides)
        return policy

    @classmethod
    def presetNames(cls):
        return ("interactive", "idle", "release")

    def toDict(self):
        return asdict(self)

    @classmethod
    def fromMapping(cls, mapping=None):
        if isinstance(mapping, cls):
            return mapping
        if isinstance(mapping, str):
            return cls.preset(mapping)
        source = dict(mapping or {})
        allowed = cls.__dataclass_fields__
        return cls(**{key: value for key, value in source.items() if key in allowed})


__all__ = ["QPerformancePolicy"]
