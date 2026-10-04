"""Mouse dispatch for ExplorerListView.

The dispatch order is intentionally preserved: modal/protected surfaces and
header/resize ownership are resolved before row selection, rubber-band, or
item drag/drop.  Keeping this in one mixin makes that ordering testable as a
behavior contract.
"""
from __future__ import annotations

import sys
import time

import dearpygui.dearpygui as dpg

from ..diagnostics import log_exception
from .interaction_gate import pointer_input_is_blocked
from .explorer_input_state import (
    _ctrl_down, _modal_input_is_blocked, _overlay_window_owns_input, _shift_down,
)


class ExplorerPointerDispatchMixin:
    def _on_mouse_move(self, sender=None, app_data=None, user_data=None):
        self._drain_pending_external_drops()
        overlay = getattr(self, "_scroller_arrow_overlay", None)
        if overlay is not None:
            overlay.update()
        if pointer_input_is_blocked(self):
            self._hide_item_tooltips()
            self._clear_hover()
            return
        if _modal_input_is_blocked():
            self._hide_item_tooltips()
            self._clear_hover()
            return
        # Context-menu groups use hover to expose their Explorer-style fly-out.
        # Handle this before the generic overlay guard, because visible menu
        # windows intentionally own the mouse while the list view is blocked.
        if self._context_menu_is_visible():
            if type(self)._resize_cursor_owner is self:
                type(self)._resize_cursor_owner = None
                self._set_mouse_cursor("mvMouseCursor_Arrow")
            self._update_context_submenu_hover()
            self._hide_item_tooltips()
            self._clear_hover()
            return
        if _overlay_window_owns_input():
            if type(self)._resize_cursor_owner is self:
                type(self)._resize_cursor_owner = None
                self._set_mouse_cursor("mvMouseCursor_Arrow")
            self._hide_item_tooltips()
            self._clear_hover()
            return
        if self._rename_active:
            self._hide_item_tooltips()
            return
        self._update_header_hover_state()
        self._update_resize_cursor()
        pinned_hover = self._mouse_in_pinned_row()
        if pinned_hover != self._pinned_hovered:
            self._pinned_hovered = pinned_hover
            self._layout_pinned_row()
        if pinned_hover:
            self._hide_tooltip_parts(self._body_item_tooltip)
            self._show_tooltip_parts(
                self._pinned_item_tooltip, self._pinned_item)
            self._clear_hover()
            return
        self._hide_tooltip_parts(self._pinned_item_tooltip)
        # _row_at_mouse() returns None both outside the body and over the empty
        # area below the final row. Therefore moving into blank space removes
        # the previous row hover immediately.
        self._update_hover_state()


    def _on_left_down(self, sender=None, app_data=None, user_data=None):
        self._hide_item_tooltips()
        if pointer_input_is_blocked(self):
            self._suppress_next_left_release = True
            self._mouse_down = False
            self._pending_click_index = None
            self._drag_started = False
            self._rubber_active = False
            self._item_drag_active = False
            self._drag_preview.end()
            self._hide_rubber_rect()
            self._clear_hover()
            return
        if _modal_input_is_blocked():
            self._suppress_next_left_release = True
            self._mouse_down = False
            self._pending_click_index = None
            self._clear_hover()
            return
        # Explorer behavior: a left click outside the main menu and all open
        # fly-outs closes them immediately. A click inside is left to the menu
        # widgets themselves and must never reach the list view underneath.
        if self._context_menu_is_visible():
            if not self._mouse_inside_context_menus():
                self._hide_context_menus()
            self._suppress_next_left_release = True
            self._mouse_down = False
            self._pending_click_index = None
            self._clear_hover()
            return
        if _overlay_window_owns_input():
            self._suppress_next_left_release = True
            self._mouse_down = False
            self._pending_click_index = None
            self._clear_hover()
            return
        if self._rename_active:
            if self._mouse_in_item(self._rename_window_tag):
                return
            # Explorer accepts the edited name when the user clicks elsewhere.
            # A validation/backend failure keeps the editor active and consumes
            # the click so the selection cannot unexpectedly move.
            if not self.commit_inline_rename():
                return
        self._rename_schedule_serial += 1
        self._rename_click_candidate = None
        self._double_click_gesture = False
        if self._mouse_in_pinned_row():
            if not self._claim_pointer_gesture():
                return
            now = time.monotonic()
            if now - self._pinned_last_click_time <= 0.38:
                self._activate_pinned_item()
                self._pinned_last_click_time = 0.0
            else:
                self._pinned_last_click_time = now
            self._has_focus = True
            self._current_index = None
            self.clear_selection()
            return
        self._mouse_down = True
        self._mouse_down_time = time.monotonic()
        self._drag_started = False
        self._rubber_active = False
        self._pending_click_index = None
        self._item_drag_active = False
        self._drag_source_index = None
        self._drag_source_items = []
        self._drag_origin_on_item = False
        self._drop_target_index = None
        self._drag_preview.end()
        self._hide_rubber_rect()
        try:
            self._mouse_down_screen = tuple(map(float, dpg.get_mouse_pos(local=False)))
        except Exception:
            self._mouse_down_screen = (0.0, 0.0)

        clicked_body = self._mouse_in_body()
        new_focus = bool(clicked_body)
        focus_changed = new_focus != self._has_focus
        self._has_focus = new_focus
        if focus_changed:
            self._update_selection_draws()

        inside_header, local_x = self._header_mouse_position()
        if inside_header:
            if not self._claim_pointer_gesture():
                self._mouse_down = False
                return
            self._header_gesture = True
            self._header_dragged = False
            resize_key = self._separator_at(local_x)
            if resize_key:
                # QHeaderView convention: a double-click on a section divider
                # resizes that section to its visible contents. The first click
                # is recorded only on release if it was not actually dragged.
                now = time.monotonic()
                is_double = (
                    self._last_header_separator_click_key == resize_key
                    and 0.0 <= now - float(self._last_header_separator_click_time or 0.0) <= 0.38
                )
                if is_double and self._last_header_separator_click_screen is not None:
                    try:
                        dx = self._mouse_down_screen[0] - self._last_header_separator_click_screen[0]
                        dy = self._mouse_down_screen[1] - self._last_header_separator_click_screen[1]
                        is_double = (dx * dx + dy * dy) ** 0.5 <= 12.0
                    except Exception:
                        is_double = False
                if is_double:
                    self._last_header_separator_click_time = 0.0
                    self._last_header_separator_click_key = None
                    self._last_header_separator_click_screen = None
                    self._separator_click_candidate_key = None
                    self._resize_key = None
                    self._auto_size_column_to_contents(resize_key)
                    self._mouse_down = False
                    return

                self._resize_key = resize_key
                self._resize_start_x = local_x
                self._resize_start_mouse_x = self._mouse_down_screen[0]
                self._resize_start_width = float(self._column_widths[resize_key])
                # Qt Interactive resize changes the grabbed section only; it
                # does not silently steal width from the neighbouring section.
                self._resize_next_key = None
                self._resize_next_start_width = 0.0
                self._separator_click_candidate_key = resize_key
                self._set_separator_hover_state(resize_key)
                self._update_resize_cursor()
                return
            key = self._column_at(local_x)
            if key:
                # Sort is committed on release, not mouse-down. This prevents a
                # press/drag across the header from changing sort order.
                self._header_pressed_key = key
                self._update_header_cell_visuals()
            return

        body_pos = self._body_local_pos()
        if body_pos is None:
            self._mouse_down = False
            return
        if not self._claim_pointer_gesture():
            self._mouse_down = False
            return

        self._rubber_start = body_pos
        self._rubber_current = body_pos
        # Use the unmodified screen mouse-down coordinate for drawing.  This is
        # important in the blank area below the data rows, where the scrollable
        # drawlist's own origin/height must not influence the visual anchor.
        self._rubber_start_screen = self._mouse_down_screen
        self._rubber_base_selection = set(self.selected)
        self._rubber_ctrl = _ctrl_down()
        self._rubber_shift = _shift_down()
        # Lock the interaction type at mouse-down. Using _row_at_mouse() is
        # more reliable than recalculating the row from body coordinates on
        # Dear PyGui builds where child-window scroll origins vary by frame.
        idx = self._row_at_mouse()
        point_on_name_text = (
            idx is not None
            and self._body_point_is_on_name(idx, body_pos)
        )

        # A rapid second press on the same row, close to the previous click
        # position, is a double-click candidate rather than a drag. Without
        # this, a shaky double-click that wobbles past DRAG_THRESHOLD turns
        # into an item drag: navigation never fires and the accidental drop
        # can even attempt a same-pane move of a locked folder.
        double_click_candidate = False
        if idx is not None and idx == self._last_click_index:
            press_dt = time.monotonic() - float(self._last_click_time or 0.0)
            if 0.0 <= press_dt <= 0.38 and self._last_click_screen is not None:
                try:
                    dx = (self._mouse_down_screen[0]
                          - self._last_click_screen[0])
                    dy = (self._mouse_down_screen[1]
                          - self._last_click_screen[1])
                    double_click_candidate = (dx * dx + dy * dy) ** 0.5 <= 12.0
                except Exception:
                    double_click_candidate = False
        # A click still targets the complete row, matching Explorer's Details
        # view.  The drag gesture also starts from anywhere on a row (icon,
        # any column, or row padding).  Only blank body space starts
        # rubber-band selection once the pointer crosses DRAG_THRESHOLD.
        # point_on_name_text is kept only for the slow-rename label gesture.
        self._pending_click_index = idx
        self._double_click_gesture = bool(double_click_candidate)
        if double_click_candidate:
            self._drag_source_index = None
            self._drag_origin_on_item = False
        else:
            self._drag_source_index = idx
            self._drag_origin_on_item = idx is not None

        if (point_on_name_text and idx in self.selected
                and not (self._rubber_ctrl or self._rubber_shift)):
            self._rename_click_candidate = idx

        # Explorer behavior: a plain click in the empty body clears selection
        # immediately. Ctrl/Shift preserve it so rubber-band additive selection
        # still works as expected.
        if idx is None and not (self._rubber_ctrl or self._rubber_shift):
            self.clear_selection()
            self._clear_hover()


    def _on_left_drag(self, sender=None, app_data=None, user_data=None):
        self._hide_item_tooltips()
        if pointer_input_is_blocked(self):
            if self._item_drag_active:
                self._finish_item_drag(perform_drop=False)
            self._rubber_active = False
            self._drag_started = False
            self._mouse_down = False
            self._pending_click_index = None
            self._suppress_next_left_release = True
            self._hide_rubber_rect()
            self._clear_hover()
            return
        if _modal_input_is_blocked():
            self._clear_hover()
            return
        if _overlay_window_owns_input():
            self._clear_hover()
            return
        if self._rename_active:
            return
        if self._header_gesture and self._resize_key is None:
            # Header presses are locked to the header. Track whether this became
            # a drag so sorting is only committed for a genuine click-release.
            try:
                mx, my = map(float, dpg.get_mouse_pos(local=False))
                dx = mx - float(self._mouse_down_screen[0])
                dy = my - float(self._mouse_down_screen[1])
                if (dx * dx + dy * dy) ** 0.5 >= float(self.DRAG_THRESHOLD):
                    self._header_dragged = True
            except Exception:
                pass
            return
        if self._double_click_gesture:
            # The second press of a double-click owns no gesture: neither an
            # item drag nor a rubber-band may steal the pending click that the
            # release handler turns into navigation/activation.
            return
        if self._resize_key:
            mouse_x = float(dpg.get_mouse_pos(local=False)[0])
            delta = mouse_x - self._resize_start_mouse_x
            new_width = max(self.MIN_COLUMN_WIDTH, self._resize_start_width + delta)
            old_width = float(self._column_widths[self._resize_key])
            if abs(delta) >= float(self.DRAG_THRESHOLD):
                self._separator_click_candidate_key = None
            self._column_widths[self._resize_key] = new_width

            if abs(old_width - new_width) >= 0.01:
                # Mouse-drag handlers already run at most once per rendered
                # frame. Applying now avoids a one-frame lag and avoids DPG's
                # single frame-callback slot being overwritten by another view.
                self._layout_all()
                self._update_resize_cursor()
            return

        if not self._mouse_down or self._body_viewport_rect() is None:
            return
        try:
            mx, my = map(float, dpg.get_mouse_pos(local=False))
        except Exception:
            return
        dx = mx - self._mouse_down_screen[0]
        dy = my - self._mouse_down_screen[1]
        distance = (dx * dx + dy * dy) ** 0.5
        if not self._drag_started and distance >= self.DRAG_THRESHOLD:
            # Explorer locks the gesture from its mouse-down origin.  Any row
            # is a move handle; only blank body space is a rubber-band origin.
            if self._drag_origin_on_item:
                self._start_item_drag()
            else:
                self._start_rubberband()
        if self._item_drag_active:
            self._update_item_drag()
        elif self._rubber_active:
            self._update_rubberband()


    def _on_left_release(self, sender=None, app_data=None, user_data=None):
        try:
            return self._on_left_release_impl(sender, app_data, user_data)
        finally:
            self._header_gesture = False
            self._header_pressed_key = None
            self._header_dragged = False
            self._update_header_cell_visuals()
            self._release_pointer_gesture()


    def _on_left_release_impl(self, sender=None, app_data=None, user_data=None):
        # Non-resize header gestures are QHeaderView section clicks. Commit the
        # sort only when the pointer is released over the same section and the
        # press never crossed the drag threshold.
        if self._header_gesture and self._resize_key is None:
            key = self._header_pressed_key
            inside, local_x = self._header_mouse_position()
            release_key = (
                self._column_at(local_x)
                if inside and self._separator_at(local_x) is None else None
            )
            should_sort = bool(
                self._header_sections_clickable
                and key and release_key == key and not self._header_dragged
            )
            self._mouse_down = False
            self._mouse_down_time = 0.0
            self._pending_click_index = None
            self._drag_started = False
            self._separator_click_candidate_key = None
            if should_sort:
                if self.sort_key == key:
                    self.sort_ascending = not self.sort_ascending
                else:
                    self.sort_key = key
                    self.sort_ascending = True
                self._update_header_sort_indicator()
                if self.on_sort_change:
                    self.on_sort_change(self.sort_key, self.sort_ascending)
                self._schedule_sort_refresh()
            return

        was_rubber = self._rubber_active
        was_item_drag = self._item_drag_active
        # An in-progress gesture owns this release even if a popup/modal tag
        # is visible at release time. Concluding it here is safe because
        # controller drop work is only queued through view.after (no nested
        # render loop). Returning early instead silently swallows the drop and
        # leaves drag state stuck, forcing the user to drag again.
        concluding_gesture = (
            was_item_drag or was_rubber or self._resize_key is not None
        )
        if not concluding_gesture:
            if _modal_input_is_blocked():
                self._mouse_down = False
                self._pending_click_index = None
                self._clear_hover()
                return
            if self._suppress_next_left_release:
                self._suppress_next_left_release = False
                self._mouse_down = False
                self._pending_click_index = None
                self._clear_hover()
                return
            if _overlay_window_owns_input():
                self._clear_hover()
                return
            if (not self._mouse_down and self._resize_key is None
                    and not self._rubber_active
                    and not self._item_drag_active):
                return
            # A plain press/release without any drag, rubber-band, or resize
            # falls through to the shared click handling below (selection and
            # double-click activation). Returning here would swallow every
            # normal click.
        # Never let a stale suppress flag leak into and eat the next click.
        self._suppress_next_left_release = False
        if self._rename_active:
            return
        pending_index = self._pending_click_index
        self._mouse_down = False
        self._mouse_down_time = 0.0
        if (self._resize_key is not None
                and self._separator_click_candidate_key == self._resize_key):
            self._last_header_separator_click_time = time.monotonic()
            self._last_header_separator_click_key = self._resize_key
            try:
                self._last_header_separator_click_screen = tuple(
                    map(float, dpg.get_mouse_pos(local=False)))
            except Exception:
                self._last_header_separator_click_screen = self._mouse_down_screen
        self._separator_click_candidate_key = None
        self._resize_key = None
        self._resize_next_key = None
        self._resize_next_start_width = 0.0
        self._hover_separator_key = None
        # Clear the active splitter decoration immediately on mouse-up. The
        # next frame may still show the resize cursor if the pointer remains
        # over the divider, but the divider itself is no longer selected.
        self._set_separator_hover_state(None)
        self._pending_click_index = None
        self._drag_origin_on_item = False
        self._double_click_gesture = False
        self._drag_started = False
        self._rubber_active = False
        self._hide_rubber_rect()
        if was_item_drag:
            if self.on_drop:
                # End every visual/native drag state before invoking the
                # controller. The controller may open an overwrite modal;
                # leaving the drag preview/cursor active while that modal is
                # visible makes both systems redraw on every frame and causes
                # whole-window flickering.
                try:
                    mx, my = map(float, dpg.get_mouse_pos(local=False))
                except Exception:
                    # (0, 0) tells the controller to reuse the last
                    # highlighted/cached target instead of hit-testing again.
                    mx, my = 0.0, 0.0
                try:
                    copy_requested = _ctrl_down()
                except Exception:
                    copy_requested = False
                # Snapshot the dragged items before _finish_item_drag() clears
                # the drag state. Cross-pane mouse capture can change normal
                # selection/hover state before the controller reads it.
                dragged_items = list(self._drag_source_items)
                self._finish_item_drag(perform_drop=False)
                try:
                    self.on_drop(mx, my, copy_requested, dragged_items)
                except Exception:
                    log_exception(
                        "Explorer item drop callback failed",
                        sys.exc_info(),
                        fatal=False,
                    )
            else:
                self._finish_item_drag(perform_drop=True)
        self._update_resize_cursor()

        if was_item_drag:
            return
        if was_rubber:
            if self.on_selection_change:
                self.on_selection_change(self.get_selected())
            return

        if pending_index is not None:
            try:
                self._last_click_screen = tuple(
                    map(float, dpg.get_mouse_pos(local=False)))
            except Exception:
                self._last_click_screen = None
            is_double = self._select_index(pending_index)
            if (self._rename_click_candidate == pending_index
                    and not is_double
                    and not (_ctrl_down() or _shift_down())):
                self._schedule_slow_click_rename(pending_index)
        elif self._has_focus:
            if not (_ctrl_down() or _shift_down()):
                self.clear_selection()


    def _select_index(self, idx):
        import time
        now = time.monotonic()
        is_double = self._last_click_index == idx and now - self._last_click_time <= 0.38
        self._last_click_index = idx
        self._last_click_time = now

        state = self._sync_qt_selection_from_fields()
        ctrl = bool(_ctrl_down()) and not self.single_selection
        shift = bool(_shift_down()) and not self.single_selection
        # Dear PyGui does not give this draw-list view a toggle value, so Ctrl
        # determines the desired state exactly like QAbstractItemView.
        selected = idx not in state.selected if ctrl else True
        state.select(idx, ctrl=ctrl, shift=shift, selected=selected)
        self._commit_selection_state()
        if is_double:
            self.activate_item(idx)
        return is_double


    def _on_right_click(self, sender=None, app_data=None, user_data=None):
        self._hide_item_tooltips()
        if pointer_input_is_blocked(self):
            self._clear_hover()
            return
        # A second right-click outside the current menu should move the menu
        # to the new target, rather than being blocked by the old popup.
        if self._context_menu_is_visible():
            if self._mouse_inside_context_menus():
                self._clear_hover()
                return
            self._hide_context_menus()
        if _overlay_window_owns_input():
            self._clear_hover()
            return
        if self._rename_active:
            if self._mouse_in_item(self._rename_window_tag):
                return
            if not self.commit_inline_rename():
                return
        if not self._mouse_in_body():
            return
        if not self._has_focus:
            self._has_focus = True
            self._update_selection_draws()
        body_pos = self._body_local_pos()
        if body_pos is None:
            return
        idx = self._row_at_mouse()
        if idx is None:
            # A blank body area targets the current directory rather than an
            # individual item, just like the Windows Explorer background menu.
            self._current_index = None
            self.clear_selection()
            self._context_item_index = None
        elif idx not in self.selected:
            state = self._sync_qt_selection_from_fields()
            state.select(idx, ctrl=False, shift=False, selected=True)
            self._commit_selection_state(notify=False)
            self._context_item_index = idx
        else:
            state = self._sync_qt_selection_from_fields()
            state.current = idx
            self._sync_fields_from_qt_selection()
            self._context_item_index = idx
            self._update_selection_draws()
        if self.on_context_menu_open:
            targets = self.get_selected()
            if idx is not None and not targets:
                targets = [self.items[idx]]
            self.on_context_menu_open(targets)
        self._clear_hover()
        self._hide_context_submenus()
        mx, my = dpg.get_mouse_pos(local=False)
        # Keep the complete context window inside the app viewport. This is
        # especially important near the right and bottom edges where a normal
        # window (unlike a native popup) is not automatically repositioned.
        menu_x, menu_y = self._clamp_context_position(
            self.itemmenu_tag, mx, my, 266.0
        )
        dpg.set_item_pos(self.itemmenu_tag, [menu_x, menu_y])
        dpg.configure_item(self.itemmenu_tag, show=True)
        self._set_context_keyboard_id(None)

