"""Abaqus/CAE registration entry point for the WinUx launcher plug-in.

Abaqus/CAE automatically imports files named ``*_plugin.py`` from its plug-in
directories.  Keep this module compatible with both Python 2 and Python 3
because the supported Python version depends on the Abaqus release.
"""

from __future__ import print_function

import json
import os
import sys
import tempfile

from abaqusConstants import ALL
from abaqusGui import (
    AFXMode,
    FXMAPFUNC,
    FXObject,
    SEL_COMMAND,
    getAFXApp,
    showAFXErrorDialog,
    showAFXInformationDialog,
)

def _activate_self_updated_bootstrap():
    """Prefer the per-user immutable bootstrap while keeping this file stable.

    The plug-in shim itself is intentionally tiny and remains in the Abaqus
    plug-in folder.  All substantial bootstrap modules can therefore update
    without overwriting files imported by Abaqus/CAE.  Invalid state always
    falls back to the bundled copy beside this shim.
    """
    if str(os.environ.get("WINUX_BOOTSTRAP_MODE", "")).strip().lower() in (
            "legacy", "bundled", "off", "disabled"):
        return None
    base = (os.environ.get("LOCALAPPDATA") or os.environ.get("APPDATA") or tempfile.gettempdir())
    root = os.path.join(os.path.abspath(base), "WinUx", "bootstrap")
    state_path = os.path.join(root, "state", "current.json")
    try:
        with open(state_path, "r") as handle:
            state = json.load(handle)
    except Exception:
        return None
    versions = []
    active = str(state.get("active_version") or "").strip()
    if active:
        versions.append(active)
    previous = state.get("previous_versions")
    if isinstance(previous, list):
        versions.extend(str(item).strip() for item in previous if str(item).strip())
    required = ("winux_launcher.py", "winux_updater.py", "run_winux.py", "VERSION")
    for version in versions:
        safe = "".join(ch if ch.isalnum() or ch in "._+-" else "_" for ch in version)
        candidate = os.path.join(root, "versions", safe)
        if not all(os.path.isfile(os.path.join(candidate, name)) for name in required):
            continue
        try:
            with open(os.path.join(candidate, "VERSION"), "r") as handle:
                if handle.read().strip() != version:
                    continue
        except Exception:
            continue
        if candidate not in sys.path:
            sys.path.insert(0, candidate)
        os.environ["WINUX_BOOTSTRAP_DIR"] = candidate
        return candidate
    return None


_activate_self_updated_bootstrap()

from winux_launcher import launch_winux, resolve_project_dir


def _plugin_version():
    """Report the active immutable runtime version when one is available."""
    try:
        root = resolve_project_dir()
        path = os.path.join(root, "VERSION")
        with open(path, "r") as handle:
            value = handle.read().strip()
        return value or "unknown"
    except Exception:
        try:
            path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "VERSION")
            with open(path, "r") as handle:
                value = handle.read().strip()
            return value or "unknown"
        except Exception:
            return "unknown"


class WinUxMenuTarget(FXObject):
    """Receive the Plug-ins menu command and start WinUx out-of-process."""

    # ``FXObject.ID_LAST`` is not exposed by several Abaqus/FOX builds.
    # ID_ACTIVATE is the documented default selector for plug-in menu buttons
    # and is available consistently through AFXMode.
    ID_LAUNCH = AFXMode.ID_ACTIVATE

    def __init__(self):
        FXObject.__init__(self)
        FXMAPFUNC(
            self,
            SEL_COMMAND,
            self.ID_LAUNCH,
            WinUxMenuTarget.onCmdLaunch,
        )

    def onCmdLaunch(self, sender, selector, data):
        del sender, selector, data
        main_window = getAFXApp().getAFXMainWindow()
        try:
            _process, started = launch_winux()
            if not started:
                showAFXInformationDialog(
                    main_window,
                    "WinUx is already running from this Abaqus/CAE session.",
                )
        except Exception as exc:
            showAFXErrorDialog(
                main_window,
                "WinUx could not start.\n\n{}".format(exc),
            )
        return 1


# Keep a module-level Python reference for the lifetime of Abaqus/CAE.  The FOX
# menu stores the C++ target, but the Python wrapper must not be garbage-collected.
_WINUX_MENU_TARGET = WinUxMenuTarget()

_TOOLSET = getAFXApp().getAFXMainWindow().getPluginToolset()
_TOOLSET.registerGuiMenuButton(
    buttonText="WinUx",
    object=_WINUX_MENU_TARGET,
    messageId=_WINUX_MENU_TARGET.ID_LAUNCH,
    # Keep the Abaqus Plug-ins menu text-only, matching native menu entries.
    icon=None,
    kernelInitString="",
    applicableModules=ALL,
    version=_plugin_version(),
    author="WinUx",
    description=(
        "Launch the local WinUx workspace with optional version checking and "
        "user-controlled updates from the shared deployment."
    ),
)
