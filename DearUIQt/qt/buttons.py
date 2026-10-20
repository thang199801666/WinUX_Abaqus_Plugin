"""Legacy module alias for :mod:`DearUIQt.widgets.buttons`.

New code should import the canonical public namespace.
"""
from importlib import import_module as _import_module
import sys as _sys
_impl = _import_module('..widgets.buttons', __package__)
_sys.modules[__name__] = _impl
