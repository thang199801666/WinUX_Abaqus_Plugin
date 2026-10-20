"""Select the locally bundled, ABI-matched native DearUIQt runtime."""
import json
import os
import struct
import sys


def native_runtime_path(project_dir, environ=None):
    environ = os.environ if environ is None else environ
    if str(environ.get("WINUX_NATIVE_WINDOWS", "1")).strip().lower() in ("0", "false", "off", "no"):
        return None
    if os.name != "nt" or struct.calcsize("P") != 8:
        return None
    abi = "cp{}{}-win_amd64".format(*sys.version_info[:2])
    root = os.path.join(os.path.abspath(project_dir), "DearUIQt", "native", "runtime", abi)
    try:
        with open(os.path.join(root, "dearuiqt_build.json"), "r") as handle:
            metadata = json.load(handle)
        if metadata.get("python_cache_tag") != sys.implementation.cache_tag or metadata.get("native_abi") != 1:
            return None
        if not all(os.path.isfile(os.path.join(root, "dearpygui", name)) for name in (
                "__init__.py", "dearpygui.py", "_dearpygui.pyd")):
            return None
    except (OSError, ValueError, AttributeError):
        return None
    return root
