"""Application services shared by WinUX controllers and views.

Keeping these operations outside the controller makes their responsibilities
explicit and lets callers reuse or test them without constructing the GUI.
"""

from .platform_integration import launch_path
from .presentation import (
    destination_display_name,
    format_conflict_message,
    remaining_time,
)

__all__ = [
    "destination_display_name",
    "format_conflict_message",
    "launch_path",
    "remaining_time",
]
