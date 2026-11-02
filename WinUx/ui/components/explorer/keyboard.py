"""Explorer keyboard commands with injected GUI and input boundaries."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from DearUIQt.core import QEvent, QKeyEvent, Qt


@dataclass
class ExplorerKeyboardInput:
    ctrl: Callable
    shift: Callable
    alt: Callable
    overlay_owns_input: Callable
    pointer_blocked: Callable


class ExplorerKeyboardController:
    def __init__(self, view, backend, input_state):
        self.view = view
        self.backend = backend
        self.input = input_state
        self._event_modifiers = None

    def _ctrl(self):
        if self._event_modifiers is not None:
            return bool(self._event_modifiers & Qt.ControlModifier)
        return bool(self.input.ctrl())

    def _shift(self):
        if self._event_modifiers is not None:
            return bool(self._event_modifiers & Qt.ShiftModifier)
        return bool(self.input.shift())

    def _alt(self):
        if self._event_modifiers is not None:
            return bool(self._event_modifiers & Qt.AltModifier)
        return bool(self.input.alt())

    def handle_qt_key_event(self, event):
        """Consume a QApplication-routed QKeyEvent for this Explorer view.

        This is the retained-input path used by WinUx.  The old Dear PyGui
        callbacks remain available as a standalone compatibility fallback, but
        they are no longer required when QApplication owns the native keyboard
        bridge.
        """
        if not isinstance(event, QKeyEvent) or event.type() != QEvent.KeyPress:
            return False
        key = event.key()
        self._event_modifiers = event.modifiers()
        try:
            # A visible Explorer popup is an exclusive application popup target.
            # Give it navigation/activation keys before the underlying view.
            if self.view._context_menu_is_visible():
                if key == getattr(self.backend, "mvKey_Escape", None):
                    self._on_escape_pressed()
                    return True
                popup_commands = (
                    ("mvKey_Up", "up"), ("mvKey_Down", "down"),
                    ("mvKey_Left", "left"), ("mvKey_Right", "right"),
                    ("mvKey_Return", "activate"), ("mvKey_Enter", "activate"),
                    ("mvKey_NumPadEnter", "activate"),
                )
                for key_name, command in popup_commands:
                    native_key = getattr(self.backend, key_name, None)
                    if native_key is not None and key == native_key:
                        self.view._on_context_menu_key(user_data=command)
                        return True
                return False

            escape = getattr(self.backend, "mvKey_Escape", None)
            if escape is not None and key == escape:
                self._on_escape_pressed()
                return True

            direct = (
                ("mvKey_A", self._on_select_all_shortcut),
                ("mvKey_C", self._on_copy_shortcut),
                ("mvKey_X", self._on_cut_shortcut),
                ("mvKey_V", self._on_paste_shortcut),
                ("mvKey_F2", self._on_rename_shortcut),
                ("mvKey_F4", self._on_edit_shortcut),
                ("mvKey_F5", self._on_transfer_shortcut),
                ("mvKey_F7", self._on_new_folder_shortcut),
                ("mvKey_R", self._on_refresh_shortcut),
                ("mvKey_Delete", self._on_delete_shortcut),
            )
            for key_name, callback in direct:
                native_key = getattr(self.backend, key_name, None)
                if native_key is not None and key == native_key:
                    callback()
                    return True

            up = getattr(self.backend, "mvKey_Up", None)
            if up is not None and key == up and self._alt():
                self._on_parent_shortcut()
                return True

            for key_name in ("mvKey_Return", "mvKey_Enter", "mvKey_NumPadEnter"):
                native_key = getattr(self.backend, key_name, None)
                if native_key is not None and key == native_key:
                    self._on_enter_pressed()
                    return True

            for key_name in ("mvKey_Spacebar", "mvKey_Space"):
                native_key = getattr(self.backend, key_name, None)
                if native_key is not None and key == native_key:
                    self._on_space_pressed()
                    return True

            navigation = (
                ("mvKey_Up", "up"), ("mvKey_Down", "down"),
                ("mvKey_Home", "home"), ("mvKey_End", "end"),
                ("mvKey_PageUp", "page_up"), ("mvKey_PageDown", "page_down"),
            )
            for key_name, command in navigation:
                native_key = getattr(self.backend, key_name, None)
                if native_key is not None and key == native_key:
                    self._on_navigation_key(user_data=command)
                    return True
            return False
        finally:
            self._event_modifiers = None

    def _on_escape_pressed(self, sender=None, app_data=None, user_data=None):
        if self.view._context_menu_is_visible():
            self.view._hide_context_menus()
            return
        if self.view.cancel_inline_rename():
            return
        self.view._cancel_current_operation()

    def _on_select_all_shortcut(self, sender=None, app_data=None, user_data=None):
        if self.input.overlay_owns_input():
            self.view._clear_hover()
            return
        if self.view._has_focus and self._ctrl() and not self.view._rename_active:
            self.view.select_all()

    def _dispatch_clipboard_command(self, action):
        """Route clipboard shortcuts through the owning application.

        FilePanel supplies ``on_item_menu_action`` and its controller owns the
        cross-pane and Windows clipboard rules.  Standalone ExplorerListView
        users retain the original local-filesystem fallback.
        """
        if self.view.on_item_menu_action:
            self.view.on_item_menu_action(
                "command:{}".format(action), self.view.get_selected())
            return
        if action == "copy":
            self.view.copy_selected()
        elif action == "cut":
            self.view.cut_selected()
        elif action == "paste":
            self.view.paste()

    def _on_copy_shortcut(self, sender=None, app_data=None, user_data=None):
        if self.input.overlay_owns_input():
            self.view._clear_hover()
            return
        if self.view._has_focus and self._ctrl() and not self.view._rename_active:
            self._dispatch_clipboard_command("copy")

    def _on_cut_shortcut(self, sender=None, app_data=None, user_data=None):
        if self.input.overlay_owns_input():
            self.view._clear_hover()
            return
        if self.view._has_focus and self._ctrl() and not self.view._rename_active:
            self._dispatch_clipboard_command("cut")

    def _on_paste_shortcut(self, sender=None, app_data=None, user_data=None):
        if self.input.overlay_owns_input():
            self.view._clear_hover()
            return
        if self.view._has_focus and self._ctrl() and not self.view._rename_active:
            self._dispatch_clipboard_command("paste")

    def _on_rename_shortcut(self, sender=None, app_data=None, user_data=None):
        if self.input.overlay_owns_input():
            self.view._clear_hover()
            return
        if self.view._has_focus and not self.view._rename_active:
            if self.view.on_item_menu_action and self.view.get_selected():
                self.view.on_item_menu_action("command:rename", self.view.get_selected())
            else:
                self.view.begin_inline_rename()

    def _dispatch_winscp_command(self, action, require_selection=False):
        if self.input.overlay_owns_input():
            self.view._clear_hover()
            return False
        if not self.view._has_focus or self.view._rename_active:
            return False
        targets = self.view.get_selected()
        if require_selection and not targets:
            return False
        if self.view.on_item_menu_action:
            self.view.on_item_menu_action(
                "command:{}".format(action), targets)
            return True
        return False

    def _on_edit_shortcut(self, sender=None, app_data=None, user_data=None):
        # WinSCP-compatible F4: edit the selected remote file in WinUx's
        # internal editor; local selections fall back to the normal Open path.
        self._dispatch_winscp_command("edit", require_selection=True)

    def _on_transfer_shortcut(self, sender=None, app_data=None, user_data=None):
        # WinSCP-compatible F5: copy/transfer the selection to the opposite pane.
        self._dispatch_winscp_command("transfer_selected", require_selection=True)

    def _on_new_folder_shortcut(self, sender=None, app_data=None, user_data=None):
        # WinSCP-compatible F7: create a folder in the focused pane.
        self._dispatch_winscp_command("new_folder", require_selection=False)

    def _on_refresh_shortcut(self, sender=None, app_data=None, user_data=None):
        if self._ctrl():
            self._dispatch_winscp_command("refresh", require_selection=False)

    def _on_parent_shortcut(self, sender=None, app_data=None, user_data=None):
        if self._alt():
            self._dispatch_winscp_command("parent", require_selection=False)

    def _on_delete_shortcut(self, sender=None, app_data=None, user_data=None):
        if self.input.overlay_owns_input():
            self.view._clear_hover()
            return
        if self.view._has_focus and not self.view._rename_active:
            targets = self.view.get_selected()
            if not targets:
                return
            if self.view.on_item_menu_action:
                self.view.on_item_menu_action("command:delete", targets)
            else:
                # Standalone ExplorerListView users can provide their own
                # confirmation callback through on_item_menu_action.  Never
                # silently delete from a keyboard shortcut.
                return

    def _keyboard_item_view_ready(self):
        return bool(
            self.view._has_focus
            and not self.view._rename_active
            and not self.view._context_menu_is_visible()
            and not self.input.overlay_owns_input()
            and not self.input.pointer_blocked(self.view)
        )

    def _keyboard_current_index(self):
        if self.view._current_index is not None and 0 <= self.view._current_index < len(self.view.items):
            return int(self.view._current_index)
        selected = min((index for index in self.view.selected
                        if 0 <= index < len(self.view.items)), default=None)
        if selected is not None:
            return selected
        if self.view.last_clicked_index is not None and 0 <= self.view.last_clicked_index < len(self.view.items):
            return int(self.view.last_clicked_index)
        return 0 if self.view.items else None

    def _ensure_index_visible(self, index):
        if index is None or not (0 <= int(index) < len(self.view.items)):
            return
        try:
            _width, height = map(float, self.backend.get_item_rect_size(self.view.body_window))
            current = float(self.backend.get_y_scroll(self.view.body_window))
            maximum = float(self.backend.get_y_scroll_max(self.view.body_window))
        except Exception:
            return
        row_top = float(index) * float(self.view.ROW_HEIGHT)
        row_bottom = row_top + float(self.view.ROW_HEIGHT)
        target = current
        if row_top < current:
            target = row_top
        elif row_bottom > current + height:
            target = row_bottom - height
        target = max(0.0, min(maximum, target))
        if abs(target - current) >= 0.5:
            try:
                self.backend.set_y_scroll(self.view.body_window, target)
            except Exception:
                pass

    def _apply_keyboard_current(self, target):
        if not self.view.items:
            return False
        target = max(0, min(int(target), len(self.view.items) - 1))
        old_selected = set(self.view.selected)
        ctrl = self._ctrl()
        shift = self._shift()

        if self.view.single_selection:
            ctrl = False
            shift = False

        if not hasattr(self.view, "_sync_qt_selection_from_fields"):
            old_current = self.view._current_index
            self.view._current_index = target
            if shift:
                anchor = self.view.last_clicked_index
                if anchor is None or not (0 <= anchor < len(self.view.items)):
                    anchor = old_current if old_current is not None and 0 <= old_current < len(self.view.items) else target
                    self.view.last_clicked_index = anchor
                lo, hi = sorted((int(anchor), target))
                self.view.selected = set(range(lo, hi + 1))
            elif not ctrl:
                self.view.selected = {target}
                self.view.last_clicked_index = target
            self.view._update_selection_draws()
            self.view._update_status_bar()
            self._ensure_index_visible(target)
            if self.view.on_selection_change and old_selected != self.view.selected:
                self.view.on_selection_change(self.view.get_selected())
            return True

        state = self.view._sync_qt_selection_from_fields()
        if state.current is None:
            state.current = self._keyboard_current_index()
        state.move(absolute=target, ctrl=ctrl, shift=shift)
        self.view._sync_fields_from_qt_selection()
        self.view._update_selection_draws()
        self.view._update_status_bar()
        self._ensure_index_visible(target)
        if self.view.on_selection_change and old_selected != self.view.selected:
            self.view.on_selection_change(self.view.get_selected())
        return True

    def _on_navigation_key(self, sender=None, app_data=None, user_data=None):
        if not self._keyboard_item_view_ready() or self._alt():
            return
        current = self._keyboard_current_index()
        if current is None:
            return
        command = str(user_data or "")
        if command in ("page_up", "page_down"):
            try:
                _width, height = map(float, self.backend.get_item_rect_size(self.view.body_window))
                page = max(1, int(height // max(1, self.view.ROW_HEIGHT)) - 1)
            except Exception:
                page = 8
        if command == "up":
            target = current - 1
        elif command == "down":
            target = current + 1
        elif command == "home":
            target = 0
        elif command == "end":
            target = len(self.view.items) - 1
        elif command == "page_up":
            target = current - page
        elif command == "page_down":
            target = current + page
        else:
            return
        self._apply_keyboard_current(target)

    def _on_space_pressed(self, sender=None, app_data=None, user_data=None):
        if not self._keyboard_item_view_ready():
            return
        current = self._keyboard_current_index()
        if current is None:
            return
        if not hasattr(self.view, "_sync_qt_selection_from_fields"):
            self.view._current_index = current
            if self._ctrl() and not self.view.single_selection:
                if current in self.view.selected:
                    self.view.selected.remove(current)
                else:
                    self.view.selected.add(current)
            else:
                self.view.selected = {current}
                self.view.last_clicked_index = current
            self.view._update_selection_draws()
            self.view._update_status_bar()
            self._ensure_index_visible(current)
            if self.view.on_selection_change:
                self.view.on_selection_change(self.view.get_selected())
            return
        state = self.view._sync_qt_selection_from_fields()
        ctrl = self._ctrl() and not self.view.single_selection
        state.current = current
        if ctrl:
            state.select(
                current,
                ctrl=True,
                shift=False,
                selected=current not in state.selected,
            )
        else:
            state.select(current, ctrl=False, shift=False, selected=True)
        self.view._commit_selection_state()
        self._ensure_index_visible(current)

    def _on_enter_pressed(self, sender=None, app_data=None, user_data=None):
        if self.input.overlay_owns_input():
            self.view._clear_hover()
            return
        if self.view._rename_active:
            self.view.commit_inline_rename()
            return
        if not self._keyboard_item_view_ready():
            return
        current = self._keyboard_current_index()
        if current is not None:
            if not hasattr(self.view, "_sync_qt_selection_from_fields"):
                self.view._current_index = current
                if current not in self.view.selected:
                    self.view.selected = {current}
                    self.view.last_clicked_index = current
                    self.view._update_selection_draws()
                    self.view._update_status_bar()
                    if self.view.on_selection_change:
                        self.view.on_selection_change(self.view.get_selected())
                self.view.activate_item(current)
                return
            state = self.view._sync_qt_selection_from_fields()
            state.current = current
            if current not in self.view.selected:
                state.select(current, ctrl=False, shift=False, selected=True)
                self.view._commit_selection_state()
            else:
                self.view._sync_fields_from_qt_selection()
                self.view._update_selection_draws()
            self.view.activate_item(current)
