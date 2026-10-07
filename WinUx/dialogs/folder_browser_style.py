"""Qt/Fusion-like chrome for the Dear ImGui folder chooser.

The folder chooser stays Dear PyGui-only.  This module deliberately gives the
whole browser one visual hierarchy (toolbars -> framed viewport -> selection
bar -> dialog button box) instead of styling isolated ImGui controls.
"""
import os
from dataclasses import dataclass
from pathlib import Path
import dearpygui.dearpygui as dpg
from PIL import Image, ImageDraw, ImageFilter, ImageOps

from ..components.qt_style import QtFusionPalette, QtFusionMetrics
from ..components.shared_scroller import add_dpg_scroller_style
from ..components.tooltip import add_styled_tooltip
from ..platform.windows_icons import WindowsIconRegistry


GLYPHS = {"Back": 0xE72B, "Forward": 0xE72A, "Up": 0xE74A,
          "Refresh": 0xE72C, "Go": 0xE72A, "Search": 0xE721,
          "Edit address": 0xE70D, "New folder": 0xE8F4,
          "Home": 0xE80F, "Chevron": 0xE76C,
          "Expanded": 0xE70D, "Collapsed": 0xE76C}


@dataclass(frozen=True)
class BrowserMetrics:
    location_height: int = 28
    toolbar_height: int = 34
    command_height: int = 28
    navigation_width: int = 28
    sidebar_width: int = 196
    sidebar_row_height: int = 24
    sidebar_section_gap: int = 8
    header_height: int = 24
    row_height: int = 20
    divider_width: int = 1
    selection_height: int = 36
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
    with dpg.theme() as theme:
        with dpg.theme_component(dpg.mvAll):
            dpg.add_theme_color(dpg.mvThemeCol_ChildBg, background)
            dpg.add_theme_color(dpg.mvThemeCol_Border, p.BORDER_LIGHT)
            dpg.add_theme_color(dpg.mvThemeCol_TableHeaderBg, p.TOOLBAR)
            dpg.add_theme_color(dpg.mvThemeCol_TableBorderLight, p.BORDER_LIGHT)
            dpg.add_theme_style(dpg.mvStyleVar_WindowPadding, *padding)
            dpg.add_theme_style(dpg.mvStyleVar_ItemSpacing, *spacing)
            dpg.add_theme_style(dpg.mvStyleVar_ChildRounding, 0)
            dpg.add_theme_style(dpg.mvStyleVar_CellPadding, *cell_padding)
    return theme


def browser_dialog_body_theme():
    return browser_surface_theme(
        background=QtFusionPalette.WINDOW,
        padding=(8, 7), cell_padding=(4, 2), spacing=(5, 5))


def browser_layout_theme(cell_padding=(2, 1)):
    with dpg.theme() as theme:
        with dpg.theme_component(dpg.mvTable):
            dpg.add_theme_style(dpg.mvStyleVar_CellPadding, *cell_padding)
            dpg.add_theme_color(dpg.mvThemeCol_TableBorderStrong, (0, 0, 0, 0))
            dpg.add_theme_color(dpg.mvThemeCol_TableBorderLight, (0, 0, 0, 0))
    return theme


def browser_toolbar_theme(*, border_bottom=False):
    p = QtFusionPalette
    with dpg.theme() as theme:
        with dpg.theme_component(dpg.mvChildWindow):
            dpg.add_theme_color(dpg.mvThemeCol_ChildBg, p.WINDOW)
            dpg.add_theme_color(dpg.mvThemeCol_Border,
                                p.BORDER_LIGHT if border_bottom else (0, 0, 0, 0))
            dpg.add_theme_style(dpg.mvStyleVar_WindowPadding, 0, 3)
            dpg.add_theme_style(dpg.mvStyleVar_ItemSpacing, 4, 2)
            dpg.add_theme_style(dpg.mvStyleVar_ChildBorderSize, 0)
            dpg.add_theme_style(dpg.mvStyleVar_ChildRounding, 0)
    return theme


