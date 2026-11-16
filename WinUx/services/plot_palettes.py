"""Excel-style curve colour themes, independent of the plot renderer.

The Job Plots panel exposes the same *kind* of theme-colour families shown by
Excel's Page Layout -> Colors gallery.  The source swatches below are taken
from the reference gallery supplied for WinUx.  Excel reserves the first two
swatches in each row for dark/light document colours, so plotted series use
only the six accent colours.  A darker pass of those six accents is appended
for charts containing more than six series.
"""


def _rgba(colors):
    return tuple(tuple(int(channel) for channel in color) + (255,) for color in colors)


def _mix(color, target, amount):
    """Blend an RGB colour toward *target* by a fixed 0..1 amount."""
    return tuple(int(round(channel + (dest - channel) * amount))
                 for channel, dest in zip(color, target))


def _excel_series(swatches):
    """Convert one Excel theme row into a chart-series colour sequence.

    The first two gallery swatches are text/background colours and are not
    suitable chart series colours (the light swatch is frequently near white).
    Excel charts primarily consume the six accent colours, so WinUx does the
    same and then continues with a darker variant of those accents for series
    7..12.
    """
    swatches = tuple(tuple(int(channel) for channel in color) for color in swatches)
    accents = swatches[2:]
    return _rgba(accents + tuple(_mix(color, (0, 0, 0), 0.22) for color in accents))


def _automatic_sequence(*anchors):
    """Legacy automatic sequence retained for persisted/internal callers."""
    anchors = tuple(tuple(int(channel) for channel in color) for color in anchors)
    colors = []
    for target, amount in (
            (None, 0.0),
            ((255, 255, 255), 0.28),
            ((0, 0, 0), 0.20),
            ((255, 255, 255), 0.48)):
        for color in anchors:
            colors.append(color if target is None else _mix(color, target, amount))
    return _rgba(colors)


