"""Qt/Windows-like border resizing for floating Dear PyGui tool windows.

Dear ImGui/Dear PyGui draws a visible triangular resize grip in the lower-right
corner of resizable windows.  That is useful for debug/tool UIs but looks unlike
Qt/Windows 11 application windows.  ``FloatingWindowResizer`` lets the host set
``no_resize=True`` (which removes that grip) and restores native-feeling resize
interaction by hit-testing the four borders and four corners itself.

The controller is intentionally independent from the Job Plots implementation
so every future WinUx floating dock can share the same behaviour.
"""

from __future__ import annotations

from typing import Optional, Tuple

import dearpygui.dearpygui as dpg

from .interaction_gate import acquire_pointer_input, release_pointer_input


class FloatingWindowResizer:
    """Resizable-border controller for one top-level DPG window.

    The public ``update`` method is designed to run *before* background splitter
    polling.  A resize gesture takes explicit pointer ownership immediately,
    preventing splitters/list views below the floating tool from reacting to the
    same mouse press.
    """

    # Windows 11 has a generous invisible resize target around a visually thin
    # border.  Keep the corner target larger than the straight edge target so
    # diagonal resizing is easy to acquire.
    EDGE_HIT = 6.0
    CORNER_HIT = 12.0
    OUTER_SLOP = 2.0

    CURSOR_BY_ZONE = {
        "n": "ns",
        "s": "ns",
        "e": "ew",
        "w": "ew",
        "nw": "nwse",
        "se": "nwse",
        "ne": "nesw",
        "sw": "nesw",
    }

    DPG_CURSOR_NAMES = {
        "ns": "mvMouseCursor_ResizeNS",
        "ew": "mvMouseCursor_ResizeEW",
        "nwse": "mvMouseCursor_ResizeNWSE",
        "nesw": "mvMouseCursor_ResizeNESW",
    }

    def __init__(
            self,
            tag,
            min_size: Tuple[int, int] = (320, 200),
            edge_hit: Optional[float] = None,
            corner_hit: Optional[float] = None):
        self.tag = tag
        self.min_width = max(1, int(min_size[0]))
        self.min_height = max(1, int(min_size[1]))
        self.edge_hit = float(edge_hit or self.EDGE_HIT)
        self.corner_hit = float(corner_hit or self.CORNER_HIT)

        self.active_zone = None
        self.hover_zone = None
        self._start_mouse = (0.0, 0.0)
        self._start_rect = (0.0, 0.0, 1.0, 1.0)
        # Do not acquire an already-in-progress tear-off/title gesture on the
        # first frame after a floating window is created.
        self._mouse_was_down = self._left_down()

    @staticmethod
    def _left_down():
        try:
            return bool(dpg.is_mouse_button_down(dpg.mvMouseButton_Left))
        except Exception:
            return False

    @staticmethod
    def _mouse_pos():
        try:
            return tuple(map(float, dpg.get_mouse_pos(local=False)))
        except Exception:
            return None

    def _window_rect(self):
        try:
            x, y = map(float, dpg.get_item_pos(self.tag))
            width, height = map(float, dpg.get_item_rect_size(self.tag))
            if width <= 1.0 or height <= 1.0:
                return None
            return x, y, width, height
        except Exception:
            return None

    @classmethod
    def hit_zone(cls, mouse, rect, edge_hit=None, corner_hit=None):
        """Return ``n/s/e/w/nw/ne/sw/se`` for a pointer near the border.

        This pure helper is intentionally testable without a running DPG
        context.  Corners win over edges, matching native window hit-testing.
        """
        if mouse is None or rect is None:
            return None
        mx, my = map(float, mouse)
        x, y, width, height = map(float, rect)
        if width <= 0.0 or height <= 0.0:
            return None
        edge = float(cls.EDGE_HIT if edge_hit is None else edge_hit)
        corner = float(cls.CORNER_HIT if corner_hit is None else corner_hit)
        x1 = x + width
        y1 = y + height

        slop = float(cls.OUTER_SLOP)
        if not (x - slop <= mx <= x1 + slop and y - slop <= my <= y1 + slop):
            return None

        near_left_corner = mx <= x + corner
        near_right_corner = mx >= x1 - corner
        near_top_corner = my <= y + corner
        near_bottom_corner = my >= y1 - corner

        if near_left_corner and near_top_corner:
            return "nw"
        if near_right_corner and near_top_corner:
            return "ne"
        if near_left_corner and near_bottom_corner:
            return "sw"
        if near_right_corner and near_bottom_corner:
            return "se"

        if my <= y + edge:
            return "n"
        if my >= y1 - edge:
            return "s"
        if mx <= x + edge:
            return "w"
        if mx >= x1 - edge:
            return "e"
        return None

    @property
    def resizing(self):
        return self.active_zone is not None

    @property
    def cursor_kind(self):
        zone = self.active_zone or self.hover_zone
        return self.CURSOR_BY_ZONE.get(zone)

    def _begin(self, zone, mouse, rect):
        if not zone or mouse is None or rect is None:
            return False
        if not acquire_pointer_input(self):
            return False
        self.active_zone = str(zone)
        self.hover_zone = str(zone)
        self._start_mouse = tuple(map(float, mouse))
        self._start_rect = tuple(map(float, rect))
        return True

    def _apply(self, mouse):
        zone = self.active_zone
        if not zone or mouse is None:
            return
        sx, sy = self._start_mouse
        x, y, width, height = self._start_rect
        dx = float(mouse[0]) - sx
        dy = float(mouse[1]) - sy

        left = x
        top = y
        right = x + width
        bottom = y + height

        if "w" in zone:
            left = min(right - self.min_width, x + dx)
        if "e" in zone:
            right = max(left + self.min_width, x + width + dx)
        if "n" in zone:
            top = min(bottom - self.min_height, y + dy)
        if "s" in zone:
            bottom = max(top + self.min_height, y + height + dy)

        new_width = max(self.min_width, int(round(right - left)))
        new_height = max(self.min_height, int(round(bottom - top)))
        try:
            dpg.configure_item(
                self.tag,
                pos=(int(round(left)), int(round(top))),
                width=new_width,
                height=new_height,
            )
        except Exception:
            pass

    def update(self):
        """Poll hover/press state and resize the controlled window.

        Returns ``True`` only while a resize gesture is actively owned.  Merely
        hovering a border changes the cursor but does not suppress unrelated
        application behaviour.
        """
        try:
            if not dpg.does_item_exist(self.tag):
                self.cancel()
                return False
        except Exception:
            self.cancel()
            return False

        down = self._left_down()
        mouse = self._mouse_pos()
        rect = self._window_rect()

        if self.active_zone is not None:
            if down:
                self._apply(mouse)
                self.hover_zone = self.active_zone
                self._mouse_was_down = True
                return True
            self.active_zone = None
            release_pointer_input(self)
            # Preserve hover feedback after release if the pointer is still on
            # the newly resized edge/corner.
            rect = self._window_rect()
            self.hover_zone = self.hit_zone(
                mouse, rect, self.edge_hit, self.corner_hit)
            self._mouse_was_down = False
            return False

        self.hover_zone = self.hit_zone(
            mouse, rect, self.edge_hit, self.corner_hit)
        pressed_now = bool(down and not self._mouse_was_down)
        if pressed_now and self.hover_zone:
            began = self._begin(self.hover_zone, mouse, rect)
            self._mouse_was_down = down
            return bool(began)

        self._mouse_was_down = down
        return False

    def apply_dpg_cursor(self):
        """Apply the diagonal/edge cursor, if the DPG build exposes it."""
        kind = self.cursor_kind
        name = self.DPG_CURSOR_NAMES.get(kind)
        cursor = getattr(dpg, name, None) if name else None
        if cursor is None:
            return False
        try:
            dpg.set_mouse_cursor(cursor)
            return True
        except Exception:
            return False

    def cancel(self):
        self.active_zone = None
        self.hover_zone = None
        release_pointer_input(self)

    destroy = cancel
