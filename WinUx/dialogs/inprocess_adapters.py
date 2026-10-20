"""Compatibility/lazy facade for main-view in-process QDialogs.

Keeping this module import-light is intentional: resolving Settings must not
import every other dialog form.  Concrete implementations live in
``WinUx.dialogs.inprocess`` and are loaded on first attribute access.
"""
from __future__ import annotations

from . import inprocess as _inprocess

__all__ = list(_inprocess.__all__)


def __getattr__(name):
    if name not in __all__:
        raise AttributeError(name)
    value = getattr(_inprocess, name)
    globals()[name] = value
    return value