def browser_field_shell_theme(*, focused=False):
    p = QtFusionPalette
    with dpg.theme() as theme:
        with dpg.theme_component(dpg.mvChildWindow):
            dpg.add_theme_color(dpg.mvThemeCol_ChildBg, p.BASE)
            dpg.add_theme_color(dpg.mvThemeCol_Border, p.FOCUS if focused else p.BORDER)
            dpg.add_theme_style(dpg.mvStyleVar_WindowPadding, 3, 1)
            dpg.add_theme_style(dpg.mvStyleVar_ChildBorderSize, 1)
            dpg.add_theme_style(dpg.mvStyleVar_ChildRounding, 1)
    return theme


def browser_icon_slot_theme():
    """Borderless fixed-height slot that vertically centers embedded icons.

    Dear ImGui table cells top-align images while QLineEdit/QToolBar content is
    vertically centered.  A tiny child canvas gives address/search icons their
    own stable alignment without changing input routing.
    """
    p = QtFusionPalette
    with dpg.theme() as theme:
        with dpg.theme_component(dpg.mvChildWindow):
            dpg.add_theme_color(dpg.mvThemeCol_ChildBg, p.BASE)
            dpg.add_theme_color(dpg.mvThemeCol_Border, (0, 0, 0, 0))
            dpg.add_theme_style(dpg.mvStyleVar_WindowPadding, 0, 0)
            dpg.add_theme_style(dpg.mvStyleVar_ItemSpacing, 0, 0)
            dpg.add_theme_style(dpg.mvStyleVar_ChildBorderSize, 0)
            dpg.add_theme_style(dpg.mvStyleVar_ChildRounding, 0)
    return theme


def browser_embedded_editor_theme():
    p = QtFusionPalette
    with dpg.theme() as theme:
        with dpg.theme_component(dpg.mvInputText):
            clear = (255, 255, 255, 0)
            dpg.add_theme_color(dpg.mvThemeCol_FrameBg, clear)
            dpg.add_theme_color(dpg.mvThemeCol_FrameBgHovered, clear)
            dpg.add_theme_color(dpg.mvThemeCol_FrameBgActive, clear)
            dpg.add_theme_color(dpg.mvThemeCol_Border, clear)
            dpg.add_theme_color(dpg.mvThemeCol_Text, p.TEXT)
            dpg.add_theme_color(dpg.mvThemeCol_TextSelectedBg, (0, 120, 215, 100))
            dpg.add_theme_style(dpg.mvStyleVar_FrameBorderSize, 0)
            dpg.add_theme_style(dpg.mvStyleVar_FrameRounding, 0)
            dpg.add_theme_style(dpg.mvStyleVar_FramePadding, 3, 4)
    return theme


def browser_workspace_theme():
    p = QtFusionPalette
    with dpg.theme() as theme:
        with dpg.theme_component(dpg.mvChildWindow):
            dpg.add_theme_color(dpg.mvThemeCol_ChildBg, p.BASE)
            dpg.add_theme_color(dpg.mvThemeCol_Border, p.BORDER)
            dpg.add_theme_style(dpg.mvStyleVar_WindowPadding, 0, 0)
            dpg.add_theme_style(dpg.mvStyleVar_ItemSpacing, 0, 0)
            dpg.add_theme_style(dpg.mvStyleVar_ChildBorderSize, 1)
            dpg.add_theme_style(dpg.mvStyleVar_ChildRounding, 0)
    return theme


def browser_sidebar_theme():
    p = QtFusionPalette
    with dpg.theme() as theme:
        with dpg.theme_component(dpg.mvChildWindow):
            dpg.add_theme_color(dpg.mvThemeCol_ChildBg, p.BASE)
            dpg.add_theme_color(dpg.mvThemeCol_Border, (0, 0, 0, 0))
            dpg.add_theme_style(dpg.mvStyleVar_WindowPadding, 3, 4)
            dpg.add_theme_style(dpg.mvStyleVar_ItemSpacing, 3, 1)
            dpg.add_theme_style(dpg.mvStyleVar_ChildBorderSize, 0)
            dpg.add_theme_style(dpg.mvStyleVar_ChildRounding, 0)
            add_dpg_scroller_style(dpg, track=p.WINDOW_ALT)
    return theme


