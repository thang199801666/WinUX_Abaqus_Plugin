"""Background modeless tools must not swallow main-window dialog commands."""
from collections import deque
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import WinUx  # Configure bundled Dear PyGui for standalone Abaqus Python tests.
from DearUIQt import input_gate as gate


class ModelessDialogInputTests(unittest.TestCase):
    def setUp(self):
        self.main, self.digitizer = 100, 200
        self.hit_root = self.main
        self.user32 = SimpleNamespace(
            WindowFromPoint=Mock(return_value=101),
            GetAncestor=Mock(side_effect=lambda hwnd, flag: self.hit_root),
            IsWindow=Mock(return_value=True),
            IsWindowVisible=Mock(return_value=True),
            GetWindowRect=Mock(side_effect=self.window_rect),
        )
        # The digitizer remains visible behind the overlapping main window.
        values = {
            "_native_pointer_hwnds": {self.digitizer},
            "_native_modal_tokens": set(),
            "_native_modal_release_pending": False,
            "_native_modal_release_guard_until_frame": -1,
            "_native_surface_press_hwnd": None,
            "_native_release_guard_until_frame": -1,
        }
        patches = [patch.multiple(gate, **values),
                   patch.object(gate.ctypes, "windll", SimpleNamespace(user32=self.user32), create=True),
                   patch.object(gate.os, "name", "nt"),
                   patch.object(gate, "_native_cursor_position", return_value=(300, 300)),
                   patch.object(gate, "_mouse_button_down", return_value=False),
                   patch.object(gate, "_frame_count", return_value=10)]
        for item in patches:
            item.start()
            self.addCleanup(item.stop)

    @staticmethod
    def window_rect(hwnd, pointer):
        rect = pointer._obj
        rect.left, rect.top, rect.right, rect.bottom = 0, 0, 800, 700
        return True

    def test_returning_to_main_unblocks_input_while_digitizer_stays_open(self):
        self.assertFalse(gate.native_background_input_blocked())

    def test_all_main_dialog_menu_callbacks_survive_return_from_digitizer(self):
        from WinUx.view import WinUXView
        view = object.__new__(WinUXView)
        view._alive = True
        view._dpg_callbacks = deque()
        callbacks = [Mock(name=name) for name in (
            "settings", "login", "job_manager", "bookmarks", "close_confirm")]
        jobs = [(callback,) for callback in callbacks]
        with patch("WinUx.view.dpg.get_callback_queue", return_value=jobs):
            view._drain_dpg_callbacks()
        for callback in callbacks:
            callback.assert_called_once_with()

    def test_digitizer_in_front_still_discards_background_menu_callbacks(self):
        from WinUx.view import WinUXView
        self.hit_root = self.digitizer
        view = object.__new__(WinUXView)
        view._alive = True
        view._dpg_callbacks = deque()
        callback = Mock()
        with patch("WinUx.view.dpg.get_callback_queue", return_value=[(callback,)]):
            view._drain_dpg_callbacks()
        callback.assert_not_called()

    def test_actual_digitizer_client_still_blocks_background_input(self):
        self.hit_root = self.digitizer
        self.assertTrue(gate.native_background_input_blocked())

    def test_another_application_on_top_is_not_mistaken_for_digitizer(self):
        self.hit_root = 999
        self.assertIsNone(gate._native_surface_under_pointer())

    def test_nested_native_child_is_resolved_to_its_registered_toplevel(self):
        self.user32.WindowFromPoint.return_value = 201
        self.hit_root = self.digitizer
        self.assertEqual(gate._native_surface_under_pointer(), self.digitizer)
        self.user32.GetAncestor.assert_called_once_with(201, 2)

    def test_real_modal_still_blocks_main_regardless_of_cursor_window(self):
        gate._native_modal_tokens.add("modal-confirm")
        self.assertTrue(gate.native_background_input_blocked())

    def test_destroyed_registered_surface_is_removed(self):
        self.user32.IsWindow.return_value = False
        self.assertIsNone(gate._native_surface_under_pointer())
        self.assertNotIn(self.digitizer, gate._native_pointer_hwnds)


class NativeCloseDispatchTests(unittest.TestCase):
    def test_native_close_is_not_lost_during_post_escape_input_release_guard(self):
        from WinUx.view import WinUXView
        for discard in (True, False):
            with self.subTest(discard=discard):
                view = object.__new__(WinUXView)
                view._alive = True
                view._dpg_callbacks = deque()
                view._close_callback = Mock()
                scheduled = []
                view.after = lambda delay, callback, *args: scheduled.append((callback, args))
                background_click = Mock()
                jobs = [(background_click,), (view._request_close,)]
                with patch("WinUx.view.dpg.get_callback_queue", return_value=jobs), \
                        patch("WinUx.view.native_background_input_blocked", return_value=True):
                    view._drain_dpg_callbacks(discard=discard)
                background_click.assert_not_called()
                for callback, args in scheduled:
                    callback(*args)
                view._close_callback.assert_called_once_with()
                self.assertFalse(view._dpg_callbacks)


if __name__ == "__main__":
    unittest.main()
