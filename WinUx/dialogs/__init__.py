"""Public dialog API with dependency-safe lazy imports.

Importing a concrete helper module such as ``WinUx.dialogs.modern`` must not
initialise every dialog backend.  In particular, the standalone Server Notepad
process uses the shared Tk/Qt-like dialog helpers but deliberately does not load
Dear PyGui.  Eager imports here used to pull ``dialogs.base`` (and therefore the
native ``dearpygui._dearpygui`` extension) into that child process before its
window could be created.

Keep the historical ``from WinUx.dialogs import LoginDialog`` API intact while
loading each dialog only when that attribute is actually requested. Application
QDialogs resolve to the shared-process DearUIQt implementations; explicit legacy
process isolation lives under ``WinUx.dialogs.floating_adapters``.
"""

from __future__ import annotations

from importlib import import_module


_LAZY_DIALOGS = {
    "FloatingDialogController": (".floating_dialog", "FloatingDialogController"),
    "QtDialog": (".qt_dialog", "QtDialog"),
    "QDialog": (".qt_dialog", "QDialog"),
    "QtTable": (".qt_dialog", "QtTable"),
    "DialogBase": (".base", "DialogBase"),
    "SyncPreviewDialog": (".inprocess_adapters", "SyncPreviewDialog"),
    "SiteManagerDialog": (".inprocess_adapters", "SiteManagerDialog"),
    "BookmarksDialog": (".inprocess_adapters", "BookmarksDialog"),
    "DiagnosticsDialog": (".inprocess_adapters", "DiagnosticsDialog"),
    "BlockingDialog": (".inprocess_adapters", "BlockingDialog"),
    "JobEditDialog": (".inprocess_adapters", "JobEditDialog"),
    "LoginDialog": (".inprocess_adapters", "LoginDialog"),
    "ODBCheckDialog": (".inprocess_adapters", "ODBCheckDialog"),
    "ODBExtractDialog": (".inprocess_adapters", "ODBExtractDialog"),
    "ReferenceChartDialog": (".native_reference_tools", "ReferenceChartDialog"),
    "PlotDigitizerDialog": (".native_reference_tools", "PlotDigitizerDialog"),
    "ODBXYResultDialog": (".inprocess_adapters", "ODBXYResultDialog"),
    "JobManagerDialog": (".inprocess_adapters", "JobManagerDialog"),
    "JobScheduleDialog": (".inprocess_adapters", "JobScheduleDialog"),
    "ProgressDialog": (".inprocess_adapters", "ProgressDialog"),
    "ServerPathDialog": (".inprocess_adapters", "ServerPathDialog"),
    "LocalFolderDialog": (".inprocess_adapters", "LocalFolderDialog"),
    "LocalFileDialog": (".inprocess_adapters", "LocalFileDialog"),
    "ServerNotepadDialog": (".server_notepad_dialog", "ServerNotepadDialog"),
    "SettingsDialog": (".inprocess_adapters", "SettingsDialog"),
    "ConsoleDialog": (".tk_console_dialog", "ConsoleDialog"),
    "TransferCenterDialog": (".inprocess_adapters", "TransferCenterDialog"),
    "TransferTaskHandle": (".inprocess_adapters", "TransferTaskHandle"),
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
