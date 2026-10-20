"""Prevent a swallowed popup release from poisoning the next Explorer click."""
from unittest.mock import MagicMock

import pytest

from WinUx.ui.components import explorer_pointer_dispatch as pointer


def _view():
    view = MagicMock()
    values = {
        "_suppress_next_left_release": False,
        "_rename_active": False,
        "_rename_schedule_serial": 0,
        "_last_click_index": None,
        "_rubber_ctrl": False,
        "_rubber_shift": False,
        "_header_gesture": False,
        "_resize_key": None,
        "_has_focus": True,
        "_item_drag_active": False,
        "_rubber_active": False,
        "_mouse_down": False,
    }
    for name, value in values.items():
        setattr(view, name, value)
    calls = {
        "_context_menu_is_visible": False,
        "_mouse_in_pinned_row": False,
        "_mouse_in_body": True,
        "_header_mouse_position": (False, 0),
        "_body_local_pos": (10, 15),
        "_claim_pointer_gesture": True,
        "_row_at_mouse": 2,
        "_body_point_is_on_name": False,
    }
    for name, value in calls.items():
        getattr(view, name).return_value = value
    return view


@pytest.mark.parametrize("blocked_by", ["surface", "modal", "overlay", "menu"])
def test_new_valid_press_clears_previous_swallowed_release(monkeypatch, blocked_by):
    view = _view()
    state = {"surface": False, "modal": False, "overlay": False}
    monkeypatch.setattr(pointer, "pointer_input_is_blocked", lambda _view: state["surface"])
    monkeypatch.setattr(pointer, "_modal_input_is_blocked", lambda: state["modal"])
    monkeypatch.setattr(pointer, "_overlay_window_owns_input", lambda: state["overlay"])

    if blocked_by == "menu":
        view._context_menu_is_visible.return_value = True
        view._mouse_inside_context_menus.return_value = True
    else:
        state[blocked_by] = True

    # The first press belongs to a foreground surface; its release may be
    # delivered to the dialog/OS rather than to the Explorer input target.
    pointer.ExplorerPointerDispatchMixin._on_left_down(view)
    assert view._suppress_next_left_release is True
    assert view._mouse_down is False
    view._select_index.assert_not_called()

    # The foreground closes or releases the pointer without an Explorer mouse-up.
    state.update(surface=False, modal=False, overlay=False)
    view._context_menu_is_visible.return_value = False
    pointer.ExplorerPointerDispatchMixin._on_left_down(view)
    assert view._suppress_next_left_release is False
    assert view._pending_click_index == 2
    pointer.ExplorerPointerDispatchMixin._on_left_release_impl(view)
    view._select_index.assert_called_once_with(2)


def test_blocked_press_never_selects_underlying_file(monkeypatch):
    view = _view()
    monkeypatch.setattr(pointer, "pointer_input_is_blocked", lambda _view: True)
    monkeypatch.setattr(pointer, "_modal_input_is_blocked", lambda: False)
    monkeypatch.setattr(pointer, "_overlay_window_owns_input", lambda: False)
    pointer.ExplorerPointerDispatchMixin._on_left_down(view)
    assert view._suppress_next_left_release is True
    assert view._pending_click_index is None
    # A matching release in the same blocked gesture must remain consumed.
    pointer.ExplorerPointerDispatchMixin._on_left_release_impl(view)
    view._select_index.assert_not_called()
    assert view._suppress_next_left_release is False
