"""Legacy module alias for :mod:`DearUIQt.gui.shortcut`."""
from importlib import import_module as _import_module
import sys as _sys
_impl = _import_module('..gui.shortcut', __package__)
_sys.modules[__name__] = _impl
