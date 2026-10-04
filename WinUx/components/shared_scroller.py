"""Shared WinUx scrollbar/scroller styling for Dear PyGui and Tk/ttk.

The module stays backend-neutral at import time. Dear PyGui is passed in by
callers, while Tk/ttk consumers use the same metrics and palette. The DPG skin
adds rounded Qt-like tracks, interactive end buttons and hover expansion over
the native scroll range. Wheel scrolling remains managed by Dear ImGui.
"""
from __future__ import annotations

import time

from .qt_style import color_hex


class SharedScrollerMetrics:
    """One geometry contract for all WinUx scrollbars."""

    # Reserve fixed gutters so hover never shifts the content layout.
    THICKNESS = 11
    COLLAPSED_THICKNESS = 6
    HOVER_DURATION = 0.16
    SCROLL_STEP = 32
    REPEAT_DELAY = 0.35
    REPEAT_INTERVAL = 0.06
    HIT_THICKNESS = 19
    HOVER_MARGIN = 4
    ARROW_SIZE = 7
    ARROW_BUTTON_EXTENT = 11
    ARROW_GLYPH_RADIUS = 2.7
    ROUNDING = 6
    MIN_THUMB = 24


class SharedScrollerPalette:
    """Windows-like neutral-gray scrollbar palette."""

    TRACK = (246, 246, 246, 255)
    TRACK_BORDER = (216, 216, 216, 255)
    END_CAP = (238, 238, 238, 255)
    END_CAP_HOVER = (226, 226, 226, 255)
    END_CAP_BORDER = (205, 205, 205, 255)
    MASK = (248, 248, 248, 255)
    THUMB = (148, 148, 148, 255)
    THUMB_BORDER = (128, 128, 128, 255)
    THUMB_HOVER = (132, 132, 132, 255)
    THUMB_ACTIVE = (114, 114, 114, 255)
    ARROW = (35, 35, 35, 255)
    ARROW_DISABLED = (164, 164, 164, 255)


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


def ttk_scroller_style_name(orient):
    value = str(orient or "vertical").lower()
    return "WinUx.Horizontal.TScrollbar" if value.startswith("h") else "WinUx.Vertical.TScrollbar"


