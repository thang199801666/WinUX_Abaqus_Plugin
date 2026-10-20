"""Compatibility shim for the Plot Digitizer feature package.

New code should import ``WinUx.plotdigitizer.ui.PlotDigitizerDialog`` or use
``WinUx.plotdigitizer.integration.open_plot_digitizer``.
"""
from ..plotdigitizer.ui import PlotDigitizerDialog

__all__ = ["PlotDigitizerDialog"]
