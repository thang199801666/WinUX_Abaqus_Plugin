from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_file_listview_body_keeps_native_mouse_wheel_enabled():
    source = (ROOT / 'WinUx' / 'ui' / 'components' / 'explorer_rendering.py').read_text(encoding='utf-8')
    block = source.split('self.body_window =', 1)[1].split('self._body_window_widget.setTheme', 1)[0]
    assert 'no_scroll_with_mouse=False' in block


def test_native_hook_does_not_intercept_or_consume_mouse_wheel():
    source = (ROOT / 'WinUx' / 'ui' / 'components' / 'explorer_native_hook.py').read_text(encoding='utf-8')
    assert 'WM_MOUSEWHEEL' not in source
    assert 'WM_MOUSEHWHEEL' not in source
    assert '_pending_wheel_events' not in source
    assert 'drain_wheel_events' not in source


def test_explorer_listview_has_no_custom_smooth_wheel_controller():
    source = (ROOT / 'WinUx' / 'ui' / 'components' / 'explorer_list_view.py').read_text(encoding='utf-8')
    assert 'SmoothScrollController' not in source
    assert '_apply_smooth_wheel_delta' not in source
    assert '_update_smooth_scroll' not in source
