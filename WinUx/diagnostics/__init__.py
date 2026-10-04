"""Runtime diagnostics for WinUX.

The public functions in this package are intentionally dependency-free.  They
can be installed before Dear PyGui or the controller is imported, which makes
startup/import failures observable as well as failures from the render loop.
"""

from .crash_logging import (
    crash_guard,
    get_log_paths,
    install_crash_logging,
    log_event,
    log_exception,
    log_runtime_snapshot,
    shutdown_crash_logging,
)
from .report import (
    build_diagnostics_report,
    collect_diagnostics,
    find_winux_plugins,
    format_diagnostics,
)

__all__ = [
    "crash_guard",
    "get_log_paths",
    "install_crash_logging",
    "log_event",
    "log_exception",
    "log_runtime_snapshot",
    "shutdown_crash_logging",
    "build_diagnostics_report",
    "collect_diagnostics",
    "find_winux_plugins",
    "format_diagnostics",
]
