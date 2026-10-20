"""Public ribbon state mutation API shared by :class:`RibbonBar`."""
from __future__ import annotations

from .textures import RibbonTileTextures as _RibbonTileTextures


class RibbonStateMixin:
    def button_tag(self, key: str):
        record = self._buttons.get(str(key))
        return None if record is None else record.get("tag")

    def set_button_enabled(self, key: str, enabled: bool) -> bool:
        record = self._buttons.get(str(key))
        if record is None:
            return False
        record["enabled"] = bool(enabled)
        for item in record.get("items", ()):
            self.backend.configure_item(item, enabled=bool(enabled))
        self._refresh_button_theme(str(key))
        return True

    def set_button_visible(self, key: str, visible: bool) -> bool:
        record = self._buttons.get(str(key))
        if record is None:
            return False
        record["visible"] = bool(visible)
        target = record.get("container") or record.get("tag")
        if target is not None:
            self.backend.configure_item(target, show=bool(visible))
        return True

    def set_button_checked(self, key: str, checked: bool) -> bool:
        record = self._buttons.get(str(key))
        if record is None or not record.get("checkable"):
            return False
        record["checked"] = bool(checked)
        self._refresh_button_theme(str(key))
        return True

    def is_button_checked(self, key: str) -> bool:
        record = self._buttons.get(str(key))
        return bool(record and record.get("checked"))

    def set_button_label(self, key: str, label: str) -> bool:
        record = self._buttons.get(str(key))
        if record is None:
            return False
        record["label"] = str(label)
        if record.get("large_tile") and record.get("image"):
            texture = _RibbonTileTextures.get(
                record["image"], record["label"],
                int(record.get("width") or self.LARGE_BUTTON_WIDTH),
                self.LARGE_BUTTON_HEIGHT, self.LARGE_ICON_SIZE,
                icon_path_resolver=self.icon_path_resolver, backend=self.backend)
            if texture is not None:
                try:
                    self.backend.configure_item(record["tag"], texture_tag=texture)
                    record["tile_texture"] = texture
                    return True
                except Exception:
                    pass
        target = record.get("label_tag") if record.get("large_image") else record.get("tag")
        if target is not None:
            value = self._wrap_large_label(record["label"]) if record.get("large_image") else self._display_label(record)
            self.backend.configure_item(target, label=value)
        return True

    def _load_texture(self, image: str | None, pixel_size: int):
        """Resolve an image through the host-provided texture loader.

        The framework intentionally knows nothing about an application's resource
        directory. Hosts may pass ``texture_loader(name, pixel_size)`` or omit it
        when text-only commands are sufficient.
        """
        if not image or self.texture_loader is None:
            return None
        try:
            return self.texture_loader(image, pixel_size)
        except TypeError:
            return self.texture_loader(image, pixel_size=pixel_size)

    def set_button_icon(self, key: str, icon: str | None) -> bool:
        record = self._buttons.get(str(key))
        if record is None:
            return False
        record["icon"] = icon
        self.backend.configure_item(record["tag"], label=self._display_label(record))
        return True

    def set_button_image(self, key: str, image: str | None) -> bool:
        record = self._buttons.get(str(key))
        if record is None:
            return False
        record["image"] = image
        image_tag = record.get("image_tag")
        if image_tag is None or not image:
            return image_tag is None
        if record.get("large_tile"):
            texture = _RibbonTileTextures.get(
                image, record.get("label", ""), int(record.get("width") or self.LARGE_BUTTON_WIDTH),
                self.LARGE_BUTTON_HEIGHT, self.LARGE_ICON_SIZE,
                icon_path_resolver=self.icon_path_resolver, backend=self.backend)
        else:
            pixel_size = 16 if record.get("scope") == "quick" else self.LARGE_ICON_SIZE
            texture = self._load_texture(image, pixel_size)
        if texture is None:
            return False
        try:
            self.backend.configure_item(image_tag, texture_tag=texture)
        except Exception:
            try:
                self.backend.set_value(image_tag, texture)
            except Exception:
                return False
        record["tile_texture"] = texture if record.get("large_tile") else record.get("tile_texture")
        return True

    def set_minimized(self, minimized: bool) -> bool:
        minimized = bool(minimized)
        if self._minimized == minimized:
            return False
        self._minimized = minimized
        self.backend.configure_item(self.body, show=not minimized)
        new_height = self._quick_height + self.TAB_HEIGHT + 6 if minimized else self._expanded_height
        self.height = new_height
        self.backend.configure_item(self.tag, height=new_height)
        if not minimized and self._active_tab in self._tabs:
            self.backend.configure_item(self._tabs[self._active_tab]["page"], show=True)
        return True

    def toggle_minimized(self):
        self.set_minimized(not self._minimized)
        return self._minimized

    def is_minimized(self) -> bool:
        return self._minimized

    def delete(self):
        if self._deleted:
            return
        for menu in tuple(self._menus):
            try:
                menu.delete()
            except Exception:
                pass
        self._menus.clear()
        super().delete()


__all__ = ["RibbonStateMixin"]
