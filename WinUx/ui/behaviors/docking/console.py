from __future__ import annotations

import sys
from DearUIQt.widgets import QApplication, QRetainedItem
from DearUIQt.gui import QCursor

from DearUIQt.input_gate import (
    acquire_pointer_input, release_pointer_input,
    unregister_pointer_protected_item,
)
from ....diagnostics import log_exception


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
                    max(1.0, float(handle_rect.width())),
                    max(1.0, float(handle_rect.height())),
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

    def _create_console_native_host(self, panel, *, drag_anchor=None, visible=True):
        """Create the detached Console renderer without changing dock state.

        When ``visible`` is False this is a resident mirror: the expensive
        terminal form, native viewport and renderer are prepared while the
        embedded QDockWidget remains authoritative.  A later tear-off is then
        a show-only transition instead of form construction on the drag path.
        """
        from ....dialogs.native_dock_hosts import ConsoleDockHost

        def closed(closing):
            if getattr(self, "_native_console_host", None) is not closing:
                return
            self._native_console_host = None
            if (getattr(self, "_console_undock_pending_host", None) is not closing
                    and getattr(self, "_console_dock_mode", "docked") == "docked"):
                # A hidden resident mirror is only a latency cache. Losing it
                # never changes the live embedded Console.
                return
            if getattr(self, "_console_undock_pending_host", None) is closing:
                self._console_undock_pending_host = None
                self._console_dock_mode = "docked"
                self.console_dock.set_floating(False, sync=False)
                QRetainedItem(self.console_dock.root).setVisible(self._console_dock_visible)
                self.set_console_visible(self._console_dock_visible, request_login=False)
                return
            self.hide_console()

        def dock(requesting):
            if getattr(self, "_native_console_host", None) is requesting:
                self.dock_console(
                    area=getattr(requesting, "_requested_dock_area", None),
                    scope=getattr(requesting, "_requested_dock_scope", None),
                    _native_confirmed=True)

        host = ConsoleDockHost(
            self, panel, dock, closed, drag_anchor=drag_anchor, visible=visible)
        self._native_console_host = host
        return host

    def _prepare_console_native_host(self):
        """Build a hidden detached Console after the dock becomes usable."""
        if (not getattr(self, "_alive", True)
                or not getattr(self, "_console_dock_visible", False)
                or getattr(self, "_console_dock_mode", "docked") != "docked"):
            return False
        host = getattr(self, "_native_console_host", None)
        if host is not None and host.winfo_exists():
            return True
        panel = getattr(self, "console_panel", None)
        if panel is None:
            return False
        try:
            self._create_console_native_host(panel, visible=False)
            return True
        except Exception:
            # This is only a latency cache. Normal undock retains the cold
            # fallback and must remain usable if background preparation fails.
            return False

    def _commit_console_float(self, host):
        if (getattr(self, "_native_console_host", None) is not host
                or getattr(self, "_console_undock_pending_host", None) is not host
                or not host.winfo_exists()):
            return
        self._console_undock_pending_host = None
        self._console_dock_mode = "floating"
        self.console_dock.set_floating(True, sync=False)
        QRetainedItem(self.console_dock.root).hide()
        self.set_console_visible(True, request_login=False)

    def undock_console(self, pointer_pos=None, drag_anchor=None):
        """Detach into a real modeless HWND, using the resident mirror first."""
        host = getattr(self, "_native_console_host", None)
        if host is not None and host.winfo_exists():
            if drag_anchor is not None:
                from ....platform.native_dock_gesture import release_owner_capture
                release_owner_capture(self)
            # A mirror can still be finishing its background construction when
            # the user starts dragging. Mark it pending before show so the first
            # presented frame atomically replaces the embedded dock.
            self._console_undock_pending_host = host
            host.after_first_present(self._commit_console_float, host)
            if getattr(host, "_ready", False):
                host.show_immediate(drag_anchor)
            else:
                host.show()
                if drag_anchor is not None:
                    host.post("begin_dock_move", drag_anchor)
            return True

        if not self._console_dock_visible:
            self._console_dock_visible = True
        if getattr(self, "_console_splitter_dragging", False):
            self._end_console_splitter_drag()
        self._cancel_console_float_interaction()
        self._set_console_keyboard_active(False)
        panel = self._ensure_console_panel()
        panel._hide_context_menu()
        panel._selection_dragging = False
        if drag_anchor is not None:
            from ....platform.native_dock_gesture import release_owner_capture
            release_owner_capture(self)
        host = self._create_console_native_host(
            panel, drag_anchor=drag_anchor, visible=True)
        self._console_undock_pending_host = host
        host.after_first_present(self._commit_console_float, host)
        return True

    def dock_console(self, area=None, scope=None, *, _native_confirmed=False):
        if scope is not None:
            self._console_dock_scope = (
                "outer" if str(scope).strip().lower() == "outer" else "inner")
        if area is not None:
            self._console_dock_area = self._normalize_console_dock_area(area)
            try:
                self.console_dock.set_dock_area(self._console_dock_area)
            except Exception:
                pass
        host = getattr(self, "_native_console_host", None)
        pending = getattr(self, "_console_undock_pending_host", None)
        if host is not None and host is pending and not _native_confirmed:
            # A dock request during the short native-startup phase simply
            # cancels the pending tear-off; the embedded dock never disappeared.
            self._console_undock_pending_host = None
            self._native_console_host = None
            host.destroy()
            self._console_dock_mode = "docked"
            self.console_dock.set_floating(False, sync=False)
            QRetainedItem(self.console_dock.root).setVisible(self._console_dock_visible)
            persist_dock = getattr(self, "_persist_dock_state", None)
            if callable(persist_dock):
                persist_dock()
            return True
        if host is not None and host.winfo_exists() and not _native_confirmed:
            return host.post("request_dock")
        if host is not None:
            if pending is host:
                # A not-yet-present host is not useful as a retained tear-off.
                self._native_console_host = None
                self._console_undock_pending_host = None
                host.destroy()
                host = None
            elif host.winfo_exists() and getattr(host, "_ready", False):
                # Docking is a visibility/state transition, not destruction.
                # Keep the HWND, renderer and terminal form resident so a later
                # undock can appear immediately.
                host.hide()
            else:
                self._native_console_host = None
                host.destroy()
                host = None
        self._cancel_console_float_interaction()
        self._console_dock_mode = "docked"
        self.console_dock.set_floating(False, sync=False)
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

    @staticmethod
    def _normalize_console_dock_area(area):
        value = str(area or "bottom").strip().lower()
        return value if value in ("left", "right", "top", "bottom") else "bottom"

    def _console_dock_target_at_pointer(self):
        """Return a Console target only while one visible guide is hovered."""
        self._dock_preview_scope = None
        if not self._console_dock_visible:
            return None
        bounds = getattr(self, "_dock_guide_geometry", lambda: None)()
        if bounds is None:
            return None
        try:
            from DearUIQt.widgets import DockDropPreview
        except Exception:
            return None
        for point in self._dock_pointer_candidates():
            area, scope = DockDropPreview.zone_hit(point, bounds, tolerance=6.0)
            if area is not None:
                self._dock_preview_scope = scope or 'inner'
                return area
        return None

    def _console_dock_preview_geometry(self, area=None):
        """Return the resulting Console rectangle for one four-way drop."""
        area = self._normalize_console_dock_area(
            self._console_dock_area if area is None else area)
        scope = getattr(self, "_dock_preview_scope", None)
        if scope == 'outer':
            bounds = getattr(self, "_dock_guide_geometry", lambda: None)()
        else:
            bounds = getattr(self, "_dock_site_geometry", lambda: None)()
        if bounds is None:
            return None
        x, y, width, height = map(float, bounds)
        if area in ("left", "right"):
            target = min(max(float(getattr(self, "_console_dock_width", 320)),
                             float(getattr(self, "MIN_CONSOLE_DOCK_WIDTH", 220))),
                         max(1.0, width * 0.50))
            if area == "right":
                x += width - target
            return x, y, target, height
        target = min(max(float(self._console_dock_height),
                         float(self.MIN_CONSOLE_DOCK_HEIGHT)),
                     max(1.0, height * 0.50))
        if area == "bottom":
            y += height - target
        return x, y, width, target

    def _set_console_dock_preview(self, visible, area=None):
        if not visible:
            self._dock_preview_scope = None
            self._hide_dock_drop_preview()
            return
        bounds = getattr(self, "_dock_guide_geometry", lambda: None)()
        active = None
        geometry = None
        if area is not None:
            active = self._normalize_console_dock_area(area)
            geometry = self._console_dock_preview_geometry(active)
        preview = self._ensure_dock_drop_preview()
        if bounds is None or preview is None:
            self._hide_dock_drop_preview()
            return
        try:
            preview.show_zones(
                bounds, active=active,
                active_scope=getattr(self, "_dock_preview_scope", None),
                preview_rect=geometry)
        except Exception:
            self._hide_dock_drop_preview()

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
            self._set_console_dock_preview(True, None)
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
                target = self._console_dock_target_at_pointer()
                self._set_console_dock_preview(True, target)
                return
            self._console_synthetic_float_drag = None
            self._console_float_dragging = False
            release_pointer_input(self._console_dock_drag_owner)
            target = self._console_dock_target_at_pointer()
            scope = getattr(self, "_dock_preview_scope", None)
            self._set_console_dock_preview(False)
            if target:
                self.after(0, self.dock_console, target, scope)
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
                target = self._console_dock_target_at_pointer()
                self._set_console_dock_preview(True, target)
        elif not down and self._console_float_dragging:
            self._console_float_dragging = False
            release_pointer_input(self._console_dock_drag_owner)
            target = self._console_dock_target_at_pointer()
            scope = getattr(self, "_dock_preview_scope", None)
            self._set_console_dock_preview(False)
            if target:
                self.after(0, self.dock_console, target, scope)
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
            persist_dock = getattr(self, "_persist_dock_state", None)
            if callable(persist_dock):
                persist_dock()
        self._layout_dirty = True
        self._resize_last_event = 0.0
        self._apply_split_layout(force=True)
        if visible:
            panel = self._ensure_console_panel()
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
