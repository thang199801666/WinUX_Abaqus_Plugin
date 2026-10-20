from __future__ import annotations

from ..site_manager_form import SiteManagerDialog as SiteManagerForm
from .common import RetainedTool


class SiteManagerDialog(RetainedTool, SiteManagerForm):
    def __init__(self, view, sites, on_save, on_delete, on_connect):
        SiteManagerForm.__init__(self, view, sites, on_save, on_delete, on_connect)
        self._init_inprocess_lifetime(view)

    def refresh(self, sites, selected_id=None, on_save=None, on_delete=None, on_connect=None):
        if on_save is not None:
            self._on_save = on_save
        if on_delete is not None:
            self._on_delete = on_delete
        if on_connect is not None:
            self._on_connect = on_connect
        return SiteManagerForm.refresh(self, sites, selected_id)