def browser_sidebar_row_theme():
    """QTreeView item palette for Places rows.

    A selected ``mvSelectable`` paints ``Header`` continuously, so use the
    real active-selection role here instead of the pale hover colour.  The
    overlay label is recoloured separately by
    :func:`browser_sidebar_item_text_theme`, keeping icon + text readable as
    one Qt-style selected row.
    """
    p = QtFusionPalette
    with dpg.theme() as theme:
        with dpg.theme_component(dpg.mvSelectable):
            dpg.add_theme_color(dpg.mvThemeCol_Header, p.SELECTION_ACTIVE)
            dpg.add_theme_color(dpg.mvThemeCol_HeaderHovered, p.SELECTION_ACTIVE_HOVER)
            dpg.add_theme_color(dpg.mvThemeCol_HeaderActive, p.SELECTION_ACTIVE_PRESSED)
            dpg.add_theme_color(dpg.mvThemeCol_NavHighlight, p.FOCUS)
            dpg.add_theme_color(dpg.mvThemeCol_Text, p.SELECTION_TEXT)
            dpg.add_theme_style(dpg.mvStyleVar_FramePadding, 4, 3)
            dpg.add_theme_style(dpg.mvStyleVar_FrameRounding, 0)
            dpg.add_theme_style(dpg.mvStyleVar_SelectableTextAlign, 0.0, 0.5)
    return theme


def browser_sidebar_item_text_theme(*, selected=False):
    """Display-role text for overlay labels in QTreeView-like rows.

    The sidebar uses an empty Selectable as the full-row hit/selection target
    and draws the icon/label above it.  Dear ImGui therefore cannot recolor the
    overlay label automatically when the row becomes selected; mirror Qt's
    highlighted-text role explicitly.
    """
    p = QtFusionPalette
    with dpg.theme() as theme:
        with dpg.theme_component(dpg.mvText):
            dpg.add_theme_color(
                dpg.mvThemeCol_Text, p.SELECTION_TEXT if selected else p.TEXT)
    return theme


def browser_list_viewport_theme():
    """QAbstractItemView viewport chrome for the folder list.

    FolderListView intentionally keeps the outer child window as the stable
    scroll owner.  Binding a generic browser surface here used to overwrite
    QtListView's scrollbar metrics; keep the flat viewport while restoring the
    shared WinUx/Qt scrollbar palette and thickness.
    """
    p = QtFusionPalette
    with dpg.theme() as theme:
        with dpg.theme_component(dpg.mvChildWindow):
            dpg.add_theme_color(dpg.mvThemeCol_ChildBg, p.BASE)
            dpg.add_theme_color(dpg.mvThemeCol_Border, (0, 0, 0, 0))
            dpg.add_theme_style(dpg.mvStyleVar_WindowPadding, 0, 0)
            dpg.add_theme_style(dpg.mvStyleVar_ItemSpacing, 0, 0)
            dpg.add_theme_style(dpg.mvStyleVar_ChildBorderSize, 0)
            dpg.add_theme_style(dpg.mvStyleVar_ChildRounding, 0)
            add_dpg_scroller_style(dpg, track=p.WINDOW_ALT)
    return theme


def browser_row_cell_theme():
    """Transparent fixed-height cell canvas for QFileDialog detail rows.

    The table owns the selected-row background.  Keeping each cell canvas
    transparent lets ``highlight_table_row`` paint continuously across Name,
    Date modified and Type while icon/text overlays use one vertical metric.
    """
    with dpg.theme() as theme:
        with dpg.theme_component(dpg.mvChildWindow):
            dpg.add_theme_color(dpg.mvThemeCol_ChildBg, (0, 0, 0, 0))
            dpg.add_theme_color(dpg.mvThemeCol_Border, (0, 0, 0, 0))
            dpg.add_theme_style(dpg.mvStyleVar_WindowPadding, 0, 0)
            dpg.add_theme_style(dpg.mvStyleVar_ItemSpacing, 0, 0)
            dpg.add_theme_style(dpg.mvStyleVar_ChildBorderSize, 0)
            dpg.add_theme_style(dpg.mvStyleVar_ChildRounding, 0)
    return theme


