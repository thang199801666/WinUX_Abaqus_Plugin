"""Regression test: a QMenu action must not click the Explorer row below it."""
from __future__ import annotations

import unittest
from unittest.mock import patch

from WinUx.ui.components.explorer_pointer_dispatch import ExplorerPointerDispatchMixin


class _FakeExplorer(ExplorerPointerDispatchMixin):
    def __init__(self):
        self._header_gesture = False
        self._resize_key = None
        self._rubber_active = False
        self._item_drag_active = False
        self._suppress_next_left_release = False
        self._mouse_down = True
        self._pending_click_index = 4
        self.hover_cleared = False
        self.selection_called = False

    def _clear_hover(self):
        self.hover_cleared = True

    def _select_index(self, _index):
        self.selection_called = True
        raise AssertionError("row selection must not run for popup closing release")


class ExplorerContextClickThroughTests(unittest.TestCase):
    def test_popup_release_guard_prevents_underlying_row_selection(self):
        view = _FakeExplorer()
        with patch(
            "WinUx.ui.components.explorer_pointer_dispatch.pointer_input_is_blocked",
            return_value=True,
        ):
            view._on_left_release_impl()
        self.assertFalse(view._mouse_down)
        self.assertIsNone(view._pending_click_index)
        self.assertTrue(view.hover_cleared)
        self.assertFalse(view.selection_called)


if __name__ == "__main__":
    unittest.main()
