from __future__ import annotations

import dearpygui.dearpygui as dpg

from ..components import FloatingWindowResizer
from ..components.interaction_gate import (
    acquire_pointer_input, register_pointer_protected_item, release_pointer_input,
    unregister_pointer_protected_item,
)
from ..diagnostics import log_exception


class ConsoleDockingMixin:
    """SSH Console floating/docking and resize interaction behavior."""
    def _console_float_requested(self, floating):
        """Handle the QDockWidget Float/Dock title button and double-click."""
        if bool(floating):
            return self.undock_console()
        return self.dock_console()

    def _on_console_dock_header_drag(
            self, sender=None, app_data=None, user_data=None):
        """Tear the embedded Console off when its title is dragged."""
        if (not self._console_dock_visible
                or self._console_dock_mode != "docked"
                or self._console_dock_drag_requested
                or not getattr(self.console_dock, "movable", False)):
            return
        try:
            active = dpg.is_item_active(self.console_dock.drag_handle)
        except Exception:
            active = False
        if not active:
            return
        if not acquire_pointer_input(self._console_dock_drag_owner):
            return
        self._console_dock_drag_requested = True
        try:
            pointer = tuple(map(float, dpg.get_mouse_pos(local=False)))
        except Exception:
            pointer = None
        drag_anchor = None
        if pointer is not None:
            try:
                hx, hy = map(float, dpg.get_item_rect_min(
                    self.console_dock.drag_handle))
                drag_anchor = (
                    max(0.0, pointer[0] - hx),
                    max(0.0, pointer[1] - hy),
                )
            except Exception:
                drag_anchor = None
        self.undock_console(pointer, drag_anchor)

    def _on_console_dock_header_drag_release(
            self, sender=None, app_data=None, user_data=None):
        self._console_dock_drag_requested = False
        # The synthetic floating drag watcher performs the final drop test.
        # Releasing here is safe because background widgets see no pressed
        # button after this callback has run.
        release_pointer_input(self._console_dock_drag_owner)

    @staticmethod
    def _console_float_tag():
        return "winux_ssh_console_float"

    def _remember_console_float_geometry(self):
        tag = getattr(self, "_console_float_window", None)
        if not tag or not dpg.does_item_exist(tag):
            return
        try:
            self._console_float_geometry = {
                "pos": tuple(map(int, dpg.get_item_pos(tag))),
                "size": tuple(map(int, dpg.get_item_rect_size(tag))),
            }
        except Exception:
            pass

    def undock_console(self, pointer_pos=None, drag_anchor=None):
        """Detach the live SSH Console into a movable Qt-like tool window."""
        if not self._console_dock_visible:
            self.set_console_visible(True, persist=True, request_login=False)
        if self._console_dock_mode == "floating":
            tag = self._console_float_window
            if tag and dpg.does_item_exist(tag):
                dpg.configure_item(tag, show=True)
                dpg.focus_item(tag)
            return True

        if getattr(self, "_console_splitter_dragging", False):
            self._end_console_splitter_drag()
        tag = self._console_float_tag()
        if dpg.does_item_exist(tag):
            try:
                dpg.delete_item(tag)
            except Exception:
                pass

        try:
            dock_w, dock_h = map(int, dpg.get_item_rect_size(
                self.console_dock.root))
        except Exception:
            dock_w, dock_h = 0, 0
        saved = self._console_float_geometry or {}
        is_drag = bool(
            pointer_pos and len(pointer_pos) >= 2
            and drag_anchor and len(drag_anchor) >= 2)
        if is_drag:
            width = max(560, dock_w or 760)
            height = max(240, dock_h or 360)
            anchor_x = max(0.0, min(float(drag_anchor[0]), width - 24.0))
            anchor_y = max(4.0, min(float(drag_anchor[1]), 24.0))
            pos = (
                max(12, int(float(pointer_pos[0]) - anchor_x)),
                max(28, int(float(pointer_pos[1]) - anchor_y)),
            )
        else:
            size = saved.get("size") or (max(640, dock_w or 760), 360)
            width = max(560, int(size[0]))
            height = max(240, int(size[1]))
            pos = saved.get("pos")
            anchor_x, anchor_y = 48.0, 10.0

        def floating_closed(sender=None, app_data=None, user_data=None):
            self.after(0, self.hide_console)

        kwargs = dict(
            tag=tag, label="SSH Console", width=width, height=height,
            min_size=(520, 220), no_saved_settings=True, no_collapse=True,
            no_resize=True, on_close=floating_closed, show=True,
        )
        if pos is not None:
            kwargs["pos"] = tuple(map(int, pos))
        dpg.add_window(**kwargs)
        dpg.bind_item_theme(tag, self._floating_dock_window_theme)
        register_pointer_protected_item(tag)
        self._console_float_resizer = FloatingWindowResizer(
            tag, min_size=(520, 220))
        dpg.move_item(self.console_dock.root, parent=tag)
        dpg.configure_item(
            self.console_dock.root, width=-1, height=-1, show=True)
        self.console_dock.set_floating(True)
        self._console_dock_mode = "floating"
        self._console_float_window = tag
        try:
            self._console_float_last_position = tuple(
                map(float, dpg.get_item_pos(tag)))
        except Exception:
            self._console_float_last_position = None
        if is_drag:
            self._console_synthetic_float_drag = {
                "anchor": (float(anchor_x), float(anchor_y)),
            }
            self._console_float_dragging = True
            acquire_pointer_input(self._console_dock_drag_owner)
        else:
            self._console_synthetic_float_drag = None
            self._console_float_dragging = False
        self._layout_dirty = True
        self._resize_last_event = 0.0
        self._apply_split_layout(force=True)
        self.console_dock.sync_layout(force=True)
        self.console_panel.focus_input(follow_tail=False)
        return True

    def dock_console(self):
        """Reparent a floating Console back into the fixed bottom dock site."""
        self._set_console_dock_preview(False)
        if self._console_dock_mode == "docked":
            self._layout_dirty = True
            self._apply_split_layout(force=True)
            return True
        self._remember_console_float_geometry()
        tag = self._console_float_window
        resizer = self._console_float_resizer
        if resizer is not None:
            resizer.destroy()
        self._console_float_resizer = None
        release_pointer_input(self._console_dock_drag_owner)
        unregister_pointer_protected_item(tag)
        dpg.move_item(self.console_dock.root, parent=self.console_region)
        dpg.configure_item(
            self.console_dock.root, width=-1, height=-1,
            show=self._console_dock_visible)
        self.console_dock.set_floating(False)
        self._console_dock_mode = "docked"
        if tag and dpg.does_item_exist(tag):
            try:
                dpg.delete_item(tag)
            except Exception:
                pass
        self._console_float_window = None
        self._console_float_last_position = None
        self._console_float_dragging = False
        self._console_synthetic_float_drag = None
        self._console_dock_drag_requested = False
        self._layout_dirty = True
        self._resize_last_event = 0.0
        self._apply_split_layout(force=True)
        if self._console_dock_visible:
            self.console_panel.focus_input(follow_tail=False)
        return True

    def _cancel_console_float_interaction(self):
        self._set_console_dock_preview(False)
        self._console_float_dragging = False
        self._console_synthetic_float_drag = None
        self._console_dock_drag_requested = False
        release_pointer_input(self._console_dock_drag_owner)
        resizer = getattr(self, "_console_float_resizer", None)
        if resizer is not None:
            resizer.destroy()
        self._console_float_resizer = None
        tag = getattr(self, "_console_float_window", None)
        if tag:
            unregister_pointer_protected_item(tag)

    def _console_dock_target_at_pointer(self):
        """Return True while pointer is in/near the allowed bottom dock."""
        if not self._console_dock_visible:
            return False
        geometry = self._console_dock_preview_geometry()
        if geometry is None:
            return False
        for point in self._dock_pointer_candidates():
            if self._point_near_rect(
                    point, geometry, self.DOCK_SNAP_DISTANCE):
                return True
        return False

    def _console_dock_preview_geometry(self):
        try:
            root_x, root_y = map(float, dpg.get_item_rect_min(self.layout_root))
            width, height = map(float, dpg.get_item_rect_size(self.layout_root))
            split_y = float(dpg.get_item_pos(self.horizontal_splitter_hitbox)[1])
            lower_y = split_y + self.FILE_JOB_SPLITTER_GUTTER_SIZE
            lower_h = max(1.0, height - lower_y)
            target_h = min(
                max(self.MIN_CONSOLE_DOCK_HEIGHT,
                    float(self._console_dock_height)),
                max(self.MIN_CONSOLE_DOCK_HEIGHT,
                    lower_h - self.MIN_BOTTOM_HEIGHT
                    - self.CONSOLE_DOCK_SPLITTER_GUTTER_SIZE),
            )
            target_h = min(target_h, lower_h)
            return (root_x, root_y + lower_y + lower_h - target_h,
                    max(1.0, width - 1.0), max(1.0, target_h))
        except Exception:
            return None

    def _set_console_dock_preview(self, visible):
        if not visible:
            self._hide_dock_drop_preview()
            return
        geometry = self._console_dock_preview_geometry()
        if geometry is None:
            self._hide_dock_drop_preview()
            return
        self._show_dock_drop_preview(geometry, inset=True)

    def _floating_console_titlebar_hit(self, tag):
        try:
            wx, wy = map(float, dpg.get_item_pos(tag))
            width, _ = map(float, dpg.get_item_rect_size(tag))
            title_h = 26.0
            try:
                _, client_y = map(float, dpg.get_item_rect_min(
                    self.console_dock.root))
                measured = client_y - wy
                if 16.0 <= measured <= 64.0:
                    title_h = measured
            except Exception:
                pass
            return any(
                wx <= mx <= wx + max(1.0, width)
                and wy <= my <= wy + title_h
                for mx, my in self._dock_pointer_candidates())
        except Exception:
            return False

    def _update_floating_console_resize_interaction(self):
        if (self._console_dock_mode != "floating"
                or not self._console_dock_visible):
            return
        controller = self._console_float_resizer
        tag = self._console_float_window
        if controller is None or not tag or not dpg.does_item_exist(tag):
            return
        active = controller.update()
        if active:
            self._console_float_dragging = False
            self._console_synthetic_float_drag = None
            self._set_console_dock_preview(False)
        try:
            self.console_dock.sync_layout(force=active)
        except Exception:
            pass

    def _update_floating_console_docking(self):
        """Move/dock the detached Console with QDockWidget-like semantics."""
        tag = self._console_float_window
        if (self._console_dock_mode != "floating" or not tag
                or not dpg.does_item_exist(tag)
                or not self._console_dock_visible):
            self._set_console_dock_preview(False)
            return
        controller = self._console_float_resizer
        if controller is not None and controller.resizing:
            self._set_console_dock_preview(False)
            return
        down = self._left_mouse_button_down()
        press_started = self._left_mouse_pressed()
        escape_pressed = self._escape_key_pressed()
        double_clicked = self._left_mouse_double_clicked()
        synthetic = self._console_synthetic_float_drag
        if (synthetic is None and press_started
                and self._floating_console_titlebar_hit(tag)):
            self._console_float_dragging = True
            acquire_pointer_input(self._console_dock_drag_owner)
        if synthetic is not None:
            if escape_pressed:
                self._console_synthetic_float_drag = None
                self._console_float_dragging = False
                release_pointer_input(self._console_dock_drag_owner)
                self.after(0, self.dock_console)
                return
            if down:
                try:
                    mx, my = map(float, dpg.get_mouse_pos(local=False))
                    ax, ay = synthetic.get("anchor", (48.0, 10.0))
                    pos = (max(0, int(mx - float(ax))),
                           max(20, int(my - float(ay))))
                    dpg.configure_item(tag, pos=pos)
                    self._console_float_last_position = tuple(map(float, pos))
                except Exception:
                    pass
                acquire_pointer_input(self._console_dock_drag_owner)
                self._console_float_dragging = True
                self._set_console_dock_preview(
                    self._console_dock_target_at_pointer())
                return
            self._console_synthetic_float_drag = None
            self._console_float_dragging = False
            release_pointer_input(self._console_dock_drag_owner)
            target = self._console_dock_target_at_pointer()
            self._set_console_dock_preview(False)
            if target:
                self.after(0, self.dock_console)
            return

        if double_clicked and self._floating_console_titlebar_hit(tag):
            release_pointer_input(self._console_dock_drag_owner)
            self._console_float_dragging = False
            self._set_console_dock_preview(False)
            self.after(0, self.dock_console)
            return
        try:
            pos = tuple(map(float, dpg.get_item_pos(tag)))
        except Exception:
            return
        previous = self._console_float_last_position
        if down and previous is not None:
            if (abs(pos[0] - previous[0]) > 0.5
                    or abs(pos[1] - previous[1]) > 0.5):
                self._console_float_dragging = True
                acquire_pointer_input(self._console_dock_drag_owner)
            if self._console_float_dragging:
                self._set_console_dock_preview(
                    self._console_dock_target_at_pointer())
        elif not down and self._console_float_dragging:
            self._console_float_dragging = False
            release_pointer_input(self._console_dock_drag_owner)
            target = self._console_dock_target_at_pointer()
            self._set_console_dock_preview(False)
            if target:
                self.after(0, self.dock_console)
                return
        elif not down:
            release_pointer_input(self._console_dock_drag_owner)
        self._console_float_last_position = pos

    def _console_menu_toggled(self, visible):
        self.set_console_visible(
            bool(visible), persist=True, request_login=bool(visible))

    def _set_console_keyboard_active(self, active, panel=None):
        if active:
            target = panel or getattr(self, "console_panel", None)
            if target is not None and self._console_dock_visible:
                self._console_keyboard_panel = target
        elif panel is None or self._console_keyboard_panel is panel:
            self._console_keyboard_panel = None

    def set_console_visible(self, visible, persist=True, request_login=False):
        """Show/hide the embedded SSH Console dock and optionally persist it."""
        visible = bool(visible)
        self._console_dock_visible = visible
        if not visible:
            self._set_console_keyboard_active(False)
            if getattr(self, "_console_splitter_dragging", False):
                self._end_console_splitter_drag()
        docked_visible = bool(
            visible and self._console_dock_mode == "docked")
        try:
            if dpg.does_item_exist(self.console_region):
                dpg.configure_item(self.console_region, show=docked_visible)
            if dpg.does_item_exist(self.console_separator):
                dpg.configure_item(self.console_separator, show=docked_visible)
            if dpg.does_item_exist(self.console_separator_hitbox):
                dpg.configure_item(
                    self.console_separator_hitbox, show=docked_visible)
            float_tag = getattr(self, "_console_float_window", None)
            if float_tag and dpg.does_item_exist(float_tag):
                dpg.configure_item(
                    float_tag,
                    show=bool(visible and self._console_dock_mode == "floating"))
            menu_item = getattr(self, "console_menu_item", None)
            if menu_item is not None and dpg.does_item_exist(menu_item):
                dpg.set_value(menu_item, visible)
        except Exception:
            pass
        if persist:
            try:
                self._general_preferences.save_console_visible(visible)
            except Exception:
                log_exception(
                    "Failed to save SSH Console dock visibility",
                    sys.exc_info(), fatal=False)
        self._layout_dirty = True
        self._resize_last_event = 0.0
        self._apply_split_layout(force=True)
        if visible:
            panel = getattr(self, "console_panel", None)
            if panel is not None:
                panel.focus_input()
            if request_login:
                connected = self.callbacks.get("console_connected")
                if callable(connected) and not connected():
                    self.after(0, self.show_login)
        return getattr(self, "console_panel", None)

    def show_console(self):
        return self.set_console_visible(
            True, persist=True, request_login=True)

    def hide_console(self):
        self.set_console_visible(False, persist=True, request_login=False)
