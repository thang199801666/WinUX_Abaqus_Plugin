import unittest
from unittest.mock import Mock

from DearUIQt.modelview.policy import QItemViewPolicyMixin


class _Backend:
    def __init__(self, *, view=(0, 100, 300, 200), row=(0, 180, 300, 28), scroll=40):
        self._view = view
        self._row = row
        self._scroll = float(scroll)
        self.set_y_scroll = Mock(side_effect=self._set_scroll)
        self.focus_item = Mock()

    def _set_scroll(self, tag, value):
        self._scroll = float(value)

    def get_item_rect_min(self, tag):
        rect = self._view if tag == 'view' else self._row
        return rect[0], rect[1]

    def get_item_rect_size(self, tag):
        rect = self._view if tag == 'view' else self._row
        return rect[2], rect[3]

    def get_y_scroll(self, tag):
        return self._scroll


class _View(QItemViewPolicyMixin):
    def __init__(self, backend):
        self.backend = backend
        self.tag = 'view'


class GeometryScrollTests(unittest.TestCase):
    def test_visible_row_does_not_scroll_or_focus(self):
        backend = _Backend(row=(0, 180, 300, 28))
        view = _View(backend)
        self.assertFalse(view._ensure_native_visible('row'))
        backend.set_y_scroll.assert_not_called()
        backend.focus_item.assert_not_called()

    def test_row_below_view_scrolls_only_required_delta(self):
        backend = _Backend(row=(0, 330, 300, 28), scroll=40)
        view = _View(backend)
        self.assertTrue(view._ensure_native_visible('row'))
        # viewport bottom=300, row bottom=358 => +58 px
        backend.set_y_scroll.assert_called_once_with('view', 98.0)
        backend.focus_item.assert_not_called()

    def test_row_above_view_scrolls_up_without_focus(self):
        backend = _Backend(row=(0, 70, 300, 28), scroll=40)
        view = _View(backend)
        self.assertTrue(view._ensure_native_visible('row'))
        backend.set_y_scroll.assert_called_once_with('view', 10.0)
        backend.focus_item.assert_not_called()

    def test_center_hint_uses_geometry_not_native_focus(self):
        backend = _Backend(row=(0, 330, 300, 28), scroll=40)
        view = _View(backend)
        self.assertTrue(view._ensure_native_visible('row', hint=view.PositionAtCenter))
        # row center=344, viewport center=200 => +144
        backend.set_y_scroll.assert_called_once_with('view', 184.0)
        backend.focus_item.assert_not_called()


if __name__ == '__main__':
    unittest.main()
