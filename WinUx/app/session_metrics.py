"""Lightweight session/process memory metrics for Session Manager.

All WinUx login sessions share one OS process, so Windows cannot report a true
working-set value per logical session.  ``estimate_session_bytes`` therefore
measures only Python/cache objects owned by a session workspace.  The dialog
labels this value as estimated and also shows the process working set separately.
"""
from __future__ import annotations

import os
import sys
from collections import deque
from dataclasses import fields, is_dataclass


def _children(value):
    if isinstance(value, dict):
        for key, item in value.items():
            yield key
            yield item
        return
    if isinstance(value, (tuple, list, set, frozenset, deque)):
        yield from value
        return
    if is_dataclass(value) and not isinstance(value, type):
        for field in fields(value):
            try:
                yield getattr(value, field.name)
            except Exception:
                pass


def deep_size(value, *, max_nodes=50000):
    """Bounded recursive size for plain session-owned cache containers."""
    seen = set()
    stack = [value]
    total = 0
    nodes = 0
    while stack and nodes < max_nodes:
        current = stack.pop()
        ident = id(current)
        if ident in seen:
            continue
        seen.add(ident)
        nodes += 1
        try:
            total += int(sys.getsizeof(current))
        except Exception:
            pass
        stack.extend(_children(current))
    return max(0, total)


def estimate_session_bytes(workspace, snapshot=None):
    """Estimate bytes retained by one logical session's owned caches.

    The SSH transport itself contains shared/native resources that cannot be
    attributed accurately inside one process, so only bounded Python-owned
    metadata/cache collections are counted here.
    """
    if workspace is None:
        return deep_size(snapshot or {})
    payload = (
        getattr(workspace, "session_id", ""),
        getattr(workspace, "remote_path", None),
        getattr(workspace, "directory_items", ()),
        getattr(workspace, "history", ()),
        getattr(workspace, "jobs", ()),
        snapshot or {},
    )
    return deep_size(payload)


def process_working_set_bytes():
    """Return current process working set, or 0 when unavailable."""
    if os.name == "nt":
        try:
            import ctypes
            from ctypes import wintypes

            class PROCESS_MEMORY_COUNTERS_EX(ctypes.Structure):
                _fields_ = [
                    ("cb", wintypes.DWORD),
                    ("PageFaultCount", wintypes.DWORD),
                    ("PeakWorkingSetSize", ctypes.c_size_t),
                    ("WorkingSetSize", ctypes.c_size_t),
                    ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
                    ("QuotaPagedPoolUsage", ctypes.c_size_t),
                    ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                    ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                    ("PagefileUsage", ctypes.c_size_t),
                    ("PeakPagefileUsage", ctypes.c_size_t),
                    ("PrivateUsage", ctypes.c_size_t),
                ]

            counters = PROCESS_MEMORY_COUNTERS_EX()
            counters.cb = ctypes.sizeof(counters)
            handle = ctypes.windll.kernel32.GetCurrentProcess()
            ok = ctypes.windll.psapi.GetProcessMemoryInfo(
                handle, ctypes.byref(counters), counters.cb)
            if ok:
                return int(counters.WorkingSetSize)
        except Exception:
            pass
    try:
        import resource
        value = int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
        # Linux reports KiB; macOS reports bytes.
        return value * 1024 if sys.platform.startswith("linux") else value
    except Exception:
        return 0


def format_bytes(value):
    value = max(0, int(value or 0))
    units = ("B", "KB", "MB", "GB")
    amount = float(value)
    for unit in units:
        if amount < 1024.0 or unit == units[-1]:
            if unit == "B":
                return "{} {}".format(int(amount), unit)
            return "{:.1f} {}".format(amount, unit)
        amount /= 1024.0
    return "{} B".format(value)


__all__ = [
    "deep_size", "estimate_session_bytes", "process_working_set_bytes", "format_bytes",
]
