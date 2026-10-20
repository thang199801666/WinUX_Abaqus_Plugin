"""Qt-style queued layout requests and idempotent retained properties."""
from collections import deque
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import WinUx  # Configure the bundled backend for Abaqus Python test runs.
from DearUIQt.dialogs.qt_dialog import QtDialog
from DearUIQt.dispatch import LatestCallQueue
from DearUIQt.qt.core import QObject, QEvent
from DearUIQt.qt.widget import QWidget


class QueuedLayoutTests(unittest.TestCase):
    def setUp(self):
        self.pending = deque()
        self.after = lambda delay, callback, *args: self.pending.append((callback, args))
        self.dialog = object.__new__(QtDialog)
        QObject.__init__(self.dialog, after=self.after)
        self.dialog.view = SimpleNamespace(after=self.after)
        self.dialog.tag = 42
        self.dialog._closed = False
        self.dialog._ui_thread = threading.get_ident()
        self.dialog._latest_updates = LatestCallQueue(self.after)
        self.dialog._apply_layout = Mock()
        self.dialog.changeEvent = Mock()
        self.exists = patch("DearUIQt.dialogs.qt_dialog.dpg.does_item_exist", return_value=True)
        self.exists.start()
        self.addCleanup(self.exists.stop)

    def pump(self):
        while self.pending:
            callback, args = self.pending.popleft()
            callback(*args)

    def test_resize_burst_posts_one_layout_request_not_one_reflow_per_event(self):
        for _ in range(1000):
            self.dialog._on_native_resize()
        self.assertEqual(self.dialog._apply_layout.call_count, 0)
        self.assertEqual(len(self.pending), 1)
        self.pump()
        self.dialog._apply_layout.assert_called_once_with()
        self.assertEqual(self.dialog.changeEvent.call_args.args[0].type(), QEvent.LayoutRequest)

    def test_worker_requests_are_marshaled_and_coalesced_to_ui_owner(self):
        worker = threading.Thread(target=lambda: [self.dialog.updateGeometry() for _ in range(100)])
        worker.start()
        worker.join(timeout=1)
        self.assertFalse(worker.is_alive())
        self.dialog._apply_layout.assert_not_called()
        self.assertEqual(len(self.pending), 1)
        self.pump()
        self.dialog._apply_layout.assert_called_once_with()

    def test_closed_dialog_ignores_previously_queued_layout(self):
        self.dialog.updateGeometry()
        self.dialog._closed = True
        self.pump()
        self.dialog._apply_layout.assert_not_called()
        self.assertFalse(self.dialog.updateGeometry())

    def test_disposed_queue_drops_layout_and_releases_callback_references(self):
        self.dialog.updateGeometry()
        self.dialog._latest_updates.close()
        self.pump()
        self.dialog._apply_layout.assert_not_called()

    def test_explicit_layout_event_is_synchronous_and_filters_can_consume_it(self):
        self.dialog.sendEvent(QEvent(QEvent.LayoutRequest))
        self.dialog._apply_layout.assert_called_once_with()
        self.dialog._apply_layout.reset_mock()
        filter_object = QObject()
        filter_object.eventFilter = lambda watched, event: event.type() == QEvent.LayoutRequest
        self.dialog.installEventFilter(filter_object)
        self.dialog.updateGeometry()
        self.pump()
        self.dialog._apply_layout.assert_not_called()

    def test_later_resize_can_request_a_new_pass(self):
        self.dialog._on_native_resize()
        self.pump()
        self.dialog._on_native_resize()
        self.pump()
        self.assertEqual(self.dialog._apply_layout.call_count, 2)

    def test_explicit_layout_event_cannot_touch_widgets_from_worker_thread(self):
        errors = []
        def worker():
            try:
                self.dialog.sendEvent(QEvent(QEvent.LayoutRequest))
            except Exception as exc:
                errors.append(exc)
        thread = threading.Thread(target=worker)
        thread.start()
        thread.join(timeout=1)
        self.assertFalse(thread.is_alive())
        self.assertEqual(len(errors), 1)
        self.assertIsInstance(errors[0], RuntimeError)
        self.assertEqual(self.dialog._apply_layout.call_count, 0)


class RetainedPropertyTests(unittest.TestCase):
    def test_repeated_enabled_value_does_not_refresh_style(self):
        backend = Mock()
        widget = QWidget(1, backend=backend)
        widget._properties["enabled"] = True
        widget._refresh_style = Mock()
        for _ in range(1000):
            widget.setEnabled(True)
        backend.configure_item.assert_not_called()
        self.assertEqual(widget._refresh_style.call_count, 0)

    def test_real_enabled_transition_updates_backend_style_and_event_once(self):
        backend = Mock()
        widget = QWidget(1, backend=backend)
        widget._properties["enabled"] = True
        widget._refresh_style = Mock()
        widget.changeEvent = Mock()
        for _ in range(100):
            widget.setEnabled(False)
        backend.configure_item.assert_called_once_with(1, enabled=False)
        widget._refresh_style.assert_called_once_with()
        self.assertEqual(widget.changeEvent.call_count, 1)

    def test_uncached_wrapped_widget_still_configures_and_styles_on_first_set(self):
        backend = Mock()
        widget = QWidget(1, backend=backend)
        widget._refresh_style = Mock()
        widget.setEnabled(True)
        backend.configure_item.assert_called_once_with(1, enabled=True)
        widget._refresh_style.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
