"""Canonical Dear ImGui editable combo-box API.

The implementation currently lives in ``qt_combo_box`` for compatibility with
older WinUx imports.  New code should import from this module; the control is
implemented entirely with Dear PyGui primitives.
"""
from .qt_combo_box import ImGuiComboBox

__all__ = ["ImGuiComboBox"]