def browser_sidebar_item_container_theme():
    """Zero-margin canvas for one QTreeView-like sidebar row."""
    p = QtFusionPalette
    with dpg.theme() as theme:
        with dpg.theme_component(dpg.mvChildWindow):
            dpg.add_theme_color(dpg.mvThemeCol_ChildBg, p.BASE)
            dpg.add_theme_color(dpg.mvThemeCol_Border, (0, 0, 0, 0))
            dpg.add_theme_style(dpg.mvStyleVar_WindowPadding, 0, 0)
            dpg.add_theme_style(dpg.mvStyleVar_ItemSpacing, 0, 0)
            dpg.add_theme_style(dpg.mvStyleVar_ChildBorderSize, 0)
            dpg.add_theme_style(dpg.mvStyleVar_ChildRounding, 0)
    return theme


def browser_sidebar_header_theme():
    """Unselected QTreeView branch row with only hover/press feedback."""
    p = QtFusionPalette
    with dpg.theme() as theme:
        with dpg.theme_component(dpg.mvSelectable):
            dpg.add_theme_color(dpg.mvThemeCol_Header, (0, 0, 0, 0))
            dpg.add_theme_color(dpg.mvThemeCol_HeaderHovered, p.HIGHLIGHT_HOVER)
            dpg.add_theme_color(dpg.mvThemeCol_HeaderActive, p.BUTTON_ACTIVE)
            dpg.add_theme_color(dpg.mvThemeCol_Text, p.TEXT)
            dpg.add_theme_style(dpg.mvStyleVar_FramePadding, 0, 0)
            dpg.add_theme_style(dpg.mvStyleVar_FrameRounding, 0)
    return theme


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
    with dpg.theme() as theme:
        with dpg.theme_component(dpg.mvButton):
            dpg.add_theme_color(dpg.mvThemeCol_Button, (0, 0, 0, 0))
            dpg.add_theme_color(dpg.mvThemeCol_ButtonHovered, p.HIGHLIGHT_HOVER)
            dpg.add_theme_color(dpg.mvThemeCol_ButtonActive, p.HIGHLIGHT_SOFT)
            dpg.add_theme_color(dpg.mvThemeCol_Text, p.TEXT)
            dpg.add_theme_color(dpg.mvThemeCol_Border, (0, 0, 0, 0))
            dpg.add_theme_style(dpg.mvStyleVar_FrameBorderSize, 0)
            dpg.add_theme_style(dpg.mvStyleVar_FrameRounding, 0)
            dpg.add_theme_style(dpg.mvStyleVar_FramePadding, 3, 2)
    return theme


def browser_breadcrumb_blank_theme():
    """Invisible address-bar remainder that stays visually inert on hover."""
    p = QtFusionPalette
    with dpg.theme() as theme:
        with dpg.theme_component(dpg.mvButton):
            clear = (0, 0, 0, 0)
            dpg.add_theme_color(dpg.mvThemeCol_Button, clear)
            dpg.add_theme_color(dpg.mvThemeCol_ButtonHovered, clear)
            dpg.add_theme_color(dpg.mvThemeCol_ButtonActive, clear)
            dpg.add_theme_color(dpg.mvThemeCol_Text, p.TEXT)
            dpg.add_theme_color(dpg.mvThemeCol_Border, clear)
            dpg.add_theme_style(dpg.mvStyleVar_FrameBorderSize, 0)
            dpg.add_theme_style(dpg.mvStyleVar_FrameRounding, 0)
            dpg.add_theme_style(dpg.mvStyleVar_FramePadding, 0, 0)
    return theme


