import unittest
from types import SimpleNamespace
from unittest.mock import Mock

from WinUx.components.explorer_keyboard import ExplorerKeyboardController, ExplorerKeyboardInput


def fixture(count=20):
    state = SimpleNamespace(ctrl=False, shift=False, alt=False, overlay=False, blocked=False)
    view = SimpleNamespace(
        items=list(range(count)), selected={2}, last_clicked_index=2, _current_index=2,
        _has_focus=True, _rename_active=False, single_selection=False, ROW_HEIGHT=24,
        body_window="body", _context_menu_is_visible=lambda: False,
        _clear_hover=Mock(), _hide_context_menus=Mock(), cancel_inline_rename=Mock(return_value=False),
        _cancel_current_operation=Mock(), commit_inline_rename=Mock(), activate_item=Mock(),
        _update_selection_draws=Mock(), _update_status_bar=Mock(), on_selection_change=Mock(),
        on_item_menu_action=Mock(), copy_selected=Mock(), cut_selected=Mock(), paste=Mock(),
        begin_inline_rename=Mock(), select_all=Mock(),
    )
    view.get_selected = lambda: [view.items[i] for i in sorted(view.selected) if 0 <= i < len(view.items)]
    backend = Mock()
    backend.get_item_rect_size.return_value = (400, 120)
    backend.get_y_scroll.return_value = 0
    backend.get_y_scroll_max.return_value = 1000
    inputs = ExplorerKeyboardInput(lambda: state.ctrl, lambda: state.shift, lambda: state.alt,
                                   lambda: state.overlay, lambda owner: state.blocked)
    return ExplorerKeyboardController(view, backend, inputs), view, backend, state


