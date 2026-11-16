from __future__ import annotations

from DearUIQt.backends import dpg
from DearUIQt.gui.placement import item_screen_rect


class PointerRoutingMixin:
    """Pointer-space routing between Local/Server explorer panes."""
    def panel_and_point_at(self, x_root, y_root):
        """Return the pane and physical desktop point under an internal drag.

        This is intentionally a *live-geometry-only* hit test.  Resize and
        splitter motion can invalidate cached panel sizes within the same
        render turn, so an internal file transfer must never infer a target
        from ``_last_size`` / ``_last_panel_divider``.  If the renderer cannot
        provide a valid pane rectangle for the current frame we reject the
        target for that frame rather than risk dropping into the wrong folder.

        ``x_root``/``y_root`` are USER32 screen pixels.  Every pane rectangle
        below is therefore mapped to screen space before comparison.  No app
        origin, maximum-size, viewport offset, or divider estimate participates
        in drop targeting.
        """
        try:
            x, y = float(x_root), float(y_root)
        except Exception:
            return None, None

        rects = []
        for panel, tag in (
            (self.left, getattr(self, "left_parent", None)),
            (self.right, getattr(self, "right_parent", None)),
        ):
            rect = None
            try:
                rect = panel.screen_rect()
            except Exception:
                rect = None

            # During construction a panel may not yet expose its outer retained
            # container. Map the immediate parent to the same physical screen
            # space; raw get_item_rect_min() is viewport-relative and must never
            # be compared directly with a physical cursor.
            if rect is None and tag and dpg.does_item_exist(tag):
                try:
                    rect = item_screen_rect(dpg, tag)
                except Exception:
                    rect = None

            if rect is None:
                continue
            try:
                x0, y0, x1, y1 = map(float, rect)
            except Exception:
                continue
            if x1 - x0 <= 2.0 or y1 - y0 <= 2.0:
                continue
            rects.append((panel, (x0, y0, x1, y1)))

        # A point can only belong to a pane whose *current physical rectangle*
        # contains it. No desktop/client conversion heuristic and no stale
        # divider guess is allowed here.
        candidates = []
        for panel, (x0, y0, x1, y1) in rects:
            if x0 <= x < x1 and y0 <= y < y1:
                area = (x1 - x0) * (y1 - y0)
                candidates.append((area, panel))
        if candidates:
            # In case retained parents overlap briefly while resizing, the
            # smaller (more specific) pane wins deterministically.
            candidates.sort(key=lambda pair: pair[0])
            return candidates[0][1], (x, y)

        # Any space between live pane rectangles is the splitter/non-drop area.
        # More importantly, a missing/stale geometry frame is rejected instead
        # of being reconstructed from cached widths.  Wrong-file transfer is
        # worse than one transient frame without a drop target.
        return None, None

    def panel_at(self, x_root, y_root):
        """Return the Local/Server pane under a drag point."""
        panel, _point = self.panel_and_point_at(x_root, y_root)
        return panel
