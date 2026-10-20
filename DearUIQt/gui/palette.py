"""Shared Qt/Fusion-like visual constants for DearUIQt widgets.

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
    # Keep focus/accent blue strong, but make row selection match the light
    # Windows Explorer selection surface instead of a saturated blue fill.
    FOCUS = (0, 120, 215, 255)
    SELECTION_ACTIVE = (204, 232, 255, 255)
    SELECTION_ACTIVE_HOVER = (191, 225, 250, 255)
    SELECTION_ACTIVE_PRESSED = (181, 219, 247, 255)
    SELECTION_TEXT = (32, 32, 32, 255)
    SELECTION_BORDER = (153, 209, 255, 255)
    SELECTION_INACTIVE = (225, 233, 240, 255)
    SELECTION_INACTIVE_BORDER = (185, 197, 210, 255)

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
    # Windows 11-style command buttons use a noticeably softer radius while
    # editors/list cells retain the tighter Qt/Fusion frame radius above.
    BUTTON_ROUNDING = 5
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


__all__ = ["QtFusionPalette", "QtFusionMetrics", "QPalette", "color_hex"]


class QPalette:
    """Toolkit-neutral Qt-style palette value.

    The object stores color roles independently from Dear PyGui theme objects.
    Widgets and applications can therefore exchange palettes without importing
    the renderer; a backend/style may translate roles into native themes later.
    """

    Active = 0
    Disabled = 1
    Inactive = 2
    Normal = Active

    Window = 0
    WindowText = 1
    Base = 2
    AlternateBase = 3
    Text = 4
    Button = 5
    ButtonText = 6
    Highlight = 7
    HighlightedText = 8
    ToolTipBase = 9
    ToolTipText = 10
    PlaceholderText = 11
    Light = 12
    Midlight = 13
    Mid = 14
    Dark = 15
    Shadow = 16
    Link = 17
    LinkVisited = 18

    _GROUPS = (Active, Disabled, Inactive)

    def __init__(self, other=None):
        self._colors = {group: {} for group in self._GROUPS}
        if isinstance(other, QPalette):
            for group in self._GROUPS:
                self._colors[group].update(other._colors[group])
        elif other is not None:
            raise TypeError("QPalette expects another QPalette or None")

    @staticmethod
    def _normalize_color(color):
        values = tuple(int(value) for value in color)
        if len(values) == 3:
            values += (255,)
        if len(values) != 4:
            raise ValueError("palette colors must be RGB or RGBA tuples")
        return tuple(max(0, min(255, value)) for value in values)

    @classmethod
    def fusion(cls):
        p = QtFusionPalette
        palette = cls()
        active = {
            cls.Window: p.WINDOW,
            cls.WindowText: p.TEXT,
            cls.Base: p.BASE,
            cls.AlternateBase: p.ALTERNATE_BASE,
            cls.Text: p.TEXT,
            cls.Button: p.BUTTON,
            cls.ButtonText: p.TEXT,
            cls.Highlight: p.HIGHLIGHT,
            cls.HighlightedText: p.HIGHLIGHT_TEXT,
            cls.ToolTipBase: p.TOOLTIP_BG,
            cls.ToolTipText: p.TEXT,
            cls.PlaceholderText: p.TEXT_MUTED,
            cls.Light: p.BORDER_LIGHT,
            cls.Midlight: p.BORDER_LIGHT,
            cls.Mid: p.BORDER,
            cls.Dark: p.BORDER_DARK,
            cls.Shadow: p.SHADOW,
            cls.Link: p.PRIMARY,
            cls.LinkVisited: (85, 26, 139, 255),
        }
        inactive = dict(active)
        inactive[cls.Highlight] = p.SELECTION_INACTIVE
        inactive[cls.HighlightedText] = p.TEXT
        disabled = dict(active)
        for role in (cls.WindowText, cls.Text, cls.ButtonText, cls.PlaceholderText,
                     cls.ToolTipText, cls.Link, cls.LinkVisited):
            disabled[role] = p.TEXT_DISABLED
        disabled[cls.Button] = p.BUTTON_DISABLED
        disabled[cls.Highlight] = p.SELECTION_INACTIVE
        disabled[cls.HighlightedText] = p.TEXT_DISABLED
        palette._colors[cls.Active].update(active)
        palette._colors[cls.Inactive].update(inactive)
        palette._colors[cls.Disabled].update(disabled)
        return palette

    def setColor(self, *args):
        if len(args) == 2:
            role, color = args
            color = self._normalize_color(color)
            for group in self._GROUPS:
                self._colors[group][int(role)] = color
            return
        if len(args) == 3:
            group, role, color = args
            group = int(group)
            if group not in self._colors:
                raise ValueError("unknown color group")
            self._colors[group][int(role)] = self._normalize_color(color)
            return
        raise TypeError("setColor(role, color) or setColor(group, role, color)")

    def color(self, *args):
        if len(args) == 1:
            group, role = self.Active, args[0]
        elif len(args) == 2:
            group, role = args
        else:
            raise TypeError("color(role) or color(group, role)")
        group = int(group)
        role = int(role)
        if group not in self._colors:
            raise ValueError("unknown color group")
        value = self._colors[group].get(role)
        if value is None and group != self.Active:
            value = self._colors[self.Active].get(role)
        return value

    def resolve(self, other):
        if not isinstance(other, QPalette):
            raise TypeError("resolve expects QPalette")
        merged = other.copy()
        for group in self._GROUPS:
            merged._colors[group].update(self._colors[group])
        return merged

    def copy(self):
        return QPalette(self)

    def __eq__(self, other):
        if not isinstance(other, QPalette):
            return NotImplemented
        return self._colors == other._colors

    def __repr__(self):
        return "QPalette(active_roles={}, disabled_roles={}, inactive_roles={})".format(
            len(self._colors[self.Active]), len(self._colors[self.Disabled]),
            len(self._colors[self.Inactive]))
