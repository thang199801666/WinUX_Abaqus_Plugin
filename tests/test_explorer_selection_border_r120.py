from types import SimpleNamespace

from WinUx.ui.components.explorer_rendering import ExplorerRenderingMixin
from WinUx.ui.components.explorer_themes import ListViewThemeManager


class _DummyView:
    _row_visual_style = ExplorerRenderingMixin._row_visual_style

    def __init__(self, cfg, *, has_focus, current_index=0, selected=(0,), hover_index=None):
        self.selected = set(selected)
        self.hover_index = hover_index
        self._current_index = current_index
        self.theme_config = cfg
        self._has_focus = has_focus
        self._item_drag_active = False
        self._drop_target_index = None
        self._external_drop_target_index = None
        self._alternating_row_colors = False
        self.items = [SimpleNamespace(data={}) for _ in range(8)]


def test_explorer_theme_uses_windows_explorer_like_selected_border():
    _, explorer = ListViewThemeManager.resolve('Explorer')
    assert explorer['selected_fill'] == (204, 232, 255, 255)
    assert explorer['selected_border'] == (153, 209, 255, 255)
    assert explorer['inactive_selected_fill'] == (225, 233, 240, 255)
    assert explorer['inactive_selected_border'] == (185, 197, 210, 255)
    assert explorer['selected_border_width'] == 1.0


def test_every_active_selected_row_gets_solid_border():
    _, cfg = ListViewThemeManager.resolve('Explorer')
    view = _DummyView(cfg, has_focus=True, current_index=0, selected=(0, 1, 2))
    for index in (0, 1, 2):
        fill, border, thickness = view._row_visual_style(index)
        assert fill == cfg['selected_fill']
        assert border == (153, 209, 255, 255)
        assert thickness == 1.0


def test_every_inactive_selected_row_keeps_solid_border():
    _, cfg = ListViewThemeManager.resolve('Explorer')
    view = _DummyView(cfg, has_focus=False, current_index=0, selected=(0, 1, 2))
    for index in (0, 1, 2):
        fill, border, thickness = view._row_visual_style(index)
        assert fill == cfg['inactive_selected_fill']
        assert border == (185, 197, 210, 255)
        assert thickness == 1.0


def test_hovered_selected_row_keeps_solid_border():
    _, cfg = ListViewThemeManager.resolve('Explorer')
    view = _DummyView(cfg, has_focus=True, current_index=0, selected=(0, 1), hover_index=1)
    fill, border, thickness = view._row_visual_style(1)
    assert fill == cfg['selected_hover_fill']
    assert border == (153, 209, 255, 255)
    assert thickness == 1.0


def test_incremental_selection_repaints_only_changed_and_current_rows():
    class _FastView:
        _update_selection_draws = ExplorerRenderingMixin._update_selection_draws

        def __init__(self):
            self.items = [object()] * 1000
            self.selected = {10, 20, 30}
            self._current_index = 30
            self._has_focus = True
            self._visual_selected_cache = {10, 20}
            self._visual_current_cache = 20
            self._visual_focus_cache = True
            self.updated = []

        def _rendered_row_indices(self):
            raise AssertionError('incremental path must not scan every rendered row')

        def _update_row_visual(self, index):
            self.updated.append(index)

    view = _FastView()
    view._update_selection_draws()
    assert set(view.updated) == {20, 30}
    assert len(view.updated) == 2
    assert view._visual_selected_cache == {10, 20, 30}


def test_selection_renderer_contains_no_dashed_outline_path():
    import inspect
    source = inspect.getsource(ExplorerRenderingMixin)
    assert '_focus_outline_geometry' not in source
    assert '_configure_focus_outline' not in source
    assert '_row_uses_dashed_outline' not in source


def test_selected_row_bounds_are_integer_pixel_aligned_with_two_pixel_row_spacing():
    from pathlib import Path
    root = Path(__file__).resolve().parents[1]
    layout = (root / 'WinUx' / 'ui' / 'components' / 'explorer_layout.py').read_text(encoding='utf-8')
    view = (root / 'WinUx' / 'ui' / 'components' / 'explorer_list_view.py').read_text(encoding='utf-8')
    assert 'ROW_SPACING = 2' in view
    assert 'int(round(y0)) + top_inset' in layout
    assert 'int(round(y1)) - bottom_inset' in layout
    assert 'top_inset = row_spacing // 2' in layout
    assert 'bottom_inset = row_spacing - top_inset' in layout


def test_selected_border_uses_filled_rectangles_not_antialiased_outline_stroke():
    import inspect
    source = inspect.getsource(ExplorerRenderingMixin._configure_crisp_selected_surface)
    assert 'fill=border' in source
    assert 'color=(0, 0, 0, 0)' in source
    assert 'thickness=0.0' in source
    assert '_ensure_selection_inner' in source
