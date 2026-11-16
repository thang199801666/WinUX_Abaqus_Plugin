"""Controller composition helpers with dependency-safe lazy imports.

The main application only needs a subset of controllers to paint its first
frame.  Keeping this package lazy preserves the historical public imports while
preventing optional feature controllers from extending cold-start time.
"""
from __future__ import annotations

from importlib import import_module

_LAZY_CONTROLLERS = {
    "ConnectionController": (".connection", "ConnectionController"),
    "JobPollingController": (".jobs.polling", "JobPollingController"),
    "JobPlotController": (".jobs.plot", "JobPlotController"),
    "JobScheduleController": (".jobs.schedule", "JobScheduleController"),
    "ScheduleManifestController": (".jobs.manifest", "ScheduleManifestController"),
    "TransferController": (".transfer.controller", "TransferController"),
    "SyncPreviewController": (".transfer.sync_preview", "SyncPreviewController"),
    "LocalWatchController": (".explorer.local_watch", "LocalWatchController"),
    "NavigationController": (".explorer.navigation", "NavigationController"),
    "ServerNotepadController": (".server_notepad", "ServerNotepadController"),
    "FileClipboardController": (".explorer.clipboard", "FileClipboardController"),
    "ClipboardTransferController": (".transfer.clipboard", "ClipboardTransferController"),
    "FileCommandController": (".explorer.commands", "FileCommandController"),
    "JobActionsController": (".jobs.actions", "JobActionsController"),
    "JobSubmissionController": (".jobs.submission", "JobSubmissionController"),
    "InpAnalysisController": (".inp.analysis", "InpAnalysisController"),
    "OdbAnalysisController": (".odb.analysis", "OdbAnalysisController"),
    "ExplorerTransferInteractionMixin": (".explorer.transfer_interaction", "ExplorerTransferInteractionMixin"),
    "SavedNavigationMixin": (".explorer.saved_navigation", "SavedNavigationMixin"),
    "ConsoleFacadeMixin": (".console", "ConsoleFacadeMixin"),
    "REQUIRED_CALLBACK_KEYS": (".callbacks", "REQUIRED_CALLBACK_KEYS"),
    "build_controller_callbacks": (".callbacks", "build_controller_callbacks"),
    "validate_callbacks": (".callbacks", "validate_callbacks"),
}

__all__ = list(_LAZY_CONTROLLERS)

def __getattr__(name):
    target = _LAZY_CONTROLLERS.get(name)
    if target is None:
        raise AttributeError(
            "module {!r} has no attribute {!r}".format(__name__, name))
    module_name, attribute_name = target
    value = getattr(import_module(module_name, __name__), attribute_name)
    globals()[name] = value
    return value

def __dir__():
    return sorted(set(globals()) | set(__all__))
