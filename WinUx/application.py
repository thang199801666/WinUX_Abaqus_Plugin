"""Stable application entry point for launchers and Abaqus plug-ins."""

from __future__ import annotations

import sys
import time

from .diagnostics import (
    install_crash_logging,
    log_event,
    log_exception,
    shutdown_crash_logging,
)


def run(controller_factory=None):
    """Create and run WinUX with crash diagnostics active.

    ``controller_factory`` is injectable to keep the lifecycle independently
    testable. Production callers normally use ``WinUx.run()`` with no argument.
    """
    install_crash_logging()
    log_event("Application entry point started")
    started = time.perf_counter()
    try:
        if controller_factory is None:
            # Import only after crash hooks are active so import/ABI failures
            # from Dear PyGui are written to the diagnostic logs.
            from .controller import WinUXController
            controller_factory = WinUXController
        log_event("Startup controller import elapsed={:.3f}s".format(time.perf_counter()-started))
        controller = controller_factory()
        log_event("Startup controller/view ready elapsed={:.3f}s".format(time.perf_counter()-started))
        controller.run()
    except Exception:
        log_exception(
            "Application entry point failed",
            sys.exc_info(),
            fatal=True,
        )
        raise
    finally:
        shutdown_crash_logging("Application entry point finished")
