"""Shared Qt/Fusion-like visual constants for DearUIQt widgets.

This module intentionally contains no Dear PyGui or Tk imports.  Both UI stacks
use the same palette so a dialog opened from a Dear PyGui view looks like it
belongs to the same application as a native Tk helper window.
"""

from __future__ import annotations


class QtFusionPalette:
    # Core Qt/Fusion neutrals.
    WINDOW = (243, 243, 243, 255)
    WINDOW_ALT = (248, 249, 250, 255)
    BASE = (255, 255, 255, 255)
    ALTERNATE_BASE = (247, 247, 247, 255)
    TOOLBAR = (246, 248, 250, 255)
    MENU = (250, 250, 250, 255)
    TITLE = (245, 247, 249, 255)
    TITLE_ACTIVE = (238, 244, 249, 255)
    TITLE_BORDER = (206, 214, 222, 255)
    DOCK_BUTTON_HOVER = (226, 238, 248, 255)
    DOCK_BUTTON_ACTIVE = (210, 228, 242, 255)

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

    BORDER = (180, 185, 190, 255)
    BORDER_LIGHT = (214, 218, 222, 255)
    BORDER_DARK = (132, 137, 143, 255)
    SHADOW = (0, 0, 0, 38)

    BUTTON = (250, 250, 250, 255)
    BUTTON_HOVER = (235, 245, 252, 255)
    BUTTON_ACTIVE = (215, 234, 248, 255)
    BUTTON_DISABLED = (241, 241, 241, 255)

    HIGHLIGHT = (0, 120, 215, 255)
    HIGHLIGHT_HOVER = (229, 243, 251, 255)
    HIGHLIGHT_SOFT = (204, 232, 255, 255)
    HIGHLIGHT_TEXT = (255, 255, 255, 255)
    HEADER_HOVER = (232, 241, 249, 255)
    HEADER_PRESSED = (218, 232, 244, 255)
    # Data-table chrome, shared with the Job Schedule reference appearance.
    # Do not reuse TOOLBAR/BORDER: those roles also style unrelated controls.
    TABLE_HEADER = (242, 246, 250, 255)
    TABLE_HEADER_TEXT = (41, 50, 62, 255)
    TABLE_ROW = (255, 255, 255, 255)
    TABLE_ROW_ALT = (249, 250, 252, 255)
    TABLE_BORDER = (211, 217, 224, 255)
    TABLE_GRID = (232, 235, 239, 255)
    MENU_HOVER = (229, 241, 251, 255)
    MENU_ACTIVE = (204, 228, 247, 255)
    TAB_ACTIVE_LINE = HIGHLIGHT

    PRIMARY = (0, 120, 215, 255)
    PRIMARY_HOVER = (0, 105, 190, 255)
    PRIMARY_ACTIVE = (0, 90, 165, 255)

    DANGER = (196, 43, 28, 255)
    DANGER_HOVER = (168, 35, 24, 255)
    DANGER_ACTIVE = (145, 30, 20, 255)

    # Semantic feedback roles.  Widgets should use these rather than baking
    # Light-theme status colors into retained resources.
    SUCCESS = (26, 127, 55, 255)
    SUCCESS_BG = (229, 244, 233, 255)
    WARNING = (176, 104, 0, 255)
    WARNING_BG = (255, 244, 214, 255)
    ERROR_BG = (252, 235, 233, 255)
    INFO = PRIMARY
    INFO_BG = (229, 243, 251, 255)
    PLACEHOLDER_TEXT = (118, 118, 118, 255)

    # Neutral tooltip surface.  The old pale-yellow system tooltip looked
    # disconnected from the rest of the Qt/Windows 11 chrome.
    TOOLTIP_BG = (250, 252, 254, 255)
    TOOLTIP_BORDER = (190, 198, 206, 255)


# Runtime-selectable application color scheme.  QtFusionPalette remains the
# public compatibility surface; changing the scheme updates its color-role
# attributes in place so existing DearUIQt theme factories automatically use
# the active palette when they materialize a new theme.
_COLOR_SCHEME = "Light"

