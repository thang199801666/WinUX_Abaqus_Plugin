"""Regression: a resized/small Explorer viewport must still open its QMenu.

The physical screen hit can remain correct while renderer/client coordinates
lag one frame after a native window resize.  Context-menu dispatch must not use
that stale client mapping as a second mandatory gate.
"""
from types import SimpleNamespace
from unittest.mock import patch

from WinUx.ui.components.explorer.pointer_dispatch import ExplorerPointerDispatchMixin


class _FakeExplorer(SimpleNamespace):
    def _hide_item_tooltips(self):
        pass

    def _context_menu_is_visible(self):
        return False

    def _mouse_inside_context_menus(self):
        return False

    def _hide_context_menus(self, **_kwargs):
        pass

    def _clear_hover(self):
        pass

    def _header_mouse_position(self):
        return False, 0.0

    def _show_header_context_menu(self):
        raise AssertionError('header menu should not open')

    def _mouse_in_body(self):
        return True

    def _set_keyboard_focus(self, _focused):
        self._has_focus = True

    def _physical_pointer_position(self):
        return 740.0, 510.0

    def _body_local_pos_from_screen(self, point=None):
        assert point == (740.0, 510.0)
        return 42.0, 31.0

    def _body_local_pos(self, point=None):
        # Simulate the stale primary-client mapping seen immediately after the
        # application window is made small. The old code returned here and the
        # context menu never reached QMenu.popupGlobal().
        return None

    def _row_at_mouse(self):
        return None

    def clear_selection(self):
        self.selected.clear()

    def get_selected(self):
        return []

    def _hide_context_submenus(self):
        pass

    def _show_item_context_menu(self):
        self.menu_opened += 1
        return True

    def _set_context_keyboard_id(self, _item_id):
        pass


def test_small_resized_viewport_uses_physical_pointer_for_context_menu_gate():
    view = _FakeExplorer(
        _rename_active=False,
        _has_focus=True,
        _current_index=3,
        _context_item_index=3,
        selected={3},
        items=['row'],
        on_context_menu_open=None,
        menu_opened=0,
    )
    with patch('WinUx.ui.components.explorer.pointer_dispatch.pointer_input_is_blocked',
               return_value=False), \
         patch('WinUx.ui.components.explorer.pointer_dispatch._overlay_window_owns_input',
               return_value=False):
        ExplorerPointerDispatchMixin._on_right_click(view)

    assert view.menu_opened == 1
    assert view._context_item_index is None
