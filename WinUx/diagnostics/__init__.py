"""Runtime diagnostics with an import-light public API.

Crash logging is needed before the GUI stack is imported, while full diagnostic
report collection is an on-demand support feature.  Lazy exports keep report
scanning/importlib metadata work out of the cold-start path.
"""
from __future__ import annotations

from importlib import import_module

_LAZY_DIAGNOSTICS = {
    "crash_guard": (".crash_logging", "crash_guard"),
    "get_log_paths": (".crash_logging", "get_log_paths"),
    "install_crash_logging": (".crash_logging", "install_crash_logging"),
    "log_event": (".crash_logging", "log_event"),
    "log_exception": (".crash_logging", "log_exception"),
    "log_runtime_snapshot": (".crash_logging", "log_runtime_snapshot"),
    "shutdown_crash_logging": (".crash_logging", "shutdown_crash_logging"),
    "build_diagnostics_report": (".report", "build_diagnostics_report"),
    "collect_diagnostics": (".report", "collect_diagnostics"),
    "find_winux_plugins": (".report", "find_winux_plugins"),
    "format_diagnostics": (".report", "format_diagnostics"),
}

__all__ = list(_LAZY_DIAGNOSTICS)


def __getattr__(name):
    target = _LAZY_DIAGNOSTICS.get(name)
    if target is None:
        raise AttributeError("module {!r} has no attribute {!r}".format(__name__, name))
    module_name, attribute_name = target
    value = getattr(import_module(module_name, __name__), attribute_name)
    globals()[name] = value
    return value


def __dir__():
    return sorted(set(globals()) | set(__all__))
