"""WinUX public package API.

Heavy GUI modules are loaded lazily so diagnostics and configuration utilities
can be imported by the launcher without importing Dear PyGui first.
"""

import os
import sys


def _configure_bundled_vendor():
    """Make an optional plug-in-level vendor directory importable."""
    package_dir = os.path.dirname(os.path.abspath(__file__))
    plugin_dir = os.path.dirname(package_dir)
    candidates = (
        os.path.join(plugin_dir, "vendor"),
        os.path.join(plugin_dir, "winux_vendor"),
        os.path.join(plugin_dir, "site-packages"),
        os.path.join(package_dir, "vendor"),
    )
    vendor_dir = next(
        (path for path in candidates if os.path.isdir(path)),
        None,
    )
    if vendor_dir and vendor_dir not in sys.path:
        sys.path.insert(0, vendor_dir)

    # Keep the handles alive for the process lifetime. This is required for
    # native extension dependencies beside vendored Dear PyGui/Pillow on
    # Python 3.8+ for Windows.
    dll_handles = []
    add_dll_directory = getattr(os, "add_dll_directory", None)
    if vendor_dir and os.name == "nt" and add_dll_directory is not None:
        for directory in (
            vendor_dir,
            os.path.join(vendor_dir, "dearpygui"),
            os.path.join(vendor_dir, "PIL"),
        ):
            if os.path.isdir(directory):
                try:
                    dll_handles.append(add_dll_directory(directory))
                except OSError:
                    pass
    return vendor_dir, dll_handles


VENDOR_DIR, _VENDOR_DLL_HANDLES = _configure_bundled_vendor()

__all__ = ["WinUXController", "run"]


def __getattr__(name):
    if name == "WinUXController":
        from .controller import WinUXController
        return WinUXController
    if name == "run":
        from .application import run
        return run
    raise AttributeError("module {!r} has no attribute {!r}".format(
        __name__, name))