def create_breadcrumb_chevron(parent):
    """Draw a DPI-stable Qt-style breadcrumb separator without font glyphs."""
    height = max(18, METRICS.location_height - 3)
    canvas = dpg.add_drawlist(11, height, parent=parent)
    cy = height * 0.5
    color = QtFusionPalette.TEXT_MUTED
    dpg.draw_line((4.0, cy - 3.5), (7.5, cy), parent=canvas, color=color, thickness=1.0)
    dpg.draw_line((7.5, cy), (4.0, cy + 3.5), parent=canvas, color=color, thickness=1.0)
    return canvas


def browser_toolbar_divider_theme():
    """Compatibility theme for older callers; the toolbar now draws its divider."""
    with dpg.theme() as theme:
        with dpg.theme_component(dpg.mvChildWindow):
            dpg.add_theme_color(dpg.mvThemeCol_ChildBg, (0, 0, 0, 0))
            dpg.add_theme_color(dpg.mvThemeCol_Border, (0, 0, 0, 0))
            dpg.add_theme_style(dpg.mvStyleVar_WindowPadding, 0, 0)
            dpg.add_theme_style(dpg.mvStyleVar_ChildBorderSize, 0)
            dpg.add_theme_style(dpg.mvStyleVar_ChildRounding, 0)
    return theme


def create_toolbar_divider(parent):
    """Draw one optically centered, one-pixel toolbar separator.

    A 1 px ``mvChildWindow`` is not reliable inside an ImGui table cell: the
    child can inherit padding/minimum sizing and appears as a thick, top-biased
    gray strip on Windows.  A draw-list line keeps the separator exactly one
    device pixel wide and lets us center its shorter 14 px stroke inside the
    28 px location row.
    """
    height = METRICS.location_height
    width = 9
    canvas = dpg.add_drawlist(width=width, height=height, parent=parent)
    line_height = 14
    y1 = (height - line_height) * 0.5
    y2 = y1 + line_height
    # Half-pixel x placement keeps a 1 px line aligned to the raster grid.
    x = (width * 0.5) + 0.5
    dpg.draw_line(
        (x, y1), (x, y2), parent=canvas,
        color=(218, 218, 218, 255), thickness=1.0)
    return canvas


def browser_inline_icon_button_theme():
    """Small borderless icon button embedded in a QLineEdit-like field."""
    p = QtFusionPalette
    with dpg.theme() as theme:
        with dpg.theme_component(dpg.mvImageButton):
            dpg.add_theme_color(dpg.mvThemeCol_Button, (0, 0, 0, 0))
            dpg.add_theme_color(dpg.mvThemeCol_ButtonHovered, p.HIGHLIGHT_HOVER)
            dpg.add_theme_color(dpg.mvThemeCol_ButtonActive, p.HIGHLIGHT_SOFT)
            dpg.add_theme_color(dpg.mvThemeCol_Border, (0, 0, 0, 0))
            dpg.add_theme_style(dpg.mvStyleVar_FrameBorderSize, 0)
            dpg.add_theme_style(dpg.mvStyleVar_FrameRounding, 2)
            dpg.add_theme_style(dpg.mvStyleVar_FramePadding, 2, 2)
    return theme


def browser_tool_button_theme(*, checked=False):
    """Compact checkable QToolButton styling for list/details toggles.

    Qt's checked tool buttons retain a soft sunken fill; they do not look as
    if keyboard focus is permanently pinned to the button.  Keep the checked
    border neutral and reserve the blue focus role for real focus states.
    """
    p = QtFusionPalette
    with dpg.theme() as theme:
        with dpg.theme_component(dpg.mvImageButton):
            base = p.HIGHLIGHT_SOFT if checked else (255, 255, 255, 0)
            dpg.add_theme_color(dpg.mvThemeCol_Button, base)
            dpg.add_theme_color(dpg.mvThemeCol_ButtonHovered, p.BUTTON_HOVER)
            dpg.add_theme_color(dpg.mvThemeCol_ButtonActive, p.BUTTON_ACTIVE)
            dpg.add_theme_color(dpg.mvThemeCol_Border, p.BORDER if checked else (0, 0, 0, 0))
            dpg.add_theme_style(dpg.mvStyleVar_FrameBorderSize, 1 if checked else 0)
            dpg.add_theme_style(dpg.mvStyleVar_FrameRounding, QtFusionMetrics.FRAME_ROUNDING)
            dpg.add_theme_style(dpg.mvStyleVar_FramePadding, 5, 6)
    return theme


