"""Shared Explorer scrollbar chrome without reparenting scroll-area content."""
from .dearpygui_scroller import DpgScrollerArrowOverlay, SharedScrollerMetrics


_candidates = {}
_overlays = {}


def register_scroll_surface(backend, item, *, viewport=None):
    """Skin an existing scroll owner, optionally bounded by a fixed viewport.

    Scrolling tables omit window geometry; their host supplies only bounds,
    while the table remains the sole owner of native scroll values/ranges.
    """
    _candidates.setdefault(id(backend), {})[item] = viewport


def _ancestors(backend, item):
    result = []
    while item:
        result.append(item)
        item = backend.get_item_parent(item)
    return result


class _ViewportScroller(DpgScrollerArrowOverlay):
    """Paint over the existing native gutter, not a second scrolling widget."""

    def __init__(self, backend, item, *, viewport=None, **options):
        self.owner_root = _ancestors(backend, item)[-1]
        self.viewport_item = viewport or item
        self._lanes = {}
        self._lane_rects = {}
        super().__init__(backend, item, 'dearuiqt.shared.scroller.{}'.format(item), **options)

    def _ensure_items(self):
        if not self.dpg.does_item_exist(self.container):
            self.dpg.add_group(parent=self.owner_root, tag=self.container, pos=(0, 0))
        # Reuse the File List's exact thumb, arrows, hit surfaces and animation.
        # An existing group bypasses its optional child-window wrapper.
        super()._ensure_items()
        # Parent drawlists render below a child's native scrollbar regardless
        # of submission order. Use narrow child surfaces *only in the gutters*
        # so the shared skin paints above it without covering content controls.
        if not self.dpg.does_item_exist(self.theme):
            with self.dpg.theme(tag=self.theme):
                with self.dpg.theme_component(self.dpg.mvAll):
                    self.dpg.add_theme_style(self.dpg.mvStyleVar_WindowPadding, 0, 0)
                    self.dpg.add_theme_style(self.dpg.mvStyleVar_ItemSpacing, 0, 0)
                    self.dpg.add_theme_style(self.dpg.mvStyleVar_ChildBorderSize, 0)
                    self.dpg.add_theme_color(self.dpg.mvThemeCol_ChildBg, (0, 0, 0, 0))
        for axis in ('v', 'h'):
            lane = self.tag + '_' + axis + '_lane'
            layer = lane + '_draw'
            self.dpg.add_child_window(parent=self.container, tag=lane, width=1, height=1,
                                      border=False, no_scrollbar=True, no_scroll_with_mouse=True, show=False)
            self.dpg.bind_item_theme(lane, self.theme)
            self.dpg.add_drawlist(1, 1, parent=lane, tag=layer)
            self._lanes[axis] = (lane, layer)
            for key, item in self._parts.items():
                if key.startswith(axis + '_') or key == 'corner' and axis == 'v':
                    self.dpg.move_item(item, parent=layer)
            for key in (('up', 'down') if axis == 'v' else ('left', 'right')):
                self.dpg.move_item(self._rects[key], parent=layer)
                self.dpg.move_item(self._arrows[key], parent=layer)
            if axis in self._hits:
                self.dpg.move_item(self._hits[axis], parent=lane, before=layer)
        self.dpg.configure_item(self.layer, show=False)

    def _fit_content(self):
        # Native gutters continue to reserve layout space and provide wheel
        # scrolling. Never change the target's dimensions, parent or policies.
        return

    def _ensure_hit_items(self):
        super()._ensure_hit_items()
        for axis, (lane, layer) in self._lanes.items():
            if axis in self._hits:
                self.dpg.move_item(self._hits[axis], parent=lane, before=layer)

    def _target_rect(self):
        rect = self._window_rect(self.viewport_item, clip=True)
        root = self._window_rect(self.owner_root)
        if rect is not None and root is not None:
            x0, y0, x1, y1 = rect
            thickness = SharedScrollerMetrics.THICKNESS
            self._lane_rects = {'v': (x1 - thickness, y0, x1, y1),
                                'h': (x0, y1 - thickness, x1, y1)}
            for axis, (lane, layer) in self._lanes.items():
                a, b, c, d = self._lane_rects[axis]
                self._configure_chrome(lane, pos=(a - root[0], b - root[1]), width=round(c - a), height=round(d - b))
                self._configure_chrome(layer, width=round(c - a), height=round(d - b))
        return rect

    def _fit_hit_items(self, axes):
        for axis, (lane, layer) in self._lanes.items():
            data = axes.get(axis)
            self._configure_chrome(lane, show=data is not None)
            item = self._hits.get(axis)
            if item is None:
                continue
            if data is None:
                self._configure_chrome(item, show=False)
                continue
            x0, y0, x1, y1 = data['hit']
            a, b, _, _ = self._lane_rects[axis]
            self._configure_chrome(item, pos=(x0 - a, y0 - b),
                                    width=max(1, round(x1 - x0)), height=max(1, round(y1 - y0)), show=True)

    def _set_part(self, key, rect, show=True, **options):
        if key.endswith('_mask') and rect[2] > rect[0] and rect[3] > rect[1]:
            show = True  # Cover native chrome even while our thumb is collapsed.
        origin = self._origin
        lane = self._lane_rects.get('h' if key.startswith('h_') else 'v')
        if lane is not None:
            self._origin = lane[:2]
        try:
            super()._set_part(key, rect, show, **options)
        finally:
            self._origin = origin

    def _set_cap(self, key, rect, points, show=True, **options):
        origin = self._origin
        lane = self._lane_rects.get('h' if key in ('left', 'right') else 'v')
        if lane is not None:
            self._origin = lane[:2]
        try:
            super()._set_cap(key, rect, points, show, **options)
        finally:
            self._origin = origin

    def hide(self):
        super().hide()
        for lane, _ in self._lanes.values():
            if self.dpg.does_item_exist(lane):
                self._configure_chrome(lane, show=False)

    def _foreground_input_blocked(self):
        from .. import input_gate as gate
        from ..core.application import QApplication
        ancestors = _ancestors(self.dpg, self.target_item)
        app = QApplication.instance()
        modal = app.activeModalWidget() if app is not None else None
        if modal is not None and getattr(modal, 'tag', None) not in ancestors:
            return True
        if gate.popup_input_is_blocked(self):
            return True
        if gate.native_background_input_blocked():
            # A modal blocks its *owner*, not its own scrolling controls.
            from .native_windows import NativeWindowBackend
            own_hwnd = NativeWindowBackend(self.dpg).winId(self.owner_root)
            hit_hwnd = gate._native_surface_under_pointer()
            if not own_hwnd or own_hwnd != hit_hwnd:
                return True
        hit = gate.protected_surface_under_pointer(
            exclude_items=tuple(ancestors) + tuple(self._hits.values()))
        return hit is not None

    def destroy(self):
        if self._destroyed:
            return
        self._destroyed = True
        self.hide()
        for item in self._hits.values():
            self._gate().unregister_pointer_protected_item(item)
        for item in (self.container, self._hit_theme, self.theme):
            if self.dpg.does_item_exist(item):
                self.dpg.delete_item(item)
        self._hits.clear()
        self._chrome_config.clear()


