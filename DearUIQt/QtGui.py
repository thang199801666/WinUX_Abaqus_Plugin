"""QtGui-compatible facade over :mod:`DearUIQt.gui`."""
from . import gui as _gui

__all__ = list(_gui.__all__)

def __getattr__(name):
    if name not in __all__:
        raise AttributeError("module {!r} has no attribute {!r}".format(__name__, name))
    value = getattr(_gui, name)
    globals()[name] = value
    return value

def __dir__():
    return sorted(set(globals()) | set(__all__))
