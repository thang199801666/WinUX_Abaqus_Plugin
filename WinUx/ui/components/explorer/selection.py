"""Public selection state operations for ExplorerListView.

Explorer's draw-list renderer keeps index-based fields for compatibility with
its hit-testing/virtualization code, while ``QtItemViewState`` is the shared
QAbstractItemView-style source of interaction semantics.  These helpers keep
both representations synchronized without changing the public API used by file
operations and drag/drop.
"""
from __future__ import annotations


class ExplorerSelectionMixin:
    def _sync_qt_selection_from_fields(self):
        state = self._qt_selection
        state.multiple = not bool(self.single_selection)
        count = len(self.items)

        # Explorer keys are stable integer row indexes. Rebuilding
        # QtItemViewState.replace(range(N)) on every Ctrl/Shift click allocates
        # and compares an N-element list even when the model did not change.
        # Rebuild the lookup only when the row count changes; reorder/content
        # refreshes keep the same 0..N-1 key domain.
        keys = state.keys
        if len(keys) != count or (count and (not keys or keys[0] != 0 or keys[-1] != count - 1)):
            state.replace(range(count))

        # Validate only the selection payload rather than materializing a full
        # set(state.keys). Multi-select cost is therefore O(selected), not O(N).
        state.selected = {
            int(i) for i in self.selected
            if 0 <= int(i) < count
        }
        current = self._current_index
        anchor = self.last_clicked_index
        state.current = current if current is not None and 0 <= int(current) < count else None
        state.anchor = anchor if anchor is not None and 0 <= int(anchor) < count else None
        return state

    def _sync_fields_from_qt_selection(self):
        state = self._qt_selection
        self.selected = set(state.selected)
        self._current_index = state.current
        self.last_clicked_index = state.anchor
        return state

    def _commit_selection_state(self, *, notify=True):
        self._sync_fields_from_qt_selection()
        self._update_selection_draws()
        self._update_status_bar()
        if notify and self.on_selection_change:
            self.on_selection_change(self.get_selected())

    def get_selected(self):
        return [self.items[i] for i in sorted(self.selected) if i < len(self.items)]

    def select_indices(self, indices, replace=True):
        valid = {int(i) for i in indices if 0 <= int(i) < len(self.items)}
        if self.single_selection and valid:
            valid = {min(valid)}
        state = self._sync_qt_selection_from_fields()
        state.selected = set(valid) if replace else state.selected | valid
        if self.single_selection and len(state.selected) > 1:
            state.selected = {min(state.selected)}
        if valid:
            state.current = min(valid)
            state.anchor = state.current
        self._commit_selection_state()
        return self

    def clear_selection(self):
        state = self._sync_qt_selection_from_fields()
        state.clear()
        # Qt keeps the current index independent from selection.  Explorer's
        # historic public clearSelection() behaved the same for keyboard focus,
        # so leave current/anchor untouched here.
        self._commit_selection_state()
        return self

    def select_all(self):
        """Select every item and emit one selection-change notification."""
        if self._rename_active:
            return False
        state = self._sync_qt_selection_from_fields()
        if self.single_selection:
            if state.keys:
                state.selected = {state.keys[-1]}
                state.current = state.keys[-1]
                state.anchor = state.current
        else:
            state.select_all()
            state.current = state.keys[-1] if state.keys else None
            state.anchor = state.current
        self._commit_selection_state()
        return True
