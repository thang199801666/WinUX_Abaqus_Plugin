"""Rendering ownership for :class:`ExplorerListView`.

This module owns Dear PyGui theme/build, row draw-items, pinned-row rendering,
text fitting and tooltip visuals.  Interaction and data semantics remain in
their existing owners.
"""
from __future__ import annotations

import os

from PIL import Image
from DearUIQt.input_gate import pointer_input_is_blocked
from DearUIQt.gui import QPainter, QFontDatabase, QFontMetrics, QtFusionMetrics, QtFusionPalette
from DearUIQt.widgets import QCanvas, QLabel, QFrame, QRetainedItem
from DearUIQt.tooltip import TOOLTIP_DELAY, TooltipHoverDelay
from DearUIQt.core import QTimer
from DearUIQt.themes import (
    menu_button_theme, menu_image_button_theme, menu_surface_theme,
    viewport_surface_theme,
)
from DearUIQt.layouts import QVBoxLayout, QHBoxLayout
from .input_state import _overlay_window_owns_input
from .item_model import stable_item_identity
from .tooltip_overlay import ExplorerTooltipOverlay
from ....platform.windows_icons import ICON_SIZE, WindowsIconRegistry


class ExplorerRenderingMixin:

    def _load_fonts(self, preferences=None):
        fonts = {"body": None, "header": None}
        try:
            from ...appearance import configure_ui_context
            from ....preferences.general import GeneralPreferences
            values = GeneralPreferences().load() if preferences is None else dict(preferences)
            family = values.get("ui_font_family", GeneralPreferences.DEFAULT_UI_FONT_FAMILY)
            size = int(values.get("ui_font_size", GeneralPreferences.DEFAULT_UI_FONT_SIZE))
            self._font_family = family
            holder = type("_ExplorerTypographyHost", (), {})()
            if configure_ui_context(holder, values, load_terminal=False):
                self._font_database = getattr(holder, "_font_database", None)
                fonts["body"] = getattr(holder, "body_qfont", None)
                # Explorer column headers are intentionally one pixel smaller
                # than body rows, matching the previous Segoe UI 15/14 layout.
                _family, _body_path, heading_path = __import__(
                    'WinUx.preferences.appearance', fromlist=['resolve_ui_font_paths']
                ).resolve_ui_font_paths(family)
                if heading_path is not None and self._font_database is not None:
                    fonts["header"] = self._font_database.addApplicationFont(
                        heading_path, max(10, size - 1))
                if fonts["header"] is None:
                    fonts["header"] = fonts["body"]
                self.BODY_FONT_PX = size
                self.RENAME_FONT_PX = size
                return fonts
        except Exception:
            self._font_database = None
        self._font_family = "Segoe UI"
        return fonts

    def apply_typography(self, preferences=None):
        """Reload and rebind Explorer fonts without rebuilding the ListView.

        Explorer draw text uses explicit font bindings, so changing the global
        application font is not enough for existing rows/header items.  This
        method swaps those bindings in-place and preserves selection, scroll,
        hover and virtualization state.
        """
        old_database = getattr(self, "_font_database", None)
        fonts = self._load_fonts(preferences)
        if not fonts.get("body"):
            return False
        self._fonts = fonts

        for row in tuple(getattr(self, "_row_items", ())):
            for text_tag in row.get("texts", {}).values():
                self._bind_font(text_tag, fonts.get("body"))
        for header in getattr(self, "_header_items", {}).values():
            self._bind_font(header.get("label"), fonts.get("header"))
        for text_tag in getattr(self, "_pinned_texts", {}).values():
            self._bind_font(text_tag, fonts.get("body"))

        drag_preview = getattr(self, "_drag_preview", None)
        if drag_preview is not None:
            try:
                drag_preview.body_font = fonts.get("body")
                drag_preview._metrics = QFontMetrics(fonts.get("body"))
            except Exception:
                pass

        for name in ("_body_item_tooltip", "_pinned_item_tooltip"):
            tooltip = getattr(self, name, None)
            if tooltip is not None:
                try:
                    tooltip.body_font = fonts.get("body")
                    tooltip.header_font = fonts.get("header")
                    tooltip._body_metrics = QFontMetrics(fonts.get("body"))
                except Exception:
                    pass

        self._text_fit_cache.clear()
        try:
            self._layout_all()
        except Exception:
            pass

        # Retain the previous registry until all explicit DPG bindings have
        # been replaced.  Deleting it eagerly can invalidate a font id that is
        # still referenced by a retained draw command during this frame.
        if old_database is not None and old_database is not getattr(self, "_font_database", None):
            retired = getattr(self, "_retired_font_databases", None)
            if retired is None:
                retired = self._retired_font_databases = []
            retired.append(old_database)
            while len(retired) > 2:
                stale = retired.pop(0)
                try:
                    stale.delete()
                except Exception:
                    pass
        return True

    def _retained_item(self, tag):
        """Return a cached DearUIQt facade for a renderer-retained item id."""
        if tag is None:
            return None
        cache = getattr(self, "_retained_item_cache", None)
        if cache is None:
            cache = self._retained_item_cache = {}
        elif len(cache) >= 4096:
            # QRetainedItem facades do not own the renderer items. Rebuilds can
            # generate fresh draw tags indefinitely, so drop stale facades in
            # one cheap sweep instead of retaining every historical tag.
            cache.clear()
        item = cache.get(tag)
        if item is None:
            item = cache[tag] = QRetainedItem(tag)
        return item

    def _rename_text_render_height(self) -> int:
        """Return the actual DPG body-text line height in device pixels.

        Dear ImGui/FreeType and Win32 GDI do not produce the same visible text
        size from the same nominal font value.  The native rename editor treats
        this measured height as a render target and chooses its GDI font size
        to match it.
        """
        font = self._fonts.get("body")
        try:
            height = QFontMetrics(font).height()
            if height > 0:
                return int(height)
        except Exception:
            pass
        return max(8, int(self.RENAME_FONT_PX))

    @staticmethod
    def _measure_text(text, font=None, fallback_size=15):
        """Measure text through DearUIQt, with a stable pre-atlas fallback."""
        text = str(text or "")
        if not text:
            return 0.0, float(fallback_size)
        try:
            size = QFontMetrics(font).size(text)
            width, height = float(size.width()), float(size.height())
            if width > 0.0 and height > 0.0:
                return width, height
        except Exception:
            pass
        average_character_width = float(fallback_size) * 0.52
        return max(1.0, len(text) * average_character_width), float(fallback_size)

    def _fit_text(self, text, max_width, font=None, fallback_size=15):
        """Fit text into a cell without caching unreliable initial measurements."""
        text = str(text or "")
        max_width = max(0.0, float(max_width))

        if not text or max_width <= 1.0:
            return ""

        try:
            measured = QFontMetrics(font).size(text)
            font_ready = measured.width() > 0 and measured.height() > 0
        except Exception:
            font_ready = False

        # Only use the cache after Dear PyGui can return real font metrics.
        cache_key = (
            text,
            round(max_width, 2),
            getattr(font, "nativeId", lambda: font or 0)(),
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
        retained = self._retained_item(item)
        if font and retained is not None and retained.exists():
            retained.setFont(font)

    def _build_theme(self, replace=False):
        """Build Explorer chrome through DearUIQt theme abstractions.

        WinUx owns visual intent only. Renderer constants and native theme
        construction belong to DearUIQt, keeping this feature portable across
        renderer implementations.
        """
        if replace:
            for old in (
                getattr(self, "theme_pane", None),
                getattr(self, "theme_popup", None),
                getattr(self, "_context_menu_button_theme", None),
                getattr(self, "_context_menu_keyboard_button_theme", None),
                getattr(self, "_context_menu_disabled_button_theme", None),
                getattr(self, "_context_menu_icon_theme", None),
                getattr(self, "_context_menu_disabled_icon_theme", None),
                getattr(self, "_context_menu_shortcut_theme", None),
                getattr(self, "_context_menu_disabled_shortcut_theme", None),
                getattr(self, "_context_menu_arrow_theme", None),
                getattr(self, "_context_menu_disabled_arrow_theme", None),
            ):
                if old:
                    retained = self._retained_item(old)
                    if retained.exists():
                        retained.deleteNative()

        cfg = self.theme_config
        self.theme_pane = viewport_surface_theme(
            background=cfg["background"],
            text=cfg["text"],
            border=cfg["border"],
            padding=(0, 0),
            spacing=(0, 0),
            scrollbar=True,
        )
        self.theme_popup = menu_surface_theme(
            padding=(4, 4), spacing=(0, 1), tag=None, cache=False)

        # Context-menu rows retain their exact WinUx geometry while DearUIQt
        # owns the renderer-specific color/style mapping.
        self._context_menu_button_theme = menu_button_theme(
            align=(0.0, 0.5), frame_padding=(8, 4), tag=None, cache=False)
        self._context_menu_keyboard_button_theme = menu_button_theme(
            keyboard=True, align=(0.0, 0.5), frame_padding=(8, 4),
            tag=None, cache=False)
        self._context_menu_shortcut_theme = menu_button_theme(
            align=(1.0, 0.5), frame_padding=(4, 4), tag=None, cache=False)
        self._context_menu_disabled_shortcut_theme = menu_button_theme(
            disabled=True, align=(1.0, 0.5), frame_padding=(4, 4),
            tag=None, cache=False)
        self._context_menu_icon_theme = menu_image_button_theme(
            frame_padding=(6, 6), tag=None, cache=False)
        self._context_menu_arrow_theme = menu_button_theme(
            align=(0.5, 0.5), frame_padding=(0, 4), tag=None, cache=False)
        self._context_menu_disabled_arrow_theme = menu_button_theme(
            disabled=True, align=(0.5, 0.5), frame_padding=(0, 4),
            tag=None, cache=False)
        self._context_menu_disabled_button_theme = menu_button_theme(
            disabled=True, align=(0.0, 0.5), frame_padding=(8, 4),
            tag=None, cache=False)
        self._context_menu_disabled_icon_theme = menu_image_button_theme(
            disabled=True, frame_padding=(6, 6), tag=None, cache=False)

    def _build_ui(self):
        self._root_widget = QVBoxLayout(
            parent=self.parent, spacing=0, tag=f"{self.uid}_root")
        pane_height = self.height if self.height == -1 else max(self.height - 26, 10)
        self.window_tag = f"{self.uid}_pane"
        self._pane_widget = QFrame(
            parent=self._root_widget, width=self.width, height=pane_height,
            tag=self.window_tag, frame_shape=QFrame.StyledPanel,
            no_scrollbar=True, no_scroll_with_mouse=True)
        self._pane_widget.setTheme(self.theme_pane)

        self._header_canvas_widget = QCanvas(
            width=-1, height=self.HEADER_HEIGHT, parent=self._pane_widget,
            tag=f"{self.uid}_header")
        self.header_canvas = self._header_canvas_widget.tag

        self.pinned_tooltip_anchor = f"{self.uid}_pinned_tooltip_anchor"
        self._pinned_anchor_widget = QVBoxLayout(
            parent=self._pane_widget, spacing=0, tag=self.pinned_tooltip_anchor)
        self._pinned_canvas_widget = QCanvas(
            width=-1, height=self.ROW_HEIGHT, parent=self._pinned_anchor_widget,
            tag=f"{self.uid}_pinned", show=False)
        self.pinned_canvas = self._pinned_canvas_widget.tag
        # Dear PyGui decides whether a tooltip may render from the actual
        # target item's hover state.  The surrounding QVBoxLayout is only a
        # layout/group and does not reliably become hovered when its QCanvas
        # child owns the pointer, so bind the tooltip to the canvas itself.
        self._pinned_item_tooltip = self._create_item_tooltip(
            self._pinned_canvas_widget, "pinned")

        self.body_window = f"{self.uid}_body"
        self._body_window_widget = QFrame(
            parent=self._pane_widget, width=-1, height=-1, tag=self.body_window,
            frame_shape=QFrame.NoFrame, horizontal_scrollbar=self.horizontal_scrollbar,
            no_scrollbar=False, no_scroll_with_mouse=False)
        self._body_window_widget.setTheme(self.theme_pane)
        self.body_tooltip_anchor = f"{self.uid}_body_tooltip_anchor"
        self._body_anchor_widget = QVBoxLayout(
            parent=self._body_window_widget, spacing=0, tag=self.body_tooltip_anchor)
        self._body_canvas_widget = QCanvas(
            width=-1, height=self.ROW_HEIGHT, parent=self._body_anchor_widget,
            tag=f"{self.uid}_body_canvas")
        self.body_canvas = self._body_canvas_widget.tag
        self._body_item_tooltip = self._create_item_tooltip(
            self._body_canvas_widget, "body")

        self._status_layout = QHBoxLayout(
            parent=self._root_widget, spacing=7, show=self.show_status_bar)
        self.status_items_tag = f"{self.uid}_status_items"
        self.status_sel_tag = f"{self.uid}_status_sel"
        self._status_items_widget = QLabel(
            "0 items", parent=self._status_layout, tag=self.status_items_tag,
            color=self.theme_config["status_text"])
        self._status_sel_widget = QLabel(
            "", parent=self._status_layout, tag=self.status_sel_tag,
            color=self.theme_config["status_text"])

    def _create_item_tooltip(self, parent, suffix):
        """Create one reusable non-interactive tooltip paint surface.

        Explorer rows are QCanvas/mvDrawlist surfaces. Dear PyGui explicitly
        rejects mvTooltip as a drawlist child, so the tooltip must not be
        parented to the canvas. ``parent`` is retained only as the logical hover
        source; row hit-testing decides when this viewport overlay is visible.
        """
        tooltip = ExplorerTooltipOverlay(
            f"{self.uid}_{suffix}_item_tooltip",
            body_font=self._fonts.get("body"),
            header_font=self._fonts.get("header"),
            primary_viewport=bool(getattr(self, "_primary_pointer_overlays", False)),
        )
        return {"widget": tooltip, "target": parent, "item_id": None}

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
    def _cancel_tooltip_wakeup(parts):
        """Cancel the scheduled dwell wake-up without touching dwell state."""
        if not parts:
            return
        parts["hover_timer_serial"] = int(parts.get("hover_timer_serial", 0)) + 1
        timer = parts.pop("hover_timer", None)
        parts.pop("hover_timer_target", None)
        if timer is not None:
            try:
                timer.delete()
            except Exception:
                pass

    @staticmethod
    def _hide_tooltip_parts(parts):
        if not parts:
            return
        ExplorerRenderingMixin._cancel_tooltip_wakeup(parts)
        delay = parts.get("hover_delay")
        if delay is not None:
            delay.reset()
        if parts.get("item_id") is None:
            return
        widget = parts.get("widget")
        if widget is not None and widget.exists():
            widget.hide()
        parts["item_id"] = None

    def _schedule_tooltip_wakeup(self, parts, item_id):
        """Wake the ListView when a stationary-pointer dwell reaches its delay.

        ``TooltipHoverDelay`` intentionally only measures elapsed time; it does
        not generate an event.  Explorer used to re-check it only from mouse
        movement, so a completely stationary pointer required a tiny nudge
        after 500 ms before the tooltip appeared.  Schedule one UI-thread
        single-shot for the logical row and re-run physical hit-testing when it
        fires.  This stays on DearUIQt's shared QApplication event loop and
        creates no worker/thread.
        """
        if not parts:
            return
        if (parts.get("hover_timer") is not None and
                parts.get("hover_timer_target") == item_id):
            return

        self._cancel_tooltip_wakeup(parts)
        serial = int(parts.get("hover_timer_serial", 0)) + 1
        parts["hover_timer_serial"] = serial
        parts["hover_timer_target"] = item_id

        def wake():
            if int(parts.get("hover_timer_serial", 0)) != serial:
                return
            parts["hover_timer"] = None
            parts.pop("hover_timer_target", None)
            # Re-sample the real pointer position at expiry rather than trusting
            # the row that originally armed the timer.  Leaving/changing rows
            # therefore cannot surface a stale tooltip even if no DPG hover
            # callback was delivered in between.
            updater = getattr(self, "_update_hover_state", None)
            if callable(updater):
                updater()

        try:
            parts["hover_timer"] = QTimer.singleShot(
                max(1, int(round(TOOLTIP_DELAY * 1000.0))), wake)
        except Exception:
            # Unit/headless hosts may not own a QApplication scheduler.  Keep
            # the legacy event-driven fallback there; production WinUx has the
            # application scheduler installed before ListViews are constructed.
            parts["hover_timer"] = None
            parts.pop("hover_timer_target", None)

    def _show_tooltip_parts(self, parts, item):
        if not parts or item is None or getattr(self, "_mouse_down", False):
            self._hide_tooltip_parts(parts)
            return
        tooltip = parts.get("widget")
        if tooltip is None or not tooltip.exists():
            return
        # A ListView can replace its Python ListViewItem objects during an
        # incremental refresh while the logical row (same path/job) remains
        # unchanged.  Using ``id(item)`` here restarted the dwell timer on every
        # refresh, so tooltips on file/job icons could disappear permanently.
        # Match the model's own stable identity semantics instead.
        try:
            item_id = stable_item_identity(item)
        except Exception:
            item_id = ("object", id(item))

        # Dwell belongs to the logical row, not to an exact mouse pixel.
        # Including the cursor position in the target restarted the 500 ms
        # timer for every 1 px movement, so a real hand could keep the tooltip
        # suppressed indefinitely. Row hit-testing already resets the dwell
        # when the pointer enters another row or leaves the ListView.
        delay = parts.get("hover_delay")
        if delay is None:
            delay = parts["hover_delay"] = TooltipHoverDelay()
        if not delay.ready(item_id):
            self._schedule_tooltip_wakeup(parts, item_id)
            if parts.get("item_id") is not None:
                tooltip.hide()
                parts["item_id"] = None
            return
        self._cancel_tooltip_wakeup(parts)
        if parts.get("item_id") == item_id:
            return

        title, details, full_path = self._item_tooltip_content(item)
        tooltip.hide()
        if not tooltip.setContent(title or " ", details, full_path):
            return
        if tooltip.show():
            parts["item_id"] = item_id

    def _hide_item_tooltips(self):
        self._hide_tooltip_parts(getattr(self, "_body_item_tooltip", None))
        self._hide_tooltip_parts(getattr(self, "_pinned_item_tooltip", None))

    def _set_item_tooltips_primary_viewport(self, primary=True):
        for parts in (getattr(self, "_body_item_tooltip", None),
                      getattr(self, "_pinned_item_tooltip", None)):
            widget = parts.get("widget") if parts else None
            setter = getattr(widget, "setPrimaryViewport", None)
            if callable(setter):
                setter(primary)

    def _destroy_item_tooltips(self):
        for name in ("_body_item_tooltip", "_pinned_item_tooltip"):
            parts = getattr(self, name, None)
            # A pending dwell wake-up closes over this ListView. Cancel it before
            # destroying the overlay so no delayed callback can touch a dead
            # Explorer surface during shutdown/navigation.
            self._hide_tooltip_parts(parts)
            widget = parts.get("widget") if parts else None
            destroy = getattr(widget, "destroy", None)
            if callable(destroy):
                destroy()
            setattr(self, name, None)

    def _resolve_icon_texture(self, icon):
        if icon is None:
            return None
        if not isinstance(icon, (str, os.PathLike)) or self._retained_item(icon).exists():
            return icon
        path = os.path.abspath(os.path.expanduser(os.fspath(icon)))
        cached = self._custom_textures.get(path)
        if cached and self._retained_item(cached).exists(): return cached
        if not os.path.isfile(path): return None
        image = Image.open(path).convert("RGBA")
        texture = WindowsIconRegistry._add_texture(image, f"{self.uid}_custom_icon_{len(self._custom_textures)}")
        self._custom_textures[path] = texture
        return texture

    def _create_body_row(self, index):
        """Create one reusable body-row primitive set for *index*."""
        y0 = float(index) * self.ROW_HEIGHT
        row_spacing = max(0, int(getattr(self, "ROW_SPACING", 0)))
        top_inset = row_spacing // 2
        bottom_inset = row_spacing - top_inset
        painter = QPainter(self._body_canvas_widget)
        background = painter.drawRect(
            (0, y0 + top_inset),
            (1, y0 + self.ROW_HEIGHT - bottom_inset),
            fill=(0, 0, 0, 0), color=(0, 0, 0, 0), thickness=0.0,
            rounding=float(self.theme_config.get("row_rounding", 1.0)),
        )
        bottom = painter.drawLine(
            (0, y0 + self.ROW_HEIGHT - 0.5),
            (1, y0 + self.ROW_HEIGHT - 0.5),
            color=self.theme_config["row_line"], thickness=1,
            show=bool(self.theme_config.get("show_row_lines", True)),
        )
        texts = {}
        icon_tag = None
        for column in self._visible_columns():
            key = column["key"]
            text_tag = painter.drawText(
                (0, 0), "", color=self.theme_config["text"], size=15, show=False)
            self._bind_font(text_tag, self._fonts.get("body"))
            texts[key] = text_tag
            if key == "name":
                # A valid texture is assigned immediately by _bind_body_row().
                texture = WindowsIconRegistry.get_icon("", is_dir=False)
                icon_tag = painter.drawImage(
                    texture, (0, 0), (ICON_SIZE, ICON_SIZE), show=False)
        row = {
            "index": int(index),
            "background": background,
            "selection_inner": None,
            "bottom": bottom,
            "texts": texts,
            "icon": icon_tag,
            "bounds": None,
            "values": {},
            "icon_texture": None,
            "visual_signature": None,
            "item_object_id": None,
            "row_fill": None,
            "row_text_color": None,
            "pending_layout": True,
        }
        self._bind_body_row(row, index)
        return row

    def _bind_body_row(self, row, index, preserve_geometry=False):
        """Bind one rendered primitive set to a logical item index."""
        index = int(index)
        if not (0 <= index < len(self.items)):
            return row
        item = self.items[index]
        row["content_changed"] = False
        previous_index = row.get("index")
        previous_object_id = row.get("item_object_id")
        row["index"] = index
        row["item_object_id"] = id(item)

        # Row-level presentation is independent from the visible cell text.
        # Job Viewer refreshes replace ListViewItem objects while retaining the
        # same stable job-id/path.  If a job changes state (Queued -> Running,
        # etc.) its ``row_fill`` can change even when the retained row slot is
        # reused.  Track that visual payload explicitly so incremental refresh
        # repaints the row instead of leaving the old/white background behind.
        row_fill = item.data.get("row_fill")
        if row.get("row_fill") != row_fill:
            row["row_fill"] = row_fill
            row["content_changed"] = True
            row["visual_signature"] = None
            row["visual_background_signature"] = None

        row_text_color = item.data.get("row_text_color")
        if row.get("row_text_color") != row_text_color:
            row["row_text_color"] = row_text_color
            row["content_changed"] = True
            row["visual_signature"] = None
            row["visual_text_color"] = None

        provider = getattr(self, 'name_color_provider', None)
        name_color = provider(item) if provider is not None else None
        if row.get('name_color') != name_color:
            row['name_color'] = name_color
            row['content_changed'] = True
            row['visual_text_color'] = None

        if previous_index != index or previous_object_id != id(item):
            row["visual_signature"] = None
            row["visual_background_signature"] = None
            row["visual_text_color"] = None
            inner_tag = row.get("selection_inner")
            if inner_tag and self._retained_item(inner_tag).exists():
                self._retained_item(inner_tag).configure(show=False)

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
                row["content_changed"] = True
                cached_values[key] = value
                if text_tag and self._retained_item(text_tag).exists():
                    self._retained_item(text_tag).configure(text=value)

        icon = row.get("icon")
        if icon and self._retained_item(icon).exists():
            texture = self._item_icons.get(id(item)) or WindowsIconRegistry.get_icon(
                item.extension, is_dir=item.is_dir
            )
            if row.get("icon_texture") != texture:
                row["content_changed"] = True
                row["icon_texture"] = texture
                try:
                    self._retained_item(icon).configure(texture_tag=texture)
                except Exception:
                    pass
        return row

    def _destroy_body_row(self, row):
        """Delete the native draw primitives owned by one rendered row slot."""
        tags = [row.get("background"), row.get("selection_inner"), row.get("bottom"), row.get("icon")]
        tags.extend(row.get("texts", {}).values())
        for tag in tags:
            if tag:
                retained = self._retained_item(tag)
                if retained.exists():
                    retained.deleteNative()

    def _rebuild_body_rows(self):
        """Rebind directory rows without clearing the visible canvas."""
        self._text_fit_cache.clear()
        if not self._body_canvas_widget.exists():
            return
        # Folder identity changes do not change the row-slot geometry. Keep
        # existing primitives, allocate only growth and remove only excess.
        # Clearing the canvas exposed a blank frame and recreated every text
        # at (0, 0) before the final layout, causing a black pile at the top.
        keys = {column["key"] for column in self._visible_columns()}
        if any(set(row.get("texts", {})) != keys for row in self._row_items):
            self._body_canvas_widget.clear()
            self._reset_row_registry()
        self._refresh_row_registry_content()
        self._sync_virtual_rows(force=True)
        self._layout_all()

    def _rebuild_draw_items(self):
        self._text_fit_cache.clear()
        getattr(self, "_retained_item_cache", {}).clear()
        self._ensure_column_widths()
        if self._header_canvas_widget.exists():
            self._header_canvas_widget.clear()
        if self._body_canvas_widget.exists():
            self._body_canvas_widget.clear()
        self._header_items = {}
        self._header_top_line = None
        self._header_bottom_line = None
        self._header_background = None
        self._reset_row_registry()

        # Keep one explicit background primitive for the *whole* header.
        # The header drawlist itself can grow later when Auto Width reacts to
        # startup/layout/splitter changes.  If this rectangle is left at the
        # width measured during construction, the newly exposed part of the
        # drawlist falls back to the canvas/window background and produces the
        # visibly uneven grey strip seen after a resize.
        painter = QPainter(self._header_canvas_widget)
        self._header_background = painter.drawRect(
            (0, 0),
            (max(1.0, self._available_width()), self.HEADER_HEIGHT),
            fill=self.theme_config["header_bg"],
            color=self.theme_config["header_bg"], thickness=0)

        for column in self._visible_columns():
            key = column["key"]
            background_tag = painter.drawRect(
                (0, 0), (1, self.HEADER_HEIGHT),
                fill=(0, 0, 0, 0), color=(0, 0, 0, 0), thickness=0.0)
            label_tag = painter.drawText(
                (0, 0), column["label"], color=self.theme_config["header_text"], size=16)
            indicator_tag = painter.drawTriangle(
                (0, 0), (0, 0), (0, 0), color=self.theme_config["header_text"],
                fill=self.theme_config["header_text"], show=False)
            separator_tag = painter.drawLine(
                (0, 0), (0, self.HEADER_HEIGHT), color=self.theme_config["separator"],
                thickness=1, show=self.show_column_separators)
            self._bind_font(label_tag, self._fonts.get("header"))
            self._header_items[key] = {
                "background": background_tag,
                "label": label_tag,
                "indicator": indicator_tag,
                "separator": separator_tag,
            }

        self._header_top_line = painter.drawLine(
            (0, 0.5), (1, 0.5),
            color=self.theme_config.get("header_top_line", self.theme_config["header_bg"]),
            thickness=1)
        self._header_bottom_line = painter.drawLine(
            (0, self.HEADER_HEIGHT - 0.5), (1, self.HEADER_HEIGHT - 0.5),
            color=self.theme_config.get("header_bottom_line", self.theme_config["border"]),
            thickness=1)

        self._rebuild_pinned_row()
        self._sync_virtual_rows(force=True)
        self._layout_all()

    def _rebuild_pinned_row(self):
        if not hasattr(self, "pinned_canvas") or not self._pinned_canvas_widget.exists():
            return
        self._pinned_canvas_widget.clear()
        self._pinned_background = None
        self._pinned_texts = {}
        self._pinned_icon = None
        item = self._pinned_item
        self._pinned_canvas_widget.setVisible(bool(item))
        self._pinned_canvas_widget.setFixedHeight(self.ROW_HEIGHT)
        if item is None:
            return
        painter = QPainter(self._pinned_canvas_widget)
        row_spacing = max(0, int(getattr(self, "ROW_SPACING", 0)))
        top_inset = row_spacing // 2
        bottom_inset = row_spacing - top_inset
        self._pinned_background = painter.drawRect(
            (0, top_inset), (2, self.ROW_HEIGHT - bottom_inset),
            fill=(0, 0, 0, 0), color=(0, 0, 0, 0), thickness=0.0,
            rounding=float(self.theme_config.get("row_rounding", 1.0)))
        painter.drawLine(
            (0, self.ROW_HEIGHT - .5), (1, self.ROW_HEIGHT - .5),
            color=self.theme_config["row_line"], thickness=1,
            show=bool(self.theme_config.get("show_row_lines", True)))
        for column in self._visible_columns():
            key = column["key"]
            value = self._display_cell_value(item, key)
            text_tag = painter.drawText(
                (0, 0), value, color=self.theme_config["text"], size=15, show=False)
            self._bind_font(text_tag, self._fonts.get("body"))
            self._pinned_texts[key] = text_tag
            if key == "name":
                texture = self._item_icons.get(id(item)) or WindowsIconRegistry.get_icon(
                    item.extension, is_dir=item.is_dir)
                self._pinned_icon = painter.drawImage(
                    texture, (0, 0), (ICON_SIZE, ICON_SIZE), show=False)
        self._layout_pinned_row()

    def _layout_pinned_row(self):
        item = self._pinned_item
        if item is None or not hasattr(self, "pinned_canvas") or not self._pinned_canvas_widget.exists():
            return
        geometry = self._column_geometry()
        total_width = sum(width for _, width in geometry.values())
        visible_width = min(total_width, self._available_width())
        self._pinned_canvas_widget.resize(max(1, int(round(total_width))), self.ROW_HEIGHT)
        if self._pinned_background and self._retained_item(self._pinned_background).exists():
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
            row_spacing = max(0, int(getattr(self, "ROW_SPACING", 0)))
            top_inset = row_spacing // 2
            bottom_inset = row_spacing - top_inset
            self._retained_item(self._pinned_background).configure(
                pmin=(0, top_inset),
                pmax=(max(1.0, visible_width), self.ROW_HEIGHT - bottom_inset),
                fill=fill, color=border, thickness=thickness)
        for column in self._visible_columns():
            key = column["key"]
            tag = self._pinned_texts.get(key)
            if not tag or not self._retained_item(tag).exists():
                continue
            x, width = geometry[key]
            value = self._display_cell_value(item, key)
            left_pad = 30.0 if key == "name" else 8.0
            fitted = self._fit_text(value, max(0.0, width-left_pad-6.0), self._fonts.get("body"), 15)
            _, th = self._measure_text(fitted, self._fonts.get("body"), 15)
            self._retained_item(tag).configure(text=fitted, pos=(round(x+left_pad), round((self.ROW_HEIGHT-th)*.5)), show=True)
            if key == "name" and self._pinned_icon and self._retained_item(self._pinned_icon).exists():
                iy = round((self.ROW_HEIGHT-ICON_SIZE)*.5)
                self._retained_item(self._pinned_icon).configure(pmin=(round(x+7), iy), pmax=(round(x+7+ICON_SIZE), iy+ICON_SIZE), show=True)

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
        selected_border_width = float(cfg.get("selected_border_width", 0.5))
        if selected and hovered:
            border = (
                cfg.get("selected_border", focus_border)
                if self._has_focus
                else cfg.get("inactive_selected_border", cfg.get("selected_border", focus_border))
            )
            return cfg["selected_hover_fill"], border, selected_border_width
        if selected and self._has_focus:
            return (
                cfg["selected_fill"],
                cfg.get("selected_border", focus_border),
                selected_border_width,
            )
        if selected:
            return (
                cfg.get("inactive_selected_fill", cfg["selected_fill"]),
                cfg.get("inactive_selected_border", cfg.get("selected_border", focus_border)),
                selected_border_width,
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

    def _ensure_selection_inner(self, row):
        """Return the non-AA inner fill used by the crisp selected border.

        The outer row rectangle becomes the 1 px border while this inner
        rectangle carries the selection fill. Creating it lazily keeps normal
        folders at the original primitive count and adds only one primitive per
        row that has ever been selected.
        """
        tag = row.get("selection_inner")
        if tag and self._retained_item(tag).exists():
            return tag
        background = row.get("background")
        painter = QPainter(self._body_canvas_widget)
        tag = painter.drawRect(
            (0, 0), (1, 1),
            fill=(0, 0, 0, 0), color=(0, 0, 0, 0), thickness=0.0,
            rounding=0.0, before=row.get("bottom"), show=False,
        )
        row["selection_inner"] = tag
        return tag

    def _configure_crisp_selected_surface(self, row, fill, border):
        """Paint a pixel-snapped selected row without anti-aliased strokes."""
        bounds = row.get("bounds")
        background = row.get("background")
        if not bounds or not background:
            return
        x0, y0, x1, y1 = bounds
        outer = self._retained_item(background)
        # Filled rectangles are used instead of a 1 px outline stroke because
        # ImGui anti-aliases draw-rectangle strokes and visually spreads them
        # across adjacent pixels. Integer-aligned fills stay crisp.
        outer.configure(
            fill=border, color=(0, 0, 0, 0), thickness=0.0, rounding=0.0)
        inner_tag = self._ensure_selection_inner(row)
        inner = self._retained_item(inner_tag)
        # Rows now have explicit visual spacing, so every selected item keeps
        # a complete one-pixel border of its own without overlapping neighbors.
        ix0 = int(round(x0)) + 1
        iy0 = int(round(y0)) + 1
        ix1 = max(ix0, int(round(x1)) - 1)
        iy1 = max(iy0, int(round(y1)) - 1)
        inner.configure(
            pmin=(ix0, iy0), pmax=(ix1, iy1),
            fill=fill, color=(0, 0, 0, 0), thickness=0.0, rounding=0.0, show=True)

    def _hide_selection_inner(self, row):
        tag = row.get("selection_inner")
        if tag and self._retained_item(tag).exists():
            self._retained_item(tag).configure(show=False)

    def _update_row_visual(self, index):
        if index is None or not (0 <= int(index) < len(self.items)):
            return
        row = self._row_for_index(index)
        if row is None:
            return
        background = row.get("background")
        if not background or not self._retained_item(background).exists():
            return
        fill, border, thickness = self._row_visual_style(index)

        selected = index in self.selected
        semantic_text_color = self.items[index].data.get("row_text_color")
        if selected and self._has_focus:
            text_color = self.theme_config.get("selected_text", self.theme_config["text"])
        elif selected:
            text_color = self.theme_config.get("inactive_selected_text", self.theme_config["text"])
        else:
            text_color = semantic_text_color or self.theme_config["text"]

        name_color = text_color
        provider = getattr(self, 'name_color_provider', None)
        if not selected and semantic_text_color is None and provider is not None:
            name_color = provider(self.items[index]) or text_color

        draw_border = border
        draw_thickness = float(thickness)
        selected_surface = bool(selected and draw_border != (0, 0, 0, 0) and draw_thickness > 0.0)
        background_signature = (fill, draw_border, draw_thickness)
        background_signature += (selected_surface, row.get("bounds"))

        if row.get("visual_background_signature") != background_signature:
            if selected_surface:
                self._configure_crisp_selected_surface(row, fill, draw_border)
            else:
                self._retained_item(background).configure(
                    fill=fill, color=draw_border, thickness=draw_thickness)
                self._hide_selection_inner(row)
            row["visual_background_signature"] = background_signature

        text_signature = (text_color, name_color)
        if row.get("visual_text_color") != text_signature:
            for key, text_tag in row.get("texts", {}).items():
                if text_tag and self._retained_item(text_tag).exists():
                    self._retained_item(text_tag).configure(color=name_color if key == 'name' else text_color)
            row["visual_text_color"] = text_signature

        row["visual_signature"] = (
            fill, border, float(thickness), text_color, row.get("bounds"))

    def refresh_row_visuals(self, indices=None):
        """Force retained row backgrounds to match the current item metadata.

        Normal Explorer selection updates are aggressively cached.  Data-driven
        views such as Job Viewer also encode persistent presentation in
        ``item.data["row_fill"]``.  Their polling refresh can replace model
        objects without changing selection/current state, so explicitly
        invalidate the retained background signature before repainting.  This
        makes status colors visible immediately instead of waiting for a hover
        event to call ``_update_row_visual``.
        """
        if indices is None:
            targets = set(self._rendered_row_indices())
        else:
            targets = {
                int(index) for index in indices
                if index is not None and 0 <= int(index) < len(self.items)
            }
        for index in targets:
            row = self._row_for_index(index)
            if row is None:
                continue
            row["visual_background_signature"] = None
            row["visual_text_color"] = None
            row["visual_signature"] = None
        self._update_selection_draws(indices=targets)
        return targets

    def _update_selection_draws(self, indices=None, force=False):
        """Repaint only rows whose selection/current/focus state changed.

        This keeps multi-selection proportional to the number of rows that
        actually changed instead of rescanning/configuring every rendered row.
        """
        selected = set(self.selected)
        current = self._current_index
        focused = bool(self._has_focus)
        previous_selected = getattr(self, "_visual_selected_cache", None)
        previous_current = getattr(self, "_visual_current_cache", None)
        previous_focus = getattr(self, "_visual_focus_cache", None)

        if force or previous_selected is None:
            targets = set(self._rendered_row_indices())
        else:
            changed = selected.symmetric_difference(previous_selected)
            targets = set(changed)
            for value in (current, previous_current):
                if value is not None:
                    targets.add(int(value))
            if previous_focus is not None and focused != previous_focus:
                # Active/inactive selection fill changes for selected rows only.
                targets.update(selected)
                targets.update(previous_selected)

        if indices is not None:
            targets.update(int(i) for i in indices if i is not None)

        for index in targets:
            self._update_row_visual(index)

        self._visual_selected_cache = selected
        self._visual_current_cache = current
        self._visual_focus_cache = focused

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
        if self._mouse_in_pinned_row():
            self._hide_tooltip_parts(getattr(self, "_body_item_tooltip", None))
            self._show_tooltip_parts(
                getattr(self, "_pinned_item_tooltip", None), self._pinned_item)
            self._clear_hover()
            return
        self._hide_tooltip_parts(getattr(self, "_pinned_item_tooltip", None))
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
