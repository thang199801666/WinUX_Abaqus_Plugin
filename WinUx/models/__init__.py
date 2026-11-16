"""Domain objects and local filesystem access with lazy exports."""
from __future__ import annotations

from importlib import import_module

_LAZY_MODELS = {
    "FileSystemModel": (".filesystem", "FileSystemModel"),
    "FileItem": (".items", "FileItem"),
    "JobItem": (".items", "JobItem"),
}

__all__ = list(_LAZY_MODELS)


def __getattr__(name):
    target = _LAZY_MODELS.get(name)
    if target is None:
        raise AttributeError("module {!r} has no attribute {!r}".format(__name__, name))
    module_name, attribute_name = target
    value = getattr(import_module(module_name, __name__), attribute_name)
    globals()[name] = value
    return value


def __dir__():
    return sorted(set(globals()) | set(__all__))
