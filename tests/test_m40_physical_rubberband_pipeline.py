from pathlib import Path
import inspect
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import run_winux
run_winux._configure_bundled_dependencies(str(Path(__file__).resolve().parents[1]))

from WinUx.ui.components.explorer.rubber_band import ExplorerRubberBandMixin
from WinUx.ui.components.explorer.pointer_dispatch import ExplorerPointerDispatchMixin


class _Body:
    def __init__(self, vertical_max=0.0, horizontal_max=0.0, scroll_y=0.0):
        self._vmax = vertical_max
        self._hmax = horizontal_max
        self._scroll_y = scroll_y
        self._scroll_x = 0.0
    def verticalScrollMaximum(self): return self._vmax
    def horizontalScrollMaximum(self): return self._hmax
    def verticalScrollValue(self): return self._scroll_y
    def horizontalScrollValue(self): return self._scroll_x
    def setVerticalScrollValue(self, value): self._scroll_y = float(value)


class _Host(ExplorerRubberBandMixin):
    SCROLLBAR_HIT_SIZE = 14
    AUTO_SCROLL_MARGIN = 24
    AUTO_SCROLL_STEP = 20

    def __init__(self):
        self.body_window = 'body'
        self.body_canvas = 'canvas'
        self.body = _Body(vertical_max=300.0, horizontal_max=0.0, scroll_y=40.0)
        self._rubber_start_screen = (530.0, 330.0)
        self.cursor = (650.0, 500.0)

    def _rubber_body_item(self): return self.body
    def _body_screen_viewport_rect(self): return (500.0, 300.0, 800.0, 600.0)
    def _screen_item_rect(self, tag):
        if tag == 'canvas':
            # Canvas is scrolled 40 px upward relative to the visible body.
            return (500.0, 260.0, 786.0, 860.0)
        return None
    def _physical_pointer_position(self): return self.cursor
    def _pointer_position(self):
        raise AssertionError('app/viewport pointer must not drive rubber-band geometry')


class M40PhysicalRubberBandTests(unittest.TestCase):
    def test_content_position_comes_from_physical_cursor_and_painted_canvas(self):
        host = _Host()
        host.cursor = (550.0, 340.0)
        self.assertEqual(host._body_local_pos_clamped(), (50.0, 80.0))

    def test_outside_pointer_clamps_in_physical_screen_space(self):
        host = _Host()
        host.cursor = (900.0, 700.0)
        # Right edge excludes the real vertical scrollbar strip: 800 - 14.
        self.assertEqual(host._body_local_pos_clamped(), (286.0, 340.0))

    def test_overlay_endpoints_use_physical_screen_cursor(self):
        host = _Host()
        host.cursor = (760.0, 550.0)
        self.assertEqual(host._rubber_screen_points(), ((530.0, 330.0), (760.0, 550.0)))

    def test_auto_scroll_uses_physical_screen_cursor(self):
        host = _Host()
        host.cursor = (650.0, 590.0)
        host._auto_scroll_during_rubberband()
        self.assertEqual(host.body.verticalScrollValue(), 60.0)
        host.cursor = (650.0, 305.0)
        host._auto_scroll_during_rubberband()
        self.assertEqual(host.body.verticalScrollValue(), 40.0)

    def test_pointer_dispatch_anchors_rubberband_to_physical_mouse_down(self):
        source = inspect.getsource(ExplorerPointerDispatchMixin._on_left_down)
        self.assertIn('self._mouse_down_physical', source)
        self.assertIn('self._rubber_start_screen = self._mouse_down_physical', source)

    def test_drag_threshold_for_rubberband_no_longer_uses_viewport_pointer(self):
        source = inspect.getsource(ExplorerPointerDispatchMixin._on_left_drag)
        tail = source[source.index('if not self._mouse_down or self._body_screen_viewport_rect() is None:'):]
        self.assertIn('self._physical_pointer_position()', tail)
        self.assertIn('_mouse_down_physical', tail)
        self.assertNotIn('point = self._pointer_position()', tail.split('if not self._drag_started', 1)[0])


if __name__ == '__main__':
    unittest.main(verbosity=2)
