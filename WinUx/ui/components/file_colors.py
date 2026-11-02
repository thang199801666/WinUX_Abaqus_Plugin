"""WinSCP-inspired filename rules; pure metadata, no filesystem/SSH calls."""
from ...services.file_color_rules import FILE_COLORS, FileColorRules


_DEFAULT_RULES = FileColorRules()


def file_name_color(item):
    """Return a filename color, or None to retain the list's normal text."""
    return _DEFAULT_RULES(item)
