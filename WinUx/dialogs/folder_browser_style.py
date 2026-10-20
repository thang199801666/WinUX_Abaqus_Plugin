"""Qt/Fusion-like chrome for the Dear ImGui folder chooser.

The folder chooser stays Dear PyGui-only.  This module deliberately gives the
whole browser one visual hierarchy (toolbars -> framed viewport -> selection
bar -> dialog button box) instead of styling isolated ImGui controls.
"""
import os
from dataclasses import dataclass
from pathlib import Path
from DearUIQt.backends import dpg
from PIL import Image, ImageDraw, ImageFilter, ImageOps

from DearUIQt.gui import QtFusionPalette, QtFusionMetrics, QPainter
from DearUIQt.themes import (
    ThemeTarget, ThemeColor, ThemeStyle, theme_component, make_theme, with_scrollbar,
)
from DearUIQt.tooltip import add_styled_tooltip
from DearUIQt.widgets import QToolButton, QCanvas
from ..platform.windows_icons import WindowsIconRegistry


GLYPHS = {"Back": 0xE72B, "Forward": 0xE72A, "Up": 0xE74A,
          "Refresh": 0xE72C, "Go": 0xE72A, "Search": 0xE721,
          "Edit address": 0xE70D, "New folder": 0xE8F4,
          "Home": 0xE80F, "Chevron": 0xE76C,
          "Expanded": 0xE70D, "Collapsed": 0xE76C}


@dataclass(frozen=True)
class BrowserMetrics:
    control_height: int = 26
    tool_button_size: int = 26
    icon_size: int = 16
    label_width: int = 76
    action_width: int = 100
    form_gap: int = 6
    location_height: int = 26
    toolbar_height: int = 32
    command_height: int = 28
    navigation_width: int = 26
    sidebar_width: int = 144
    sidebar_row_height: int = 20
    sidebar_section_gap: int = 8
    header_height: int = 24
    row_height: int = 18
    divider_width: int = 1
    selection_height: int = 72
    inline_action_height: int = 34


METRICS = BrowserMetrics()


FOLDER_SELECTOR_ICON_DIR = Path(__file__).resolve().parents[1] / "Resources" / "folder_selector_icons"
FOLDER_SELECTOR_ICON_MAP = {
    "back": "back.png",
    "forward": "forward.png",
    "up": "up.png",
    "refresh": "refresh.png",
    "search": "search.png",
    "new_folder": "new_folder.png",
    "details": "details.png",
    "list": "list.png",
    "drive": "drive.png",
    "folder": "folder.png",
    "chevron": "chevron.png",
    # The right edge of the QFileDialog-style address bar uses the same
    # down-chevron artwork as the editable-address action.
    "edit_address": "chevron.png",
    "address_menu": "chevron.png",
}

# Image-generation masters are normalized to 64x64.  Dear ImGui displays
# them at 20x20 logical pixels, so Windows DPI scaling starts from a dense
# source texture instead of stretching an already-small 20px bitmap.
FOLDER_SELECTOR_MASTER_SIZE = 64


def load_navigation_font():
    path = Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts" / "segmdl2.ttf"
    if not path.is_file():
        return None
    with dpg.font_registry():
        font = dpg.add_font(str(path), 16)
    return font


def browser_surface_theme(background=None, padding=(0, 0), cell_padding=(6, 2), spacing=(6, 3)):
    p = QtFusionPalette
    background = tuple(background or p.BASE)
    return make_theme(theme_component(
        ThemeTarget.ALL,
        colors={
            ThemeColor.CHILD_BACKGROUND: background,
            ThemeColor.BORDER: p.BORDER_LIGHT,
            ThemeColor.TABLE_HEADER_BACKGROUND: p.TOOLBAR,
            ThemeColor.TABLE_BORDER_LIGHT: p.BORDER_LIGHT,
        },
        styles={
            ThemeStyle.WINDOW_PADDING: padding,
            ThemeStyle.ITEM_SPACING: spacing,
            ThemeStyle.CHILD_ROUNDING: 0,
            ThemeStyle.CELL_PADDING: cell_padding,
        },
    ))


def browser_dialog_body_theme():
    return browser_surface_theme(
        background=QtFusionPalette.WINDOW,
        padding=(8, 8), cell_padding=(3, 3), spacing=(METRICS.form_gap, METRICS.form_gap))


def browser_layout_theme(cell_padding=(2, 1)):
    return make_theme(theme_component(
        ThemeTarget.TABLE,
        colors={
            ThemeColor.TABLE_BORDER_STRONG: (0, 0, 0, 0),
            ThemeColor.TABLE_BORDER_LIGHT: (0, 0, 0, 0),
        },
        styles={ThemeStyle.CELL_PADDING: cell_padding, ThemeStyle.ITEM_SPACING: (0, 0)},
    ))


def browser_toolbar_theme(*, border_bottom=False):
    p = QtFusionPalette
    return make_theme(theme_component(
        ThemeTarget.CHILD_WINDOW,
        colors={
            ThemeColor.CHILD_BACKGROUND: p.WINDOW,
            ThemeColor.BORDER: p.BORDER_LIGHT if border_bottom else (0, 0, 0, 0),
        },
        styles={
            ThemeStyle.WINDOW_PADDING: (0, 3),
            ThemeStyle.ITEM_SPACING: (4, 2),
            ThemeStyle.CHILD_BORDER_SIZE: 0,
            ThemeStyle.CHILD_ROUNDING: 0,
        },
    ))


def browser_field_shell_theme(*, focused=False):
    p = QtFusionPalette
    return make_theme(theme_component(
        ThemeTarget.CHILD_WINDOW,
        colors={
            ThemeColor.CHILD_BACKGROUND: p.BASE,
            ThemeColor.BORDER: p.FOCUS if focused else p.BORDER,
        },
        styles={
            ThemeStyle.WINDOW_PADDING: (3, 1),
            ThemeStyle.CHILD_BORDER_SIZE: 1,
            ThemeStyle.CHILD_ROUNDING: 2,
        },
    ))


