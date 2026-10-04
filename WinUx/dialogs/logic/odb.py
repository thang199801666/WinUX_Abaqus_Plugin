"""UI-neutral ODB display helpers shared by all dialog front ends."""
from __future__ import annotations

import math


def format_check_number(value):
    if value is None:
        return "-"
    try:
        value = float(value)
    except (TypeError, ValueError):
        return str(value)
    if not math.isfinite(value):
        return str(value)
    magnitude = abs(value)
    if magnitude and (magnitude >= 1.0e6 or magnitude < 1.0e-3):
        return "{:.6e}".format(value)
    return "{:.6g}".format(value)


def format_extract_number(value):
    try:
        value = float(value)
    except (TypeError, ValueError):
        return str(value if value is not None else "-")
    if not math.isfinite(value):
        return str(value)
    magnitude = abs(value)
    if magnitude and (magnitude >= 1.0e6 or magnitude < 1.0e-4):
        return "{:.8e}".format(value)
    return "{:.8g}".format(value)


def format_vector(value):
    if value is None:
        return "-"
    if isinstance(value, (tuple, list)):
        return "[{}]".format(", ".join(format_check_number(item) for item in value))
    return format_check_number(value)


def format_bytes(value):
    try:
        amount = float(value or 0)
    except (TypeError, ValueError):
        return "-"
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if amount < 1024.0 or unit == "TB":
            return ("{:.1f} {}".format(amount, unit)
                    if unit != "B" else "{} B".format(int(amount)))
        amount /= 1024.0
    return "-"


def history_item_label(item):
    """Return the exact Abaqus History Output variable label."""
    item = dict(item or {})
    display_name = str(item.get("displayName") or "").strip()
    if display_name:
        return display_name
    output = str(item.get("output") or "").strip()
    if output:
        return output
    return str(item.get("description") or "").strip()
