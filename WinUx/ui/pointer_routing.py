from __future__ import annotations

import dearpygui.dearpygui as dpg


class PointerRoutingMixin:
    """Pointer-space routing between Local/Server explorer panes."""
    def panel_and_point_at(self, x_root, y_root):
        """Return the pane and viewport-space point under a drag position.

        Dear PyGui may expose ``get_mouse_pos(local=False)`` in desktop-screen
        coordinates while item rectangles remain viewport-relative.  Accept
        both coordinate systems and hit-test the stable table-cell containers
        instead of nested ListView children, whose rectangles can be stale
        while the source pane owns mouse capture.

        Returning the matching coordinate variant is important: callers must
        use the same point when resolving a folder row inside the pane.
        """
        try:
            raw_x, raw_y = float(x_root), float(y_root)
        except Exception:
            return None, None

        points = [(raw_x, raw_y)]
        try:
            viewport_pos = dpg.get_viewport_pos()
            vx, vy = float(viewport_pos[0]), float(viewport_pos[1])
            # Desktop-screen mouse point -> viewport-relative item rectangles.
            points.append((raw_x - vx, raw_y - vy))
            # Keep the inverse variant as a defensive fallback for backends
            # that expose screen-relative item rectangles.
            points.append((raw_x + vx, raw_y + vy))
        except Exception:
            pass

        # Deduplicate nearly identical coordinate variants.
        unique_points = []
        for point in points:
            if not any(abs(point[0] - old[0]) < 0.5 and
                       abs(point[1] - old[1]) < 0.5
                       for old in unique_points):
                unique_points.append(point)

        panel_tags = (
            (self.left, getattr(self, "left_parent", None)),
            (self.right, getattr(self, "right_parent", None)),
        )
        rects = []
        for panel, tag in panel_tags:
            rect = None
            if tag and dpg.does_item_exist(tag):
                try:
                    x0, y0 = map(float, dpg.get_item_rect_min(tag))
                    width, height = map(float, dpg.get_item_rect_size(tag))
                    if width > 2 and height > 2:
                        rect = (x0, y0, x0 + width, y0 + height)
                except Exception:
                    rect = None
            if rect is None:
                try:
                    rect = panel.screen_rect()
                except Exception:
                    rect = None
            if rect is not None:
                rects.append((panel, rect))

        for x, y in unique_points:
            candidates = []
            for panel, (x0, y0, x1, y1) in rects:
                if x0 <= x < x1 and y0 <= y < y1:
                    area = max(1.0, (x1 - x0) * (y1 - y0))
                    candidates.append((area, panel))
            if candidates:
                candidates.sort(key=lambda pair: pair[0])
                return candidates[0][1], (x, y)

        # If both pane rectangles are valid, preserve the real gutter between
        # them as a non-panel surface. This prevents drag/drop and row hover
        # from leaking through the QSplitter-style handle.
        for x, y in unique_points:
            if len(rects) < 2:
                continue
            left_rect = next((r for p, r in rects if p is self.left), None)
            right_rect = next((r for p, r in rects if p is self.right), None)
            if left_rect is None or right_rect is None:
                continue
            y0 = min(left_rect[1], right_rect[1])
            y1 = max(left_rect[3], right_rect[3])
            x0 = min(left_rect[0], right_rect[0])
            x1 = max(left_rect[2], right_rect[2])
            if x0 <= x < x1 and y0 <= y < y1:
                gutter_left = left_rect[2]
                gutter_right = right_rect[0]
                if gutter_left <= x < gutter_right:
                    return None, None
                panel = self.left if x < gutter_left else self.right
                return panel, (x, y)

        # Native mouse capture can temporarily make pane rectangles report
        # 0x0. The layout root remains stable, so derive them from the last
        # applied gutter position instead.
        root_rect = None
        root_tag = getattr(self, "layout_root", None)
        if root_tag and dpg.does_item_exist(root_tag):
            try:
                root_x, root_y = map(float, dpg.get_item_rect_min(root_tag))
                root_width, root_height = map(
                    float, dpg.get_item_rect_size(root_tag))
                if root_width > 2 and root_height > 2:
                    root_rect = (
                        root_x, root_y, root_width, root_height)
            except Exception:
                root_rect = None

        if root_rect is None:
            try:
                root_width = float(dpg.get_viewport_client_width())
                root_height = float(dpg.get_viewport_client_height())
            except Exception:
                root_width, root_height = map(
                    float, getattr(self, "_last_content_size",
                                   (self.WIDTH, self.HEIGHT)))
            if root_width > 2 and root_height > 2:
                root_rect = (0.0, 0.0, root_width, root_height)

        if root_rect is not None:
            root_x, root_y, root_width, root_height = root_rect
            panel_height = max(
                1.0,
                float(getattr(self.left, "_last_size", (0, 0))[1] or
                      (root_height * self._top_ratio
                       - self.FILE_STATUS_HEIGHT)),
            )
            divider_offset = float(getattr(
                self, "_last_panel_divider", root_width * 0.5))
            gutter_left = root_x + min(
                max(1.0, divider_offset), max(1.0, root_width - 1.0))
            gutter_right = gutter_left + self.FILE_PANEL_SPLITTER_GUTTER_SIZE
            for x, y in unique_points:
                if (root_x <= x < root_x + root_width and
                        root_y <= y < root_y + panel_height):
                    if gutter_left <= x < gutter_right:
                        return None, None
                    panel = self.left if x < gutter_left else self.right
                    return panel, (x, y)
        return None, None

    def panel_at(self, x_root, y_root):
        """Return the Local/Server pane under a drag point."""
        panel, _point = self.panel_and_point_at(x_root, y_root)
        return panel
