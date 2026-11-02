"""Notification visual policy, independent of the host application."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class QNotificationTheme:
    width: int = 360
    min_height: int = 92
    max_height: int = 160
    margin: int = 14
    gap: int = 10
    corner_radius: int = 10
    padding_x: int = 16
    padding_y: int = 13
    icon_box: int = 28
    close_box: int = 28
    title_font_px: int = 14
    body_font_px: int = 13
    background: tuple = (249, 249, 249)
    border: tuple = (210, 210, 210)
    foreground: tuple = (28, 28, 28)
    secondary: tuple = (82, 82, 82)
    close_hover: tuple = (229, 229, 229)
    info_accent: tuple = (0, 103, 192)
    success_accent: tuple = (16, 124, 65)
    warning_accent: tuple = (196, 116, 0)
    error_accent: tuple = (196, 43, 28)

    def accent_for(self, kind):
        value = getattr(kind, "value", str(kind or "info"))
        return {
            "success": self.success_accent,
            "warning": self.warning_accent,
            "error": self.error_accent,
        }.get(value, self.info_accent)

    def scaled(self, dpi):
        scale = max(0.75, min(3.0, float(dpi or 96) / 96.0))
        values = {}
        for name in (
            "width", "min_height", "max_height", "margin", "gap",
            "corner_radius", "padding_x", "padding_y", "icon_box",
            "close_box", "title_font_px", "body_font_px",
        ):
            values[name] = max(1, int(round(getattr(self, name) * scale)))
        for name in (
            "background", "border", "foreground", "secondary", "close_hover",
            "info_accent", "success_accent", "warning_accent", "error_accent",
        ):
            values[name] = getattr(self, name)
        return QNotificationTheme(**values)


__all__ = ["QNotificationTheme"]
