"""Pointer-capture state shared by :class:`ExplorerListView`.

Kept separate from event dispatch so external splitters can cancel a list-view
gesture without depending on the full row/drag implementation.
"""

from .interaction_gate import acquire_pointer_input, release_pointer_input


class ExplorerPointerCaptureMixin:
    def _claim_pointer_gesture(self):
        """Exclusively own the current pointer gesture, Qt mouse-grab style."""
        if self._pointer_input_owned:
            return True
        self._pointer_input_owned = bool(acquire_pointer_input(self))
        return self._pointer_input_owned

    def _release_pointer_gesture(self):
        if self._pointer_input_owned:
            release_pointer_input(self)
            self._pointer_input_owned = False

    def cancel_pointer_gesture(self, suppress_release=True):
        """Abort transient mouse state without changing the selection.

        Splitters and other higher-priority surfaces call this when they own the
        original mouse-down.  Dear PyGui dispatches ListView handlers globally,
        so a selected row can otherwise retain ``_drag_origin_on_item`` and
        promote the same physical gesture into a file drag while a splitter is
        already resizing.  This is the QAbstractItemView equivalent of losing
        the mouse grab before a drag operation has been accepted.
        """
        if self._item_drag_active:
            self._finish_item_drag(perform_drop=False)
        else:
            self._drag_source_index = None
            self._drag_source_items = []
            self._drag_origin_on_item = False
            self._drop_target_index = None
            self._drop_target_pinned = False
            self._drag_cursor_active = False
            self._drag_preview.end()

        self._mouse_down = False
        self._mouse_down_time = 0.0
        self._pending_click_index = None
        self._drag_started = False
        self._rubber_active = False
        self._double_click_gesture = False
        self._rename_click_candidate = None
        self._hide_rubber_rect()

        # Header/column gestures are transient too.  Clearing them here avoids
        # a queued global drag callback reviving a resize after the external
        # splitter has already taken ownership.
        self._header_gesture = False
        self._header_pressed_key = None
        self._header_dragged = False
        self._resize_key = None
        self._resize_next_key = None
        self._resize_next_start_width = 0.0
        self._separator_click_candidate_key = None
        self._hover_separator_key = None
        self._set_separator_hover_state(None)

        if suppress_release:
            self._suppress_next_left_release = True
        self._release_pointer_gesture()
