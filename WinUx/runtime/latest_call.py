"""Compatibility facade; implementation lives in :mod:`DearUIQt.dispatch`."""
import sys as _sys
from DearUIQt import dispatch as _implementation
_sys.modules[__name__] = _implementation