_LIGHT_FUSION_COLORS = {
    name: getattr(QtFusionPalette, name)
    for name in (
        "WINDOW", "WINDOW_ALT", "BASE", "ALTERNATE_BASE", "TOOLBAR", "MENU",
        "TITLE", "TITLE_ACTIVE", "TITLE_BORDER", "DOCK_BUTTON_HOVER",
        "DOCK_BUTTON_ACTIVE", "TEXT", "TEXT_MUTED", "TEXT_DISABLED", "FOCUS",
        "SELECTION_ACTIVE", "SELECTION_ACTIVE_HOVER", "SELECTION_ACTIVE_PRESSED",
        "SELECTION_TEXT", "SELECTION_BORDER", "SELECTION_INACTIVE",
        "SELECTION_INACTIVE_BORDER", "BORDER", "BORDER_LIGHT", "BORDER_DARK",
        "SHADOW", "BUTTON", "BUTTON_HOVER", "BUTTON_ACTIVE", "BUTTON_DISABLED",
        "HIGHLIGHT", "HIGHLIGHT_HOVER", "HIGHLIGHT_SOFT", "HIGHLIGHT_TEXT",
        "HEADER_HOVER", "HEADER_PRESSED", "TABLE_HEADER", "TABLE_HEADER_TEXT",
        "TABLE_ROW", "TABLE_ROW_ALT", "TABLE_BORDER", "TABLE_GRID", "MENU_HOVER",
        "MENU_ACTIVE", "TAB_ACTIVE_LINE", "PRIMARY", "PRIMARY_HOVER",
        "PRIMARY_ACTIVE", "DANGER", "DANGER_HOVER", "DANGER_ACTIVE",
        "SUCCESS", "SUCCESS_BG", "WARNING", "WARNING_BG", "ERROR_BG",
        "INFO", "INFO_BG", "PLACEHOLDER_TEXT", "TOOLTIP_BG", "TOOLTIP_BORDER",
    )
}

_DARK_FUSION_COLORS = {
    "WINDOW": (31, 31, 31, 255),
    "WINDOW_ALT": (36, 36, 36, 255),
    "BASE": (25, 25, 25, 255),
    "ALTERNATE_BASE": (30, 30, 30, 255),
    "TOOLBAR": (35, 35, 35, 255),
    "MENU": (38, 38, 38, 255),
    "TITLE": (33, 33, 33, 255),
    "TITLE_ACTIVE": (38, 43, 48, 255),
    "TITLE_BORDER": (72, 72, 72, 255),
    "DOCK_BUTTON_HOVER": (53, 63, 72, 255),
    "DOCK_BUTTON_ACTIVE": (57, 78, 94, 255),
    "TEXT": (232, 232, 232, 255),
    "TEXT_MUTED": (170, 170, 170, 255),
    "TEXT_DISABLED": (118, 118, 118, 255),
    "FOCUS": (0, 120, 215, 255),
    "SELECTION_ACTIVE": (0, 88, 158, 255),
    "SELECTION_ACTIVE_HOVER": (0, 103, 181, 255),
    "SELECTION_ACTIVE_PRESSED": (0, 113, 195, 255),
    "SELECTION_TEXT": (246, 246, 246, 255),
    "SELECTION_BORDER": (55, 153, 220, 255),
    "SELECTION_INACTIVE": (57, 57, 57, 255),
    "SELECTION_INACTIVE_BORDER": (85, 85, 85, 255),
    "BORDER": (82, 82, 82, 255),
    "BORDER_LIGHT": (66, 66, 66, 255),
    "BORDER_DARK": (105, 105, 105, 255),
    "SHADOW": (0, 0, 0, 90),
    "BUTTON": (45, 45, 45, 255),
    "BUTTON_HOVER": (57, 62, 66, 255),
    "BUTTON_ACTIVE": (65, 76, 84, 255),
    "BUTTON_DISABLED": (38, 38, 38, 255),
    "HIGHLIGHT": (0, 120, 215, 255),
    "HIGHLIGHT_HOVER": (48, 61, 72, 255),
    "HIGHLIGHT_SOFT": (45, 70, 90, 255),
    "HIGHLIGHT_TEXT": (255, 255, 255, 255),
    "HEADER_HOVER": (52, 61, 69, 255),
    "HEADER_PRESSED": (59, 72, 82, 255),
    "TABLE_HEADER": (39, 42, 46, 255),
    "TABLE_HEADER_TEXT": (232, 236, 240, 255),
    "TABLE_ROW": (25, 25, 25, 255),
    "TABLE_ROW_ALT": (29, 29, 29, 255),
    "TABLE_BORDER": (69, 69, 69, 255),
    "TABLE_GRID": (54, 54, 54, 255),
    "MENU_HOVER": (48, 64, 77, 255),
    "MENU_ACTIVE": (53, 79, 99, 255),
    "TAB_ACTIVE_LINE": (0, 120, 215, 255),
    "PRIMARY": (0, 120, 215, 255),
    "PRIMARY_HOVER": (18, 136, 230, 255),
    "PRIMARY_ACTIVE": (0, 100, 185, 255),
    "DANGER": (196, 60, 52, 255),
    "DANGER_HOVER": (214, 72, 63, 255),
    "DANGER_ACTIVE": (170, 47, 40, 255),
    "SUCCESS": (92, 196, 118, 255),
    "SUCCESS_BG": (30, 67, 42, 255),
    "WARNING": (232, 180, 78, 255),
    "WARNING_BG": (72, 57, 27, 255),
    "ERROR_BG": (79, 39, 38, 255),
    "INFO": (85, 172, 235, 255),
    "INFO_BG": (35, 61, 80, 255),
    "PLACEHOLDER_TEXT": (135, 135, 135, 255),
    "TOOLTIP_BG": (45, 45, 45, 255),
    "TOOLTIP_BORDER": (86, 86, 86, 255),
}

