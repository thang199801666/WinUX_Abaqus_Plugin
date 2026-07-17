# -*- coding: utf-8 -*-
"""Abaqus/CAE GUI registration file for WinUX."""

from abaqusGui import FXObject, FXMAPFUNC, SEL_COMMAND, getAFXApp
from abaqusConstants import ALL


class WinUXLauncher(FXObject):
    ID_LAUNCH = 1

    def __init__(self):
        FXObject.__init__(self)
        FXMAPFUNC(
            self,
            SEL_COMMAND,
            self.ID_LAUNCH,
            WinUXLauncher.onCmdLaunch,
        )

    def onCmdLaunch(self, sender, sel, ptr):
        try:
            import winux_plugin_launcher
            winux_plugin_launcher.launch_winux()
        except Exception as exc:
            try:
                from abaqusGui import showAFXErrorDialog
                showAFXErrorDialog(
                    getAFXApp().getAFXMainWindow(),
                    'Failed to start WinUX:\n%s' % exc,
                )
            except Exception:
                print('Failed to start WinUX: %s' % exc)
        return 1


_toolset = getAFXApp().getAFXMainWindow().getPluginToolset()
_launcher = WinUXLauncher()

_toolset.registerGuiMenuButton(
    buttonText='WinUX Explorer...',
    object=_launcher,
    messageId=WinUXLauncher.ID_LAUNCH,
    icon=None,
    kernelInitString='',
    applicableModules=ALL,
    version='1.2.0',
    author='Thang',
    description='Open the WinUX dual-panel file and job explorer.',
    helpUrl='',
)