from DearUIQt.qt.item_views import (
    QtItemViewState, QtGridColumn, QtGridRow, QtListItem,
)
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest


def test_selection_model_single_selection_is_qt_like():
    state = QtItemViewState(multiple=False).replace(["a", "b", "c"])
    assert state.current == "a"
    assert state.selected == set()
    state.select("b", selected=False)
    assert state.current == "b"
    assert state.selected == {"b"}


def test_selection_model_extended_ctrl_and_shift():
    state = QtItemViewState(multiple=True).replace([0, 1, 2, 3, 4])
    state.select(1)
    state.select(3, shift=True)
    assert state.selected == {1, 2, 3}
    state.select(2, ctrl=True, selected=False)
    assert state.selected == {1, 3}


def test_selection_model_keyboard_current_and_selection_are_stable():
    state = QtItemViewState(multiple=True).replace(["a", "b", "c", "d"])
    state.select("b")
    key, changed = state.move(1, ctrl=True)
    assert key == "c"
    assert changed
    assert state.current == "c"
    assert state.selected == {"b"}
    key, changed = state.move(1, shift=True)
    assert key == "d"
    assert state.selected == {"b", "c", "d"}


def test_selection_model_preserves_keys_across_refresh():
    state = QtItemViewState(multiple=True).replace(["a", "b", "c"])
    state.select("b")
    state.replace(["b", "c", "d"])
    assert state.selected == {"b"}
    assert state.current == "b"


def test_item_view_value_objects_are_backend_independent():
    column = QtGridColumn("name", "Name", width=120, align="left")
    row = QtGridRow("job-1", ("job-1", "Running"), {"owner": "user"},
                    background=(205, 244, 213, 255))
    item = QtListItem("id", "Visible", {"value": 1})
    assert column.key == "name"
    assert column.width == 120
    assert item.text == "Visible"
    assert item.data == {"value": 1}
    assert row.key == "job-1"
    assert row.data == {"owner": "user"}
    assert row.background == (205, 244, 213, 255)


@pytest.mark.parametrize("current,enabled,row_enabled,expected", [
    ("b", True, True, True), (None, True, True, False),
    ("b", False, True, False), ("b", True, False, False),
])
def test_keyboard_activation_respects_current_and_disabled_state(current, enabled, row_enabled, expected):
    from DearUIQt.qt.item_view_base import _QtAbstractItemView
    view = object.__new__(_QtAbstractItemView)
    view._state = QtItemViewState().replace(["a", "b"])
    view._state.current = current
    view.isEnabled = lambda: enabled
    view.items = {"a": 1, "b": 2}
    view.backend = SimpleNamespace(get_item_configuration=lambda tag: {"enabled": row_enabled})
    view.activated = SimpleNamespace(emit=Mock())
    assert view.activateCurrent() is expected
    if expected:
        view.activated.emit.assert_called_once_with("b")
    else:
        view.activated.emit.assert_not_called()


def test_focused_button_wins_over_a_retained_table_focus_flag():
    from WinUx.dialogs.qt_dialog import QtDialog

    class Button:
        def isEnabled(self):
            return True

        click = Mock()

    dialog = object.__new__(QtDialog)
    dialog.enter_editors = set()
    dialog.active_table = SimpleNamespace(hasFocus=lambda: True, activateCurrent=Mock())
    button = Button()
    dialog._control_wrappers = {42: button}
    with patch("WinUx.dialogs.qt_dialog.QPushButton", Button), \
            patch("WinUx.dialogs.qt_dialog.dpg.get_focused_item", return_value=42):
        dialog.invoke_default()
    button.click.assert_called_once()
    dialog.active_table.activateCurrent.assert_not_called()
