"""Reusable scrollbar/scroller styling for Dear PyGui and Tk/ttk.

The module stays backend-neutral at import time. Dear PyGui is passed in by
callers, while Tk/ttk consumers use the same metrics and palette. The DPG skin
adds rounded Qt-like tracks, interactive end buttons and hover expansion over
the native scroll range. Wheel scrolling remains managed by Dear ImGui.
"""
from __future__ import annotations

import time
import os
import ctypes

from ..gui.palette import color_hex


class SharedScrollerMetrics:
    """One geometry contract for all framework scrollbars."""

    # Reserve fixed gutters so hover never shifts the content layout.
    THICKNESS = 10
    COLLAPSED_THICKNESS = 4
    HOVER_DURATION = 0.12
    SCROLL_STEP = 32
    REPEAT_DELAY = 0.35
    REPEAT_INTERVAL = 0.06
    HIT_THICKNESS = 18
    HOVER_MARGIN = 4
    ARROW_SIZE = 7
    ARROW_BUTTON_EXTENT = 11
    ARROW_GLYPH_RADIUS = 2.7
    ROUNDING = 4
    MIN_THUMB = 22


class SharedScrollerPalette:
    """Windows 11 Explorer-like neutral scrollbar palette."""

    TRACK = (250, 250, 250, 255)
    TRACK_BORDER = (234, 234, 234, 255)
    END_CAP = (250, 250, 250, 255)
    END_CAP_HOVER = (246, 246, 246, 255)
    END_CAP_BORDER = (250, 250, 250, 255)
    MASK = (250, 250, 250, 255)
    THUMB = (162, 162, 162, 255)
    THUMB_BORDER = (162, 162, 162, 255)
    THUMB_HOVER = (142, 142, 142, 255)
    THUMB_ACTIVE = (122, 122, 122, 255)
    ARROW = (92, 92, 92, 255)
    ARROW_DISABLED = (176, 176, 176, 255)


def add_dpg_scroller_style(dpg, *, track=None):
    """Add shared Dear PyGui scrollbar colors/metrics to a theme component."""

    p = SharedScrollerPalette
    m = SharedScrollerMetrics
    track = tuple(track or p.TRACK)
    dpg.add_theme_color(dpg.mvThemeCol_ScrollbarBg, track)
    dpg.add_theme_color(dpg.mvThemeCol_ScrollbarGrab, p.THUMB)
    dpg.add_theme_color(dpg.mvThemeCol_ScrollbarGrabHovered, p.THUMB_HOVER)
    dpg.add_theme_color(dpg.mvThemeCol_ScrollbarGrabActive, p.THUMB_ACTIVE)
    dpg.add_theme_style(dpg.mvStyleVar_ScrollbarSize, m.THICKNESS)
    dpg.add_theme_style(dpg.mvStyleVar_ScrollbarRounding, m.ROUNDING)


DEFAULT_TTK_STYLE_PREFIX = "DearUIQt"


def ttk_scroller_style_name(orient, *, style_prefix=DEFAULT_TTK_STYLE_PREFIX):
    value = str(orient or "vertical").lower()
    prefix = str(style_prefix or "UiFramework").strip() or "UiFramework"
    axis = "Horizontal" if value.startswith("h") else "Vertical"
    return f"{prefix}.{axis}.TScrollbar"


def configure_ttk_scroller_styles(style, *, style_prefix=DEFAULT_TTK_STYLE_PREFIX):
    """Install the shared scrollbar styles into an existing ``ttk.Style``.

    ttk uses the platform's native scrollbar layout, so Windows arrow buttons
    remain available while the host supplies a consistent neutral-gray palette.
    """

    p = SharedScrollerPalette
    m = SharedScrollerMetrics
    track = color_hex(p.TRACK)
    border = color_hex(p.TRACK_BORDER)
    thumb = color_hex(p.THUMB)
    hover = color_hex(p.THUMB_HOVER)
    active = color_hex(p.THUMB_ACTIVE)
    arrow = color_hex(p.ARROW)
    disabled = color_hex(p.ARROW_DISABLED)

    for name in (
        ttk_scroller_style_name("vertical", style_prefix=style_prefix),
        ttk_scroller_style_name("horizontal", style_prefix=style_prefix),
    ):
        try:
            style.configure(
                name,
                background=thumb,
                troughcolor=track,
                bordercolor=border,
                lightcolor=color_hex((252, 252, 252, 255)),
                darkcolor=border,
                arrowcolor=arrow,
                relief="flat",
                borderwidth=1,
                width=m.THICKNESS,
                arrowsize=m.ARROW_SIZE,
            )
            style.map(
                name,
                background=[("pressed", active), ("active", hover), ("!disabled", thumb)],
                arrowcolor=[("disabled", disabled), ("!disabled", arrow)],
            )
        except Exception:
            pass
    return style


def make_ttk_scroller(
    ttk_module, parent, *, orient="vertical", command=None,
    style_prefix=DEFAULT_TTK_STYLE_PREFIX, **kwargs
):
    """Create a ttk scrollbar using the shared framework style contract."""

    kwargs.setdefault(
        "style", ttk_scroller_style_name(orient, style_prefix=style_prefix))
    kwargs["orient"] = orient
    if command is not None:
        kwargs["command"] = command
    return ttk_module.Scrollbar(parent, **kwargs)


