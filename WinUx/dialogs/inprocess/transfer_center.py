from __future__ import annotations

from ..transfer_center_form import (
    TransferCenterDialog as TransferCenterForm,
    TransferTaskHandle,
    _TransferItemRow,
)
from .common import RetainedTool


class TransferCenterDialog(RetainedTool, TransferCenterForm):
    def __init__(self, view):
        TransferCenterForm.__init__(self, view)
        self._init_inprocess_lifetime(view)


__all__ = ["TransferCenterDialog", "TransferTaskHandle", "_TransferItemRow"]
