"""Pytest collection policy for WinUx.

The shipped Dear PyGui extension is a Windows ``.pyd``.  Portable CI should
still execute the large pure-Python regression suite rather than failing while
collecting tests that need a real Win32/DPG runtime.  Those tests remain part of
the repository and are collected normally on Windows.
"""
from __future__ import annotations

import sys


_WINDOWS_NATIVE_MODULES = {
    "test_all_floating_dialogs.py",
    "test_dialog_prewarm.py",
    "test_dpg_dialog_migration.py",
    "test_floating_login.py",
    "test_native_widget_wrappers.py",
}


def pytest_ignore_collect(collection_path, config):
    del config
    if sys.platform == "win32":
        return None
    # Returning False short-circuits pytest's first-result hook and prevents
    # command-line --ignore from taking effect. Defer all other decisions.
    return True if collection_path.name in _WINDOWS_NATIVE_MODULES else None