def dpg_window_rect(dpg, item, *, clip=False):
    """Reconstruct window bounds without content padding or scroll offsets.

    DPG 2.x window states omit rect_min. Their pos is relative to the nearest
    parent window, whereas a drawlist's rect_min starts inside window padding.
    """
    try:
        info = dpg.get_item_info(item)
        window_types = ("mvChildWindow", "mvWindowAppItem", "mvWindowApp")
        if info["type"].split("::")[-1] not in window_types:
            return None
        state = dpg.get_item_state(item)
        x, y = map(float, state["pos"])
        width, height = map(float, state["rect_size"])
        parent = dpg.get_item_parent(item)
        while parent:
            parent_info = dpg.get_item_info(parent)
            kind = parent_info["type"].split("::")[-1]
            if kind in window_types:
                px, py = map(float, dpg.get_item_state(parent)["pos"])
                x += px
                y += py
            parent = dpg.get_item_parent(parent)
        if width > 0.0 and height > 0.0:
            rect = (x, y, x+width, y+height)
            if clip:
                parent = dpg.get_item_parent(item)
                while parent:
                    bounds = dpg_window_rect(dpg, parent)
                    if bounds is not None:
                        rect = (max(rect[0], bounds[0]), max(rect[1], bounds[1]),
                                min(rect[2], bounds[2]), min(rect[3], bounds[3]))
                    parent = dpg.get_item_parent(parent)
                if rect[2] <= rect[0] or rect[3] <= rect[1]:
                    return None
            return rect
    except (KeyError, TypeError, ValueError, RuntimeError, AttributeError):
        pass
    return None


