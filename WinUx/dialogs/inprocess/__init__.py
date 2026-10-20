"""Lazy in-process dialog implementations used by the main WinUX viewport."""
from __future__ import annotations

from importlib import import_module

_LAZY = {
    "BlockingDialog": (".transient", "BlockingDialog"),
    "LoginDialog": (".transient", "LoginDialog"),
    "JobEditDialog": (".transient", "JobEditDialog"),
    "JobManagerDialog": (".transient", "JobManagerDialog"),
    "LocalFolderDialog": (".transient", "LocalFolderDialog"),
    "LocalFileDialog": (".transient", "LocalFileDialog"),
    "ServerPathDialog": (".transient", "ServerPathDialog"),
    "ProgressDialog": (".transient", "ProgressDialog"),
    "ODBCheckDialog": (".transient", "ODBCheckDialog"),
    "ODBExtractDialog": (".transient", "ODBExtractDialog"),
    "ODBXYResultDialog": (".transient", "ODBXYResultDialog"),
    "SettingsDialog": (".settings", "SettingsDialog"),
    "DiagnosticsDialog": (".diagnostics", "DiagnosticsDialog"),
    "BookmarksDialog": (".bookmarks", "BookmarksDialog"),
    "SiteManagerDialog": (".site_manager", "SiteManagerDialog"),
    "SyncPreviewDialog": (".sync_preview", "SyncPreviewDialog"),
    "JobScheduleDialog": (".job_schedule", "JobScheduleDialog"),
    "TransferCenterDialog": (".transfer_center", "TransferCenterDialog"),
    "TransferTaskHandle": (".transfer_center", "TransferTaskHandle"),
    "_TransferItemRow": (".transfer_center", "_TransferItemRow"),
}

__all__ = list(_LAZY)


def __getattr__(name):
    target = _LAZY.get(name)
    if target is None:
        raise AttributeError(name)
    module_name, attribute = target
    value = getattr(import_module(module_name, __name__), attribute)
    globals()[name] = value
    return value
