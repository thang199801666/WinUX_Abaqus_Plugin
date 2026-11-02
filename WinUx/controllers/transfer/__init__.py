"""Transfer orchestration controllers.

Canonical implementations live in this package.  ``TransferController`` is
re-exported here so the historical ``WinUx.controllers.transfer`` import keeps
working after ``transfer.py`` became a feature package.
"""
from .controller import TransferController

__all__ = ["TransferController"]
