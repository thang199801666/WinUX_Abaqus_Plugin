from pathlib import Path
from unittest.mock import Mock

from WinUx.ui import Qt, QObject, Signal, QEvent, QWidget, QVBoxLayout, QMainWindow


class _Filter(QObject):
    def __init__(self):
        super().__init__()
        self.events = []

    def eventFilter(self, watched, event):
        self.events.append((watched, event.type(), dict(event.payload)))
        return event.type() == QEvent.User


class _CloseVetoWidget(QWidget):
    def closeEvent(self, event):
        event.ignore()


def _backend():
    backend = Mock()
    backend.add_group.side_effect = iter(range(100, 200))
    backend.add_window.side_effect = iter(range(1, 50))
    backend.add_child_window.side_effect = iter(range(200, 300))
    backend.get_item_parent.return_value = 900
    backend.get_item_configuration.return_value = {"show": True, "enabled": True}
    backend.does_item_exist.return_value = True
    return backend



def test_signal_connect_accepts_qt_connection_types():
    direct_receiver = _Filter()
    direct_receiver.hit = []
    signal = Signal()
    signal.connect(lambda value: direct_receiver.hit.append(value), Qt.DirectConnection)
    signal.emit(4)
    assert direct_receiver.hit == [4]

    queued_calls = []
    receiver = QObject(after=lambda delay, callback, *args: queued_calls.append((callback, args)))
    values = []
    signal2 = Signal()
    signal2.connect(lambda value: values.append(value), Qt.QueuedConnection, receiver=receiver)
    signal2.emit(9)
    assert values == []
    callback, args = queued_calls.pop()
    callback(*args)
    assert values == [9]


def test_qobject_event_filters_are_ordered_removable_and_can_consume_events():
    watched = QObject()
    first, second = _Filter(), _Filter()
    watched.installEventFilter(first)
    watched.installEventFilter(second)
    assert watched.sendEvent(QEvent(QEvent.User, value=3)) is True
    assert second.events[-1][2]["value"] == 3
    assert first.events == []  # reverse installation order, consumed by second
    assert watched.removeEventFilter(second) is True
    assert watched.sendEvent(QEvent(QEvent.Show)) is False
    assert first.events[-1][1] == QEvent.Show



def test_deleted_event_filter_detaches_immediately_from_watched_object():
    watched = QObject()
    filter_object = _Filter()
    watched.installEventFilter(filter_object)
    assert watched._event_filters == [filter_object]
    filter_object.delete()
    assert watched._event_filters == []
    assert watched.sendEvent(QEvent(QEvent.Show)) is False


def test_qwidget_set_layout_transfers_native_and_qobject_ownership():
    backend = _backend()
    widget = QWidget(10, backend=backend)
    layout = QVBoxLayout(parent=20, backend=backend)
    assert widget.setLayout(layout) is layout
    assert widget.layout() is layout
    assert layout.parent is widget
    backend.move_item.assert_called_with(layout.tag, parent=widget.tag)
    widget.delete()
    assert layout._deleted


def test_qwidget_close_event_can_veto_hide():
    backend = _backend()
    widget = _CloseVetoWidget(10, backend=backend)
    assert widget.close() is False
    assert not any(call.kwargs.get("show") is False for call in backend.configure_item.call_args_list)


def test_qmainwindow_owns_one_central_widget():
    backend = _backend()
    window = QMainWindow("WinUx", backend=backend)
    central = QWidget(77, backend=backend)
    assert window.setCentralWidget(central) is central
    assert window.centralWidget() is central
    assert central.parent is window
    backend.move_item.assert_called_with(central.tag, parent=window.tag)
    window.delete()
    assert central._deleted


def test_qdialog_facade_and_framework_version_are_exported():
    import DearUIQt

    root = Path(__file__).resolve().parents[1]
    package = (root / "DearUIQt/__init__.py").read_text(encoding="utf-8")
    dialogs = (root / "DearUIQt/dialogs/qt_dialog.py").read_text(encoding="utf-8")
    assert tuple(map(int, DearUIQt.__version__.split("."))) >= (1, 2, 0)
    assert '"QDialog": ".widgets"' in package
    assert "class QtDialog(DialogBase, QObject):" in dialogs
    assert "QDialog = QtDialog" in dialogs
    for token in ("def setLayout(self, layout):", "def close(self):", "def delete(self):"):
        assert token in dialogs
