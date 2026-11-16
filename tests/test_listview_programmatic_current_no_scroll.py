import unittest
from unittest.mock import Mock

from DearUIQt.modelview.base import QAbstractItemView


class _Backend:
    def __init__(self):
        self.focus_item = Mock()


class _State:
    def __init__(self):
        self._key_index = {'old': 0, 'new': 1}
        self.keys = ['old', 'new']
        self.selected = {'old'}
        self.current = 'old'
        self.anchor = 'old'

    def select(self, key, selected=True, **kwargs):
        before = set(self.selected)
        if selected:
            self.selected = {key}
        self.current = key
        self.anchor = key
        return self.selected != before


class _View:
    setCurrentKey = QAbstractItemView.setCurrentKey

    def __init__(self):
        self.backend = _Backend()
        self._state = _State()
        self.items = {'old': 'native-old', 'new': 'native-new'}
        self.current = 'old'
        self.selected = self._state.selected
        self.currentChanged = Mock()
        self.selectionChanged = Mock()
        self._focus_current = Mock()
        self._set_view_focus = Mock()
        self._sync_selection_visuals = Mock()
        self._sync_model_selection = Mock()


class ProgrammaticCurrentDoesNotScrollTests(unittest.TestCase):
    def test_default_set_current_does_not_focus_native_row(self):
        view = _View()
        self.assertTrue(view.setCurrentKey('new', select=True))
        view._focus_current.assert_not_called()
        view._set_view_focus.assert_called_once_with(True)
        view.backend.focus_item.assert_not_called()

    def test_explicit_focus_still_supported(self):
        view = _View()
        self.assertTrue(view.setCurrentKey('new', select=True, focus=True, ensure_visible=True))
        view._set_view_focus.assert_called_once_with(True)
        view._focus_current.assert_called_once_with()


if __name__ == '__main__':
    unittest.main()
