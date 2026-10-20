"""Bundled dependency discovery for the importable WinUx package.

The standalone ``run_winux.py`` bootstrap has additional deployment/update
rules and deliberately remains independent.  This module owns only the package
import-time vendor-path policy previously embedded in ``WinUx.__init__``.
"""

from __future__ import annotations

import os
import sys


def _vendor_candidates(package_dir):
    plugin_dir = os.path.dirname(package_dir)
    return (
        os.path.join(plugin_dir, "vendor"),
        os.path.join(plugin_dir, "winux_vendor"),
        os.path.join(plugin_dir, "site-packages"),
        os.path.join(package_dir, "vendor"),
    )


def configure_package_vendor(package_dir=None):
    """Expose the first bundled vendor directory and adjacent native DLLs.

    Returns ``(vendor_dir, dll_handles)``.  Callers must retain ``dll_handles``
    for the process lifetime on Windows so loaded extension dependencies stay
    resolvable.
    """
    package_dir = os.path.abspath(
        package_dir or os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    )
    vendor_dir = next(
        (path for path in _vendor_candidates(package_dir) if os.path.isdir(path)),
        None,
    )
    if vendor_dir and vendor_dir not in sys.path:
        sys.path.insert(0, vendor_dir)
    from winux_native_runtime import native_runtime_path
    native = native_runtime_path(os.path.dirname(package_dir))
    if native:
        if native in sys.path:
            sys.path.remove(native)
        sys.path.insert(0, native)

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


__all__ = ["configure_package_vendor"]
