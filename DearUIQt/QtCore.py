"""QtCore-compatible facade over :mod:`DearUIQt.core`."""
from . import core as _core

__all__ = list(_core.__all__)

def __getattr__(name):
    if name not in __all__:
        raise AttributeError("module {!r} has no attribute {!r}".format(__name__, name))
    value = getattr(_core, name)
    globals()[name] = value
    return value

def __dir__():
    return sorted(set(globals()) | set(__all__))
