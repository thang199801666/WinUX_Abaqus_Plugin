"""Exercise Explorer clicks against the real shared selection model."""
import unittest
from unittest.mock import Mock

from DearUIQt.modelview import QtItemViewState
from WinUx.ui.components.explorer_pointer_dispatch import ExplorerPointerDispatchMixin
from WinUx.ui.components.explorer_selection import ExplorerSelectionMixin


class SelectionView(ExplorerSelectionMixin, ExplorerPointerDispatchMixin):
    def __init__(self, single=False):
        self.items = list("abcde")
        self.single_selection = single
        self.selected = set()
        self._current_index = None
        self.last_clicked_index = None
        self._last_click_index = None
        self._last_click_time = 0.0
        self._qt_selection = QtItemViewState(multiple=not single)
        self._pointer_ctrl_down = Mock(return_value=False)
        self._pointer_shift_down = Mock(return_value=False)
        self._update_selection_draws = Mock()
        self._update_status_bar = Mock()
        self.on_selection_change = Mock()
        self.activate_item = Mock()


class ExplorerSelectionSyncTests(unittest.TestCase):
    def test_plain_click_selects_and_notifies(self):
        view = SelectionView()
        view._select_index(2)
        self.assertEqual(view.selected, {2})
        self.assertEqual(view._current_index, 2)
        self.assertEqual(view.last_clicked_index, 2)
        view.on_selection_change.assert_called_once_with(["c"])

    def test_ctrl_click_adds_and_toggles(self):
        view = SelectionView()
        view._select_index(1)
        view._pointer_ctrl_down.return_value = True
        view._select_index(3)
        self.assertEqual(view.selected, {1, 3})
        view._select_index(1)
        self.assertEqual(view.selected, {3})

    def test_shift_click_selects_range_from_anchor(self):
        view = SelectionView()
        view._select_index(1)
        view._pointer_shift_down.return_value = True
        view._select_index(4)
        self.assertEqual(view.selected, {1, 2, 3, 4})
        self.assertEqual(view.last_clicked_index, 1)

    def test_refresh_rebuilds_lookup_for_new_rows(self):
        view = SelectionView()
        view._select_index(0)
        view.items.extend(["f", "g"])
        view._select_index(6)
        self.assertEqual(view.get_selected(), ["g"])
        view.items = ["a"]
        view._sync_qt_selection_from_fields()
        self.assertFalse(view._qt_selection.select(6))
        view._select_index(0)
        self.assertEqual(view.get_selected(), ["a"])

    def test_single_selection_ignores_modifiers(self):
        view = SelectionView(single=True)
        view._select_index(1)
        view._pointer_ctrl_down.return_value = True
        view._pointer_shift_down.return_value = True
        view._select_index(3)
        self.assertEqual(view.selected, {3})

    def test_double_click_selects_and_activates(self):
        view = SelectionView()
        view._select_index(2)
        self.assertTrue(view._select_index(2))
        self.assertEqual(view.selected, {2})
        view.activate_item.assert_called_once_with(2)


def test_sync_does_not_rebuild_row_key_lookup_when_item_count_is_unchanged():
    view = SelectionView()
    view.items = list(range(5000))
    view._sync_qt_selection_from_fields()

    original_replace = view._qt_selection.replace
    calls = []

    def guarded_replace(keys):
        calls.append(True)
        return original_replace(keys)

    view._qt_selection.replace = guarded_replace
    view.selected = {10, 20, 30}
    view._current_index = 30
    view.last_clicked_index = 10
    view._sync_qt_selection_from_fields()

    assert calls == []
    assert view._qt_selection.selected == {10, 20, 30}
    assert view._qt_selection.current == 30
    assert view._qt_selection.anchor == 10
