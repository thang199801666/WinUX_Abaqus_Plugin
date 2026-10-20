from __future__ import annotations

from ..sync_preview_form import SyncPreviewDialog as SyncPreviewForm
from .common import RetainedTool


class SyncPreviewDialog(RetainedTool, SyncPreviewForm):
    def __init__(self, view, rows, local_path, server_path, on_refresh, on_transfer):
        SyncPreviewForm.__init__(
            self, view, rows, local_path, server_path, on_refresh, on_transfer)
        self._init_inprocess_lifetime(view)

    def refresh(self, rows, local_path, server_path, on_refresh=None, on_transfer=None):
        if on_refresh is not None:
            self._on_refresh = on_refresh
        if on_transfer is not None:
            self._on_transfer = on_transfer
        return SyncPreviewForm.refresh(self, rows, local_path, server_path)
