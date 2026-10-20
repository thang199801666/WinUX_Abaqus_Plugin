"""Public SSH Login API on the shared DearUIQt application event loop.

Process-isolated compatibility hosting remains available explicitly from
``WinUx.dialogs.floating_adapters``.
"""
from .inprocess_adapters import LoginDialog

__all__ = ["LoginDialog"]
