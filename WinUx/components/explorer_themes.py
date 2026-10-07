"""GUI-independent Explorer theme names, palettes and registration."""
from __future__ import annotations
from .qt_style import QtFusionPalette

class ListViewTheme:
    EXPLORER = "Explorer"
    WHITE = "White"
    BLACK = "Black"
    DARK = "Dark"
    BLUE = "Blue"
    DARK_BLUE = "Dark Blue"
    LIGHT_BLUE = "Light Blue"
    GRAY = "Gray"
    GREEN = "Green"
    RED = "Red"
    PURPLE = "Purple"
    VSCODE = "VS Code"
    GITHUB = "GitHub"
    WINSCP = "WinSCP"
    JOB_VIEWER = "Job Viewer"


class ListViewThemeManager:
    """Registry for built-in and application-defined ExplorerListView themes."""

    _themes = {
        "Explorer": {
            # Qt/Fusion-like item-view palette.  The control remains Explorer-
            # familiar, but headers, selection, focus and disabled surfaces use
            # the same shared palette as WinUx dialogs and dock widgets.
            "background": QtFusionPalette.BASE, "header_bg": QtFusionPalette.TOOLBAR,
            "header_hover": QtFusionPalette.HEADER_HOVER,
            "header_pressed": QtFusionPalette.HEADER_PRESSED,
            "text": QtFusionPalette.TEXT, "header_text": QtFusionPalette.TEXT,
            "border": QtFusionPalette.BORDER, "separator": QtFusionPalette.BORDER_LIGHT,
            "header_top_line": QtFusionPalette.BASE,
            "header_bottom_line": QtFusionPalette.BORDER_LIGHT,
            "row_line": QtFusionPalette.BORDER_LIGHT,
            "show_row_lines": False, "row_rounding": 0.0,
            "hover_fill": QtFusionPalette.HIGHLIGHT_HOVER,
            "hover_border": (0, 0, 0, 0),
            "selected_fill": QtFusionPalette.SELECTION_ACTIVE,
            "selected_border": QtFusionPalette.SELECTION_BORDER,
            "selected_hover_fill": QtFusionPalette.SELECTION_ACTIVE_HOVER,
            "selected_text": QtFusionPalette.SELECTION_TEXT,
            "inactive_selected_fill": QtFusionPalette.SELECTION_INACTIVE,
            "inactive_selected_border": (0, 0, 0, 0),
            "inactive_selected_text": QtFusionPalette.TEXT,
            "focus_border": QtFusionPalette.FOCUS,
            # Header labels are centered uniformly across WinUx list views.
            "header_alignment": "center",
            "drop_fill": (214, 239, 255, 255), "drop_border": QtFusionPalette.HIGHLIGHT,
            "status_bg": QtFusionPalette.BASE, "status_text": QtFusionPalette.TEXT_MUTED,
            "rubber_fill": (0, 120, 215, 38), "rubber_border": QtFusionPalette.HIGHLIGHT,
            "drag_bg": (255, 255, 255, 238), "drag_text": QtFusionPalette.TEXT,
            "drag_border": QtFusionPalette.BORDER, "drag_accent": QtFusionPalette.HIGHLIGHT,
        },
        "Job Viewer": {
            # Visual contract from the pre-migration WinUx job table.  Keep it
            # independent from generic Explorer/file panels so later item-view
            # work cannot silently change the scheduler table again.
            "background": (255, 255, 255, 255),
            "header_bg": (248, 250, 252, 255),
            "header_hover": (235, 242, 248, 255),
            "header_pressed": (220, 232, 243, 255),
            "text": (38, 50, 56, 255),
            "header_text": (23, 32, 51, 255),
            "border": (215, 225, 238, 255),
            "separator": (215, 225, 238, 255),
            "header_top_line": (255, 255, 255, 255),
            "header_bottom_line": (205, 215, 226, 255),
            "row_line": (255, 255, 255, 255),
            "show_row_lines": False,
            "row_rounding": 0.0,
            "hover_fill": (229, 243, 255, 255),
            "hover_border": (112, 192, 242, 255),
            "selected_fill": QtFusionPalette.SELECTION_ACTIVE,
            "selected_border": QtFusionPalette.SELECTION_BORDER,
            "selected_hover_fill": QtFusionPalette.SELECTION_ACTIVE_HOVER,
            "selected_text": QtFusionPalette.SELECTION_TEXT,
            "inactive_selected_fill": QtFusionPalette.SELECTION_INACTIVE,
            "inactive_selected_border": QtFusionPalette.SELECTION_INACTIVE_BORDER,
            "inactive_selected_text": QtFusionPalette.TEXT,
            "focus_border": (91, 155, 213, 255),
            "drop_fill": (214, 239, 255, 255),
            "drop_border": (0, 120, 215, 255),
            "status_bg": (255, 255, 255, 255),
            "status_text": (110, 110, 110, 255),
            "rubber_fill": (51, 153, 255, 45),
            "rubber_border": (51, 153, 255, 255),
            "drag_bg": (255, 255, 255, 238),
            "drag_text": (25, 25, 25, 255),
            "drag_border": (170, 170, 170, 230),
            "drag_accent": (0, 120, 215, 255),
            # Keep all Job Viewer header labels visually centered regardless
            # of the data-cell alignment used by each column.
            "header_alignment": "center",
            # Keep the sort marker in the standard right-side header sub-area.
            "sort_indicator_mode": "edge",
        },
        "WinSCP": {
            # Commander-style file panel palette modelled after WinSCP's
            # native Windows details view.  This theme is intentionally
            # separate from Explorer so Job Viewer and generic list views keep
            # their Qt/Fusion appearance.
            "background": (255, 255, 255, 255),
            "header_bg": (245, 245, 245, 255),
            "header_hover": (229, 241, 251, 255),
            "header_pressed": (204, 228, 247, 255),
            "header_text": (24, 24, 24, 255),
            "text": (25, 25, 25, 255),
            "border": (188, 188, 188, 255),
            "separator": (210, 210, 210, 255),
            "header_top_line": (255, 255, 255, 255),
            "header_bottom_line": (183, 183, 183, 255),
            "row_line": (255, 255, 255, 0),
            "show_row_lines": False,
            "row_rounding": 0.0,
            "hover_fill": (229, 243, 255, 255),
            "hover_border": (174, 210, 235, 255),
            "selected_fill": QtFusionPalette.SELECTION_ACTIVE,
            "selected_border": QtFusionPalette.SELECTION_BORDER,
            "selected_hover_fill": QtFusionPalette.SELECTION_ACTIVE_HOVER,
            "selected_text": QtFusionPalette.SELECTION_TEXT,
            "inactive_selected_fill": QtFusionPalette.SELECTION_INACTIVE,
            "inactive_selected_border": QtFusionPalette.SELECTION_INACTIVE_BORDER,
            "inactive_selected_text": QtFusionPalette.TEXT,
            "focus_border": (0, 84, 153, 255),
            "drop_fill": (205, 232, 255, 255),
            "drop_border": (0, 102, 184, 255),
            "status_bg": (250, 250, 250, 255),
            "status_text": (80, 80, 80, 255),
            "rubber_fill": (0, 120, 215, 32),
            "rubber_border": (0, 120, 215, 255),
            "drag_bg": (255, 255, 255, 244),
            "drag_text": (25, 25, 25, 255),
            "drag_border": (170, 170, 170, 255),
            "drag_accent": (0, 120, 215, 255),
            # File panel headers use the same centered-label contract as the
            # rest of WinUx while cell contents keep their own alignments.
            "header_alignment": "center",
        },
        "White": {
            "background": (255, 255, 255, 255), "header_bg": (245, 245, 245, 255),
            "text": (25, 25, 25, 255), "header_text": (15, 15, 15, 255),
            "border": (205, 205, 205, 255), "separator": (210, 210, 210, 255),
            "row_line": (242, 242, 242, 255), "hover_fill": (240, 246, 252, 255),
            "hover_border": (155, 195, 230, 255), "selected_fill": (215, 235, 252, 255),
            "selected_border": (75, 150, 215, 255), "selected_hover_fill": (195, 225, 250, 255),
            "drop_fill": (220, 240, 255, 255), "drop_border": (30, 125, 210, 255),
            "status_bg": (250, 250, 250, 255), "status_text": (95, 95, 95, 255),
        },
        "Black": {
            "background": (20, 20, 20, 255), "header_bg": (28, 28, 28, 255),
            "text": (238, 238, 238, 255), "header_text": (255, 255, 255, 255),
            "border": (62, 62, 62, 255), "separator": (72, 72, 72, 255),
            "row_line": (36, 36, 36, 255), "hover_fill": (48, 48, 48, 255),
            "hover_border": (105, 105, 105, 255), "selected_fill": (0, 92, 160, 255),
            "selected_border": (45, 150, 225, 255), "selected_hover_fill": (0, 112, 190, 255),
            "drop_fill": (20, 75, 110, 255), "drop_border": (65, 175, 240, 255),
            "status_bg": (24, 24, 24, 255), "status_text": (185, 185, 185, 255),
            "rubber_fill": (30, 140, 230, 50), "rubber_border": (65, 175, 245, 255),
            "drag_bg": (35, 35, 35, 245), "drag_text": (245, 245, 245, 255),
            "drag_border": (95, 95, 95, 255), "drag_accent": (35, 150, 235, 255),
        },
        "Dark": {
            "background": (32, 32, 32, 255), "header_bg": (40, 40, 40, 255),
            "text": (232, 232, 232, 255), "header_text": (250, 250, 250, 255),
            "border": (72, 72, 72, 255), "separator": (78, 78, 78, 255),
            "row_line": (48, 48, 48, 255), "hover_fill": (55, 55, 55, 255),
            "hover_border": (95, 125, 150, 255), "selected_fill": (0, 105, 185, 255),
            "selected_border": (60, 165, 235, 255), "selected_hover_fill": (15, 125, 205, 255),
            "drop_fill": (40, 85, 115, 255), "drop_border": (65, 180, 245, 255),
            "status_bg": (38, 38, 38, 255), "status_text": (190, 190, 190, 255),
        },
        "Blue": {
            "background": (238, 247, 255, 255), "header_bg": (211, 233, 252, 255),
            "text": (20, 48, 72, 255), "header_text": (8, 55, 95, 255),
            "border": (126, 177, 218, 255), "separator": (145, 190, 225, 255),
            "row_line": (218, 237, 252, 255), "hover_fill": (205, 232, 252, 255),
            "hover_border": (65, 145, 210, 255), "selected_fill": (145, 205, 247, 255),
            "selected_border": (20, 105, 185, 255), "selected_hover_fill": (120, 192, 242, 255),
            "drop_fill": (165, 220, 250, 255), "drop_border": (0, 95, 180, 255),
            "status_bg": (222, 240, 254, 255), "status_text": (45, 90, 125, 255),
        },
        "Dark Blue": {
            "background": (18, 30, 46, 255), "header_bg": (24, 42, 64, 255),
            "text": (225, 238, 250, 255), "header_text": (245, 250, 255, 255),
            "border": (52, 79, 105, 255), "separator": (60, 90, 118, 255),
            "row_line": (31, 50, 70, 255), "hover_fill": (35, 65, 92, 255),
            "hover_border": (65, 145, 205, 255), "selected_fill": (20, 92, 150, 255),
            "selected_border": (65, 170, 240, 255), "selected_hover_fill": (25, 112, 178, 255),
            "drop_fill": (25, 75, 110, 255), "drop_border": (80, 190, 250, 255),
            "status_bg": (22, 37, 55, 255), "status_text": (170, 200, 225, 255),
        },
        "Light Blue": {
            "background": (247, 252, 255, 255), "header_bg": (225, 242, 254, 255),
            "text": (35, 60, 78, 255), "header_text": (18, 75, 112, 255),
            "border": (165, 205, 232, 255), "separator": (178, 215, 238, 255),
            "row_line": (230, 244, 253, 255), "hover_fill": (218, 240, 254, 255),
            "hover_border": (85, 165, 218, 255), "selected_fill": (180, 224, 250, 255),
            "selected_border": (45, 135, 200, 255), "selected_hover_fill": (160, 214, 246, 255),
            "drop_fill": (195, 232, 252, 255), "drop_border": (35, 125, 195, 255),
            "status_bg": (235, 248, 255, 255), "status_text": (70, 110, 138, 255),
        },
        "Gray": {
            "background": (242, 242, 242, 255), "header_bg": (220, 220, 220, 255),
            "text": (40, 40, 40, 255), "header_text": (20, 20, 20, 255),
            "border": (165, 165, 165, 255), "separator": (178, 178, 178, 255),
            "row_line": (225, 225, 225, 255), "hover_fill": (215, 215, 215, 255),
            "hover_border": (135, 135, 135, 255), "selected_fill": (185, 205, 220, 255),
            "selected_border": (90, 120, 145, 255), "selected_hover_fill": (170, 195, 212, 255),
            "drop_fill": (195, 215, 225, 255), "drop_border": (75, 115, 145, 255),
            "status_bg": (228, 228, 228, 255), "status_text": (90, 90, 90, 255),
        },
        "Green": {
            "background": (244, 252, 246, 255), "header_bg": (220, 240, 225, 255),
            "text": (30, 65, 40, 255), "header_text": (15, 80, 35, 255),
            "border": (145, 195, 155, 255), "separator": (165, 207, 172, 255),
            "row_line": (226, 242, 230, 255), "hover_fill": (213, 239, 220, 255),
            "hover_border": (70, 155, 90, 255), "selected_fill": (165, 220, 178, 255),
            "selected_border": (40, 125, 60, 255), "selected_hover_fill": (145, 210, 160, 255),
            "drop_fill": (185, 230, 194, 255), "drop_border": (35, 115, 55, 255),
            "status_bg": (230, 246, 234, 255), "status_text": (65, 115, 75, 255),
        },
        "Red": {
            "background": (255, 247, 247, 255), "header_bg": (249, 225, 225, 255),
            "text": (80, 35, 35, 255), "header_text": (115, 25, 25, 255),
            "border": (220, 165, 165, 255), "separator": (228, 180, 180, 255),
            "row_line": (248, 232, 232, 255), "hover_fill": (248, 218, 218, 255),
            "hover_border": (205, 95, 95, 255), "selected_fill": (238, 175, 175, 255),
            "selected_border": (180, 55, 55, 255), "selected_hover_fill": (232, 155, 155, 255),
            "drop_fill": (244, 195, 195, 255), "drop_border": (170, 45, 45, 255),
            "status_bg": (252, 235, 235, 255), "status_text": (135, 70, 70, 255),
        },
        "Purple": {
            "background": (250, 247, 255, 255), "header_bg": (232, 224, 247, 255),
            "text": (62, 42, 82, 255), "header_text": (83, 38, 125, 255),
            "border": (187, 160, 214, 255), "separator": (200, 176, 225, 255),
            "row_line": (239, 231, 248, 255), "hover_fill": (228, 214, 244, 255),
            "hover_border": (135, 90, 185, 255), "selected_fill": (200, 174, 231, 255),
            "selected_border": (105, 55, 160, 255), "selected_hover_fill": (187, 156, 225, 255),
            "drop_fill": (214, 190, 237, 255), "drop_border": (95, 45, 150, 255),
            "status_bg": (240, 233, 249, 255), "status_text": (100, 75, 125, 255),
        },
        "VS Code": {
            "background": (30, 30, 30, 255), "header_bg": (37, 37, 38, 255),
            "text": (212, 212, 212, 255), "header_text": (235, 235, 235, 255),
            "border": (62, 62, 64, 255), "separator": (70, 70, 72, 255),
            "row_line": (44, 44, 44, 255), "hover_fill": (45, 45, 45, 255),
            "hover_border": (80, 80, 82, 255), "selected_fill": (4, 57, 94, 255),
            "selected_border": (0, 122, 204, 255), "selected_hover_fill": (7, 68, 112, 255),
            "drop_fill": (15, 70, 105, 255), "drop_border": (0, 150, 230, 255),
            "status_bg": (0, 122, 204, 255), "status_text": (255, 255, 255, 255),
        },
        "GitHub": {
            "background": (246, 248, 250, 255), "header_bg": (234, 238, 242, 255),
            "text": (31, 35, 40, 255), "header_text": (36, 41, 47, 255),
            "border": (208, 215, 222, 255), "separator": (216, 222, 228, 255),
            "row_line": (226, 231, 236, 255), "hover_fill": (238, 242, 246, 255),
            "hover_border": (175, 184, 193, 255), "selected_fill": (207, 230, 255, 255),
            "selected_border": (84, 174, 255, 255), "selected_hover_fill": (188, 218, 250, 255),
            "drop_fill": (215, 235, 255, 255), "drop_border": (47, 129, 247, 255),
            "status_bg": (242, 244, 246, 255), "status_text": (87, 96, 106, 255),
        },
    }

    _aliases = {"darkblue": "Dark Blue", "lightblue": "Light Blue", "vscode": "VS Code", "github": "GitHub"}

    @classmethod
    def _complete(cls, config):
        base = dict(cls._themes["Explorer"])
        base.update(config)
        return base

    @classmethod
    def resolve(cls, theme):
        if theme is None:
            name = "Explorer"
        elif isinstance(theme, str):
            normalized = theme.strip()
            name = next((n for n in cls._themes if n.casefold() == normalized.casefold()), None)
            if name is None:
                name = cls._aliases.get(normalized.replace(" ", "").casefold())
            if name is None:
                raise KeyError("Unknown theme %r. Available themes: %s" % (theme, ", ".join(cls.available())))
        else:
            raise TypeError("Theme must be a registered theme name")
        return name, cls._complete(cls._themes[name])

    @classmethod
    def register(cls, name, config, base="Explorer", replace=False):
        name = str(name).strip()
        if not name:
            raise ValueError("Theme name cannot be empty")
        if name in cls._themes and not replace:
            raise KeyError("Theme already exists: %s" % name)
        _, parent = cls.resolve(base)
        parent.update(dict(config))
        cls._themes[name] = parent
        return name

    @classmethod
    def unregister(cls, name):
        if name in {"Explorer", "White", "Black", "Dark", "Blue"}:
            raise ValueError("Built-in core theme cannot be removed")
        cls._themes.pop(name, None)

    @classmethod
    def available(cls):
        return tuple(cls._themes.keys())


