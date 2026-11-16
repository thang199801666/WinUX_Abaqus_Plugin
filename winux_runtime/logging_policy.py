"""Small shared policy for bounded WinUx text logs.

The helpers are intentionally import-light because they are also used by the
Abaqus launcher before the WinUx application package is imported.
"""
from __future__ import print_function

import os
import time


def _env_int(name, default, minimum=0):
    try:
        value = int(str(os.environ.get(name, default)).strip())
    except Exception:
        value = int(default)
    return max(int(minimum), value)


def log_max_bytes(default_kb=512):
    return _env_int("WINUX_LOG_MAX_KB", default_kb, 64) * 1024


def log_backup_count(default=2):
    return _env_int("WINUX_LOG_BACKUPS", default, 0)


def log_retention_days(default=7):
    return _env_int("WINUX_LOG_RETENTION_DAYS", default, 1)


def verbose_startup_logging(environ=None):
    environ = os.environ if environ is None else environ
    value = str(environ.get("WINUX_VERBOSE_STARTUP_LOG", "")).strip().lower()
    return value in ("1", "true", "yes", "on", "debug", "verbose")


def normal_log_level_name(environ=None):
    environ = os.environ if environ is None else environ
    value = str(environ.get("WINUX_LOG_LEVEL", "WARNING")).strip().upper()
    if value not in ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"):
        value = "WARNING"
    return value


def trim_log_tail(path, max_bytes=None, keep_bytes=None, marker=None):
    """Bound an append-only log by retaining only its most recent tail."""
    max_bytes = int(max_bytes or log_max_bytes())
    keep_bytes = int(keep_bytes or max(16 * 1024, max_bytes // 4))
    keep_bytes = min(keep_bytes, max_bytes)
    try:
        size = os.path.getsize(path)
    except OSError:
        return False
    if size <= max_bytes:
        return False
    try:
        with open(path, "rb") as handle:
            handle.seek(max(0, size - keep_bytes))
            tail = handle.read()
        newline = tail.find(b"\n")
        if newline != -1:
            tail = tail[newline + 1:]
        message = marker or b"[WinUx log truncated; keeping recent entries]\n"
        if not isinstance(message, bytes):
            message = (str(message).rstrip() + "\n").encode("utf-8", "replace")
        with open(path, "wb") as handle:
            handle.write(message)
            handle.write(tail)
        return True
    except (OSError, IOError):
        return False


def prune_old_logs(directory, *, max_age_days=None, exclude=()):
    """Delete old closed log files; never required for correctness."""
    max_age_days = int(max_age_days or log_retention_days())
    cutoff = time.time() - max_age_days * 24 * 60 * 60
    excluded = {str(name).casefold() for name in exclude}
    try:
        entries = list(os.scandir(str(directory)))
    except Exception:
        return 0
    removed = 0
    for entry in entries:
        name = entry.name
        low = name.casefold()
        if low in excluded:
            continue
        if not (low.endswith(".log") or ".log." in low):
            continue
        try:
            if not entry.is_file() or entry.stat().st_mtime >= cutoff:
                continue
            os.remove(entry.path)
            removed += 1
        except Exception:
            pass
    return removed


__all__ = [
    "log_backup_count",
    "log_max_bytes",
    "log_retention_days",
    "normal_log_level_name",
    "prune_old_logs",
    "trim_log_tail",
    "verbose_startup_logging",
]