def browser_file_editor_theme(*, focused=False, disabled=False, font_height=14, combo=False):
    """Quiet one-pixel field chrome, scoped to the selector's filename input."""
    p = QtFusionPalette
    background = p.BUTTON_DISABLED if disabled else p.BASE
    text = p.TEXT_DISABLED if disabled else p.TEXT
    border = p.FOCUS if focused and not disabled else (174, 178, 182, 255)
    colors = {ThemeColor.FRAME_BACKGROUND: background,
              ThemeColor.FRAME_BACKGROUND_HOVERED: background,
              ThemeColor.FRAME_BACKGROUND_ACTIVE: background,
              ThemeColor.TEXT: text, ThemeColor.BORDER: border}
    if combo:
        colors.update({ThemeColor.BUTTON: background,
                       ThemeColor.BUTTON_HOVERED: p.HIGHLIGHT_HOVER,
                       ThemeColor.BUTTON_ACTIVE: p.HIGHLIGHT_SOFT,
                       ThemeColor.POPUP_BACKGROUND: p.BASE,
                       ThemeColor.HEADER: p.SELECTION_ACTIVE,
                       ThemeColor.HEADER_HOVERED: p.HIGHLIGHT_HOVER})
    return make_theme(theme_component(
        ThemeTarget.COMBO_BOX if combo else ThemeTarget.LINE_EDIT,
        enabled_state=not disabled, colors=colors,
        styles={ThemeStyle.FRAME_BORDER_SIZE: 1, ThemeStyle.FRAME_ROUNDING: 2,
                ThemeStyle.FRAME_PADDING: (5, max(0, (METRICS.control_height - font_height) / 2))},
    ))


def browser_action_theme(*, default=False, focused=False, disabled=False):
    """Restrained Qt-like action chrome without the generic raised-button edge."""
    return make_theme(theme_component(
        ThemeTarget.PUSH_BUTTON, enabled_state=not disabled,
        colors={ThemeColor.BUTTON: QtFusionPalette.BUTTON_DISABLED if disabled else (250, 250, 250, 255),
                ThemeColor.BUTTON_HOVERED: (232, 243, 250, 255),
                ThemeColor.BUTTON_ACTIVE: (214, 233, 245, 255),
                ThemeColor.TEXT: QtFusionPalette.TEXT_DISABLED if disabled else QtFusionPalette.TEXT,
                ThemeColor.BORDER: QtFusionPalette.FOCUS if (default or focused) and not disabled else (174, 178, 182, 255)},
        styles={ThemeStyle.FRAME_BORDER_SIZE: 1, ThemeStyle.FRAME_ROUNDING: 2,
                ThemeStyle.FRAME_PADDING: (8, 4)},
    ))


def browser_icon_slot_theme():
    """Borderless fixed-height slot that vertically centers embedded icons."""
    p = QtFusionPalette
    return make_theme(theme_component(
        ThemeTarget.CHILD_WINDOW,
        colors={ThemeColor.CHILD_BACKGROUND: p.BASE, ThemeColor.BORDER: (0, 0, 0, 0)},
        styles={
            ThemeStyle.WINDOW_PADDING: (0, 0), ThemeStyle.ITEM_SPACING: (0, 0),
            ThemeStyle.CHILD_BORDER_SIZE: 0, ThemeStyle.CHILD_ROUNDING: 0,
        },
    ))


def browser_embedded_editor_theme(font_height=14):
    p = QtFusionPalette
    clear = (255, 255, 255, 0)
    return make_theme(theme_component(
        ThemeTarget.LINE_EDIT,
        colors={
            ThemeColor.FRAME_BACKGROUND: clear,
            ThemeColor.FRAME_BACKGROUND_HOVERED: clear,
            ThemeColor.FRAME_BACKGROUND_ACTIVE: clear,
            ThemeColor.BORDER: clear,
            ThemeColor.TEXT: p.TEXT,
            ThemeColor.TEXT_SELECTED_BACKGROUND: (0, 120, 215, 100),
        },
        styles={
            ThemeStyle.FRAME_BORDER_SIZE: 0, ThemeStyle.FRAME_ROUNDING: 0,
            ThemeStyle.FRAME_PADDING: (2, max(0, (METRICS.control_height - 2 - font_height) / 2)),
        },
    ))


def browser_caption_theme():
    return make_theme(
        theme_component(
            ThemeTarget.CHILD_WINDOW,
            colors={ThemeColor.CHILD_BACKGROUND: (0, 0, 0, 0), ThemeColor.BORDER: (0, 0, 0, 0)},
            styles={ThemeStyle.WINDOW_PADDING: (0, 0), ThemeStyle.ITEM_SPACING: (0, 0),
                    ThemeStyle.CHILD_BORDER_SIZE: 0, ThemeStyle.CHILD_ROUNDING: 0}),
        # DPG Text calls AlignTextToFramePadding itself. Suppress that extra
        # offset: the caption host already positions text at the field baseline.
        theme_component(ThemeTarget.TEXT, styles={ThemeStyle.FRAME_PADDING: (0, 0)}),
    )



def browser_rename_editor_theme():
    """Fusion-style inline rename editor without renderer symbols in the form."""
    return make_theme(theme_component(
        ThemeTarget.LINE_EDIT,
        colors={
            ThemeColor.FRAME_BACKGROUND: QtFusionPalette.BASE,
            ThemeColor.TEXT: QtFusionPalette.TEXT,
            ThemeColor.BORDER: (72, 72, 72, 255),
        },
        styles={
            ThemeStyle.FRAME_BORDER_SIZE: 1,
            ThemeStyle.FRAME_ROUNDING: 0,
            ThemeStyle.FRAME_PADDING: (2, 1),
        },
    ))

def browser_workspace_theme():
    p = QtFusionPalette
    return make_theme(theme_component(
        ThemeTarget.CHILD_WINDOW,
        colors={ThemeColor.CHILD_BACKGROUND: p.BASE, ThemeColor.BORDER: p.BORDER},
        styles={
            ThemeStyle.WINDOW_PADDING: (0, 0), ThemeStyle.ITEM_SPACING: (0, 0),
            ThemeStyle.CHILD_BORDER_SIZE: 1, ThemeStyle.CHILD_ROUNDING: 0,
        },
    ))


def browser_sidebar_theme():
    p = QtFusionPalette
    spec = theme_component(
        ThemeTarget.CHILD_WINDOW,
        colors={ThemeColor.CHILD_BACKGROUND: p.BASE, ThemeColor.BORDER: (0, 0, 0, 0)},
        styles={
            ThemeStyle.WINDOW_PADDING: (3, 4), ThemeStyle.ITEM_SPACING: (3, 1),
            ThemeStyle.CHILD_BORDER_SIZE: 0, ThemeStyle.CHILD_ROUNDING: 0,
        },
    )
    return make_theme(with_scrollbar(spec, track=p.WINDOW_ALT))


