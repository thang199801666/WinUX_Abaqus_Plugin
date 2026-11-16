"""Shared, side-effect-free lifecycle diagnostics formatting helpers."""
from __future__ import annotations


def filter_transition_records(records, *, action=None, state=None, reason=None,
                              limit=None, transform=None):
    """Return a filtered tuple without mutating or retaining native objects."""
    rows = []
    for record in tuple(records):
        item = record.toDict()
        if transform is not None:
            item = transform(record, item)
        if action is not None and item.get("action") != str(action):
            continue
        if state is not None and item.get("state") != str(state):
            continue
        if reason is not None and item.get("reason") != str(reason):
            continue
        rows.append(item)
    if limit is not None:
        rows = rows[-max(0, int(limit)):]
    return tuple(rows)


def compact_transition_records(records, *, kind="generic"):
    """Serialize lifecycle records with stable compact keys."""
    if kind == "host":
        return tuple({
            "n": int(r.serial), "s": r.state, "r": r.reason,
            "c": r.teardown_correlation_id,
        } for r in tuple(records))
    if kind == "popup":
        return tuple({
            "n": int(r.serial), "a": r.action, "r": r.reason,
            "s": int(r.state), "g": int(r.generation),
            "v": bool(r.visual_requested), "i": bool(r.input_owned),
            "hc": r.host_correlation_id, "tc": r.teardown_correlation_id,
        } for r in tuple(records))
    return tuple(r.compact() for r in tuple(records))


__all__ = ["filter_transition_records", "compact_transition_records"]
