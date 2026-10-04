"""Virtualized rendered-row registry for :class:`ExplorerListView`.

The ListView keeps the full logical item model while only materializing Dear
PyGui draw primitives for the visible window plus a small overscan margin.
Rendered rows are pooled and rebound to logical indices as scrolling moves the
window, so selection, rename, hit-testing and drag/drop continue to operate on
stable logical indices without requiring one native draw object set per item.
"""
from __future__ import annotations

import dearpygui.dearpygui as dpg

from .explorer_virtualization import compute_render_window


class ExplorerRowRegistryMixin:
    """Own the mapping between logical item indices and rendered row slots."""

    def _row_virtualization_active(self):
        return len(self.items) >= int(self.VIRTUALIZATION_THRESHOLD)

    def _row_render_window(self):
        try:
            scroll_y = float(dpg.get_y_scroll(self.body_window))
        except Exception:
            scroll_y = 0.0
        try:
            _width, viewport_height = map(float, dpg.get_item_rect_size(self.body_window))
        except Exception:
            viewport_height = 0.0
        return compute_render_window(
            len(self.items), self.ROW_HEIGHT, scroll_y, viewport_height,
            threshold=self.VIRTUALIZATION_THRESHOLD,
            overscan=self.VIRTUALIZATION_OVERSCAN_ROWS,
            fallback_rows=self.VIRTUALIZATION_FALLBACK_ROWS,
        )

    def _row_for_index(self, index):
        if index is None:
            return None
        return self._row_registry.get(int(index))

    def _rendered_row_indices(self):
        return tuple(sorted(self._row_registry))

    def _reset_row_registry(self):
        self._row_items = []
        self._row_registry = {}
        self._row_render_window_cache = None

    def _replace_row_registry(self, rows):
        rows = sorted(rows, key=lambda row: int(row.get("index", -1)))
        self._row_items = rows
        self._row_registry = {
            int(row["index"]): row
            for row in rows
            if row.get("index") is not None
        }

    def _sync_virtual_rows(self, force=False):
        """Materialize the desired logical row window, reusing old primitives."""
        start, end = self._row_render_window()
        desired = tuple(range(start, end))
        if not force and desired == self._row_render_window_cache:
            return False
        self._row_render_window_cache = desired

        old = dict(self._row_registry)
        keep = {index: old.pop(index) for index in desired if index in old}
        reusable = list(old.values())
        rows = list(keep.values())

        missing = [index for index in desired if index not in keep]
        for index in missing:
            if reusable:
                row = reusable.pop()
                self._bind_body_row(row, index)
            else:
                row = self._create_body_row(index)
            rows.append(row)

        # Rows outside the desired window are kept only as a bounded pool while
        # rebinding above. Any excess primitives are actually removed so native
        # object count remains proportional to the viewport, not directory size.
        for row in reusable:
            self._destroy_body_row(row)

        self._replace_row_registry(rows)
        return True

    def _refresh_row_registry_content(self):
        """Rebind metadata for materialized rows without changing the window."""
        for row in self._row_items:
            index = int(row.get("index", -1))
            if 0 <= index < len(self.items):
                self._bind_body_row(row, index, preserve_geometry=True)

    def _row_registry_can_reuse(self, old_topology, new_topology):
        if old_topology != new_topology:
            return False
        if not self._header_items or not dpg.does_item_exist(self.body_canvas):
            return False
        if self._cell_values or self._cell_styles or self._item_icons:
            return False
        if self._row_virtualization_active():
            return True
        return len(self._row_items) == len(self.items)
