"""Application composition layer for WinUx.

This package owns the main controller and main-window orchestration.  Feature
controllers stay in :mod:`WinUx.controllers`; reusable UI remains in
:mod:`WinUx.ui` and :mod:`DearUIQt`.
"""

__all__ = ["WinUXController", "WinUXView"]

def __getattr__(name):
    if name == "WinUXController":
        from .controller import WinUXController
        return WinUXController
    if name == "WinUXView":
        from ..ui.main_window import WinUXView
        return WinUXView
    raise AttributeError(name)
