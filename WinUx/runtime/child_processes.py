"""Lifecycle registry for WinUx-owned helper UI processes.

The main WinUx viewport runs in a disposable standalone process, while several
UI surfaces (floating dialogs, dialog prewarm workers, Server Notepad and the
folder chooser) intentionally run in child processes.  A hard parent exit must
not leave those children alive long enough for Windows to promote an orphaned
helper HWND to an independent taskbar button.

This module has no GUI-toolkit dependency.  Callers register only processes
that are owned by WinUx and safe to terminate when the application exits.
"""
from __future__ import annotations

import ctypes
from ctypes import wintypes
import os
import subprocess
import threading
import time


_lock = threading.Lock()
_processes = {}


def register_child_process(process, label="helper"):
    """Track a WinUx-owned helper process until it exits.

    ``subprocess.Popen`` objects are kept strongly referenced on purpose: the
    process handle is useful during final shutdown even when the dialog object
    that created it has already removed itself from the visible-dialog registry.
    """
    if process is None:
        return process
    try:
        pid = int(process.pid)
    except Exception:
        return process
    if pid <= 0:
        return process
    with _lock:
        _processes[pid] = (process, str(label or "helper"))
    return process


def unregister_child_process(process_or_pid):
    """Forget a helper after its process has definitely exited."""
    try:
        pid = int(getattr(process_or_pid, "pid", process_or_pid))
    except Exception:
        return
    with _lock:
        _processes.pop(pid, None)


def _alive_snapshot():
    """Return live registered helpers and prune completed handles."""
    with _lock:
        items = list(_processes.items())
    live = []
    dead = []
    for pid, (process, label) in items:
        try:
            alive = process.poll() is None
        except Exception:
            alive = False
        if alive:
            live.append((pid, process, label))
        else:
            dead.append(pid)
    if dead:
        with _lock:
            for pid in dead:
                _processes.pop(pid, None)
    return live


def registered_child_pids():
    """Return currently live helper PIDs (primarily for diagnostics/tests)."""
    return tuple(pid for pid, _process, _label in _alive_snapshot())


def hide_registered_process_windows():
    """Synchronously hide every top-level HWND owned by a helper process.

    This is intentionally done *before* the main WinUx process hard-exits.
    Closing IPC is asynchronous; hiding the HWNDs first guarantees that Windows
    cannot display a transient generic/grey taskbar button while a child spends
    its final few milliseconds tearing down DPG/Tk.
    """
    if os.name != "nt":
        return 0
    pids = {pid for pid, _process, _label in _alive_snapshot()}
    if not pids:
        return 0
    try:
        user32 = ctypes.windll.user32
        hidden = [0]
        enum_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
        user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
        user32.GetWindowThreadProcessId.restype = wintypes.DWORD
        user32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
        user32.ShowWindow.restype = wintypes.BOOL
        user32.IsWindowVisible.argtypes = [wintypes.HWND]
        user32.IsWindowVisible.restype = wintypes.BOOL

        def visit(hwnd, _lparam):
            process_id = wintypes.DWORD()
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(process_id))
            if int(process_id.value) in pids and user32.IsWindowVisible(hwnd):
                user32.ShowWindow(hwnd, 0)  # SW_HIDE
                hidden[0] += 1
            return True

        callback = enum_type(visit)
        user32.EnumWindows.argtypes = [enum_type, wintypes.LPARAM]
        user32.EnumWindows.restype = wintypes.BOOL
        user32.EnumWindows(callback, 0)
        return hidden[0]
    except Exception:
        # Exit cleanup must remain one-way even if user32 is already partially
        # unavailable during interpreter/process teardown.
        return 0


def _wait_for_exit(entries, timeout):
    deadline = time.monotonic() + max(0.0, float(timeout))
    remaining = list(entries)
    while remaining and time.monotonic() < deadline:
        next_remaining = []
        for entry in remaining:
            _pid, process, _label = entry
            try:
                if process.poll() is None:
                    next_remaining.append(entry)
            except Exception:
                pass
        remaining = next_remaining
        if remaining:
            time.sleep(0.01)
    return remaining


def terminate_registered_children(grace_timeout=0.12, force_timeout=0.25):
    """Finish WinUx-owned helper processes without leaving orphan UI windows.

    Callers are expected to have sent their normal close/EOF signals first.
    We allow a short graceful interval (long enough for the 16-50 ms helper
    loops), then kill any remaining Windows process *trees*.  ``taskkill /T``
    matters for floating dialogs because their Popen handle may be ``cmd.exe``
    wrapping ``abaqus python``.

    The main viewport is already hidden by this point, so the bounded wait is
    invisible to the user and avoids the taskbar ghost race.
    """
    entries = _alive_snapshot()
    if not entries:
        return ()

    remaining = _wait_for_exit(entries, grace_timeout)
    if remaining:
        if os.name == "nt":
            flags = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)
            killers = []
            for pid, process, _label in remaining:
                try:
                    if process.poll() is not None:
                        continue
                    killers.append(subprocess.Popen(
                        ["taskkill", "/PID", str(int(pid)), "/T", "/F"],
                        stdin=subprocess.DEVNULL,
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                        creationflags=flags,
                    ))
                except Exception:
                    try:
                        process.kill()
                    except Exception:
                        pass
            deadline = time.monotonic() + max(0.0, float(force_timeout))
            for killer in killers:
                remaining_time = max(0.0, deadline - time.monotonic())
                if remaining_time <= 0:
                    break
                try:
                    killer.wait(timeout=remaining_time)
                except Exception:
                    pass
        else:
            for _pid, process, _label in remaining:
                try:
                    process.terminate()
                except Exception:
                    pass

        remaining = _wait_for_exit(remaining, force_timeout)

    # Remove all helpers that have now exited.  Survivors are intentionally
    # retained for diagnostics; the standalone parent exits immediately after
    # this call, so the OS/taskkill owns any final cleanup.
    _alive_snapshot()
    return tuple(pid for pid, _process, _label in remaining)


__all__ = [
    "hide_registered_process_windows",
    "register_child_process",
    "registered_child_pids",
    "terminate_registered_children",
    "unregister_child_process",
]
