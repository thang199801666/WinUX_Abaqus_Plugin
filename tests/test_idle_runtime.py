"""Deterministic pacing, dispatch, modal and geometry regressions."""
import sys
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import run_winux
run_winux._configure_bundled_dependencies(str(ROOT))
from WinUx.runtime.frame_clock import AdaptiveFrameClock
from WinUx.runtime.ui_dispatcher import UiDispatcher
from DearUIQt.backends.dearpygui_scroller import dpg_window_rect
from DearUIQt import modal


class IdleTests(unittest.TestCase):
    def test_pacing_and_activity(self):
        now = [0.0]
        clock = AdaptiveFrameClock(lambda: now[0])
        self.assertEqual(clock.delay(), 0)
        clock.presented()
        self.assertAlmostEqual(clock.delay(), 1 / 60)
        now[0] = 2
        clock.presented()
        self.assertAlmostEqual(clock.delay(), .5)
        self.assertAlmostEqual(clock.delay(foreground=False), 1)
        clock.work()
        self.assertAlmostEqual(clock.delay(), 1 / 30)
        clock.input()
        self.assertAlmostEqual(clock.delay(), 1 / 60)
        self.assertEqual(clock.delay(urgent=True), 0)
        self.assertAlmostEqual(clock.delay(minimized=True), 1)

    def test_worker_wakes_owner_but_ui_timers_do_not(self):
        dispatcher = UiDispatcher()
        wake, delivered = Mock(), []
        dispatcher.set_wake_callback(wake)
        dispatcher.after(0, lambda: delivered.append(threading.get_ident()))
        wake.assert_not_called()
        worker = threading.Thread(target=lambda: dispatcher.after(0, lambda: delivered.append(threading.get_ident())))
        worker.start()
        worker.join()
        wake.assert_called_once()
        dispatcher.drain()
        self.assertEqual(delivered, [threading.get_ident()] * 2)
        dispatcher.close()

    def test_deadlines_cancel_and_bounded_timer_delivery(self):
        dispatcher = UiDispatcher()
        callback = Mock()
        with patch('WinUx.runtime.ui_dispatcher.time.monotonic', return_value=10):
            token = dispatcher.after(50, callback)
            self.assertAlmostEqual(dispatcher.next_deadline_ms(), 50)
            dispatcher.drain()
            callback.assert_not_called()
        with patch('WinUx.runtime.ui_dispatcher.time.monotonic', return_value=10.06):
            dispatcher.drain(max_callbacks=1)
            callback.assert_called_once()
        self.assertIsNone(dispatcher.next_deadline_ms())

        token = dispatcher.after(50, callback)
        self.assertTrue(dispatcher.after_cancel(token))
        self.assertIsNone(dispatcher.next_deadline_ms())
        dispatcher.close()

    def test_worker_burst_coalesces_wake_without_dropping_results(self):
        dispatcher = UiDispatcher()
        wake, delivered = Mock(), []
        dispatcher.set_wake_callback(wake)
        def produce():
            for index in range(1000):
                dispatcher.after(0, delivered.append, index)
        worker = threading.Thread(target=produce)
        worker.start()
        worker.join()
        wake.assert_called_once()
        self.assertEqual(dispatcher.drain(max_callbacks=256), 256)
        self.assertTrue(dispatcher.has_immediate_work())
        dispatcher.drain()
        self.assertEqual(delivered, list(range(1000)))
        worker = threading.Thread(target=lambda: dispatcher.after(0, delivered.append, 'next'))
        worker.start()
        worker.join()
        self.assertEqual(wake.call_count, 2)
        dispatcher.drain()
        self.assertEqual(delivered[-1], 'next')
        dispatcher.close()

    def test_modal_changes_are_synchronous_inside_cached_frame(self):
        backend = Mock()
        backend.get_windows.return_value = [1]
        backend.get_frame_count.return_value = 7
        backend.get_item_configuration.return_value = {'modal': False}
        app = SimpleNamespace(activeModalWidget=Mock(return_value=None))
        with patch.object(modal, 'dpg', backend), patch.object(modal, 'MODAL_TAGS', set()), \
                patch.object(modal, '_legacy_scan', None), \
                patch('DearUIQt.core.application.QApplication.instance', return_value=app):
            self.assertFalse(modal.visible_modal_window_exists())
            self.assertFalse(modal.visible_modal_window_exists())
            backend.get_item_configuration.assert_called_once()
            app.activeModalWidget.return_value = object()
            self.assertTrue(modal.visible_modal_window_exists())
            app.activeModalWidget.return_value = None
            self.assertFalse(modal.visible_modal_window_exists())

    def test_clipped_geometry_walk_is_linear(self):
        backend = Mock()
        backend.does_item_exist.return_value = True
        backend.get_item_info.side_effect = lambda item: {'type': 'mvChildWindow', 'parent': item - 1}
        backend.get_item_state.side_effect = lambda item: {'pos': (1, 2), 'rect_size': (100, 100)}
        self.assertEqual(dpg_window_rect(backend, 20, clip=True), (20, 40, 101, 102))
        self.assertEqual(backend.get_item_info.call_count, 20)
        self.assertEqual(backend.get_item_state.call_count, 20)

    def test_scroller_geometry_pass_reuses_ancestor_reads_not_future_frames(self):
        backend = Mock()
        backend.get_item_info.side_effect = lambda item: {'type': 'mvChildWindow', 'parent': item - 1}
        backend.get_item_state.side_effect = lambda item: {'pos': (1, 2), 'rect_size': (100, 100)}
        nodes = {}
        self.assertEqual(dpg_window_rect(backend, 20, node_cache=nodes), (20, 40, 120, 140))
        self.assertEqual(dpg_window_rect(backend, 20, clip=True, node_cache=nodes), (20, 40, 101, 102))
        self.assertEqual(dpg_window_rect(backend, 10, node_cache=nodes), (10, 20, 110, 120))
        self.assertEqual(backend.get_item_info.call_count, 20)
        self.assertEqual(backend.get_item_state.call_count, 20)
        backend.get_item_state.side_effect = lambda item: {'pos': (2, 3), 'rect_size': (100, 100)}
        self.assertEqual(dpg_window_rect(backend, 20, node_cache={}), (40, 60, 140, 160))
        self.assertEqual(backend.get_item_state.call_count, 40)

    def test_restore_rechecks_minimized_state_after_wake(self):
        from WinUx.view import WinUXView
        now = [2.0]
        clock = AdaptiveFrameClock(lambda: now[0])
        clock.last_input = float('-inf')
        clock.presented()
        dispatcher = UiDispatcher()
        host = SimpleNamespace(
            _alive=True, _frame_clock=clock, _dispatcher=dispatcher,
            _layout_dirty=False, _startup_layout_frames=0, _after_render_callbacks=[],
            _find_main_viewport_hwnd=lambda: 123, _drain_queue=dispatcher.drain,
            _safe_frame_step=lambda name, callback: callback())
        user32 = Mock()
        user32.IsIconic.side_effect = [True, False]
        user32.GetForegroundWindow.return_value = 123
        waits = []
        def wait(timeout_ms, on_input):
            waits.append(timeout_ms)
            clock.input()  # Native restore event renews input grace.
            now[0] += .02
            return True
        with patch('WinUx.view.ctypes', SimpleNamespace(windll=SimpleNamespace(user32=user32))), \
                patch('WinUx.ui.native.message_pump.wait_native_messages', side_effect=wait):
            WinUXView._wait_for_ui_frame(host)
        self.assertEqual(len(waits), 1)
        self.assertEqual(user32.IsIconic.call_count, 2)

    def test_child_timers_cancel_and_worker_wake(self):
        from WinUx.ui.hosting.floating_runtime import ChildView
        child = ChildView()
        child._native_hwnd = 456
        calls = []
        with patch('WinUx.ui.hosting.floating_runtime.wake_native_window') as wake:
            token = child.after(100, lambda: calls.append('cancelled'))
            self.assertTrue(child.after_cancel(token))
            child.after(0, lambda: calls.append('ui'))
            wake.assert_not_called()
            worker = threading.Thread(target=lambda: child.after(0, lambda: calls.append('worker')))
            worker.start()
            worker.join()
            wake.assert_called_once_with(456)
            child.drain()
        self.assertEqual(calls, ['ui', 'worker'])
        child._dispatcher.close()

    def test_hidden_child_wait_uses_timer_deadline_not_12ms_poll(self):
        from WinUx.ui.hosting.floating_runtime import ChildView, FloatingDialogRuntime
        runtime = FloatingDialogRuntime.__new__(FloatingDialogRuntime)
        runtime.view = ChildView()
        runtime.gui = SimpleNamespace(isRunning=lambda: True)
        runtime.form = SimpleNamespace(winfo_exists=lambda: True)
        runtime.native = SimpleNamespace(visible=False)
        runtime._drain_commands = lambda: None
        runtime._drain_form_callbacks = lambda: None
        runtime.incoming = __import__('queue').Queue()
        with patch('WinUx.ui.hosting.floating_runtime.wait_native_messages', return_value=False) as wait:
            self.assertFalse(runtime._wait_for_frame())
            self.assertEqual(wait.call_args.args[0], 1000)
            runtime.view.after(200, lambda: None)
            self.assertFalse(runtime._wait_for_frame())
            self.assertGreater(wait.call_args.args[0], 100)
            self.assertLessEqual(wait.call_args.args[0], 200)
        runtime.view._dispatcher.close()


if __name__ == '__main__':
    unittest.main(verbosity=2)
