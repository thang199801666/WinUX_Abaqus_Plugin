from __future__ import annotations

import time

from DearUIQt.core import Qt
from DearUIQt.gui import QCursor, QKeyboard, QScreen
from DearUIQt.widgets import QRetainedItem

from ..components import JobPlotsWindow
from DearUIQt.input_gate import (
    unregister_pointer_protected_item,
)


class PlotDockingMixin:
    """Job Plots floating/docking behavior separated from WinUXView."""
    @staticmethod
    def _get_reference_chart_library(view):
        """Return the one app-wide reference library, creating it lazily.

        Reference curves are independent of a running job.  The main menu can
        therefore open their manager before the first Plot dock exists, while
        every later Plot dock still receives this exact same library instance.
        """
        library = getattr(view, "_reference_chart_library", None)
        if library is None:
            from ...services.reference_charts import ReferenceChartLibrary
            library = ReferenceChartLibrary()
            view._reference_chart_library = library
        return library

    def _update_floating_plot_resize_interaction(self):
        """Update custom eight-way resizing for every detached Plot dock."""
        for key, controller in list(self._plot_float_resizers.items()):
            key = str(key)
            tag = self.job_plot_float_windows.get(key)
            if (controller is None or not tag
                    or not QRetainedItem(tag).exists()):
                if controller is not None:
                    controller.destroy()
                self._plot_float_resizers.pop(key, None)
                continue
            active = controller.update()
            if active:
                # North/west resize changes window position. Do not let the
                # QDockWidget drag-back watcher interpret that as title motion.
                self._plot_float_dragging.discard(key)
                self._plot_synthetic_float_drag.pop(key, None)
                self._set_plot_dock_preview(False)
                try:
                    self._plot_float_last_positions[key] = tuple(map(float, QRetainedItem(tag).pos().toTuple()))
                except Exception:
                    pass

    def _floating_plot_is_resizing(self, key):
        controller = self._plot_float_resizers.get(str(key))
        return bool(controller is not None and controller.resizing)

    def _set_plot_dock_open(self, opened):
        opened = bool(opened)
        if self._plot_dock_open == opened:
            return
        self._plot_dock_open = opened
        self._layout_dirty = True
        self._apply_split_layout(force=True)

    def _job_plot_float_tag(self, job_id):
        safe = "".join(ch if ch.isalnum() else "_" for ch in str(job_id))
        return "job_plots_float_{}".format(safe)

    def _remember_plot_float_geometry(self, job_id, tag=None):
        key = str(job_id)
        tag = tag or self.job_plot_float_windows.get(key)
        if not tag or not QRetainedItem(tag).exists():
            return None
        try:
            geometry = QRetainedItem(tag).globalGeometry()
            x, y = geometry.x(), geometry.y()
            width, height = geometry.width(), geometry.height()
            if width <= 1 or height <= 1:
                return None
            geometry = {
                "pos": (x, y),
                "size": (width, height),
            }
            self._plot_float_geometries[key] = geometry
            return geometry
        except Exception:
            return None

    @staticmethod
    def _escape_key_pressed():
        try:
            return bool(QKeyboard.isKeyPressed(Qt.Key_Escape))
        except Exception:
            return False

    def _remove_job_plot_float_window(self, job_id):
        self._set_plot_dock_preview(False)
        key = str(job_id)
        host = getattr(self, "_native_plot_hosts", {}).pop(key, None)
        if host is not None:
            host.destroy()
        tag = self.job_plot_float_windows.pop(key, None)
        self._remember_plot_float_geometry(key, tag)
        self._plot_float_last_positions.pop(key, None)
        self._plot_float_dragging.discard(key)
        self._plot_synthetic_float_drag.pop(key, None)
        resizer = self._plot_float_resizers.pop(key, None)
        if resizer is not None:
            resizer.destroy()
        unregister_pointer_protected_item(tag)
        window = self.job_plot_windows.get(key)
        if window is not None:
            window.end_pointer_capture()
        if tag and QRetainedItem(tag).exists():
            try:
                QRetainedItem(tag).deleteNative()
            except Exception:
                pass

    def _sync_job_plot_windows(self):
        """Keep dock title controls aligned while panes/windows are resized."""
        for window in list(self.job_plot_windows.values()):
            try:
                if window is not None and window.exists():
                    window.sync_layout()
            except Exception:
                pass

    def _dock_pointer_candidates(self):
        """Return pointer coordinates in the spaces DPG may expose.

        Windows/DPI combinations differ in whether get_mouse_pos(False) is
        viewport- or desktop-relative.  Testing the small deterministic set of
        transforms keeps docking feedback stable across both conventions.
        """
        native = getattr(self, "_native_dock_pointer_candidates", None)
        if native is not None:
            return native
        candidates = []
        try:
            point = QCursor.pos()
            raw = (float(point.x()), float(point.y()))
            candidates.append(raw)
        except Exception:
            raw = None
        try:
            point = QCursor.localPos()
            local = (float(point.x()), float(point.y()))
            if local not in candidates:
                candidates.append(local)
        except Exception:
            pass
        if raw is not None:
            try:
                viewport = QScreen().geometry()
                vx, vy = float(viewport.x()), float(viewport.y())
                for point in ((raw[0] - vx, raw[1] - vy),
                              (raw[0] + vx, raw[1] + vy)):
                    if point not in candidates:
                        candidates.append(point)
            except Exception:
                pass
        return tuple(candidates)

    @staticmethod
    def _point_near_rect(point, rect, margin=0.0):
        mx, my = point
        x, y, width, height = rect
        margin = max(0.0, float(margin))
        return (x - margin <= mx <= x + width + margin
                and y - margin <= my <= y + height + margin)

    def _show_dock_drop_preview(self, geometry, *, inset=True):
        preview = getattr(self, "_dock_drop_preview", None)
        if preview is None or geometry is None:
            return False
        try:
            x, y, width, height = geometry
            return bool(preview.show(x, y, width, height, inset=inset))
        except Exception:
            return False

    def _hide_dock_drop_preview(self):
        preview = getattr(self, "_dock_drop_preview", None)
        if preview is not None:
            preview.hide()

    def _plot_dock_target_at_pointer(self):
        """Return the nearest allowed Plot dock area within snap distance.

        Native Qt begins showing docking feedback *before* the cursor fully
        enters the dock rectangle.  Expand the Job workspace by a modest snap
        margin and choose the nearest edge.  The centre of an existing Plot
        group remains a tabify target.
        """
        try:
            region = QRetainedItem(self.bottom_region).globalGeometry()
            x0, y0 = float(region.x()), float(region.y())
            width, height = float(region.width()), float(region.height())
            if width <= 1 or height <= 1:
                return None
            workspace = (x0, y0, width, height)
            preferred = self._normalize_plot_dock_area(self._plot_dock_area)
            manager = getattr(self, "plot_dock_manager", None)
            has_tab_group = bool(manager is not None and manager.has_docked())
            plot_rect = None
            if has_tab_group:
                try:
                    plot_geometry = QRetainedItem(self.plot_region).globalGeometry()
                    px, py = float(plot_geometry.x()), float(plot_geometry.y())
                    pw, ph = float(plot_geometry.width()), float(plot_geometry.height())
                    if pw > 1.0 and ph > 1.0:
                        plot_rect = (px, py, pw, ph)
                except Exception:
                    plot_rect = None
            for mx, my in self._dock_pointer_candidates():
                if not self._point_near_rect(
                        (mx, my), workspace, self.DOCK_SNAP_DISTANCE):
                    continue
                if plot_rect is not None:
                    px, py, pw, ph = plot_rect
                    inset_x = min(48.0, max(12.0, pw * 0.18))
                    inset_y = min(40.0, max(10.0, ph * 0.18))
                    if (px + inset_x <= mx <= px + pw - inset_x
                            and py + inset_y <= my <= py + ph - inset_y):
                        return "tabify"
                distances = {
                    "left": abs(mx - x0),
                    "right": abs(mx - (x0 + width)),
                    "top": abs(my - y0),
                    "bottom": abs(my - (y0 + height)),
                }
                order = [preferred] + [
                    area for area in self.PLOT_DOCK_AREAS if area != preferred]
                return min(order, key=lambda area: distances[area])
        except Exception:
            pass
        return None

    def _mouse_over_dock_target(self):
        """Compatibility boolean for older code using the single target API."""
        return self._plot_dock_target_at_pointer() is not None

    def _plot_dock_preview_geometry(self, area):
        """Return viewport coordinates for one prospective Plot target."""
        if str(area or "").strip().lower() == "tabify":
            try:
                plot_geometry = QRetainedItem(self.plot_region).globalGeometry()
                px, py = plot_geometry.x(), plot_geometry.y()
                pw, ph = plot_geometry.width(), plot_geometry.height()
                if pw > 1 and ph > 1:
                    return px, py, pw, ph
            except Exception:
                return None
        area = self._normalize_plot_dock_area(area)
        try:
            region = QRetainedItem(self.bottom_region).globalGeometry()
            x0, y0 = region.x(), region.y()
            width, height = region.width(), region.height()
        except Exception:
            return None
        if width <= 2 or height <= 2:
            return None
        if self._plot_dock_is_vertical_split(area):
            job_width, plot_width = self._plot_split_widths(width, area)
            px = x0 if area == "left" else (x0 + job_width
                    + self.PLOT_DOCK_SEPARATOR_SIZE)
            return px, y0, max(1, plot_width), max(1, height)
        job_height, plot_height = self._plot_split_heights(height, area)
        py = y0 if area == "top" else (y0 + job_height
                + self.PLOT_DOCK_SEPARATOR_SIZE)
        return x0, py, max(1, width), max(1, plot_height)

    def _set_plot_dock_preview(self, visible, area=None):
        """Show/hide viewport-front preview for the prospective Plot dock."""
        if not visible:
            self._hide_dock_drop_preview()
            return
        requested = self._plot_dock_area if area is None else area
        area = ("tabify" if str(requested or "").strip().lower() == "tabify"
                else self._normalize_plot_dock_area(requested))
        geometry = self._plot_dock_preview_geometry(area)
        if geometry is None:
            self._hide_dock_drop_preview()
            return
        self._show_dock_drop_preview(geometry, inset=area != "tabify")

    @staticmethod
    def _left_mouse_pressed():
        try:
            return bool(QCursor.isButtonClicked(Qt.LeftButton))
        except Exception:
            return False

    @staticmethod
    def _left_mouse_double_clicked():
        try:
            return bool(QCursor.isButtonDoubleClicked(Qt.LeftButton))
        except Exception:
            return False

    def _floating_plot_titlebar_hit(self, window, tag):
        """Hit-test only the floating DPG window title strip.

        ``get_item_pos`` is the outer ImGui-window origin.  The embedded dock
        root begins at the client origin, so their Y delta gives the actual
        title/chrome height and naturally follows DPI/font scaling.  A compact
        fallback is used during the first frame before client geometry exists.
        """
        try:
            float_geometry = QRetainedItem(tag).globalGeometry()
            wx, wy = float(QRetainedItem(tag).pos().x()), float(QRetainedItem(tag).pos().y())
            width = float(float_geometry.width())
            title_h = 26.0
            try:
                client_y = float(QRetainedItem(window.root).globalGeometry().y())
                measured = client_y - wy
                if 16.0 <= measured <= 64.0:
                    title_h = measured
            except Exception:
                pass
            pointer = QCursor.pos()
            raw_x, raw_y = float(pointer.x()), float(pointer.y())
            candidates = [(raw_x, raw_y)]
            try:
                local_pointer = QCursor.localPos()
                candidates.append((float(local_pointer.x()), float(local_pointer.y())))
            except Exception:
                pass
            try:
                viewport = QScreen().geometry()
                vx, vy = float(viewport.x()), float(viewport.y())
                candidates.extend(((raw_x - vx, raw_y - vy),
                                   (raw_x + vx, raw_y + vy)))
            except Exception:
                pass
            return any(
                wx <= mx <= wx + max(1.0, width)
                and wy <= my <= wy + title_h
                for mx, my in candidates)
        except Exception:
            return False

    def _update_floating_plot_docking(self):
        """Emulate QDockWidget drag-back docking for detached Plot windows.

        Dear PyGui owns movement of the floating top-level tool window.  WinUx
        watches that position while the left mouse button is held; when a moved
        Plot window is released over Job Viewer, the same live panel is reparented
        into the dock area instead of being recreated.
        """
        if self._native_dock_preview_is_active():
            return
        if not self.job_plot_float_windows:
            self._set_plot_dock_preview(False)
            self._plot_float_mouse_was_down = self._left_mouse_button_down()
            return

        down = self._left_mouse_button_down()
        press_started = self._left_mouse_pressed()
        double_clicked = self._left_mouse_double_clicked()
        escape_pressed = self._escape_key_pressed()
        for key, tag in list(self.job_plot_float_windows.items()):
            window = self.job_plot_windows.get(key)
            if not tag or not QRetainedItem(tag).exists():
                self._plot_float_last_positions.pop(key, None)
                self._plot_float_dragging.discard(key)
                self._plot_synthetic_float_drag.pop(key, None)
                if window is not None:
                    window.end_pointer_capture()
                continue

            if self._floating_plot_is_resizing(key):
                self._plot_float_dragging.discard(key)
                self._set_plot_dock_preview(False)
                try:
                    self._plot_float_last_positions[key] = tuple(map(float, QRetainedItem(tag).pos().toTuple()))
                except Exception:
                    pass
                continue

            synthetic = self._plot_synthetic_float_drag.get(key)
            # Start docking feedback on the title-bar press itself.  Native
            # window managers can delay the DPG item-position update until late
            # in a move gesture, which previously meant no preview was visible
            # while the user was actually dragging.
            if (synthetic is None and press_started and window is not None
                    and self._floating_plot_titlebar_hit(window, tag)):
                self._plot_float_dragging.add(key)
                window.begin_pointer_capture()
            if synthetic is not None:
                if escape_pressed:
                    self._plot_synthetic_float_drag.pop(key, None)
                    self._plot_float_dragging.discard(key)
                    if window is not None:
                        window.end_pointer_capture()
                    self._set_plot_dock_preview(False)
                    self.after(0, self.dock_job_plots, key)
                    continue
                if down:
                    try:
                        pointer = QCursor.pos()
                        mx, my = float(pointer.x()), float(pointer.y())
                        ax, ay = synthetic.get("anchor", (40.0, 10.0))
                        new_pos = (max(0, int(mx - float(ax))),
                                   max(20, int(my - float(ay))))
                        QRetainedItem(tag).move(*new_pos)
                        self._plot_float_last_positions[key] = tuple(
                            map(float, new_pos))
                    except Exception:
                        pass
                    self._plot_float_dragging.add(key)
                    if window is not None:
                        window.begin_pointer_capture()
                    target_area = self._plot_dock_target_at_pointer()
                    self._set_plot_dock_preview(
                        target_area is not None, target_area)
                    continue

                # Physical release completes the synthetic tear-off drag. If it
                # ends over a dock target, dock immediately; otherwise keep the
                # detached window at its current geometry.
                self._plot_synthetic_float_drag.pop(key, None)
                self._plot_float_dragging.discard(key)
                if window is not None:
                    window.end_pointer_capture()
                target_area = self._plot_dock_target_at_pointer()
                self._set_plot_dock_preview(False)
                if target_area is not None:
                    self.after(0, self.dock_job_plots, key, target_area)
                continue

            # Escape cancels an active tear-off/move gesture and restores the
            # previous dock area, matching the reversible feel of native Qt
            # dock dragging instead of committing an accidental float.
            if escape_pressed and key in self._plot_float_dragging:
                if window is not None:
                    window.end_pointer_capture()
                self._plot_float_dragging.discard(key)
                self._plot_synthetic_float_drag.pop(key, None)
                self._set_plot_dock_preview(False)
                self.after(0, self.dock_job_plots, key)
                continue

            # Match QDockWidget: a double-click on the title bar of a floating
            # dock restores it to its previous dock area. no_collapse=True on
            # the floating DPG window prevents ImGui's own title double-click
            # collapse action from competing with this toggle.
            if (double_clicked and window is not None
                    and self._floating_plot_titlebar_hit(window, tag)):
                window.end_pointer_capture()
                self._plot_float_dragging.discard(key)
                self._plot_synthetic_float_drag.pop(key, None)
                self._set_plot_dock_preview(False)
                self.after(0, self.dock_job_plots, key)
                continue

            try:
                point = QRetainedItem(tag).pos()
                pos = (float(point.x()), float(point.y()))
            except Exception:
                continue
            previous = self._plot_float_last_positions.get(key)
            if down and previous is not None:
                if abs(pos[0] - previous[0]) > 0.5 or abs(pos[1] - previous[1]) > 0.5:
                    self._plot_float_dragging.add(key)
                    if window is not None:
                        window.begin_pointer_capture()
                if key in self._plot_float_dragging:
                    target_area = self._plot_dock_target_at_pointer()
                    self._set_plot_dock_preview(
                        target_area is not None, target_area)
            elif (not down and key in self._plot_float_dragging):
                self._plot_float_dragging.discard(key)
                if window is not None:
                    window.end_pointer_capture()
                target_area = self._plot_dock_target_at_pointer()
                self._set_plot_dock_preview(False)
                if target_area is not None:
                    self.after(0, self.dock_job_plots, key, target_area)
            elif not down and window is not None:
                window.end_pointer_capture()
            self._plot_float_last_positions[key] = pos
        if not down and not self._plot_float_dragging:
            self._set_plot_dock_preview(False)
        self._plot_float_mouse_was_down = down

    def _native_dock_preview_is_active(self):
        hosts = list(getattr(self, "_native_plot_hosts", {}).values())
        console = getattr(self, "_native_console_host", None)
        if console is not None:
            hosts.append(console)
        return any(getattr(host, "_native_preview_active", False) for host in hosts)

    def _sync_job_plot_menu_state(self):
        """Keep Job Viewer checkmarks synchronized with every open Plot dock."""
        manager = getattr(self, "plot_dock_manager", None)
        active = getattr(manager, "active_key", None) if manager is not None else None
        self.jobs_view.set_plots_open_jobs(
            self.job_plot_windows.keys(), active_job_id=active)

    def _job_plot_tab_activated(self, job_id):
        """QMainWindow-like tab activation callback from ``DockManager``."""
        if job_id is None:
            self._sync_job_plot_menu_state()
            return
        key = str(job_id)
        if key not in self.job_plot_windows:
            return
        self.jobs_view.set_plots_open_jobs(
            self.job_plot_windows.keys(), active_job_id=key)

    def _job_plot_tab_tearoff(self, job_id, pointer_pos, drag_anchor):
        """Detach one QTabBar-style tab without disturbing sibling docks."""
        key = str(job_id)
        if key not in self.job_plot_windows:
            return False
        return self.undock_job_plots(
            key, pointer_pos=pointer_pos, drag_anchor=drag_anchor)

    def _focus_job_plots(self, job_id):
        key = str(job_id)
        window = self.job_plot_windows.get(key)
        if window is None or not window.exists():
            return
        if getattr(window, "dock_mode", "docked") == "floating":
            host = getattr(self, "_native_plot_hosts", {}).get(key)
            if host is not None and host.winfo_exists():
                host.show()
                return
            tag = self.job_plot_float_windows.get(key)
            if tag and QRetainedItem(tag).exists():
                try:
                    item = QRetainedItem(tag)
                    item.show()
                    item.setFocus()
                    return
                except Exception:
                    pass
        manager = getattr(self, "plot_dock_manager", None)
        if manager is not None:
            manager.raise_dock_widget(key)
            try:
                geometry = QRetainedItem(self.plot_region).globalGeometry()
                width, height = geometry.width(), geometry.height()
                manager.layout(width, height, force=True)
            except Exception:
                pass
        self._sync_job_plot_menu_state()
        window.focus()

    def undock_job_plots(self, job_id, pointer_pos=None, drag_anchor=None):
        """Detach a plot client into its own HWND; retain the ODB model here."""
        from ...dialogs.native_dock_hosts import PlotDockHost
        key = str(job_id)
        panel = self.job_plot_windows.get(key)
        if panel is None or not panel.exists():
            return False
        hosts = getattr(self, "_native_plot_hosts", None)
        if hosts is None:
            hosts = self._native_plot_hosts = {}
        host = hosts.get(key)
        if host is not None and host.winfo_exists():
            host.show()
            return True
        panel.end_pointer_capture()
        manager = getattr(self, "plot_dock_manager", None)
        if manager is not None:
            manager._reset_tab_drag()
        self._set_plot_dock_preview(False)

        pending_hosts = getattr(self, "_native_plot_pending_hosts", None)
        if pending_hosts is None:
            pending_hosts = self._native_plot_pending_hosts = {}

        def closed(closing):
            if hosts.get(key) is not closing:
                return
            hosts.pop(key, None)
            if pending_hosts.get(key) is closing:
                # If native startup dies before first presentation, retain the
                # original docked panel instead of briefly removing the widget.
                pending_hosts.pop(key, None)
                panel.set_dock_mode("docked")
                QRetainedItem(panel.root).show()
                if manager is not None:
                    manager.set_floating(key, False)
                    manager.raise_dock_widget(key)
                self._set_plot_dock_open(True)
                self._sync_job_plot_menu_state()
                self._layout_dirty = True
                self._apply_split_layout(force=True)
                return
            self.close_job_plots(key)

        def dock(requesting):
            if hosts.get(key) is requesting:
                self.dock_job_plots(key, getattr(requesting, "_requested_dock_area", None))

        if drag_anchor is not None:
            from ...platform.native_dock_gesture import release_owner_capture
            release_owner_capture(self)
        host = PlotDockHost(self, panel, dock, closed, drag_anchor=drag_anchor)
        hosts[key] = host
        pending_hosts[key] = host

        def commit_float():
            if (hosts.get(key) is not host or pending_hosts.get(key) is not host
                    or not host.winfo_exists() or not panel.exists()):
                return
            # Preserve the docked frame until the detached HWND is already on
            # screen, then flip manager/model/layout state in one UI turn.
            pending_hosts.pop(key, None)
            panel.set_dock_mode("floating")
            QRetainedItem(panel.root).hide()
            if manager is not None:
                manager.set_floating(key, True)
            self._set_plot_dock_open(manager.has_docked() if manager is not None else False)
            self._sync_job_plot_menu_state()
            self._layout_dirty = True
            self._apply_split_layout(force=True)

        host.after_first_present(commit_float)
        return True

    def dock_job_plots(self, job_id, dock_area=None):
        """Move a floating Plot dock into the shared Qt-like dock/tab group."""
        self._set_plot_dock_preview(False)
        key = str(job_id)
        window = self.job_plot_windows.get(key)
        if window is None or not window.exists():
            return False
        requested_target = (
            dock_area if dock_area is not None
            else getattr(window, "dock_area", self._plot_dock_area))
        tabify_target = str(requested_target or "").strip().lower() == "tabify"
        area = (self._normalize_plot_dock_area(self._plot_dock_area)
                if tabify_target else self._normalize_plot_dock_area(requested_target))
        self._plot_dock_area = area
        self._plot_split_ratio = self._plot_ratio_for_area(area)
        manager = getattr(self, "plot_dock_manager", None)
        pending_hosts = getattr(self, "_native_plot_pending_hosts", {})
        pending_host = pending_hosts.pop(key, None)
        if pending_host is not None:
            hosts = getattr(self, "_native_plot_hosts", {})
            if hosts.get(key) is pending_host:
                hosts.pop(key, None)
            pending_host.destroy()
            window.set_dock_mode("docked")
            QRetainedItem(window.root).show()
            if manager is not None:
                manager.set_floating(key, False)
                manager.raise_dock_widget(key)

        if getattr(window, "dock_mode", "docked") == "docked":
            if manager is not None:
                manager.set_dock_area(key, area, group=True)
                manager.raise_dock_widget(key)
            window.set_dock_area(area)
            self._set_plot_dock_open(True)
            self._sync_job_plot_menu_state()
            self._layout_dirty = True
            self._apply_split_layout(force=True)
            window.focus()
            return True

        tag = self.job_plot_float_windows.get(key)
        host = getattr(self, "_native_plot_hosts", {}).pop(key, None)
        if host is not None:
            host.destroy()
        self._remember_plot_float_geometry(key, tag)
        resizer = self._plot_float_resizers.pop(key, None)
        if resizer is not None:
            resizer.destroy()
        window.end_pointer_capture()
        unregister_pointer_protected_item(tag)
        QRetainedItem(window.root).reparent(self.plot_region)
        QRetainedItem(window.root).configure(width=-1, height=-1, show=True)
        window.set_dock_mode("docked")
        window.set_dock_area(area)
        if manager is not None:
            manager.set_floating(key, False)
            # Job Plots are one tabified dock group. Moving one dock back to a
            # particular side moves the group to that side, like a tabbed
            # QDockWidget group in QMainWindow.
            manager.set_dock_area(key, area, group=True)
            manager.raise_dock_widget(key)
        if tag and QRetainedItem(tag).exists():
            try:
                QRetainedItem(tag).deleteNative()
            except Exception:
                pass
        self.job_plot_float_windows.pop(key, None)
        self._plot_float_last_positions.pop(key, None)
        self._plot_float_dragging.discard(key)
        self._plot_synthetic_float_drag.pop(key, None)
        self._set_plot_dock_open(True)
        self._sync_job_plot_menu_state()
        self._layout_dirty = True
        self._apply_split_layout(force=True)
        window.focus()
        return True

    def _job_plot_dock_area_change(self, job_id, dock_area):
        """Handle the dock title menu's Left/Right/Top/Bottom commands."""
        key = str(job_id)
        window = self.job_plot_windows.get(key)
        if window is None or not window.exists():
            return False
        area = self._normalize_plot_dock_area(dock_area)
        if getattr(window, "dock_mode", "docked") == "floating":
            return self.dock_job_plots(key, area)
        self._end_job_plot_splitter_drag()
        self._plot_dock_area = area
        self._plot_split_ratio = self._plot_ratio_for_area(area)
        manager = getattr(self, "plot_dock_manager", None)
        if manager is not None:
            manager.set_dock_area(key, area, group=True)
            manager.raise_dock_widget(key)
        else:
            window.set_dock_area(area)
        self._set_plot_dock_open(True)
        self._sync_job_plot_menu_state()
        self._layout_dirty = True
        self._apply_split_layout(force=True)
        window.focus()
        return True

    def _job_plot_dock_change(
            self, job_id, mode, pointer_pos=None, drag_anchor=None):
        if str(mode).lower() == "floating":
            return self.undock_job_plots(job_id, pointer_pos, drag_anchor)
        return self.dock_job_plots(job_id)

    def show_job_plots(self, job_id, job_name, on_selection_change, on_close):
        """Show exactly one realtime History Plot for the selected Job.

        Job Plots intentionally use a single-dock model. Opening Plots for a
        different Job closes the previous Plot (and its realtime ODB monitor)
        before creating the new one. DockManager is retained for Qt-like dock
        geometry/float behaviour, but the Plot site never exposes a tab bar.
        """
        key = str(job_id)
        window = self.job_plot_windows.get(key)
        if window is not None and window.exists():
            if getattr(window, "dock_mode", "docked") == "docked":
                self._set_plot_dock_open(True)
                manager = getattr(self, "plot_dock_manager", None)
                if manager is not None:
                    manager.raise_dock_widget(key)
            self._sync_job_plot_menu_state()
            self._focus_job_plots(key)
            return window

        # Single-Job invariant: replace any Plot that belongs to another job.
        # Use the normal notify path so Controller cancels the old realtime ODB
        # watcher as well as removing its dock/floating window state.
        for old_key, old_window in list(self.job_plot_windows.items()):
            if old_key == key:
                continue
            if old_window is not None:
                old_window.close(notify=True)
            else:
                self.job_plot_windows.pop(old_key, None)

        def plot_closed(closed_job_id):
            closed_key = str(closed_job_id)
            self.job_plot_windows.pop(closed_key, None)
            manager = getattr(self, "plot_dock_manager", None)
            if manager is not None:
                manager.remove_dock_widget(closed_key)
            self._remove_job_plot_float_window(closed_key)
            self._set_plot_dock_open(
                manager.has_docked() if manager is not None else False)
            self._sync_job_plot_menu_state()
            self._layout_dirty = True
            self._apply_split_layout(force=True)
            if callable(on_close):
                on_close(closed_job_id)

        self._set_plot_dock_open(True)
        library = PlotDockingMixin._get_reference_chart_library(self)
        window = JobPlotsWindow(
            self.plot_region, key, str(job_name or ""),
            on_selection_change=on_selection_change,
            on_close=plot_closed,
            on_dock_change=self._job_plot_dock_change,
            on_dock_area_change=self._job_plot_dock_area_change,
            dock_area=self._plot_dock_area,
            reference_library=library,
            on_reference_manage=self._show_reference_chart_dialog,
            after=self.after,
        )
        self.job_plot_windows[key] = window
        manager = getattr(self, "plot_dock_manager", None)
        if manager is not None:
            # Only one Plot dock is allowed. With a single registered dock the
            # DockManager automatically hides its QTabBar-style tab strip.
            manager.add_dock_widget(
                key, window, title=str(job_name or "Job"),
                area=self._plot_dock_area, activate=True)
        self._sync_job_plot_menu_state()
        self._layout_dirty = True
        self._apply_split_layout(force=True)
        return window

    def _show_reference_chart_dialog(self):
        from ...dialogs.reference_chart_dialog import ReferenceChartDialog
        dialog = getattr(self, "_reference_chart_dialog", None)
        library = PlotDockingMixin._get_reference_chart_library(self)

        def saved(series):
            if series is None or not self.winfo_exists():
                return
            try:
                library.replace(series)
            except (OSError, ValueError) as exc:
                self.show_error("Reference Chart", "Could not save references: {}".format(exc))

        manager = getattr(self, "plot_dock_manager", None)
        windows = getattr(self, "job_plot_windows", {}) or {}
        active_key = getattr(manager, "active_key", None) if manager is not None else None
        plot_window = windows.get(str(active_key)) if active_key is not None else None
        if plot_window is None and len(windows) == 1:
            plot_window = next(iter(windows.values()))
        history_outputs = []
        if plot_window is not None and plot_window.exists():
            try:
                history_outputs = plot_window.reference_formula_sources()
            except Exception:
                history_outputs = []

        series = (library.editor_snapshot()
                  if hasattr(library, "editor_snapshot") else library.snapshot())
        revision = getattr(library, "revision", None)
        if dialog is not None and dialog.winfo_exists():
            dialog.begin_session(
                series, saved, history_outputs, source_revision=revision)
            dialog.focus()
            return
        self._reference_chart_dialog = ReferenceChartDialog(
            self, series, saved, history_outputs=history_outputs)
        self._reference_chart_dialog._source_revision = revision

    def _show_plot_digitizer_dialog(self):
        """Open the WinUx-native Plot Digitizer from Reference menu."""
        from ...plotdigitizer.integration import open_plot_digitizer
        dialog = getattr(self, "_plot_digitizer_dialog", None)
        if dialog is not None and dialog.winfo_exists():
            dialog.focus()
            return
        library = PlotDockingMixin._get_reference_chart_library(self)
        self._plot_digitizer_dialog = open_plot_digitizer(
            self, reference_library=library)

    def get_job_plots(self, job_id):
        window = self.job_plot_windows.get(str(job_id))
        if window is not None and window.exists():
            return window
        return None

    def close_job_plots(self, job_id):
        key = str(job_id)
        window = self.job_plot_windows.get(key)
        if window is not None:
            # ``plot_closed`` performs dictionary/manager cleanup through the
            # existing notify callback, keeping title-button and context-menu
            # closes on one code path.
            window.close(notify=True)
            return
        manager = getattr(self, "plot_dock_manager", None)
        if manager is not None:
            manager.remove_dock_widget(key)
        self._remove_job_plot_float_window(key)
        self._set_plot_dock_open(
            manager.has_docked() if manager is not None else False)
        self._sync_job_plot_menu_state()
