"""Process construction for isolated Dear PyGui dialog hosts."""
from __future__ import annotations

import os
from pathlib import Path
import subprocess
import tempfile

from DearUIQt.core import QProcess
from ...runtime.child_processes import register_child_process


def floating_dialog_command(script):
    command = os.environ.get("WINUX_ABAQUS_COMMAND") or os.environ.get("WIXUX_ABAQUS_COMMAND") or "abaqus"
    args = [command, "python", str(script)]
    if os.name == "nt":
        return [os.environ.get("COMSPEC", "cmd.exe"), "/d", "/s", "/c", subprocess.list2cmdline(args)]
    return args


def floating_dialog_log_path(name):
    base = os.environ.get("LOCALAPPDATA")
    if base:
        log_dir = Path(base) / "WinUx" / "logs"
    else:
        log_dir = Path(tempfile.gettempdir()) / "WinUx" / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    path = log_dir / "floating_dialog_{}.log".format(name)
    path.touch(exist_ok=True)
    return str(path)


def launch_dialog_process(script, *, environment, log_path, child_label):
    Path(log_path).parent.mkdir(parents=True, exist_ok=True)
    Path(log_path).touch(exist_ok=True)
    command = floating_dialog_command(script)
    with open(log_path, "ab", buffering=0) as log:
        process = QProcess(childLabel=child_label)
        process.startCommand(
            command,
            stdin=subprocess.DEVNULL,
            stdout=log,
            stderr=log,
            cwd=str(Path(script).parent),
            env=environment,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    register_child_process(process, child_label)
    return process


__all__ = ["floating_dialog_command", "floating_dialog_log_path", "launch_dialog_process"]
