"""Reusable Qt-like dock chrome for Dear PyGui tool panels.

The implementation deliberately mirrors the interaction contract and compact
visual language of ``QDockWidget`` without introducing a Qt dependency.  The
host still owns the actual docking geometry; this class owns only the framed
panel, title chrome, float/close controls and state transitions.
"""

from __future__ import annotations

from typing import Callable, Optional

import dearpygui.dearpygui as dpg

from .qt_style import QtFusionPalette
from ..widgets.imgui_qt_style import (
    dock_content_theme, dock_control_theme, dock_frame_theme, dock_title_theme,
    menu_bar_theme,
)
from .tooltip import add_styled_tooltip

from .interaction_gate import (
    register_pointer_protected_item,
    unregister_pointer_protected_item,
)


class DockWidget:
    """Compact dock container modelled after Qt/Fusion ``QDockWidget``.

    A docked instance has a one-pixel neutral frame, a 24 px title strip, small
    right-aligned float/close buttons and a content widget that is flush with
    the chrome.  When the host tears the dock out into a top-level window, the
    embedded title strip is hidden so the native floating window owns movement
    and title-bar chrome, just like a floating ``QDockWidget``.
    """

    # QDockWidget-style feature flags.  Keeping them local avoids a Qt
    # dependency while still exposing the same useful behaviour contract to
    # WinUx tool panels.
    DockWidgetClosable = 0x01
    DockWidgetMovable = 0x02
    DockWidgetFloatable = 0x04
    AllDockWidgetFeatures = (
        DockWidgetClosable | DockWidgetMovable | DockWidgetFloatable)

    # QMainWindow/QDockWidget-style dock areas.  These are deliberately kept
    # dependency-free so WinUx can expose the familiar Qt contract while still
    # rendering with Dear PyGui.
    LeftDockWidgetArea = 0x01
    RightDockWidgetArea = 0x02
    TopDockWidgetArea = 0x04
    BottomDockWidgetArea = 0x08
    AllDockWidgetAreas = (
        LeftDockWidgetArea | RightDockWidgetArea
        | TopDockWidgetArea | BottomDockWidgetArea)
    _AREA_NAME_TO_FLAG = {
        "left": LeftDockWidgetArea,
        "right": RightDockWidgetArea,
        "top": TopDockWidgetArea,
        "bottom": BottomDockWidgetArea,
    }

    FRAME = 1
    TITLE_HEIGHT = 24
    CONTROL_SIZE = 20
    CONTROL_GAP = 1
    TITLE_LEFT_PADDING = 6
    TITLE_TOP_PADDING = 4
    TITLE_TEXT_RIGHT_PADDING = 4

    # Text/glyph colors remain local geometry details; surface/state colors are
    # supplied by the shared Dear ImGui Qt/Fusion style foundation.
    TEXT_COLOR = QtFusionPalette.TEXT
    GLYPH_COLOR = (55, 55, 55, 255)

    def __init__(
            self,
            parent,
            title: str,
            tag: str,
            on_float_change: Optional[Callable[[bool], None]] = None,
            on_close: Optional[Callable[[], None]] = None,
            features: Optional[int] = None,
            dock_area: str = "right",
            allowed_areas: Optional[int] = None,
            on_dock_area_change: Optional[Callable[[str], None]] = None):
        self.parent = parent
        self.title = str(title or "")
        self.tag = str(tag)
        self.on_float_change = on_float_change
        self.on_close = on_close
        self.on_dock_area_change = on_dock_area_change
        self.features = (
            self.AllDockWidgetFeatures if features is None else int(features))
        self.allowed_areas = (
            self.AllDockWidgetAreas if allowed_areas is None
            else int(allowed_areas))
        self.dock_area = self._normalize_dock_area(dock_area)
        if not self.is_area_allowed(self.dock_area):
            self.dock_area = self._first_allowed_area()
        self.floating = False
        self._last_layout_size = (0, 0)
        self._title_menu = None

        self._build_themes()

        # Do not use Dear PyGui's native child border here.  Its thickness and
        # colour can vary with the global theme and produced the heavy black
        # outline seen in earlier builds.  Instead the root uses the frame
        # colour as its background and the title/content are inset by 1 px.
        self.root = dpg.add_child_window(
            parent=self.parent,
            tag=self.tag,
            width=-1,
            height=-1,
            border=False,
            no_scrollbar=True,
            no_scroll_with_mouse=True,
        )
        dpg.bind_item_theme(self.root, self._frame_theme)
        # Do NOT register the embedded dock root as a global foreground
        # surface while it is docked. A docked panel is a normal sibling in
        # the main layout, not an overlay. Treating its large child-window
        # rectangle as a global input shield can make unrelated panes (most
        # visibly the Local Explorer list) non-interactive on DPG builds that
        # report child rect_min in parent-local coordinates.
        #
        # Click-through protection is still complete where it is needed:
        # * the title drag handle below is protected for tear-off gestures;
        # * the host registers the top-level floating window when detached;
        # * dialogs/popups register their own actual overlay surfaces.

        self.title_bar = dpg.add_child_window(
            parent=self.root,
            pos=(self.FRAME, self.FRAME),
            width=1,
            height=self.TITLE_HEIGHT,
            border=False,
            no_scrollbar=True,
            no_scroll_with_mouse=True,
        )
        dpg.bind_item_theme(self.title_bar, self._title_theme)

        # Transparent button used as the drag/double-click target.  It extends
        # from the left edge up to the title controls and therefore behaves like
        # the free title area in QDockWidget.
        self.drag_handle = dpg.add_button(
            parent=self.title_bar,
            label="",
            pos=(0, 0),
            width=1,
            height=self.TITLE_HEIGHT,
            callback=lambda: None,
        )
        dpg.bind_item_theme(self.drag_handle, self._drag_theme)
        # Global DPG mouse handlers continue firing for widgets underneath a
        # dragged dock. Register the title handle as a protected foreground
        # surface so background views never start selection/rubber-band work.
        register_pointer_protected_item(self.drag_handle)

        self.title_text = dpg.add_text(
            self.title,
            parent=self.title_bar,
            pos=(self.TITLE_LEFT_PADDING, self.TITLE_TOP_PADDING),
            color=self.TEXT_COLOR,
        )

        with dpg.item_handler_registry() as self._title_handlers:
            dpg.add_item_double_clicked_handler(
                button=dpg.mvMouseButton_Left,
                callback=self._title_double_clicked)
            dpg.add_item_clicked_handler(
                button=dpg.mvMouseButton_Right,
                callback=self._show_title_menu)
        dpg.bind_item_handler_registry(self.drag_handle, self._title_handlers)

        # Buttons are hit areas only.  The small line glyphs are rendered in a
        # title overlay so their appearance does not depend on Unicode glyphs
        # being present in the Dear PyGui default font.
        self.float_button = dpg.add_button(
            parent=self.title_bar,
            label="",
            pos=(0, 0),
            width=self.CONTROL_SIZE,
            height=self.CONTROL_SIZE,
            callback=self._float_clicked,
        )
        self.close_button = dpg.add_button(
            parent=self.title_bar,
            label="",
            pos=(0, 0),
            width=self.CONTROL_SIZE,
            height=self.CONTROL_SIZE,
            callback=self._close_clicked,
        )
        dpg.bind_item_theme(self.float_button, self._float_control_theme)
        dpg.bind_item_theme(self.close_button, self._close_control_theme)

        add_styled_tooltip(self.float_button, "Float")
        add_styled_tooltip(self.close_button, "Close")

        # Qt exposes dock actions from the title area.  Dear PyGui has no
        # QDockWidget system menu, so provide a compact popup with the same
        # practical actions.  The popup is an overlay and therefore registers
        # with the global pointer gate to prevent click-through.
        self._title_menu = dpg.add_window(
            popup=True, show=False, width=166, height=146,
            no_saved_settings=True, no_title_bar=True, no_resize=True,
            no_collapse=True, no_scrollbar=True, no_scroll_with_mouse=True)
        dpg.bind_item_theme(self._title_menu, self._menu_theme)
        register_pointer_protected_item(self._title_menu)
        self._menu_float = dpg.add_selectable(
            parent=self._title_menu, label="Float",
            callback=self._menu_float_clicked)
        self._menu_dock_separator = dpg.add_separator(parent=self._title_menu)
        self._menu_dock_items = {}
        for area_name, label in (("left", "Dock Left"),
                                 ("right", "Dock Right"),
                                 ("top", "Dock Top"),
                                 ("bottom", "Dock Bottom")):
            self._menu_dock_items[area_name] = dpg.add_selectable(
                parent=self._title_menu, label=label,
                callback=self._menu_dock_area_clicked,
                user_data=area_name)
        self._menu_separator = dpg.add_separator(parent=self._title_menu)
        self._menu_close = dpg.add_selectable(
            parent=self._title_menu, label="Close",
            callback=self._menu_close_clicked)

        self.title_overlay = dpg.add_drawlist(
            parent=self.title_bar,
            pos=(0, 0),
            width=1,
            height=self.TITLE_HEIGHT,
        )
        # Floating glyph = two overlapping tiny windows.
        self._float_back = dpg.draw_rectangle(
            (0, 0), (1, 1), color=self.GLYPH_COLOR, thickness=1.0,
            parent=self.title_overlay)
        self._float_front = dpg.draw_rectangle(
            (0, 0), (1, 1), color=self.GLYPH_COLOR, thickness=1.0,
            parent=self.title_overlay)
        # Close glyph = crisp 8 px cross rather than a large window-style X.
        self._close_line_a = dpg.draw_line(
            (0, 0), (1, 1), color=self.GLYPH_COLOR, thickness=1.15,
            parent=self.title_overlay)
        self._close_line_b = dpg.draw_line(
            (0, 1), (1, 0), color=self.GLYPH_COLOR, thickness=1.15,
            parent=self.title_overlay)
        with dpg.item_handler_registry() as self._close_visual_handlers:
            dpg.add_item_visible_handler(callback=self._sync_close_glyph_visual)
        dpg.bind_item_handler_registry(self.close_button, self._close_visual_handlers)

        self.content = dpg.add_child_window(
            parent=self.root,
            pos=(self.FRAME, self.TITLE_HEIGHT + 2 * self.FRAME),
            width=1,
            height=1,
            border=False,
            no_scrollbar=True,
            no_scroll_with_mouse=True,
        )
        dpg.bind_item_theme(self.content, self._content_theme)

        self.sync_layout(force=True)

    def _build_themes(self):
        # The dock chrome now comes from the same Dear ImGui Qt/Fusion style
        # foundation as dialogs, toolbars and item views.  Keep only the
        # transparent drag target local because it is interaction geometry, not
        # a visible control.
        self._frame_theme = dock_frame_theme(dpg)
        self._title_theme = dock_title_theme(dpg, active=True)
        self._content_theme = dock_content_theme(dpg)
        self._float_control_theme = dock_control_theme(dpg, close=False)
        self._close_control_theme = dock_control_theme(dpg, close=True)
        self._menu_theme = menu_bar_theme(dpg)

        with dpg.theme() as self._drag_theme:
            with dpg.theme_component(dpg.mvButton):
                transparent = (0, 0, 0, 0)
                dpg.add_theme_color(dpg.mvThemeCol_Button, transparent)
                dpg.add_theme_color(dpg.mvThemeCol_ButtonHovered, transparent)
                dpg.add_theme_color(dpg.mvThemeCol_ButtonActive, transparent)
                dpg.add_theme_style(dpg.mvStyleVar_FrameRounding, 0)
                dpg.add_theme_style(dpg.mvStyleVar_FrameBorderSize, 0)
                dpg.add_theme_style(dpg.mvStyleVar_FramePadding, 0, 0)

    @classmethod
    def _normalize_dock_area(cls, area):
        name = str(area or "right").strip().lower()
        return name if name in cls._AREA_NAME_TO_FLAG else "right"

    def _first_allowed_area(self):
        for name in ("right", "left", "bottom", "top"):
            if self.is_area_allowed(name):
                return name
        return "right"

    def is_area_allowed(self, area):
        name = self._normalize_dock_area(area)
        return bool(int(self.allowed_areas) & int(self._AREA_NAME_TO_FLAG[name]))

    def set_allowed_areas(self, areas):
        self.allowed_areas = int(areas)
        if not self.is_area_allowed(self.dock_area):
            self.dock_area = self._first_allowed_area()
        self._sync_action_visibility()

    def set_dock_area(self, area, notify=False):
        name = self._normalize_dock_area(area)
        if not self.is_area_allowed(name):
            return False
        changed = name != self.dock_area
        self.dock_area = name
        self._sync_action_visibility()
        if changed and notify and callable(self.on_dock_area_change):
            self.on_dock_area_change(name)
        return True

    def _feature_enabled(self, feature):
        return bool(int(self.features) & int(feature))

    @property
    def movable(self):
        return self._feature_enabled(self.DockWidgetMovable)

    @property
    def floatable(self):
        return self._feature_enabled(self.DockWidgetFloatable)

    @property
    def closable(self):
        return self._feature_enabled(self.DockWidgetClosable)

    def set_features(self, features):
        self.features = int(features)
        self._last_layout_size = (0, 0)
        self._sync_action_visibility()
        self.sync_layout(force=True)

    def set_feature_enabled(self, feature, enabled=True):
        features = int(self.features)
        if enabled:
            features |= int(feature)
        else:
            features &= ~int(feature)
        self.set_features(features)

    def _sync_action_visibility(self):
        try:
            if dpg.does_item_exist(self.float_button):
                dpg.configure_item(self.float_button, show=self.floatable)
            if dpg.does_item_exist(self.close_button):
                dpg.configure_item(self.close_button, show=self.closable)
            # Keep vector glyphs in lock-step with their hit buttons.
            for glyph in (self._float_back, self._float_front):
                if dpg.does_item_exist(glyph):
                    dpg.configure_item(glyph, show=self.floatable)
            for glyph in (self._close_line_a, self._close_line_b):
                if dpg.does_item_exist(glyph):
                    dpg.configure_item(glyph, show=self.closable)
            if self._title_menu and dpg.does_item_exist(self._title_menu):
                dpg.configure_item(
                    self._menu_float, show=self.floatable,
                    label="Dock" if self.floating else "Float")
                area_actions_visible = bool(self.movable)
                for area_name, item in self._menu_dock_items.items():
                    allowed = area_actions_visible and self.is_area_allowed(area_name)
                    dpg.configure_item(
                        item, show=allowed,
                        label=("✓ " if area_name == self.dock_area and not self.floating else "")
                              + "Dock " + area_name.title())
                dpg.configure_item(
                    self._menu_dock_separator, show=area_actions_visible)
                dpg.configure_item(self._menu_close, show=self.closable)
                dpg.configure_item(
                    self._menu_separator,
                    show=self.closable and (self.floatable or area_actions_visible))
        except Exception:
            pass

    def _title_double_clicked(self, sender=None, app_data=None, user_data=None):
        if self.floatable and not self.floating:
            self._float_clicked()

    def _show_title_menu(self, sender=None, app_data=None, user_data=None):
        if not self._title_menu or not dpg.does_item_exist(self._title_menu):
            return
        self._sync_action_visibility()
        if not self.floatable and not self.closable and not self.movable:
            return
        try:
            mx, my = map(int, dpg.get_mouse_pos(local=False))
            dpg.configure_item(
                self._title_menu, pos=(mx, my), show=True)
            dpg.focus_item(self._title_menu)
        except Exception:
            try:
                dpg.configure_item(self._title_menu, show=True)
            except Exception:
                pass

    def _hide_title_menu(self):
        if self._title_menu and dpg.does_item_exist(self._title_menu):
            try:
                dpg.configure_item(self._title_menu, show=False)
            except Exception:
                pass

    def _menu_float_clicked(self, sender=None, app_data=None, user_data=None):
        self._hide_title_menu()
        self._float_clicked()

    def _menu_dock_area_clicked(
            self, sender=None, app_data=None, user_data=None):
        area = self._normalize_dock_area(user_data)
        self._hide_title_menu()
        if not self.movable or not self.is_area_allowed(area):
            return
        callback = self.on_dock_area_change
        if callable(callback):
            callback(area)
        else:
            self.set_dock_area(area)

    def _menu_close_clicked(self, sender=None, app_data=None, user_data=None):
        self._hide_title_menu()
        self._close_clicked()

    def _float_clicked(self, sender=None, app_data=None, user_data=None):
        if not self.floatable:
            return
        callback = self.on_float_change
        if callable(callback):
            callback(not self.floating)

    def _close_clicked(self, sender=None, app_data=None, user_data=None):
        if not self.closable:
            return
        callback = self.on_close
        if callable(callback):
            callback()

    @staticmethod
    def _elide_title(title: str, available_px: int):
        """Approximate Qt::ElideRight for the compact default DPG font."""
        text = str(title or "")
        available_px = max(0, int(available_px))
        # Default Dear PyGui text is close to seven pixels per average glyph at
        # the scale used by WinUx. This intentionally errs on the conservative
        # side so long job names never paint underneath the dock controls.
        max_chars = max(0, available_px // 7)
        if len(text) <= max_chars:
            return text
        if max_chars <= 1:
            return ""
        if max_chars <= 4:
            return "." * max_chars
        return text[:max_chars - 3].rstrip() + "..."

    def set_title(self, title: str):
        self.title = str(title or "")
        self.sync_layout(force=True)

    def set_floating(self, floating: bool):
        floating = bool(floating)
        if self.floating == floating:
            self.sync_layout(force=True)
            return
        self.floating = floating
        self._hide_title_menu()
        self._sync_action_visibility()
        if dpg.does_item_exist(self.title_bar):
            dpg.configure_item(self.title_bar, show=not floating)
        self.sync_layout(force=True)

    def _sync_close_glyph_visual(self, sender=None, app_data=None, user_data=None):
        """Keep the vector X readable over the red close-button hover state."""
        try:
            hovered = bool(dpg.is_item_hovered(self.close_button))
            active = bool(dpg.is_item_active(self.close_button))
            color = (255, 255, 255, 255) if (hovered or active) else self.GLYPH_COLOR
            dpg.configure_item(self._close_line_a, color=color)
            dpg.configure_item(self._close_line_b, color=color)
        except Exception:
            pass

    def _update_title_glyphs(self, float_x: int, close_x: int, control_y: int):
        """Position vector glyphs over the right-aligned title buttons."""
        # Coordinates are relative to title_overlay/title_bar.
        fy = control_y
        try:
            dpg.configure_item(
                self._float_back,
                pmin=(float_x + 5, fy + 7), pmax=(float_x + 11, fy + 13))
            dpg.configure_item(
                self._float_front,
                pmin=(float_x + 8, fy + 4), pmax=(float_x + 14, fy + 10))
            dpg.configure_item(
                self._close_line_a,
                p1=(close_x + 5, fy + 5), p2=(close_x + 13, fy + 13))
            dpg.configure_item(
                self._close_line_b,
                p1=(close_x + 13, fy + 5), p2=(close_x + 5, fy + 13))
        except Exception:
            # Older DPG builds can be stricter about draw-item reconfiguration;
            # losing a glyph is preferable to breaking the dock layout.
            pass

    def sync_layout(self, width=None, height=None, force=False):
        """Keep Qt-like chrome aligned while the host/splitter is resized."""
        if not dpg.does_item_exist(self.root):
            return

        try:
            actual_w, actual_h = dpg.get_item_rect_size(self.root)
            actual_w, actual_h = int(actual_w), int(actual_h)
        except Exception:
            actual_w, actual_h = 0, 0

        try:
            cfg = dpg.get_item_configuration(self.root)
        except Exception:
            cfg = {}

        if width is None:
            width = actual_w if actual_w > 1 else int(cfg.get("width", 1) or 1)
        if height is None:
            height = actual_h if actual_h > 1 else int(cfg.get("height", 1) or 1)
        width = max(1, int(width))
        height = max(1, int(height))

        if not force and self._last_layout_size == (width, height):
            return
        self._last_layout_size = (width, height)

        inner_w = max(1, width - 2 * self.FRAME)
        inner_h = max(1, height - 2 * self.FRAME)

        if self.floating:
            dpg.configure_item(self.title_bar, show=False)
            dpg.configure_item(
                self.content,
                pos=(self.FRAME, self.FRAME),
                width=inner_w,
                height=inner_h,
            )
            return

        title_h = min(self.TITLE_HEIGHT, inner_h)
        visible_controls = []
        if self.floatable:
            visible_controls.append(self.float_button)
        if self.closable:
            visible_controls.append(self.close_button)
        controls_w = (
            len(visible_controls) * self.CONTROL_SIZE
            + max(0, len(visible_controls) - 1) * self.CONTROL_GAP)
        drag_w = max(1, inner_w - controls_w)
        control_y = max(0, (title_h - self.CONTROL_SIZE) // 2)

        dpg.configure_item(
            self.title_bar,
            pos=(self.FRAME, self.FRAME),
            width=inner_w,
            height=title_h,
            show=True,
        )
        dpg.configure_item(
            self.drag_handle,
            pos=(0, 0),
            width=drag_w,
            height=title_h,
        )

        # Qt packs title buttons from the right edge.  Keep Close rightmost and
        # Float immediately to its left, while allowing either feature to be
        # disabled without leaving a dead gap.
        right_x = inner_w
        close_x = inner_w
        float_x = inner_w
        if self.closable:
            right_x -= self.CONTROL_SIZE
            close_x = right_x
            dpg.configure_item(
                self.close_button, pos=(close_x, control_y),
                width=self.CONTROL_SIZE, height=self.CONTROL_SIZE, show=True)
            right_x -= self.CONTROL_GAP
        else:
            dpg.configure_item(self.close_button, show=False)
        if self.floatable:
            right_x -= self.CONTROL_SIZE
            float_x = right_x
            dpg.configure_item(
                self.float_button, pos=(float_x, control_y),
                width=self.CONTROL_SIZE, height=self.CONTROL_SIZE, show=True)
        else:
            dpg.configure_item(self.float_button, show=False)

        title_available = max(
            0, drag_w - self.TITLE_LEFT_PADDING - self.TITLE_TEXT_RIGHT_PADDING)
        if dpg.does_item_exist(self.title_text):
            dpg.set_value(
                self.title_text, self._elide_title(self.title, title_available))
        dpg.configure_item(
            self.title_overlay,
            pos=(0, 0),
            width=inner_w,
            height=title_h,
        )
        if self.floatable or self.closable:
            self._update_title_glyphs(float_x, close_x, control_y)

        # Leave one frame-colour scanline between title and client area.  It is
        # the subtle separator used by QDockWidget/Fusion rather than a thick
        # black border.
        content_y = self.FRAME + title_h + self.FRAME
        content_h = max(1, height - content_y - self.FRAME)
        dpg.configure_item(
            self.content,
            pos=(self.FRAME, content_y),
            width=inner_w,
            height=content_h,
        )

    def close(self):
        # root is intentionally not a protected surface while docked; keep the
        # unregister call harmless for compatibility with instances created by
        # an older build before an in-process update/reload.
        unregister_pointer_protected_item(getattr(self, "root", None))
        unregister_pointer_protected_item(getattr(self, "drag_handle", None))
        unregister_pointer_protected_item(getattr(self, "_title_menu", None))
        for handlers in (
                getattr(self, "_title_handlers", None),
                getattr(self, "_close_visual_handlers", None)):
            if handlers and dpg.does_item_exist(handlers):
                try:
                    dpg.delete_item(handlers)
                except Exception:
                    pass
        if self._title_menu and dpg.does_item_exist(self._title_menu):
            try:
                dpg.delete_item(self._title_menu)
            except Exception:
                pass
        if dpg.does_item_exist(self.root):
            dpg.delete_item(self.root)


class DockDropPreview:
    """Viewport-front translucent dock target preview.

    QMainWindow paints docking feedback above the central widget while a
    floating QDockWidget is dragged near an allowed dock area.  A normal child
    drawlist can be obscured by sibling child windows, so WinUx keeps this
    feedback in a lazy viewport-front drawlist.  The overlay is visual only and
    never participates in hit testing.
    """

    BORDER = (0, 120, 215, 235)
    FILL = (0, 120, 215, 52)
    INNER_BORDER = (0, 120, 215, 150)
    INNER_FILL = (0, 120, 215, 24)

    def __init__(self, tag="winux_dock_drop_preview"):
        self.tag = str(tag)
        self._layer = None
        self._rect = None
        self._inner = None
        self._last_rect = None

    def _ensure_built(self):
        if self._layer and dpg.does_item_exist(self._layer):
            return True
        self._layer = None
        self._rect = None
        self._inner = None
        if dpg.does_item_exist(self.tag):
            try:
                dpg.delete_item(self.tag)
            except Exception:
                pass
        try:
            self._layer = dpg.add_viewport_drawlist(front=True, tag=self.tag)
        except TypeError:
            try:
                self._layer = dpg.add_viewport_drawlist(tag=self.tag)
            except Exception:
                self._layer = None
                return False
        except Exception:
            self._layer = None
            return False
        try:
            self._rect = dpg.draw_rectangle(
                (0, 0), (1, 1), parent=self._layer, color=self.BORDER,
                fill=self.FILL, thickness=2.0, rounding=1.0, show=False)
            self._inner = dpg.draw_rectangle(
                (0, 0), (1, 1), parent=self._layer, color=self.INNER_BORDER,
                fill=self.INNER_FILL, thickness=1.0, rounding=1.0, show=False)
        except Exception:
            self.destroy()
            return False
        return True

    def show(self, x, y, width, height, *, inset=True):
        if not self._ensure_built():
            return False
        x = float(x)
        y = float(y)
        width = max(1.0, float(width))
        height = max(1.0, float(height))
        x2 = x + width
        y2 = y + height
        try:
            dpg.configure_item(
                self._rect, pmin=(x, y), pmax=(x2, y2), show=True)
            if inset and width > 24 and height > 24:
                pad = min(10.0, width * 0.08, height * 0.08)
                dpg.configure_item(
                    self._inner,
                    pmin=(x + pad, y + pad),
                    pmax=(x2 - pad, y2 - pad), show=True)
            else:
                dpg.configure_item(self._inner, show=False)
            self._last_rect = (x, y, width, height)
            return True
        except Exception:
            return False

    def hide(self):
        for item in (self._rect, self._inner):
            if item and dpg.does_item_exist(item):
                try:
                    dpg.configure_item(item, show=False)
                except Exception:
                    pass
        self._last_rect = None

    def destroy(self):
        layer = self._layer
        self._layer = None
        self._rect = None
        self._inner = None
        self._last_rect = None
        if layer and dpg.does_item_exist(layer):
            try:
                dpg.delete_item(layer)
            except Exception:
                pass
