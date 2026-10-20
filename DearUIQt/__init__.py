"""DearUIQt — reusable Qt-style desktop GUI library backed by Dear PyGui.

New code should prefer the structured namespaces ``core``, ``gui``, ``widgets``,
``layouts`` and ``modelview``.  Top-level exports are retained for source
compatibility and convenience.
"""
from importlib import import_module

_LAZY_EXPORTS = {
    # Core
    "Qt": ".core", "QPoint": ".core", "QPointF": ".core", "QSize": ".core",
    "QRect": ".core", "QMargins": ".core", "QSizePolicy": ".core",
    "QCoreApplication": ".core", "QObject": ".core", "QEvent": ".core",
    "QCloseEvent": ".core", "QKeyEvent": ".core", "QMouseEvent": ".core",
    "QChildEvent": ".core", "QPointer": ".core", "Signal": ".core",
    "QInputTarget": ".core", "QItemInputBinding": ".core", "QGlobalInputBinding": ".core", "SignalConnection": ".core",
    "QSignalBlocker": ".core", "QMetaObject": ".core", "QTimer": ".core",
    "QThread": ".core", "QRunnable": ".core", "QFuture": ".core",
    "QFutureWatcher": ".core", "QThreadPool": ".core", "QtConcurrent": ".core",
    "QProcess": ".core",
    "QModelIndex": ".core", "QPersistentModelIndex": ".core",
    "QAbstractItemModel": ".core", "QAbstractTableModel": ".core",
    "QAbstractListModel": ".core", "QItemSelectionRange": ".core",
    "QItemSelection": ".core", "QItemSelectionModel": ".core",

    # GUI / actions
    "QAction": ".gui", "QActionGroup": ".gui",
    "QPen": ".gui", "QBrush": ".gui", "QPainter": ".gui", "QPaintLayer": ".gui",
    "QFont": ".gui", "QFontDatabase": ".gui", "QTexture": ".gui", "QTextureRegistry": ".gui",
    "QCursor": ".gui", "QClipboard": ".gui", "QFontMetrics": ".gui", "QScreen": ".gui",
    "QPalette": ".gui", "QStyle": ".gui", "QProxyStyle": ".gui", "QStyleFactory": ".gui",
    "QtFusionPalette": ".gui", "QtFusionMetrics": ".gui",
    "QStandardItem": ".gui", "QStandardItemModel": ".gui",

    # Widgets
    "QApplication": ".widgets", "QWidget": ".widgets", "QRetainedItem": ".widgets", "QCanvas": ".widgets", "QToolTip": ".widgets", "QFrame": ".widgets",
    "QPlotWidget": ".widgets", "QPlotAxis": ".widgets", "QLineSeries": ".widgets",
    "QMainWindow": ".widgets", "QLabel": ".widgets", "QPushButton": ".widgets", "QImageView": ".widgets", "QInlineEditPanel": ".widgets",
    "QToolButton": ".widgets", "QLineEdit": ".widgets", "QPlainTextEdit": ".widgets", "QTextEdit": ".widgets",
    "QProgressBar": ".widgets", "QCheckBox": ".widgets", "QRadioButton": ".widgets",
    "QButtonGroup": ".widgets", "QRadioButtonGroup": ".widgets",
    "QSpinBox": ".widgets", "QDoubleSpinBox": ".widgets", "QGroupBox": ".widgets",
    "QAbstractSlider": ".widgets", "QSlider": ".widgets", "QScrollBar": ".widgets", "QDialogButtonBox": ".widgets",
    "QTabWidget": ".widgets", "QStackedWidget": ".widgets", "QMenu": ".widgets", "QModelessMenu": ".widgets", "QPopupPanel": ".widgets",
    "QMenuBar": ".widgets", "QComboBox": ".widgets", "QtComboBox": ".widgets",
    "QAbstractScrollArea": ".widgets", "QScrollArea": ".widgets", "QScroller": ".widgets", "QToolBar": ".widgets",
    "QStatusBar": ".widgets", "QSeparator": ".widgets", "QSpacer": ".widgets", "ColorField": ".widgets", "QColorField": ".widgets",
    "DialogBase": ".widgets", "DialogCode": ".widgets", "QtDialog": ".widgets", "QDialog": ".widgets",
    "DockWidget": ".widgets", "QDockWidget": ".widgets", "DockManager": ".widgets",
    "DockDropPreview": ".widgets", "DockLayoutTree": ".widgets",
    "ToolWindow": ".widgets", "QToolWindow": ".widgets",

    # Layouts
    "QBoxLayout": ".layouts", "QHBoxLayout": ".layouts", "QVBoxLayout": ".layouts",
    "QGridLayout": ".layouts", "QFormLayout": ".layouts", "QLayoutItem": ".layouts", "QSpacerItem": ".layouts",
    "QSplitter": ".layouts", "QSplitterHandle": ".layouts", "SplitterAxis": ".layouts",
    "SplitterController": ".layouts", "SplitterPolicy": ".layouts",
    "SplitterSizes": ".layouts", "SplitterState": ".layouts",
    "clamp_ratio": ".layouts", "split_extent": ".layouts",

    # Model/view
    "QAbstractItemView": ".modelview", "QTableView": ".modelview", "QTableWidget": ".modelview", "QTableWidgetItem": ".modelview",
    "QListView": ".modelview", "QListWidget": ".modelview", "QListWidgetItem": ".modelview", "QHeaderView": ".modelview",
    "QTreeItem": ".modelview", "QTreeView": ".modelview", "QTreeWidget": ".modelview", "QTreeWidgetItem": ".modelview",
    "QAbstractItemDelegate": ".modelview", "QStyledItemDelegate": ".modelview", "QStandardItem": ".modelview", "QStandardItemModel": ".modelview", "QtDataGridView": ".modelview",
    "QtListView": ".modelview", "QtGridColumn": ".modelview", "QtGridRow": ".modelview",
    "QtListItem": ".modelview", "QtSelectionMode": ".modelview",
    "QtItemViewState": ".modelview",

    # Themes / styling resources
    "QTheme": ".themes",

    # Higher-level / utilities
    "StandaloneUiHost": ".runtime", "QGuiRuntime": ".runtime", "RibbonBar": ".ribbon",
    "RibbonResources": ".contracts", "LatestCallQueue": ".dispatch",
    "DpgScrollerArrowOverlay": ".backends.dearpygui", "SharedScrollerMetrics": ".backends.dearpygui",
    "SharedScrollerPalette": ".backends.dearpygui",
}

