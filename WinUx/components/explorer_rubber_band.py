"""Rubber-band selection engine for the Explorer details view."""

import dearpygui.dearpygui as dpg


class ExplorerRubberBandMixin:
    def _body_local_pos_clamped(self):
        """Return body-canvas coordinates even while dragging outside the viewport."""
        viewport = self._body_viewport_rect()
        if viewport is None:
            return None
        try:
            mx, my = map(float, dpg.get_mouse_pos(local=False))
        except Exception:
            return None
        vx0, vy0, vx1, vy1 = viewport
        cx = min(max(mx, vx0), vx1)
        cy = min(max(my, vy0), vy1)
        try:
            scroll_x = float(dpg.get_x_scroll(self.body_window))
        except Exception:
            scroll_x = 0.0
        try:
            scroll_y = float(dpg.get_y_scroll(self.body_window))
        except Exception:
            scroll_y = 0.0
        return cx - vx0 + scroll_x, cy - vy0 + scroll_y

    def _auto_scroll_during_rubberband(self):
        viewport = self._body_viewport_rect()
        if viewport is None:
            return
        try:
            _, my = map(float, dpg.get_mouse_pos(local=False))
            current = float(dpg.get_y_scroll(self.body_window))
            maximum = float(dpg.get_y_scroll_max(self.body_window))
        except Exception:
            return
        _, vy0, _, vy1 = viewport
        target = current
        if my < vy0 + self.AUTO_SCROLL_MARGIN:
            target = max(0.0, current - self.AUTO_SCROLL_STEP)
        elif my > vy1 - self.AUTO_SCROLL_MARGIN:
            target = min(maximum, current + self.AUTO_SCROLL_STEP)
        if target != current:
            try:
                dpg.set_y_scroll(self.body_window, target)
            except Exception:
                pass

    def _ensure_rubber_rect(self):
        """Create the rubber-band on a front viewport overlay.

        A rectangle parented to ``body_canvas`` is clipped to that drawlist's
        content bounds.  In Details view the visible child window can be much
        taller than the rows, which made a drag beginning below the final row
        appear to start at the canvas edge.  A viewport drawlist uses screen
        coordinates and therefore covers the complete visible list body.
        """
        if self._rubber_rect_tag and dpg.does_item_exist(self._rubber_rect_tag):
            dpg.configure_item(
                self._rubber_rect_tag,
                color=self.theme_config["rubber_border"],
                fill=self.theme_config["rubber_fill"],
            )
            return True

        if not dpg.does_item_exist(self._rubber_layer_tag):
            try:
                dpg.add_viewport_drawlist(
                    front=True, tag=self._rubber_layer_tag)
            except TypeError:
                # Dear PyGui 1.x does not expose the ``front`` keyword.
                dpg.add_viewport_drawlist(tag=self._rubber_layer_tag)
            except Exception:
                return False

        try:
            self._rubber_rect_tag = dpg.draw_rectangle(
                (0, 0), (0, 0), parent=self._rubber_layer_tag,
                color=self.theme_config["rubber_border"],
                fill=self.theme_config["rubber_fill"],
                thickness=1.0, show=False,
            )
        except Exception:
            self._rubber_rect_tag = None
            return False
        return True

    def _hide_rubber_rect(self):
        if self._rubber_rect_tag and dpg.does_item_exist(self._rubber_rect_tag):
            dpg.configure_item(self._rubber_rect_tag, show=False)

    def _rubber_screen_points(self):
        """Return the visible rectangle endpoints in screen coordinates.

        Both endpoints are clamped to the body viewport, matching Explorer's
        mouse capture while preventing the overlay from drawing over adjacent
        panes.  The first endpoint remains the exact mouse-down location even
        when that location is in empty space below all rows.
        """
        viewport = self._body_viewport_rect()
        if viewport is None:
            return None
        vx0, vy0, vx1, vy1 = viewport
        sx, sy = self._rubber_start_screen
        try:
            mx, my = map(float, dpg.get_mouse_pos(local=False))
        except Exception:
            return None

        # Avoid drawing inside the child-window scrollbar strips.
        right = vx1
        bottom = vy1
        try:
            if float(dpg.get_y_scroll_max(self.body_window)) > 0.0:
                right -= float(self.SCROLLBAR_HIT_SIZE)
        except Exception:
            pass
        try:
            if float(dpg.get_x_scroll_max(self.body_window)) > 0.0:
                bottom -= float(self.SCROLLBAR_HIT_SIZE)
        except Exception:
            pass
        right = max(vx0, right)
        bottom = max(vy0, bottom)

        sx = min(max(float(sx), vx0), right)
        sy = min(max(float(sy), vy0), bottom)
        mx = min(max(mx, vx0), right)
        my = min(max(my, vy0), bottom)
        return (sx, sy), (mx, my)

    def _start_rubberband(self):
        self._drag_started = True
        self._rubber_active = True
        self._pending_click_index = None
        self._ensure_rubber_rect()
        if not (self._rubber_ctrl or self._rubber_shift):
            self.selected.clear()
        self._update_selection_draws()

    def _update_rubberband(self):
        self._auto_scroll_during_rubberband()
        current = self._body_local_pos_clamped()
        if current is None:
            return
        self._rubber_current = current
        x0, y0 = self._rubber_start
        x1, y1 = current
        left, right = sorted((x0, x1))
        top, bottom = sorted((y0, y1))
        screen_points = self._rubber_screen_points()
        if screen_points is not None and self._ensure_rubber_rect():
            (screen_x0, screen_y0), (screen_x1, screen_y1) = screen_points
            dpg.configure_item(
                self._rubber_rect_tag,
                pmin=(min(screen_x0, screen_x1), min(screen_y0, screen_y1)),
                pmax=(max(screen_x0, screen_x1), max(screen_y0, screen_y1)),
                show=True,
            )

        total_width = sum(
            float(self._column_widths.get(c["key"], self.MIN_COLUMN_WIDTH))
            for c in self._visible_columns()
        )
        hits = set()
        for index in range(len(self.items)):
            row_top = index * self.ROW_HEIGHT
            row_bottom = row_top + self.ROW_HEIGHT
            intersects = right >= 0.0 and left <= total_width and bottom >= row_top and top <= row_bottom
            if intersects:
                hits.add(index)

        if self.single_selection:
            self.selected = {min(hits)} if hits else set()
        elif self._rubber_ctrl:
            self.selected = self._rubber_base_selection.symmetric_difference(hits)
        elif self._rubber_shift:
            self.selected = self._rubber_base_selection.union(hits)
        else:
            self.selected = hits
        if self.selected:
            self._current_index = min(self.selected)
            if not (self._rubber_ctrl or self._rubber_shift):
                self.last_clicked_index = self._current_index
        self._sync_qt_selection_from_fields()
        self._update_selection_draws()
        self._update_status_bar()
