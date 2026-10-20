"""Rendering backend boundary for DearUIQt.

DearUIQt's public API is backend-neutral.  The current production renderer is
Dear PyGui, loaded lazily on first native access.  Tests and future renderers
can inject a compatible backend without monkey-patching every widget module.
"""
from __future__ import annotations

from contextlib import contextmanager
import threading

_lock = threading.RLock()
_default_backend = None


def _load_dearpygui():
    import dearpygui.dearpygui as backend
    return backend


def get_backend():
    global _default_backend
    with _lock:
        if _default_backend is None:
            _default_backend = _load_dearpygui()
        return _default_backend


def set_backend(backend):
    """Set the process-wide default renderer and return the previous backend."""
    if backend is None:
        raise ValueError("backend cannot be None; use reset_backend()")
    global _default_backend
    with _lock:
        previous = _default_backend
        _default_backend = backend
    return previous


def reset_backend():
    """Forget an injected backend; Dear PyGui will be reloaded lazily."""
    global _default_backend
    with _lock:
        previous = _default_backend
        _default_backend = None
    return previous


@contextmanager
def use_backend(backend):
    previous = set_backend(backend)
    try:
        yield backend
    finally:
        global _default_backend
        with _lock:
            _default_backend = previous


from .api import (
    RendererBackend, BackendCapabilities, BackendCapabilityError,
    backend_capabilities, require_backend_capability,
)

class _BackendProxy:
    """Attribute proxy preserving the familiar ``dpg`` module-shaped API."""
    __slots__ = ()

    def __getattr__(self, name):
        return getattr(get_backend(), name)

    def __dir__(self):
        try:
            return dir(get_backend())
        except Exception:
            return []


dpg = _BackendProxy()

__all__ = [
    "dpg", "get_backend", "set_backend", "reset_backend", "use_backend",
    "RendererBackend", "BackendCapabilities", "BackendCapabilityError",
    "backend_capabilities", "require_backend_capability",
]
