from __future__ import annotations

import time

import dearpygui.dearpygui as dpg

from ..components import FloatingWindowResizer, JobPlotsWindow
from ..components.interaction_gate import (
    register_pointer_protected_item, unregister_pointer_protected_item,
)


class PlotDockingMixin:
    """Job Plots floating/docking behavior separated from WinUXView."""
    def _update_floating_plot_resize_interaction(self):
        """Update custom eight-way resizing for every detached Plot dock."""
        for key, controller in list(self._plot_float_resizers.items()):
            key = str(key)
            tag = self.job_plot_float_windows.get(key)
            if (controller is None or not tag
                    or not dpg.does_item_exist(tag)):
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
                    self._plot_float_last_positions[key] = tuple(
                        map(float, dpg.get_item_pos(tag)))
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
        if not tag or not dpg.does_item_exist(tag):
            return None
        try:
            x, y = map(int, dpg.get_item_pos(tag))
            width, height = map(int, dpg.get_item_rect_size(tag))
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
            return bool(dpg.is_key_pressed(dpg.mvKey_Escape))
        except Exception:
            return False

    def _remove_job_plot_float_window(self, job_id):
        self._set_plot_dock_preview(False)
        key = str(job_id)
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
        if tag and dpg.does_item_exist(tag):
            try:
                dpg.delete_item(tag)
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
        candidates = []
        try:
            raw = tuple(map(float, dpg.get_mouse_pos(local=False)))
            candidates.append(raw)
        except Exception:
            raw = None
        try:
            local = tuple(map(float, dpg.get_mouse_pos(local=True)))
            if local not in candidates:
                candidates.append(local)
        except Exception:
            pass
        if raw is not None:
            try:
                vx, vy = map(float, dpg.get_viewport_pos())
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
            x0, y0 = map(float, dpg.get_item_rect_min(self.bottom_region))
            width, height = map(float, dpg.get_item_rect_size(self.bottom_region))
            if width <= 1 or height <= 1:
                return None
            workspace = (x0, y0, width, height)
            preferred = self._normalize_plot_dock_area(self._plot_dock_area)
            manager = getattr(self, "plot_dock_manager", None)
            has_tab_group = bool(manager is not None and manager.has_docked())
            plot_rect = None
            if has_tab_group:
                try:
                    px, py = map(float, dpg.get_item_rect_min(self.plot_region))
                    pw, ph = map(float, dpg.get_item_rect_size(self.plot_region))
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
                px, py = map(int, dpg.get_item_rect_min(self.plot_region))
                pw, ph = map(int, dpg.get_item_rect_size(self.plot_region))
                if pw > 1 and ph > 1:
                    return px, py, pw, ph
            except Exception:
                return None
        area = self._normalize_plot_dock_area(area)
        try:
            x0, y0 = map(int, dpg.get_item_rect_min(self.bottom_region))
            width, height = map(int, dpg.get_item_rect_size(self.bottom_region))
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
            return bool(dpg.is_mouse_button_clicked(dpg.mvMouseButton_Left))
        except Exception:
            return False

    @staticmethod
    def _left_mouse_double_clicked():
        try:
            return bool(dpg.is_mouse_button_double_clicked(
                dpg.mvMouseButton_Left))
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
            wx, wy = map(float, dpg.get_item_pos(tag))
            width, _ = map(float, dpg.get_item_rect_size(tag))
            title_h = 26.0
            try:
                _, client_y = map(float, dpg.get_item_rect_min(window.root))
                measured = client_y - wy
                if 16.0 <= measured <= 64.0:
                    title_h = measured
            except Exception:
                pass
            raw_x, raw_y = map(float, dpg.get_mouse_pos(local=False))
            candidates = [(raw_x, raw_y)]
            try:
                candidates.append(tuple(map(float, dpg.get_mouse_pos(local=True))))
            except Exception:
                pass
            try:
                vx, vy = map(float, dpg.get_viewport_pos())
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
            if not tag or not dpg.does_item_exist(tag):
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
                    self._plot_float_last_positions[key] = tuple(
                        map(float, dpg.get_item_pos(tag)))
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
                        mx, my = map(float, dpg.get_mouse_pos(local=False))
                        ax, ay = synthetic.get("anchor", (40.0, 10.0))
                        new_pos = (max(0, int(mx - float(ax))),
                                   max(20, int(my - float(ay))))
                        dpg.configure_item(tag, pos=new_pos)
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
                pos = tuple(map(float, dpg.get_item_pos(tag)))
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
            tag = self.job_plot_float_windows.get(key)
            if tag and dpg.does_item_exist(tag):
                try:
                    dpg.configure_item(tag, show=True)
                    dpg.focus_item(tag)
                    return
                except Exception:
                    pass
        manager = getattr(self, "plot_dock_manager", None)
        if manager is not None:
            manager.raise_dock_widget(key)
            try:
                width, height = map(int, dpg.get_item_rect_size(self.plot_region))
                manager.layout(width, height, force=True)
            except Exception:
                pass
        self._sync_job_plot_menu_state()
        window.focus()

    def undock_job_plots(self, job_id, pointer_pos=None, drag_anchor=None):
        """Move one tab/dock into a draggable Dear PyGui tool window.

        If other Job Plot docks remain in the dock site they stay visible as a
        tabified group.  This mirrors QMainWindow: floating one QDockWidget does
        not collapse unrelated dock widgets that shared the same dock area.
        """
        key = str(job_id)
        window = self.job_plot_windows.get(key)
        if window is None or not window.exists():
            return False
        if getattr(window, "dock_mode", "docked") == "floating":
            self._focus_job_plots(key)
            return True

        self._remove_job_plot_float_window(key)
        tag = self._job_plot_float_tag(key)

        def floating_closed(sender=None, app_data=None, user_data=None):
            # Closing the detached tool window is equivalent to unchecking the
            # Plots command. Defer destruction out of DPG's on_close callback.
            self.after(0, self.close_job_plots, key)

        saved_geometry = self._plot_float_geometries.get(key) or {}
        try:
            dock_w, dock_h = map(int, dpg.get_item_rect_size(window.root))
        except Exception:
            dock_w, dock_h = 0, 0

        # A direct drag tear-off should feel physically continuous: preserve
        # the grabbed title point and use the live dock size. A non-drag Float
        # action restores the last floating geometry from this session.
        is_drag_tearoff = bool(
            pointer_pos and len(pointer_pos) >= 2
            and drag_anchor and len(drag_anchor) >= 2)
        if is_drag_tearoff:
            width = max(560, dock_w or 900)
            height = max(280, dock_h or 500)
            anchor_x, anchor_y = 40.0, 10.0
            try:
                anchor_x = max(0.0, min(float(drag_anchor[0]), width - 24.0))
                anchor_y = max(4.0, min(float(drag_anchor[1]), 24.0))
                pos = [
                    max(12, int(float(pointer_pos[0]) - anchor_x)),
                    max(28, int(float(pointer_pos[1]) - anchor_y)),
                ]
            except Exception:
                pos = None
        else:
            saved_size = saved_geometry.get("size") or (
                dock_w or 900, dock_h or 500)
            width = max(560, int(saved_size[0]))
            height = max(280, int(saved_size[1]))
            saved_pos = saved_geometry.get("pos")
            pos = list(saved_pos) if saved_pos else None
            if pos is None and pointer_pos and len(pointer_pos) >= 2:
                try:
                    pos = [max(12, int(pointer_pos[0]) - 180),
                           max(28, int(pointer_pos[1]) - 18)]
                except Exception:
                    pos = None

        kwargs = dict(
            tag=tag, label=window.label, width=width, height=height,
            min_size=(560, 280), no_saved_settings=True, no_collapse=True,
            # Remove Dear ImGui's visible lower-right resize triangle. Custom
            # border hit-testing below provides four-corner/eight-way resize.
            no_resize=True,
            on_close=floating_closed, show=True,
        )
        if pos is not None:
            kwargs["pos"] = pos
        dpg.add_window(**kwargs)
        dpg.bind_item_theme(tag, self._floating_dock_window_theme)
        register_pointer_protected_item(tag)
        self._plot_float_resizers[key] = FloatingWindowResizer(
            tag, min_size=(560, 280))
        dpg.move_item(window.root, parent=tag)
        dpg.configure_item(window.root, width=-1, height=-1, show=True)
        self.job_plot_float_windows[key] = tag
        try:
            self._plot_float_last_positions[key] = tuple(
                map(float, dpg.get_item_pos(tag)))
        except Exception:
            self._plot_float_last_positions.pop(key, None)
        if is_drag_tearoff:
            # Continue the same physical gesture even though its press began on
            # an embedded title/tab rather than this newly created top-level
            # window. Native window dragging cannot inherit that press.
            self._plot_synthetic_float_drag[key] = {
                "anchor": (float(anchor_x), float(anchor_y)),
            }
            self._plot_float_dragging.add(key)
            window.begin_pointer_capture()
        else:
            self._plot_synthetic_float_drag.pop(key, None)
        window.set_dock_area(self._plot_dock_area)
        window.set_dock_mode("floating")
        manager = getattr(self, "plot_dock_manager", None)
        if manager is not None:
            manager.set_floating(key, True)
        self._set_plot_dock_open(
            manager.has_docked() if manager is not None else False)
        self._sync_job_plot_menu_state()
        self._layout_dirty = True
        self._apply_split_layout(force=True)
        try:
            dpg.focus_item(tag)
        except Exception:
            pass
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
        self._remember_plot_float_geometry(key, tag)
        resizer = self._plot_float_resizers.pop(key, None)
        if resizer is not None:
            resizer.destroy()
        window.end_pointer_capture()
        unregister_pointer_protected_item(tag)
        dpg.move_item(window.root, parent=self.plot_region)
        dpg.configure_item(window.root, width=-1, height=-1, show=True)
        window.set_dock_mode("docked")
        window.set_dock_area(area)
        if manager is not None:
            manager.set_floating(key, False)
            # Job Plots are one tabified dock group. Moving one dock back to a
            # particular side moves the group to that side, like a tabbed
            # QDockWidget group in QMainWindow.
            manager.set_dock_area(key, area, group=True)
            manager.raise_dock_widget(key)
        if tag and dpg.does_item_exist(tag):
            try:
                dpg.delete_item(tag)
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
        window = JobPlotsWindow(
            self.plot_region, key, str(job_name or ""),
            on_selection_change=on_selection_change,
            on_close=plot_closed,
            on_dock_change=self._job_plot_dock_change,
            on_dock_area_change=self._job_plot_dock_area_change,
            dock_area=self._plot_dock_area,
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
