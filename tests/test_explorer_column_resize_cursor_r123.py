from types import SimpleNamespace

from WinUx.ui.components.explorer_native_hook import ExplorerNativeHook


def _hook_with_view():
    view = SimpleNamespace(
        SEPARATOR_HIT=8.0,
        MIN_COLUMN_WIDTH=40,
        HEADER_HEIGHT=26,
        header_canvas='header',
        window_tag='pane',
        _column_widths={'name': 180.0, 'date': 120.0, 'type': 90.0},
        _visible_columns=lambda: [
            {'key': 'name', 'resizable': True},
            {'key': 'date', 'resizable': True},
            {'key': 'type', 'resizable': False},
        ],
    )
    rects = {
        'header': (100.0, 200.0, 490.0, 226.0),
        'pane': (100.0, 180.0, 490.0, 600.0),
    }
    view._safe_item_rect = lambda tag: rects.get(tag)
    hook = ExplorerNativeHook(view, SimpleNamespace(), SimpleNamespace())
    return view, hook


def test_native_cursor_geometry_keeps_screen_space_header_coordinates():
    _, hook = _hook_with_view()
    hook._native_hwnd = 999
    hook._update_native_cursor_geometry()

    # _safe_item_rect already returns screen-space coordinates. They must stay
    # exactly at x=100/y=200 instead of being shifted by ClientToScreen again.
    assert hook._native_header_screen_rect == (100.0, 200.0, 490.0, 226.0)
    assert hook._native_separator_screen_x == (280.0, 400.0)
    assert hook._native_separator_keys == ('name', 'date')


def test_native_separator_hit_returns_resizable_column_key():
    _, hook = _hook_with_view()
    hook._update_native_cursor_geometry()

    assert hook._separator_key_at_screen(280, 212) == 'name'
    assert hook._separator_key_at_screen(405, 212) == 'date'
    assert hook._separator_key_at_screen(450, 212) is None
    assert hook._separator_key_at_screen(280, 250) is None


def test_resize_cursor_uses_native_screen_fallback_when_renderer_hover_misses(monkeypatch):
    import WinUx.ui.components.explorer_list_view as module
    from WinUx.ui.components.explorer_list_view import ExplorerListView

    calls = []
    dummy = SimpleNamespace(
        _rename_active=False,
        _resize_key=None,
        _hover_separator_key=None,
        _native_cursor_hook_active=True,
        _native_cursor_sizewe=None,
        _native_hwnd=None,
        _native_hook=SimpleNamespace(_separator_key_under_native_cursor=lambda: 'name'),
        _context_menu_is_visible=lambda: False,
        _header_mouse_position=lambda: (False, 0.0),
        _separator_at=lambda x: None,
        _set_separator_hover_state=lambda key: calls.append(('hover', key)),
        _set_mouse_cursor=lambda name: calls.append(('cursor', name)),
        _update_native_cursor_geometry=lambda: calls.append(('geometry', None)),
    )
    monkeypatch.setattr(module, '_overlay_window_owns_input', lambda: False)
    monkeypatch.setattr(module.os, 'name', 'nt')

    previous = ExplorerListView._resize_cursor_owner
    try:
        ExplorerListView._resize_cursor_owner = None
        ExplorerListView._update_resize_cursor(dummy)
    finally:
        ExplorerListView._resize_cursor_owner = previous

    assert dummy._hover_separator_key == 'name'
    assert ('cursor', 'mvMouseCursor_ResizeEW') in calls