# Historical names remain compatibility leaves; new code should not depend on them.
for _name in (
    "ImGuiWidget", "ImGuiLabel", "ImGuiPushButton", "ImGuiLineEdit",
    "ImGuiProgressBar", "ImGuiCheckBox", "ImGuiSpinBox", "ImGuiDoubleSpinBox",
    "ImGuiGroupBox", "ImGuiRadioButtonGroup", "ImGuiHBoxLayout",
    "ImGuiVBoxLayout", "ImGuiGridLayout", "ImGuiFormLayout",
    "ImGuiTabPage", "ImGuiTabWidget", "ImGuiStackedWidget", "ImGuiMenu", "ImGuiHeaderView",
    "ImGuiDataGridView", "ImGuiListView", "ImGuiItemViewState",
    "ImGuiQtPalette", "ImGuiQtMetrics", "ImGuiQtControlMetrics", "ImGuiComboBox",
):
    _LAZY_EXPORTS[_name] = ".qt"

__all__ = list(_LAZY_EXPORTS)
__version__ = "1.36.3"


def __getattr__(name):
    module_name = _LAZY_EXPORTS.get(name)
    if module_name is None:
        raise AttributeError("module {!r} has no attribute {!r}".format(__name__, name))
    value = getattr(import_module(module_name, __name__), name)
    globals()[name] = value
    return value


def __dir__():
    return sorted(set(globals()) | set(__all__))
