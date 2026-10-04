"""Pure presentation helpers for controller-facing data."""

import math


def remaining_time(target, now):
    """Format the non-negative time from ``now`` to ``target`` as HH:MM:SS."""
    seconds = max(0, int(math.ceil((target - now).total_seconds())))
    hours, remainder = divmod(seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    return "{:02d}:{:02d}:{:02d}".format(hours, minutes, seconds)


def destination_display_name(destination):
    """Return the exact folder label used by a drag preview."""
    if destination is None:
        return ""
    name = str(getattr(destination, "name", "") or "").strip()
    return name or str(destination)


def format_conflict_message(conflicts):
    """Build the overwrite confirmation text for destination conflicts."""
    preview = "\n".join(conflicts[:8])
    if len(conflicts) > 8:
        preview += "\n... and {} more".format(len(conflicts) - 8)
    return (
        "The following item(s) already exist in the destination:"
        "\n\n{}\n\nClick OK to overwrite them, or Cancel "
        "to stop.".format(preview)
    )
