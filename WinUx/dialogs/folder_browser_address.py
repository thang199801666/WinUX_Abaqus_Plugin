"""A single Windows-style address field that switches breadcrumbs/editor."""
from pathlib import Path
import dearpygui.dearpygui as dpg

from .folder_browser_style import GLYPHS, browser_surface_theme, browser_layout_theme
from ..components.tooltip import add_styled_tooltip
from ..platform.windows_icons import WindowsIconRegistry


class FolderAddressBar:
    def __init__(self, dialog, parent):
        self.dialog = dialog
        self.editing = False
        self._last_layout = None
        self.tag = dpg.add_child_window(
            parent=parent, width=-1, height=27, border=True,
            no_scrollbar=True, no_scroll_with_mouse=True)
        dpg.bind_item_theme(self.tag, browser_surface_theme(
            padding=(3, 1), cell_padding=(1, 0), spacing=(0, 0)))
        with dpg.table(parent=self.tag, header_row=False, width=-1,
                       policy=dpg.mvTable_SizingStretchProp, pad_outerX=False) as layout:
            dpg.bind_item_theme(layout, browser_layout_theme(cell_padding=(1, 0)))
            dpg.add_table_column(width_fixed=True, init_width_or_weight=20)
            dpg.add_table_column(width_stretch=True)
            dpg.add_table_column(width_fixed=True, init_width_or_weight=25)
            with dpg.table_row() as row:
                self.icon = dpg.add_image(
                    WindowsIconRegistry.get_stock_icon(4), parent=row, width=16, height=16)
                self.body = dpg.add_child_window(
                    parent=row, width=-1, height=24, border=False,
                    no_scrollbar=True, no_scroll_with_mouse=True)
                dpg.bind_item_theme(self.body, browser_surface_theme(
                    cell_padding=(1, 0), spacing=(0, 0)))
                self.breadcrumbs = dpg.add_group(parent=self.body, horizontal=True,
                                                horizontal_spacing=0)
                self.editor = dialog.line_edit(
                    dialog._current_path, parent=self.body, width=-1,
                    show=False, pos=(0, 0), on_enter=True, auto_select_all=True,
                    callback=lambda *_args: dialog._navigate_typed())
                self.edit_button = dialog._nav_button(row, "Edit address", self.begin_edit)
        self.refresh(force=True)

    def begin_edit(self):
        self.editing = True
        dpg.hide_item(self.breadcrumbs)
        dpg.show_item(self.editor)
        dpg.set_value(self.editor, self.dialog._current_path)
        self.dialog.focus_editor(self.editor)

    def end_edit(self):
        self.editing = False
        dpg.hide_item(self.editor)
        dpg.show_item(self.breadcrumbs)
        dpg.set_value(self.editor, self.dialog._current_path)
        self.refresh(force=True)

    @staticmethod
    def _width(text):
        measured = dpg.get_text_size(text)
        return float(measured[0]) if measured else len(text) * 7.0

    def _fit(self, text, available):
        if self._width(text) <= available:
            return text
        while text and self._width(text + "...") > available:
            text = text[:-1]
        return text + "..." if text else "..."

    def refresh(self, force=False):
        if not dpg.does_item_exist(self.tag):
            return
        available = dpg.get_item_rect_size(self.body)[0]
        if available < 40:
            available = max(90, dpg.get_item_width(self.dialog.tag) - 425)
        stamp = (self.dialog._current_path, int(available))
        if not force and stamp == self._last_layout:
            return
        self._last_layout = stamp
        dpg.delete_item(self.breadcrumbs, children_only=True)
        path = Path(self.dialog._current_path)
        chain = list(reversed(path.parents)) + [path]
        # Keep the current folder readable, folding ancestors from the left.
        visible = [chain[-1]]
        used = min(self._width(path.name or path.anchor) + 14, available * 0.6)
        for ancestor in reversed(chain[:-1]):
            width = self._width(ancestor.name or ancestor.anchor) + 28
            if used + width + 26 > available:
                break
            visible.insert(0, ancestor)
            used += width
        if len(visible) < len(chain):
            button = dpg.add_button(
                parent=self.breadcrumbs, label="...", width=24, height=24,
                callback=lambda *_args: self.begin_edit())
            dpg.bind_item_theme(button, self.dialog._navigation_theme)
            add_styled_tooltip(button, self.dialog._current_path)
        budget = max(24, available - (26 if len(visible) < len(chain) else 0))
        for index, ancestor in enumerate(visible):
            if index or len(visible) < len(chain):
                separator = dpg.add_text(
                    chr(GLYPHS["Chevron"]) if self.dialog._navigation_font else ">",
                    parent=self.breadcrumbs, color=(145, 145, 145, 255))
                if self.dialog._navigation_font:
                    dpg.bind_item_font(separator, self.dialog._navigation_font)
                budget -= 16
            full_label = ancestor.name or ancestor.anchor
            remaining = len(visible) - index - 1
            width = max(24, min(self._width(full_label) + 14,
                                budget - remaining * 40))
            label = self._fit(full_label, max(8, width - 12))
            button = dpg.add_button(
                parent=self.breadcrumbs, label=label, width=int(width), height=24,
                callback=lambda _s, _a, _u, p=str(ancestor): self.dialog._navigate(p))
            dpg.bind_item_theme(button, self.dialog._navigation_theme)
            add_styled_tooltip(button, str(ancestor))
            budget -= width
        # This transparent remainder is the address field's blank-click target.
        if budget > 4:
            button = dpg.add_button(parent=self.breadcrumbs, label="", width=int(budget),
                                    height=24, callback=lambda *_args: self.begin_edit())
            dpg.bind_item_theme(button, self.dialog._navigation_theme)
