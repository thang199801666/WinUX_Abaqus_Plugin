"""Identify WinUx's single vendored, ABI-matched Dear PyGui runtime."""
import json
import os
import struct
import sys


def native_runtime_path(project_dir, environ=None):
    # Native-window enablement is a feature flag, not a second import path.
    # Both window modes use the same extension in vendor/dearpygui.
    del environ
    if os.name != "nt" or struct.calcsize("P") != 8:
        return None
    root = os.path.join(os.path.abspath(project_dir), "vendor")
    try:
        with open(os.path.join(root, "dearpygui", "dearuiqt_build.json"), "r") as handle:
            metadata = json.load(handle)
        if metadata.get("python_cache_tag") != sys.implementation.cache_tag or metadata.get("native_abi") != 1:
            return None
        if not all(os.path.isfile(os.path.join(root, "dearpygui", name)) for name in (
                "__init__.py", "dearpygui.py", "_dearpygui.pyd")):
            return None
    except (OSError, ValueError, AttributeError):
        return None
    return root