class DpgScrollerArrowOverlay:
    """Animated scrollbar skin using the native DPG scroll range and wheel.

    Pointer gestures use the drawn geometry rather than the different
    underlying ImGui thumb geometry. The visual language is intentionally
    close to the Windows 11 File Explorer scrollbar: light track, subtle
    chrome, and a slim neutral thumb that expands only on hover.
    """

    def __init__(self, dpg, target_item, tag, *, vertical=True, horizontal=False,
                  rect_provider=None, content_item=None, content_size_provider=None,
                  interaction_gate=None):
        self.dpg = dpg
        self.target_item = target_item
        self.tag = str(tag)
        self.vertical = bool(vertical)
        self.horizontal = bool(horizontal)
        # Child-window rect_min is not populated reliably by Dear PyGui 2.x.
        # Owners that already know their visible viewport can supply a stable
        # screen-space rectangle here.
        self.rect_provider = rect_provider
        self.content_item = content_item
        self.content_size_provider = content_size_provider
        self._content_extent = None
        self.layer = self.tag + "_layer"
        self.anchor = self.tag + "_anchor"
        self.container = self.tag + "_container"
        self.theme = self.tag + "_theme"
        self._origin = (0.0, 0.0)
        self._original_config = None
        self._rects = {}
        self._arrows = {}
        self._parts = {}
        self._expansion = {"v": 0.0, "h": 0.0}
        self._last_time = time.monotonic()
        self._gesture = None
        self._mouse_down = False
        self._last_scroll = {}
        self._last_axes = {}
        self._hits = {}
        self._hit_theme = self.tag + "_hit_theme"
        self._interaction_gate = interaction_gate
        self._pointer_owner = object()
        self._captured = False
        self._active_hits = set()
        self._destroyed = False
        self._ensure_items()

    def _gate(self):
        if self._interaction_gate is None:
            # Keep the Tk/scroller metrics import backend-light. DPG input
            # ownership is needed only when constructing interactive chrome.
            from .. import input_gate
            self._interaction_gate = input_gate
        return self._interaction_gate

    def _ensure_hit_items(self):
        """Real ImGui hit surfaces, separate from the decorative drawlist."""
        dpg = self.dpg
        if not dpg.does_item_exist(self._hit_theme):
            dpg.add_theme(tag=self._hit_theme)
            component = dpg.add_theme_component(dpg.mvButton, parent=self._hit_theme)
            for color in (dpg.mvThemeCol_Button, dpg.mvThemeCol_ButtonHovered, dpg.mvThemeCol_ButtonActive):
                dpg.add_theme_color(color, (0, 0, 0, 0), parent=component)
            dpg.add_theme_style(dpg.mvStyleVar_FramePadding, 0, 0, parent=component)
            dpg.add_theme_style(dpg.mvStyleVar_FrameBorderSize, 0, parent=component)
        for axis, enabled in (("v", self.vertical), ("h", self.horizontal)):
            if not enabled:
                continue
            tag = self.tag + "_" + axis + "_hit"
            if not dpg.does_item_exist(tag):
                dpg.add_button(tag=tag, label="", parent=self.container, pos=(0, 0),
                               width=1, height=1, show=False, callback=lambda: None)
                dpg.bind_item_theme(tag, self._hit_theme)
            self._hits[axis] = tag
            # Submit the real hit widget before the drawing canvas. DPG's
            # drawlist can take an ImGui ActiveId; it cannot be disabled on all
            # supported builds even though its config reports 'enabled'.
            dpg.move_item(tag, parent=self.container, before=self.anchor)
            self._gate().register_pointer_protected_item(tag)

    def _end_gesture(self):
        self._gesture = None
        if self._captured:
            self._gate().release_pointer_input(self._pointer_owner)
            self._captured = False

    def _left_button_down(self):
        if os.name == "nt" and getattr(self.dpg, "__name__", "") == "dearpygui.dearpygui":
            # Mouse-up can be delivered outside GLFW. Do not retain capture
            # indefinitely from a cached DPG press (or another held button).
            user32 = ctypes.windll.user32
            user32.GetAsyncKeyState.argtypes = [ctypes.c_int]
            user32.GetAsyncKeyState.restype = ctypes.c_short
            return bool(int(user32.GetAsyncKeyState(1)) & 0x8000)
        return bool(self.dpg.is_mouse_button_down(self.dpg.mvMouseButton_Left))

    def _fit_hit_items(self, axes):
        for axis, tag in self._hits.items():
            data = axes.get(axis)
            if data is None:
                self.dpg.configure_item(tag, show=False)
                continue
            x0, y0, x1, y1 = data["hit"]
            ox, oy = self._origin
            self.dpg.configure_item(tag, pos=(x0-ox, y0-oy),
                                    width=max(1, round(x1-x0)), height=max(1, round(y1-y0)), show=True)

    def _ensure_items(self):
        dpg = self.dpg
        try:
            if not dpg.does_item_exist(self.container):
                config = dpg.get_item_configuration(self.target_item)
                self._original_config = {key: config.get(key, default) for key, default in
                                         (("width", -1), ("height", -1), ("no_scrollbar", False),
                                          ("horizontal_scrollbar", False))}
                parent = dpg.get_item_parent(self.target_item)
                dpg.add_child_window(
                    parent=parent, before=self.target_item, tag=self.container,
                    width=config.get("width", -1), height=config.get("height", -1),
                    border=False, no_scrollbar=True, no_scroll_with_mouse=True)
                dpg.add_theme(tag=self.theme)
                component = dpg.add_theme_component(dpg.mvAll, parent=self.theme)
                dpg.add_theme_style(dpg.mvStyleVar_WindowPadding, 0, 0, parent=component)
                dpg.add_theme_style(dpg.mvStyleVar_ItemSpacing, 0, 0, parent=component)
                dpg.add_theme_style(dpg.mvStyleVar_ChildBorderSize, 0, parent=component)
                dpg.add_theme_color(dpg.mvThemeCol_ChildBg, (0, 0, 0, 0), parent=component)
                dpg.bind_item_theme(self.container, self.theme)
                dpg.move_item(self.target_item, parent=self.container)
                # Reserve fixed gutters outside the native scrolling child.
                # No viewport-front drawing, popup scans or hide/show fallback.
                self._fit_content()
            if not dpg.does_item_exist(self.layer):
                # DPG drawlists do not apply their own 'pos' to the ImGui
                # cursor. A positioned group anchors the canvas at (0, 0).
                dpg.add_group(parent=self.container, pos=(0, 0), tag=self.anchor)
                dpg.add_drawlist(1, 1, parent=self.anchor, tag=self.layer)
            for key in ("v_mask", "h_mask", "v_track", "v_thumb", "h_track", "h_thumb", "corner"):
                tag = self.tag + "_" + key
                if not dpg.does_item_exist(tag):
                    if key.endswith("thumb"):
                        color = SharedScrollerPalette.THUMB_BORDER
                        fill = SharedScrollerPalette.THUMB
                        rounding = float(SharedScrollerMetrics.ROUNDING)
                    elif key.endswith("mask"):
                        color = SharedScrollerPalette.MASK
                        fill = SharedScrollerPalette.MASK
                        rounding = 0.0
                    elif key == "corner":
                        color = SharedScrollerPalette.TRACK_BORDER
                        fill = SharedScrollerPalette.END_CAP
                        rounding = 0.0
                    else:
                        color = SharedScrollerPalette.TRACK_BORDER
                        fill = SharedScrollerPalette.TRACK
                        rounding = float(SharedScrollerMetrics.ROUNDING)
                    self._parts[key] = dpg.draw_rectangle(
                        (0, 0), (0, 0), parent=self.layer, color=color, fill=fill,
                        thickness=1.0, rounding=rounding, show=False, tag=tag)
                else:
                    self._parts[key] = tag
            # End buttons must be drawn after masks/tracks, otherwise the
            # opaque native-chrome mask covers their arrow glyphs.
            for key in ("up", "down", "left", "right"):
                rect_tag = self.tag + "_" + key + "_cap"
                arrow_tag = self.tag + "_" + key + "_arrow"
                if not dpg.does_item_exist(rect_tag):
                    self._rects[key] = dpg.draw_rectangle(
                        (0, 0), (0, 0), parent=self.layer,
                        color=SharedScrollerPalette.END_CAP_BORDER,
                        fill=SharedScrollerPalette.END_CAP, thickness=1.0,
                        show=False, tag=rect_tag)
                else:
                    self._rects[key] = rect_tag
                if not dpg.does_item_exist(arrow_tag):
                    self._arrows[key] = dpg.draw_triangle(
                        (0, 0), (0, 0), (0, 0), parent=self.layer,
                        color=SharedScrollerPalette.ARROW,
                        fill=SharedScrollerPalette.ARROW,
                        show=False, tag=arrow_tag)
                else:
                    self._arrows[key] = arrow_tag
            # Put real input surfaces ahead of the decorative drawlist.
            # A parent child-window is not necessarily hovered over its draw
            # children; relying on parent hover made the drawn thumb inert.
            self._ensure_hit_items()
        except Exception:
            self._rects.clear()
            self._arrows.clear()
            self._parts.clear()

    def _fit_content(self):
        """Keep resize calls from extending the content into scroller gutters."""
        expected = dict(
            no_scrollbar=True, horizontal_scrollbar=self.horizontal,
            width=-SharedScrollerMetrics.THICKNESS if self.vertical else -1,
            height=-SharedScrollerMetrics.THICKNESS if self.horizontal else -1)
        config = self.dpg.get_item_configuration(self.target_item)
        if any(config.get(key) != value for key, value in expected.items()):
            self.dpg.configure_item(self.target_item, **expected)
        self._content_extent = None
        if self.content_item is not None and callable(self.content_size_provider):
            size = self.content_size_provider()
            if size is not None and self.dpg.does_item_exist(self.content_item):
                width, height = (max(1, int(round(float(value)))) for value in size)
                self._content_extent = (width, height)
                content_config = self.dpg.get_item_configuration(self.content_item)
                if content_config.get("width") != width or content_config.get("height") != height:
                    self.dpg.configure_item(self.content_item, width=width, height=height)

    @staticmethod
    def _snap_rect(rect, origin=(0.0, 0.0)):
        """Convert a screen-space rectangle to crisp local integer pixel bounds."""
        x0, y0, x1, y1 = rect
        ox, oy = origin
        return (
            int(round(x0 - ox)),
            int(round(y0 - oy)),
            int(round(x1 - ox)),
            int(round(y1 - oy)),
        )

    @staticmethod
    def _resolve_lane(outer_start, outer_end, content_end, fallback_thickness):
        """Return the real reserved scrollbar lane, not just a fixed-width guess.

        Dear ImGui/DPG can leave extra layout spacing between the scrolling child
        and its parent edge. Centering against ``THICKNESS`` alone therefore
        makes the collapsed thumb look pinned toward the outside edge. When the
        child geometry is available, use that actual gap as the lane.
        """
        outer_start = float(outer_start)
        outer_end = float(outer_end)
        fallback = max(1.0, float(fallback_thickness))
        lane_start = outer_end - fallback
        if content_end is not None:
            try:
                content_end = float(content_end)
                gap = outer_end - content_end
                # Ignore obviously invalid/stale geometry but accept modest
                # renderer spacing around the nominal 10 px scrollbar gutter.
                if 1.0 <= gap <= max(32.0, fallback * 3.0):
                    lane_start = max(outer_start, content_end)
            except (TypeError, ValueError):
                pass
        lane_start = min(max(outer_start, lane_start), outer_end)
        return lane_start, outer_end

    @staticmethod
    def _centered_span(lane_start, lane_end, thickness):
        """Center ``thickness`` symmetrically inside the supplied lane."""
        lane_start = float(lane_start)
        lane_end = float(lane_end)
        lane_width = max(0.0, lane_end - lane_start)
        width = min(lane_width, max(0.0, float(thickness)))
        center = (lane_start + lane_end) * 0.5
        return center - width * 0.5, center + width * 0.5


    def _set_cap(self, key, rect, points, show=True, *, hovered=False, rounding=None):
        dpg = self.dpg
        rect_tag = self._rects.get(key)
        arrow_tag = self._arrows.get(key)
        if not rect_tag or not arrow_tag:
            return
        try:
            x0, y0, x1, y1 = rect
            ox, oy = self._origin
            p = SharedScrollerPalette
            sx0, sy0, sx1, sy1 = self._snap_rect((x0, y0, x1, y1), (ox, oy))
            kwargs = dict(
                pmin=(sx0, sy0), pmax=(sx1, sy1), show=show,
                fill=p.END_CAP_HOVER if hovered else p.END_CAP,
                color=p.END_CAP_BORDER)
            if rounding is not None:
                kwargs["rounding"] = float(rounding)
            dpg.configure_item(rect_tag, **kwargs)
            snapped = {}
            for name, point in zip(("p1", "p2", "p3"), points):
                snapped[name] = (int(round(point[0]-ox)), int(round(point[1]-oy)))
            dpg.configure_item(
                arrow_tag, **snapped,
                color=p.ARROW, fill=p.ARROW, show=show)
        except Exception:
            pass

    def _set_part(self, key, rect, show=True, *, fill=None, color=None, rounding=None):
        tag = self._parts.get(key)
        if not tag:
            return
        try:
            x0, y0, x1, y1 = rect
            ox, oy = self._origin
            sx0, sy0, sx1, sy1 = self._snap_rect((x0, y0, x1, y1), (ox, oy))
            kwargs = dict(pmin=(sx0, sy0), pmax=(sx1, sy1), show=show)
            if fill is not None:
                kwargs["fill"] = fill
            if color is not None:
                kwargs["color"] = color
            if rounding is not None:
                kwargs["rounding"] = float(rounding)
            self.dpg.configure_item(tag, **kwargs)
        except Exception:
            pass

    def hide(self):
        self._end_gesture()
        self._expansion = {"v": 0.0, "h": 0.0}
        self._last_scroll.clear()
        self._last_axes.clear()
        dpg = self.dpg
        for tag in list(self._parts.values()) + list(self._rects.values()) + list(self._arrows.values()) + list(self._hits.values()):
            try:
                if tag and dpg.does_item_exist(tag):
                    dpg.configure_item(tag, show=False)
            except Exception:
                pass

    @staticmethod
    def _triangle(cx, cy, direction, radius):
        # Snap the solid triangle to integer pixel coordinates so the tiny
        # Explorer-like arrows render crisp instead of landing on sub-pixels.
        r = max(2.0, float(radius))
        cx = int(round(cx))
        cy = int(round(cy))
        half_base = max(2, int(round(r * 0.95)))
        half_height = max(2, int(round(r * 0.82)))
        if direction == "up":
            return (
                (cx, cy-half_height),
                (cx-half_base, cy+half_height),
                (cx+half_base, cy+half_height),
            )
        if direction == "down":
            return (
                (cx, cy+half_height),
                (cx-half_base, cy-half_height),
                (cx+half_base, cy-half_height),
            )
        if direction == "left":
            return (
                (cx-half_height, cy),
                (cx+half_height, cy-half_base),
                (cx+half_height, cy+half_base),
            )
        return (
            (cx+half_height, cy),
            (cx-half_height, cy-half_base),
            (cx-half_height, cy+half_base),
        )

    def _target_rect(self):
        dpg = self.dpg
        rect = dpg_window_rect(dpg, self.container, clip=True)
        if rect is not None:
            return rect
        provider = self.rect_provider
        if callable(provider):
            try:
                rect = provider()
                if rect is not None and len(rect) >= 4:
                    x0, y0, x1, y1 = map(float, rect[:4])
                    if x1 > x0 and y1 > y0:
                        return x0, y0, x1, y1
            except Exception:
                pass

        rect = dpg_window_rect(dpg, self.target_item, clip=True)
        if rect is not None:
            return rect
        if dpg_window_rect(dpg, self.target_item) is not None:
            return None

        # Fast path used by drawing items and DPG builds that expose child
        # window screen rectangles normally.
        try:
            x0, y0 = map(float, dpg.get_item_rect_min(self.target_item))
            width, height = map(float, dpg.get_item_rect_size(self.target_item))
            if width > 0.0 and height > 0.0:
                return x0, y0, x0 + width, y0 + height
        except Exception:
            pass

        # Dear PyGui 2.x compatibility: child windows can have a valid
        # rect_size but no rect_min. Reconstruct the visible viewport from a
        # drawing child, whose rect_min remains reliable, plus the scroll
        # offset. This mirrors ExplorerListView._body_viewport_rect().
        try:
            children = dpg.get_item_children(self.target_item, 1) or []
        except Exception:
            children = []
        for child in children:
            try:
                cx, cy = map(float, dpg.get_item_rect_min(child))
                width, height = map(float, dpg.get_item_rect_size(self.target_item))
                sx = float(dpg.get_x_scroll(self.target_item))
                sy = float(dpg.get_y_scroll(self.target_item))
                if width > 0.0 and height > 0.0:
                    x0, y0 = cx + sx, cy + sy
                    return x0, y0, x0 + width, y0 + height
            except Exception:
                continue
        return None

    @staticmethod
    def _inside(point, rect, margin=0.0):
        if point is None or rect is None:
            return False
        x, y = point
        x0, y0, x1, y1 = rect
        m = float(margin)
        return (x0 - m) <= x <= (x1 + m) and (y0 - m) <= y <= (y1 + m)

    def _pointer(self):
        try:
            return tuple(map(float, self.dpg.get_mouse_pos(local=False)))
        except Exception:
            return None

    def _target_is_shown(self):
        """Child windows expose 'show', but not necessarily 'visible' state."""
        item = self.target_item
        while item:
            if not self.dpg.is_item_shown(item):
                return False
            if self.dpg.get_item_state(item).get("visible") is False:
                return False
            item = self.dpg.get_item_parent(item)
        return True

    def _foreground_input_blocked(self):
        """Return True when foreground UI must suppress scroller hover/input.

        The scrollbar chrome is custom-drawn and therefore cannot rely on
        Dear ImGui hover state alone: ``get_mouse_pos()`` still reports the
        desktop pointer even when a QDialog/native window is on top.  Mirror
        Qt's z-order semantics explicitly so background scrollbars neither
        highlight nor start a gesture through a dialog or popup.
        """
        dpg = self.dpg

        # A modal QDialog disables every background control, even if this
        # scroller happened to own a mouse grab before the dialog appeared.
        # Use the logical modal registry but query visibility through this
        # scroller's backend so tests/alternate DPG facades remain isolated.
        try:
            from ..modal import MODAL_TAGS
            for tag in tuple(MODAL_TAGS):
                try:
                    if dpg.does_item_exist(tag) and dpg.is_item_shown(tag):
                        return True
                except Exception:
                    continue
        except Exception:
            pass

        gate = self._gate()

        # Native top-level dialogs live outside the DPG item tree.  The input
        # gate performs real Win32 hit testing and also preserves the closing
        # gesture through release.
        native_blocked = getattr(gate, "native_background_input_blocked", None)
        if callable(native_blocked):
            try:
                if native_blocked():
                    return True
            except Exception:
                pass
        else:
            # Compatibility with older/small interaction-gate implementations.
            native_modal = getattr(gate, "native_modal_input_active", None)
            try:
                if callable(native_modal) and native_modal():
                    return True
            except Exception:
                pass

        # QMenu/QPopup has application-level pointer ownership while visible.
        popup_active = getattr(gate, "popup_input_active", None)
        try:
            if callable(popup_active) and popup_active():
                return True
        except Exception:
            pass

        # Modeless QDialogs/panels block only the pixels they actually cover.
        # Exclude this scroller's own transparent hit buttons; they are
        # registered precisely to protect content below the scrollbar and must
        # not make the scrollbar block itself.
        foreground_at_pointer = getattr(gate, "protected_surface_under_pointer", None)
        if callable(foreground_at_pointer):
            try:
                hit = foreground_at_pointer(exclude_items=tuple(self._hits.values()))
            except TypeError:
                hit = None
            except Exception:
                hit = None
            if hit is not None:
                return True
        return False

    def _interact(self, axes, pointer, now, *, blocked=False):
        """Handle end-button repeat, page clicks and captured thumb dragging."""
        dpg = self.dpg
        try:
            down = self._left_button_down()
        except Exception:
            self._end_gesture()
            return
        pressed = down and not self._mouse_down
        self._mouse_down = down
        active_hits = {axis for axis, hit in self._hits.items() if dpg.is_item_active(hit)}
        activated = active_hits - self._active_hits
        self._active_hits = active_hits
        if blocked:
            # Keep the physical button transition synchronized while the
            # foreground surface owns input.  When that surface closes with
            # the button still held, the old press cannot become a new
            # scrollbar press on the following frame.
            self._end_gesture()
            return
        if not down:
            self._end_gesture()
        # The physical press can precede GLFW's next input frame. Retry on the
        # actual hit widget's activation edge rather than losing that drag when
        # the first poll still had the previous frame's hover state.
        if down and self._gesture is None and (pressed or activated):
            for axis, data in axes.items():
                hit = self._hits.get(axis)
                if not pressed and axis not in activated:
                    continue
                if hit is None or not (dpg.is_item_hovered(hit) or dpg.is_item_active(hit)):
                    continue
                data = self._last_axes.get(axis, data)
                if not self._inside(pointer, data["hit"]):
                    continue
                if not self._gate().acquire_pointer_input(self._pointer_owner):
                    continue
                self._captured = True
                pos = pointer[1 if axis == "v" else 0]
                # Start from the position matching the last displayed thumb.
                value = self._last_scroll.get(axis, data["value"])
                if self._inside(pointer, data["start_cap"]):
                    kind, delta = "button", -SharedScrollerMetrics.SCROLL_STEP
                elif self._inside(pointer, data["end_cap"]):
                    kind, delta = "button", SharedScrollerMetrics.SCROLL_STEP
                elif data["thumb0"] <= pos <= data["thumb0"] + data["length"]:
                    self._gesture = dict(axis=axis, kind="drag", offset=pos-data["thumb0"])
                    break
                else:
                    kind = "page"
                    delta = data["viewport"] * (-1 if pos < data["thumb0"] else 1)
                value = max(0.0, min(data["maximum"], value + delta))
                self._gesture = dict(axis=axis, kind=kind, delta=delta,
                                     value=value, next_repeat=now+SharedScrollerMetrics.REPEAT_DELAY)
                break
        gesture = self._gesture
        if gesture is not None:
            axis = gesture["axis"]
            data = axes.get(axis)
            if data is None or pointer is None:
                self._end_gesture()
            else:
                if gesture["kind"] == "drag":
                    pos = pointer[1 if axis == "v" else 0]
                    travel = max(0.0, data["available"] - data["length"])
                    ratio = (pos - gesture["offset"] - data["track0"]) / travel if travel else 0.0
                    value = max(0.0, min(1.0, ratio)) * data["maximum"]
                else:
                    value = gesture["value"]
                    cap = data["start_cap"] if gesture["delta"] < 0 else data["end_cap"]
                    if (gesture["kind"] == "button" and now >= gesture["next_repeat"]
                            and self._inside(pointer, cap)):
                        value += gesture["delta"]
                        gesture["next_repeat"] = now + SharedScrollerMetrics.REPEAT_INTERVAL
                    value = max(0.0, min(data["maximum"], value))
                    gesture["value"] = value
                setter = dpg.set_y_scroll if axis == "v" else dpg.set_x_scroll
                setter(self.target_item, value)
                data["value"] = value
        self._last_scroll = {axis: data["value"] for axis, data in axes.items()}
        self._last_axes = axes

    def update(self):
        if self._destroyed:
            return
        dpg = self.dpg
        try:
            if not dpg.does_item_exist(self.target_item):
                self.hide(); return
            if not self._target_is_shown():
                self.hide(); return
            self._fit_content()
            rect = self._target_rect()
            if rect is None:
                self.hide(); return
            x0, y0, x1, y1 = rect
            width, height = x1 - x0, y1 - y0
            if width <= 0 or height <= 0:
                self.hide(); return
            max_y = float(dpg.get_y_scroll_max(self.target_item)) if self.vertical else 0.0
            max_x = float(dpg.get_x_scroll_max(self.target_item)) if self.horizontal else 0.0
            cur_y = float(dpg.get_y_scroll(self.target_item)) if self.vertical else 0.0
            cur_x = float(dpg.get_x_scroll(self.target_item)) if self.horizontal else 0.0
            viewport_size = None
            if self._content_extent is not None:
                viewport_rect = dpg_window_rect(dpg, self.target_item, clip=True)
                if viewport_rect is not None:
                    viewport_size = (viewport_rect[2]-viewport_rect[0], viewport_rect[3]-viewport_rect[1])
                else:
                    viewport_size = tuple(map(float, dpg.get_item_rect_size(self.target_item)))
                # ImGui's scroll_max belongs to the previous content frame.
                # Column/row extents are authoritative, including on startup
                # and when the list is empty but its headers still overflow.
                max_x = max(0.0, self._content_extent[0]-viewport_size[0]) if self.horizontal else 0.0
                max_y = max(0.0, self._content_extent[1]-viewport_size[1]) if self.vertical else 0.0
        except Exception:
            self.hide(); return

        origin = dpg_window_rect(dpg, self.container)
        self._origin = (origin[0], origin[1]) if origin is not None else (x0, y0)
        dpg.configure_item(self.layer, width=max(1, int(width)), height=max(1, int(height)))

        m = SharedScrollerMetrics
        p = SharedScrollerPalette
        native_t = float(m.THICKNESS)
        has_v = self.vertical and max_y > 0.0
        has_h = self.horizontal and max_x > 0.0
        pointer = self._pointer()
        foreground_blocked = self._foreground_input_blocked()
        visual_pointer = None if foreground_blocked else pointer
        if foreground_blocked:
            # Occlusion is a z-order state, not an animation target.  Clear
            # hover/active chrome immediately instead of leaving a short fade
            # visible through the foreground dialog.
            self._end_gesture()
            self._expansion["v"] = 0.0
            self._expansion["h"] = 0.0

        # Animate only the chrome inside a fixed native gutter.
        now = time.monotonic()
        dt = max(0.0, min(0.05, now - self._last_time))
        self._last_time = now
        axes = {}
        # Resolve the *actual* reserved lane from the scrolling child's visible
        # geometry. DPG may add spacing around a width=-THICKNESS child; using
        # x1-THICKNESS blindly is what made the idle thumb appear right-biased.
        content_rect = dpg_window_rect(dpg, self.target_item, clip=True)
        content_right = content_rect[2] if content_rect is not None else None
        content_bottom = content_rect[3] if content_rect is not None else None
        v_lane_x0, v_lane_x1 = self._resolve_lane(x0, x1, content_right, native_t)
        h_lane_y0, h_lane_y1 = self._resolve_lane(y0, y1, content_bottom, native_t)
        v_lane_width = max(1.0, v_lane_x1 - v_lane_x0)
        h_lane_height = max(1.0, h_lane_y1 - h_lane_y0)
        v_full_t = min(native_t, v_lane_width)
        h_full_t = min(native_t, h_lane_height)
        v_bound_y1 = h_lane_y0 if has_h else y1
        h_bound_x1 = v_lane_x0 if has_v else x1
        v_hover_rect = (v_lane_x0, y0, v_lane_x1, v_bound_y1)
        h_hover_rect = (x0, h_lane_y0, h_bound_x1, h_lane_y1)
        v_hover = has_v and self._inside(visual_pointer, v_hover_rect, m.HOVER_MARGIN)
        h_hover = has_h and self._inside(visual_pointer, h_hover_rect, m.HOVER_MARGIN)
        for axis, hovered in (("v", v_hover), ("h", h_hover)):
            captured = self._gesture is not None and self._gesture["axis"] == axis
            target = 1.0 if hovered or captured else 0.0
            value = self._expansion[axis]
            step = dt / m.HOVER_DURATION
            self._expansion[axis] = min(target, value+step) if target > value else max(target, value-step)
        v_chrome = self._expansion["v"] > 0.0
        h_chrome = self._expansion["h"] > 0.0

        # Paint the reserved component gutters. Wheel scrolling still uses
        # the native child, and pointer gestures use the skin geometry.
        if has_v:
            self._set_part(
                "v_mask", (v_lane_x0, y0, v_lane_x1, v_bound_y1), v_chrome,
                fill=p.MASK, color=p.MASK, rounding=0.0)
        else:
            self._set_part("v_mask", (0,0,0,0), False)
        if has_h:
            self._set_part(
                "h_mask", (x0, h_lane_y0, h_bound_x1, h_lane_y1), h_chrome,
                fill=p.MASK, color=p.MASK, rounding=0.0)
        else:
            self._set_part("h_mask", (0,0,0,0), False)

        if has_v:
            collapsed_t = min(float(m.COLLAPSED_THICKNESS), v_full_t)
            t = collapsed_t + (v_full_t-collapsed_t)*self._expansion["v"]
            e = min(float(m.ARROW_BUTTON_EXTENT), max(0.0, (v_bound_y1-y0-2.0)/2.0))
            r = min(max(1.7, float(m.ARROW_GLYPH_RADIUS)*t/max(1.0, v_full_t)), e*0.25)
            # Collapse around the real lane center, including any DPG spacing
            # between the scrolling child and the parent edge.
            vx0, vx1 = self._centered_span(v_lane_x0, v_lane_x1, t)
            vy1 = v_bound_y1
            round_track = max(1.0, t * 0.5)
            self._set_part(
                "v_track", (vx0, y0, vx1, vy1), v_chrome,
                fill=p.TRACK, color=p.TRACK_BORDER, rounding=round_track)
            cap_x0, cap_x1 = self._centered_span(v_lane_x0, v_lane_x1, v_full_t)
            top = (cap_x0, y0, cap_x1, min(vy1, y0 + e))
            bottom = (cap_x0, max(y0, vy1 - e), cap_x1, vy1)
            tcx, tcy = (top[0]+top[2])/2.0, (top[1]+top[3])/2.0
            bcx, bcy = (bottom[0]+bottom[2])/2.0, (bottom[1]+bottom[3])/2.0
            cap_round = max(1.0, min(t, e) * 0.48)
            buttons_shown = self._expansion["v"] > 0.0
            self._set_cap(
                "up", top, self._triangle(tcx, tcy, "up", r), buttons_shown,
                hovered=self._inside(visual_pointer, top), rounding=cap_round)
            self._set_cap(
                "down", bottom, self._triangle(bcx, bcy, "down", r), buttons_shown,
                hovered=self._inside(visual_pointer, bottom), rounding=cap_round)

            track0 = top[3] + 1.0
            track1 = bottom[1] - 1.0
            available = max(0.0, track1 - track0)
            viewport = max(1.0, viewport_size[1] if viewport_size is not None else vy1-y0)
            total = viewport + max(0.0, max_y)
            if available > 0.0:
                thumb_len = available if total <= viewport else available * viewport / total
                thumb_len = min(available, max(float(m.MIN_THUMB), thumb_len))
                travel = max(0.0, available - thumb_len)
                ratio = 0.0 if max_y <= 0.0 else max(0.0, min(1.0, cur_y / max_y))
                thumb0 = track0 + travel * ratio
                inset = 1.5
                thumb_fill = p.THUMB_HOVER if v_hover else p.THUMB
                if self._gesture is not None and self._gesture["axis"] == "v":
                    thumb_fill = p.THUMB_ACTIVE
                self._set_part(
                    "v_thumb", (vx0 + inset, thumb0, vx1 - inset, thumb0 + thumb_len), True,
                    fill=thumb_fill, color=p.THUMB_BORDER, rounding=max(1.0, (t-2*inset)*0.5))
                axes["v"] = dict(hit=v_hover_rect, start_cap=top,
                                 end_cap=bottom,
                                 track0=track0, available=available, length=thumb_len,
                                 thumb0=thumb0, viewport=viewport, maximum=max_y, value=cur_y)
            else:
                self._set_part("v_thumb", (0,0,0,0), False)
        else:
            self._set_part("v_track", (0,0,0,0), False)
            self._set_part("v_thumb", (0,0,0,0), False)
            for key in ("up", "down"):
                self._set_cap(key, (0,0,0,0), ((0,0),(0,0),(0,0)), False)

        if has_h:
            collapsed_t = min(float(m.COLLAPSED_THICKNESS), h_full_t)
            t = collapsed_t + (h_full_t-collapsed_t)*self._expansion["h"]
            e = min(float(m.ARROW_BUTTON_EXTENT), max(0.0, (h_bound_x1-x0-2.0)/2.0))
            r = min(max(1.7, float(m.ARROW_GLYPH_RADIUS)*t/max(1.0, h_full_t)), e*0.25)
            hy0, hy1 = self._centered_span(h_lane_y0, h_lane_y1, t)
            hx1 = h_bound_x1
            round_track = max(1.0, t * 0.5)
            self._set_part(
                "h_track", (x0, hy0, hx1, hy1), h_chrome,
                fill=p.TRACK, color=p.TRACK_BORDER, rounding=round_track)
            cap_y0, cap_y1 = self._centered_span(h_lane_y0, h_lane_y1, h_full_t)
            left = (x0, cap_y0, min(hx1, x0 + e), cap_y1)
            right = (max(x0, hx1 - e), cap_y0, hx1, cap_y1)
            lcx, lcy = (left[0]+left[2])/2.0, (left[1]+left[3])/2.0
            rcx, rcy = (right[0]+right[2])/2.0, (right[1]+right[3])/2.0
            cap_round = max(1.0, min(t, e) * 0.48)
            buttons_shown = self._expansion["h"] > 0.0
            self._set_cap(
                "left", left, self._triangle(lcx, lcy, "left", r), buttons_shown,
                hovered=self._inside(visual_pointer, left), rounding=cap_round)
            self._set_cap(
                "right", right, self._triangle(rcx, rcy, "right", r), buttons_shown,
                hovered=self._inside(visual_pointer, right), rounding=cap_round)

            track0 = left[2] + 1.0
            track1 = right[0] - 1.0
            available = max(0.0, track1 - track0)
            viewport = max(1.0, viewport_size[0] if viewport_size is not None else hx1-x0)
            total = viewport + max(0.0, max_x)
            if available > 0.0:
                thumb_len = available if total <= viewport else available * viewport / total
                thumb_len = min(available, max(float(m.MIN_THUMB), thumb_len))
                travel = max(0.0, available - thumb_len)
                ratio = 0.0 if max_x <= 0.0 else max(0.0, min(1.0, cur_x / max_x))
                thumb0 = track0 + travel * ratio
                inset = 1.5
                thumb_fill = p.THUMB_HOVER if h_hover else p.THUMB
                if self._gesture is not None and self._gesture["axis"] == "h":
                    thumb_fill = p.THUMB_ACTIVE
                self._set_part(
                    "h_thumb", (thumb0, hy0 + inset, thumb0 + thumb_len, hy1 - inset), True,
                    fill=thumb_fill, color=p.THUMB_BORDER, rounding=max(1.0, (t-2*inset)*0.5))
                axes["h"] = dict(hit=h_hover_rect, start_cap=left,
                                 end_cap=right,
                                 track0=track0, available=available, length=thumb_len,
                                 thumb0=thumb0, viewport=viewport, maximum=max_x, value=cur_x)
            else:
                self._set_part("h_thumb", (0,0,0,0), False)
        else:
            self._set_part("h_track", (0,0,0,0), False)
            self._set_part("h_thumb", (0,0,0,0), False)
            for key in ("left", "right"):
                self._set_cap(key, (0,0,0,0), ((0,0),(0,0),(0,0)), False)

        if has_v and has_h and (v_chrome or h_chrome):
            # Square junction between the two rounded scrollbar tracks.
            self._set_part(
                "corner", (v_lane_x0, h_lane_y0, v_lane_x1, h_lane_y1), True,
                fill=p.END_CAP, color=p.TRACK_BORDER, rounding=0.0)
        else:
            self._set_part("corner", (0,0,0,0), False)
        self._fit_hit_items(axes)
        self._interact(axes, pointer, now, blocked=foreground_blocked)

    def destroy(self):
        if self._destroyed:
            return
        self._destroyed = True
        self.hide()
        for tag in self._hits.values():
            self._gate().unregister_pointer_protected_item(tag)
        try:
            dpg = self.dpg
            if dpg.does_item_exist(self.container):
                if dpg.does_item_exist(self.target_item):
                    dpg.move_item(self.target_item, parent=dpg.get_item_parent(self.container),
                                  before=self.container)
                    if self._original_config is not None:
                        dpg.configure_item(self.target_item, **self._original_config)
                dpg.delete_item(self.container)
            if dpg.does_item_exist(self.theme):
                dpg.delete_item(self.theme)
            if dpg.does_item_exist(self._hit_theme):
                dpg.delete_item(self._hit_theme)
        except Exception:
            pass
        self._parts.clear()
        self._rects.clear()
        self._arrows.clear()
        self._hits.clear()


class QScroller(DpgScrollerArrowOverlay):
    """Qt-style public name for the Dear PyGui scroller wrapper.

    The implementation intentionally keeps the existing overlay behavior while
    exposing a stable, backend-oriented name that can be reused across applications.
    """




__all__ = [
    "SharedScrollerMetrics",
    "SharedScrollerPalette",
    "DpgScrollerArrowOverlay",
    "QScroller",
    "dpg_window_rect",
    "add_dpg_scroller_style",
    "configure_ttk_scroller_styles",
    "make_ttk_scroller",
    "ttk_scroller_style_name",
]
