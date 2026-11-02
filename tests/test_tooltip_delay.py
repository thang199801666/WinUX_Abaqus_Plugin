"""One app-wide dwell interval, including reused Explorer and Tk tooltips."""
from contextlib import contextmanager
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import run_winux
run_winux._configure_bundled_dependencies(str(ROOT))
from DearUIQt.tooltip import TOOLTIP_DELAY, TooltipHoverDelay
from DearUIQt.widgets import QWidget
from DearUIQt.core import QPoint
from WinUx.ui.components.explorer_rendering import ExplorerRenderingMixin
from WinUx.ui.components.server_notepad_tabs import _ToolTip


class TooltipDelayTests(unittest.TestCase):
    def test_dwell_waits_full_interval_and_stays_ready(self):
        delay = TooltipHoverDelay()
        self.assertFalse(delay.ready('a', now=10))
        self.assertFalse(delay.ready('a', now=10 + TOOLTIP_DELAY - .001))
        self.assertTrue(delay.ready('a', now=10 + TOOLTIP_DELAY))
        self.assertTrue(delay.ready('a', now=12))

    def test_new_target_and_leave_restart_timer(self):
        delay = TooltipHoverDelay()
        delay.ready('a', now=10)
        self.assertTrue(delay.ready('a', now=11))
        self.assertFalse(delay.ready('b', now=11))
        self.assertFalse(delay.ready('b', now=11.1))
        delay.reset()
        self.assertFalse(delay.ready('b', now=15))

    def test_widget_tooltip_has_shared_delay_and_hides_on_activity(self):
        backend = Mock()
        @contextmanager
        def tooltip(*args, **kwargs):
            yield 'tip'
        backend.tooltip.side_effect = tooltip
        widget = QWidget.__new__(QWidget)
        widget.backend, widget.tag = backend, 'button'
        widget._tooltip = None
        widget._require_ui = Mock()
        widget.setToolTip('Help')
        backend.tooltip.assert_called_once_with('button', delay=TOOLTIP_DELAY, hide_on_activity=True)
        backend.get_item_children.return_value = ['label']
        widget.setToolTip('Updated help')
        self.assertEqual(backend.tooltip.call_count, 1)
        backend.set_value.assert_called_once_with('label', 'Updated help')

    def test_reused_explorer_tooltip_waits_after_row_or_pointer_changes(self):
        parts = {'widget': Mock(), 'title': Mock(), 'details': Mock(), 'path': Mock(), 'item_id': None}
        host = SimpleNamespace(_mouse_down=False, _item_tooltip_content=lambda item: ('Title', 'Details', 'Path'))
        first, second = object(), object()
        point = QPoint(10, 20)
        with patch('DearUIQt.tooltip.time.monotonic') as clock, \
                patch('WinUx.ui.components.explorer_rendering.QCursor.pos', return_value=point) as cursor:
            def hover(item, now):
                clock.return_value = now
                ExplorerRenderingMixin._show_tooltip_parts(host, parts, item)
            hover(first, 10)
            hover(first, 10.49)
            parts['widget'].show.assert_not_called()
            hover(first, 10.5)
            self.assertEqual(parts['item_id'], id(first))
            hover(second, 10.6)
            self.assertIsNone(parts['item_id'])
            hover(second, 11.1)
            self.assertEqual(parts['item_id'], id(second))
            cursor.return_value = QPoint(11, 20)
            hover(second, 11.2)
            self.assertIsNone(parts['item_id'])
            ExplorerRenderingMixin._hide_tooltip_parts(parts)
            hover(second, 12)
            self.assertIsNone(parts['item_id'])
            hover(second, 12.5)
            self.assertEqual(parts['item_id'], id(second))

    def test_tk_tooltip_uses_same_delay_and_cancels_on_leave_or_motion(self):
        widget = Mock()
        tip = _ToolTip(widget, 'Help')
        tip._enter()
        widget.after.assert_called_with(round(TOOLTIP_DELAY * 1000), tip._show)
        old_timer = tip._after
        tip._enter()
        widget.after_cancel.assert_called_with(old_timer)
        tip._leave()
        self.assertIsNone(tip._after)


if __name__ == '__main__':
    unittest.main()
