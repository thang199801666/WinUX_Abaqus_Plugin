"""Dear ImGui retained widget contracts with Qt-like style/behavior semantics."""
from .core import QObject, Signal, SignalConnection, QSignalBlocker
from .controls import (
    QWidget, ImGuiLabel, ImGuiPushButton, ImGuiLineEdit, ImGuiProgressBar,
    ImGuiCheckBox, ImGuiSpinBox, ImGuiDoubleSpinBox, ImGuiGroupBox,
    ImGuiRadioButtonGroup, QLabel, QPushButton, QLineEdit, QProgressBar,
    QCheckBox, QRadioButtonGroup, QSpinBox, QDoubleSpinBox, QGroupBox,
)
from .layouts import QHBoxLayout, QVBoxLayout, QGridLayout
from .tabs import ImGuiTabPage, ImGuiTabWidget, QTabWidget
from .menu import ImGuiMenu, QMenu
from .item_views import (
    QtGridColumn, QtGridRow, QtListItem, QtSelectionMode, QtItemViewState,
    QtDataGridView, QtListView, ImGuiItemViewState, ImGuiDataGridView,
    ImGuiListView, ImGuiHeaderView, QHeaderView, QTableView, QListView,
)
from .imgui_qt_style import ImGuiQtPalette, ImGuiQtMetrics, ImGuiQtControlMetrics


def __getattr__(name):
    # Keep the editable combo lazy: its implementation imports the real DPG
    # backend, while the retained widget/model modules remain importable in
    # headless unit tests.
    if name == "ImGuiComboBox":
        from ..components.imgui_combo_box import ImGuiComboBox
        return ImGuiComboBox
    raise AttributeError(name)

ImGuiWidget = QWidget
ImGuiHBoxLayout = QHBoxLayout
ImGuiVBoxLayout = QVBoxLayout
ImGuiGridLayout = QGridLayout

__all__ = [
    "QObject", "Signal", "SignalConnection", "QSignalBlocker",
    "QWidget", "ImGuiWidget", "ImGuiLabel", "ImGuiPushButton", "ImGuiLineEdit",
    "ImGuiProgressBar", "ImGuiCheckBox", "ImGuiSpinBox", "ImGuiDoubleSpinBox",
    "ImGuiGroupBox", "ImGuiRadioButtonGroup", "QLabel", "QPushButton", "QLineEdit", "QProgressBar",
    "QCheckBox", "QRadioButtonGroup", "QSpinBox", "QDoubleSpinBox", "QGroupBox", "QHBoxLayout", "QVBoxLayout", "QGridLayout",
    "ImGuiHBoxLayout", "ImGuiVBoxLayout", "ImGuiGridLayout",
    "QtGridColumn", "QtGridRow", "QtListItem", "QtSelectionMode", "QtItemViewState",
    "QtDataGridView", "QtListView", "ImGuiItemViewState", "ImGuiDataGridView",
    "ImGuiListView", "ImGuiHeaderView", "QHeaderView", "QTableView", "QListView", "ImGuiTabPage",
    "ImGuiTabWidget", "QTabWidget", "ImGuiMenu", "QMenu", "ImGuiQtPalette",
    "ImGuiQtMetrics", "ImGuiQtControlMetrics", "ImGuiComboBox",
]
