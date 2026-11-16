"""QtGui-style non-widget GUI types and styling primitives."""
from .._lazy import resolve, namespace_dir
_EXPORTS = {
    "QGuiEventType": ".events", "isGuiEventType": ".events",
    "QAction": ".action", "QActionGroup": ".action", "QUndoCommand": ".undo", "QUndoStack": ".undo", "QEditTransaction": ".edit_transaction", "QPropertyEditCommand": ".property_edit", "QPropertyEditController": ".property_edit",
    "QKeySequence": ".shortcut", "QShortcut": ".shortcut",
    "QPen": ".painting", "QBrush": ".painting", "QPainter": ".painting", "QPaintLayer": ".layers",
    "QFont": ".resources", "QFontDatabase": ".resources", "QTexture": ".resources", "QTextureRegistry": ".resources",
    "QCursor": ".system", "QKeyboard": ".system", "QClipboard": ".system", "QFontMetrics": ".system", "QScreen": ".system",
    "QPalette": ".palette", "QtFusionPalette": ".palette", "QtFusionMetrics": ".palette",
    "color_hex": ".palette", "ImGuiQtPalette": ".style",
    "ImGuiQtMetrics": ".style", "ImGuiQtControlMetrics": ".style",
    "METRICS": ".style", "metrics_for_dpi": ".style", "metrics_for_screen": ".style", "metrics_for_backend": ".style",
    "logical_dpi_for_backend": ".dpi", "dpi_scale_for_backend": ".dpi",
    "sync_backend_dpi": ".dpi",
    "QStyle": ".style", "QProxyStyle": ".style", "QStyleFactory": ".style",
    "QStandardItem": ".standard_item_model", "QStandardItemModel": ".standard_item_model",
    "QWindowHost": ".window_host", "QWindowHostState": ".window_host", "QPopupSurface": ".popup_surface",
    "QLifecycleTransitionRecord": ".lifecycle",
    "QCloseEvent": "..core", "QKeyEvent": ".events", "QMouseEvent": ".events", "QWheelEvent": ".events",
}
__all__ = list(_EXPORTS)
def __getattr__(name): return resolve(globals(), __name__, _EXPORTS, name)
def __dir__(): return namespace_dir(globals(), _EXPORTS)
