from types import SimpleNamespace
from pathlib import Path

from WinUx.ui.components.explorer_hit_testing import ExplorerHitTestingMixin


class _View(ExplorerHitTestingMixin):
    ROW_HEIGHT = 24
    ROW_SPACING = 2

    def __init__(self):
        self.items = [SimpleNamespace(name='alpha.txt')]

    def _column_geometry(self):
        return {
            'name': (0.0, 200.0),
            'date': (200.0, 160.0),
            'type': (360.0, 100.0),
        }

    def _body_point_is_on_name(self, index, body_pos):
        x, _y = body_pos
        return 24.0 <= float(x) <= 92.0


def test_item_drag_handle_is_limited_to_icon_or_visible_filename():
    view = _View()
    # icon
    assert view._body_point_is_on_item_drag_handle(0, (8.0, 12.0)) is True
    # visible label
    assert view._body_point_is_on_item_drag_handle(0, (60.0, 12.0)) is True
    # whitespace in Name column should remain available for rubber-band
    assert view._body_point_is_on_item_drag_handle(0, (150.0, 12.0)) is False
    # non-Name cells should remain available for rubber-band
    assert view._body_point_is_on_item_drag_handle(0, (250.0, 12.0)) is False


def test_row_visual_spacing_is_a_rubberband_origin_not_a_drag_handle():
    view = _View()
    assert view._body_point_is_on_item_drag_handle(0, (60.0, 0.5)) is False
    assert view._body_point_is_on_item_drag_handle(0, (60.0, 23.5)) is False
    assert view._body_point_is_on_item_drag_handle(0, (60.0, 12.0)) is True


def test_pointer_dispatch_uses_content_hit_for_drag_vs_rubberband():
    root = Path(__file__).resolve().parents[1]
    source = (root / 'WinUx' / 'ui' / 'components' / 'explorer_pointer_dispatch.py').read_text(encoding='utf-8')
    assert 'self._body_point_is_on_item_drag_handle(idx, body_pos)' in source
    assert 'if self._drag_origin_on_item:' in source
    assert 'self._start_item_drag()' in source
    assert 'self._start_rubberband()' in source
