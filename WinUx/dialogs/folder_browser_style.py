"""Scoped Windows file-picker chrome and system navigation glyphs."""
import os
from pathlib import Path
import dearpygui.dearpygui as dpg
from PIL import Image, ImageDraw

from ..components.tooltip import add_styled_tooltip
from ..platform.windows_icons import WindowsIconRegistry


GLYPHS = {"Back": 0xE72B, "Forward": 0xE72A, "Up": 0xE74A,
          "Refresh": 0xE72C, "Go": 0xE72A, "Search": 0xE721,
          "Edit address": 0xE70D, "New folder": 0xE8F4,
          "Home": 0xE80F, "Chevron": 0xE76C,
          "Expanded": 0xE70D, "Collapsed": 0xE76C}


def load_navigation_font():
    path = Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts" / "segmdl2.ttf"
    if not path.is_file():
        return None
    with dpg.font_registry():
        font = dpg.add_font(str(path), 16)
    return font


def browser_surface_theme(background=(255, 255, 255, 255), padding=(0, 0),
                          cell_padding=(7, 1), spacing=(6, 2)):
    with dpg.theme() as theme:
        with dpg.theme_component(dpg.mvAll):
            dpg.add_theme_color(dpg.mvThemeCol_ChildBg, background)
            dpg.add_theme_color(dpg.mvThemeCol_Border, (224, 224, 224, 255))
            dpg.add_theme_color(dpg.mvThemeCol_TableHeaderBg, (248, 248, 248, 255))
            dpg.add_theme_color(dpg.mvThemeCol_TableBorderLight, (235, 235, 235, 255))
            dpg.add_theme_style(dpg.mvStyleVar_WindowPadding, *padding)
            dpg.add_theme_style(dpg.mvStyleVar_ItemSpacing, *spacing)
            dpg.add_theme_style(dpg.mvStyleVar_ChildRounding, 0)
            dpg.add_theme_style(dpg.mvStyleVar_CellPadding, *cell_padding)
    return theme



def browser_layout_theme(cell_padding=(2, 1)):
    """Chrome-free layout table metrics for the folder browser toolbar.

    Layout tables should not inherit the generous details-view cell padding;
    they are the Dear ImGui equivalent of a compact QToolBar/QHBoxLayout.
    """
    with dpg.theme() as theme:
        with dpg.theme_component(dpg.mvTable):
            dpg.add_theme_style(dpg.mvStyleVar_CellPadding, *cell_padding)
            dpg.add_theme_color(dpg.mvThemeCol_TableBorderStrong, (235, 235, 235, 0))
            dpg.add_theme_color(dpg.mvThemeCol_TableBorderLight, (235, 235, 235, 0))
    return theme

def navigation_button_theme():
    with dpg.theme() as theme:
        for item_type, enabled in ((kind, state) for kind in (dpg.mvButton, dpg.mvImageButton)
                                   for state in (True, False)):
            with dpg.theme_component(item_type, enabled_state=enabled):
                dpg.add_theme_color(dpg.mvThemeCol_Button, (255, 255, 255, 0))
                dpg.add_theme_color(dpg.mvThemeCol_ButtonHovered, (230, 240, 250, 255))
                dpg.add_theme_color(dpg.mvThemeCol_ButtonActive, (207, 228, 249, 255))
                dpg.add_theme_color(dpg.mvThemeCol_Text,
                                    (65, 65, 65, 255) if enabled else (176, 176, 176, 255))
                dpg.add_theme_color(dpg.mvThemeCol_TextDisabled, (176, 176, 176, 255))
                dpg.add_theme_style(dpg.mvStyleVar_FrameBorderSize, 0)
                dpg.add_theme_style(dpg.mvStyleVar_FrameRounding, 1)
                dpg.add_theme_style(dpg.mvStyleVar_FramePadding, 4, 3)
    return theme


def new_folder_texture():
    """Use the actual Shell folder with the standard green create overlay."""
    tag = "native_browser_new_folder"
    if dpg.does_item_exist(tag):
        return tag
    source = WindowsIconRegistry.get_icon(is_dir=True)
    pixels = dpg.get_value(source)
    image = Image.frombytes("RGBA", (16, 16),
                            bytes(max(0, min(255, round(value * 255))) for value in pixels))
    draw = ImageDraw.Draw(image)
    for width, color in ((4, (255, 255, 255, 255)), (2, (0, 140, 60, 255))):
        draw.line((9, 12, 15, 12), fill=color, width=width)
        draw.line((12, 9, 12, 15), fill=color, width=width)
    return WindowsIconRegistry._add_texture(image, tag)


def navigation_button(parent, name, callback, font, theme):
    button = dpg.add_button(
        parent=parent, label=chr(GLYPHS[name]) if font else name,
        width=27 if font else 58, height=26, callback=lambda *_args: callback())
    dpg.bind_item_theme(button, theme)
    if font:
        dpg.bind_item_font(button, font)
    add_styled_tooltip(button, name)
    return button
