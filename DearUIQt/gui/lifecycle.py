"""Typed, bounded lifecycle records shared by retained GUI surfaces."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class QLifecycleTransitionRecord:
    """Immutable lifecycle transition suitable for diagnostics and crash logs.

    The record deliberately contains primitive values only.  It must never own
    a QObject, HWND, viewport or renderer object, so retaining a bounded history
    cannot extend native/widget lifetime.
    """

    serial: int
    time_monotonic: float
    action: str
    state: str
    reason: Optional[str] = None
    generation: int = 0
    visual_requested: bool = False
    input_owned: bool = False
    host_correlation_id: Optional[str] = None
    teardown_correlation_id: Optional[str] = None

    def toDict(self):
        return {
            "serial": int(self.serial),
            "time_monotonic": float(self.time_monotonic),
            "action": str(self.action),
            "state": str(self.state),
            "reason": self.reason,
            "generation": int(self.generation),
            "visual_requested": bool(self.visual_requested),
            "input_owned": bool(self.input_owned),
            "host_correlation_id": self.host_correlation_id,
            "teardown_correlation_id": self.teardown_correlation_id,
        }

    def compact(self):
        return {
            "n": int(self.serial),
            "a": str(self.action),
            "s": str(self.state),
            "r": self.reason,
            "g": int(self.generation),
            "v": bool(self.visual_requested),
            "i": bool(self.input_owned),
            "hc": self.host_correlation_id,
            "tc": self.teardown_correlation_id,
        }


__all__ = ["QLifecycleTransitionRecord"]
