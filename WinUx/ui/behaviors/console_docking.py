from __future__ import annotations

import sys
from DearUIQt.widgets import QApplication, QRetainedItem
from DearUIQt.gui import QCursor

from DearUIQt.input_gate import (
    acquire_pointer_input, release_pointer_input,
    unregister_pointer_protected_item,
)
from ...diagnostics import log_exception


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
            active = self.console_dock.dragHandleWidget().isActive()
        except Exception:
            active = False
        if not active:
            return
        if not acquire_pointer_input(self._console_dock_drag_owner):
            return
        self._console_dock_drag_requested = True
        try:
            point = QCursor.pos()
            pointer = (float(point.x()), float(point.y()))
        except Exception:
            pointer = None
        drag_anchor = None
        if pointer is not None:
            try:
                handle_rect = self.console_dock.dragHandleWidget().globalGeometry()
                hx, hy = float(handle_rect.x()), float(handle_rect.y())
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
        item = QRetainedItem(tag) if tag else None
        if item is None or not item.exists():
            return
        try:
            self._console_float_geometry = {
                "pos": tuple(map(int, item.pos().toTuple())),
                "size": tuple(map(int, item.size().toTuple())),
            }
        except Exception:
            pass

    def undock_console(self, pointer_pos=None, drag_anchor=None):
        """Detach into a real modeless HWND, not an in-viewport DPG window."""
        from ...dialogs.native_dock_hosts import ConsoleDockHost
        host = getattr(self, "_native_console_host", None)
        if host is not None and host.winfo_exists():
            host.show()
            return True
        if not self._console_dock_visible:
            self._console_dock_visible = True
        if getattr(self, "_console_splitter_dragging", False):
            self._end_console_splitter_drag()
        self._cancel_console_float_interaction()
        self._set_console_keyboard_active(False)
        self.console_panel._hide_context_menu()
        self.console_panel._selection_dragging = False

        def closed(closing):
            if getattr(self, "_native_console_host", None) is not closing:
                return
            self._native_console_host = None
            if getattr(self, "_console_undock_pending_host", None) is closing:
                # Native tear-off never reached its first presented frame. Keep
                # the embedded QDockWidget intact instead of leaving a visual gap.
                self._console_undock_pending_host = None
                self._console_dock_mode = "docked"
                self.console_dock.set_floating(False)
                QRetainedItem(self.console_dock.root).setVisible(self._console_dock_visible)
                self.set_console_visible(self._console_dock_visible, request_login=False)
                return
            self.hide_console()

        def dock(requesting):
            if getattr(self, "_native_console_host", None) is requesting:
                self.dock_console(_native_confirmed=True)

        if drag_anchor is not None:
            from ...platform.native_dock_gesture import release_owner_capture
            release_owner_capture(self)
        host = ConsoleDockHost(self, self.console_panel, dock, closed, drag_anchor=drag_anchor)
        self._native_console_host = host
        self._console_undock_pending_host = host

        def commit_float():
            if (getattr(self, "_native_console_host", None) is not host
                    or getattr(self, "_console_undock_pending_host", None) is not host
                    or not host.winfo_exists()):
                return
            # Keep the embedded dock painted until the native HWND has already
            # produced its first visible frame. The handoff is then one UI turn
            # instead of hide -> startup gap -> floating window.
            self._console_undock_pending_host = None
            self._console_dock_mode = "floating"
            self.console_dock.set_floating(True)
            QRetainedItem(self.console_dock.root).hide()
            self.set_console_visible(True, request_login=False)

        host.after_first_present(commit_float)
        return True

    def dock_console(self, *, _native_confirmed=False):
        host = getattr(self, "_native_console_host", None)
        pending = getattr(self, "_console_undock_pending_host", None)
        if host is not None and host is pending and not _native_confirmed:
            # A dock request during the short native-startup phase simply
            # cancels the pending tear-off; the embedded dock never disappeared.
            self._console_undock_pending_host = None
            self._native_console_host = None
            host.destroy()
            self._console_dock_mode = "docked"
            self.console_dock.set_floating(False)
            QRetainedItem(self.console_dock.root).setVisible(self._console_dock_visible)
            return True
        if host is not None and host.winfo_exists() and not _native_confirmed:
            return host.post("request_dock")
        if host is not None:
            self._native_console_host = None
            if pending is host:
                self._console_undock_pending_host = None
            host.destroy()
        self._cancel_console_float_interaction()
        self._console_dock_mode = "docked"
        self.console_dock.set_floating(False)
        QRetainedItem(self.console_dock.root).setVisible(self._console_dock_visible)
        self.set_console_visible(self._console_dock_visible, request_login=False)
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
            root_rect = QRetainedItem(self.layout_root).globalGeometry()
            root_x, root_y = float(root_rect.x()), float(root_rect.y())
            width, height = float(root_rect.width()), float(root_rect.height())
            split_y = float(QRetainedItem(self.horizontal_splitter_hitbox).pos().y())
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
            window = QRetainedItem(tag)
            point, size = window.pos(), window.size()
            wx, wy = float(point.x()), float(point.y())
            width = float(size.width())
            title_h = 26.0
            try:
                client_y = float(QRetainedItem(
                    self.console_dock.root).globalGeometry().y())
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
        if controller is None or not tag or not QRetainedItem(tag).exists():
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
        if self._native_dock_preview_is_active():
            return
        tag = self._console_float_window
        if (self._console_dock_mode != "floating" or not tag
                or not QRetainedItem(tag).exists()
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
                    point = QCursor.pos()
                    mx, my = float(point.x()), float(point.y())
                    ax, ay = synthetic.get("anchor", (48.0, 10.0))
                    pos = (max(0, int(mx - float(ax))),
                           max(20, int(my - float(ay))))
                    QRetainedItem(tag).setPosition(pos)
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
            pos = tuple(map(float, QRetainedItem(tag).pos().toTuple()))
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
        target = panel or getattr(self, "console_panel", None)
        application = QApplication.instance()
        if active:
            if (target is not None and self._console_dock_visible
                    and self._console_dock_mode == "docked"):
                self._console_keyboard_panel = target
                # A retained draw-list terminal is not a QWidget, but it still
                # must own QApplication keyboard routing.  Otherwise Enter is
                # delivered to the previously focused Explorer view as well as
                # the Console's DPG handler, opening a selected file while the
                # command is submitted.
                if application is not None:
                    try:
                        application.setFocusObject(target)
                    except Exception:
                        pass
            else:
                self._console_keyboard_panel = None
        elif panel is None or self._console_keyboard_panel is panel:
            previous = self._console_keyboard_panel
            self._console_keyboard_panel = None
            if application is not None and previous is not None:
                try:
                    # Do not clear a newer focus target established by the
                    # physical click that deactivated the Console.
                    application.clearFocusObject(previous)
                except Exception:
                    pass

    def set_console_visible(self, visible, persist=True, request_login=False):
        """Show/hide the embedded SSH Console dock and optionally persist it."""
        visible = bool(visible)
        self._console_dock_visible = visible
        dock = getattr(self, "console_dock", None)
        if dock is not None:
            # Keep QDockWidget::visibilityChanged/toggleViewAction state as the
            # single source of truth even when visibility is changed by host
            # commands rather than the View menu. notify=False prevents the
            # dock's host callback from recursively calling this method.
            dock.set_visible(visible, notify=False)
        if not visible:
            self._set_console_keyboard_active(False)
            self._cancel_console_float_interaction()
            host = getattr(self, "_native_console_host", None)
            if host is not None:
                self._native_console_host = None
                host.destroy()
            if getattr(self, "_console_splitter_dragging", False):
                self._end_console_splitter_drag()
        docked_visible = bool(
            visible and self._console_dock_mode == "docked")
        try:
            for tag in (self.console_region, self.console_separator,
                        self.console_separator_hitbox):
                item = QRetainedItem(tag)
                if item.exists():
                    item.setVisible(docked_visible)
            float_tag = getattr(self, "_console_float_window", None)
            if float_tag:
                floating = QRetainedItem(float_tag)
                if floating.exists():
                    floating.setVisible(bool(
                        visible and self._console_dock_mode == "floating"))
            menu_item = getattr(self, "console_menu_item", None)
            if menu_item is not None and hasattr(menu_item, "setChecked"):
                # QAction::setChecked emits toggled; state synchronization must
                # not recursively invoke set_console_visible. This mirrors Qt
                # code which uses QSignalBlocker while updating a bound action.
                from DearUIQt.core import QSignalBlocker
                with QSignalBlocker(menu_item):
                    menu_item.setChecked(visible)
            elif menu_item is not None:
                retained_menu = QRetainedItem(menu_item)
                if retained_menu.exists():
                    retained_menu.setValue(visible)
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
            if self._console_dock_mode == "floating":
                host = getattr(self, "_native_console_host", None)
                if host is None or not host.winfo_exists():
                    self.undock_console()
                else:
                    host.show()
            elif panel is not None:
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
