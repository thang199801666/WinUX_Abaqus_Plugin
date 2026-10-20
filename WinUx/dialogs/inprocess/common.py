from __future__ import annotations

from ...ui.hosting.inprocess_dialog import RetainedInProcessDialogMixin


class RetainedTool(RetainedInProcessDialogMixin):
    """MRO anchor for QWidget-style retained application tools."""

    def show(self):
        return super().show()


__all__ = ["RetainedTool"]
