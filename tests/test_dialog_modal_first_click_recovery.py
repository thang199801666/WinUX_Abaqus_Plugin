"""Regression coverage for lost mouse-up and delayed dialog initial focus."""

from types import SimpleNamespace
from unittest.mock import Mock, patch

from DearUIQt.qt import QApplication, QEvent, QMouseEvent, QInputTarget, Qt
from DearUIQt.dialogs.qt_dialog import QtDialog


def mouse(event_type, x, *, button=Qt.LeftButton, buttons=None):
    if buttons is None:
        buttons = button if event_type == QEvent.MouseButtonPress else Qt.NoButton
    return QMouseEvent(event_type, (x, 10), button=button, buttons=buttons)


def test_modal_steals_old_owner_grab_before_first_click():
    app = QApplication(after=lambda *_args: None)
    events = []
    owner = QInputTarget(
        parent=app, hit_test=lambda _pos: True,
        pointer_handler=lambda event: events.append(("owner", event.type())) or True)
    dialog = QInputTarget(
        parent=app, hit_test=lambda _pos: True,
        pointer_handler=lambda event: events.append(("dialog", event.type())) or True)
    try:
        # Opening a modal from a button press is common; the originating view
        # may not receive the OS mouse-up after HWND activation switches.
        app.unregisterPointerTarget(dialog)
        assert app.dispatchPointerEvent(mouse(QEvent.MouseButtonPress, 10))
        assert app.mouseGrabberObject() is owner

        assert app._register_modal(dialog)
        assert app.mouseGrabberObject() is None
        assert app.dispatchPointerEvent(mouse(QEvent.MouseButtonPress, 10))
        assert app.dispatchPointerEvent(mouse(QEvent.MouseButtonRelease, 10))
        assert ("dialog", QEvent.MouseButtonPress) in events
        assert ("dialog", QEvent.MouseButtonRelease) in events
        assert events.count(("owner", QEvent.MouseButtonPress)) == 1
    finally:
        dialog.delete()
        owner.delete()
        app.delete()


def test_second_left_press_recovers_orphaned_implicit_grab():
    app = QApplication(after=lambda *_args: None)
    events = []
    background = QInputTarget(
        parent=app, hit_test=lambda pos: pos[0] < 50,
        pointer_handler=lambda event: events.append(("background", event.type())) or True)
    foreground = QInputTarget(
        parent=app, hit_test=lambda pos: pos[0] >= 50,
        pointer_handler=lambda event: events.append(("foreground", event.type())) or True)
    try:
        assert app.dispatchPointerEvent(mouse(QEvent.MouseButtonPress, 10))
        assert app.mouseGrabberObject() is background
        # The first release is lost to an external native viewport. A new
        # left-button press is necessarily an independent click, not a drag.
        assert app.dispatchPointerEvent(mouse(QEvent.MouseButtonPress, 90))
        assert app.mouseGrabberObject() is foreground
        assert app.dispatchPointerEvent(mouse(QEvent.MouseButtonRelease, 90))
        assert events.count(("background", QEvent.MouseButtonPress)) == 1
        assert events.count(("foreground", QEvent.MouseButtonPress)) == 1
        assert events.count(("foreground", QEvent.MouseButtonRelease)) == 1
    finally:
        foreground.delete()
        background.delete()
        app.delete()


def test_genuine_chorded_press_preserves_implicit_capture():
    app = QApplication(after=lambda *_args: None)
    events = []
    origin = QInputTarget(
        parent=app, hit_test=lambda pos: pos[0] < 50,
        pointer_handler=lambda event: events.append(("origin", event.type())) or True)
    other = QInputTarget(
        parent=app, hit_test=lambda pos: pos[0] >= 50,
        pointer_handler=lambda event: events.append(("other", event.type())) or True)
    try:
        assert app.dispatchPointerEvent(mouse(QEvent.MouseButtonPress, 10))
        assert app.dispatchPointerEvent(mouse(
            QEvent.MouseButtonPress, 90, button=Qt.RightButton,
            buttons=Qt.LeftButton | Qt.RightButton))
        assert app.mouseGrabberObject() is origin
        assert ("other", QEvent.MouseButtonPress) not in events
        assert app.dispatchPointerEvent(mouse(
            QEvent.MouseButtonRelease, 90, button=Qt.RightButton,
            buttons=Qt.LeftButton))
        assert app.mouseGrabberObject() is origin
        assert app.dispatchPointerEvent(mouse(QEvent.MouseButtonRelease, 90))
        assert app.mouseGrabberObject() is None
    finally:
        other.delete()
        origin.delete()
        app.delete()


def test_pointer_activity_blocks_late_first_present_focus_even_after_mouse_up():
    backend = SimpleNamespace(
        is_item_shown=lambda tag: True,
        is_mouse_button_down=lambda *_: False,
        get_focused_item=lambda: 1,
        focus_item=Mock(),
        mvMouseButton_Left=0, mvMouseButton_Right=1, mvMouseButton_Middle=2)
    dialog = SimpleNamespace(
        tag=1, _initial_pointer_activity=True, winfo_exists=lambda: True,
        _initial_focus_item=2, _focus_order=[2], _default_button=None,
        _item_is_focusable=lambda item: True,
        _item_belongs_to=lambda item, parent: False)
    with patch("DearUIQt.dialogs.qt_dialog.dpg", backend):
        assert QtDialog._focus_initial(dialog) is False
        backend.focus_item.assert_not_called()
        # A new show lease resets the flag and restores normal initial focus.
        dialog._initial_pointer_activity = False
        assert QtDialog._focus_initial(dialog) is True
        backend.focus_item.assert_called_once_with(2)


def test_subclass_initial_focus_is_gated_after_first_pointer_gesture():
    custom_focus = Mock(return_value=True)
    dialog = SimpleNamespace(_initial_pointer_activity=True, _focus_initial=custom_focus)
    assert QtDialog._apply_initial_focus_if_idle(dialog) is False
    custom_focus.assert_not_called()
    dialog._initial_pointer_activity = False
    assert QtDialog._apply_initial_focus_if_idle(dialog) is True
    custom_focus.assert_called_once_with()


def test_deferred_editor_focus_never_steals_later_pointer_click():
    callbacks = []
    backend = SimpleNamespace(
        get_frame_count=lambda: 10,
        set_frame_callback=lambda frame, callback: callbacks.append((frame, callback)))
    focus = Mock()
    dialog = SimpleNamespace(
        _pointer_interaction_serial=0,
        _focus_text_editor_now=focus,
        isVisible=lambda: True)
    with patch("DearUIQt.dialogs.qt_dialog.dpg", backend):
        QtDialog.focus_editor(dialog, 77)
        focus.assert_called_once_with(77)
        assert len(callbacks) == 2
        dialog._pointer_interaction_serial += 1
        for _frame, callback in callbacks:
            callback()
        # Initial programmatic focus was legal; after the physical click,
        # neither of the two queued frame callbacks can override the click.
        focus.assert_called_once_with(77)
