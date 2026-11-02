"""Explorer relayout queues must not replay work already completed directly."""
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import run_winux
run_winux._configure_bundled_dependencies(str(ROOT))
from WinUx.ui.components.explorer_layout import ExplorerLayoutMixin as Layout

MODULE = 'WinUx.ui.components.explorer_layout'


class LayoutCoalescingTests(unittest.TestCase):
    def setUp(self):
        self.callbacks = []
        self.runtime = SimpleNamespace(invokeNextFrame=self.callbacks.append)
        self.runtime_patch = patch(MODULE + '.QGuiRuntime', return_value=self.runtime)
        self.runtime_patch.start()
        self.addCleanup(self.runtime_patch.stop)
        self.item_patch = patch(MODULE + '.QRetainedItem')
        self.item_patch.start().return_value.exists.return_value = True
        self.addCleanup(self.item_patch.stop)
        self.host = SimpleNamespace(
            _resize_layout_pending=False, header_canvas=1, window_tag=2,
            auto_width_enabled=True, _text_fit_cache=Mock(),
            _sync_auto_width_to_viewport=Mock(), _layout_all=Mock(),
            _update_native_cursor_geometry=Mock())

    def test_drag_burst_queues_one_layout(self):
        for _ in range(100):
            Layout._queue_layout(self.host)
        self.assertEqual(len(self.callbacks), 1)
        self.callbacks.pop()()
        self.host._layout_all.assert_called_once()
        self.assertFalse(self.host._resize_layout_pending)

    def test_direct_layout_satisfies_queued_request(self):
        Layout._queue_layout(self.host)
        # _layout_all clears the flag as soon as a direct layout starts.
        self.host._resize_layout_pending = False
        self.callbacks.pop()()
        self.host._layout_all.assert_not_called()

    def test_old_callback_may_satisfy_new_request_but_never_replay_it(self):
        Layout._queue_layout(self.host)
        self.host._resize_layout_pending = False
        Layout._queue_layout(self.host)
        for callback in self.callbacks:
            callback()
        self.host._layout_all.assert_called_once()

    def test_resize_burst_has_one_deferred_auto_width_sync(self):
        for width in range(300, 400):
            Layout.resize(self.host, width, 300)
        self.assertEqual(len(self.callbacks), 1)
        self.host._sync_auto_width_to_viewport.reset_mock()
        self.callbacks.pop()()
        self.host._sync_auto_width_to_viewport.assert_called_once_with(layout=True)
        self.assertFalse(self.host._auto_width_resize_sync_pending)

    def test_pending_resize_respects_auto_width_being_disabled(self):
        Layout.resize(self.host, 400, 300)
        self.host.auto_width_enabled = False
        self.host._sync_auto_width_to_viewport.reset_mock()
        self.callbacks.pop()()
        self.host._sync_auto_width_to_viewport.assert_not_called()
        self.assertFalse(self.host._auto_width_resize_sync_pending)

    def test_failed_schedule_allows_next_resize_to_retry(self):
        self.runtime.invokeNextFrame = Mock(side_effect=RuntimeError('unavailable'))
        Layout.resize(self.host, 400, 300)
        self.assertFalse(self.host._auto_width_resize_sync_pending)
        self.runtime.invokeNextFrame = self.callbacks.append
        Layout.resize(self.host, 500, 300)
        self.assertEqual(len(self.callbacks), 1)


if __name__ == '__main__':
    unittest.main(verbosity=2)