def update_shared_scrollers(backend):
    entries = _overlays.setdefault(id(backend), {})
    candidates = _candidates.get(id(backend), {})
    for target in tuple(candidates):
        overlay = entries.get(target)
        if not backend.does_item_exist(target):
            candidates.pop(target, None)
            if overlay is not None:
                overlay.destroy()
                entries.pop(target, None)
            continue
        config = backend.get_item_configuration(target)
        if overlay is not None and (not backend.does_item_exist(overlay.container) or
                                    _ancestors(backend, target)[-1] != overlay.owner_root):
            overlay.destroy()
            entries.pop(target, None)
            overlay = None
        viewport = candidates[target]
        if viewport is not None:
            vertical = bool(config.get('scrollY', False))
            horizontal = bool(config.get('scrollX', False))
        else:
            vertical = not config.get('no_scrollbar', False)
            horizontal = bool(config.get('horizontal_scrollbar', False)) and vertical
        if not vertical and not horizontal:
            # File List/Console already have managed scrollers and hide their
            # native bars. Explicit ScrollBarAlwaysOff must also remain off.
            if overlay is not None:
                overlay.hide()
            continue
        if overlay is None:
            if (not backend.is_item_shown(target) or
                    (not vertical or backend.get_y_scroll_max(target) <= 0) and
                    (not horizontal or backend.get_x_scroll_max(target) <= 0)):
                continue
            overlay = entries[target] = _ViewportScroller(
                backend, target, viewport=viewport, vertical=vertical, horizontal=horizontal)
        overlay.vertical, overlay.horizontal = vertical, horizontal
        if (horizontal and 'h' not in overlay._hits or
                vertical and 'v' not in overlay._hits):
            overlay._ensure_hit_items()
        overlay.update()


def clear_shared_scrollers(backend):
    for overlay in _overlays.pop(id(backend), {}).values():
        overlay.destroy()
    _candidates.pop(id(backend), None)