def browser_inline_action_theme():
    """QFileDialog-like action strip used while entering a new folder name."""
    p = QtFusionPalette
    with dpg.theme() as theme:
        with dpg.theme_component(dpg.mvChildWindow):
            dpg.add_theme_color(dpg.mvThemeCol_ChildBg, p.WINDOW_ALT)
            dpg.add_theme_color(dpg.mvThemeCol_Border, p.BORDER_LIGHT)
            dpg.add_theme_style(dpg.mvStyleVar_WindowPadding, 4, 3)
            dpg.add_theme_style(dpg.mvStyleVar_ItemSpacing, 4, 2)
            dpg.add_theme_style(dpg.mvStyleVar_ChildBorderSize, 0)
            dpg.add_theme_style(dpg.mvStyleVar_ChildRounding, 0)
    return theme


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
    path = FOLDER_SELECTOR_ICON_DIR / filename
    if not path.is_file():
        return None
    size = max(1, int(size))
    tag = "folder_selector_generated_{}_{}_{}px".format(
        normalized, "disabled" if disabled else "normal", size)
    if dpg.does_item_exist(tag):
        return tag
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
            # Rev 1.1.6 masters are already drawn with a lighter optical
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
    """Use the generated high-resolution list/details toolbar artwork."""
    key = "list" if str(mode or "details").strip().lower() == "list" else "details"
    return (_generated_folder_selector_icon(key, size=20)
            or _crisp_toolbar_icon(key)
            or navigation_texture("List" if key == "list" else "Details"))


def browser_details_theme():
    """QHeaderView-like table chrome; row selection stays owned by QtListView."""
    p = QtFusionPalette
    with dpg.theme() as theme:
        with dpg.theme_component(dpg.mvTable):
            dpg.add_theme_color(dpg.mvThemeCol_TableHeaderBg, p.TOOLBAR)
            dpg.add_theme_color(dpg.mvThemeCol_Header, p.TOOLBAR)
            dpg.add_theme_color(dpg.mvThemeCol_HeaderHovered, p.HEADER_HOVER)
            dpg.add_theme_color(dpg.mvThemeCol_HeaderActive, p.HEADER_PRESSED)
            dpg.add_theme_color(dpg.mvThemeCol_TableBorderStrong, p.BORDER_LIGHT)
            dpg.add_theme_color(dpg.mvThemeCol_TableBorderLight, p.BORDER_LIGHT)
            dpg.add_theme_color(dpg.mvThemeCol_TableRowBg, p.BASE)
            dpg.add_theme_color(dpg.mvThemeCol_TableRowBgAlt, p.BASE)
            dpg.add_theme_style(dpg.mvStyleVar_CellPadding, 5, 1)
            add_dpg_scroller_style(dpg, track=p.WINDOW_ALT)
        with dpg.theme_component(dpg.mvButton):
            dpg.add_theme_color(dpg.mvThemeCol_Button, p.TOOLBAR)
            dpg.add_theme_color(dpg.mvThemeCol_ButtonHovered, p.HEADER_HOVER)
            dpg.add_theme_color(dpg.mvThemeCol_ButtonActive, p.HEADER_PRESSED)
            dpg.add_theme_color(dpg.mvThemeCol_Text, p.TEXT)
            dpg.add_theme_color(dpg.mvThemeCol_Border, p.BORDER_LIGHT)
            dpg.add_theme_style(dpg.mvStyleVar_FrameBorderSize, 0)
            dpg.add_theme_style(dpg.mvStyleVar_FrameRounding, 0)
            dpg.add_theme_style(dpg.mvStyleVar_FramePadding, 6, 3)
            if hasattr(dpg, "mvStyleVar_ButtonTextAlign"):
                dpg.add_theme_style(dpg.mvStyleVar_ButtonTextAlign, 0.0, 0.5)
    return theme



