"""Backward-compatible application entry point.

New internal code should use :mod:`WinUx.bootstrap.application`.  This module is
kept so launchers and integrations importing ``WinUx.application.run`` continue
to work unchanged.
"""

from .bootstrap.application import run

__all__ = ["run"]
