"""Legacy module alias for :mod:`DearUIQt.core.application`.

New code should import the canonical public namespace.
"""
from importlib import import_module as _import_module
import sys as _sys
_impl = _import_module('..core.application', __package__)
_sys.modules[__name__] = _impl
