"""A single Windows-style address field that switches breadcrumbs/editor."""
from pathlib import Path
import dearpygui.dearpygui as dpg

from .folder_browser_style import (
    METRICS, browser_surface_theme, browser_layout_theme,
    browser_field_shell_theme, browser_icon_slot_theme, browser_embedded_editor_theme,
    browser_breadcrumb_button_theme, browser_breadcrumb_blank_theme,
    create_breadcrumb_chevron, address_location_texture,
)
from ..components.tooltip import add_styled_tooltip
from ..platform.windows_icons import WindowsIconRegistry


class FolderAddressBar:
    def __init__(self, dialog, parent):
        self.dialog = dialog
        self.editing = False
        self._last_layout = None
        self._last_valid_width = 0.0
        self._segment_theme = browser_breadcrumb_button_theme()
        self._blank_theme = browser_breadcrumb_blank_theme()
        self._normal_theme = browser_field_shell_theme(focused=False)
        self._focus_theme = browser_field_shell_theme(focused=True)
        self.tag = dpg.add_child_window(
            parent=parent, width=-1, height=METRICS.location_height, border=True,
            no_scrollbar=True, no_scroll_with_mouse=True)
        dpg.bind_item_theme(self.tag, self._normal_theme)
        with dpg.table(parent=self.tag, header_row=False, width=-1,
                       policy=dpg.mvTable_SizingStretchProp, pad_outerX=False) as layout:
            dpg.bind_item_theme(layout, browser_layout_theme(cell_padding=(1, 0)))
            dpg.add_table_column(width_fixed=True, init_width_or_weight=24)
            dpg.add_table_column(width_stretch=True)
            dpg.add_table_column(width_fixed=True, init_width_or_weight=28)
            with dpg.table_row() as row:
                icon_slot = dpg.add_child_window(
                    parent=row, width=22, height=METRICS.location_height - 2, border=False,
                    no_scrollbar=True, no_scroll_with_mouse=True)
                dpg.bind_item_theme(icon_slot, browser_icon_slot_theme())
                self.icon = dpg.add_image(
                    address_location_texture(dialog._current_path, size=18), parent=icon_slot, width=18, height=18,
                    pos=(2, max(0, (METRICS.location_height - 20) // 2)))
                self.body = dpg.add_child_window(
                    parent=row, width=-1, height=METRICS.location_height - 3, border=False,
                    no_scrollbar=True, no_scroll_with_mouse=True)
                dpg.bind_item_theme(self.body, browser_surface_theme(
                    cell_padding=(1, 0), spacing=(0, 0)))
                self.breadcrumbs = dpg.add_group(parent=self.body, horizontal=True,
                                                horizontal_spacing=0)
                self.editor = dialog.line_edit(
                    dialog._current_path, parent=self.body, width=-1,
                    show=False, pos=(0, 0), on_enter=True, auto_select_all=True,
                    callback=lambda *_args: dialog._navigate_typed())
                # The outer address field owns the frame; edit mode must not
                # draw a second QLineEdit rectangle inside it.
                dpg.bind_item_theme(self.editor, browser_embedded_editor_theme())
                self.edit_button = dialog._nav_button(row, "Edit address", self.begin_edit)
        self.refresh(force=True)

    def begin_edit(self):
        self.editing = True
        dpg.hide_item(self.breadcrumbs)
        dpg.show_item(self.editor)
        dpg.set_value(self.editor, self.dialog._current_path)
        dpg.bind_item_theme(self.tag, self._focus_theme)
        self.dialog.focus_editor(self.editor)

    def end_edit(self):
        self.editing = False
        dpg.hide_item(self.editor)
        dpg.show_item(self.breadcrumbs)
        dpg.set_value(self.editor, self.dialog._current_path)
        self.refresh(force=True)
        dpg.bind_item_theme(self.tag, self._normal_theme)

    @staticmethod
    def _width(text):
        try:
            measured = dpg.get_text_size(text)
        except Exception:
            measured = None
        if isinstance(measured, (tuple, list)) and len(measured) >= 1:
            try:
                width = float(measured[0] or 0.0)
                if width > 0:
                    return width
            except (TypeError, ValueError, IndexError, OverflowError):
                pass
        return len(text) * 7.0

    def _available_width(self):
        """Return address-body width without assuming the item has rendered.

        ``get_item_rect_size`` can legitimately return ``()`` before the first
        Dear ImGui frame, and can briefly do so while the folder browser is
        rebuilding its layout during navigation.  Never index that tuple until
        its shape has been validated.
        """
        available = 0.0
        try:
            rect = dpg.get_item_rect_size(self.body)
        except Exception:
            rect = None
        if isinstance(rect, (tuple, list)) and len(rect) >= 1:
            try:
                available = float(rect[0] or 0.0)
            except (TypeError, ValueError, IndexError, OverflowError):
                available = 0.0
        if available >= 40:
            self._last_valid_width = available
            return available
        if self._last_valid_width >= 40:
            return self._last_valid_width

        # First-frame fallback: the address field is stretch-sized, therefore
        # its configured width is often -1 until layout.  Derive a conservative
        # usable width from the dialog's preferred width instead of querying
        # unrendered geometry.
        preferred = getattr(self.dialog, "preferred_size", None)
        dialog_width = 0.0
        if isinstance(preferred, (tuple, list)) and len(preferred) >= 1:
            try:
                dialog_width = float(preferred[0] or 0.0)
            except (TypeError, ValueError, IndexError, OverflowError):
                dialog_width = 0.0
        if dialog_width <= 0:
            try:
                configured = dpg.get_item_width(self.dialog.tag)
                dialog_width = float(configured or 0.0)
            except Exception:
                dialog_width = 0.0
        available = max(180.0, dialog_width - 425.0) if dialog_width > 0 else 320.0
        return available

    def _fit(self, text, available):
        if self._width(text) <= available:
            return text
        while text and self._width(text + "...") > available:
            text = text[:-1]
        return text + "..." if text else "..."

    def refresh(self, force=False):
        if not dpg.does_item_exist(self.tag):
            return
        available = self._available_width()
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
                parent=self.breadcrumbs, label="...", width=24, height=METRICS.location_height - 3,
                callback=lambda *_args: self.begin_edit())
            dpg.bind_item_theme(button, self._segment_theme)
            add_styled_tooltip(button, self.dialog._current_path)
        budget = max(24, available - (26 if len(visible) < len(chain) else 0))
        for index, ancestor in enumerate(visible):
            if index or len(visible) < len(chain):
                create_breadcrumb_chevron(self.breadcrumbs)
                budget -= 11
            full_label = ancestor.name or ancestor.anchor
            remaining = len(visible) - index - 1
            width = max(24, min(self._width(full_label) + 14,
                                budget - remaining * 40))
            label = self._fit(full_label, max(8, width - 12))
            button = dpg.add_button(
                parent=self.breadcrumbs, label=label, width=int(width), height=METRICS.location_height - 3,
                user_data=str(ancestor),
                callback=lambda _s, _a, p: self.dialog._navigate(p))
            dpg.bind_item_theme(button, self._segment_theme)
            add_styled_tooltip(button, str(ancestor))
            budget -= width
        # This transparent remainder is the address field's blank-click target.
        if budget > 4:
            button = dpg.add_button(parent=self.breadcrumbs, label="", width=int(budget),
                                    height=METRICS.location_height - 3, callback=lambda *_args: self.begin_edit())
            dpg.bind_item_theme(button, self._blank_theme)
