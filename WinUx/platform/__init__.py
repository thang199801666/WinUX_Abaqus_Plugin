"""Platform integration facade.

Platform implementations are imported lazily so importing an unrelated platform
helper (for example ``WinUx.platform.resources``) does not initialize native
windowing modules or create circular imports during GUI startup.
"""

_NATIVE_DIALOG_EXPORTS = {
    "NativeDialogController",
    "apply_native_qt_chrome",
    "attach_native_owner",
    "center_over_owner",
    "find_process_window",
    "is_native_window_foreground",
    "restore_owner_focus",
    "resolve_native_dialog_parent",
    "restore_native_dialog_geometry",
    "save_native_dialog_geometry",
    "set_owner_enabled",
}
_RESOURCE_EXPORTS = {"RESOURCE_DIR", "resource_path", "icon_path"}

__all__ = sorted(_NATIVE_DIALOG_EXPORTS | _RESOURCE_EXPORTS)


def __getattr__(name):
    if name in _NATIVE_DIALOG_EXPORTS:
        from . import native_dialog_host
        return getattr(native_dialog_host, name)
    if name in _RESOURCE_EXPORTS:
        from . import resources
        return getattr(resources, name)
    raise AttributeError(name)


def __dir__():
    return sorted(set(globals()) | set(__all__))
