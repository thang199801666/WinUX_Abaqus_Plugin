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
from DearUIQt.widgets import QWidget, QToolTip
from WinUx.ui.components.explorer_rendering import ExplorerRenderingMixin
from WinUx.ui.components.explorer.tooltip_overlay import ExplorerTooltipOverlay
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

    def test_qtooltip_rejects_drawlist_before_entering_dpg_context(self):
        backend = Mock()
        backend.get_item_info.return_value = {
            'type': 'mvAppItemType::mvDrawlist'}
        with self.assertRaisesRegex(TypeError, 'paint/draw items'):
            QToolTip('drawlist', backend=backend)
        backend.tooltip.assert_not_called()

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

    def test_reused_explorer_tooltip_waits_per_logical_row_not_per_mouse_pixel(self):
        parts = {'widget': Mock(), 'title': Mock(), 'details': Mock(), 'path': Mock(), 'item_id': None}
        class Host(ExplorerRenderingMixin):
            _mouse_down = False

            @staticmethod
            def _item_tooltip_content(item):
                return ('Title', 'Details', 'Path')

            def _update_hover_state(self):
                return None

        host = Host()
        first = SimpleNamespace(path='C:/same.txt', name='same.txt', data={})
        replacement = SimpleNamespace(path='C:/same.txt', name='same.txt', data={})
        second = SimpleNamespace(path='C:/other.txt', name='other.txt', data={})
        with patch('DearUIQt.tooltip.time.monotonic') as clock:
            def hover(item, now):
                clock.return_value = now
                ExplorerRenderingMixin._show_tooltip_parts(host, parts, item)
            hover(first, 10)
            hover(first, 10.49)
            parts['widget'].show.assert_not_called()
            # Replacing the Python object for the same logical file must not
            # restart the dwell timer. This is what live Job/File refreshes do.
            hover(replacement, 10.5)
            self.assertEqual(parts['item_id'], ('path', 'C:/same.txt'))
            hover(second, 10.6)
            self.assertIsNone(parts['item_id'])
            hover(second, 11.1)
            self.assertEqual(parts['item_id'], ('path', 'C:/other.txt'))
            # No exact mouse position participates in the dwell target. Small
            # movement inside the same row therefore keeps the tooltip alive.
            hover(second, 11.2)
            self.assertEqual(parts['item_id'], ('path', 'C:/other.txt'))
            ExplorerRenderingMixin._hide_tooltip_parts(parts)
            hover(second, 12)
            self.assertIsNone(parts['item_id'])
            hover(second, 12.5)
            self.assertEqual(parts['item_id'], ('path', 'C:/other.txt'))


    def test_explorer_stationary_pointer_wakes_at_dwell_deadline(self):
        class Host(ExplorerRenderingMixin):
            _mouse_down = False

            @staticmethod
            def _item_tooltip_content(item):
                return ('Title', 'Details', 'Path')

        host = Host()
        parts = {
            'widget': Mock(), 'item_id': None,
        }
        item = SimpleNamespace(path='C:/still.txt', name='still.txt', data={})
        callbacks = []
        timer = Mock()

        def single_shot(milliseconds, callback):
            self.assertEqual(milliseconds, round(TOOLTIP_DELAY * 1000))
            callbacks.append(callback)
            return timer

        def update_hover():
            ExplorerRenderingMixin._show_tooltip_parts(host, parts, item)

        host._update_hover_state = update_hover
        with patch(
                'WinUx.ui.components.explorer.rendering.QTimer.singleShot',
                side_effect=single_shot), \
                patch('DearUIQt.tooltip.time.monotonic') as clock:
            clock.return_value = 20.0
            host._show_tooltip_parts(parts, item)
            self.assertEqual(len(callbacks), 1)
            parts['widget'].show.assert_not_called()

            # No mouse-move call is made here. The UI timer itself reaches the
            # dwell deadline and re-samples hover state.
            clock.return_value = 20.0 + TOOLTIP_DELAY
            callbacks.pop()()
            parts['widget'].show.assert_called_once_with()
            self.assertEqual(parts['item_id'], ('path', 'C:/still.txt'))

    def test_explorer_stationary_wakeup_is_cancelled_when_hover_leaves(self):
        class Host(ExplorerRenderingMixin):
            _mouse_down = False

            @staticmethod
            def _item_tooltip_content(item):
                return ('Title', '', '')

            def _update_hover_state(self):
                return None

        host = Host()
        parts = {'widget': Mock(), 'item_id': None}
        item = SimpleNamespace(path='C:/leave.txt', name='leave.txt', data={})
        timer = Mock()
        with patch(
                'WinUx.ui.components.explorer.rendering.QTimer.singleShot',
                return_value=timer):
            host._show_tooltip_parts(parts, item)
            host._hide_tooltip_parts(parts)
        timer.delete.assert_called_once_with()
        self.assertNotIn('hover_timer', parts)
        self.assertNotIn('hover_timer_target', parts)

    def test_explorer_tooltip_overlay_is_lazy_at_listview_startup(self):
        with patch(
                'WinUx.ui.components.explorer.tooltip_overlay.QFontMetrics'), \
                patch(
                'WinUx.ui.components.explorer.tooltip_overlay.QViewportCanvas') as canvas:
            overlay = ExplorerTooltipOverlay('rows_body')
        canvas.assert_not_called()
        self.assertTrue(overlay.exists())

    def test_reused_explorer_tooltip_uses_viewport_overlay_not_drawlist_child(self):
        target = object()
        tooltip = Mock()
        host = SimpleNamespace(
            uid='rows', _fonts={}, _primary_pointer_overlays=True)
        with patch(
                'WinUx.ui.components.explorer.rendering.ExplorerTooltipOverlay',
                return_value=tooltip) as ctor:
            parts = ExplorerRenderingMixin._create_item_tooltip(
                host, target, 'body')
        ctor.assert_called_once_with(
            'rows_body_item_tooltip', body_font=None, header_font=None,
            primary_viewport=True)
        self.assertIs(parts['widget'], tooltip)
        self.assertIs(parts['target'], target)
        self.assertIsNone(parts['item_id'])

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
