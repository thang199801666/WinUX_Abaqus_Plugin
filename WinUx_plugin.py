"""Abaqus/CAE registration entry point for the WinUx launcher plug-in.

Abaqus/CAE automatically imports files named ``*_plugin.py`` from its plug-in
directories.  Keep this module compatible with both Python 2 and Python 3
because the supported Python version depends on the Abaqus release.
"""

from __future__ import print_function

import os

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

from winux_launcher import launch_winux


def _plugin_version():
    """Read the deployment VERSION so local/server packages share one codebase."""
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
