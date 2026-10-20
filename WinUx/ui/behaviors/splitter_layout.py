"""WinUx host adapter for the reusable splitter-layout implementation."""
from ..components.explorer_list_view import _visible_modal_window_exists
from ...diagnostics import log_exception
from .splitter_behavior import SplitterLayoutBehaviorMixin


class SplitterLayoutMixin(SplitterLayoutBehaviorMixin):
    """Bind framework splitter behavior to WinUx modal and diagnostics services."""

    def _native_owner_accepts_input(self):
        """Honor the enabled state of the native WinUx owner window."""
        import ctypes
        import os
        from ctypes import wintypes

        if os.name != "nt":
            return True
        try:
            from ...platform.native_dialog_host import find_process_window
            hwnd = int(find_process_window("WinUX") or 0)
            if not hwnd:
                return True
            user32 = ctypes.windll.user32
            user32.IsWindowEnabled.argtypes = [wintypes.HWND]
            user32.IsWindowEnabled.restype = wintypes.BOOL
            return bool(user32.IsWindowEnabled(wintypes.HWND(hwnd)))
        except Exception:
            return True

    def _splitter_modal_window_visible(self):
        return bool(_visible_modal_window_exists())

    def _report_splitter_exception(self, message, exc_info):
        log_exception(message, exc_info, fatal=False)


__all__ = ["SplitterLayoutMixin"]
