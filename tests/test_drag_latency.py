"""Paint-group fast paths, preview caching and scoped drag/transfer timing."""
from collections import deque
import ctypes
from ctypes import wintypes
import itertools
from pathlib import Path
import sys
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import run_winux
run_winux._configure_bundled_dependencies(str(ROOT))
from DearUIQt.widgets import QWidget, QPaintGroup
from DearUIQt.gui import QCursor
from DearUIQt.backends.native_windows import NativeWindowBackend
from DearUIQt.backends.native_presentation import NativePresentation
from WinUx.ui.components.explorer_drag_preview import DragPreviewHelper
from WinUx.ui.components.explorer_drag_drop import ExplorerDragDropMixin
from WinUx.runtime.frame_clock import AdaptiveFrameClock
from WinUx.dialogs.logic.transfer import TransferCenterLogic
from WinUx.dialogs.transfer_center_form import TransferCenterDialog


class Backend:
    def __init__(self):
        self.tags, self.writes, self.transforms = {1}, [], []
    def add_draw_node(self, **kwargs):
        self.tags.add(2)
        return 2
    def does_item_exist(self, tag):
        return tag in self.tags
    def create_translation_matrix(self, point):
        return tuple(point)
    def apply_transform(self, tag, matrix):
        self.transforms.append((tag, matrix))
    def configure_item(self, tag, **kwargs):
        self.writes.append((tag, kwargs))
    def delete_item(self, tag):
        self.tags.discard(tag)


class Adapter:
    instances = 0
    def __init__(self, tag):
        type(self).instances += 1
        self.tag, self.writes = tag, []
    def setImmediateUpdates(self, flag):
        return self
    def configure(self, **kwargs):
        self.writes.append(kwargs)
    def exists(self):
        return True


class Center(TransferCenterLogic):
    def __init__(self):
        self.tasks, self._row_to_task, self._row_ids = [], {}, itertools.count(1)
        self.view = SimpleNamespace(after=Mock())
        self.show, self.hide = Mock(), Mock()
        self.isVisible = Mock(return_value=False)
    def post(self, *args):
        return True
    def update_row(self, *args, **kwargs):
        return True