def browser_sidebar_row_theme():
    """QTreeView item palette for Places rows."""
    p = QtFusionPalette
    return make_theme(theme_component(
        ThemeTarget.SELECTABLE,
        colors={
            ThemeColor.HEADER: p.SELECTION_ACTIVE,
            ThemeColor.HEADER_HOVERED: p.SELECTION_ACTIVE_HOVER,
            ThemeColor.HEADER_ACTIVE: p.SELECTION_ACTIVE_PRESSED,
            ThemeColor.NAV_HIGHLIGHT: p.FOCUS,
            ThemeColor.TEXT: p.SELECTION_TEXT,
        },
        styles={
            ThemeStyle.FRAME_PADDING: (4, 3), ThemeStyle.FRAME_ROUNDING: 0,
            ThemeStyle.SELECTABLE_TEXT_ALIGN: (0.0, 0.5),
        },
    ))


def browser_selected_item_theme(*, active=True):
    """Explorer-like selection using the same row surface as hover."""
    fill = QtFusionPalette.SELECTION_ACTIVE if active else QtFusionPalette.SELECTION_INACTIVE
    text = QtFusionPalette.SELECTION_TEXT if active else QtFusionPalette.TEXT
    return make_theme(theme_component(
        ThemeTarget.SELECTABLE,
        colors={ThemeColor.HEADER: fill, ThemeColor.HEADER_HOVERED: fill,
                ThemeColor.HEADER_ACTIVE: fill, ThemeColor.TEXT: text},
        styles={
            ThemeStyle.FRAME_ROUNDING: 0,
            ThemeStyle.FRAME_PADDING: (5, 2),
            ThemeStyle.SELECTABLE_TEXT_ALIGN: (0.0, 0.5),
            ThemeStyle.FRAME_BORDER_SIZE: 0,
        },
    ))


def browser_name_item_theme(*, selected=False, disabled=False, current=False, active=True):
    """Vertically centered QFileDialog Name-cell selectable.

    The details columns are native table text cells while the Name column is a
    Selectable embedded beside an icon. Keep the Selectable centered inside its
    explicit row height so icon, label, hover and selection share one geometry.
    """
    p = QtFusionPalette
    if disabled:
        fill = p.SELECTION_INACTIVE
        hover = p.SELECTION_INACTIVE
        pressed = p.SELECTION_INACTIVE
        text = p.TEXT_DISABLED
        border = p.SELECTION_INACTIVE_BORDER
    elif selected and active:
        fill = p.SELECTION_ACTIVE
        hover = fill
        pressed = fill
        text = p.SELECTION_TEXT
        border = p.SELECTION_BORDER
    elif selected:
        fill = p.SELECTION_INACTIVE
        hover = fill
        pressed = fill
        text = p.TEXT
        border = p.SELECTION_INACTIVE_BORDER
    else:
        fill = p.HIGHLIGHT_SOFT
        hover = p.HIGHLIGHT_HOVER if active else p.WINDOW_ALT
        pressed = p.BUTTON_ACTIVE if active else p.SELECTION_INACTIVE
        text = p.TEXT
        border = p.FOCUS if active else p.SELECTION_INACTIVE_BORDER
    return make_theme(theme_component(
        ThemeTarget.SELECTABLE,
        colors={
            ThemeColor.HEADER: fill,
            ThemeColor.HEADER_HOVERED: hover,
            ThemeColor.HEADER_ACTIVE: pressed,
            ThemeColor.NAV_HIGHLIGHT: p.FOCUS,
            ThemeColor.TEXT: text,
            ThemeColor.BORDER: border,
        },
        styles={
            ThemeStyle.SELECTABLE_TEXT_ALIGN: (0.0, 0.5),
            ThemeStyle.FRAME_PADDING: (5, 2),
            ThemeStyle.FRAME_ROUNDING: 0,
            # The spanning Selectable is the single hover/selection surface.
            # Keep its outer geometry identical in every state.
            ThemeStyle.FRAME_BORDER_SIZE: 0,
        },
    ))


def browser_selected_text_theme(*, active=True):
    return make_theme(theme_component(
        ThemeTarget.TEXT,
        colors={ThemeColor.TEXT: QtFusionPalette.SELECTION_TEXT if active else QtFusionPalette.TEXT},
    ))


def browser_sidebar_item_text_theme(*, selected=False):
    """Display-role text for overlay labels in QTreeView-like rows."""
    p = QtFusionPalette
    return make_theme(theme_component(
        ThemeTarget.TEXT,
        colors={ThemeColor.TEXT: p.SELECTION_TEXT if selected else p.TEXT},
    ))


def browser_list_viewport_theme():
    """QAbstractItemView viewport chrome for the folder list."""
    p = QtFusionPalette
    spec = theme_component(
        ThemeTarget.CHILD_WINDOW,
        colors={ThemeColor.CHILD_BACKGROUND: p.BASE, ThemeColor.BORDER: (0, 0, 0, 0)},
        styles={
            ThemeStyle.WINDOW_PADDING: (0, 0), ThemeStyle.ITEM_SPACING: (0, 0),
            ThemeStyle.CHILD_BORDER_SIZE: 0, ThemeStyle.CHILD_ROUNDING: 0,
        },
    )
    return make_theme(with_scrollbar(spec, track=p.WINDOW_ALT))


def browser_row_cell_theme():
    """Transparent fixed-height cell canvas for QFileDialog detail rows."""
    return make_theme(theme_component(
        ThemeTarget.CHILD_WINDOW,
        colors={ThemeColor.CHILD_BACKGROUND: (0, 0, 0, 0), ThemeColor.BORDER: (0, 0, 0, 0)},
        styles={
            ThemeStyle.WINDOW_PADDING: (0, 0), ThemeStyle.ITEM_SPACING: (0, 0),
            ThemeStyle.CHILD_BORDER_SIZE: 0, ThemeStyle.CHILD_ROUNDING: 0,
        },
    ))


def browser_sidebar_item_container_theme():
    """Zero-margin canvas for one QTreeView-like sidebar row."""
    p = QtFusionPalette
    return make_theme(theme_component(
        ThemeTarget.CHILD_WINDOW,
        colors={ThemeColor.CHILD_BACKGROUND: p.BASE, ThemeColor.BORDER: (0, 0, 0, 0)},
        styles={
            ThemeStyle.WINDOW_PADDING: (0, 0), ThemeStyle.ITEM_SPACING: (0, 0),
            ThemeStyle.CHILD_BORDER_SIZE: 0, ThemeStyle.CHILD_ROUNDING: 0,
        },
    ))


