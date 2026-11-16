"""Legacy module alias for :mod:`DearUIQt.core.event_loop`."""
from importlib import import_module as _import_module
import sys as _sys
_impl = _import_module('..core.event_loop', __package__)
_sys.modules[__name__] = _impl
