"""UI-neutral scheduling rules used by the running-job editor."""
from __future__ import annotations

from datetime import datetime, timedelta


class JobEditScheduleLogic:
    """Parsing/default rules for automatic job deletion.

    This class intentionally owns no widgets, threads or native-window state.
    Dialog front ends only depend on this stable scheduling contract.
    """

    DELETE_MODES = ("Delete After", "Delete At")
    DELETE_AT_FORMAT = "%Y-%m-%d %H:%M:%S"
    LEGACY_DELETE_AT_FORMAT = "%H:%M:%S %m-%d-%Y"
    DEFAULT_DELETE_AFTER = "00:30"
    JOB_FIELDS = (
        ("Job ID", 0),
        ("Name", 1),
        ("User", 2),
        ("Tokens", 3),
        ("Status", 4),
        ("Elapsed", 5),
    )
    ASYNC_RESULT_DELAY_MS = 20

    @classmethod
    def _parse_delete_after(cls, value):
        value = str(value or "").strip()
        parts = value.split(":")
        if len(parts) not in (2, 3) or any(not part.isdigit() for part in parts):
            raise ValueError("Delete After must use HH:MM[:SS]")
        hours = int(parts[0])
        minutes = int(parts[1])
        seconds = int(parts[2]) if len(parts) == 3 else 0
        if minutes > 59 or seconds > 59:
            raise ValueError("Delete After must use HH:MM[:SS]")
        if hours == 0 and minutes == 0 and seconds == 0:
            raise ValueError("Delete After must be greater than 00:00")
        return timedelta(hours=hours, minutes=minutes, seconds=seconds)

    @classmethod
    def _parse_delete_at(cls, value):
        text = str(value or "").strip()
        for fmt in (cls.DELETE_AT_FORMAT, cls.LEGACY_DELETE_AT_FORMAT):
            try:
                return datetime.strptime(text, fmt)
            except ValueError:
                pass
        raise ValueError("Delete At must use YYYY-MM-DD HH:MM:SS")

    @classmethod
    def _delete_at_from_duration(cls, value, now=None):
        target = (now or datetime.now()) + cls._parse_delete_after(value)
        return target.strftime(cls.DELETE_AT_FORMAT)

    @classmethod
    def _initial_delete_values(cls, settings):
        settings = dict(settings or {})
        if settings.get("delete_at_enabled"):
            mode = "Delete At"
        elif settings.get("delete_after_enabled"):
            mode = "Delete After"
        else:
            mode = str(settings.get("mode") or "Delete After")
            if mode not in cls.DELETE_MODES:
                mode = "Delete After"

        legacy_value = str(settings.get("value") or "").strip()
        delete_after = str(
            settings.get("delete_after")
            or (legacy_value if mode == "Delete After" else "")
            or cls.DEFAULT_DELETE_AFTER
        ).strip()
        delete_at = str(
            settings.get("delete_at")
            or (legacy_value if mode == "Delete At" else "")
        ).strip()

        if delete_at:
            try:
                delete_at = cls._parse_delete_at(delete_at).strftime(cls.DELETE_AT_FORMAT)
            except ValueError:
                delete_at = ""
        if not delete_at:
            try:
                delete_at = cls._delete_at_from_duration(delete_after)
            except ValueError:
                delete_at = (datetime.now() + timedelta(minutes=30)).strftime(
                    cls.DELETE_AT_FORMAT)
        return mode, delete_after, delete_at
