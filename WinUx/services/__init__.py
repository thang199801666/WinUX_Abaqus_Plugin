"""Application services with dependency-safe lazy public helpers.

Feature implementations are grouped into dependency-safe subpackages such as
``transfer``, ``odb`` and ``server_notepad``. Historical flat modules remain
compatibility aliases only. The package initializer does not eagerly import
presentation/platform helpers merely because a controller imports this namespace.
"""
from __future__ import annotations

from importlib import import_module

_LAZY_SERVICES = {
    "launch_path": (".platform_integration", "launch_path"),
    "destination_display_name": (".presentation", "destination_display_name"),
    "format_conflict_message": (".presentation", "format_conflict_message"),
    "remaining_time": (".presentation", "remaining_time"),
}

__all__ = list(_LAZY_SERVICES)


def __getattr__(name):
    target = _LAZY_SERVICES.get(name)
    if target is None:
        raise AttributeError("module {!r} has no attribute {!r}".format(__name__, name))
    module_name, attribute_name = target
    value = getattr(import_module(module_name, __name__), attribute_name)
    globals()[name] = value
    return value


def __dir__():
    return sorted(set(globals()) | set(__all__))
