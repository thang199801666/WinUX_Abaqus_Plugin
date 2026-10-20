"""Regression coverage for acquiring the File/Job Viewer resize gutter."""
import ast
from pathlib import Path
import unittest
from unittest.mock import Mock
from types import SimpleNamespace


def load_splitter():
    source = Path(__file__).resolve().parents[1] / 'WinUx/ui/behaviors/splitter_behavior.py'
    tree = ast.parse(source.read_text(encoding='utf-8'))
    tree.body = [node for node in tree.body if isinstance(node, ast.ClassDef)]
    backend = Mock()
    backend.does_item_exist.return_value = True
    backend.is_item_hovered.return_value = False
    backend.is_item_active.return_value = False
    backend.get_item_pos.return_value = (0, 400)
    namespace = {'dpg': backend, 'acquire_pointer_input': Mock(return_value=True),
                 'release_pointer_input': Mock()}
    exec(compile(tree, str(source), 'exec'), namespace)
    view = namespace['SplitterLayoutBehaviorMixin']()
    view.horizontal_splitter_hitbox = 'gutter'
    view._horizontal_splitter_owner = object()
    view._horizontal_splitter_dragging = False
    view._splitter_input_blocked = Mock(return_value=False)
    view._job_view_header_owns_pointer = Mock(return_value=True)
    view._mouse_over_item_rect = Mock(return_value=False)
    view._rename_is_active = Mock(return_value=False)
    view._left_mouse_button_down = Mock(return_value=True)
    view._native_cursor_screen_y = Mock(return_value=1000)
    view._cancel_explorer_gestures_for_splitter = Mock()
    view._clear_splitter_selections = Mock()
    return view, backend, namespace


