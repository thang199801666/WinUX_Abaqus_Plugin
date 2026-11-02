"""Internal layout, command dispatch, menu and theme helpers for RibbonBar."""
from __future__ import annotations

from typing import Callable

from .textures import RibbonTileTextures as _RibbonTileTextures


class RibbonInternalsMixin:
    def _tile_texture(self, record):
        disabled = not bool(record.get("enabled", True))
        return _RibbonTileTextures.get(
            record.get("image"), record.get("label", ""),
            int(record.get("width") or self.LARGE_BUTTON_WIDTH),
            self.LARGE_BUTTON_HEIGHT, self.LARGE_ICON_SIZE,
            font_size=self.TILE_FONT_SIZE, line_height=self.TILE_LINE_HEIGHT,
            text_margin=self.TILE_TEXT_MARGIN,
            text_color=self.visual_style.disabled_text if disabled else self.visual_style.text,
            icon_path_resolver=self.icon_path_resolver, backend=self.backend,
            bottom_padding=getattr(self, "TILE_BOTTOM_PADDING", None),
            normalize_icon_bounds=getattr(self, "NORMALIZE_ICON_BOUNDS", False),
            disabled=disabled)

    def _reserve_group_width(self, group, slot, width):
        """Measure the natural group width independently from adaptive display state."""
        slots = group["slot_widths"]
        slots[slot] = max(slots.get(slot, 0), int(width))
        content_width = sum(slots.values()) + self.COMMAND_GAP * max(0, len(slots) - 1)
        # Each width=-1 child also reserves one pixel at its right edge.
        padding = 2 * (self.GROUP_HORIZONTAL_PADDING + self.CONTROLS_HORIZONTAL_PADDING) + 2
        natural_width = max(group["minimum_width"], content_width + padding)
        group["natural_width"] = natural_width

        # Outside responsive mode the natural measurement is the rendered width.
        # In adaptive mode relayout() owns the rendered width so newly measured
        # content cannot fight the currently selected breakpoint.
        if not getattr(self, "_responsive", False):
            if natural_width != group["width"]:
                self.backend.configure_item(group["tag"], width=natural_width)
                group["width"] = natural_width
            self._update_group_footer_alignment(group, natural_width)

    def _update_group_footer_alignment(self, group, width):
        caption_space = group["caption_width"] + (20 if group["launcher"] is not None else 0)
        left_pad = max(2, (int(width) - 2 * self.GROUP_HORIZONTAL_PADDING - caption_space) // 2)
        try:
            self.backend.configure_item(group["footer_spacer"], width=left_pad)
        except Exception:
            pass

    def _recalculate_group_natural_width(self, group):
        """Re-measure one retained group after display-template geometry changes."""
        slots = dict(group.get("fixed_slots", {}))
        for record in self._buttons.values():
            if record.get("tab") != group["tab"] or record.get("group") != group["key"]:
                continue
            slot = record.get("layout_slot")
            if slot is None:
                continue
            width = max(1, int(record.get("width") or 1))
            slots[slot] = max(slots.get(slot, 0), width)
        group["slot_widths"] = slots
        content_width = sum(slots.values()) + self.COMMAND_GAP * max(0, len(slots) - 1)
        padding = 2 * (self.GROUP_HORIZONTAL_PADDING + self.CONTROLS_HORIZONTAL_PADDING) + 2
        natural = max(int(group.get("minimum_width", self.GROUP_MIN_WIDTH)), content_width + padding)
        group["natural_width"] = natural
        return natural

    def _apply_button_display_geometry(self, record):
        """Update one retained command for the active display template."""
        scope = record.get("scope")
        if scope == "application":
            tag = record.get("tag")
            if tag is not None:
                self.backend.configure_item(tag, height=max(16, self.QUICK_ACCESS_HEIGHT - 4))
            return
        if scope == "quick":
            # Quick image buttons intentionally keep their icon footprint. Only
            # text-style QAT buttons need to follow the toolbar height.
            tag = record.get("tag")
            if tag is not None and not record.get("image"):
                self.backend.configure_item(tag, height=max(16, self.QUICK_ACCESS_HEIGHT - 4))
            return
        if not record.get("tab") or not record.get("group"):
            return

        size = record.get("size", "small")
        if record.get("uses_template_width", False):
            record["width"] = (
                self.LARGE_BUTTON_WIDTH if size == "large" else self.SMALL_BUTTON_WIDTH
            )
        natural = max(1, int(record.get("width") or (
            self.LARGE_BUTTON_WIDTH if size == "large" else self.SMALL_BUTTON_WIDTH
        )))
        state = "large"
        group = self._groups.get((record.get("tab"), record.get("group")))
        if group is not None and self._responsive:
            state = group.get("adaptive_state", "large")
        target = self._adaptive_policy.command_width(natural, state) if state in ("medium", "small") else natural
        record["adaptive_width"] = target

        main = record.get("tag")
        arrow = record.get("arrow")
        if record.get("split"):
            if size == "large":
                if main is not None:
                    self.backend.configure_item(
                        main, width=target, height=max(38, self.LARGE_BUTTON_HEIGHT - 18))
                if arrow is not None:
                    self.backend.configure_item(arrow, width=target, height=17)
            else:
                arrow_width = min(
                    self.SPLIT_ARROW_WIDTH,
                    max(14, int(round(self.SPLIT_ARROW_WIDTH * (target / max(1, natural))))),
                )
                if main is not None:
                    self.backend.configure_item(
                        main, width=max(24, target - arrow_width), height=self.SMALL_BUTTON_HEIGHT)
                if arrow is not None:
                    self.backend.configure_item(
                        arrow, width=arrow_width, height=self.SMALL_BUTTON_HEIGHT)
            return

        if main is not None:
            height = self.LARGE_BUTTON_HEIGHT if size == "large" else self.SMALL_BUTTON_HEIGHT
            config = {"width": target, "height": height}
            if record.get("large_tile") and record.get("image"):
                texture = self._tile_texture(record)
                if texture is not None:
                    config["texture_tag"] = texture
                    record["tile_texture"] = texture
            self.backend.configure_item(main, **config)

    def _apply_group_adaptive_state(self, group, state, width):
        """Apply one adaptive visual state without rebuilding application content.

        Existing controls stay alive (no worker, no widget destruction/recreate
        cycle).  Their horizontal footprint is scaled by the display template's
        policy while command identity/callback/state remain untouched.
        """
        state = str(state or "large").lower()
        if state not in ("large", "medium", "small"):
            return
        width = max(1, int(width))
        policy = self._adaptive_policy
        self.backend.configure_item(group["tag"], width=width)
        group["width"] = width
        group["adaptive_state"] = state
        self._update_group_footer_alignment(group, width)

        for record in self._buttons.values():
            if record.get("tab") != group["tab"] or record.get("group") != group["key"]:
                continue
            natural = int(record.get("width") or (
                self.LARGE_BUTTON_WIDTH if record.get("size") == "large" else self.SMALL_BUTTON_WIDTH
            ))
            target = policy.command_width(natural, state)
            record["adaptive_width"] = target

            if record.get("split"):
                arrow = record.get("arrow")
                main = record.get("tag")
                if record.get("size") == "large":
                    # Large split buttons are vertical; both halves share width.
                    for item in (main, arrow):
                        if item is not None:
                            self.backend.configure_item(item, width=target)
                else:
                    arrow_width = min(self.SPLIT_ARROW_WIDTH, max(14, int(round(self.SPLIT_ARROW_WIDTH * (target / max(1, natural))))))
                    main_width = max(24, target - arrow_width)
                    if main is not None:
                        self.backend.configure_item(main, width=main_width)
                    if arrow is not None:
                        self.backend.configure_item(arrow, width=arrow_width)
                continue

            tag = record.get("tag")
            if tag is not None:
                self.backend.configure_item(tag, width=target)

    def _restore_group_natural_state(self, group):
        natural = int(group.get("natural_width", group.get("minimum_width", self.GROUP_MIN_WIDTH)))
        self._apply_group_adaptive_state(group, "large", natural)

    @staticmethod
    def _key(value, kind):
        value = str(value or "").strip()
        if not value:
            raise ValueError("Ribbon {} key cannot be empty.".format(kind))
        return value

    @staticmethod
    def _normalize_group_layout(layout):
        layout = str(layout or "mixed").strip().lower()
        if layout not in ("mixed", "large", "small"):
            raise ValueError("Ribbon group layout must be 'mixed', 'large' or 'small'.")
        return layout

    @staticmethod
    def _normalize_size(size):
        size = str(size or "auto").strip().lower()
        if size not in ("auto", "small", "large"):
            raise ValueError("Ribbon button size must be 'auto', 'small' or 'large'.")
        return size

    def _resolve_button_size(self, group, size):
        size = self._normalize_size(size)
        if size != "auto":
            return size
        layout = group.get("layout", "mixed")
        return "large" if layout == "large" else "small"

    def _new_button_record(self, tab_key, group_key, key, label, callback, **state):
        tab_key, group_key = str(tab_key), str(group_key)
        if (tab_key, group_key) not in self._groups:
            raise KeyError("Unknown ribbon group {!r} in tab {!r}.".format(group_key, tab_key))
        key = self._key(key, "button")
        if key in self._buttons:
            raise ValueError("Ribbon button {!r} already exists.".format(key))
        return {
            "key": key,
            "tab": tab_key,
            "group": group_key,
            "label": str(label),
            "callback": callback,
            "visible": True,
            **state,
        }

    def _wrap_large_label(self, label: str, button_width: int | None = None) -> str:
        # Native-button fallback only. Real image tiles use pixel-aware wrapping.
        width = int(button_width or self.LARGE_BUTTON_WIDTH)
        lines = _RibbonTileTextures._wrapped_lines(
            label, max_width=max(24, width - 2 * self.TILE_TEXT_MARGIN))
        return "\n".join(lines[:2])

    def _add_large_image_command(self, record, parent, button_width, enabled):
        """Build a large command as one clickable tile, not stacked controls."""
        tile_texture = self._tile_texture(record)
        if tile_texture is None:
            tag = self.backend.add_button(
                label=self._wrap_large_label(record.get("label", ""), button_width), parent=parent,
                width=button_width, height=self.LARGE_BUTTON_HEIGHT,
                enabled=bool(enabled),
                callback=lambda *_args, button_key=record["key"]: self._button_clicked(button_key),
            )
            return tag, [tag], None

        tag = self.backend.add_image_button(
            tile_texture, parent=parent, width=button_width, height=self.LARGE_BUTTON_HEIGHT,
            enabled=bool(enabled), background_color=(0, 0, 0, 0),
            callback=lambda *_args, button_key=record["key"]: self._button_clicked(button_key),
        )
        record["image_tag"] = tag
        record["tile_texture"] = tile_texture
        record["large_image"] = True
        record["large_tile"] = True
        return tag, [tag], None

    def _small_button_parent(self, group, width):
        columns = group["small_columns"]
        column = columns[-1] if columns and columns[-1]["count"] < self.SMALL_ROWS else None
        if column is None:
            tag = self.backend.add_group(parent=group["row"], horizontal=False, horizontal_spacing=0)
            column = {"tag": tag, "count": 0, "width": int(width)}
            columns.append(column)
        column["count"] += 1
        column["width"] = max(column["width"], int(width))
        return column["tag"]

    def _display_label(self, record):
        label = str(record.get("label", ""))
        icon = record.get("icon")
        size = record.get("size", "small")
        menu_indicator = bool(record.get("menu_indicator"))
        if size == "large":
            if icon:
                result = "{}\n{}".format(icon, label)
            elif " " in label and len(label) > 10:
                result = label.replace(" ", "\n", 1)
            else:
                result = label
            if menu_indicator:
                result += "  v"
            return result
        prefix = "{}  ".format(icon) if icon else ""
        suffix = "  v" if menu_indicator else ""
        return "{}{}{}".format(prefix, label, suffix)

    def _button_clicked(self, key):
        record = self._buttons.get(str(key))
        if record is None or not record.get("enabled", True):
            return
        if record.get("checkable"):
            record["checked"] = not bool(record.get("checked"))
            self._refresh_button_theme(str(key))
            callback = record.get("callback")
            if callable(callback):
                callback(bool(record["checked"]))
            return
        callback = record.get("callback")
        if callable(callback):
            callback()

    def _create_menu(self, key, entries, *, min_width=180):
        # Keep RibbonBar importable without the native DearPyGui backend. Popup
        # rendering is loaded only when a ribbon menu is actually constructed.
        from ..widgets.menu import QMenu
        commands: dict[str, Callable] = {}
        actions = []
        for index, entry in enumerate(entries):
            if entry is None:
                actions.append({"separator": True, "label": "---", "action": "sep_{}".format(index)})
                continue
            if isinstance(entry, dict):
                spec = dict(entry)
                callback = spec.pop("callback", None)
                action = str(spec.get("action") or spec.get("id") or "{}_{}".format(key, index))
                spec.setdefault("id", action)
                spec.setdefault("action", action)
                actions.append(spec)
            else:
                if len(entry) < 2:
                    raise ValueError("Ribbon menu entries require (label, callback).")
                action = "{}_{}".format(key, index)
                actions.append({"id": action, "label": str(entry[0]), "action": action})
                callback = entry[1]
            if callable(callback):
                commands[action] = callback
        menu = QMenu(actions, backend=self.backend, min_width=min_width, max_width=420)
        menu.triggered.connect(lambda action, _context=None: self._menu_triggered(commands, action))
        self._menus.append(menu)
        return menu

    def _popup_menu(self, key, menu, *, anchor=None):
        record = self._buttons.get(str(key))
        if record is None:
            return
        anchor = anchor or record.get("arrow") or record.get("tag")
        try:
            from ..gui.placement import item_screen_rect, visible_item_screen_rect
            from ..backends.native_windows import NativeWindowBackend
            menu.popupBelow(
                item_screen_rect(self.backend, anchor),
                global_position=NativeWindowBackend(self.backend).isEnabled(),
                anchor_provider=lambda: visible_item_screen_rect(self.backend, anchor))
        except Exception:
            menu.popup()

    @staticmethod
    def _menu_triggered(commands, action):
        callback = commands.get(str(action))
        if callable(callback):
            callback()

    def _refresh_tab_theme(self, key):
        tab = self._tabs.get(str(key))
        if tab is None:
            return
        renderer = getattr(self, "_tab_renderer", None)
        if renderer is not None and tab.get("host") is not None:
            renderer.refresh(tab, active=str(key) == self._active_tab)
            return
        self.backend.bind_item_theme(
            tab["header"], self._tab_theme(str(key) == self._active_tab))

    def _refresh_button_theme(self, key):
        record = self._buttons.get(str(key))
        if record is None:
            return
        if record.get("large_tile") and record.get("image"):
            texture = self._tile_texture(record)
            if texture is not None and texture != record.get("tile_texture"):
                self.backend.configure_item(record["tag"], texture_tag=texture)
                record["tile_texture"] = texture
        if record.get("scope") == "application":
            theme = self._application_theme()
        else:
            theme = self._button_theme(
                checked=bool(record.get("checked")),
                disabled=not bool(record.get("enabled", True)),
                compact=record.get("size") == "quick",
            )
        image_tag = record.get("image_tag")
        label_tag = record.get("label_tag")
        for item in record.get("items", ()):
            if image_tag is not None and item == image_tag:
                self.backend.bind_item_theme(item, self._image_button_theme(
                    checked=bool(record.get("checked")),
                    disabled=not bool(record.get("enabled", True)),
                ))
            elif label_tag is not None and item == label_tag and record.get("large_image"):
                self.backend.bind_item_theme(item, self._large_label_theme(
                    checked=bool(record.get("checked")),
                    disabled=not bool(record.get("enabled", True)),
                ))
            else:
                self.backend.bind_item_theme(item, theme)

    def _add_tooltip(self, item, text):
        if not text:
            return
        try:
            from ..tooltip import add_styled_tooltip
            return add_styled_tooltip(item, text, backend=self.backend)
        except Exception:
            pass

    # --------------------------------------------------------------- themes
    # Public/internal method names remain on RibbonBar for compatibility; the
    # heavy theme construction now lives in RibbonThemeFactory.
    def _cached_theme(self, key, builder):
        return self._theme_factory._cached_theme(key, builder)

    def _surface_theme(self, kind):
        return self._theme_factory._surface_theme(kind)

    def _tab_theme(self, active):
        return self._theme_factory._tab_theme(active)

    def _button_theme(self, *, checked=False, disabled=False, compact=False):
        return self._theme_factory._button_theme(
            checked=checked, disabled=disabled, compact=compact)

    def _large_label_theme(self, *, checked=False, disabled=False):
        return self._theme_factory._large_label_theme(
            checked=checked, disabled=disabled)

    def _image_button_theme(self, *, checked=False, disabled=False):
        return self._theme_factory._image_button_theme(
            checked=checked, disabled=disabled)

    def _application_theme(self):
        return self._theme_factory._application_theme()

    def _text_theme(self, *, muted=False):
        return self._theme_factory._text_theme(muted=muted)


__all__ = ["RibbonInternalsMixin"]
