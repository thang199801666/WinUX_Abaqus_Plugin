"""Shared QDialog buttons click once even when native activation is missing."""
from collections import deque
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from DearUIQt.core import QObject, QEvent, QMouseEvent, Qt, Signal
from DearUIQt.core.application import QApplication
from DearUIQt.dialogs.qt_dialog import QtDialog
from DearUIQt.widgets.buttons import QPushButton


class DialogButtonPointerTests(unittest.TestCase):
    def setUp(self):
        self.queue = deque()
        self.after = lambda delay, callback, *args: self.queue.append((callback, args))
        self.app = QApplication(after=self.after)
        self.addCleanup(self.app.delete)
        self.app._pointer_bridge_installed = True
        self.dialog = object.__new__(QtDialog)
        QObject.__init__(self.dialog, after=self.after)
        self.dialog.tag = 1
        self.dialog._closed = False
        self.dialog.winfo_exists = lambda: True
        self.dialog.isVisible = lambda: True
        self.dialog._button_pointer_target = None
        self.button = object.__new__(QPushButton)
        QObject.__init__(self.button, parent=self.dialog, after=self.after)
        self.button.tag = 2
        self.button._ui_thread = threading.get_ident()
        self.button._properties = {"enabled": True}
        self.button._effective_visible = True
        self.button._updates = None
        self.button._default_action = None
        self.button._checkable = self.button._checked = False
        self.button._dialog_pointer_routing = True
        self.button._pointer_pressed = False
        self.button._native_pointer_suppressed = False
        self.button._pointer_generation = 0
        self.button._refresh_style = Mock()
        self.button.clicked, self.button.toggled = Signal(), Signal()
        self.clicked = Mock()
        self.button.clicked.connect(self.clicked)
        self.dialog._control_wrappers = {2: self.button}
        self.app._register_modal(self.dialog)
        self.backend = SimpleNamespace(
            get_item_rect_min=lambda tag: (100, 200),
            get_item_rect_size=lambda tag: (82, 26),
            get_item_state=lambda tag: {"visible": True})
        context = patch("DearUIQt.dialogs.qt_dialog.dpg", self.backend)
        context.start()
        self.addCleanup(context.stop)

    def pointer(self, kind, point=(130, 210), button=Qt.LeftButton):
        return self.app.dispatchPointerEvent(QMouseEvent(
            kind, point, button=button,
            buttons=button if kind == QEvent.MouseButtonPress else Qt.NoButton))

    def drain(self):
        while self.queue:
            callback, args = self.queue.popleft()
            callback(*args)

    def test_first_press_works_when_dpg_visible_state_lags_first_render(self):
        # The button has valid hit geometry while ImGui's state still records
        # the previous hidden frame.
        self.backend.get_item_state = lambda tag: {"visible": False}
        self.backend.is_item_shown = lambda tag: True
        self.assertTrue(self.pointer(QEvent.MouseButtonPress))
        self.assertTrue(self.pointer(QEvent.MouseButtonRelease))
        self.drain()
        self.clicked.assert_called_once_with()

    def test_first_press_works_when_dpg_visible_state_is_not_populated(self):
        self.backend.get_item_state = lambda tag: {}
        self.backend.is_item_shown = lambda tag: True
        self.assertTrue(self.pointer(QEvent.MouseButtonPress))
        self.assertTrue(self.pointer(QEvent.MouseButtonRelease))
        self.drain()
        self.clicked.assert_called_once_with()

    def test_explicitly_hidden_button_stays_unclickable_during_show_transaction(self):
        self.backend.get_item_state = lambda tag: {"visible": False}
        self.backend.is_item_shown = lambda tag: False
        self.pointer(QEvent.MouseButtonPress)
        self.pointer(QEvent.MouseButtonRelease)
        self.drain()
        self.clicked.assert_not_called()

    def test_first_real_press_release_does_not_require_native_callback(self):
        self.assertTrue(self.pointer(QEvent.MouseButtonPress))
        self.clicked.assert_not_called()
        self.assertTrue(self.pointer(QEvent.MouseButtonRelease))
        self.drain()
        self.clicked.assert_called_once_with()

    def test_native_before_release_does_not_duplicate_click(self):
        self.pointer(QEvent.MouseButtonPress)
        self.button._clicked(2, None, None)
        self.pointer(QEvent.MouseButtonRelease)
        self.drain()
        self.clicked.assert_called_once()

    def test_native_after_release_does_not_duplicate_click(self):
        self.pointer(QEvent.MouseButtonPress)
        self.pointer(QEvent.MouseButtonRelease)
        self.button._clicked(2, None, None)
        self.drain()
        self.clicked.assert_called_once()

    def test_native_before_both_bridge_events_does_not_duplicate_click(self):
        self.button._clicked(2, None, None)
        self.pointer(QEvent.MouseButtonPress)
        self.pointer(QEvent.MouseButtonRelease)
        self.drain()
        self.clicked.assert_called_once()

    def test_repeated_clicks_each_emit_exactly_once(self):
        for _ in range(3):
            self.pointer(QEvent.MouseButtonPress)
            self.pointer(QEvent.MouseButtonRelease)
            self.button._clicked(2, None, None)
            self.drain()
        self.assertEqual(self.clicked.call_count, 3)

    def test_keyboard_native_fallback_still_works_after_pointer_batch(self):
        self.pointer(QEvent.MouseButtonPress)
        self.pointer(QEvent.MouseButtonRelease)
        self.drain()
        self.button._clicked(2, None, None)
        self.drain()
        self.assertEqual(self.clicked.call_count, 2)

    def test_programmatic_click_remains_synchronous(self):
        self.assertTrue(self.button.click())
        self.clicked.assert_called_once()

    def test_checkable_button_toggles_once_not_twice(self):
        self.button._checkable = True
        self.pointer(QEvent.MouseButtonPress)
        self.pointer(QEvent.MouseButtonRelease)
        self.button._clicked(2, True, None)
        self.drain()
        self.assertTrue(self.button._checked)
        self.clicked.assert_called_once()

    def test_release_outside_cancels_click_and_native_fallback(self):
        self.pointer(QEvent.MouseButtonPress)
        self.pointer(QEvent.MouseButtonRelease, (10, 10))
        self.button._clicked(2, None, None)
        self.drain()
        self.clicked.assert_not_called()

    def test_press_outside_then_release_inside_does_not_click(self):
        self.pointer(QEvent.MouseButtonPress, (10, 10))
        self.pointer(QEvent.MouseButtonRelease)
        self.drain()
        self.clicked.assert_not_called()

    def test_disabled_and_hidden_buttons_cannot_click(self):
        self.button._properties["enabled"] = False
        self.pointer(QEvent.MouseButtonPress)
        self.pointer(QEvent.MouseButtonRelease)
        self.button._properties["enabled"] = True
        self.button._effective_visible = False
        self.pointer(QEvent.MouseButtonPress)
        self.pointer(QEvent.MouseButtonRelease)
        self.drain()
        self.clicked.assert_not_called()

    def test_right_click_does_not_activate_button(self):
        self.pointer(QEvent.MouseButtonPress, button=Qt.RightButton)
        self.pointer(QEvent.MouseButtonRelease, button=Qt.RightButton)
        self.drain()
        self.clicked.assert_not_called()

    def test_hide_during_press_cancels_pending_click(self):
        self.pointer(QEvent.MouseButtonPress)
        self.dialog.event(QEvent(QEvent.Hide))
        self.pointer(QEvent.MouseButtonRelease)
        self.drain()
        self.clicked.assert_not_called()

    def test_popup_prevents_dialog_button_click_through(self):
        popup = QObject()
        self.app._register_popup(popup)
        self.pointer(QEvent.MouseButtonPress)
        self.pointer(QEvent.MouseButtonRelease)
        self.drain()
        self.clicked.assert_not_called()

    def test_modeless_dialog_uses_registered_pointer_target(self):
        self.app._unregister_modal(self.dialog)
        self.dialog._native_window_backend = SimpleNamespace(containsGlobalPoint=lambda *_: True)
        self.app.registerPointerTarget(self.dialog)
        self.pointer(QEvent.MouseButtonPress)
        self.pointer(QEvent.MouseButtonRelease)
        self.drain()
        self.clicked.assert_called_once()
