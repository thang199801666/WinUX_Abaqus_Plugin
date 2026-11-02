from __future__ import annotations

import time

from DearUIQt.core import Qt
from DearUIQt.gui import QCursor, QKeyboard, QScreen
from DearUIQt.widgets import QRetainedItem

from ...components import JobPlotsWindow
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
            from ....services.reference_charts import ReferenceChartLibrary
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
                "pos": (int(x), int(y)),
                "size": (int(width), int(height)),
            }
            self._plot_float_geometries[key] = geometry
            self._plot_saved_float_geometry = dict(geometry)
            return geometry
        except Exception:
            return None

    def _remember_plot_native_host_geometry(self, job_id=None, host=None):
        """Capture the actual detached Plot HWND geometry for persistence.

        Plot tear-offs live in a process-isolated native viewport, so their
        screen rectangle cannot be read from the embedded QRetainedItem.  Keep
        one app-level last floating geometry because Job Plots intentionally use
        a single-dock model; a different job should reopen at the same place.
        """
        key = None if job_id is None else str(job_id or "")
        hosts = getattr(self, "_native_plot_hosts", {}) or {}
        candidates = []
        if host is not None:
            candidates.append((key or "", host))
        elif key is not None:
            candidates.append((key, hosts.get(key)))
        else:
            # Prefer the live floating Plot/placeholder, then any remaining host.
            for candidate_key, candidate_host in hosts.items():
                panel = self._plot_window_for_key(candidate_key)
                if (panel is not None
                        and str(getattr(panel, "dock_mode", "docked")).lower() == "floating"):
                    candidates.append((str(candidate_key), candidate_host))
            for candidate_key, candidate_host in hosts.items():
                pair = (str(candidate_key), candidate_host)
                if pair not in candidates:
                    candidates.append(pair)
        try:
            from ....ui.native.floating_viewport import window_rect
        except Exception:
            return None
        for candidate_key, candidate_host in candidates:
            if candidate_host is None:
                continue
            # A docked Plot keeps a hidden resident native mirror only as a
            # latency cache.  Its centered/off-screen preparation rectangle is
            # not user state and must never overwrite the last real float rect.
            panel = self._plot_window_for_key(candidate_key)
            if (panel is not None
                    and str(getattr(panel, "dock_mode", "docked")).lower() != "floating"
                    and not bool(getattr(candidate_host, "_native_visible", False))):
                continue
            try:
                hwnd = int(getattr(candidate_host, "_hwnd", 0) or 0)
                if not hwnd:
                    continue
                rect = window_rect(hwnd)
                if not rect:
                    continue
                left, top, right, bottom = map(int, rect)
                width, height = right - left, bottom - top
                if width <= 1 or height <= 1:
                    continue
                geometry = {
                    "pos": (left, top),
                    "size": (width, height),
                }
                self._plot_saved_float_geometry = dict(geometry)
                self._plot_float_geometries[str(candidate_key)] = dict(geometry)
                return geometry
            except Exception:
                continue
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
        hosts = getattr(self, "_native_plot_hosts", {})
        host = hosts.get(key)
        if host is not None:
            self._remember_plot_native_host_geometry(key, host)
            hosts.pop(key, None)
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
        windows = list(self.job_plot_windows.values())
        placeholder = getattr(self, "_empty_job_plot_window", None)
        if placeholder is not None:
            windows.append(placeholder)
        for window in windows:
            try:
                if window is not None and window.exists():
                    window.sync_layout()
            except Exception:
                pass

    def _placeholder_plot_closed(self, _job_id=None):
        self._empty_job_plot_window = None
        self._plot_dock_visible = False
        hosts = (getattr(self, "_native_plot_hosts", {}) or {})
        host = hosts.get("")
        (getattr(self, "_native_plot_pending_hosts", {}) or {}).pop("", None)
        if host is not None:
            self._remember_plot_native_host_geometry("", host)
            hosts.pop("", None)
            try:
                host.destroy()
            except Exception:
                pass
        self._set_plot_dock_open(False)
        self._layout_dirty = True
        self._apply_split_layout(force=True)
        self._sync_plots_view_action()
        persist_dock = getattr(self, "_persist_dock_state", None)
        if callable(persist_dock):
            persist_dock()

    def _clear_empty_job_plot_window(self, notify=False):
        window = getattr(self, "_empty_job_plot_window", None)
        self._empty_job_plot_window = None
        hosts = (getattr(self, "_native_plot_hosts", {}) or {})
        host = hosts.get("")
        if host is not None:
            self._remember_plot_native_host_geometry("", host)
            hosts.pop("", None)
        pending = (getattr(self, "_native_plot_pending_hosts", {}) or {}).pop("", None)
        if pending is not None and pending is not host:
            try:
                pending.destroy()
            except Exception:
                pass
        if host is not None:
            try:
                host.destroy()
            except Exception:
                pass
        if window is None:
            return False
        try:
            if window.exists():
                window.close(notify=bool(notify))
        except Exception:
            return False
        return True

    def _ensure_empty_job_plot_window(self):
        window = getattr(self, "_empty_job_plot_window", None)
        if window is not None and window.exists():
            return window
        library = PlotDockingMixin._get_reference_chart_library(self)
        window = JobPlotsWindow(
            self.plot_region, "", "",
            on_selection_change=None,
            on_close=self._placeholder_plot_closed,
            on_dock_change=self._job_plot_dock_change,
            on_dock_area_change=self._job_plot_dock_area_change,
            dock_area=self._plot_dock_area,
            reference_library=library,
            on_reference_manage=self._show_reference_chart_dialog,
            after=self.after,
        )
        window.set_waiting("Waiting for job ODB to appear...")
        self._empty_job_plot_window = window
        # Match SSH Console: prepare a hidden native floating host while the
        # embedded dock is idle so the first undock is a show-only transition.
        self.after(220, self._prepare_plot_native_host, "")
        if str(getattr(self, "_plot_default_mode", "docked")).lower() == "floating":
            self.after(300, self.undock_job_plots, "")
        return window

    def _on_empty_plot_dock_header_drag(
            self, sender=None, app_data=None, user_data=None):
        """Tear the no-job Plot dock off after the normal drag threshold."""
        window = getattr(self, "_empty_job_plot_window", None)
        if window is None or not window.exists():
            return
        window._on_header_drag(sender, app_data, user_data)

    def _on_empty_plot_dock_header_drag_release(
            self, sender=None, app_data=None, user_data=None):
        window = getattr(self, "_empty_job_plot_window", None)
        if window is None:
            return
        window._on_header_drag_release(sender, app_data, user_data)

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

    def _ensure_dock_drop_preview(self):
        """Build the shared front-layer once a dock gesture actually starts."""
        preview = getattr(self, "_dock_drop_preview", None)
        if preview is None:
            try:
                from DearUIQt.widgets import DockDropPreview
                preview = DockDropPreview()
                self._dock_drop_preview = preview
            except Exception:
                return None
        try:
            if not preview.prepare():
                return None
        except Exception:
            return None
        return preview

    def _show_dock_drop_preview(self, geometry, *, inset=True):
        if geometry is None:
            return False
        preview = self._ensure_dock_drop_preview()
        if preview is None:
            return False
        try:
            x, y, width, height = geometry
            return bool(preview.show(x, y, width, height, inset=inset))
        except Exception:
            return False

    def _hide_dock_drop_preview(self):
        self._dock_preview_scope = None
        preview = getattr(self, "_dock_drop_preview", None)
        if preview is not None:
            preview.hide()

    def _dock_guide_geometry(self):
        """Return the stable viewport region used to center docking guides.

        The four-way guide is a gesture target, not the resulting dock
        rectangle.  Keep it centered in the main WinUx content area for the
        entire drag, independent of the current Job/Plot/Console split.
        """
        for item in (getattr(self, "layout_root", None),
                     getattr(self, "_main_window", None)):
            if item is None:
                continue
            try:
                rect = QRetainedItem(item).globalGeometry()
                x, y = float(rect.x()), float(rect.y())
                width, height = float(rect.width()), float(rect.height())
                if width > 16.0 and height > 16.0:
                    return x, y, width, height
            except Exception:
                continue
        return self._dock_site_geometry()

    def _dock_site_geometry(self):
        """Return the currently usable lower workspace in viewport coordinates.

        Read the live Job/Plot pane geometry instead of reconstructing the site
        from the full main window.  This automatically excludes a Console that
        is already docked on any side and keeps the four drop guides aligned
        with the area that will actually receive the floating widget.
        """
        try:
            rects = []
            job = QRetainedItem(self.bottom_region).globalGeometry()
            if float(job.width()) > 1.0 and float(job.height()) > 1.0:
                rects.append((float(job.x()), float(job.y()),
                              float(job.width()), float(job.height())))
            if self._job_plot_dock_visible():
                plot = QRetainedItem(self.plot_region).globalGeometry()
                if float(plot.width()) > 1.0 and float(plot.height()) > 1.0:
                    rects.append((float(plot.x()), float(plot.y()),
                                  float(plot.width()), float(plot.height())))
            if not rects:
                return None
            x0 = min(r[0] for r in rects)
            y0 = min(r[1] for r in rects)
            x1 = max(r[0] + r[2] for r in rects)
            y1 = max(r[1] + r[3] for r in rects)
            return x0, y0, max(1.0, x1 - x0), max(1.0, y1 - y0)
        except Exception:
            return None

    @staticmethod
    def _four_way_area_at(point, bounds):
        """Choose Left/Right/Top/Bottom by the nearest edge of *bounds*."""
        if point is None or bounds is None:
            return None
        mx, my = map(float, point)
        x, y, width, height = map(float, bounds)
        if not (x <= mx <= x + width and y <= my <= y + height):
            return None
        distances = {
            "left": mx - x,
            "right": x + width - mx,
            "top": my - y,
            "bottom": y + height - my,
        }
        return min(("left", "right", "top", "bottom"),
                   key=lambda area: distances[area])

    def _dock_pointer_inside_site(self):
        """Return True while the authoritative pointer is inside the dock site."""
        bounds = self._dock_site_geometry()
        if bounds is None:
            return False
        for point in self._dock_pointer_candidates():
            if self._point_near_rect(point, bounds, 0.0):
                return True
        return False

    def _plot_dock_target_at_pointer(self):
        """Return a target only when the pointer is over one visible guide."""
        self._dock_preview_scope = None
        bounds = self._dock_guide_geometry()
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
        scope = getattr(self, '_dock_preview_scope', None)
        if scope == 'outer':
            bounds = self._dock_guide_geometry()
            if bounds is None:
                return None
            x0, y0, width, height = map(float, bounds)
        else:
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
        """Show guides in-site; show result fill only for the hovered guide."""
        if not visible:
            self._hide_dock_drop_preview()
            return
        bounds = self._dock_guide_geometry()
        active = None
        geometry = None
        if area is not None:
            active = self._normalize_plot_dock_area(area)
            geometry = self._plot_dock_preview_geometry(active)
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
                self._set_plot_dock_preview(True, None)
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
                    self._set_plot_dock_preview(True, target_area)
                    continue

                # Physical release completes the synthetic tear-off drag. If it
                # ends over a dock target, dock immediately; otherwise keep the
                # detached window at its current geometry.
                self._plot_synthetic_float_drag.pop(key, None)
                self._plot_float_dragging.discard(key)
                if window is not None:
                    window.end_pointer_capture()
                target_area = self._plot_dock_target_at_pointer()
                target_scope = getattr(self, "_dock_preview_scope", None)
                self._set_plot_dock_preview(False)
                if target_area is not None:
                    self.after(0, self.dock_job_plots, key, target_area, target_scope)
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
                    self._set_plot_dock_preview(True, target_area)
            elif (not down and key in self._plot_float_dragging):
                self._plot_float_dragging.discard(key)
                if window is not None:
                    window.end_pointer_capture()
                target_area = self._plot_dock_target_at_pointer()
                target_scope = getattr(self, "_dock_preview_scope", None)
                self._set_plot_dock_preview(False)
                if target_area is not None:
                    self.after(0, self.dock_job_plots, key, target_area, target_scope)
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

    def _live_job_plot_windows(self):
        """Return live Plot windows without forcing lazy Job Viewer creation."""
        live = []
        for key, window in list(getattr(self, "job_plot_windows", {}).items()):
            try:
                if window is not None and window.exists():
                    live.append((str(key), window))
            except Exception:
                continue
        return live

    def _plot_window_for_key(self, job_id):
        """Return a real Job Plot or the empty View->Plots placeholder."""
        key = str(job_id or "")
        if key:
            window = getattr(self, "job_plot_windows", {}).get(key)
        else:
            window = getattr(self, "_empty_job_plot_window", None)
        try:
            return window if window is not None and window.exists() else None
        except Exception:
            return None

    def _plot_window_key(self, window):
        """Stable host key for both real and empty Plot docks."""
        if window is getattr(self, "_empty_job_plot_window", None):
            return ""
        return str(getattr(window, "job_id", "") or "")

    def _sync_plots_view_action(self):
        """Synchronize View -> Plots with the persisted requested visibility.

        Unlike Console, Plot docks are created lazily, so there is no permanent
        QDockWidget toggle action to own this state.  ``_plot_dock_visible`` is
        therefore the app-level equivalent of QDockWidget::isVisible(): native
        floating hosts may remain resident while hidden and must *not* make the
        View action look checked merely because their HWND still exists.
        """
        action = getattr(self, "plots_menu_item", None)
        if action is None:
            return False
        visible = bool(getattr(self, "_plot_dock_visible", False))
        try:
            # Programmatic synchronization must not call set_plots_visible()
            # again through QAction::toggled.  This is the same QSignalBlocker
            # pattern used by the Console dock.
            from DearUIQt.core import QSignalBlocker
            with QSignalBlocker(action):
                # View -> Plots is a visibility control, not an availability
                # indicator. It must remain clickable even before the first Job
                # Plot exists so the user can show/hide the Plot workspace.
                action.setEnabled(True)
                action.setChecked(bool(visible))
            return True
        except Exception:
            return False

    def set_plots_visible(self, visible, persist=True):
        """Show/hide Plot presentation while preserving its dock state.

        This mirrors ``set_console_visible``: visibility is persistent state,
        independent from docked/floating mode.  Hiding a Plot does not destroy
        its model, ODB monitor or resident floating host; reopening restores the
        same dock area/mode/geometry.  ``persist=False`` is used only while the
        startup restore transaction is replaying saved state.
        """
        visible = bool(visible)
        self._plot_dock_visible = visible
        live = self._live_job_plot_windows()
        if not live:
            placeholder = (self._ensure_empty_job_plot_window()
                           if visible else getattr(self, "_empty_job_plot_window", None))
            floating = False
            if placeholder is not None and placeholder.exists():
                dock = getattr(placeholder, "dock", None)
                setter = getattr(dock, "set_visible", None)
                if callable(setter):
                    try:
                        setter(visible, notify=False)
                    except TypeError:
                        setter(visible)
                floating = str(getattr(placeholder, "dock_mode", "docked")).lower() == "floating"
                host = (getattr(self, "_native_plot_hosts", {}) or {}).get("")
                if floating and host is not None and host.winfo_exists():
                    host.show() if visible else host.hide()
                if visible:
                    placeholder.set_waiting("Waiting for job ODB to appear...")
            self._set_plot_dock_open(bool(visible and not floating))
            self._layout_dirty = True
            self._apply_split_layout(force=True)
            self._sync_plots_view_action()
            if visible and placeholder is not None:
                if floating:
                    host = (getattr(self, "_native_plot_hosts", {}) or {}).get("")
                    if host is None or not host.winfo_exists():
                        self.undock_job_plots("")
                    else:
                        host.show()
                else:
                    try:
                        placeholder.focus()
                    except Exception:
                        pass
            if persist:
                persist_dock = getattr(self, "_persist_dock_state", None)
                if callable(persist_dock):
                    persist_dock()
            return True

        manager = getattr(self, "plot_dock_manager", None)
        native_hosts = getattr(self, "_native_plot_hosts", {}) or {}
        for key, window in live:
            dock = getattr(window, "dock", None)
            setter = getattr(dock, "set_visible", None)
            if callable(setter):
                try:
                    setter(visible, notify=False)
                except TypeError:
                    setter(visible)

            if str(getattr(window, "dock_mode", "docked")).lower() == "floating":
                host = native_hosts.get(key)
                if host is not None:
                    try:
                        if host.winfo_exists():
                            host.show() if visible else host.hide()
                    except Exception:
                        pass

        # DockManager::has_docked() already excludes requested-hidden docks, so
        # the splitter/layout path naturally gives reclaimed space to Job Viewer.
        docked_visible = bool(manager.has_docked()) if manager is not None else bool(
            visible and any(
                str(getattr(window, "dock_mode", "docked")).lower() == "docked"
                for _key, window in live))
        self._set_plot_dock_open(docked_visible)
        self._layout_dirty = True
        self._apply_split_layout(force=True)
        self._sync_plots_view_action()
        if visible:
            # Keep the current dock/floating host active without recreating Plot
            # data or restarting its realtime source.
            key, window = live[0]
            if str(getattr(window, "dock_mode", "docked")).lower() == "docked":
                if manager is not None:
                    manager.raise_dock_widget(key)
                try:
                    window.focus()
                except Exception:
                    pass
        if persist:
            persist_dock = getattr(self, "_persist_dock_state", None)
            if callable(persist_dock):
                persist_dock()
        return True

    def _sync_job_plot_menu_state(self):
        """Keep Job Viewer checkmarks synchronized with every open Plot dock."""
        jobs_view = getattr(self, "jobs_view", None)
        if jobs_view is None:
            if not self.job_plot_windows:
                return
            jobs_view = self._ensure_jobs_view()
        manager = getattr(self, "plot_dock_manager", None)
        active = getattr(manager, "active_key", None) if manager is not None else None
        jobs_view.set_plots_open_jobs(
            self.job_plot_windows.keys(), active_job_id=active)

    def _job_plot_tab_activated(self, job_id):
        """QMainWindow-like tab activation callback from ``DockManager``."""
        if job_id is None:
            self._sync_job_plot_menu_state()
            return
        key = str(job_id)
        if key not in self.job_plot_windows:
            return
        self._ensure_jobs_view().set_plots_open_jobs(
            self.job_plot_windows.keys(), active_job_id=key)

    def _job_plot_tab_tearoff(self, job_id, pointer_pos, drag_anchor):
        """Detach one QTabBar-style tab without disturbing sibling docks."""
        key = str(job_id)
        if key not in self.job_plot_windows:
            return False
        return self.undock_job_plots(
            key, pointer_pos=pointer_pos, drag_anchor=drag_anchor)

    def _focus_job_plots(self, job_id):
        key = str(job_id or "")
        window = self._plot_window_for_key(key)
        if window is None:
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
        if manager is not None and key:
            manager.raise_dock_widget(key)
            try:
                geometry = QRetainedItem(self.plot_region).globalGeometry()
                width, height = geometry.width(), geometry.height()
                manager.layout(width, height, force=True)
            except Exception:
                pass
        self._sync_job_plot_menu_state()
        window.focus()

    def _create_plot_native_host(self, key, panel, *, drag_anchor=None, visible=True):
        """Create a native Plot renderer without changing the embedded dock.

        Hidden creation is used as a resident mirror. JobPlotsWindow/ImPlot,
        themes and the detached viewport are paid for while the dock is idle,
        leaving the later tear-off gesture with only a show/drag transition.
        """
        from ....dialogs.native_dock_hosts import PlotDockHost
        key = str(key)
        hosts = getattr(self, "_native_plot_hosts", None)
        if hosts is None:
            hosts = self._native_plot_hosts = {}
        pending_hosts = getattr(self, "_native_plot_pending_hosts", None)
        if pending_hosts is None:
            pending_hosts = self._native_plot_pending_hosts = {}

        def closed(closing):
            if hosts.get(key) is not closing:
                return
            self._remember_plot_native_host_geometry(key, closing)
            hosts.pop(key, None)
            if (pending_hosts.get(key) is not closing
                    and getattr(panel, "dock_mode", "docked") == "docked"):
                # Hidden mirrors are disposable latency caches; losing one must
                # never alter the authoritative embedded Plot dock.
                return
            manager = getattr(self, "plot_dock_manager", None)
            if pending_hosts.get(key) is closing:
                pending_hosts.pop(key, None)
                panel.set_dock_mode("docked", sync=False)
                QRetainedItem(panel.root).show()
                if manager is not None and key:
                    manager.set_floating(key, False)
                    manager.raise_dock_widget(key)
                self._set_plot_dock_open(True)
                self._sync_job_plot_menu_state()
                self._layout_dirty = True
                self._apply_split_layout(force=True)
                return
            if key == "":
                self.set_plots_visible(False)
            else:
                self.close_job_plots(key)

        def dock(requesting):
            if hosts.get(key) is requesting:
                self.dock_job_plots(
                    key, getattr(requesting, "_requested_dock_area", None),
                    getattr(requesting, "_requested_dock_scope", None))

        saved_geometry = (
            (getattr(self, "_plot_float_geometries", {}) or {}).get(key)
            or getattr(self, "_plot_saved_float_geometry", {}) or None)
        host = PlotDockHost(
            self, panel, dock, closed, drag_anchor=drag_anchor, visible=visible,
            saved_geometry=saved_geometry)
        hosts[key] = host
        return host

    def _prepare_plot_native_host(self, job_id):
        """Build a hidden detached Plot mirror after its dock has settled."""
        key = str(job_id or "")
        panel = self._plot_window_for_key(key)
        if (panel is None
                or getattr(panel, "dock_mode", "docked") != "docked"):
            return False
        hosts = getattr(self, "_native_plot_hosts", None) or {}
        host = hosts.get(key)
        if host is not None and host.winfo_exists():
            return True
        try:
            self._create_plot_native_host(key, panel, visible=False)
            return True
        except Exception:
            return False

    def _commit_plot_float(self, key, host, panel):
        key = str(key)
        hosts = getattr(self, "_native_plot_hosts", {})
        pending_hosts = getattr(self, "_native_plot_pending_hosts", {})
        if (hosts.get(key) is not host or pending_hosts.get(key) is not host
                or not host.winfo_exists() or not panel.exists()):
            return
        pending_hosts.pop(key, None)
        panel.set_dock_mode("floating", sync=False)
        QRetainedItem(panel.root).hide()
        manager = getattr(self, "plot_dock_manager", None)
        if manager is not None and key:
            manager.set_floating(key, True)
        self._set_plot_dock_open(manager.has_docked() if manager is not None else False)
        self._sync_job_plot_menu_state()
        self._layout_dirty = True
        self._apply_split_layout(force=True)
        self._plot_default_mode = "floating"
        self._plot_dock_visible = True
        persist_dock = getattr(self, "_persist_dock_state", None)
        if callable(persist_dock):
            persist_dock()

    def undock_job_plots(self, job_id, pointer_pos=None, drag_anchor=None):
        """Detach a plot client into its prepared native mirror when possible."""
        key = str(job_id or "")
        panel = self._plot_window_for_key(key)
        if panel is None:
            return False
        hosts = getattr(self, "_native_plot_hosts", None)
        if hosts is None:
            hosts = self._native_plot_hosts = {}
        pending_hosts = getattr(self, "_native_plot_pending_hosts", None)
        if pending_hosts is None:
            pending_hosts = self._native_plot_pending_hosts = {}
        manager = getattr(self, "plot_dock_manager", None)
        host = hosts.get(key)
        if host is not None and host.winfo_exists():
            if drag_anchor is not None:
                from ....platform.native_dock_gesture import release_owner_capture
                release_owner_capture(self)
            pending_hosts[key] = host
            host.after_first_present(self._commit_plot_float, key, host, panel)
            if getattr(host, "_ready", False):
                host.show_immediate(drag_anchor)
            else:
                host.show()
                if drag_anchor is not None:
                    host.post("begin_dock_move", drag_anchor)
            return True

        panel.end_pointer_capture()
        if manager is not None and key:
            manager._reset_tab_drag()
        self._set_plot_dock_preview(False)
        if drag_anchor is not None:
            from ....platform.native_dock_gesture import release_owner_capture
            release_owner_capture(self)
        host = self._create_plot_native_host(
            key, panel, drag_anchor=drag_anchor, visible=True)
        pending_hosts[key] = host
        host.after_first_present(self._commit_plot_float, key, host, panel)
        return True

    def dock_job_plots(self, job_id, dock_area=None, dock_scope=None):
        """Move a floating Plot dock into the shared Qt-like dock/tab group."""
        if dock_scope is not None:
            self._plot_dock_scope = (
                "outer" if str(dock_scope).strip().lower() == "outer" else "inner")
        self._set_plot_dock_preview(False)
        key = str(job_id or "")
        window = self._plot_window_for_key(key)
        if window is None:
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
            window.set_dock_mode("docked", sync=False)
            QRetainedItem(window.root).show()
            if manager is not None and key:
                manager.set_floating(key, False)
                manager.raise_dock_widget(key)

        if getattr(window, "dock_mode", "docked") == "docked":
            if manager is not None and key:
                manager.set_dock_area(key, area, group=True)
                manager.raise_dock_widget(key)
            window.set_dock_area(area)
            self._set_plot_dock_open(True)
            self._sync_job_plot_menu_state()
            self._layout_dirty = True
            self._apply_split_layout(force=True)
            self._plot_default_mode = "docked"
            persist_dock = getattr(self, "_persist_dock_state", None)
            if callable(persist_dock):
                persist_dock()
            window.focus()
            return True

        tag = self.job_plot_float_windows.get(key)
        host = getattr(self, "_native_plot_hosts", {}).get(key)
        if host is not None:
            # Capture the real detached HWND before hiding it.  Resident hosts
            # stay alive across dock cycles, so HWND existence alone cannot be
            # used later to infer the user's last floating position.
            self._remember_plot_native_host_geometry(key, host)
            if host.winfo_exists() and getattr(host, "_ready", False):
                # Preserve the native renderer/HWND across dock cycles.
                host.hide()
            else:
                getattr(self, "_native_plot_hosts", {}).pop(key, None)
                host.destroy()
        self._remember_plot_float_geometry(key, tag)
        resizer = self._plot_float_resizers.pop(key, None)
        if resizer is not None:
            resizer.destroy()
        window.end_pointer_capture()
        unregister_pointer_protected_item(tag)
        QRetainedItem(window.root).reparent(self.plot_region)
        QRetainedItem(window.root).configure(width=-1, height=-1, show=True)
        window.set_dock_mode("docked", sync=False)
        window.set_dock_area(area)
        if manager is not None and key:
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
        self._plot_default_mode = "docked"
        persist_dock = getattr(self, "_persist_dock_state", None)
        if callable(persist_dock):
            persist_dock()
        window.focus()
        return True

    def _job_plot_dock_area_change(self, job_id, dock_area):
        """Handle the dock title menu's Left/Right/Top/Bottom commands."""
        key = str(job_id or "")
        window = self._plot_window_for_key(key)
        if window is None:
            return False
        area = self._normalize_plot_dock_area(dock_area)
        if getattr(window, "dock_mode", "docked") == "floating":
            return self.dock_job_plots(key, area)
        self._end_job_plot_splitter_drag()
        self._plot_dock_area = area
        self._plot_split_ratio = self._plot_ratio_for_area(area)
        manager = getattr(self, "plot_dock_manager", None)
        if manager is not None and key:
            manager.set_dock_area(key, area, group=True)
            manager.raise_dock_widget(key)
        else:
            window.set_dock_area(area)
        self._set_plot_dock_open(True)
        self._sync_job_plot_menu_state()
        self._layout_dirty = True
        self._apply_split_layout(force=True)
        persist_dock = getattr(self, "_persist_dock_state", None)
        if callable(persist_dock):
            persist_dock()
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
        self._ensure_jobs_view()
        self._clear_empty_job_plot_window(notify=False)
        self._ensure_plot_dock_manager()
        # Job Viewer -> Plots is an explicit show operation.  Keep the app-level
        # visibility flag in sync even before the lazy QDockWidget exists.
        self._plot_dock_visible = True
        window = self.job_plot_windows.get(key)
        if window is not None and window.exists():
            # An explicit Job Viewer -> Plots command must reveal a Plot that
            # was previously hidden from View -> Plots.
            self.set_plots_visible(True)
            if getattr(window, "dock_mode", "docked") == "docked":
                self._set_plot_dock_open(True)
                manager = getattr(self, "plot_dock_manager", None)
                if manager is not None:
                    manager.raise_dock_widget(key)
            self._sync_job_plot_menu_state()
            self._sync_plots_view_action()
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
            try:
                keep_panel_visible = bool(getattr(self, "plots_menu_item", None).isChecked())
            except Exception:
                keep_panel_visible = bool(getattr(self, "_plot_dock_open", False))
            closed_key = str(closed_job_id)
            self.job_plot_windows.pop(closed_key, None)
            manager = getattr(self, "plot_dock_manager", None)
            if manager is not None:
                manager.remove_dock_widget(closed_key)
            self._remove_job_plot_float_window(closed_key)
            self._set_plot_dock_open(
                manager.has_docked() if manager is not None else False)
            if not self.job_plot_windows and keep_panel_visible:
                placeholder = self._ensure_empty_job_plot_window()
                try:
                    placeholder.dock.set_visible(True, notify=False)
                except TypeError:
                    placeholder.dock.set_visible(True)
                self._set_plot_dock_open(True)
            self._sync_job_plot_menu_state()
            self._sync_plots_view_action()
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
        self._sync_plots_view_action()
        self._layout_dirty = True
        self._apply_split_layout(force=True)
        # Build the detached ImPlot mirror after the embedded dock has rendered.
        # This moves JobPlotsWindow/native viewport construction out of the
        # user's later title-bar drag, while keeping the authoritative model in
        # the main process. Only one Job Plot is allowed, so this cache is bounded.
        self.after(220, self._prepare_plot_native_host, key)
        if str(getattr(self, "_plot_default_mode", "docked")).lower() == "floating":
            # Preserve the user's last dock mode across launches. Wait until the
            # resident mirror has had a chance to warm so restore is cheap.
            self.after(300, self.undock_job_plots, key)
        else:
            persist_dock = getattr(self, "_persist_dock_state", None)
            if callable(persist_dock):
                persist_dock()
        return window

    def _show_reference_chart_dialog(self):
        from ....dialogs.reference_chart_dialog import ReferenceChartDialog
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
                # Preset generation needs only component/step/region metadata,
                # never a full copy of every live XY sample on dialog opening.
                history_outputs = plot_window.reference_formula_sources(include_points=False)
            except Exception:
                history_outputs = []

        series = (library.editor_snapshot()
                  if hasattr(library, "editor_snapshot") else library.snapshot())
        revision = getattr(library, "revision", None)
        # Keep dialog activation metadata-only. Copy live XY samples only on
        # an explicit Preview refresh, never while constructing the editor.
        def preview_history():
            return (plot_window.reference_formula_sources()
                    if plot_window is not None and plot_window.exists() else [])

        if dialog is not None and dialog.winfo_exists():
            dialog._preview_history_provider = preview_history
            dialog.begin_session(
                series, saved, history_outputs, source_revision=revision)
            dialog.focus()
            return
        self._reference_chart_dialog = ReferenceChartDialog(
            self, series, saved, history_outputs=history_outputs)
        self._reference_chart_dialog._preview_history_provider = preview_history
        self._reference_chart_dialog._source_revision = revision

    def _show_plot_digitizer_dialog(self):
        """Open the WinUx-native Plot Digitizer from Reference menu."""
        from ....plotdigitizer.integration import open_plot_digitizer
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
        self._sync_plots_view_action()
