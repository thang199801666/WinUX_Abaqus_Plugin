"""Shared renderer late-sampling hooks without creating WinUx windows."""
import gc
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch
import weakref

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'vendor'))
sys.path.insert(0, str(ROOT))
from DearUIQt import QGuiRuntime


class RenderHookTests(unittest.TestCase):
    def runtime(self):
        backend = SimpleNamespace(is_dearpygui_running=lambda: True, render_dearpygui_frame=Mock())
        runtime = QGuiRuntime(backend=backend)
        runtime._context_created = True
        self.addCleanup(lambda: QGuiRuntime._before_render_callbacks.pop(id(backend), None))
        return runtime

    def test_callback_is_after_preparation_and_immediately_before_render(self):
        runtime, events = self.runtime(), []
        runtime.backend.render_dearpygui_frame.side_effect = lambda: events.append('draw')
        native = SimpleNamespace(before_frame=lambda: events.append('prepare'), after_frame=lambda: events.append('present'))
        runtime.addBeforeRenderCallback(lambda: events.append('cursor'))
        with patch('DearUIQt.gui.popup_tracking.update_popup_positions', side_effect=lambda b: events.append('popup')), \
                patch('DearUIQt.backends.shared_scrollers.update_shared_scrollers', side_effect=lambda b: events.append('scroller')), \
                patch('DearUIQt.backends.native_presentation.presentation_for', return_value=native):
            runtime.renderFrame()
        self.assertEqual(events, ['popup', 'scroller', 'prepare', 'cursor', 'draw', 'present', 'popup'])

    def test_wrappers_share_registration_and_can_remove_it(self):
        runtime = self.runtime()
        other = QGuiRuntime(backend=runtime.backend)
        callback = Mock()
        token = other.addBeforeRenderCallback(callback)
        runtime._run_before_render_callbacks()
        callback.assert_called_once()

        self.assertTrue(runtime.removeBeforeRenderCallback(token))
        other._run_before_render_callbacks()
        callback.assert_called_once()

    def test_pointer_samples_after_all_regular_updates_even_if_registered_first(self):
        runtime = self.runtime()
        pointer = [0, 0]
        sampled = []
        runtime.addBeforeRenderCallback(lambda: sampled.append(tuple(pointer)), late=True)
        runtime.addBeforeRenderCallback(lambda: pointer.__setitem__(slice(None), [100, 200]))
        runtime._run_before_render_callbacks()
        self.assertEqual(sampled, [(100, 200)])

    def test_late_registration_during_regular_update_waits_for_next_frame(self):
        runtime, events = self.runtime(), []
        runtime.addBeforeRenderCallback(
            lambda: runtime.addBeforeRenderCallback(lambda: events.append('late'), late=True))
        runtime._run_before_render_callbacks()
        self.assertEqual(events, [])
        runtime._run_before_render_callbacks()
        self.assertEqual(events, ['late'])

    def test_bound_method_receiver_is_weak_and_deleted_receivers_are_skipped(self):
        runtime = self.runtime()
        events = []
        class Receiver:
            _deleted = False
            def run(self):
                events.append('called')
        receiver = Receiver()
        reference = weakref.ref(receiver)
        runtime.addBeforeRenderCallback(receiver.run)
        del receiver
        gc.collect()
        self.assertIsNone(reference())
        runtime._run_before_render_callbacks()
        receiver = Receiver()
        runtime.addBeforeRenderCallback(receiver.run)
        receiver._deleted = True
        runtime._run_before_render_callbacks()
        self.assertEqual(events, [])
        self.assertNotIn(id(runtime.backend), runtime._before_render_callbacks)

    def test_reentrant_registration_waits_and_removal_is_authoritative(self):
        runtime, events = self.runtime(), []
        token = None
        def first():
            events.append('first')
            runtime.removeBeforeRenderCallback(token)
            runtime.addBeforeRenderCallback(lambda: events.append('new'))
        runtime.addBeforeRenderCallback(first)
        token = runtime.addBeforeRenderCallback(lambda: events.append('removed'))
        runtime._run_before_render_callbacks()
        self.assertEqual(events, ['first'])
        runtime._run_before_render_callbacks()
        self.assertEqual(events, ['first', 'first', 'new'])

    def test_bad_optional_hook_is_removed_without_blocking_other_work(self):
        runtime, events = self.runtime(), []
        runtime.addBeforeRenderCallback(Mock(side_effect=ValueError('bad hook')))
        runtime.addBeforeRenderCallback(lambda: events.append('good'))
        with self.assertLogs('DearUIQt.runtime', level='ERROR'):
            runtime._run_before_render_callbacks()
        runtime._run_before_render_callbacks()
        self.assertEqual(events, ['good', 'good'])


if __name__ == '__main__':
    unittest.main(verbosity=2)