def browser_sidebar_header_theme():
    """Unselected QTreeView branch row with only hover/press feedback."""
    p = QtFusionPalette
    return make_theme(theme_component(
        ThemeTarget.SELECTABLE,
        colors={
            ThemeColor.HEADER: (0, 0, 0, 0), ThemeColor.HEADER_HOVERED: p.HIGHLIGHT_HOVER,
            ThemeColor.HEADER_ACTIVE: p.BUTTON_ACTIVE, ThemeColor.TEXT: p.TEXT,
        },
        styles={ThemeStyle.FRAME_PADDING: (0, 0), ThemeStyle.FRAME_ROUNDING: 0},
    ))


def create_branch_indicator(parent, expanded=True, pos=(1, 0)):
    """Create a font-independent Qt-style disclosure triangle."""
    indicator = dpg.add_drawlist(18, METRICS.sidebar_row_height, parent=parent, pos=pos)
    paint_branch_indicator(indicator, expanded)
    return indicator


def paint_branch_indicator(indicator, expanded):
    """Redraw the branch arrow without mutating a DPG draw command in-place."""
    if not dpg.does_item_exist(indicator):
        return
    dpg.delete_item(indicator, children_only=True)
    color = QtFusionPalette.TEXT_MUTED
    cy = METRICS.sidebar_row_height * 0.5
    if expanded:
        points = ((5.0, cy - 2.6), (12.0, cy - 2.6), (8.5, cy + 2.4))
    else:
        points = ((6.0, cy - 3.5), (6.0, cy + 3.5), (11.0, cy))
    dpg.draw_triangle(*points, parent=indicator, color=color, fill=color)



def browser_breadcrumb_button_theme():
    """Flat QToolButton-like segment used inside the address field."""
    p = QtFusionPalette
    return make_theme(theme_component(
        ThemeTarget.PUSH_BUTTON,
        colors={
            ThemeColor.BUTTON: (0, 0, 0, 0), ThemeColor.BUTTON_HOVERED: p.HIGHLIGHT_HOVER,
            ThemeColor.BUTTON_ACTIVE: p.HIGHLIGHT_SOFT, ThemeColor.TEXT: p.TEXT,
            ThemeColor.BORDER: (0, 0, 0, 0),
        },
        styles={
            ThemeStyle.FRAME_BORDER_SIZE: 0, ThemeStyle.FRAME_ROUNDING: 0,
            ThemeStyle.FRAME_PADDING: (3, 2),
        },
    ))


def browser_breadcrumb_blank_theme():
    """Invisible address-bar remainder that stays visually inert on hover."""
    p = QtFusionPalette
    clear = (0, 0, 0, 0)
    return make_theme(theme_component(
        ThemeTarget.PUSH_BUTTON,
        colors={
            ThemeColor.BUTTON: clear, ThemeColor.BUTTON_HOVERED: clear,
            ThemeColor.BUTTON_ACTIVE: clear, ThemeColor.TEXT: p.TEXT, ThemeColor.BORDER: clear,
        },
        styles={
            ThemeStyle.FRAME_BORDER_SIZE: 0, ThemeStyle.FRAME_ROUNDING: 0,
            ThemeStyle.FRAME_PADDING: (0, 0),
        },
    ))


def create_breadcrumb_chevron(parent):
    """Draw a DPI-stable Qt-style breadcrumb separator without font glyphs."""
    height = max(18, METRICS.location_height - 3)
    canvas = QCanvas(11, height, parent=parent)
    cy = height * 0.5
    painter = QPainter(canvas)
    color = QtFusionPalette.TEXT_MUTED
    painter.drawLine((4.0, cy - 3.5), (7.5, cy), color=color, thickness=1.0)
    painter.drawLine((7.5, cy), (4.0, cy + 3.5), color=color, thickness=1.0)
    return canvas


def browser_toolbar_divider_theme():
    """Compatibility theme for older callers; the toolbar now draws its divider."""
    return make_theme(theme_component(
        ThemeTarget.CHILD_WINDOW,
        colors={ThemeColor.CHILD_BACKGROUND: (0, 0, 0, 0), ThemeColor.BORDER: (0, 0, 0, 0)},
        styles={
            ThemeStyle.WINDOW_PADDING: (0, 0), ThemeStyle.CHILD_BORDER_SIZE: 0,
            ThemeStyle.CHILD_ROUNDING: 0,
        },
    ))


def create_toolbar_divider(parent):
    """Draw one optically centered, one-pixel toolbar separator."""
    height = METRICS.location_height
    width = 9
    canvas = QCanvas(width, height, parent=parent)
    line_height = 14
    y1 = (height - line_height) * 0.5
    y2 = y1 + line_height
    x = (width * 0.5) + 0.5
    QPainter(canvas).drawLine(
        (x, y1), (x, y2), color=(218, 218, 218, 255), thickness=1.0)
    return canvas


def browser_inline_icon_button_theme():
    """Small borderless icon button embedded in a QLineEdit-like field."""
    p = QtFusionPalette
    return make_theme(theme_component(
        ThemeTarget.IMAGE_BUTTON,
        colors={
            ThemeColor.BUTTON: (0, 0, 0, 0), ThemeColor.BUTTON_HOVERED: p.HIGHLIGHT_HOVER,
            ThemeColor.BUTTON_ACTIVE: p.HIGHLIGHT_SOFT, ThemeColor.BORDER: (0, 0, 0, 0),
        },
        styles={
            ThemeStyle.FRAME_BORDER_SIZE: 0, ThemeStyle.FRAME_ROUNDING: 2,
            ThemeStyle.FRAME_PADDING: (2, 2),
        },
    ))


def browser_tool_button_theme(*, checked=False):
    """Compact checkable QToolButton styling for list/details toggles."""
    p = QtFusionPalette
    base = p.HIGHLIGHT_SOFT if checked else (255, 255, 255, 0)
    return make_theme(theme_component(
        ThemeTarget.IMAGE_BUTTON,
        colors={
            ThemeColor.BUTTON: base, ThemeColor.BUTTON_HOVERED: p.BUTTON_HOVER,
            ThemeColor.BUTTON_ACTIVE: p.BUTTON_ACTIVE,
            ThemeColor.BORDER: p.BORDER if checked else (0, 0, 0, 0),
        },
        styles={
            ThemeStyle.FRAME_BORDER_SIZE: 1 if checked else 0,
            ThemeStyle.FRAME_ROUNDING: QtFusionMetrics.FRAME_ROUNDING,
            ThemeStyle.FRAME_PADDING: (3, 3),
        },
    ))