# Eight swatches per row from the supplied Excel Theme Colors reference.
# [0:2] are document dark/light colours; [2:8] are the six chart accents.
THEME_SWATCHES = {
    'default': ('Office', (
        (65, 85, 112), (236, 227, 232), (94, 153, 211), (231, 126, 60),
        (166, 164, 167), (252, 192, 0), (71, 114, 193), (112, 174, 65))),
    'office_2007_2010': ('Office 2007 - 2010', (
        (34, 71, 126), (238, 235, 226), (78, 130, 188), (200, 75, 81),
        (153, 188, 86), (129, 99, 161), (73, 173, 197), (247, 150, 73))),
    'grayscale': ('Grayscale', (
        (0, 0, 0), (248, 248, 248), (221, 221, 221), (178, 178, 178),
        (150, 150, 150), (128, 128, 128), (95, 95, 95), (77, 77, 77))),
    'blue_warm': ('Blue Warm', (
        (36, 41, 83), (171, 204, 247), (75, 101, 175), (96, 158, 207),
        (41, 127, 214), (130, 141, 171), (89, 163, 174), (157, 144, 164))),
    'excel_blue': ('Blue', (
        (25, 64, 107), (219, 239, 248), (20, 109, 193), (0, 160, 219),
        (6, 210, 219), (19, 206, 153), (126, 200, 105), (164, 195, 78))),
    'blue_ii': ('Blue II', (
        (53, 90, 116), (223, 227, 230), (28, 173, 230), (32, 132, 208),
        (39, 205, 217), (63, 187, 151), (60, 137, 85), (97, 163, 162))),
    'blue_green': ('Blue Green', (
        (55, 52, 71), (206, 218, 232), (54, 148, 186), (91, 181, 192),
        (117, 189, 165), (121, 141, 142), (129, 173, 184), (41, 129, 200))),
    'excel_green': ('Green', (
        (71, 95, 81), (228, 222, 206), (85, 156, 60), (140, 185, 43),
        (193, 208, 57), (0, 151, 118), (75, 181, 197), (15, 134, 177))),
    'green_yellow': ('Green Yellow', (
        (69, 96, 81), (226, 224, 203), (154, 200, 66), (102, 161, 69),
        (60, 164, 113), (75, 190, 161), (80, 177, 209), (84, 194, 247))),
    'yellow': ('Yellow', (
        (57, 48, 43), (230, 222, 219), (255, 202, 5), (255, 145, 24),
        (203, 142, 62), (236, 113, 20), (236, 69, 37), (159, 104, 107))),
    'yellow_orange': ('Yellow Orange', (
        (77, 59, 47), (253, 237, 203), (234, 164, 52), (160, 103, 76),
        (182, 138, 129), (194, 152, 114), (162, 149, 115), (194, 115, 48))),
    'excel_orange': ('Orange', (
        (101, 111, 86), (203, 221, 233), (231, 129, 18), (197, 83, 46),
        (133, 87, 64), (158, 129, 89), (196, 188, 125), (147, 161, 136))),
    'orange_red': ('Orange Red', (
        (108, 99, 102), (233, 229, 220), (216, 68, 30), (159, 42, 35),
        (164, 141, 109), (149, 98, 81), (144, 133, 131), (136, 92, 91))),
    'red_orange': ('Red Orange', (
        (80, 80, 70), (238, 236, 224), (232, 76, 36), (254, 190, 67),
        (182, 74, 38), (250, 133, 37), (204, 153, 0), (176, 40, 2))),
    'red': ('Red', (
        (50, 50, 50), (226, 195, 68), (162, 49, 17), (220, 83, 29),
        (230, 151, 30), (180, 154, 129), (127, 95, 84), (180, 124, 77))),
    'red_violet': ('Red Violet', (
        (69, 68, 82), (216, 217, 221), (229, 44, 145), (204, 44, 212),
        (79, 166, 219), (70, 117, 235), (137, 113, 225), (209, 72, 114))),
    'violet': ('Violet', (
        (55, 52, 71), (222, 216, 220), (174, 131, 200), (134, 134, 198),
        (93, 115, 156), (104, 152, 175), (132, 171, 186), (111, 129, 133))),
    'violet_ii': ('Violet II', (
        (99, 46, 100), (234, 229, 235), (149, 38, 143), (153, 85, 220),
        (117, 93, 217), (104, 93, 187), (71, 165, 237), (87, 131, 220))),
    'median': ('Median', (
        (119, 94, 87), (235, 220, 197), (148, 182, 207), (211, 131, 80),
        (164, 170, 132), (216, 178, 93), (124, 167, 158), (149, 141, 139))),
    'paper': ('Paper', (
        (69, 76, 42), (254, 250, 202), (165, 180, 147), (243, 165, 64),
        (230, 189, 39), (210, 145, 169), (157, 133, 191), (129, 158, 192))),
    'marquee': ('Marquee', (
        (94, 94, 94), (221, 221, 221), (65, 139, 176), (166, 185, 34),
        (250, 145, 0), (131, 131, 131), (255, 194, 5), (225, 82, 42))),
}


# User-visible Excel gallery.
PALETTES = {
    key: (label, _excel_series(swatches))
    for key, (label, swatches) in THEME_SWATCHES.items()
}