class FileJobSplitterTests(unittest.TestCase):
    def configure_all_splitters(self, view):
        for prefix in ("file_panel", "console", "plot"):
            setattr(view, "_" + prefix + "_splitter_owner", object())
            setattr(view, "_" + prefix + "_splitter_dragging", False)
        view.file_panel_separator_hitbox = "file_gutter"
        view.console_separator_hitbox = "console_gutter"
        view.job_plot_separator_hitbox = "plot_gutter"
        view._console_dock_visible = True
        view._job_plot_dock_visible = Mock(return_value=True)

    def test_force_path_cannot_bypass_dialog_or_list_capture(self):
        for name in ("file_panel", "horizontal", "console", "job_plot"):
            with self.subTest(splitter=name):
                view, backend, namespace = load_splitter()
                self.configure_all_splitters(view)
                backend.is_item_active.return_value = True
                view._splitter_input_blocked.return_value = True
                getattr(view, "_begin_" + name + "_splitter_drag")(force_new_press=True)
                namespace["acquire_pointer_input"].assert_not_called()
                view._cancel_explorer_gestures_for_splitter.assert_not_called()
                view._clear_splitter_selections.assert_not_called()

    def test_hover_and_geometry_never_promote_a_list_press_to_resize(self):
        view, backend, namespace = load_splitter()
        self.configure_all_splitters(view)
        backend.is_item_hovered.return_value = True  # previous frame hovered divider
        view._mouse_over_item_rect.return_value = True  # old coordinate aliases
        view._job_view_header_owns_pointer.return_value = False
        for name in ("file_panel", "horizontal", "console", "job_plot"):
            getattr(view, "_begin_" + name + "_splitter_drag")(force_new_press=True)
        namespace["acquire_pointer_input"].assert_not_called()
        view._cancel_explorer_gestures_for_splitter.assert_not_called()
        view._mouse_over_item_rect.assert_not_called()
        assert not view._horizontal_splitter_native_hovered()

    def test_failed_capture_never_cancels_existing_list_gesture(self):
        view, backend, namespace = load_splitter()
        self.configure_all_splitters(view)
        backend.is_item_active.return_value = True
        namespace["acquire_pointer_input"].return_value = False
        for name in ("file_panel", "horizontal", "console", "job_plot"):
            getattr(view, "_begin_" + name + "_splitter_drag")(force_new_press=True)
        view._cancel_explorer_gestures_for_splitter.assert_not_called()

    def test_pre_dispatch_waits_for_real_activation_then_claims_before_callbacks(self):
        view, backend, namespace = load_splitter()
        view._splitter_press_was_down = False
        view._job_view_header_owns_pointer.return_value = False
        view._console_splitter_native_hovered = Mock(return_value=False)
        view._job_plot_splitter_native_hovered = Mock(return_value=False)
        view._begin_file_panel_splitter_drag = Mock()
        backend.is_item_hovered.return_value = True
        view._pre_dispatch_splitter_input()  # hardware down, backend not updated
        namespace["acquire_pointer_input"].assert_not_called()
        backend.is_item_active.side_effect = lambda item: item == "gutter"
        view._pre_dispatch_splitter_input()  # same held press, now actually resolved
        assert view._horizontal_splitter_dragging
        namespace["acquire_pointer_input"].assert_called_once_with(view._horizontal_splitter_owner)

    def test_blocked_poll_preserves_held_press_history_for_all_splitters(self):
        view, backend, _ = load_splitter()
        self.configure_all_splitters(view)
        view._splitter_input_blocked.return_value = True
        for name in ("file_panel", "horizontal", "console", "plot"):
            setattr(view, "_" + name + "_splitter_mouse_was_down", False)
        for method in ("file_panel", "horizontal", "console", "job_plot"):
            getattr(view, "_update_" + method + "_splitter_input")()
        for name in ("file_panel", "horizontal", "console", "plot"):
            assert getattr(view, "_" + name + "_splitter_mouse_was_down")

    def test_native_dialog_cancels_resize_instead_of_resuming_old_drag(self):
        view, _, namespace = load_splitter()
        self.configure_all_splitters(view)
        for name in ("file_panel", "horizontal", "console", "plot"):
            setattr(view, "_" + name + "_splitter_dragging", True)
        view._cancel_splitter_interactions()
        for name in ("file_panel", "horizontal", "console", "plot"):
            assert not getattr(view, "_" + name + "_splitter_dragging")
            assert getattr(view, "_" + name + "_splitter_mouse_was_down")
        assert namespace["release_pointer_input"].call_count == 4
        assert not view._splitter_cursor_active

    def test_physical_release_is_authoritative_over_stale_dpg_down(self):
        view, backend, namespace = load_splitter()
        # Exercise the real method rather than the default test fixture hook.
        del view._left_mouse_button_down
        backend.is_mouse_button_down.return_value = True
        namespace["os"] = SimpleNamespace(name="nt")
        namespace["ctypes"] = SimpleNamespace(windll=SimpleNamespace(
            user32=SimpleNamespace(GetAsyncKeyState=Mock(return_value=0))))
        assert not view._left_mouse_button_down()

    def test_actual_hover_beats_stale_job_header_geometry(self):
        view, backend, _ = load_splitter()
        view._left_mouse_button_down.return_value = False
        backend.is_item_hovered.return_value = True
        self.assertTrue(view._horizontal_splitter_native_hovered())
        view._job_view_header_owns_pointer.assert_not_called()

    def test_header_retains_priority_when_gutter_does_not_own_pointer(self):
        view, _, _ = load_splitter()
        self.assertFalse(view._horizontal_splitter_native_hovered(ignore_pointer_capture=True))

    def test_item_click_acquires_drag_when_polling_hover_is_missing(self):
        view, _, namespace = load_splitter()
        view._on_horizontal_splitter_pressed()
        self.assertTrue(view._horizontal_splitter_dragging)
        self.assertEqual(view._horizontal_splitter_drag_start_top, 400)
        namespace['acquire_pointer_input'].assert_called_once_with(view._horizontal_splitter_owner)
        view._cancel_explorer_gestures_for_splitter.assert_called_once_with()

    def test_item_click_respects_other_pointer_owner(self):
        view, _, namespace = load_splitter()
        view._splitter_input_blocked.return_value = True
        view._on_horizontal_splitter_pressed()
        self.assertFalse(view._horizontal_splitter_dragging)
        namespace['acquire_pointer_input'].assert_not_called()

    def test_missed_release_does_not_start_a_stuck_drag(self):
        view, _, namespace = load_splitter()
        view._left_mouse_button_down.return_value = False
        view._on_horizontal_splitter_pressed()
        self.assertFalse(view._horizontal_splitter_dragging)
        namespace['acquire_pointer_input'].assert_not_called()

    def test_release_relinquishes_capture_and_requests_final_layout(self):
        view, _, namespace = load_splitter()
        view._on_horizontal_splitter_pressed()
        view._end_horizontal_splitter_drag()
        self.assertFalse(view._horizontal_splitter_dragging)
        self.assertTrue(view._layout_dirty)
        namespace['release_pointer_input'].assert_called_once_with(view._horizontal_splitter_owner)