def browser_inline_action_theme():
    """QFileDialog-like action strip used while entering a new folder name."""
    p = QtFusionPalette
    return make_theme(theme_component(
        ThemeTarget.CHILD_WINDOW,
        colors={ThemeColor.CHILD_BACKGROUND: p.WINDOW_ALT, ThemeColor.BORDER: p.BORDER_LIGHT},
        styles={
            ThemeStyle.WINDOW_PADDING: (4, 3), ThemeStyle.ITEM_SPACING: (4, 2),
            ThemeStyle.CHILD_BORDER_SIZE: 0, ThemeStyle.CHILD_ROUNDING: 0,
        },
    ))


def _downsample_icon(image, size=16):
    resampling = getattr(Image, "Resampling", Image).LANCZOS
    return image.resize((size, size), resampling)


def _resize_rgba_for_toolbar(image, size, *, monochrome=False, padding=1, thin_strength=0.0):
    """Crop generated artwork to visible bounds and rasterize it once.

    Image-generation masters intentionally include generous transparent canvas
    margins.  Resizing that *whole* 64px canvas into a 20px toolbar slot made
    the visible glyph much smaller (the old back chevron was only about 9px
    wide) and therefore looked soft even though the texture itself was 20px.

    This path first finds the real alpha bounds, then fits that artwork into the
    final device-pixel canvas with a tiny explicit padding.  Monochrome toolbar
    actions use the generated artwork's alpha geometry but a solid neutral ink;
    this removes the glossy gradient that does not survive at 16-20px sizes.
    """
    size = max(1, int(size))
    padding = max(0, min(int(padding), max(0, size // 3)))
    image = image.convert("RGBA")

    alpha = image.getchannel("A")
    # Ignore near-transparent antialias/fringe pixels when measuring content.
    mask = alpha.point(lambda value: 255 if value > 8 else 0)
    bbox = mask.getbbox()
    if bbox:
        left, top, right, bottom = bbox
        # Preserve one source pixel of antialiasing around the measured shape.
        left = max(0, left - 1)
        top = max(0, top - 1)
        right = min(image.width, right + 1)
        bottom = min(image.height, bottom + 1)
        image = image.crop((left, top, right, bottom))

    available = max(1, size - padding * 2)
    scale = min(available / float(max(1, image.width)),
                available / float(max(1, image.height)))
    draw_width = max(1, int(round(image.width * scale)))
    draw_height = max(1, int(round(image.height * scale)))

    resampling = getattr(Image, "Resampling", Image).LANCZOS
    if monochrome:
        glyph_alpha = image.getchannel("A").resize(
            (draw_width, draw_height), resampling)
        # The image-generation geometry is intentionally bold at master size.
        # At 20 px that made navigation strokes feel heavier than native Qt /
        # Explorer glyphs.  Blend in a one-pixel alpha erosion rather than
        # shrinking the whole icon, so its footprint stays unchanged while the
        # perceived stroke weight drops by roughly 10-15%.
        thin_strength = max(0.0, min(float(thin_strength or 0.0), 1.0))
        if thin_strength > 0.0 and draw_width >= 5 and draw_height >= 5:
            eroded = glyph_alpha.filter(ImageFilter.MinFilter(3))
            glyph_alpha = Image.blend(glyph_alpha, eroded, thin_strength)
        # Flat neutral ink is materially sharper than retaining the generated
        # bevel/gradient at a 20px toolbar size.
        resized = Image.new("RGBA", (draw_width, draw_height), (88, 88, 88, 0))
        resized.putalpha(glyph_alpha)
    else:
        # Strip RGB from fully transparent source pixels so coloured fringe
        # cannot bleed into the small final icon during Lanczos resampling.
        pixels = image.load()
        for y in range(image.height):
            for x in range(image.width):
                red, green, blue, value = pixels[x, y]
                if value <= 6:
                    pixels[x, y] = (0, 0, 0, 0)
        try:
            resized = image.convert("RGBa").resize(
                (draw_width, draw_height), resampling).convert("RGBA")
        except (ValueError, OSError):
            resized = image.resize((draw_width, draw_height), resampling)

        out_alpha = resized.getchannel("A")
        rgb = resized.convert("RGB").filter(
            ImageFilter.UnsharpMask(radius=0.35, percent=170, threshold=1))
        red, green, blue = rgb.split()
        resized = Image.merge("RGBA", (red, green, blue, out_alpha))

    canvas = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    x = (size - draw_width) // 2
    y = (size - draw_height) // 2
    canvas.alpha_composite(resized, (x, y))

    pixels = canvas.load()
    for y in range(canvas.height):
        for x in range(canvas.width):
            red, green, blue, value = pixels[x, y]
            if value <= 4:
                pixels[x, y] = (0, 0, 0, 0)
    return canvas


def _generated_folder_selector_icon(key, disabled=False, size=20):
    """Return an exact-size generated PNG texture for the folder chooser.

    Previous revisions accidentally passed these masters through
    ``WindowsIconRegistry._add_texture``.  That API is deliberately a 16px
    Windows-Shell icon uploader, so a 64px master became 16px and was then
    stretched to 20px by the toolbar.  Keep toolbar resources on a separate
    exact-size path instead.
    """
    normalized = str(key or "").strip().lower().replace(" ", "_")
    filename = FOLDER_SELECTOR_ICON_MAP.get(normalized)
    if not filename:
        return None
    size = max(1, int(size))
    tag = "folder_selector_generated_{}_{}_{}px".format(
        normalized, "disabled" if disabled else "normal", size)
    if dpg.does_item_exist(tag):
        return tag
    # A live context texture is authoritative. Do not stat the same bundled
    # PNG for every directory row or every toolbar rebuild on the click path.
    path = FOLDER_SELECTOR_ICON_DIR / filename
    if not path.is_file():
        return None
    try:
        image = Image.open(path).convert("RGBA")
        if image.size != (FOLDER_SELECTOR_MASTER_SIZE, FOLDER_SELECTOR_MASTER_SIZE):
            image = image.resize(
                (FOLDER_SELECTOR_MASTER_SIZE, FOLDER_SELECTOR_MASTER_SIZE),
                getattr(Image, "Resampling", Image).LANCZOS)

        monochrome = normalized in {
            "back", "forward", "up", "refresh", "search", "chevron",
            "edit_address", "address_menu", "details", "list",
        }
        thin_strength = {
            # Rev 1.1.4 masters are already drawn with a lighter optical
            # weight. Keep erosion subtle so 16-20 px edges stay crisp.
            "back": 0.18, "forward": 0.18, "up": 0.18,
            "refresh": 0.14, "details": 0.12, "list": 0.12,
            "search": 0.10, "chevron": 0.10,
            "edit_address": 0.10, "address_menu": 0.10,
        }.get(normalized, 0.0)
        image = _resize_rgba_for_toolbar(
            image, size, monochrome=monochrome, thin_strength=thin_strength)
        if disabled:
            alpha = image.getchannel("A").point(lambda value: int(value * 0.46))
            image.putalpha(alpha)
        return WindowsIconRegistry._add_native_texture(image, tag)
    except Exception:
        return None


def address_location_texture(path, size=18):
    """Return a sharp address-bar location icon, preferring the generated drive glyph.

    Root drive locations are the common case in the Open Folder address bar
    shown by WinUx.  Non-root folders keep their Windows Shell icon so the
    semantic behavior of the chooser is preserved.
    """
    value = os.path.abspath(str(path or os.curdir))
    drive, tail = os.path.splitdrive(value)
    if drive and tail in ("\\", "/", ""):
        return _generated_folder_selector_icon("drive", size=size) or WindowsIconRegistry.get_path_icon(value)
    if os.path.dirname(value) == value:
        return _generated_folder_selector_icon("drive", size=size) or WindowsIconRegistry.get_path_icon(value)
    # The address bar only needs the folder semantic, not a path-specific 16px
    # Shell bitmap. Use an exact-size folder texture so the 18px slot stays 1:1.
    return folder_item_texture(size=size)


def _crisp_toolbar_icon(key, disabled=False):
    """Render crisp 20x20 toolbar icons directly to avoid soft imagegen edges."""
    normalized = str(key or "").strip().lower()
    tag = f"folder_selector_crisp_{normalized}_{'disabled' if disabled else 'normal'}"
    if dpg.does_item_exist(tag):
        return tag
    image = Image.new("RGBA", (20, 20), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    alpha = 125 if disabled else 255
    ink = (97, 97, 97, alpha)
    ink2 = (120, 120, 120, alpha)
    yellow = (241, 182, 52, alpha)
    yellow_hi = (250, 205, 104, alpha)
    yellow_shadow = (210, 157, 39, alpha)
    blue = (0, 120, 215, alpha)
    if normalized == 'back':
        draw.line((13, 3, 7, 9, 13, 15), fill=ink, width=2)
    elif normalized == 'forward':
        draw.line((7, 3, 13, 9, 7, 15), fill=ink, width=2)
    elif normalized == 'up':
        draw.line((10, 3, 10, 16), fill=ink, width=2)
        draw.line((5, 8, 10, 3, 15, 8), fill=ink, width=2)
    elif normalized == 'refresh':
        draw.arc((4, 4, 15, 15), start=30, end=330, fill=ink, width=2)
        draw.polygon(((12, 4), (16, 5), (13, 8)), fill=ink)
    elif normalized == 'search':
        draw.ellipse((3, 3, 12, 12), outline=ink, width=2)
        draw.line((11, 11, 16, 16), fill=ink, width=2)
    elif normalized == 'details':
        for y in (5, 9, 13):
            draw.rectangle((3, y-1, 5, y+1), fill=ink)
            draw.line((8, y, 16, y), fill=ink2, width=2)
    elif normalized == 'list':
        for y in (5, 9, 13):
            draw.line((3, y, 16, y), fill=ink, width=2)
    elif normalized == 'new_folder':
        draw.rounded_rectangle((2, 6, 15, 15), radius=1, fill=yellow, outline=yellow_shadow, width=1)
        draw.polygon(((2, 6), (2, 4), (7, 4), (9, 6)), fill=yellow_hi)
        draw.line((2, 6, 15, 6), fill=yellow_shadow, width=1)
        draw.line((11, 11, 17, 11), fill=blue, width=2)
        draw.line((14, 8, 14, 14), fill=blue, width=2)
    else:
        return None
    return WindowsIconRegistry._add_texture(image, tag)


def view_mode_texture(mode):
    """Small symbolic Qt tool-button icons, not Explorer's colored tiles."""
    key = "list" if str(mode or "details").strip().lower() == "list" else "details"
    return qt_browser_texture(key)


def browser_details_theme():
    """QHeaderView-like table chrome; row selection stays owned by QtListView."""
    p = QtFusionPalette
    table = theme_component(
        ThemeTarget.TABLE,
        colors={
            ThemeColor.TABLE_HEADER_BACKGROUND: p.TOOLBAR, ThemeColor.HEADER: p.TOOLBAR,
            ThemeColor.HEADER_HOVERED: p.HEADER_HOVER, ThemeColor.HEADER_ACTIVE: p.HEADER_PRESSED,
            ThemeColor.TABLE_BORDER_STRONG: (0, 0, 0, 0), ThemeColor.TABLE_BORDER_LIGHT: (0, 0, 0, 0),
            ThemeColor.TABLE_ROW_BACKGROUND: p.BASE, ThemeColor.TABLE_ROW_BACKGROUND_ALT: p.BASE,
        },
        styles={ThemeStyle.CELL_PADDING: (5, 1), ThemeStyle.ITEM_SPACING: (0, 0)},
    )
    button = theme_component(
        ThemeTarget.PUSH_BUTTON,
        colors={
            ThemeColor.BUTTON: p.TOOLBAR, ThemeColor.BUTTON_HOVERED: p.HEADER_HOVER,
            ThemeColor.BUTTON_ACTIVE: p.HEADER_PRESSED, ThemeColor.TEXT: p.TEXT,
            ThemeColor.BORDER: p.BORDER_LIGHT,
        },
        styles={
            ThemeStyle.FRAME_BORDER_SIZE: 0, ThemeStyle.FRAME_ROUNDING: 0,
            ThemeStyle.FRAME_PADDING: (6, 3),
        },
    ).with_style(ThemeStyle.BUTTON_TEXT_ALIGN, 0.0, 0.5, optional=True)
    return make_theme(with_scrollbar(table, track=p.WINDOW_ALT), button)



def browser_empty_state_theme():
    """Muted QFileDialog/QAbstractItemView empty-state surface."""
    p = QtFusionPalette
    return make_theme(
        theme_component(
            ThemeTarget.CHILD_WINDOW,
            colors={ThemeColor.CHILD_BACKGROUND: p.BASE, ThemeColor.BORDER: (0, 0, 0, 0)},
            styles={
                ThemeStyle.WINDOW_PADDING: (8, 8), ThemeStyle.ITEM_SPACING: (4, 4),
                ThemeStyle.CHILD_BORDER_SIZE: 0, ThemeStyle.CHILD_ROUNDING: 0,
            },
        ),
        theme_component(ThemeTarget.TEXT, colors={ThemeColor.TEXT: p.TEXT_MUTED}),
    )


def browser_status_text_theme(*, error=False):
    """QDialogButtonBox status text: muted normally, danger colour on errors."""
    p = QtFusionPalette
    return make_theme(theme_component(
        ThemeTarget.TEXT, colors={ThemeColor.TEXT: p.DANGER if error else p.TEXT_MUTED},
    ))


def browser_footer_theme():
    """Compact QFileDialog/QDialogButtonBox footer surface."""
    p = QtFusionPalette
    return make_theme(theme_component(
        ThemeTarget.CHILD_WINDOW,
        colors={ThemeColor.CHILD_BACKGROUND: p.WINDOW, ThemeColor.BORDER: (0, 0, 0, 0)},
        styles={
            ThemeStyle.WINDOW_PADDING: (12, 8), ThemeStyle.ITEM_SPACING: (6, 2),
            ThemeStyle.CHILD_BORDER_SIZE: 0, ThemeStyle.CHILD_ROUNDING: 0,
        },
    ))


def browser_sidebar_section_text_theme():
    """QTreeView top-level branch label styling."""
    return make_theme(theme_component(
        ThemeTarget.TEXT, colors={ThemeColor.TEXT: QtFusionPalette.TEXT},
    ))

def browser_divider_theme():
    return make_theme(theme_component(
        ThemeTarget.CHILD_WINDOW,
        colors={ThemeColor.CHILD_BACKGROUND: QtFusionPalette.BORDER_LIGHT, ThemeColor.BORDER: (0, 0, 0, 0)},
        styles={
            ThemeStyle.WINDOW_PADDING: (0, 0), ThemeStyle.CHILD_BORDER_SIZE: 0,
            ThemeStyle.CHILD_ROUNDING: 0,
        },
    ))


def browser_selection_bar_theme():
    p = QtFusionPalette
    return make_theme(theme_component(
        ThemeTarget.CHILD_WINDOW,
        colors={ThemeColor.CHILD_BACKGROUND: p.WINDOW, ThemeColor.BORDER: (0, 0, 0, 0)},
        styles={
            ThemeStyle.WINDOW_PADDING: (4, 4), ThemeStyle.ITEM_SPACING: (0, 0),
            ThemeStyle.CHILD_BORDER_SIZE: 0, ThemeStyle.CHILD_ROUNDING: 0,
        },
    ))


def browser_separator_theme():
    p = QtFusionPalette
    return make_theme(theme_component(
        ThemeTarget.SEPARATOR,
        colors={
            ThemeColor.SEPARATOR: p.BORDER_LIGHT,
            ThemeColor.SEPARATOR_HOVERED: p.BORDER_LIGHT,
            ThemeColor.SEPARATOR_ACTIVE: p.BORDER_LIGHT,
        },
    ))



def _navigation_texture(name, disabled=False):
    """Build one cached Qt-like toolbar glyph texture."""
    key = str(name or "").strip().lower().replace(" ", "_")
    if key in ("back", "forward", "up", "refresh", "edit_address", "address_menu", "chevron"):
        return qt_browser_texture(key, disabled=disabled)
    generated = _generated_folder_selector_icon(key, disabled=disabled, size=20)
    if generated:
        return generated
    crisp = _crisp_toolbar_icon(key, disabled=disabled)
    if crisp:
        return crisp
    tag = "native_browser_nav_{}_{}_aa".format(key, "disabled" if disabled else "normal")
    if dpg.does_item_exist(tag):
        return tag
    scale = 2
    image = Image.new("RGBA", (16 * scale, 16 * scale), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    ink = (158, 158, 158, 255) if disabled else (61, 61, 61, 255)
    muted = (180, 180, 180, 255) if disabled else (102, 102, 102, 255)
    w = 2 * scale
    # PIL expects a flat coordinate sequence; keep each toolbar shape explicit.
    if key == "back":
        draw.line((10*scale,3*scale,5*scale,8*scale,10*scale,13*scale), fill=ink, width=w, joint="curve")
    elif key == "forward":
        draw.line((6*scale,3*scale,11*scale,8*scale,6*scale,13*scale), fill=ink, width=w, joint="curve")
    elif key == "up":
        draw.line((3*scale,10*scale,8*scale,5*scale,13*scale,10*scale), fill=ink, width=w, joint="curve")
        draw.line((8*scale,5*scale,8*scale,14*scale), fill=ink, width=w)
    elif key == "refresh":
        draw.arc((3*scale,3*scale,13*scale,13*scale), start=35, end=320, fill=ink, width=w)
        draw.polygon(((11*scale,2*scale),(14*scale,3*scale),(13*scale,6*scale)), fill=ink)
    elif key == "search":
        draw.ellipse((3*scale,3*scale,10*scale,10*scale), outline=ink, width=w)
        draw.line((9*scale,9*scale,14*scale,14*scale), fill=ink, width=w)
    elif key in ("clear", "close"):
        draw.line((4*scale,4*scale,12*scale,12*scale), fill=muted, width=w)
        draw.line((12*scale,4*scale,4*scale,12*scale), fill=muted, width=w)
    elif key in ("edit_address", "address_menu"):
        # QComboBox/QFileDialog-style down chevron.  This replaces the old
        # generic square fallback that appeared as a broken icon in the field.
        draw.line((4*scale,6*scale,8*scale,10*scale,12*scale,6*scale),
                  fill=ink, width=1*scale, joint="curve")
    else:
        draw.rounded_rectangle((5*scale,5*scale,11*scale,11*scale),
                               radius=1*scale, outline=ink, width=1*scale)
    return WindowsIconRegistry._add_texture(_downsample_icon(image), tag)


def navigation_texture(name):
    """Create the normal DPI-stable Qt-like toolbar glyph."""
    return _navigation_texture(name, disabled=False)


def navigation_disabled_texture(name):
    """Create the muted disabled-state variant used by QToolButton chrome."""
    return _navigation_texture(name, disabled=True)


def navigation_button_theme():
    p = QtFusionPalette
    components = []
    for target in (ThemeTarget.PUSH_BUTTON, ThemeTarget.IMAGE_BUTTON):
        for enabled in (True, False):
            components.append(theme_component(
                target, enabled_state=enabled,
                colors={
                    ThemeColor.BUTTON: (255, 255, 255, 0),
                    ThemeColor.BUTTON_HOVERED: p.BUTTON_HOVER,
                    ThemeColor.BUTTON_ACTIVE: p.BUTTON_ACTIVE,
                    ThemeColor.TEXT: p.TEXT if enabled else p.TEXT_DISABLED,
                    ThemeColor.TEXT_DISABLED: p.TEXT_DISABLED,
                    ThemeColor.BORDER: (0, 0, 0, 0),
                },
                styles={
                    ThemeStyle.FRAME_BORDER_SIZE: 0,
                    ThemeStyle.FRAME_ROUNDING: QtFusionMetrics.FRAME_ROUNDING,
                    ThemeStyle.FRAME_PADDING: (3, 3),
                },
            ))
    return make_theme(*components)


def folder_item_texture(size=16):
    """Use the real Windows Shell directory icon, not a drawn substitute.

    ``size`` remains a compatibility argument for the address-bar/list callers;
    the registry owns the shared native folder texture and its system fallback.
    """
    return WindowsIconRegistry.get_icon(is_dir=True)


def new_folder_texture():
    return qt_browser_texture("new_folder")


def _qt_browser_symbol_image(name, *, disabled=False, size=16):
    """Draw a single-tab folder and consistent fine-stroke toolbar symbols.

    Retain a 3x texture master instead of uploading a 16 px raster which Windows
    then has to magnify at 125/150/200% display scale.
    """
    key = str(name).lower().replace(" ", "_")
    size = max(1, int(size))
    image = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    ink = (160, 160, 160, 255) if disabled else (48, 52, 55, 255)
    def line(points):
        draw.line([(int(x * 4), int(y * 4)) for x, y in points], fill=ink, width=4)
    if key == "back":
        line([(10, 3), (5, 8), (10, 13)])
    elif key == "forward":
        line([(6, 3), (11, 8), (6, 13)])
    elif key == "up":
        line([(3, 10), (8, 5), (13, 10)])
    elif key in ("edit_address", "address_menu", "chevron"):
        draw.polygon([(5*4, 6*4), (11*4, 6*4), (8*4, 10*4)], fill=ink)
    elif key == "list":
        for x in (3, 9):
            for y in (3, 9):
                draw.rectangle((x*4, y*4, (x+3)*4, (y+3)*4), fill=ink)
    elif key == "details":
        for y in (4, 8, 12):
            line([(3, y), (5, y)])
            line([(7, y), (13, y)])
    elif key == "refresh":
        draw.arc((3*4, 3*4, 13*4, 13*4), 35, 320, fill=ink, width=4)
        draw.polygon([(11*4, 2*4), (14*4, 3*4), (13*4, 6*4)], fill=ink)
    else:
        # One continuous silhouette. The old second tab/stroke above it made
        # the glyph look like two stacked folders rather than Qt's directory.
        line([(2.5, 4.5), (6.5, 4.5), (8.5, 6.5), (13.5, 6.5),
              (13.5, 12.5), (2.5, 12.5), (2.5, 4.5)])
        if key == "new_folder":
            # Separate the plus from the folder outline instead of overlaying
            # two dark strokes into an unreadable blob.
            draw.rectangle((9*4, 8*4, 16*4, 15*4), fill=(0, 0, 0, 0))
            line([(10, 11.5), (15, 11.5)])
            line([(12.5, 9), (12.5, 14)])
    return image.resize((size * 3, size * 3), Image.Resampling.LANCZOS)


def qt_browser_texture(name, *, disabled=False, size=16):
    """Cache dense symbolic masters while keeping the display slot 16 logical px."""
    key = str(name).lower().replace(" ", "_")
    size = max(1, int(size))
    tag = "qt_browser_symbol_v2_{}_{}_{}".format(key, size, int(disabled))
    if dpg.does_item_exist(tag):
        return tag
    return WindowsIconRegistry._add_native_texture(
        _qt_browser_symbol_image(name, disabled=disabled, size=size), tag)


def prepare_browser_textures():
    """Warm bounded shared graphics on the hidden host's DPG owner thread.

    Never construct a chooser, enumerate folders/drives, read preferences or
    install handlers. These context-scoped textures are the same caches used
    by real forms; a destroyed DPG context naturally invalidates their tags.
    """
    textures = []
    for name in ("Back", "Forward", "Up", "Refresh", "Search", "Clear",
                 "Chevron", "Edit address", "Address menu"):
        textures.append(navigation_texture(name))
    for name in ("Back", "Forward", "Up"):
        textures.append(navigation_disabled_texture(name))
    textures.extend((new_folder_texture(), view_mode_texture("details"),
                     view_mode_texture("list"), folder_item_texture(16),
                     folder_item_texture(18),
                     _generated_folder_selector_icon("drive", size=18),
                     WindowsIconRegistry.get_icon(is_dir=True)))
    # Only documented, path-independent Shell stock icons. No mapped drive or
    # network location is probed just to prepare an idle browser host.
    for stock_id in (7, 8, 9, 11, 12, 58, 94):
        textures.append(WindowsIconRegistry.get_stock_icon(stock_id))
    return tuple(dict.fromkeys(texture for texture in textures if texture is not None))


def navigation_button(parent, name, callback, font, theme):
    # Use a generated monochrome glyph rather than a font codepoint.  Qt-like
    # toolbar icons should keep the same geometry across DPI/font changes.
    control = QToolButton(
        "", parent=parent, icon=navigation_texture(name), icon_size=(METRICS.icon_size, METRICS.icon_size),
        width=METRICS.tool_button_size, height=METRICS.tool_button_size)
    control.clicked.connect(callback)
    control.setTheme(theme)
    add_styled_tooltip(control.tag, name)
    return control.tag
