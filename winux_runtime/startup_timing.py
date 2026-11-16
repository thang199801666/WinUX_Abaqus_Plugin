"""Import-light end-to-end startup timing helpers."""
from __future__ import print_function

import os
import time

from winux_runtime.logging_policy import verbose_startup_logging


def note_startup_milestone(label, environ=None, now=None):
    """Append one Plug-ins->WinUx timing milestone to the launcher log."""
    environ = os.environ if environ is None else environ
    path = environ.get("WINUX_LAUNCH_LOG") or environ.get("WIXUX_LAUNCH_LOG")
    started = environ.get("WINUX_LAUNCH_STARTED_AT")
    if not path or not started:
        return False
    # Normal runs keep one useful end-to-end line only. Detailed phase
    # milestones remain opt-in for startup profiling.
    if not verbose_startup_logging(environ) and str(label) != "first visible frame rendered":
        return False
    try:
        started = float(started)
        stamp = time.time() if now is None else float(now)
        elapsed = max(0.0, stamp - started)
        with open(path, "ab") as handle:
            handle.write(("[startup] {} total={:.3f}s\n".format(
                str(label), elapsed)).encode("utf-8"))
        return True
    except Exception:
        return False


__all__ = ["note_startup_milestone"]
