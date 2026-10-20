"""QtWidgets-style visual controls and windows.

Implementation lives in this package. ``DearUIQt.qt`` is a legacy facade only.
"""
from .._lazy import resolve, namespace_dir
_EXPORTS = {
    "QApplication": "..core.application", "QWidget": ".widget", "QRetainedItem": ".retained", "QCanvas": ".canvas", "QViewportCanvas": ".canvas", "QToolTip": ".tooltip",
    "QPlotWidget": ".plot", "QPlotAxis": ".plot", "QLineSeries": ".plot",
    "QFrame": ".containers", "QMainWindow": ".windows", "QNativeWindow": ".native_window", "QInlineEditPanel": ".inline_edit",
    "QLabel": ".buttons", "QPushButton": ".buttons", "QToolButton": ".buttons", "QImageView": ".image",
    "QLineEdit": ".editors", "QPlainTextEdit": ".editors", "QTextEdit": ".text_edit",
    "QSpinBox": ".editors", "QDoubleSpinBox": ".editors",
    "QProgressBar": ".containers", "QGroupBox": ".containers",
    "QCheckBox": ".selection", "QRadioButton": ".selection",
    "QButtonGroup": ".selection", "QRadioButtonGroup": ".selection",
    "QAbstractSlider": ".sliders", "QSlider": ".sliders", "QScrollBar": ".scrollbar",
    "QComboBox": ".combo_box", "QtComboBox": ".combo_box", "ImGuiComboBox": ".combo_box",
    "QDialogButtonBox": ".dialog_button_box", "QTabWidget": ".tabs",
    "QStackedWidget": ".tabs", "QMenu": ".menu", "QModelessMenu": ".modeless_menu", "QPopupPanel": ".popup_panel", "QMenuBar": ".menu_bar",
    "QAbstractScrollArea": ".abstract_scroll_area", "QScrollArea": ".scroll_area",
    "QScroller": "..backends.dearpygui", "QScrollerMetrics": "..backends.dearpygui",
    "QScrollerArrowOverlay": "..backends.dearpygui",
    "QToolBar": ".tool_bar", "QStatusBar": ".tool_bar",
    "QSplitterHandle": "..layouts.splitter",
    "QSeparator": ".primitives", "QSpacer": ".primitives",
    "QDialog": "..dialogs", "QtDialog": "..dialogs", "QtTable": "..dialogs", "DialogBase": "..dialogs", "DialogCode": "..dialogs",
    "QDockWidget": "..docking", "DockWidget": "..docking", "DockManager": "..docking",
    "DockDropPreview": "..docking", "DockLayoutTree": "..docking",
    "QToolWindow": "..tool_window", "ToolWindow": "..tool_window",
    "ColorField": ".color_field", "QColorField": ".color_field",
}
__all__ = list(_EXPORTS)
def __getattr__(name): return resolve(globals(), __name__, _EXPORTS, name)
def __dir__(): return namespace_dir(globals(), _EXPORTS)
