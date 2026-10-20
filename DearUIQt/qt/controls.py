"""Compatibility facade for retained Dear ImGui controls with Qt-like APIs.

Implementation is split by concern: buttons, editors, containers/progress and
selection controls. Imports from ``DearUIQt.qt.controls`` remain
stable.
"""
from __future__ import annotations

from .widget import QWidget
from .buttons import ImGuiLabel, ImGuiPushButton, QLabel, QPushButton, QToolButton
from .editors import (
    ImGuiLineEdit, ImGuiSpinBox, ImGuiDoubleSpinBox,
    QLineEdit, QPlainTextEdit, QSpinBox, QDoubleSpinBox,
)
from .containers import QFrame, ImGuiGroupBox, ImGuiProgressBar, QGroupBox, QProgressBar
from .selection import (
    ImGuiCheckBox, ImGuiRadioButtonGroup, QCheckBox, QRadioButton,
    QButtonGroup, QRadioButtonGroup,
)
from .sliders import QAbstractSlider, QSlider
from .combo_box import QComboBox
from .dialog_button_box import QDialogButtonBox

__all__ = [
    "QWidget", "ImGuiLabel", "ImGuiPushButton", "ImGuiLineEdit",
    "ImGuiProgressBar", "ImGuiCheckBox", "ImGuiSpinBox",
    "ImGuiDoubleSpinBox", "ImGuiGroupBox", "ImGuiRadioButtonGroup",
    "QLabel", "QPushButton", "QToolButton", "QFrame", "QLineEdit", "QPlainTextEdit", "QProgressBar",
    "QCheckBox", "QRadioButton", "QButtonGroup", "QRadioButtonGroup",
    "QSpinBox", "QDoubleSpinBox", "QAbstractSlider", "QSlider", "QComboBox",
    "QDialogButtonBox", "QGroupBox",
]