class ExplorerKeyboardTests(unittest.TestCase):
    def test_arrow_moves_current_selection_and_notifies_once(self):
        keyboard, view, _, _ = fixture()
        keyboard._on_navigation_key(user_data="down")
        self.assertEqual((view._current_index, view.selected, view.last_clicked_index), (3, {3}, 3))
        view.on_selection_change.assert_called_once_with([3])

    def test_ctrl_arrow_moves_current_without_changing_selection(self):
        keyboard, view, _, state = fixture()
        state.ctrl = True
        keyboard._on_navigation_key(user_data="down")
        self.assertEqual((view._current_index, view.selected, view.last_clicked_index), (3, {2}, 2))
        view.on_selection_change.assert_not_called()

    def test_ctrl_shift_arrow_notifies_range_change(self):
        keyboard, view, _, state = fixture()
        state.ctrl = state.shift = True
        keyboard._on_navigation_key(user_data="down")
        self.assertEqual(view.selected, {2, 3})
        view.on_selection_change.assert_called_once_with([2, 3])

    def test_single_selection_ignores_range_and_ctrl_modifiers(self):
        keyboard, view, _, state = fixture()
        view.single_selection = True
        state.ctrl = state.shift = True
        keyboard._on_navigation_key(user_data="down")
        self.assertEqual(view.selected, {3})

    def test_page_navigation_uses_visible_rows(self):
        keyboard, view, _, _ = fixture()
        keyboard._on_navigation_key(user_data="page_down")
        self.assertEqual(view._current_index, 6)
        keyboard._on_navigation_key(user_data="page_up")
        self.assertEqual(view._current_index, 2)

    def test_home_end_and_bounds(self):
        keyboard, view, _, _ = fixture()
        for command, expected in (("home", 0), ("up", 0), ("end", 19), ("down", 19)):
            keyboard._on_navigation_key(user_data=command)
            self.assertEqual(view._current_index, expected)

    def test_blocked_navigation_does_not_touch_native_scroll(self):
        for flag in ("overlay", "blocked", "alt"):
            keyboard, view, backend, state = fixture()
            setattr(state, flag, True)
            keyboard._on_navigation_key(user_data="down")
            self.assertEqual(view._current_index, 2)
            backend.get_item_rect_size.assert_not_called()

    def test_invalid_removed_indices_do_not_create_invalid_range(self):
        keyboard, view, _, state = fixture(count=3)
        view._current_index, view.last_clicked_index, view.selected = 99, 99, {-1, 99}
        self.assertEqual(keyboard._keyboard_current_index(), 0)
        state.shift = True
        keyboard._apply_keyboard_current(1)
        self.assertEqual(view.selected, {1})

    def test_empty_list_navigation_is_noop(self):
        keyboard, view, _, _ = fixture(count=0)
        keyboard._on_navigation_key(user_data="down")
        view.on_selection_change.assert_not_called()

    def test_space_toggles_current_with_ctrl(self):
        keyboard, view, _, state = fixture()
        state.ctrl = True
        keyboard._on_space_pressed()
        self.assertEqual(view.selected, set())
        keyboard._on_space_pressed()
        self.assertEqual(view.selected, {2})

    def test_enter_selects_and_activates_current(self):
        keyboard, view, _, _ = fixture()
        view._current_index = 5
        keyboard._on_enter_pressed()
        view.activate_item.assert_called_once_with(5)
        view.on_selection_change.assert_called_once_with([5])

    def test_enter_commits_rename_and_escape_prefers_popup(self):
        keyboard, view, _, _ = fixture()
        view._rename_active = True
        keyboard._on_enter_pressed()
        view.commit_inline_rename.assert_called_once()
        view._context_menu_is_visible = lambda: True
        keyboard._on_escape_pressed()
        view._hide_context_menus.assert_called_once()
        view.cancel_inline_rename.assert_not_called()

    def test_escape_cancels_rename_before_other_gestures(self):
        keyboard, view, _, _ = fixture()
        view.cancel_inline_rename.return_value = True
        keyboard._on_escape_pressed()
        view._cancel_current_operation.assert_not_called()
        view.cancel_inline_rename.return_value = False
        keyboard._on_escape_pressed()
        view._cancel_current_operation.assert_called_once()

    def test_clipboard_uses_owner_or_standalone_fallback(self):
        keyboard, view, _, state = fixture()
        state.ctrl = True
        keyboard._on_copy_shortcut()
        view.on_item_menu_action.assert_called_once_with("command:copy", [2])
        view.copy_selected.assert_not_called()
        view.on_item_menu_action = None
        keyboard._on_cut_shortcut()
        keyboard._on_paste_shortcut()
        view.cut_selected.assert_called_once()
        view.paste.assert_called_once()

    def test_shortcut_blocked_by_overlay_and_rename(self):
        keyboard, view, _, state = fixture()
        state.ctrl, state.overlay = True, True
        keyboard._on_copy_shortcut()
        view._clear_hover.assert_called_once()
        state.overlay, view._rename_active = False, True
        keyboard._on_copy_shortcut()
        view.on_item_menu_action.assert_not_called()

    def test_delete_and_edit_require_selection_and_owner(self):
        keyboard, view, _, _ = fixture()
        view.selected = set()
        keyboard._on_delete_shortcut()
        keyboard._on_edit_shortcut()
        view.on_item_menu_action.assert_not_called()
        view.selected = {1}
        keyboard._on_edit_shortcut()
        view.on_item_menu_action.assert_called_once_with("command:edit", [1])

    def test_scrolling_skips_visible_row_and_clamps_target(self):
        keyboard, _, backend, _ = fixture()
        keyboard._ensure_index_visible(2)
        backend.set_y_scroll.assert_not_called()
        keyboard._ensure_index_visible(10)
        backend.set_y_scroll.assert_called_once_with("body", 144.0)

    def test_arrow_does_not_query_unused_page_size(self):
        keyboard, _, backend, _ = fixture()
        keyboard._on_navigation_key(user_data="down")
        backend.get_item_rect_size.assert_called_once_with("body")
