"""Internal layout, command dispatch, menu and theme helpers for RibbonBar."""
from __future__ import annotations

from typing import Callable

from .textures import RibbonTileTextures as _RibbonTileTextures


class RibbonInternalsMixin:
    def _reserve_group_width(self, group, slot, width):
        """Account for command columns, spacing and both nested window paddings."""
        slots = group["slot_widths"]
        slots[slot] = max(slots.get(slot, 0), int(width))
        content_width = sum(slots.values()) + self.COMMAND_GAP * max(0, len(slots) - 1)
        # Each width=-1 child also reserves one pixel at its right edge.
        padding = 2 * (self.GROUP_HORIZONTAL_PADDING + self.CONTROLS_HORIZONTAL_PADDING) + 2
        width = max(group["minimum_width"], content_width + padding)
        if width != group["width"]:
            self.backend.configure_item(group["tag"], width=width)
            group["width"] = width
        caption_space = group["caption_width"] + (20 if group["launcher"] is not None else 0)
        left_pad = max(2, (width - 2 * self.GROUP_HORIZONTAL_PADDING - caption_space) // 2)
        self.backend.configure_item(group["footer_spacer"], width=left_pad)

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

    @staticmethod
    def _wrap_large_label(label: str) -> str:
        # Native-button fallback only. Real image tiles use pixel-aware wrapping.
        lines = _RibbonTileTextures._wrapped_lines(label, max_width=84)
        return "\n".join(lines[:2])

    def _add_large_image_command(self, record, parent, button_width, enabled):
        """Build a large command as one clickable tile, not stacked controls."""
        tile_texture = _RibbonTileTextures.get(
            record.get("image"), record.get("label", ""), button_width,
            self.LARGE_BUTTON_HEIGHT, self.LARGE_ICON_SIZE,
            icon_path_resolver=self.icon_path_resolver, backend=self.backend)
        if tile_texture is None:
            tag = self.backend.add_button(
                label=self._wrap_large_label(record.get("label", "")), parent=parent,
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
            x, y = self.backend.get_item_rect_min(anchor)
            _width, height = self.backend.get_item_rect_size(anchor)
            menu.popup((x, y + height))
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
        self.backend.bind_item_theme(
            tab["header"], self._tab_theme(str(key) == self._active_tab))

    def _refresh_button_theme(self, key):
        record = self._buttons.get(str(key))
        if record is None:
            return
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
