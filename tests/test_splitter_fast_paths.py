"""Avoid expensive input-gate scans for unrelated idle splitter controls."""
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import Mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import run_winux
run_winux._configure_bundled_dependencies(str(ROOT))
from WinUx.ui.behaviors.splitter_behavior import SplitterLayoutBehaviorMixin as Splitters
from WinUx.ui.components.explorer_layout import ExplorerLayoutMixin


CASES = (
    ('file_panel', '_update_file_panel_splitter_input', '_update_file_panel_splitter_cursor',
     '_file_panel_splitter_hit_test', '_end_file_panel_splitter_drag'),
    ('horizontal', '_update_horizontal_splitter_input', '_update_horizontal_splitter_cursor',
     '_horizontal_splitter_native_hovered', '_end_horizontal_splitter_drag'),
    ('console', '_update_console_splitter_input', '_update_console_splitter_cursor',
     '_console_splitter_native_hovered', '_end_console_splitter_drag'),
    ('plot', '_update_job_plot_splitter_input', '_update_job_plot_splitter_cursor',
     '_job_plot_splitter_native_hovered', '_end_job_plot_splitter_drag'),
)


class SplitterFastPathTests(unittest.TestCase):
    def host(self):
        host = SimpleNamespace(
            _left_mouse_button_down=Mock(return_value=False),
            _splitter_input_blocked=Mock(return_value=True),
            _stable_splitter_cursor_hover=Mock(),
            _console_dock_visible=True, _console_dock_area='bottom',
            _job_plot_dock_visible=Mock(return_value=True),
            _normalize_console_dock_area=lambda value: value,
            _splitter_cursor_active=False)
        for prefix, _input, _cursor, hit, end in CASES:
            setattr(host, '_' + prefix + '_splitter_dragging', False)
            setattr(host, '_' + prefix + '_splitter_mouse_was_down', True)
            setattr(host, '_' + prefix + '_splitter_cursor_active', False)
            setattr(host, '_' + prefix + '_splitter_owner', object())
            setattr(host, hit, Mock(return_value=False))
            setattr(host, end, Mock())
        return host

    def test_idle_input_skips_gate_but_resets_press_history(self):
        for prefix, method, *_rest in CASES:
            with self.subTest(splitter=prefix):
                host = self.host()
                getattr(Splitters, method)(host)
                host._splitter_input_blocked.assert_not_called()
                self.assertFalse(getattr(host, '_' + prefix + '_splitter_mouse_was_down'))

    def test_release_and_blocked_drag_still_end_capture(self):
        for prefix, method, _cursor, _hit, end in CASES:
            with self.subTest(splitter=prefix):
                host = self.host()
                setattr(host, '_' + prefix + '_splitter_dragging', True)
                getattr(Splitters, method)(host)
                host._splitter_input_blocked.assert_called_once()
                getattr(host, end).assert_called_once()

    def test_new_press_always_checks_live_pointer_ownership(self):
        for prefix, method, *_rest in CASES:
            with self.subTest(splitter=prefix):
                host = self.host()
                host._left_mouse_button_down.return_value = True
                getattr(Splitters, method)(host)
                host._splitter_input_blocked.assert_called_once()
                self.assertTrue(getattr(host, '_' + prefix + '_splitter_mouse_was_down'))

    def test_cursor_away_from_handle_skips_gate(self):
        for prefix, _input, method, hit, _end in CASES:
            with self.subTest(splitter=prefix):
                host = self.host()
                getattr(Splitters, method)(host)
                getattr(host, hit).assert_called_once_with(ignore_pointer_capture=True)
                host._splitter_input_blocked.assert_not_called()

    def test_hover_checks_live_gate_before_showing_resize_cursor(self):
        for prefix, _input, method, hit, _end in CASES:
            with self.subTest(splitter=prefix):
                host = self.host()
                getattr(host, hit).return_value = True
                getattr(Splitters, method)(host)
                host._splitter_input_blocked.assert_called_once()
                host._stable_splitter_cursor_hover.assert_not_called()

    def test_dirty_frame_does_not_reflow_entire_app_during_file_split_drag(self):
        host = SimpleNamespace(
            _layout_updating=False, _alive=True, _layout_items_exist=lambda: True,
            _resize_last_event=0, _resize_settle_delay=.15,
            _file_panel_splitter_dragging=True, _layout_dirty=True,
            _pending_viewport_size=None, _content_size=Mock(return_value=(800, 600)),
            _job_plot_dock_visible=Mock(return_value=False),
            _report_splitter_exception=Mock())
        Splitters._apply_split_layout(host)
        host._content_size.assert_not_called()
        self.assertTrue(host._layout_dirty)

    def test_native_visibility_callbacks_defer_row_layout_during_owner_resize(self):
        listview = SimpleNamespace(_owner_resize_interactive=True, _resize_key=None,
                                   _resize_layout_pending=False)
        ExplorerLayoutMixin._layout_all(listview)
        self.assertTrue(listview._resize_layout_pending)


if __name__ == '__main__':
    unittest.main(verbosity=2)