# Legacy/internal palettes remain valid for old settings, detached snapshots,
# formula previews, and callers outside Job Plots.  They are deliberately not
# exposed in the redesigned Theme menu.
PALETTES.update({
    'excel_pastel': ('Excel - Pastel (legacy)', _rgba((
        (157, 195, 230), (244, 177, 131), (201, 201, 201), (255, 230, 153),
        (169, 209, 142), (198, 180, 206), (143, 170, 220), (244, 204, 204),
        (180, 198, 231), (248, 203, 173), (217, 217, 217), (226, 239, 218)))),
    'excel_dark': ('Excel - Dark (legacy)', _rgba((
        (47, 85, 151), (198, 89, 17), (127, 127, 127), (191, 143, 0),
        (31, 78, 121), (84, 130, 53), (112, 48, 160), (131, 60, 12),
        (36, 64, 98), (118, 59, 15), (89, 89, 89), (128, 96, 0)))),
    'auto_rgb': ('Auto - Red -> Green -> Blue', _automatic_sequence(
        (220, 53, 69), (40, 167, 69), (45, 108, 223))),
    'auto_bog': ('Auto - Blue -> Orange -> Green', _automatic_sequence(
        (68, 114, 196), (237, 125, 49), (112, 173, 71))),
    'auto_gbp': ('Auto - Green -> Blue -> Purple', _automatic_sequence(
        (84, 160, 70), (68, 114, 196), (112, 48, 160))),
    'auto_bpr': ('Auto - Blue -> Purple -> Red', _automatic_sequence(
        (47, 85, 151), (112, 48, 160), (192, 0, 0))),
    'auto_pcg': ('Auto - Purple -> Cyan -> Gold', _automatic_sequence(
        (112, 48, 160), (0, 176, 240), (255, 192, 0))),
    'auto_tpo': ('Auto - Teal -> Purple -> Orange', _automatic_sequence(
        (0, 150, 150), (128, 100, 162), (237, 125, 49))),
    'auto_roy': ('Auto - Red -> Orange -> Yellow', _automatic_sequence(
        (192, 0, 0), (237, 125, 49), (255, 192, 0))),
    'auto_cmg': ('Auto - Cyan -> Magenta -> Gold', _automatic_sequence(
        (0, 176, 240), (192, 0, 160), (255, 192, 0))),
    'tableau': ('Tableau 10', _rgba(((31, 119, 180), (255, 127, 14), (44, 160, 44),
                                  (214, 39, 40), (148, 103, 189), (140, 86, 75),
                                  (227, 119, 194), (127, 127, 127), (188, 189, 34),
                                  (23, 190, 207)))),
    'colorblind': ('Colorblind (Okabe-Ito)', _rgba(((0, 114, 178), (230, 159, 0),
                                                (0, 158, 115), (213, 94, 0),
                                                (204, 121, 167), (86, 180, 233),
                                                (240, 228, 66), (60, 60, 60)))),
    'viridis': ('Viridis', _rgba(((68, 1, 84), (70, 50, 126), (54, 92, 141),
                                (39, 127, 142), (31, 161, 135), (74, 193, 109),
                                (160, 218, 57), (253, 231, 37)))),
    'pastel': ('Pastel', _rgba(((102, 194, 165), (252, 141, 98), (141, 160, 203),
                              (231, 138, 195), (166, 216, 84), (255, 217, 47),
                              (229, 196, 148), (179, 179, 179)))),
})


EXCEL_THEME_KEYS = tuple(THEME_SWATCHES)
# Retained as a public constant for compatibility; the old generated sequences
# are no longer shown in the Theme menu now that the Excel-style gallery is
# complete.
AUTO_SEQUENCE_KEYS = ()
PLOT_THEME_KEYS = EXCEL_THEME_KEYS


# Previous builds exposed these ids in the Theme menu.  Translate persisted
# values to the closest new Excel gallery family rather than silently losing
# the user's colour preference.
_PLOT_THEME_ALIASES = {
    'excel_pastel': 'paper',
    'excel_dark': 'grayscale',
    'auto_rgb': 'marquee',
    'auto_bog': 'default',
    'auto_gbp': 'blue_green',
    'auto_bpr': 'red_violet',
    'auto_pcg': 'violet_ii',
    'auto_tpo': 'median',
    'auto_roy': 'yellow_orange',
    'auto_cmg': 'red_violet',
}


def normalize_palette(value):
    value = value.strip().lower() if isinstance(value, str) else ''
    return value if value in PALETTES else 'default'


def normalize_plot_theme(value):
    """Normalize a Job Plots theme and migrate older saved palette ids."""
    value = normalize_palette(value)
    value = _PLOT_THEME_ALIASES.get(value, value)
    return value if value in PLOT_THEME_KEYS else 'default'


def palette_colors(value):
    return PALETTES[normalize_palette(value)][1]


def theme_swatches(value):
    """Return the eight gallery swatches for a visible Excel theme."""
    key = normalize_plot_theme(value)
    return _rgba(THEME_SWATCHES[key][1])