def browser_empty_state_theme():
    """Muted QFileDialog/QAbstractItemView empty-state surface."""
    p = QtFusionPalette
    with dpg.theme() as theme:
        with dpg.theme_component(dpg.mvChildWindow):
            dpg.add_theme_color(dpg.mvThemeCol_ChildBg, p.BASE)
            dpg.add_theme_color(dpg.mvThemeCol_Border, (0, 0, 0, 0))
            dpg.add_theme_style(dpg.mvStyleVar_WindowPadding, 8, 8)
            dpg.add_theme_style(dpg.mvStyleVar_ItemSpacing, 4, 4)
            dpg.add_theme_style(dpg.mvStyleVar_ChildBorderSize, 0)
            dpg.add_theme_style(dpg.mvStyleVar_ChildRounding, 0)
        with dpg.theme_component(dpg.mvText):
            dpg.add_theme_color(dpg.mvThemeCol_Text, p.TEXT_MUTED)
    return theme


def browser_status_text_theme(*, error=False):
    """QDialogButtonBox status text: muted normally, danger colour on errors."""
    p = QtFusionPalette
    with dpg.theme() as theme:
        with dpg.theme_component(dpg.mvText):
            dpg.add_theme_color(dpg.mvThemeCol_Text, p.DANGER if error else p.TEXT_MUTED)
    return theme


def browser_footer_theme():
    """Compact QFileDialog/QDialogButtonBox footer surface."""
    p = QtFusionPalette
    with dpg.theme() as theme:
        with dpg.theme_component(dpg.mvChildWindow):
            dpg.add_theme_color(dpg.mvThemeCol_ChildBg, p.WINDOW)
            dpg.add_theme_color(dpg.mvThemeCol_Border, (0, 0, 0, 0))
            dpg.add_theme_style(dpg.mvStyleVar_WindowPadding, 12, 8)
            dpg.add_theme_style(dpg.mvStyleVar_ItemSpacing, 6, 2)
            dpg.add_theme_style(dpg.mvStyleVar_ChildBorderSize, 0)
            dpg.add_theme_style(dpg.mvStyleVar_ChildRounding, 0)
    return theme


def browser_sidebar_section_text_theme():
    """QTreeView top-level branch label styling."""
    p = QtFusionPalette
    with dpg.theme() as theme:
        with dpg.theme_component(dpg.mvText):
            dpg.add_theme_color(dpg.mvThemeCol_Text, p.TEXT)
    return theme

def browser_divider_theme():
    with dpg.theme() as theme:
        with dpg.theme_component(dpg.mvChildWindow):
            dpg.add_theme_color(dpg.mvThemeCol_ChildBg, QtFusionPalette.BORDER_LIGHT)
            dpg.add_theme_color(dpg.mvThemeCol_Border, (0, 0, 0, 0))
            dpg.add_theme_style(dpg.mvStyleVar_WindowPadding, 0, 0)
            dpg.add_theme_style(dpg.mvStyleVar_ChildBorderSize, 0)
            dpg.add_theme_style(dpg.mvStyleVar_ChildRounding, 0)
    return theme


def browser_selection_bar_theme():
    p = QtFusionPalette
    with dpg.theme() as theme:
        with dpg.theme_component(dpg.mvChildWindow):
            dpg.add_theme_color(dpg.mvThemeCol_ChildBg, p.WINDOW)
            dpg.add_theme_color(dpg.mvThemeCol_Border, (0, 0, 0, 0))
            dpg.add_theme_style(dpg.mvStyleVar_WindowPadding, 4, 4)
            dpg.add_theme_style(dpg.mvStyleVar_ItemSpacing, 4, 2)
            dpg.add_theme_style(dpg.mvStyleVar_ChildBorderSize, 0)
            dpg.add_theme_style(dpg.mvStyleVar_ChildRounding, 0)
    return theme


