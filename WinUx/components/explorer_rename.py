"""Inline rename behavior shared by ExplorerListView.

The reusable ExplorerRenameTextBox owns the native/DPG editor details; this
mixin owns only the list-view state transition and filesystem rename contract.
"""
from __future__ import annotations

import os
import time

import dearpygui.dearpygui as dpg
from ..runtime.rename_result import RenameResult


class ExplorerRenameMixin:
    def begin_inline_rename(self, item_or_index=None):
        """Edit one Name cell in-place using :class:`ExplorerRenameTextBox`."""
        self._pending_slow_rename = None
        if self._rename_active:
            self.cancel_inline_rename()

        if item_or_index is None:
            if len(self.selected) != 1:
                return False
            index = next(iter(self.selected))
        elif isinstance(item_or_index, int):
            index = item_or_index
        else:
            try:
                index = self.items.index(item_or_index)
            except ValueError:
                return False

        if not (0 <= index < len(self.items)):
            return False

        geometry = self._column_geometry().get("name")
        viewport = self._body_viewport_rect()
        if geometry is None or viewport is None:
            return False

        item = self.items[index]
        column_x, column_width = geometry
        vx0, vy0, vx1, vy1 = viewport

        try:
            scroll_x = float(dpg.get_x_scroll(self.body_window))
        except Exception:
            scroll_x = 0.0
        try:
            scroll_y = float(dpg.get_y_scroll(self.body_window))
        except Exception:
            scroll_y = 0.0

        text_x = vx0 + float(column_x) + 24.0 - scroll_x
        row_y = vy0 + float(index * self.ROW_HEIGHT) - scroll_y
        if row_y + self.ROW_HEIGHT <= vy0 or row_y >= vy1:
            return False

        try:
            text_width, text_height = dpg.get_text_size(
                item.name, font=self._fonts.get("body"))
        except Exception:
            try:
                text_width, text_height = dpg.get_text_size(item.name)
            except Exception:
                text_width, text_height = max(24, len(item.name) * 8), 16

        cell_right = vx0 + float(column_x + column_width) - scroll_x
        # Windows Explorer places the rename box directly around the label:
        # one pixel before the first glyph, white interior, 1 px dark border.
        editor_left = max(vx0, text_x - 1.0)
        max_right = min(vx1 - 1.0, cell_right - self.CELL_PADDING)
        editor_max_width = max(24, int(round(max_right - editor_left)))
        # Do not size the Win32 EDIT from get_text_size() line height.  Dear
        # PyGui includes font line metrics there, while CreateFontW interprets
        # the supplied value as the actual font height; using the measured
        # height made rename text visibly larger than the row label.  Explorer
        # also uses a slightly tighter editor than the full row height.
        editor_height = min(
            max(18, int(self.ROW_HEIGHT) - 2),
            max(18, int(self.RENAME_EDITOR_HEIGHT)),
        )
        editor_top = max(
            vy0, row_y + (self.ROW_HEIGHT - editor_height) * 0.5)
        input_width = max(
            24, min(editor_max_width, int(round(text_width + 8.0))))

        self._quiesce_pointer_for_inline_rename()
        self._install_native_cursor_hook()
        hwnd = int(getattr(self, "_native_hwnd", None) or 0)
        # Dear PyGui item positions are already in the same viewport-client
        # coordinate space used by Win32 child windows.  Applying an extra
        # DPI ratio here shrinks and shifts the EDIT control on 125/150%
        # displays (the exact artifact visible in inline rename).
        scale = 1.0

        source_tag = None
        rendered_row = self._row_for_index(index)
        if rendered_row is not None:
            source_tag = rendered_row.get("texts", {}).get("name")

        # Rename is intentionally Explorer-neutral rather than inheriting the
        # application's blue selection chrome.  The selected row remains blue
        # behind it; the editor itself is white with a thin dark border.
        editor_fill = (255, 255, 255, 255)
        editor_border = (72, 72, 72, 255)

        if not self._rename_textbox.begin(
            item.name,
            is_directory=item.is_dir,
            left=editor_left,
            top=editor_top,
            initial_width=input_width,
            max_width=editor_max_width,
            height=editor_height,
            source_text_tag=source_tag,
            font=self._fonts.get("body"),
            editor_fill=editor_fill,
            editor_border=editor_border,
            text_color=self.RENAME_TEXT_AND_CARET_COLOR,
            selection_color=self.RENAME_SELECTION_COLOR,
            native_hwnd=hwnd,
            native_scale=scale,
            font_px=self._rename_text_render_height(),
            font_face="Segoe UI",
        ):
            return False

        self._rename_active = True
        self._rename_index = index
        return True

    def _read_rename_text(self, item):
        return self._rename_textbox.text(str(item.name or ""))

    def _quiesce_pointer_for_inline_rename(self):
        """End transient pointer state without changing row selection."""
        pending_release = bool(
            getattr(self, "_mouse_down", False)
            or getattr(self, "_pending_click_index", None) is not None
            or getattr(self, "_rubber_active", False)
            or getattr(self, "_item_drag_active", False)
            or getattr(self, "_resize_key", None) is not None
        )
        old_target = getattr(self, "_drop_target_index", None)

        self._mouse_down = False
        self._mouse_down_time = 0.0
        self._pending_click_index = None
        self._drag_started = False
        self._drag_origin_on_item = False
        self._drag_source_index = None
        self._drag_source_items = []
        self._rubber_active = False
        self._item_drag_active = False
        self._drop_target_index = None
        self._drop_target_pinned = False
        self._drag_cursor_active = False
        self._resize_key = None
        self._resize_next_key = None
        self._resize_next_start_width = 0.0
        self._hover_separator_key = None
        self._rename_click_candidate = None
        self._rename_schedule_serial += 1

        self._suppress_next_left_release = bool(
            getattr(self, "_suppress_next_left_release", False)
            or pending_release)
        self._hide_rubber_rect()
        preview = getattr(self, "_drag_preview", None)
        if preview is not None:
            try:
                preview.end()
            except Exception:
                pass
        self._set_separator_hover_state(None)
        self._update_row_visual(old_target)
        self._set_mouse_cursor("mvMouseCursor_Arrow")
        self._clear_hover()

    def _process_inline_rename_focus(self):
        """Advance the reusable rename textbox and dispatch native keys."""
        if not self._rename_active:
            return
        action = self._rename_textbox.pump()
        if action == "commit":
            self.commit_inline_rename()
        elif action == "cancel":
            self.cancel_inline_rename()

    def _focus_and_select_inline_rename(self):
        """Restore focus to the active rename textbox."""
        if not self._rename_active:
            return False
        return bool(self._rename_textbox.refocus())

    def commit_inline_rename(self, new_name=None):
        if getattr(self, "_rename_pending", None) is not None:
            return False
        if not self._rename_active or self._rename_index is None:
            return False
        index = self._rename_index
        if not (0 <= index < len(self.items)):
            self.cancel_inline_rename()
            return False
        item = self.items[index]
        if new_name is None:
            new_name = str(self._read_rename_text(item)).strip()
        else:
            new_name = str(new_name).strip()

        old_path = os.path.abspath(item.path)
        directory = os.path.dirname(old_path)
        requested = os.path.join(directory, new_name)
        if new_name != item.name:
            if self.on_rename_commit:
                result = self.on_rename_commit(item, new_name)
                if isinstance(result, RenameResult):
                    self._rename_pending = result
                    result.then(lambda success: self._rename_completed(result, success))
                    return True
                if result is False:
                    self.refocus_inline_rename()
                    return False
                self._finish_inline_rename_ui()
                if self.on_selection_change:
                    self.on_selection_change(self.get_selected())
                return True
            else:
                if not new_name or new_name in (".", ".."):
                    return False
                if any(ch in new_name for ch in '<>:"/\\|?*'):
                    return False
                target = requested
                if (os.path.exists(target) and
                        os.path.normcase(os.path.abspath(target)) !=
                        os.path.normcase(old_path)):
                    error = OSError(
                        "An item with that name already exists")
                    if self.on_move_error:
                        self.on_move_error(error)
                        self.refocus_inline_rename()
                        return False
                    raise error
                try:
                    os.rename(old_path, target)
                except Exception as exc:
                    if self.on_move_error:
                        self.on_move_error(exc)
                        self.refocus_inline_rename()
                        return False
                    raise
        else:
            target = requested

        # Update the existing row object immediately instead of waiting for a
        # directory reload. Keeping the same object also preserves any custom
        # icon, cell style and user data attached to this item.
        item.path = os.path.abspath(target)
        item.name = os.path.basename(target)
        item.extension = os.path.splitext(item.name)[1]
        item.item_type = "File folder" if item.is_dir else item._guess_type(item.name)
        try:
            item.mtime = os.path.getmtime(item.path)
        except OSError:
            pass
        if not item.is_dir:
            try:
                item.size = os.path.getsize(item.path)
            except OSError:
                pass
        refresh_cache = getattr(item, "refresh_display_cache", None)
        if callable(refresh_cache):
            refresh_cache()

        self._finish_inline_rename_ui()

        # Sorting by Name/Type/Date may move the renamed item. Rebuild the rows
        # and restore selection using object identity, not the old row index.
        renamed_item = item
        self._sort_items()
        self._rebuild_draw_items()
        try:
            new_index = self.items.index(renamed_item)
            self.selected = {new_index}
            self.last_clicked_index = new_index
            self._current_index = new_index
        except ValueError:
            self.selected.clear()
            self.last_clicked_index = None
            self._current_index = None

        self._sync_qt_selection_from_fields()

        self._update_selection_draws()
        self._update_status_bar()
        if self.on_selection_change:
            self.on_selection_change(self.get_selected())
        return True

    def _finish_inline_rename_ui(self):
        self._rename_pending = None
        self._rename_textbox.close()
        self._rename_active = False
        self._rename_index = None

    def _rename_completed(self, result, success):
        if getattr(self, "_rename_pending", None) is not result:
            return
        self._rename_pending = None
        if not self._rename_active:
            return
        if success:
            self._finish_inline_rename_ui()
            if self.on_selection_change:
                self.on_selection_change(self.get_selected())
        else:
            self.refocus_inline_rename()

    def cancel_inline_rename(self):
        if not self._rename_active:
            return False
        self._finish_inline_rename_ui()
        return True

    def refocus_inline_rename(self):
        """Restore keyboard focus after an Explorer-style rename error."""
        return self._focus_and_select_inline_rename()

    def _body_point_is_on_name(self, index, body_pos):
        """Return True when a body point is over the visible filename label."""
        if body_pos is None or not (0 <= index < len(self.items)):
            return False
        geometry = self._column_geometry().get("name")
        if geometry is None:
            return False
        x, _y = body_pos
        column_x, column_width = geometry
        text_left = float(column_x) + 24.0
        try:
            text_width = float(dpg.get_text_size(
                self.items[index].name,
                font=self._fonts.get("body"))[0])
        except Exception:
            text_width = max(24.0, len(self.items[index].name) * 8.0)
        text_right = min(
            float(column_x + column_width - self.CELL_PADDING),
            text_left + text_width + 6.0,
        )
        return text_left <= float(x) <= text_right

    def _schedule_slow_click_rename(self, index):
        """Start rename after Explorer's selected-label single-click delay."""
        self._rename_schedule_serial += 1
        serial = self._rename_schedule_serial
        self._pending_slow_rename = (
            time.monotonic() + self.ITEM_MOVE_HOLD_DELAY,
            serial,
            index,
        )

    def _process_pending_slow_rename(self):
        pending = self._pending_slow_rename
        if pending is None or time.monotonic() < pending[0]:
            return
        self._pending_slow_rename = None
        _deadline, serial, index = pending
        if (serial != self._rename_schedule_serial
                or self._rename_active or self._mouse_down
                or self._last_click_index != index
                or self.selected != {index}
                or not (0 <= index < len(self.items))):
            return
        item = self.items[index]
        if self.on_item_menu_action:
            self.on_item_menu_action("command:rename", [item])
        else:
            self.begin_inline_rename(index)