def normalize_color_scheme(value):
    text = str(value or "").strip().casefold()
    return "Dark" if text == "dark" else "Light"

def color_scheme():
    return _COLOR_SCHEME

def set_color_scheme(value):
    """Set the process-wide Qt/Fusion color scheme to ``Light`` or ``Dark``.

    The operation is renderer-neutral: it only updates palette role values.
    Themes materialized afterwards pick up the new colors.
    """
    global _COLOR_SCHEME
    scheme = normalize_color_scheme(value)
    colors = _DARK_FUSION_COLORS if scheme == "Dark" else _LIGHT_FUSION_COLORS
    for name, color in colors.items():
        setattr(QtFusionPalette, name, tuple(color))
    _COLOR_SCHEME = scheme
    # Keep an already-imported shared scrollbar coherent without importing
    # renderer modules during early application startup.
    try:
        import sys
        module = sys.modules.get("DearUIQt.backends.dearpygui_scroller")
        palette = getattr(module, "SharedScrollerPalette", None) if module else None
        if palette is not None:
            palette.refresh_color_scheme(scheme)

        # Some retained subsystems intentionally cache style objects instead of
        # reading QtFusionPalette on every paint.  If they are already loaded,
        # give them a cheap palette-refresh hook without importing UI modules
        # during early startup.
        for module_name, hook_name in (
            ("DearUIQt.ribbon.visual_styles", "refresh_builtin_visual_styles"),
        ):
            loaded = sys.modules.get(module_name)
            hook = getattr(loaded, hook_name, None) if loaded else None
            if callable(hook):
                hook()
    except Exception:
        pass
    return scheme


class QtFusionMetrics:
    TABLE_CELL_PADDING = (6, 3)
    # Qt Fusion uses compact square-ish controls; keep radii intentionally low.
    WINDOW_ROUNDING = 3
    POPUP_ROUNDING = 2
    FRAME_ROUNDING = 5
    # Editors and command buttons share a subtle Windows 11-style radius.
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


__all__ = ["QtFusionPalette", "QtFusionMetrics", "QPalette", "color_hex",
           "normalize_color_scheme", "color_scheme", "set_color_scheme"]


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