def browser_separator_theme():
    p = QtFusionPalette
    with dpg.theme() as theme:
        with dpg.theme_component(dpg.mvSeparator):
            dpg.add_theme_color(dpg.mvThemeCol_Separator, p.BORDER_LIGHT)
            dpg.add_theme_color(dpg.mvThemeCol_SeparatorHovered, p.BORDER_LIGHT)
            dpg.add_theme_color(dpg.mvThemeCol_SeparatorActive, p.BORDER_LIGHT)
    return theme



def _navigation_texture(name, disabled=False):
    """Build one cached Qt-like toolbar glyph texture."""
    key = str(name or "").strip().lower().replace(" ", "_")
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
    with dpg.theme() as theme:
        for item_type, enabled in ((kind, state) for kind in (dpg.mvButton, dpg.mvImageButton)
                                   for state in (True, False)):
            with dpg.theme_component(item_type, enabled_state=enabled):
                dpg.add_theme_color(dpg.mvThemeCol_Button, (255, 255, 255, 0))
                dpg.add_theme_color(dpg.mvThemeCol_ButtonHovered, p.BUTTON_HOVER)
                dpg.add_theme_color(dpg.mvThemeCol_ButtonActive, p.BUTTON_ACTIVE)
                dpg.add_theme_color(dpg.mvThemeCol_Text, p.TEXT if enabled else p.TEXT_DISABLED)
                dpg.add_theme_color(dpg.mvThemeCol_TextDisabled, p.TEXT_DISABLED)
                dpg.add_theme_color(dpg.mvThemeCol_Border, (0, 0, 0, 0))
                dpg.add_theme_style(dpg.mvStyleVar_FrameBorderSize, 0)
                dpg.add_theme_style(dpg.mvStyleVar_FrameRounding, QtFusionMetrics.FRAME_ROUNDING)
                dpg.add_theme_style(dpg.mvStyleVar_FramePadding, 5, 6)
    return theme


def folder_item_texture(size=16):
    """Generated folder icon rasterized exactly for its final UI slot."""
    size = max(1, int(size))
    generated = _generated_folder_selector_icon("folder", size=size)
    if generated:
        return generated
    tag = "native_browser_folder_item_{}_aa".format(size)
    if dpg.does_item_exist(tag):
        return tag
    scale = 4
    canvas = max(16, size) * scale
    image = Image.new("RGBA", (canvas, canvas), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    k = canvas / 16.0
    outline = (183, 128, 25, 255)
    folder = (245, 184, 61, 255)
    folder_hi = (255, 204, 91, 255)
    shadow = (214, 157, 45, 255)
    draw.rounded_rectangle((2*k, 5*k, 14*k, 13*k), radius=1*k,
                           fill=folder, outline=outline, width=max(1, int(round(k))))
    draw.polygon(((2*k, 5*k), (2*k, 3*k), (7*k, 3*k),
                  (9*k, 5*k)), fill=folder_hi)
    draw.line((2*k, 5*k, 14*k, 5*k), fill=outline, width=max(1, int(round(k))))
    draw.line((3*k, 9*k, 13*k, 9*k), fill=shadow, width=max(1, int(round(k))))
    prepared = _resize_rgba_for_toolbar(image, size, monochrome=False)
    return WindowsIconRegistry._add_native_texture(prepared, tag)


def new_folder_texture():
    """Use the generated high-resolution new-folder glyph for the browser toolbar."""
    return (_generated_folder_selector_icon("new_folder", size=20)
            or _crisp_toolbar_icon("new_folder")
            or folder_item_texture())


def navigation_button(parent, name, callback, font, theme):
    # Use a generated monochrome glyph rather than a font codepoint.  Qt-like
    # toolbar icons should keep the same geometry across DPI/font changes.
    button = dpg.add_image_button(
        navigation_texture(name), parent=parent, width=20, height=20,
        callback=lambda *_args: callback())
    dpg.bind_item_theme(button, theme)
    add_styled_tooltip(button, name)
    return button
