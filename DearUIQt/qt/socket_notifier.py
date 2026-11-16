"""Legacy alias for :mod:`DearUIQt.core.socket_notifier`."""
from importlib import import_module as _import_module
_impl = _import_module("..core.socket_notifier", __package__)
QSocketNotifier = _impl.QSocketNotifier
__all__ = ["QSocketNotifier"]
