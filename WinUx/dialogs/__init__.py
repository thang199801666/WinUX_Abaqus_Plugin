"""Public dialog API with dependency-safe lazy imports.

Importing a concrete helper module such as ``WinUx.dialogs.modern`` must not
initialise every dialog backend.  In particular, the standalone Server Notepad
process uses the shared Tk/Qt-like dialog helpers but deliberately does not load
Dear PyGui.  Eager imports here used to pull ``dialogs.base`` (and therefore the
native ``dearpygui._dearpygui`` extension) into that child process before its
window could be created.

Keep the historical ``from WinUx.dialogs import LoginDialog`` API intact while
loading each dialog only when that attribute is actually requested.
"""

from __future__ import annotations

from importlib import import_module


_LAZY_DIALOGS = {
    "FloatingDialogController": (".floating_dialog", "FloatingDialogController"),
    "QtDialog": (".qt_dialog", "QtDialog"),
    "QtTable": (".qt_dialog", "QtTable"),
    "DialogBase": (".base", "DialogBase"),
    "SyncPreviewDialog": (".sync_preview_dialog", "SyncPreviewDialog"),
    "SiteManagerDialog": (".site_manager_dialog", "SiteManagerDialog"),
    "BookmarksDialog": (".bookmarks_dialog", "BookmarksDialog"),
    "DiagnosticsDialog": (".diagnostics_dialog", "DiagnosticsDialog"),
    "BlockingDialog": (".blocking_dialog", "BlockingDialog"),
    "JobEditDialog": (".job_edit_dialog", "JobEditDialog"),
    "LoginDialog": (".login_dialog", "LoginDialog"),
    "ODBCheckDialog": (".odb_check_dialog", "ODBCheckDialog"),
    "ODBExtractDialog": (".odb_extract_dialog", "ODBExtractDialog"),
    "ODBXYResultDialog": (".odb_extract_dialog", "ODBXYResultDialog"),
    "JobManagerDialog": (".job_manager_dialog", "JobManagerDialog"),
    "JobScheduleDialog": (".job_schedule_dialog", "JobScheduleDialog"),
    "ProgressDialog": (".progress_dialog", "ProgressDialog"),
    "ServerPathDialog": (".server_path_dialog", "ServerPathDialog"),
    "LocalFolderDialog": (".local_folder_dialog", "LocalFolderDialog"),
    "ServerNotepadDialog": (".server_notepad_dialog", "ServerNotepadDialog"),
    "SettingsDialog": (".settings_dialog", "SettingsDialog"),
    "ConsoleDialog": (".tk_console_dialog", "ConsoleDialog"),
    "TransferCenterDialog": (".transfer_center_dialog", "TransferCenterDialog"),
    "TransferTaskHandle": (".transfer_center_dialog", "TransferTaskHandle"),
}

__all__ = list(_LAZY_DIALOGS)


def __getattr__(name):
    target = _LAZY_DIALOGS.get(name)
    if target is None:
        raise AttributeError(
            "module {!r} has no attribute {!r}".format(__name__, name))
    module_name, attribute_name = target
    value = getattr(import_module(module_name, __name__), attribute_name)
    # Cache the resolved class just like a normal eager import.  This keeps
    # repeated attribute access cheap and preserves introspection semantics.
    globals()[name] = value
    return value


def __dir__():
    return sorted(set(globals()) | set(__all__))
