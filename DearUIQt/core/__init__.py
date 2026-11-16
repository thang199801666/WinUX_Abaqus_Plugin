"""QtCore-style, backend-neutral primitives for DearUIQt."""
from .._lazy import resolve, namespace_dir

_EXPORTS = {
    "Qt": ".object", "QPoint": ".object", "QPointF": ".object",
    "QSize": ".object", "QRect": ".object", "QMargins": ".object",
    "QSizePolicy": ".object", "QObject": ".object", "QPointer": ".object",
    "QEvent": ".object", "QCloseEvent": ".object", "QChildEvent": ".object",
    "QKeyEvent": ("..gui.events", "QKeyEvent"),
    "QMouseEvent": ("..gui.events", "QMouseEvent"),
    "QWheelEvent": ("..gui.events", "QWheelEvent"), "Signal": ".object",
    "SignalConnection": ".object", "QSignalBlocker": ".object",
    "QMetaObject": ".object", "QCoreApplication": ".application", "QEventLoop": ".event_loop",
    "QTimer": ".timer", "QElapsedTimer": ".timer", "QDeadlineTimer": ".timer", "QThread": ".thread", "QRunnable": ".concurrent",
    "QAbstractEventDispatcher": ".dispatcher_protocol", "QEventDispatcher": ".dispatcher",
    "QPerformancePolicy": ".performance_policy",
    "QDebouncer": ".debounce",
    "QFuture": ".concurrent", "QFutureWatcher": ".concurrent",
    "QThreadPool": ".concurrent", "QtConcurrent": ".concurrent",
    "QProcess": ".process", "QSocketNotifier": ".socket_notifier", "QInputTarget": ".input", "QItemInputBinding": ".input", "QGlobalInputBinding": ".input",
    "QModelIndex": ".item_model", "QPersistentModelIndex": ".item_model",
    "QAbstractItemModel": ".item_model", "QAbstractTableModel": ".item_model",
    "QAbstractListModel": ".item_model", "QItemSelectionRange": ".item_model",
    "QItemSelection": ".item_model", "QItemSelectionModel": ".item_model",
}
__all__ = list(_EXPORTS)
def __getattr__(name): return resolve(globals(), __name__, _EXPORTS, name)
def __dir__(): return namespace_dir(globals(), _EXPORTS)
