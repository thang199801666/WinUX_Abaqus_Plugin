"""Notification visual policy, independent of the host application."""
from __future__ import annotations

from dataclasses import dataclass

from ..gui.palette import QtFusionPalette


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
    background: tuple | None = None
    border: tuple | None = None
    foreground: tuple | None = None
    secondary: tuple | None = None
    close_hover: tuple | None = None
    info_accent: tuple | None = None
    success_accent: tuple | None = None
    warning_accent: tuple | None = None
    error_accent: tuple | None = None

    def __post_init__(self):
        # Resolve defaults at instance creation, not module import time.  Toasts
        # created after a live Light/Dark switch therefore use the same palette
        # as the rest of the application. Explicit custom colors remain intact.
        p = QtFusionPalette
        defaults = {
            "background": p.MENU[:3],
            "border": p.BORDER[:3],
            "foreground": p.TEXT[:3],
            "secondary": p.TEXT_MUTED[:3],
            "close_hover": p.BUTTON_HOVER[:3],
            "info_accent": p.INFO[:3],
            "success_accent": p.SUCCESS[:3],
            "warning_accent": p.WARNING[:3],
            "error_accent": p.DANGER[:3],
        }
        for name, value in defaults.items():
            if getattr(self, name) is None:
                object.__setattr__(self, name, tuple(value))

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
