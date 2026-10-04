"""Small UI-neutral formatting helpers used by transfer/progress dialogs."""
from __future__ import annotations


def format_size(value):
    value = float(value or 0)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if value < 1024 or unit == "TB":
            return "{:.1f} {}".format(value, unit)
        value /= 1024


def format_time(seconds):
    if seconds is None:
        return "--"
    hours, remainder = divmod(int(max(0, seconds)), 3600)
    minutes, seconds = divmod(remainder, 60)
    if hours:
        return "{}h {:02d}m".format(hours, minutes)
    return "{}m {:02d}s".format(minutes, seconds) if minutes else "{}s".format(seconds)
