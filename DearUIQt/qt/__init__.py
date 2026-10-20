"""Portable Dear ImGui widgets exposing a compact Qt-like API.

The namespace is intentionally lazy. Importing QtCore-style primitives such as
QObject/QTimer/QApplication must not import DearPyGui, menu rendering, scrollers
or every widget class. This keeps command-line/domain code lightweight and
reduces cold dialog worker startup.
"""
from importlib import import_module

_LAZY_EXPORTS = {
    # QtCore-style primitives
    "Qt": ".core", "QPoint": ".core", "QPointF": ".core", "QSize": ".core", "QRect": ".core", "QMargins": ".core", "QSizePolicy": ".core", "QObject": ".core", "Signal": ".core",
    "SignalConnection": ".core", "QSignalBlocker": ".core", "QMetaObject": ".core", "QPointer": ".core",
    "QEvent": ".core", "QCloseEvent": ".core", "QChildEvent": ".core", "QKeyEvent": ".core", "QMouseEvent": ".core",
    "QInputTarget": ".input_target",
    "QCoreApplication": ".application", "QApplication": ".application", "QTimer": ".timer", "QThread": ".thread",
    "QRunnable": ".concurrent", "QFuture": ".concurrent",
    "QFutureWatcher": ".concurrent", "QThreadPool": ".concurrent",
    "QtConcurrent": ".concurrent", "QProcess": ".process",

    # Actions / base windows
    "QAction": ".action", "QActionGroup": ".action",
    "QWidget": ".widget", "QMainWindow": ".windows",

    # Controls
    "ImGuiLabel": ".buttons", "ImGuiPushButton": ".buttons",
    "QLabel": ".buttons", "QPushButton": ".buttons", "QToolButton": ".buttons",
    "ImGuiLineEdit": ".editors", "ImGuiSpinBox": ".editors",
    "ImGuiDoubleSpinBox": ".editors", "QLineEdit": ".editors",
    "QPlainTextEdit": ".editors", "QSpinBox": ".editors", "QDoubleSpinBox": ".editors",
    "ImGuiProgressBar": ".containers", "ImGuiGroupBox": ".containers",
    "QFrame": ".containers", "QProgressBar": ".containers", "QGroupBox": ".containers",
    "ImGuiCheckBox": ".selection", "ImGuiRadioButtonGroup": ".selection",
    "QCheckBox": ".selection", "QRadioButton": ".selection",
    "QButtonGroup": ".selection", "QRadioButtonGroup": ".selection",
    "QAbstractSlider": ".sliders", "QSlider": ".sliders", "QDialogButtonBox": ".dialog_button_box",

    # Layouts / tabs / popups
    "QBoxLayout": ".layouts", "QHBoxLayout": ".layouts", "QVBoxLayout": ".layouts",
    "QGridLayout": ".layouts", "QFormLayout": ".layouts", "QLayoutItem": ".layouts",
    "ImGuiTabPage": ".tabs", "ImGuiTabWidget": ".tabs", "QTabWidget": ".tabs",
    "ImGuiStackedWidget": ".tabs", "QStackedWidget": ".tabs",
    "ImGuiMenu": ".menu", "QMenu": ".menu", "QMenuBar": ".menu_bar",
    "QComboBox": ".combo_box", "QtComboBox": ".combo_box", "ImGuiComboBox": ".combo_box",

    # Item views / models
    "QtGridColumn": ".item_models", "QtGridRow": ".item_models",
    "QtListItem": ".item_models", "QtSelectionMode": ".item_models",
    "QtItemViewState": ".item_models",
    "ImGuiHeaderView": ".item_grid", "QHeaderView": ".item_grid",
    "QtDataGridView": ".item_grid", "ImGuiDataGridView": ".item_grid",
    "QTableView": ".item_grid", "QtListView": ".item_list",
    "ImGuiListView": ".item_list", "QListView": ".item_list",
    "QTreeItem": ".tree", "QTreeView": ".tree",

    # Styling / containers / chrome
    "QtFusionPalette": ".palette", "QtFusionMetrics": ".palette", "color_hex": ".palette",
    "ImGuiQtPalette": ".style", "ImGuiQtMetrics": ".style",
    "ImGuiQtControlMetrics": ".style", "METRICS": ".style",
    "QScroller": ".scroller", "DpgScrollerArrowOverlay": ".scroller",
    "SharedScrollerMetrics": ".scroller", "SharedScrollerPalette": ".scroller",
    "QScrollArea": ".scroll_area", "QSplitter": ".splitter", "QSplitterHandle": ".splitter",
    "QToolBar": ".tool_bar", "QStatusBar": ".tool_bar",
}

# Historical ImGui-prefixed layout/widget aliases. Resolve aliases lazily too,
# rather than importing the target module during package initialization.
_ALIASES = {
    "ImGuiWidget": "QWidget",
    "ImGuiHBoxLayout": "QHBoxLayout",
    "ImGuiVBoxLayout": "QVBoxLayout",
    "ImGuiGridLayout": "QGridLayout",
    "ImGuiFormLayout": "QFormLayout",
    "ImGuiItemViewState": "QtItemViewState",
}

__all__ = list(_LAZY_EXPORTS) + list(_ALIASES)


def __getattr__(name):
    alias = _ALIASES.get(name)
    if alias is not None:
        value = getattr(__import__(__name__, fromlist=[alias]), alias)
        globals()[name] = value
        return value
    module_name = _LAZY_EXPORTS.get(name)
    if module_name is None:
        raise AttributeError("module {!r} has no attribute {!r}".format(__name__, name))
    value = getattr(import_module(module_name, __name__), name)
    globals()[name] = value
    return value


def __dir__():
    return sorted(set(globals()) | set(__all__))
