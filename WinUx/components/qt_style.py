"""Shared Qt/Fusion-like visual constants for WinUx widgets.

This module intentionally contains no Dear PyGui or Tk imports.  Both UI stacks
use the same palette so a dialog opened from a Dear PyGui view looks like it
belongs to the same application as a native Tk helper window.
"""

from __future__ import annotations


class QtFusionPalette:
    # Core Qt/Fusion neutrals.
    WINDOW = (240, 240, 240, 255)
    WINDOW_ALT = (245, 245, 245, 255)
    BASE = (255, 255, 255, 255)
    ALTERNATE_BASE = (247, 247, 247, 255)
    TOOLBAR = (245, 245, 245, 255)
    MENU = (248, 248, 248, 255)
    TITLE = (239, 239, 239, 255)
    TITLE_ACTIVE = (232, 232, 232, 255)

    TEXT = (32, 32, 32, 255)
    TEXT_MUTED = (96, 96, 96, 255)
    TEXT_DISABLED = (130, 130, 130, 255)

    # Focus/selection roles used by item views and editable controls.
    FOCUS = (0, 120, 215, 255)
    SELECTION_INACTIVE = (225, 225, 225, 255)
    SELECTION_INACTIVE_BORDER = (170, 170, 170, 255)

    BORDER = (171, 171, 171, 255)
    BORDER_LIGHT = (205, 205, 205, 255)
    BORDER_DARK = (128, 128, 128, 255)
    SHADOW = (0, 0, 0, 38)

    BUTTON = (240, 240, 240, 255)
    BUTTON_HOVER = (229, 241, 251, 255)
    BUTTON_ACTIVE = (204, 228, 247, 255)
    BUTTON_DISABLED = (235, 235, 235, 255)

    HIGHLIGHT = (0, 120, 215, 255)
    HIGHLIGHT_HOVER = (229, 243, 251, 255)
    HIGHLIGHT_SOFT = (204, 232, 255, 255)
    HIGHLIGHT_TEXT = (255, 255, 255, 255)
    HEADER_HOVER = (232, 240, 247, 255)
    HEADER_PRESSED = (214, 230, 242, 255)
    MENU_HOVER = (229, 241, 251, 255)
    MENU_ACTIVE = (204, 228, 247, 255)
    TAB_ACTIVE_LINE = HIGHLIGHT

    PRIMARY = (0, 120, 215, 255)
    PRIMARY_HOVER = (0, 105, 190, 255)
    PRIMARY_ACTIVE = (0, 90, 165, 255)

    DANGER = (196, 43, 28, 255)
    DANGER_HOVER = (168, 35, 24, 255)
    DANGER_ACTIVE = (145, 30, 20, 255)

    TOOLTIP_BG = (255, 255, 220, 255)
    TOOLTIP_BORDER = (118, 118, 118, 255)


class QtFusionMetrics:
    # Qt Fusion uses compact square-ish controls; keep radii intentionally low.
    WINDOW_ROUNDING = 3
    POPUP_ROUNDING = 2
    FRAME_ROUNDING = 2
    CHILD_ROUNDING = 2
    SCROLLBAR_ROUNDING = 2
    GRAB_ROUNDING = 2

    FRAME_BORDER = 1
    WINDOW_BORDER = 1
    FRAME_PAD_X = 6
    FRAME_PAD_Y = 3
    ITEM_SPACING_X = 7
    ITEM_SPACING_Y = 5

    BUTTON_HEIGHT = 26
    CHECKBOX_PAD = 1
    FOCUS_BORDER = 1
    HEADER_HEIGHT = 28
    ROW_HEIGHT = 24


def color_hex(color) -> str:
    """Convert an RGB(A) tuple into a Tk-compatible ``#rrggbb`` string."""
    r, g, b = [max(0, min(255, int(value))) for value in color[:3]]
    return "#{:02x}{:02x}{:02x}".format(r, g, b)


__all__ = ["QtFusionPalette", "QtFusionMetrics", "color_hex"]