def configure_ttk_scroller_styles(style):
    """Install the shared scrollbar styles into an existing ``ttk.Style``.

    ttk uses the platform's native scrollbar layout, so Windows arrow buttons
    remain available while WinUx supplies a consistent neutral-gray palette.
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

    for name in ("WinUx.Vertical.TScrollbar", "WinUx.Horizontal.TScrollbar"):
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


def make_ttk_scroller(ttk_module, parent, *, orient="vertical", command=None, **kwargs):
    """Create a ttk scrollbar that always uses the shared WinUx style."""

    kwargs.setdefault("style", ttk_scroller_style_name(orient))
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

    Pointer gestures use the drawn geometry, including the space reserved for
    end buttons, rather than the different underlying ImGui thumb geometry.
    Chrome is drawn inside a dedicated child container, beside the scrolling
    content. ImGui therefore stacks tooltips/popups above it naturally.
    """

    def __init__(self, dpg, target_item, tag, *, vertical=True, horizontal=False,
                  rect_provider=None, content_item=None, content_size_provider=None):
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
        self._ensure_items()

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
            kwargs = dict(
                pmin=(x0-ox, y0-oy), pmax=(x1-ox, y1-oy), show=show,
                fill=p.END_CAP_HOVER if hovered else p.END_CAP,
                color=p.END_CAP_BORDER)
            if rounding is not None:
                kwargs["rounding"] = float(rounding)
            dpg.configure_item(rect_tag, **kwargs)
            dpg.configure_item(
                arrow_tag, **{name: (point[0]-ox, point[1]-oy)
                              for name, point in zip(("p1", "p2", "p3"), points)},
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
            kwargs = dict(pmin=(x0-ox, y0-oy), pmax=(x1-ox, y1-oy), show=show)
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
        self._gesture = None
        self._expansion = {"v": 0.0, "h": 0.0}
        self._last_scroll.clear()
        self._last_axes.clear()
        dpg = self.dpg
        for tag in list(self._parts.values()) + list(self._rects.values()) + list(self._arrows.values()):
            try:
                if tag and dpg.does_item_exist(tag):
                    dpg.configure_item(tag, show=False)
            except Exception:
                pass

    @staticmethod
    def _triangle(cx, cy, direction, radius):
        r = float(radius)
        if direction == "up":
            return ((cx, cy-r), (cx-r, cy+r*0.65), (cx+r, cy+r*0.65))
        if direction == "down":
            return ((cx, cy+r), (cx-r, cy-r*0.65), (cx+r, cy-r*0.65))
        if direction == "left":
            return ((cx-r, cy), (cx+r*0.65, cy-r), (cx+r*0.65, cy+r))
        return ((cx+r, cy), (cx-r*0.65, cy-r), (cx-r*0.65, cy+r))

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

    def _interact(self, axes, pointer, now):
        """Handle end-button repeat, page clicks and captured thumb dragging."""
        dpg = self.dpg
        try:
            down = dpg.is_mouse_button_down(dpg.mvMouseButton_Left)
            hovered = dpg.is_item_hovered(self.container)
        except Exception:
            return
        pressed = down and not self._mouse_down
        self._mouse_down = down
        if not down:
            self._gesture = None
        if pressed and hovered:
            for axis, data in axes.items():
                data = self._last_axes.get(axis, data)
                if not self._inside(pointer, data["hit"]):
                    continue
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
                self._gesture = None
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

        # Animate only the chrome inside a fixed native gutter.
        now = time.monotonic()
        dt = max(0.0, min(0.05, now - self._last_time))
        self._last_time = now
        axes = {}
        v_bound_y1 = y1 - (native_t if has_h else 0.0)
        h_bound_x1 = x1 - (native_t if has_v else 0.0)
        v_hover_rect = (x1 - native_t, y0, x1, v_bound_y1)
        h_hover_rect = (x0, y1 - native_t, h_bound_x1, y1)
        v_hover = has_v and self._inside(pointer, v_hover_rect, m.HOVER_MARGIN)
        h_hover = has_h and self._inside(pointer, h_hover_rect, m.HOVER_MARGIN)
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
                "v_mask", (x1 - native_t, y0, x1, v_bound_y1), v_chrome,
                fill=p.MASK, color=p.MASK, rounding=0.0)
        else:
            self._set_part("v_mask", (0,0,0,0), False)
        if has_h:
            self._set_part(
                "h_mask", (x0, y1 - native_t, h_bound_x1, y1), h_chrome,
                fill=p.MASK, color=p.MASK, rounding=0.0)
        else:
            self._set_part("h_mask", (0,0,0,0), False)

        if has_v:
            t = m.COLLAPSED_THICKNESS + (native_t-m.COLLAPSED_THICKNESS)*self._expansion["v"]
            e = min(float(m.ARROW_BUTTON_EXTENT), max(0.0, (v_bound_y1-y0-2.0)/2.0))
            r = min(float(m.ARROW_GLYPH_RADIUS)*t/native_t, e*0.25)
            vx0 = x1 - t
            vy1 = v_bound_y1
            round_track = max(1.0, t * 0.5)
            self._set_part(
                "v_track", (vx0, y0, x1, vy1), v_chrome,
                fill=p.TRACK, color=p.TRACK_BORDER, rounding=round_track)
            top = (vx0, y0, x1, min(vy1, y0 + e))
            bottom = (vx0, max(y0, vy1 - e), x1, vy1)
            tcx, tcy = (top[0]+top[2])/2.0, (top[1]+top[3])/2.0
            bcx, bcy = (bottom[0]+bottom[2])/2.0, (bottom[1]+bottom[3])/2.0
            cap_round = max(1.0, min(t, e) * 0.48)
            buttons_shown = self._expansion["v"] > 0.0
            self._set_cap(
                "up", top, self._triangle(tcx, tcy, "up", r), buttons_shown,
                hovered=self._inside(pointer, top), rounding=cap_round)
            self._set_cap(
                "down", bottom, self._triangle(bcx, bcy, "down", r), buttons_shown,
                hovered=self._inside(pointer, bottom), rounding=cap_round)

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
                    "v_thumb", (vx0 + inset, thumb0, x1 - inset, thumb0 + thumb_len), True,
                    fill=thumb_fill, color=p.THUMB_BORDER, rounding=max(1.0, (t-2*inset)*0.5))
                axes["v"] = dict(hit=v_hover_rect, start_cap=(x1-native_t, top[1], x1, top[3]),
                                 end_cap=(x1-native_t, bottom[1], x1, bottom[3]),
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
            t = m.COLLAPSED_THICKNESS + (native_t-m.COLLAPSED_THICKNESS)*self._expansion["h"]
            e = min(float(m.ARROW_BUTTON_EXTENT), max(0.0, (h_bound_x1-x0-2.0)/2.0))
            r = min(float(m.ARROW_GLYPH_RADIUS)*t/native_t, e*0.25)
            hy0 = y1 - t
            hx1 = h_bound_x1
            round_track = max(1.0, t * 0.5)
            self._set_part(
                "h_track", (x0, hy0, hx1, y1), h_chrome,
                fill=p.TRACK, color=p.TRACK_BORDER, rounding=round_track)
            left = (x0, hy0, min(hx1, x0 + e), y1)
            right = (max(x0, hx1 - e), hy0, hx1, y1)
            lcx, lcy = (left[0]+left[2])/2.0, (left[1]+left[3])/2.0
            rcx, rcy = (right[0]+right[2])/2.0, (right[1]+right[3])/2.0
            cap_round = max(1.0, min(t, e) * 0.48)
            buttons_shown = self._expansion["h"] > 0.0
            self._set_cap(
                "left", left, self._triangle(lcx, lcy, "left", r), buttons_shown,
                hovered=self._inside(pointer, left), rounding=cap_round)
            self._set_cap(
                "right", right, self._triangle(rcx, rcy, "right", r), buttons_shown,
                hovered=self._inside(pointer, right), rounding=cap_round)

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
                    "h_thumb", (thumb0, hy0 + inset, thumb0 + thumb_len, y1 - inset), True,
                    fill=thumb_fill, color=p.THUMB_BORDER, rounding=max(1.0, (t-2*inset)*0.5))
                axes["h"] = dict(hit=h_hover_rect, start_cap=(left[0], y1-native_t, left[2], y1),
                                 end_cap=(right[0], y1-native_t, right[2], y1),
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
                "corner", (x1 - native_t, y1 - native_t, x1, y1), True,
                fill=p.END_CAP, color=p.TRACK_BORDER, rounding=0.0)
        else:
            self._set_part("corner", (0,0,0,0), False)
        self._interact(axes, pointer, now)

    def destroy(self):
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
        except Exception:
            pass
        self._parts.clear()
        self._rects.clear()
        self._arrows.clear()


__all__ = [
    "SharedScrollerMetrics",
    "SharedScrollerPalette",
    "DpgScrollerArrowOverlay",
    "dpg_window_rect",
    "add_dpg_scroller_style",
    "configure_ttk_scroller_styles",
    "make_ttk_scroller",
    "ttk_scroller_style_name",
]
