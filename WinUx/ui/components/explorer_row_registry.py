"""Full rendered-row registry for :class:`ExplorerListView`.

Every logical item owns a rendered row, independent of scroll position and
viewport size. Scrolling never removes or replaces rows.
"""
from __future__ import annotations

class ExplorerRowRegistryMixin:
    """Own the mapping between logical item indices and rendered row slots."""

    def _row_virtualization_active(self):
        return False

    def _row_render_window(self):
        return (0, len(self.items))

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
        # The body canvas may have been cleared/rebuilt. Reset retained visual
        # caches so the next paint initializes only the current row state.
        self._visual_selected_cache = None
        self._visual_current_cache = None
        self._visual_focus_cache = None

    def _replace_row_registry(self, rows):
        rows = sorted(rows, key=lambda row: int(row.get("index", -1)))
        self._row_items = rows
        self._row_registry = {
            int(row["index"]): row
            for row in rows
            if row.get("index") is not None
        }

    def _sync_virtual_rows(self, force=False):
        """Render all logical rows, reusing primitives when the model changes."""
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

        # Remove excess primitives only when the logical list shrinks.
        for row in reusable:
            self._destroy_body_row(row)

        self._replace_row_registry(rows)
        return True

    def _refresh_row_registry_content(self):
        """Rebind metadata and report rows whose rendered state changed."""
        changed = set()
        for row in self._row_items:
            index = int(row.get("index", -1))
            if 0 <= index < len(self.items):
                self._bind_body_row(row, index, preserve_geometry=True)
                if row.get("content_changed", False):
                    changed.add(index)
        return changed

    def _row_registry_can_reuse(self, old_topology, new_topology):
        if old_topology != new_topology:
            return False
        canvas = getattr(self, "_body_canvas_widget", None)
        if not self._header_items or canvas is None or not canvas.exists():
            return False
        if self._cell_values or self._cell_styles or self._item_icons:
            return False
        return len(self._row_items) == len(self.items)

    def _row_registry_can_reconcile(self, old_topology, new_topology):
        """Allow watcher refreshes to keep primitives across inserts/reorders."""
        canvas = getattr(self, "_body_canvas_widget", None)
        if not self._header_items or canvas is None or not canvas.exists():
            return False
        if self._cell_values or self._cell_styles or self._item_icons:
            return False
        if len(self._row_items) != len(old_topology):
            return False
        if len(set(old_topology)) != len(old_topology) or len(set(new_topology)) != len(new_topology):
            return False
        columns = {column["key"] for column in self._visible_columns()}
        return (set(self._row_registry) == set(range(len(old_topology)))
                and all(set(row.get("texts", {})) == columns for row in self._row_items))

    def _reconcile_body_rows(self, old_topology, new_topology):
        """Rebind rows by stable path, deleting only entries actually removed."""
        previous = {key: self._row_registry[index] for index, key in enumerate(old_topology)}
        rows, changed = [], []
        for index, key in enumerate(new_topology):
            row = previous.pop(key, None)
            if row is None:
                row = self._create_body_row(index)
                changed.append(index)
            else:
                moved = row["index"] != index
                self._bind_body_row(row, index, preserve_geometry=not moved)
                if moved or row.get("content_changed", False):
                    changed.append(index)
            rows.append(row)
        for row in previous.values():
            self._destroy_body_row(row)
        self._replace_row_registry(rows)
        self._row_render_window_cache = tuple(range(len(new_topology)))
        if old_topology != new_topology:
            self._visual_selected_cache = None
            self._visual_current_cache = None
        return changed
