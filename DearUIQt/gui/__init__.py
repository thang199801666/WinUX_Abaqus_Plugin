"""QtGui-style non-widget GUI types and styling primitives."""
from .._lazy import resolve, namespace_dir
_EXPORTS = {
    "QAction": ".action", "QActionGroup": ".action",
    "QPen": ".painting", "QBrush": ".painting", "QPainter": ".painting", "QPaintLayer": ".layers",
    "QFont": ".resources", "QFontDatabase": ".resources", "QTexture": ".resources", "QTextureRegistry": ".resources",
    "QCursor": ".system", "QKeyboard": ".system", "QClipboard": ".system", "QFontMetrics": ".system", "QScreen": ".system",
    "QPalette": ".palette", "QtFusionPalette": ".palette", "QtFusionMetrics": ".palette",
    "color_hex": ".palette", "ImGuiQtPalette": ".style",
    "ImGuiQtMetrics": ".style", "ImGuiQtControlMetrics": ".style",
    "METRICS": ".style", "QStyle": ".style", "QProxyStyle": ".style", "QStyleFactory": ".style",
    "QStandardItem": ".standard_item_model", "QStandardItemModel": ".standard_item_model",
    "QCloseEvent": "..core", "QKeyEvent": "..core", "QMouseEvent": "..core",
}
__all__ = list(_EXPORTS)
def __getattr__(name): return resolve(globals(), __name__, _EXPORTS, name)
def __dir__(): return namespace_dir(globals(), _EXPORTS)
