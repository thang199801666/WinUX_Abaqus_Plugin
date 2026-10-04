"""Rendering ownership for :class:`ExplorerListView`.

This module owns Dear PyGui theme/build, row draw-items, pinned-row rendering,
text fitting and tooltip visuals.  Interaction and data semantics remain in
their existing owners.
"""
from __future__ import annotations

import os

from PIL import Image
import dearpygui.dearpygui as dpg

from .interaction_gate import pointer_input_is_blocked
from .qt_style import QtFusionMetrics, QtFusionPalette
from .shared_scroller import add_dpg_scroller_style
from .tooltip import TOOLTIP_DELAY, TOOLTIP_WRAP_WIDTH, tooltip_theme
from .explorer_input_state import _overlay_window_owns_input
from ..platform.windows_icons import ICON_SIZE, WindowsIconRegistry


class ExplorerRenderingMixin:

    def _load_fonts(self):
        fonts = {"body": None, "header": None}
        windir = os.environ.get("WINDIR", "C:\\Windows")
        body_path = os.path.join(windir, "Fonts", "segoeui.ttf")
        bold_candidates = [
            os.path.join(windir, "Fonts", "seguisb.ttf"),
            os.path.join(windir, "Fonts", "segoeuib.ttf"),
            os.path.join(windir, "Fonts", "arialbd.ttf"),
        ]
        try:
            with dpg.font_registry():
                if os.path.exists(body_path):
                    fonts["body"] = dpg.add_font(body_path, self.BODY_FONT_PX)
                for path in bold_candidates:
                    if os.path.exists(path):
                        fonts["header"] = dpg.add_font(path, 16)
                        break
        except Exception:
            pass
        return fonts

    def _rename_text_render_height(self) -> int:
        """Return the actual DPG body-text line height in device pixels.

        Dear ImGui/FreeType and Win32 GDI do not produce the same visible text
        size from the same nominal font value.  The native rename editor treats
        this measured height as a render target and chooses its GDI font size
        to match it.
        """
        font = self._fonts.get("body")
        try:
            _width, height = dpg.get_text_size("Ag", font=font)
            height = int(round(float(height)))
            if height > 0:
                return height
        except Exception:
            pass
        return max(8, int(self.RENAME_FONT_PX))

    @staticmethod
    def _measure_text(text, font=None, fallback_size=15):
        """Measure text safely after validating Dear PyGui's result.

        Dear PyGui may temporarily return zero or invalid dimensions before the
        font atlas has completed its first rendered frame. Invalid measurements
        must not be used for center/right alignment.
        """
        text = str(text or "")

        if not text:
            return 0.0, float(fallback_size)

        try:
            if font is not None and dpg.does_item_exist(font):
                size = dpg.get_text_size(text, font=font)
            else:
                size = dpg.get_text_size(text)

            if size is not None and len(size) >= 2:
                width = float(size[0])
                height = float(size[1])

                # Ignore measurements returned before the font atlas is ready.
                if width > 0.0 and height > 0.0:
                    return width, height

        except Exception:
            pass

        # Temporary approximation used only until the first valid rendered frame.
        # The layout watch will clear cached values and perform an exact relayout.
        average_character_width = float(fallback_size) * 0.52

        return (
            max(1.0, len(text) * average_character_width),
            float(fallback_size),
        )

    def _fit_text(self, text, max_width, font=None, fallback_size=15):
        """Fit text into a cell without caching unreliable initial measurements."""
        text = str(text or "")
        max_width = max(0.0, float(max_width))

        if not text or max_width <= 1.0:
            return ""

        font_ready = False

        try:
            if font is not None and dpg.does_item_exist(font):
                measured = dpg.get_text_size(text, font=font)
            else:
                measured = dpg.get_text_size(text)

            if measured is not None and len(measured) >= 2:
                font_ready = (
                    float(measured[0]) > 0.0
                    and float(measured[1]) > 0.0
                )
        except Exception:
            font_ready = False

        # Only use the cache after Dear PyGui can return real font metrics.
        cache_key = (
            text,
            round(max_width, 2),
            font or 0,
            int(fallback_size),
        )

        if font_ready:
            cached = self._text_fit_cache.get(cache_key)
            if cached is not None:
                return cached

        text_width, _ = self._measure_text(
            text,
            font,
            fallback_size,
        )

        if text_width <= max_width:
            result = text
        else:
            ellipsis_width, _ = self._measure_text(
                self.ELLIPSIS,
                font,
                fallback_size,
            )

            if ellipsis_width > max_width:
                result = ""
            else:
                low = 0
                high = len(text)

                while low < high:
                    middle = (low + high + 1) // 2
                    candidate = text[:middle] + self.ELLIPSIS

                    candidate_width, _ = self._measure_text(
                        candidate,
                        font,
                        fallback_size,
                    )

                    if candidate_width <= max_width:
                        low = middle
                    else:
                        high = middle - 1

                result = text[:low] + self.ELLIPSIS

        if font_ready:
            if len(self._text_fit_cache) > 12000:
                self._text_fit_cache.clear()

            self._text_fit_cache[cache_key] = result

        return result

    def _bind_font(self, item, font):
        if font and dpg.does_item_exist(item):
            try:
                dpg.bind_item_font(item, font)
            except Exception:
                pass

    def _build_theme(self, replace=False):
        if replace:
            for old in (
                getattr(self, "theme_pane", None),
                getattr(self, "theme_popup", None),
                getattr(self, "_context_menu_button_theme", None),
                getattr(self, "_context_menu_keyboard_button_theme", None),
                getattr(self, "_context_menu_disabled_button_theme", None),
                getattr(self, "_context_menu_disabled_icon_theme", None),
                getattr(self, "_context_menu_arrow_theme", None),
                getattr(self, "_context_menu_disabled_arrow_theme", None),
            ):
                if old and dpg.does_item_exist(old): dpg.delete_item(old)
        cfg = self.theme_config
        p = QtFusionPalette
        m = QtFusionMetrics
        with dpg.theme() as self.theme_pane:
            with dpg.theme_component(dpg.mvAll):
                dpg.add_theme_color(dpg.mvThemeCol_ChildBg, cfg["background"])
                dpg.add_theme_color(dpg.mvThemeCol_WindowBg, cfg["background"])
                dpg.add_theme_color(dpg.mvThemeCol_Text, cfg["text"])
                dpg.add_theme_color(dpg.mvThemeCol_Border, cfg["border"])
                add_dpg_scroller_style(dpg)
                dpg.add_theme_style(dpg.mvStyleVar_WindowPadding, 0, 0)
                dpg.add_theme_style(dpg.mvStyleVar_ItemSpacing, 0, 0)
        with dpg.theme() as self.theme_popup:
            with dpg.theme_component(dpg.mvAll):
                # Compact Qt/Fusion QMenu surface shared with dialogs/widgets.
                dpg.add_theme_color(dpg.mvThemeCol_WindowBg, p.MENU)
                dpg.add_theme_color(dpg.mvThemeCol_PopupBg, p.MENU)
                dpg.add_theme_color(dpg.mvThemeCol_Text, p.TEXT)
                dpg.add_theme_color(dpg.mvThemeCol_TextDisabled, p.TEXT_DISABLED)
                dpg.add_theme_color(dpg.mvThemeCol_Border, p.BORDER)
                dpg.add_theme_color(dpg.mvThemeCol_Separator, p.BORDER_LIGHT)
                dpg.add_theme_style(dpg.mvStyleVar_WindowPadding, 4, 4)
                dpg.add_theme_style(dpg.mvStyleVar_ItemSpacing, 0, 1)
                dpg.add_theme_style(dpg.mvStyleVar_WindowRounding, m.POPUP_ROUNDING)
                dpg.add_theme_style(dpg.mvStyleVar_PopupRounding, m.POPUP_ROUNDING)
                dpg.add_theme_style(dpg.mvStyleVar_WindowBorderSize, 1)

        with dpg.theme() as self._context_menu_button_theme:
            with dpg.theme_component(dpg.mvButton):
                dpg.add_theme_color(dpg.mvThemeCol_Button, (0, 0, 0, 0))
                dpg.add_theme_color(dpg.mvThemeCol_ButtonHovered, p.MENU_HOVER)
                dpg.add_theme_color(dpg.mvThemeCol_ButtonActive, p.MENU_ACTIVE)
                dpg.add_theme_color(dpg.mvThemeCol_Text, p.TEXT)
                dpg.add_theme_color(dpg.mvThemeCol_Border, (0, 0, 0, 0))
                dpg.add_theme_style(dpg.mvStyleVar_FramePadding, 8, 4)
                dpg.add_theme_style(dpg.mvStyleVar_FrameRounding, 0)
                dpg.add_theme_style(dpg.mvStyleVar_FrameBorderSize, 0)
                dpg.add_theme_style(dpg.mvStyleVar_ButtonTextAlign, 0.0, 0.5)

        with dpg.theme() as self._context_menu_keyboard_button_theme:
            with dpg.theme_component(dpg.mvButton):
                dpg.add_theme_color(dpg.mvThemeCol_Button, p.MENU_HOVER)
                dpg.add_theme_color(dpg.mvThemeCol_ButtonHovered, p.MENU_HOVER)
                dpg.add_theme_color(dpg.mvThemeCol_ButtonActive, p.MENU_ACTIVE)
                dpg.add_theme_color(dpg.mvThemeCol_Text, p.TEXT)
                dpg.add_theme_color(dpg.mvThemeCol_Border, p.FOCUS)
                dpg.add_theme_style(dpg.mvStyleVar_FramePadding, 8, 4)
                dpg.add_theme_style(dpg.mvStyleVar_FrameRounding, 0)
                dpg.add_theme_style(dpg.mvStyleVar_FrameBorderSize, 1)
                dpg.add_theme_style(dpg.mvStyleVar_ButtonTextAlign, 0.0, 0.5)

        with dpg.theme() as self._context_menu_icon_theme:
            with dpg.theme_component(dpg.mvImageButton):
                dpg.add_theme_color(dpg.mvThemeCol_Button, (0, 0, 0, 0))
                dpg.add_theme_color(dpg.mvThemeCol_ButtonHovered, p.MENU_HOVER)
                dpg.add_theme_color(dpg.mvThemeCol_ButtonActive, p.MENU_ACTIVE)
                dpg.add_theme_color(dpg.mvThemeCol_Border, (0, 0, 0, 0))
                dpg.add_theme_style(dpg.mvStyleVar_FramePadding, 6, 6)
                dpg.add_theme_style(dpg.mvStyleVar_FrameRounding, 0)
                dpg.add_theme_style(dpg.mvStyleVar_FrameBorderSize, 0)

        with dpg.theme() as self._context_menu_arrow_theme:
            with dpg.theme_component(dpg.mvButton):
                dpg.add_theme_color(dpg.mvThemeCol_Button, (0, 0, 0, 0))
                dpg.add_theme_color(dpg.mvThemeCol_ButtonHovered, p.MENU_HOVER)
                dpg.add_theme_color(dpg.mvThemeCol_ButtonActive, p.MENU_ACTIVE)
                dpg.add_theme_color(dpg.mvThemeCol_Text, p.TEXT)
                dpg.add_theme_color(dpg.mvThemeCol_Border, (0, 0, 0, 0))
                dpg.add_theme_style(dpg.mvStyleVar_FramePadding, 0, 4)
                dpg.add_theme_style(dpg.mvStyleVar_FrameRounding, 0)
                dpg.add_theme_style(dpg.mvStyleVar_FrameBorderSize, 0)
                dpg.add_theme_style(dpg.mvStyleVar_ButtonTextAlign, 0.5, 0.5)

        with dpg.theme() as self._context_menu_disabled_arrow_theme:
            with dpg.theme_component(dpg.mvButton):
                dpg.add_theme_color(dpg.mvThemeCol_Button, (0, 0, 0, 0))
                dpg.add_theme_color(dpg.mvThemeCol_ButtonHovered, (0, 0, 0, 0))
                dpg.add_theme_color(dpg.mvThemeCol_ButtonActive, (0, 0, 0, 0))
                dpg.add_theme_color(dpg.mvThemeCol_Text, p.TEXT_DISABLED)
                dpg.add_theme_color(dpg.mvThemeCol_Border, (0, 0, 0, 0))
                dpg.add_theme_style(dpg.mvStyleVar_FramePadding, 0, 4)
                dpg.add_theme_style(dpg.mvStyleVar_FrameRounding, 0)
                dpg.add_theme_style(dpg.mvStyleVar_FrameBorderSize, 0)
                dpg.add_theme_style(dpg.mvStyleVar_ButtonTextAlign, 0.5, 0.5)

        # Disabled menu entries keep the exact same layout as enabled entries.
        # Only the foreground/icon is muted and no hover/active fill is shown.
        with dpg.theme() as self._context_menu_disabled_button_theme:
            with dpg.theme_component(dpg.mvButton):
                dpg.add_theme_color(dpg.mvThemeCol_Button, (0, 0, 0, 0))
                dpg.add_theme_color(dpg.mvThemeCol_ButtonHovered, (0, 0, 0, 0))
                dpg.add_theme_color(dpg.mvThemeCol_ButtonActive, (0, 0, 0, 0))
                dpg.add_theme_color(dpg.mvThemeCol_Text, p.TEXT_DISABLED)
                dpg.add_theme_color(dpg.mvThemeCol_TextDisabled, p.TEXT_DISABLED)
                dpg.add_theme_color(dpg.mvThemeCol_Border, (0, 0, 0, 0))
                dpg.add_theme_style(dpg.mvStyleVar_FramePadding, 8, 4)
                dpg.add_theme_style(dpg.mvStyleVar_FrameRounding, 0)
                dpg.add_theme_style(dpg.mvStyleVar_FrameBorderSize, 0)
                dpg.add_theme_style(dpg.mvStyleVar_ButtonTextAlign, 0.0, 0.5)

        with dpg.theme() as self._context_menu_disabled_icon_theme:
            with dpg.theme_component(dpg.mvImageButton):
                dpg.add_theme_color(dpg.mvThemeCol_Button, (0, 0, 0, 0))
                dpg.add_theme_color(dpg.mvThemeCol_ButtonHovered, (0, 0, 0, 0))
                dpg.add_theme_color(dpg.mvThemeCol_ButtonActive, (0, 0, 0, 0))
                dpg.add_theme_color(dpg.mvThemeCol_Border, (0, 0, 0, 0))
                dpg.add_theme_style(dpg.mvStyleVar_Alpha, 0.38)
                dpg.add_theme_style(dpg.mvStyleVar_FramePadding, 6, 6)
                dpg.add_theme_style(dpg.mvStyleVar_FrameRounding, 0)
                dpg.add_theme_style(dpg.mvStyleVar_FrameBorderSize, 0)

    def _build_ui(self):
        with dpg.group(parent=self.parent, tag=f"{self.uid}_root"):
            pane_height = self.height if self.height == -1 else max(self.height - 26, 10)
            self.window_tag = f"{self.uid}_pane"
            # The outer pane is only a fixed clipping/layout container.  It
            # must never own a scrollbar; otherwise Dear PyGui renders one
            # scrollbar for this pane and another for ``body_window``.
            # Scrolling is exclusively handled by ``body_window`` below.
            with dpg.child_window(
                width=self.width, height=pane_height, tag=self.window_tag,
                border=True, no_scrollbar=True, no_scroll_with_mouse=True,
            ):
                self.header_canvas = dpg.add_drawlist(width=-1, height=self.HEADER_HEIGHT, tag=f"{self.uid}_header")
                self.pinned_tooltip_anchor = f"{self.uid}_pinned_tooltip_anchor"
                # Groups expose the canvas hover as an ordinary ImGui item.
                # Drawlists cannot be tooltip anchors directly in DPG 2.x.
                with dpg.group(tag=self.pinned_tooltip_anchor):
                    self.pinned_canvas = dpg.add_drawlist(
                        width=-1, height=self.ROW_HEIGHT, tag=f"{self.uid}_pinned", show=False)
                self._pinned_item_tooltip = self._create_item_tooltip(
                    self.pinned_tooltip_anchor, "pinned")
                self.body_window = f"{self.uid}_body"
                with dpg.child_window(
                        width=-1, height=-1, tag=self.body_window,
                        border=False,
                        horizontal_scrollbar=self.horizontal_scrollbar):
                    self.body_tooltip_anchor = f"{self.uid}_body_tooltip_anchor"
                    with dpg.group(tag=self.body_tooltip_anchor):
                        self.body_canvas = dpg.add_drawlist(width=-1, height=self.ROW_HEIGHT, tag=f"{self.uid}_body_canvas")
                    self._body_item_tooltip = self._create_item_tooltip(
                        self.body_tooltip_anchor, "body")
            dpg.bind_item_theme(self.window_tag, self.theme_pane)
            dpg.bind_item_theme(self.body_window, self.theme_pane)
            with dpg.group(horizontal=True, show=self.show_status_bar):
                self.status_items_tag = f"{self.uid}_status_items"
                self.status_sel_tag = f"{self.uid}_status_sel"
                dpg.add_text("0 items", tag=self.status_items_tag, color=self.theme_config["status_text"])
                dpg.add_text("", tag=self.status_sel_tag, color=self.theme_config["status_text"])

    def _create_item_tooltip(self, parent, suffix):
        """Create one reusable tooltip for a drawlist-backed row region."""
        tooltip_tag = f"{self.uid}_{suffix}_item_tooltip"
        title_tag = f"{tooltip_tag}_title"
        details_tag = f"{tooltip_tag}_details"
        path_tag = f"{tooltip_tag}_path"
        with dpg.tooltip(
            parent,
            tag=tooltip_tag,
            show=False,
            delay=TOOLTIP_DELAY,
            hide_on_activity=True,
        ):
            dpg.add_text(
                " ", tag=title_tag, color=QtFusionPalette.TEXT,
                wrap=TOOLTIP_WRAP_WIDTH,
            )
            dpg.add_separator()
            dpg.add_text(
                " ", tag=details_tag, color=QtFusionPalette.TEXT_MUTED,
                wrap=TOOLTIP_WRAP_WIDTH,
            )
            dpg.add_text(
                " ", tag=path_tag, color=QtFusionPalette.HIGHLIGHT,
                wrap=TOOLTIP_WRAP_WIDTH,
            )
        dpg.bind_item_theme(tooltip_tag, tooltip_theme())
        title_font = self._fonts.get("header")
        if title_font is not None:
            try:
                dpg.bind_item_font(title_tag, title_font)
            except Exception:
                pass
        return {
            "tag": tooltip_tag,
            "title": title_tag,
            "details": details_tag,
            "path": path_tag,
            "item_id": None,
        }

    def _item_tooltip_content(self, item):
        """Return title, metadata and full path for one ListView item."""
        title = str(item.name or "")
        if item.is_dir and title == "..":
            title = "Parent folder"

        details = []
        for column in self._visible_columns():
            key = column.get("key")
            if key == "name":
                continue
            value = self._display_cell_value(item, key)
            if value:
                details.append("{}: {}".format(column.get("label", key), value))

        # Custom/simple ListViews may expose only a Name column. Preserve a
        # useful type line in that case without duplicating an existing field.
        if not any(str(line).casefold().startswith("type:") for line in details):
            item_type = str(getattr(item, "item_type", "") or "")
            if item_type:
                details.insert(0, "Type: {}".format(item_type))

        full_path = item.data.get("path") or item.path
        full_path = str(full_path or "")
        if full_path == str(item.name or ""):
            full_path = ""
        return title, "\n".join(details), full_path

    @staticmethod
    def _hide_tooltip_parts(parts):
        if not parts or parts.get("item_id") is None:
            return
        tag = parts.get("tag")
        if tag and dpg.does_item_exist(tag):
            dpg.configure_item(tag, show=False)
        parts["item_id"] = None

    def _show_tooltip_parts(self, parts, item):
        if not parts or item is None:
            self._hide_tooltip_parts(parts)
            return
        tag = parts.get("tag")
        if not tag or not dpg.does_item_exist(tag):
            return
        item_id = id(item)
        if parts.get("item_id") == item_id:
            return

        title, details, full_path = self._item_tooltip_content(item)
        dpg.configure_item(tag, show=False)
        dpg.set_value(parts["title"], title or " ")
        dpg.set_value(parts["details"], details or " ")
        dpg.set_value(parts["path"], full_path or " ")
        dpg.configure_item(parts["details"], show=bool(details))
        dpg.configure_item(parts["path"], show=bool(full_path))
        dpg.configure_item(tag, show=True)
        parts["item_id"] = item_id

    def _hide_item_tooltips(self):
        self._hide_tooltip_parts(getattr(self, "_body_item_tooltip", None))
        self._hide_tooltip_parts(getattr(self, "_pinned_item_tooltip", None))

    def _resolve_icon_texture(self, icon):
        if icon is None:
            return None
        if not isinstance(icon, (str, os.PathLike)) or dpg.does_item_exist(icon):
            return icon
        path = os.path.abspath(os.path.expanduser(os.fspath(icon)))
        cached = self._custom_textures.get(path)
        if cached and dpg.does_item_exist(cached): return cached
        if not os.path.isfile(path): return None
        image = Image.open(path).convert("RGBA")
        texture = WindowsIconRegistry._add_texture(image, f"{self.uid}_custom_icon_{len(self._custom_textures)}")
        self._custom_textures[path] = texture
        return texture

    def _create_body_row(self, index):
        """Create one reusable body-row primitive set for *index*."""
        y0 = float(index) * self.ROW_HEIGHT
        background = dpg.draw_rectangle(
            (0.5, y0 + 0.5), (1, y0 + self.ROW_HEIGHT - 0.5),
            parent=self.body_canvas, fill=(0, 0, 0, 0), color=(0, 0, 0, 0),
            thickness=0.0,
            rounding=float(self.theme_config.get("row_rounding", 1.0)),
        )
        bottom = dpg.draw_line(
            (0, y0 + self.ROW_HEIGHT - 0.5),
            (1, y0 + self.ROW_HEIGHT - 0.5),
            parent=self.body_canvas, color=self.theme_config["row_line"],
            thickness=1, show=bool(self.theme_config.get("show_row_lines", True)),
        )
        texts = {}
        icon_tag = None
        for column in self._visible_columns():
            key = column["key"]
            text_tag = dpg.draw_text(
                (0, 0), "", parent=self.body_canvas,
                color=self.theme_config["text"], size=15,
            )
            self._bind_font(text_tag, self._fonts.get("body"))
            texts[key] = text_tag
            if key == "name":
                # A valid texture is assigned immediately by _bind_body_row().
                texture = WindowsIconRegistry.get_icon("", is_dir=False)
                icon_tag = dpg.draw_image(
                    texture, (0, 0), (ICON_SIZE, ICON_SIZE), parent=self.body_canvas
                )
        row = {
            "index": int(index),
            "background": background,
            "bottom": bottom,
            "texts": texts,
            "icon": icon_tag,
            "values": {},
            "icon_texture": None,
            "visual_signature": None,
            "item_object_id": None,
        }
        self._bind_body_row(row, index)
        return row

    def _bind_body_row(self, row, index, preserve_geometry=False):
        """Bind one rendered primitive set to a logical item index."""
        index = int(index)
        if not (0 <= index < len(self.items)):
            return row
        item = self.items[index]
        previous_index = row.get("index")
        previous_object_id = row.get("item_object_id")
        row["index"] = index
        row["item_object_id"] = id(item)
        if previous_index != index or previous_object_id != id(item):
            row["visual_signature"] = None

        cached_values = row.setdefault("values", {})
        visible_keys = {column["key"] for column in self._visible_columns()}
        for stale_key in tuple(cached_values):
            if stale_key not in visible_keys:
                cached_values.pop(stale_key, None)

        for column in self._visible_columns():
            key = column["key"]
            value = self._display_cell_value(item, key)
            text_tag = row.get("texts", {}).get(key)
            if cached_values.get(key) != value:
                cached_values[key] = value
                if text_tag and dpg.does_item_exist(text_tag):
                    dpg.configure_item(text_tag, text=value)

        icon = row.get("icon")
        if icon and dpg.does_item_exist(icon):
            texture = self._item_icons.get(id(item)) or WindowsIconRegistry.get_icon(
                item.extension, is_dir=item.is_dir
            )
            if row.get("icon_texture") != texture:
                row["icon_texture"] = texture
                try:
                    dpg.configure_item(icon, texture_tag=texture)
                except Exception:
                    pass
        return row

    def _destroy_body_row(self, row):
        """Delete the native draw primitives owned by one rendered row slot."""
        tags = [row.get("background"), row.get("bottom"), row.get("icon")]
        tags.extend(row.get("texts", {}).values())
        for tag in tags:
            if tag and dpg.does_item_exist(tag):
                try:
                    dpg.delete_item(tag)
                except Exception:
                    pass

    def _rebuild_body_rows(self):
        """Replace directory rows without rebuilding the stable header."""
        self._text_fit_cache.clear()
        if not dpg.does_item_exist(self.body_canvas):
            return
        dpg.delete_item(self.body_canvas, children_only=True)
        self._reset_row_registry()
        self._sync_virtual_rows(force=True)
        self._layout_all()

    def _rebuild_draw_items(self):
        self._text_fit_cache.clear()
        self._ensure_column_widths()
        if dpg.does_item_exist(self.header_canvas):
            dpg.delete_item(self.header_canvas, children_only=True)
        if dpg.does_item_exist(self.body_canvas):
            dpg.delete_item(self.body_canvas, children_only=True)
        self._header_items = {}
        self._header_top_line = None
        self._header_bottom_line = None
        self._reset_row_registry()
        dpg.draw_rectangle((0, 0), (max(1.0, self._available_width()), self.HEADER_HEIGHT),
                           parent=self.header_canvas, fill=self.theme_config["header_bg"],
                           color=self.theme_config["header_bg"], thickness=0)

        for column in self._visible_columns():
            key = column["key"]
            background_tag = dpg.draw_rectangle(
                (0, 0), (1, self.HEADER_HEIGHT), parent=self.header_canvas,
                fill=(0, 0, 0, 0), color=(0, 0, 0, 0), thickness=0.0,
            )
            label_tag = dpg.draw_text((0, 0), column["label"], parent=self.header_canvas, color=self.theme_config["header_text"], size=16)
            indicator_tag = dpg.draw_triangle(
                (0, 0), (0, 0), (0, 0), parent=self.header_canvas,
                color=self.theme_config["header_text"],
                fill=self.theme_config["header_text"], show=False,
            )
            separator_tag = dpg.draw_line(
                (0, 0), (0, self.HEADER_HEIGHT), parent=self.header_canvas,
                color=self.theme_config["separator"], thickness=1,
                show=self.show_column_separators,
            )
            self._bind_font(label_tag, self._fonts.get("header"))
            self._header_items[key] = {
                "background": background_tag,
                "label": label_tag,
                "indicator": indicator_tag,
                "separator": separator_tag,
            }

        self._header_top_line = dpg.draw_line(
            (0, 0.5), (1, 0.5), parent=self.header_canvas,
            color=self.theme_config.get("header_top_line", self.theme_config["header_bg"]),
            thickness=1)
        self._header_bottom_line = dpg.draw_line(
            (0, self.HEADER_HEIGHT - 0.5), (1, self.HEADER_HEIGHT - 0.5),
            parent=self.header_canvas,
            color=self.theme_config.get("header_bottom_line", self.theme_config["border"]),
            thickness=1)

        self._rebuild_pinned_row()
        self._sync_virtual_rows(force=True)
        self._layout_all()

    def _rebuild_pinned_row(self):
        if not hasattr(self, "pinned_canvas") or not dpg.does_item_exist(self.pinned_canvas):
            return
        dpg.delete_item(self.pinned_canvas, children_only=True)
        self._pinned_background = None
        self._pinned_texts = {}
        self._pinned_icon = None
        item = self._pinned_item
        dpg.configure_item(self.pinned_canvas, show=bool(item), height=self.ROW_HEIGHT)
        if item is None:
            return
        self._pinned_background = dpg.draw_rectangle(
            (0.5, 0.5), (2, self.ROW_HEIGHT - 0.5), parent=self.pinned_canvas,
            fill=(0, 0, 0, 0), color=(0, 0, 0, 0), thickness=0.0,
            rounding=float(self.theme_config.get("row_rounding", 1.0)))
        dpg.draw_line((0, self.ROW_HEIGHT - .5), (1, self.ROW_HEIGHT - .5),
                      parent=self.pinned_canvas, color=self.theme_config["row_line"], thickness=1,
                                      show=bool(self.theme_config.get("show_row_lines", True)))
        for column in self._visible_columns():
            key = column["key"]
            value = self._display_cell_value(item, key)
            text_tag = dpg.draw_text((0, 0), value, parent=self.pinned_canvas,
                                     color=self.theme_config["text"], size=15)
            self._bind_font(text_tag, self._fonts.get("body"))
            self._pinned_texts[key] = text_tag
            if key == "name":
                texture = self._item_icons.get(id(item)) or WindowsIconRegistry.get_icon(
                    item.extension, is_dir=item.is_dir)
                self._pinned_icon = dpg.draw_image(
                    texture, (0, 0), (ICON_SIZE, ICON_SIZE), parent=self.pinned_canvas)
        self._layout_pinned_row()

    def _layout_pinned_row(self):
        item = self._pinned_item
        if item is None or not hasattr(self, "pinned_canvas") or not dpg.does_item_exist(self.pinned_canvas):
            return
        geometry = self._column_geometry()
        total_width = sum(width for _, width in geometry.values())
        visible_width = min(total_width, self._available_width())
        dpg.configure_item(self.pinned_canvas, width=max(1, int(round(total_width))), height=self.ROW_HEIGHT)
        if self._pinned_background and dpg.does_item_exist(self._pinned_background):
            is_drop_target = bool(
                (self._item_drag_active and self._drop_target_pinned)
                or self._external_drop_target_pinned
            )
            if is_drop_target:
                fill = self.theme_config["drop_fill"]
                border = self.theme_config["drop_border"]
                thickness = 2.0
            elif self._pinned_hovered:
                fill = self.theme_config["hover_fill"]
                border = (0, 0, 0, 0)
                thickness = 0.0
            else:
                fill = (0, 0, 0, 0)
                border = (0, 0, 0, 0)
                thickness = 0.0
            dpg.configure_item(self._pinned_background, pmin=(0.5, 0.5),
                               pmax=(max(1.0, visible_width - 0.5), self.ROW_HEIGHT - 0.5),
                               fill=fill, color=border, thickness=thickness)
        for column in self._visible_columns():
            key = column["key"]
            tag = self._pinned_texts.get(key)
            if not tag or not dpg.does_item_exist(tag):
                continue
            x, width = geometry[key]
            value = self._display_cell_value(item, key)
            left_pad = 30.0 if key == "name" else 8.0
            fitted = self._fit_text(value, max(0.0, width-left_pad-6.0), self._fonts.get("body"), 15)
            _, th = self._measure_text(fitted, self._fonts.get("body"), 15)
            dpg.configure_item(tag, text=fitted, pos=(round(x+left_pad), round((self.ROW_HEIGHT-th)*.5)))
            if key == "name" and self._pinned_icon and dpg.does_item_exist(self._pinned_icon):
                iy = round((self.ROW_HEIGHT-ICON_SIZE)*.5)
                dpg.configure_item(self._pinned_icon, pmin=(round(x+7), iy), pmax=(round(x+7+ICON_SIZE), iy+ICON_SIZE))

    def _activate_pinned_item(self):
        if self._pinned_item is None:
            return
        if self._pinned_command is not None:
            self._pinned_command()
        else:
            self.activate_item(self._pinned_item)

    def _row_visual_style(self, index):
        """Return QAbstractItemView-like fill/border colors for one row."""
        selected = index in self.selected
        hovered = index == self.hover_index
        current = index == self._current_index
        cfg = self.theme_config
        focus_border = cfg.get("focus_border", cfg.get("selected_border"))

        if ((self._item_drag_active and index == self._drop_target_index)
                or index == self._external_drop_target_index):
            return cfg["drop_fill"], cfg["drop_border"], 2.0
        if selected and hovered:
            return (
                cfg["selected_hover_fill"],
                focus_border if self._has_focus and current else (0, 0, 0, 0),
                1.0 if self._has_focus and current else 0.0,
            )
        if selected and self._has_focus:
            return (
                cfg["selected_fill"],
                focus_border if current else (0, 0, 0, 0),
                1.0 if current else 0.0,
            )
        if selected:
            return (
                cfg.get("inactive_selected_fill", cfg["selected_fill"]),
                (0, 0, 0, 0),
                0.0,
            )
        if current and self._has_focus:
            # Ctrl+Arrow moves the current index without changing selection.
            # Qt still exposes the keyboard focus row with a thin outline.
            base_fill = self.items[index].data.get("row_fill")
            if not base_fill and self._alternating_row_colors and index % 2:
                base_fill = QtFusionPalette.ALTERNATE_BASE
            return base_fill or (0, 0, 0, 0), focus_border, 1.0
        if hovered:
            return cfg["hover_fill"], (0, 0, 0, 0), 0.0
        base_fill = self.items[index].data.get("row_fill")
        if not base_fill and self._alternating_row_colors and index % 2:
            base_fill = QtFusionPalette.ALTERNATE_BASE
        if base_fill:
            return base_fill, (0, 0, 0, 0), 0.0
        return (0, 0, 0, 0), (0, 0, 0, 0), 0.0

    def _update_row_visual(self, index):
        if index is None or not (0 <= int(index) < len(self.items)):
            return
        row = self._row_for_index(index)
        if row is None:
            return
        background = row.get("background")
        if not background or not dpg.does_item_exist(background):
            return
        fill, border, thickness = self._row_visual_style(index)

        # WinSCP/native details views invert the foreground for the active
        # selection and return to normal dark text for an inactive panel.
        selected = index in self.selected
        if selected and self._has_focus:
            text_color = self.theme_config.get("selected_text", self.theme_config["text"])
        elif selected:
            text_color = self.theme_config.get("inactive_selected_text", self.theme_config["text"])
        else:
            text_color = self.theme_config["text"]

        # Selection and hover paths can call this for every row many times per
        # gesture.  Preserve the exact visual semantics while avoiding native
        # Dear PyGui configure calls when the rendered style is unchanged.
        signature = (fill, border, float(thickness), text_color)
        if row.get("visual_signature") == signature:
            return
        row["visual_signature"] = signature

        dpg.configure_item(
            background,
            fill=fill,
            color=border,
            thickness=thickness,
        )
        for text_tag in row.get("texts", {}).values():
            if text_tag and dpg.does_item_exist(text_tag):
                dpg.configure_item(text_tag, color=text_color)

    def _update_selection_draws(self):
        for row in self._row_items:
            self._update_row_visual(row["index"])

    def _row_content_width(self):
        """Return the horizontal extent occupied by visible data columns."""
        return sum(
            float(self._column_widths.get(column["key"], self.MIN_COLUMN_WIDTH))
            for column in self._visible_columns()
        )

    def _update_hover_state(self):
        if pointer_input_is_blocked(self):
            self._hide_item_tooltips()
            self._clear_hover()
            return
        if self._rename_active:
            self._hide_item_tooltips()
            return
        if _overlay_window_owns_input():
            self._hide_item_tooltips()
            self._clear_hover()
            return
        new_hover = None if self._mouse_down and (self._rubber_active or self._item_drag_active) else self._row_at_mouse()
        if new_hover == self.hover_index:
            if new_hover is not None and 0 <= new_hover < len(self.items):
                self._show_tooltip_parts(
                    getattr(self, "_body_item_tooltip", None),
                    self.items[new_hover],
                )
            return
        old_hover = self.hover_index
        self.hover_index = new_hover
        if new_hover is None:
            self._hide_tooltip_parts(
                getattr(self, "_body_item_tooltip", None))
        else:
            self._show_tooltip_parts(
                getattr(self, "_body_item_tooltip", None),
                self.items[new_hover],
            )
        self._update_row_visual(old_hover)
        self._update_row_visual(new_hover)