class DragLatencyTests(unittest.TestCase):
    def test_group_translation_is_immediate_deduplicated_and_owned(self):
        backend = Backend()
        parent = QWidget(1, backend=backend)
        group = QPaintGroup(parent=parent, show=False)
        group.setTranslation(10, 20)
        group.setTranslation(10, 20)
        self.assertEqual(backend.transforms, [(2, (10.0, 20.0, 0.0))])
        group.configure(show=True)
        self.assertEqual(backend.writes[-1], (2, {'show': True}))
        parent.delete()
        group.setTranslation(30, 40)
        self.assertEqual(len(backend.transforms), 1)

    def test_worker_translation_coalesces_on_parent_scheduler(self):
        queue = deque()
        backend = Backend()
        parent = QWidget(1, backend=backend, after=lambda delay, cb, *args: queue.append((cb, args)))
        group = QPaintGroup(parent=parent)
        def producer():
            for i in range(100):
                group.setTranslation(i, i)
        worker = threading.Thread(target=producer)
        worker.start()
        worker.join()
        self.assertFalse(backend.transforms)
        while queue:
            cb, args = queue.popleft()
            cb(*args)
        self.assertEqual(backend.transforms, [(2, (99.0, 99.0, 0.0))])
        parent.delete()

    def test_preview_reuses_adapters_and_text_layout_while_moving(self):
        helper = DragPreviewHelper('test')
        helper._canvas = SimpleNamespace(exists=lambda: True)
        helper._group = Mock()
        helper._parts = {'shadow': 1, 'panel': 2, 'accent': 3, 'texts': [4, 5, 6, 7]}
        helper._measure = Mock(return_value=(100, 15))
        Adapter.instances = 0
        with patch('WinUx.ui.components.explorer_drag_preview.QRetainedItem', Adapter), \
                patch.object(QCursor, 'paintPos', return_value=(10, 20)):
            helper.begin([SimpleNamespace(name='example.inp')])
            helper.update(True, '/work')
            measured = helper._measure.call_count
            writes = sum(len(a.writes) for a in helper._adapters.values())
            for _ in range(100):
                helper.update(True, '/work')
            self.assertEqual(helper._measure.call_count, measured)
            self.assertEqual(sum(len(a.writes) for a in helper._adapters.values()), writes)
            self.assertEqual(Adapter.instances, 7)
            helper.moveToCursor((100, 200))
            helper._group.setTranslation.assert_called_with(109.0, 211.0)
            helper.end()
            helper._group.configure.assert_called_with(show=False)
            helper.update(True, '/other')
            self.assertEqual(helper._measure.call_count, measured)

    def test_drag_frame_rate_does_not_change_idle_policy(self):
        clock = AdaptiveFrameClock(clock=lambda: 10.0)
        clock.presented()
        self.assertAlmostEqual(clock.delay(dragging=True), 1 / 240)
        self.assertAlmostEqual(clock.delay(), 1 / 60)
        clock.last_input = -10
        self.assertAlmostEqual(clock.delay(), .5)
        self.assertAlmostEqual(clock.delay(dragging=True), 1 / 240)
        self.assertAlmostEqual(clock.delay(dragging=True, minimized=True), 1)

    def test_live_native_cursor_and_renderer_fallback(self):
        backend = SimpleNamespace(get_mouse_pos=lambda **kwargs: (3, 4))
        with patch.object(NativeWindowBackend, 'cursorClientPosition', return_value=(-50, 80)):
            self.assertEqual(tuple(QCursor.viewportPos(backend=backend)), (-50, 80))
        with patch.object(NativeWindowBackend, 'cursorClientPosition', return_value=None):
            self.assertEqual(tuple(QCursor.viewportPos(backend=backend)), (3, 4))
        with patch.object(NativeWindowBackend, 'cursorPaintPosition', return_value=(700, 500)):
            self.assertEqual(tuple(QCursor.paintPos(backend=backend)), (700, 500))

    def test_native_cursor_paint_space_differs_from_client_hit_test_space(self):
        user32 = Mock()
        def physical(ptr):
            point = ctypes.cast(ptr, ctypes.POINTER(wintypes.POINT)).contents
            point.x, point.y = -120, 80
            return True
        def to_client(hwnd, ptr):
            point = ctypes.cast(ptr, ctypes.POINTER(wintypes.POINT)).contents
            point.x += 200
            point.y -= 50
            return True
        user32.GetCursorPos.side_effect = physical
        user32.ScreenToClient.side_effect = to_client
        native = NativeWindowBackend(SimpleNamespace())
        native.primaryWinId = Mock(return_value=123)
        native.isEnabled = Mock(return_value=True)
        with patch('DearUIQt.backends.native_windows._windows_user32', return_value=user32):
            self.assertEqual(native.cursorClientPosition(), (80, 30))
            self.assertEqual(native.cursorPaintPosition(), (-120, 80))
            native.isEnabled.return_value = False
            self.assertEqual(native.cursorPaintPosition(), (80, 30))

    def test_completed_tasks_hide_quickly_but_never_hide_active_or_failed(self):
        center = Center()
        task = center.add_task('Upload', threading.Event(), ['a'])
        task.complete()
        delay, callback, task_arg = center.view.after.call_args.args
        self.assertEqual(delay, 120)
        self.assertLess(delay, 900)
        center.hide.assert_not_called()
        center.isVisible.return_value = True
        other = center.add_task('Upload', threading.Event(), ['b'])
        self.assertEqual(center.show.call_count, 1)
        callback(task_arg)
        center.hide.assert_not_called()
        other.fail('network error')
        center._hide_if_idle()
        center.hide.assert_not_called()

    def test_initial_transfer_height_uses_logical_rows_before_widget_commands(self):
        cls = TransferCenterDialog
        fake = SimpleNamespace(row_widgets={}, _pending_row_creations={}, _row_to_task=dict.fromkeys(range(4)))
        for key in ('EMPTY_ROWS_HEIGHT', 'MAX_VISIBLE_ROWS', 'ROW_HEIGHT_HINT', 'MIN_WINDOW_HEIGHT',
                    'MAX_WINDOW_HEIGHT', 'CHROME_HEIGHT'):
            setattr(fake, key, getattr(cls, key))
        self.assertEqual(cls._target_window_height(fake), 518)

    def test_native_warm_presentation_reuses_only_stable_opt_in_geometry(self):
        backend = SimpleNamespace(does_item_exist=lambda tag: True, is_item_shown=lambda tag: True)
        presentation = NativePresentation(backend)
        presentation.native = SimpleNamespace(_rawWinId=lambda tag: 123)
        presentation._cloak = Mock()
        presentation._geometry = Mock(return_value=(10, 20, 830, 340, 800, 300))
        shown = Mock()
        presentation.prepare(1, lambda: True, presented=shown, reuse_geometry=True)
        presentation._settle_frame()
        shown.assert_not_called()
        presentation._settle_frame()
        self.assertEqual(shown.call_count, 1)
        presentation.prepare(1, lambda: True, presented=shown, reuse_geometry=True)
        presentation._settle_frame()
        self.assertEqual(shown.call_count, 2)
        # A changed size must settle again, even for an opted-in retained tool.
        presentation._geometry.return_value = (10, 20, 830, 440, 800, 400)
        presentation.prepare(1, lambda: True, presented=shown, reuse_geometry=True)
        presentation._settle_frame()
        self.assertEqual(shown.call_count, 2)
        presentation._settle_frame()
        self.assertEqual(shown.call_count, 3)
        # Ordinary modal/dialog callers keep the original two-frame policy.
        presentation.prepare(1, lambda: True, presented=shown)
        presentation._settle_frame()
        self.assertEqual(shown.call_count, 3)
        presentation._settle_frame()
        self.assertEqual(shown.call_count, 4)

    def test_pending_presentation_is_urgent_without_idle_paint_polling(self):
        from WinUx.view import WinUXView
        clock = AdaptiveFrameClock(clock=lambda: 10.0)
        clock.presented()
        clock.last_input = -10
        dispatcher = SimpleNamespace(has_immediate_work=lambda: False)
        host = SimpleNamespace(
            _alive=True, _frame_clock=clock, _dispatcher=dispatcher,
            _layout_dirty=False, _startup_layout_frames=0, _after_render_callbacks=[],
            _gui_runtime=SimpleNamespace(hasPendingPresentation=lambda: True), panels=[],
            _find_main_viewport_hwnd=lambda: 0, _drain_queue=lambda: None,
            _safe_frame_step=lambda name, callback: callback())
        with patch('WinUx.ui.native.message_pump.wait_native_messages') as wait:
            WinUXView._wait_for_ui_frame(host)
            wait.assert_not_called()

    def test_stale_internal_hover_cannot_override_live_controller_feedback(self):
        fake = SimpleNamespace(
            on_drop=Mock(), on_drag_motion=Mock(), _item_drag_active=True,
            _drop_target_index=0, _drop_target_pinned=False, _pinned_item=None,
            items=[SimpleNamespace(name='stale folder', is_dir=True)],
            _external_drop_valid=True, _external_drop_target_name='/fresh/local/path',
            _drag_preview=Mock(), _set_mouse_cursor=Mock(), _apply_native_drag_cursor=Mock())
        ExplorerDragDropMixin._update_drag_cursor(fake)
        fake._drag_preview.update.assert_called_with(can_copy=True, target_name='/fresh/local/path')
        fake._external_drop_valid = False
        ExplorerDragDropMixin._update_drag_cursor(fake)
        fake._drag_preview.update.assert_called_with(can_copy=False, target_name=None)

    def test_native_transition_urgency_is_bounded_if_a_window_refuses_to_hide(self):
        presentation = NativePresentation(SimpleNamespace())
        presentation._retiring_windows.add(123)
        presentation._settle_frame = Mock()
        presentation._deliver_after_hidden = Mock()
        presentation.retiring_windows = Mock()
        self.assertTrue(presentation.needs_frame())
        for _ in range(8):
            presentation.after_frame()
        self.assertFalse(presentation.needs_frame())
        self.assertIn(123, presentation._retiring_windows)


if __name__ == '__main__':
    unittest.main(verbosity=2)
