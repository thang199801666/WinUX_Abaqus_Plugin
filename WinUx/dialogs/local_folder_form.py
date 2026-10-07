from __future__ import annotations

import os
import threading
import time
from datetime import datetime
from pathlib import Path

import dearpygui.dearpygui as dpg

from .qt_dialog import QtDialog
from .folder_browser_address import FolderAddressBar
from ..widgets import QtListItem, QtListView
from ..widgets.menu import ImGuiMenu
from ..widgets.item_views import qt_item_text_theme
from ..components.qt_style import QtFusionPalette
from ..components.tooltip import add_styled_tooltip
from ..components.shared_scroller import dpg_window_rect
from ..models.filesystem import FileSystemModel
from ..platform.windows_icons import WindowsIconRegistry
from ..platform.folder_browser_places import quick_access_places, drive_stock_id
from .folder_browser_style import (
    METRICS, browser_surface_theme, browser_dialog_body_theme,
    browser_layout_theme, browser_toolbar_theme, browser_workspace_theme,
    browser_field_shell_theme, browser_icon_slot_theme, browser_embedded_editor_theme,
    browser_sidebar_theme, browser_sidebar_row_theme, browser_sidebar_item_text_theme,
    browser_row_cell_theme,
    browser_sidebar_item_container_theme, browser_sidebar_header_theme,
    browser_list_viewport_theme,
    create_branch_indicator, paint_branch_indicator,
    browser_details_theme, browser_divider_theme, browser_selection_bar_theme,
    browser_empty_state_theme, browser_status_text_theme, browser_footer_theme,
    browser_sidebar_section_text_theme,
    browser_separator_theme, browser_toolbar_divider_theme, create_toolbar_divider,
    browser_tool_button_theme,
    browser_inline_icon_button_theme,
    navigation_button, navigation_button_theme,
    new_folder_texture, folder_item_texture, view_mode_texture, navigation_texture, navigation_disabled_texture,
    address_location_texture,
)


class FolderListView(QtListView):
    """Keep shared selection/keyboard behavior with compact folder-icon rows."""

    def __init__(self, *args, on_sort=None, **kwargs):
        self.details = {}
        self.icons = {}
        self.detail_texts = {}
        self._row_index = {}
        self.sort_column, self.sort_ascending = 0, True
        self.empty_text = "This folder is empty."
        self.details_mode = True
        self.on_sort = on_sort
        self._last_click_key = None
        self._last_click_at = 0.0
        self._double_click_interval = self._system_double_click_interval()
        super().__init__(*args, **kwargs)

    @staticmethod
    def _system_double_click_interval():
        if os.name == "nt":
            try:
                import ctypes
                return max(0.20, min(0.80, ctypes.windll.user32.GetDoubleClickTime() / 1000.0))
            except Exception:
                pass
        return 0.50

    def _clicked(self, sender, value, key):
        # Dear PyGui's native double-click flag is not reliable on every
        # Windows/DPG build when callbacks are manually pumped by a floating
        # dialog process.  Keep the shared QtListView behavior, then provide a
        # QFileDialog-style second-click fallback for the same folder row.
        try:
            native_double = bool(dpg.is_mouse_button_double_clicked(dpg.mvMouseButton_Left))
        except Exception:
            native_double = False
        now = time.monotonic()
        repeated = (
            key == self._last_click_key
            and 0.0 <= now - self._last_click_at <= self._double_click_interval
        )
        super()._clicked(sender, value, key)
        if native_double:
            self._last_click_key = None
            self._last_click_at = 0.0
            return
        if repeated:
            self._last_click_key = None
            self._last_click_at = 0.0
            self.doubleClicked.emit(key)
            self.activated.emit(key)
            return
        self._last_click_key = key
        self._last_click_at = now

    def setItems(self, items):
        self.detail_texts.clear()
        self._row_index.clear()
        super().setItems(items)
        for tag in self.items.values():
            # Selectable uses zero for fill-available width; unlike a
            # child window, negative width is a literal invisible extent.
            dpg.configure_item(tag, width=0, height=METRICS.row_height)
        self.icons.clear()
        self.table = dpg.add_table(
            parent=self.tag, header_row=self.details_mode, width=-1,
            policy=dpg.mvTable_SizingStretchProp, sortable=self.details_mode,
            callback=self._sorted, freeze_rows=1 if self.details_mode else 0,
            borders_innerH=False, borders_innerV=False,
            borders_outerH=False, borders_outerV=False, pad_outerX=False,
            row_background=True)
        dpg.bind_item_theme(self.table, browser_details_theme())
        name_column = dpg.add_table_column(parent=self.table, label="Name", width_stretch=True,
                             init_width_or_weight=1.0, default_sort=self.sort_column == 0,
                             prefer_sort_ascending=self.sort_ascending,
                             prefer_sort_descending=not self.sort_ascending)
        self.detail_columns = ()
        self._column_keys = {name_column: 0}
        if self.details_mode:
            date_column = dpg.add_table_column(parent=self.table, label="Date modified", width_fixed=True,
                                 init_width_or_weight=145, default_sort=self.sort_column == 1,
                                 prefer_sort_ascending=self.sort_ascending,
                                 prefer_sort_descending=not self.sort_ascending)
            type_column = dpg.add_table_column(parent=self.table, label="Type", width_fixed=True,
                                 init_width_or_weight=90, no_sort=True)
            self.detail_columns = (date_column, type_column)
            self._column_keys[date_column] = 1
        for row_index, item in enumerate(self._values):
            tag = self.items[item.key]
            row = dpg.add_table_row(parent=self.table)
            self._row_index[item.key] = row_index
            # Keep one compact ImGui line for the whole Name cell.  The
            # selectable supplies selection/current behavior; the Shell icon
            # sits on the same line so Dear ImGui owns the baseline instead of
            # nested child windows adding a second padding stack.
            name = dpg.add_group(parent=row, horizontal=True, horizontal_spacing=4)
            icon_slot = dpg.add_drawlist(
                parent=name, width=18, height=METRICS.row_height)
            texture = folder_item_texture()
            self.icons[item.key] = dpg.draw_image(
                texture, parent=icon_slot,
                pmin=(1, max(0, (METRICS.row_height - 16) // 2)),
                pmax=(17, max(0, (METRICS.row_height - 16) // 2) + 16),
                uv_min=(0, 0), uv_max=(1, 1))
            dpg.move_item(tag, parent=name)
            dpg.configure_item(
                tag, label=item.text, width=0, height=METRICS.row_height,
                span_columns=True)
            if self.details_mode:
                modified = self.details.get(item.key, 0)
                date = datetime.fromtimestamp(modified).strftime("%m/%d/%Y %H:%M") if modified else ""
                date_text = dpg.add_text(date, parent=row)
                type_text = dpg.add_text("Folder", parent=row)
                self.detail_texts[item.key] = (date_text, type_text)
        if not self._values and self.empty_text != "This folder is empty.":
            self._add_empty_state()
        # The first selectable owns the full-row selection background, while
        # the Date/Type cells are separate mvText items. Keep their display
        # role synchronized with the QAbstractItemView selection/current state.
        self._sync_selection_visuals()
        return self

    def _sync_selection_visuals(self):
        super()._sync_selection_visuals()
        enabled_by_key = {value.key: bool(value.enabled) for value in self._values}
        active = bool(getattr(self, "_has_focus", False))
        # QTreeView/QFileDialog selects the complete visual row, not only the
        # Name-cell primitive.  DearPyGui exposes a table-row highlight that
        # lets us mirror that behavior across Name/Date modified/Type.
        if getattr(self, "table", None):
            for key, row_index in tuple(self._row_index.items()):
                try:
                    if key in self.selected:
                        color = (
                            QtFusionPalette.SELECTION_ACTIVE if active
                            else QtFusionPalette.SELECTION_INACTIVE
                        )
                        self.backend.highlight_table_row(self.table, row_index, color)
                    else:
                        self.backend.unhighlight_table_row(self.table, row_index)
                except Exception:
                    pass
        for key, cells in tuple(self.detail_texts.items()):
            theme = qt_item_text_theme(
                self.backend,
                selected=key in self.selected,
                disabled=not enabled_by_key.get(key, True),
                active=active,
            )
            for cell in cells:
                try:
                    self.backend.bind_item_theme(cell, theme)
                except Exception:
                    pass

    def _sorted(self, _sender, specs, _user_data):
        # DPG sort specs contain column item IDs, not positional indices.
        if specs and self.on_sort:
            self.on_sort([(self._column_keys[column], direction)
                          for column, direction in specs if column in self._column_keys])

    def _add_empty_state(self):
        """Render a quiet QFileDialog-style message below the details header."""
        state = dpg.add_child_window(
            parent=self.tag, width=-1, height=84, border=False,
            no_scrollbar=True, no_scroll_with_mouse=True)
        dpg.bind_item_theme(state, browser_empty_state_theme())
        dpg.add_spacer(parent=state, height=18)
        with dpg.table(parent=state, header_row=False, width=-1,
                       policy=dpg.mvTable_SizingStretchProp, pad_outerX=False) as layout:
            dpg.bind_item_theme(layout, browser_layout_theme(cell_padding=(0, 0)))
            dpg.add_table_column(width_stretch=True)
            dpg.add_table_column(width_fixed=True, init_width_or_weight=280)
            dpg.add_table_column(width_stretch=True)
            with dpg.table_row():
                dpg.add_spacer(width=1)
                with dpg.group(horizontal=False, horizontal_spacing=0):
                    dpg.add_text(self.empty_text)
                    if self.empty_text == "Loading...":
                        dpg.add_text("Reading folders in this location...")
                    elif self.empty_text.startswith("No folders match"):
                        dpg.add_text("Try a different search term.")
                dpg.add_spacer(width=1)


class LocalFolderDialog(QtDialog):
    """Dear ImGui/Dear PyGui local-folder browser.

    This replaces the historical external native folder-picker helper. Directory I/O
    is performed on a small worker thread owned by the dialog process while all
    widgets and selection state stay on the Dear PyGui UI thread.
    """

    def __init__(self, view, initial, on_result):
        self.on_result = on_result
        self._finished = False
        self._generation = 0
        self._current_path = self._normalize_initial(initial)
        self._entries = {}
        self._back_paths, self._forward_paths = [], []
        self._listing = []
        self._folder_mtimes = {}
        self._sort_column, self._sort_ascending = 0, True
        self._place_items, self.place_buttons = {}, {}
        self._pending_place_path = None
        self._place_navigation_scheduled = False
        self._creating_folder = False
        self._select_after_load = None
        self._rename_after_load = None
        self._rename_path = None
        self._rename_editor = None
        self._rename_source = None
        self._folder_context_menu = None
        self._folder_menu_action_pending = False
        super().__init__(view, "Open Folder", 840, 540)
        dpg.configure_item(self.tag, on_close=lambda *_args: self._close_from_native())
        self.preferred_size = (840, 540)
        dpg.configure_item(self.content, no_scrollbar=True, no_scroll_with_mouse=True)
        dpg.bind_item_theme(self.content, browser_dialog_body_theme())
        # Toolbar icons are generated geometry/textures; avoid font-dependent glyph metrics.
        self._navigation_font = None
        self._navigation_theme = navigation_button_theme()
        self.location_toolbar = dpg.add_child_window(
            parent=self.content, width=-1, height=METRICS.toolbar_height, border=False,
            no_scrollbar=True, no_scroll_with_mouse=True)
        dpg.bind_item_theme(self.location_toolbar, browser_toolbar_theme())
        with dpg.table(parent=self.location_toolbar, header_row=False, width=-1,
                       policy=dpg.mvTable_SizingStretchProp, pad_outerX=False) as location:
            dpg.bind_item_theme(location, browser_layout_theme(cell_padding=(2, 0)))
            dpg.add_table_column(width_fixed=True, init_width_or_weight=90)
            dpg.add_table_column(width_stretch=True)
            dpg.add_table_column(width_fixed=True, init_width_or_weight=190)
            dpg.add_table_column(width_fixed=True, init_width_or_weight=9)
            dpg.add_table_column(width_fixed=True, init_width_or_weight=30)
            dpg.add_table_column(width_fixed=True, init_width_or_weight=30)
            dpg.add_table_column(width_fixed=True, init_width_or_weight=30)
            with dpg.table_row() as location_row:
                with dpg.group(parent=location_row, horizontal=True, horizontal_spacing=1) as nav:
                    self.back_button = self._nav_button(nav, "Back", self._go_back)
                    self.forward_button = self._nav_button(nav, "Forward", self._go_forward)
                    self.up_button = self._nav_button(nav, "Up", self._go_up)
                with dpg.table(parent=location_row, header_row=False, width=-1,
                               policy=dpg.mvTable_SizingStretchProp, pad_outerX=False) as address_layout:
                    dpg.bind_item_theme(address_layout, browser_layout_theme(cell_padding=(1, 0)))
                    dpg.add_table_column(width_stretch=True)
                    dpg.add_table_column(width_fixed=True, init_width_or_weight=28)
                    with dpg.table_row() as address_row:
                        self.address = FolderAddressBar(self, address_row)
                        self.address_icon = self.address.icon
                        self.path_edit = self.address.editor
                        self.breadcrumbs = self.address.breadcrumbs
                        self._nav_button(address_row, "Refresh", self._refresh)
                self.search_shell = dpg.add_child_window(
                    parent=location_row, width=-1, height=METRICS.location_height, border=True,
                    no_scrollbar=True, no_scroll_with_mouse=True)
                self._search_normal_theme = browser_field_shell_theme()
                self._search_focus_theme = browser_field_shell_theme(focused=True)
                self._search_clear_theme = browser_inline_icon_button_theme()
                dpg.bind_item_theme(self.search_shell, self._search_normal_theme)
                with dpg.table(parent=self.search_shell, header_row=False, width=-1,
                               policy=dpg.mvTable_SizingStretchProp, pad_outerX=False) as search_layout:
                    dpg.bind_item_theme(search_layout, browser_layout_theme(cell_padding=(1, 0)))
                    dpg.add_table_column(width_fixed=True, init_width_or_weight=21)
                    dpg.add_table_column(width_stretch=True)
                    dpg.add_table_column(width_fixed=True, init_width_or_weight=20)
                    with dpg.table_row() as search_row:
                        search_icon_slot = dpg.add_child_window(
                            parent=search_row, width=21, height=METRICS.location_height - 2,
                            border=False, no_scrollbar=True, no_scroll_with_mouse=True)
                        dpg.bind_item_theme(search_icon_slot, browser_icon_slot_theme())
                        dpg.add_image(
                            navigation_texture("search"), parent=search_icon_slot, width=20, height=20,
                            pos=(2, max(0, (METRICS.location_height - 18) // 2)))
                        self.filter_edit = self.line_edit(
                            "", parent=search_row, width=-1, hint="Search this folder",
                            callback=lambda *_args: self._search_changed())
                        dpg.bind_item_theme(self.filter_edit, browser_embedded_editor_theme())
                        clear_slot = dpg.add_child_window(
                            parent=search_row, width=20, height=METRICS.location_height - 2,
                            border=False, no_scrollbar=True, no_scroll_with_mouse=True)
                        dpg.bind_item_theme(clear_slot, browser_icon_slot_theme())
                        self.clear_search_button = dpg.add_image_button(
                            navigation_texture("clear"), parent=clear_slot, width=12, height=12,
                            pos=(2, 5), show=False, callback=lambda *_args: self._clear_search())
                        dpg.bind_item_theme(self.clear_search_button, self._search_clear_theme)
                        add_styled_tooltip(self.clear_search_button, "Clear search")
                        self._bind_search_focus()
                tool_divider = create_toolbar_divider(location_row)
                self.new_folder_button = dpg.add_image_button(
                    new_folder_texture(), parent=location_row, width=20, height=20,
                    callback=lambda *_args: self._show_new_folder())
                dpg.bind_item_theme(self.new_folder_button, self._navigation_theme)
                add_styled_tooltip(self.new_folder_button, "New folder (Ctrl+Shift+N)")
                self.details_view_button = dpg.add_image_button(
                    view_mode_texture("details"), parent=location_row, width=20, height=20,
                    callback=lambda *_args: self._change_view("Details"))
                self.list_view_button = dpg.add_image_button(
                    view_mode_texture("list"), parent=location_row, width=20, height=20,
                    callback=lambda *_args: self._change_view("List"))
                self._details_tool_theme = browser_tool_button_theme(checked=True)
                self._list_tool_theme = browser_tool_button_theme(checked=False)
                dpg.bind_item_theme(self.details_view_button, self._details_tool_theme)
                dpg.bind_item_theme(self.list_view_button, self._list_tool_theme)
                add_styled_tooltip(self.details_view_button, "Details view")
                add_styled_tooltip(self.list_view_button, "List view")
                # Compatibility alias for code that treated the old combo as the view control.
                self.view_mode = self.details_view_button
        toolbar_separator = dpg.add_separator(parent=self.content)
        dpg.bind_item_theme(toolbar_separator, browser_separator_theme())
        self.workspace = dpg.add_child_window(
            parent=self.content, width=-1, height=-METRICS.selection_height, border=True,
            no_scrollbar=True, no_scroll_with_mouse=True)
        dpg.bind_item_theme(self.workspace, browser_workspace_theme())
        with dpg.group(parent=self.workspace, horizontal=True, horizontal_spacing=0):
            self.places = dpg.add_child_window(
                width=METRICS.sidebar_width, height=-1, border=False, no_scrollbar=False)
            dpg.bind_item_theme(self.places, browser_sidebar_theme())
            self.quick_group = self._place_section("Quick access")
            for label, path in quick_access_places():
                self._add_place(label, path, WindowsIconRegistry.get_icon(is_dir=True),
                                parent=self.quick_group)
            dpg.add_spacer(parent=self.places, height=METRICS.sidebar_section_gap)
            self.drive_group = self._place_section("This PC", WindowsIconRegistry.get_stock_icon(94))
            for drive in self._drives():
                self._add_place(drive, drive, WindowsIconRegistry.get_stock_icon(drive_stock_id(drive)),
                                is_drive=True, parent=self.drive_group)
            divider = dpg.add_child_window(
                width=METRICS.divider_width, height=-1, border=False,
                no_scrollbar=True, no_scroll_with_mouse=True)
            dpg.bind_item_theme(divider, browser_divider_theme())
            self.folder_region = dpg.add_child_window(
                width=-1, height=-1, border=False, no_scrollbar=True)
        dpg.bind_item_theme(self.folder_region, browser_surface_theme())
        self.listbox = self.own_widget(
            FolderListView(
                self.folder_region,
                [],
                width=-1,
                height=-1,
                multiple=False,
                after=self.view.after,
                backend=dpg,
                on_sort=self._sort_entries,
            )
        )
        dpg.configure_item(self.listbox.tag, border=False)
        dpg.bind_item_theme(self.listbox.tag, browser_list_viewport_theme())
        self.listbox.doubleClicked.connect(self._enter_key)
        self.listbox.currentChanged.connect(self._selection_changed)
        self.active_table = self.listbox
        selection_separator = dpg.add_separator(parent=self.content)
        dpg.bind_item_theme(selection_separator, browser_separator_theme())
        self.selection_bar = dpg.add_child_window(
            parent=self.content, width=-1, height=METRICS.selection_height, border=False,
            no_scrollbar=True, no_scroll_with_mouse=True)
        dpg.bind_item_theme(self.selection_bar, browser_selection_bar_theme())
        with dpg.table(parent=self.selection_bar, header_row=False, width=-1,
                       policy=dpg.mvTable_SizingStretchProp, pad_outerX=False) as selection_layout:
            dpg.bind_item_theme(selection_layout, browser_layout_theme(cell_padding=(3, 0)))
            dpg.add_table_column(width_fixed=True, init_width_or_weight=54)
            dpg.add_table_column(width_stretch=True)
            with dpg.table_row() as selection_row:
                dpg.add_text("Folder:", parent=selection_row)
                self.folder_edit = self.line_edit(
                    self._current_path, parent=selection_row, width=-1, on_enter=True,
                    callback=lambda *_args: self._select_folder())
        self.enter_editors.update((self.path_edit, self.folder_edit, self.filter_edit))
        self.status = self.status_text("")
        self._status_normal_theme = browser_status_text_theme(error=False)
        self._status_error_theme = browser_status_text_theme(error=True)
        dpg.bind_item_theme(self.status, self._status_normal_theme)
        self.button_box([
            ("Select Folder", self._select_folder, "primary", True),
            ("Cancel", lambda: self.finish(None), "secondary", False),
        ], status_item=self.status, status_left_padding=6)
        if self.footer_shell is not None:
            dpg.bind_item_theme(self.footer_shell, browser_footer_theme())
        dpg.configure_item(self.tag, min_size=(700, 430))
        self._create_folder_context_menu()
        self._update_navigation()
        self._refresh()
        self._load_place_icons()
        self._install_browser_keys()
        self.view.after(0, self._apply_layout)

    def _nav_button(self, parent, name, callback):
        return navigation_button(parent, name, callback,
                                 self._navigation_font, self._navigation_theme)

    def _refresh_search_focus(self):
        if not hasattr(self, "filter_edit") or not dpg.does_item_exist(self.filter_edit):
            return
        try:
            focused = bool(dpg.is_item_focused(self.filter_edit) or dpg.is_item_active(self.filter_edit))
            dpg.bind_item_theme(
                self.search_shell,
                self._search_focus_theme if focused else self._search_normal_theme,
            )
        except Exception:
            pass

    def _bind_search_focus(self):
        """Mirror QLineEdit focus-frame behavior without changing input routing."""
        try:
            with dpg.item_handler_registry() as registry:
                if hasattr(dpg, "add_item_focus_handler"):
                    dpg.add_item_focus_handler(callback=lambda *_args: self._refresh_search_focus())
                if hasattr(dpg, "add_item_activated_handler"):
                    dpg.add_item_activated_handler(callback=lambda *_args: self._refresh_search_focus())
                if hasattr(dpg, "add_item_deactivated_handler"):
                    dpg.add_item_deactivated_handler(callback=lambda *_args: self._refresh_search_focus())
            dpg.bind_item_handler_registry(self.filter_edit, registry)
            self._control_handler_registries.append(registry)
        except Exception:
            # Older DPG builds can omit one of these item handlers.  The field
            # remains fully functional with the normal frame theme.
            pass

    def _search_changed(self):
        query = str(dpg.get_value(self.filter_edit) or "")
        if hasattr(self, "clear_search_button") and dpg.does_item_exist(self.clear_search_button):
            dpg.configure_item(self.clear_search_button, show=bool(query))
        self._filter_entries()

    def _clear_search(self):
        dpg.set_value(self.filter_edit, "")
        if hasattr(self, "clear_search_button") and dpg.does_item_exist(self.clear_search_button):
            dpg.configure_item(self.clear_search_button, show=False)
        self._filter_entries()
        self.focus_editor(self.filter_edit)
        self.view.after(0, self._refresh_search_focus)

    def _place_section(self, title, texture=None):
        # QTreeView-style branch row. The arrow is geometry, not a font glyph,
        # so compact rows/DPI changes cannot clip it.
        header = dpg.add_child_window(
            parent=self.places, width=-1, height=METRICS.sidebar_row_height,
            border=False, no_scrollbar=True, no_scroll_with_mouse=True)
        dpg.bind_item_theme(header, browser_sidebar_item_container_theme())
        toggle_row = dpg.add_selectable(
            parent=header, label="", width=0, height=METRICS.sidebar_row_height,
            default_value=False, pos=(0, 0))
        dpg.bind_item_theme(toggle_row, browser_sidebar_header_theme())
        indicator = create_branch_indicator(header, expanded=True, pos=(1, 0))
        text_x = 24
        overlay = dpg.add_drawlist(
            METRICS.sidebar_width, METRICS.sidebar_row_height, parent=header, pos=(0, 0))
        if texture:
            dpg.draw_image(
                texture, (22, 4), (38, 20), parent=overlay)
            text_x = 43
        section_label = dpg.draw_text(
            (text_x, self._sidebar_draw_text_y(title)), title, parent=overlay,
            color=QtFusionPalette.TEXT, size=13)
        body = dpg.add_group(parent=self.places, indent=18)

        def change(_sender=None, _app_data=None, _user_data=None):
            shown = not dpg.get_item_configuration(body)["show"]
            dpg.configure_item(body, show=shown)
            dpg.set_value(toggle_row, False)
            paint_branch_indicator(indicator, shown)

        dpg.configure_item(toggle_row, callback=change)
        try:
            with dpg.item_handler_registry() as registry:
                dpg.add_item_clicked_handler(
                    button=dpg.mvMouseButton_Left, callback=change)
            dpg.bind_item_handler_registry(indicator, registry)
            self._control_handler_registries.append(registry)
        except Exception:
            pass
        return body

    @staticmethod
    def _text_width(text):
        try:
            measured = dpg.get_text_size(str(text or ""))
            if isinstance(measured, (tuple, list)) and measured:
                return float(measured[0] or 0.0)
        except Exception:
            pass
        return float(len(str(text or "")) * 7)

    def _sidebar_draw_text_y(self, sample="Ag"):
        """Pixel-position draw_text so sidebar labels share the icon coordinate system."""
        try:
            measured = dpg.get_text_size(str(sample or "Ag"))
            if isinstance(measured, (tuple, list)) and len(measured) >= 2:
                height = float(measured[1] or 0.0)
                if height > 0:
                    return max(0, int(round((METRICS.sidebar_row_height - height) * 0.5)))
        except Exception:
            pass
        return 4

    def _elide_sidebar_label(self, text, max_width=None):
        """QFontMetrics::elidedText-like right elision for the Places tree."""
        text = str(text or "")
        budget = float(max_width or (METRICS.sidebar_width - 46))
        if self._text_width(text) <= budget:
            return text
        ellipsis = "…"
        ellipsis_width = self._text_width(ellipsis)
        if budget <= ellipsis_width:
            return ellipsis
        lo, hi = 0, len(text)
        while lo < hi:
            mid = (lo + hi + 1) // 2
            candidate = text[:mid] + ellipsis
            if self._text_width(candidate) <= budget:
                lo = mid
            else:
                hi = mid - 1
        return text[:lo] + ellipsis

    def _set_place_label(self, label_item, text):
        dpg.configure_item(label_item, text=self._elide_sidebar_label(text))

    def _add_place(self, label, path, texture, is_drive=False, parent=None):
        # Full-row background selection/hover, matching QTreeView's visual
        # behavior instead of starting the highlight after the icon.
        row = dpg.add_child_window(
            parent=parent or self.places, width=-1, height=METRICS.sidebar_row_height,
            border=False, no_scrollbar=True, no_scroll_with_mouse=True)
        dpg.bind_item_theme(row, browser_sidebar_item_container_theme())
        button = dpg.add_selectable(
            parent=row, label="", width=0, height=METRICS.sidebar_row_height,
            pos=(0, 0), user_data=str(path),
            callback=self._place_clicked)
        dpg.bind_item_theme(button, browser_sidebar_row_theme())
        overlay = dpg.add_drawlist(
            METRICS.sidebar_width, METRICS.sidebar_row_height, parent=row, pos=(0, 0))
        image = dpg.draw_image(
            texture, (5, 4), (21, 20), parent=overlay)
        display_label = self._elide_sidebar_label(label)
        label_item = dpg.draw_text(
            (28, self._sidebar_draw_text_y(display_label)), display_label,
            parent=overlay, color=QtFusionPalette.TEXT, size=13)
        add_styled_tooltip(row, str(path))
        self.place_buttons[label] = button
        self._place_items[str(path)] = (image, button, label_item, is_drive)


    def _place_clicked(self, _sender, _app_data, path):
        """Queue sidebar navigation after the current pointer transaction.

        Dear ImGui keeps the clicked Selectable active until the current frame
        commits. Rebuilding the browser synchronously from this callback can
        leave the active item/mouse ownership stale, which makes the whole
        floating dialog appear unclickable after switching drives.
        """
        if not path:
            return
        self._pending_place_path = str(path)
        if self._place_navigation_scheduled:
            return
        self._place_navigation_scheduled = True
        # A small non-zero delay guarantees the current DPG frame is rendered
        # before navigation mutates selection, address bar and the folder view.
        self.view.after(1, self._commit_place_navigation)

    def _commit_place_navigation(self):
        self._place_navigation_scheduled = False
        path = self._pending_place_path
        self._pending_place_path = None
        if not path or not self.winfo_exists():
            return
        self._navigate(path)

    def _change_view(self, value):
        details = value == "Details"
        if self.listbox.details_mode == details:
            return
        self.listbox.details_mode = details
        if hasattr(self, "details_view_button"):
            self._details_tool_theme = browser_tool_button_theme(checked=details)
            self._list_tool_theme = browser_tool_button_theme(checked=not details)
            dpg.bind_item_theme(self.details_view_button, self._details_tool_theme)
            dpg.bind_item_theme(self.list_view_button, self._list_tool_theme)
        self._filter_entries()

    def _apply_layout(self):
        super()._apply_layout()
        if hasattr(self, "address") and self.winfo_exists():
            self.address.refresh()

    def _install_browser_keys(self):
        with dpg.handler_registry() as registry:
            for key in (dpg.mvKey_L, dpg.mvKey_F, dpg.mvKey_F4, dpg.mvKey_F5, dpg.mvKey_N,
                        dpg.mvKey_Left, dpg.mvKey_Right, dpg.mvKey_Up,
                        dpg.mvKey_Return, dpg.mvKey_Back, dpg.mvKey_F2):
                dpg.add_key_press_handler(key=key, callback=self._browser_key)
            dpg.add_mouse_click_handler(
                button=dpg.mvMouseButton_Left, callback=self._rename_outside_click)
            dpg.add_mouse_click_handler(
                button=dpg.mvMouseButton_Left, callback=self._folder_menu_outside_click)
            dpg.add_mouse_release_handler(
                button=dpg.mvMouseButton_Right, callback=self._folder_right_release)
        self._control_handler_registries.append(registry)

    def _browser_key(self, _sender, key, _user_data=None):
        if not self.winfo_exists() or not dpg.is_item_shown(self.tag):
            return
        if self._folder_menu_is_open() or self._folder_menu_action_pending:
            return
        if self._rename_path is not None or self._rename_after_load is not None:
            if key == dpg.mvKey_Return and self._rename_path is not None:
                self.view.after(1, self._commit_folder_rename, self._rename_path,
                                dpg.get_value(self._rename_editor))
            return
        ctrl = dpg.is_key_down(dpg.mvKey_LControl) or dpg.is_key_down(dpg.mvKey_RControl)
        shift = dpg.is_key_down(dpg.mvKey_LShift) or dpg.is_key_down(dpg.mvKey_RShift)
        alt = dpg.is_key_down(dpg.mvKey_LAlt) or dpg.is_key_down(dpg.mvKey_RAlt)
        if (key == dpg.mvKey_L and ctrl) or key == dpg.mvKey_F4:
            self.address.begin_edit()
        elif key == dpg.mvKey_F and ctrl:
            self.focus_editor(self.filter_edit)
            self.view.after(0, self._refresh_search_focus)
        elif key == dpg.mvKey_F5:
            self._refresh()
        elif key == dpg.mvKey_N and ctrl and shift:
            self._show_new_folder()
        elif key == dpg.mvKey_F2 and self._list_keyboard_active():
            self._request_folder_rename(self.listbox.currentData())
        elif key == dpg.mvKey_Left and alt:
            self._go_back()
        elif key == dpg.mvKey_Right and alt:
            self._go_forward()
        elif key == dpg.mvKey_Up and alt:
            self._go_up()
        elif key == dpg.mvKey_Return and self._list_keyboard_active():
            path = self.listbox.currentData()
            if path:
                self._enter_key(path)
        elif key == dpg.mvKey_Back and self._list_keyboard_active():
            if self._back_paths:
                self._go_back()
            else:
                self._go_up()

    def _list_keyboard_active(self):
        # Text editors own Return/Backspace.  Once a folder row has focus, the
        # view behaves like QFileDialog/QListView: arrows move current, Return
        # opens it, and Backspace navigates back/up.
        if self._rename_path is not None:
            return False
        for item in (self.path_edit, self.folder_edit, self.filter_edit):
            try:
                if dpg.does_item_exist(item) and (dpg.is_item_focused(item) or dpg.is_item_active(item)):
                    return False
            except Exception:
                pass
        return bool(self.listbox.hasFocus() and self.listbox.currentData())

    def _set_status(self, message, *, error=False):
        """Update footer text with the same information/error hierarchy as Qt."""
        if not hasattr(self, "status") or not dpg.does_item_exist(self.status):
            return
        dpg.set_value(self.status, str(message or ""))
        theme = self._status_error_theme if error else self._status_normal_theme
        dpg.bind_item_theme(self.status, theme)

    def _show_new_folder(self):
        if self._creating_folder:
            return
        if self._rename_path is not None and not self._commit_folder_rename():
            return
        self.address.end_edit()
        self._create_folder()

    def _hide_new_folder(self):
        self._rename_after_load = None
        self._rename_path = None
        editor, self._rename_editor = self._rename_editor, None
        source, self._rename_source = self._rename_source, None
        if editor is not None:
            self.enter_editors.discard(editor)
            if dpg.does_item_exist(editor):
                dpg.delete_item(editor)
        if source is not None and dpg.does_item_exist(source):
            dpg.show_item(source)

    def _create_folder(self):
        if self._creating_folder:
            return
        parent = self._current_path
        self._creating_folder = True
        dpg.configure_item(self.new_folder_button, enabled=False)
        self._set_status("Creating folder...")

        def worker():
            path, error = None, None
            try:
                path = str(FileSystemModel.new_folder(Path(parent)))
            except (OSError, ValueError) as exc:
                error = str(exc)
            self.view.after(0, self._folder_created, parent, path, error)
        threading.Thread(target=worker, name="winux-folder-create", daemon=True).start()

    def _folder_created(self, parent, path, error):
        if not self.winfo_exists():
            return
        self._creating_folder = False
        dpg.configure_item(self.new_folder_button, enabled=True)
        if parent != self._current_path:
            return
        if error:
            self._set_status("Could not create folder: {}".format(error), error=True)
            return
        self._hide_new_folder()
        dpg.set_value(self.filter_edit, "")
        if hasattr(self, "clear_search_button") and dpg.does_item_exist(self.clear_search_button):
            dpg.configure_item(self.clear_search_button, show=False)
        self._select_after_load = path
        self._rename_after_load = path
        self._refresh()

    def _begin_folder_rename(self, path):
        if (not self.winfo_exists() or self._rename_after_load != path
                or path not in self.listbox.items):
            return
        tag = self.listbox.items[path]
        _, y = dpg.get_item_rect_min(tag)
        bounds = dpg_window_rect(dpg, self.listbox.tag, clip=True)
        if bounds is None:
            self.view.after(20, self._begin_folder_rename, path)
            return
        _, top, right, bottom = bounds
        # Scroll the new row into view before positioning the shared editor.
        header = METRICS.header_height if self.listbox.details_mode else 0
        if y < top + header or y + METRICS.row_height > bottom:
            offset = y - top - header if y < top + header else y + METRICS.row_height - bottom
            dpg.set_y_scroll(self.listbox.tag, max(0, dpg.get_y_scroll(self.listbox.tag) + offset))
            self.view.after(20, self._begin_folder_rename, path)
            return
        name = os.path.basename(path)
        # A span-columns Selectable reports the full row rect, including the
        # icon. Use the icon slot to place the editor exactly over the label.
        icon_slot = dpg.get_item_parent(self.listbox.icons[path])
        x = dpg.get_item_rect_min(icon_slot)[0] + dpg.get_item_rect_size(icon_slot)[0] + 4
        if self.listbox.details_mode:
            date_text = self.listbox.detail_texts[path][0]
            right = min(right, dpg.get_item_rect_min(date_text)[0] - 6)
        max_width = max(24, int(right - x - 4))
        editor_width = min(max_width, max(120, int(dpg.get_text_size(name)[0] + 12)))
        self._rename_editor = dpg.add_input_text(
            parent=dpg.get_item_parent(tag), before=tag,
            default_value=name, width=editor_width, height=METRICS.row_height,
            auto_select_all=True, on_enter=True,
            callback=lambda _sender, value, _user_data=None: self.view.after(
                1, self._commit_folder_rename, path, value))
        if not hasattr(self, "_rename_editor_theme"):
            with dpg.theme() as self._rename_editor_theme:
                with dpg.theme_component(dpg.mvInputText):
                    dpg.add_theme_color(dpg.mvThemeCol_FrameBg, QtFusionPalette.BASE)
                    dpg.add_theme_color(dpg.mvThemeCol_Text, QtFusionPalette.TEXT)
                    dpg.add_theme_color(dpg.mvThemeCol_Border, (72, 72, 72, 255))
                    dpg.add_theme_style(dpg.mvStyleVar_FrameBorderSize, 1)
                    dpg.add_theme_style(dpg.mvStyleVar_FrameRounding, 0)
                    dpg.add_theme_style(dpg.mvStyleVar_FramePadding, 2, 1)
        dpg.bind_item_theme(self._rename_editor, self._rename_editor_theme)
        self._rename_source = tag
        dpg.hide_item(tag)
        self._rename_after_load = None
        self._rename_path = path
        self.enter_editors.add(self._rename_editor)
        self._focus_folder_rename(path, retries=4)

    def _focus_folder_rename(self, path, retries=4):
        if self.winfo_exists() and self._rename_path == path:
            if dpg.is_item_active(self._rename_editor):
                return
            # The toolbar/address field may still own its child window's focus.
            # Focus the list window before requesting its newly rendered input.
            dpg.focus_item(self.listbox.tag)
            dpg.focus_item(self._rename_editor)
            if retries:
                self.view.after(16, self._focus_folder_rename, path, retries - 1)

    def _rename_outside_click(self, *_args):
        if self._rename_path is None:
            return
        if not dpg.is_item_hovered(self._rename_editor):
            self.view.after(1, self._commit_folder_rename, self._rename_path,
                            dpg.get_value(self._rename_editor))

    def _commit_folder_rename(self, path=None, new_name=None):
        current = self._rename_path
        if current is None or (path is not None and current != path):
            return False
        if new_name is None:
            new_name = dpg.get_value(self._rename_editor)
        try:
            renamed = str(FileSystemModel().rename(
                Path(current), str(new_name or "")))
        except (OSError, ValueError) as exc:
            self._set_status("Could not rename folder: {}".format(exc), error=True)
            self.view.after(20, self._focus_folder_rename, current)
            return False
        self._hide_new_folder()
        self._select_after_load = renamed
        dpg.set_value(self.folder_edit, renamed)
        self._refresh()
        return True

    def invoke_default(self):
        # Enter belongs to the inline editor, not Select Folder.
        if (self._rename_path is None and self._rename_after_load is None
                and not self._folder_menu_is_open() and not self._folder_menu_action_pending):
            super().invoke_default()

    def _create_folder_context_menu(self):
        menu = ImGuiMenu([
            {"label": "Open", "action": "open"},
            {"label": "Select folder", "action": "select"},
            {"label": "Rename", "action": "rename", "shortcut": "F2"},
            {"label": "Copy path", "action": "copy_path"},
            {"label": "Open in File Explorer", "action": "explorer"},
            {"label": "---"},
            {"label": "New folder", "action": "new_folder", "shortcut": "Ctrl+Shift+N"},
            {"label": "Refresh", "action": "refresh", "shortcut": "F5"},
        ], backend=dpg, after=self.view.after, parent_window=self.tag)
        menu.triggered.connect(self._folder_menu_triggered)
        menu.aboutToShow.connect(lambda *_args: setattr(self, "active_table", None))
        menu.aboutToHide.connect(lambda *_args: setattr(self, "active_table", self.listbox))
        self._folder_context_menu = menu

    def _folder_menu_is_open(self):
        menu = self._folder_context_menu
        return bool(menu is not None and dpg.does_item_exist(menu.tag)
                    and dpg.is_item_shown(menu.tag))

    def _folder_menu_outside_click(self, *_args):
        if not self._folder_menu_is_open():
            return
        bounds = dpg_window_rect(dpg, self._folder_context_menu.tag, clip=True)
        if bounds is None:
            return
        x, y = dpg.get_mouse_pos(local=False)
        left, top, right, bottom = bounds
        if not (left <= x < right and top <= y < bottom):
            self.view.after(1, self._folder_context_menu.hide)

    def _folder_right_release(self, *_args):
        if not self.winfo_exists() or not dpg.is_item_shown(self.tag):
            return
        position = tuple(dpg.get_mouse_pos(local=False))
        bounds = dpg_window_rect(dpg, self.listbox.tag, clip=True)
        if bounds is None:
            return
        mx, my = position
        left, top, right, bottom = bounds
        if not (left <= mx < right and top <= my < bottom):
            return
        if self._folder_menu_is_open():
            return
        path = None
        for key, tag in self.listbox.items.items():
            if not dpg.is_item_shown(tag):
                continue
            _, y = dpg.get_item_rect_min(tag)
            _, height = dpg.get_item_rect_size(tag)
            if y <= my < y + height:
                path = key
                break
        # Freeze the target while processing this release. Popup mutation and
        # selection run after the physical gesture has finished.
        self.view.after(1, self._show_folder_context_menu,
                        path, position, self._current_path)

    def _show_folder_context_menu(self, path, position, parent):
        if not self.winfo_exists() or parent != self._current_path:
            return
        if self._rename_path is not None and not self._commit_folder_rename():
            return
        if path is not None and path not in self.listbox.items:
            return
        if path is not None:
            self.listbox.setCurrentKey(path, select=True)
        menu = self._folder_context_menu
        for action in ("open", "select", "rename", "copy_path", "explorer"):
            menu.setActionEnabled(action, path is not None)
        menu.setActionEnabled("new_folder", not self._creating_folder)
        menu.popup(position, context=(parent, path))

    def _folder_menu_triggered(self, action, context):
        # Menu signals may originate from a physical mouse-down callback. Hide
        # first and defer operations until its popup input transaction ends.
        self._folder_menu_action_pending = True
        self._folder_context_menu.hide()
        self.view.after(1, self._run_folder_menu_action, action, context)

    def _run_folder_menu_action(self, action, context):
        self._folder_menu_action_pending = False
        if not self.winfo_exists() or not context:
            return
        parent, path = context
        if parent != self._current_path or (path is not None and path not in self._entries):
            return
        if action == "new_folder":
            self._show_new_folder()
        elif action == "refresh":
            self._refresh()
        elif path is not None:
            if action == "open":
                self._enter_key(path)
            elif action == "select":
                self.finish(path)
            elif action == "rename":
                self._request_folder_rename(path)
            elif action == "copy_path":
                dpg.set_clipboard_text(path)
            elif action == "explorer":
                try:
                    os.startfile(path)
                except OSError as exc:
                    self._set_status("Could not open folder: {}".format(exc), error=True)

    def _request_folder_rename(self, path):
        if path not in self.listbox.items:
            return
        self._hide_new_folder()
        self.listbox.setCurrentKey(path, select=True)
        self._rename_after_load = path
        self.view.after(1, self._begin_folder_rename, path)

    def _load_place_icons(self):
        def worker():
            for path, items in tuple(self._place_items.items()):
                if self._finished:
                    return
                image, name = WindowsIconRegistry.read_path_info(path)
                self.view.after(0, self._apply_place_icon, path, items, image, name)
        threading.Thread(target=worker, name="winux-folder-shell-icons", daemon=True).start()

    def _apply_place_icon(self, path, items, image, name):
        if not self.winfo_exists():
            return
        image_tag, button, label_item, is_drive = items
        if image is not None:
            texture = WindowsIconRegistry.get_path_icon(path, image)
            if image_tag:
                dpg.configure_item(image_tag, texture_tag=texture)
            list_icon = self.listbox.icons.get(path)
            if list_icon:
                dpg.configure_item(list_icon, texture_tag=texture)
            if os.path.normcase(path) == os.path.normcase(self._current_path):
                dpg.configure_item(
                    self.address_icon,
                    texture_tag=address_location_texture(self._current_path, size=18),
                )
        if is_drive and name:
            self._set_place_label(label_item, name)

    def _update_breadcrumbs(self):
        self.address.end_edit()

    def _sort_entries(self, specs):
        if not specs:
            return
        column, direction = specs[0]
        ascending = direction > 0
        if (column, ascending) != (self._sort_column, self._sort_ascending):
            self._sort_column, self._sort_ascending = column, ascending
            self._filter_entries()

    @staticmethod
    def _drives():
        if os.name == "nt":
            import ctypes
            mask = ctypes.windll.kernel32.GetLogicalDrives()
            return [chr(65 + index) + ":\\" for index in range(26) if mask & (1 << index)]
        return [os.path.abspath(os.sep)]

    def _update_navigation(self):
        back_enabled = bool(self._back_paths)
        forward_enabled = bool(self._forward_paths)
        up_enabled = os.path.dirname(self._current_path) != self._current_path
        dpg.configure_item(
            self.back_button, enabled=back_enabled,
            texture_tag=navigation_texture("Back") if back_enabled else navigation_disabled_texture("Back"))
        dpg.configure_item(
            self.forward_button, enabled=forward_enabled,
            texture_tag=navigation_texture("Forward") if forward_enabled else navigation_disabled_texture("Forward"))
        dpg.configure_item(
            self.up_button, enabled=up_enabled,
            texture_tag=navigation_texture("Up") if up_enabled else navigation_disabled_texture("Up"))
        current = os.path.normcase(self._current_path)
        parents = [path for path in self._place_items
                   if current == os.path.normcase(path) or
                   current.startswith(os.path.normcase(path).rstrip("\\/") + os.sep)]
        active = max(parents, key=len) if parents else None
        for path, (_, button, label_item, _) in self._place_items.items():
            selected = path == active
            dpg.set_value(button, selected)
            try:
                dpg.configure_item(
                    label_item,
                    color=(QtFusionPalette.SELECTION_TEXT if selected else QtFusionPalette.TEXT),
                )
            except Exception:
                pass

    def _navigate(self, value, remember=True):
        value = os.path.expandvars(os.path.expanduser(str(value).strip()))
        candidate = os.path.abspath(os.path.join(self._current_path, value))
        if not os.path.isdir(candidate):
            self._set_status("Folder does not exist: {}".format(candidate), error=True)
            self._update_navigation()
            return False
        if remember and candidate != self._current_path:
            self._back_paths.append(self._current_path)
            self._forward_paths.clear()
        self._current_path = candidate
        self._folder_context_menu.hide()
        self._select_after_load = None
        self._hide_new_folder()
        dpg.set_value(self.path_edit, candidate)
        dpg.configure_item(self.address_icon, texture_tag=address_location_texture(candidate, size=18))
        self._update_breadcrumbs()
        dpg.set_value(self.folder_edit, candidate)
        dpg.set_value(self.filter_edit, "")
        if hasattr(self, "clear_search_button") and dpg.does_item_exist(self.clear_search_button):
            dpg.configure_item(self.clear_search_button, show=False)
        self._entries.clear()
        self._listing = []
        self.listbox.empty_text = "Loading..."
        self.listbox.setItems([])
        self._update_navigation()
        self._refresh()
        return True

    def _go_back(self):
        if self._back_paths:
            previous = self._current_path
            if self._navigate(self._back_paths[-1], remember=False):
                self._back_paths.pop()
                self._forward_paths.append(previous)
                self._update_navigation()

    def _go_forward(self):
        if self._forward_paths:
            previous = self._current_path
            if self._navigate(self._forward_paths[-1], remember=False):
                self._forward_paths.pop()
                self._back_paths.append(previous)
                self._update_navigation()

    def _selection_changed(self, key):
        if hasattr(self, "folder_edit"):
            dpg.set_value(self.folder_edit, self._entries.get(key, self._current_path))

    def _filter_entries(self):
        if self._rename_path is not None:
            self._hide_new_folder()
        query = str(dpg.get_value(self.filter_edit) or "").casefold().strip()
        entries = [item for item in self._listing if query in item[1].casefold()]
        entries.sort(key=lambda item: (
            (self._folder_mtimes.get(item[2], 0), item[0], item[1])
            if self._sort_column == 1 else (item[0], item[1])),
            reverse=not self._sort_ascending)
        self.listbox.details = self._folder_mtimes
        self.listbox.sort_column, self.listbox.sort_ascending = self._sort_column, self._sort_ascending
        self.listbox.empty_text = "No folders match your search." if query else "This folder is empty."
        self.listbox.setItems([QtListItem(path, name, path) for _, name, path in entries])
        # Path editors and list rows own Enter (navigate/activate); do not
        # also run the dialog default action for that same physical keypress.
        self.enter_editors = {self.path_edit, self.folder_edit, self.filter_edit,
                              *self.listbox.items.values()}
        count = len(entries)
        self._set_status("{} folder{}".format(count, "" if count == 1 else "s"))

    @staticmethod
    def _normalize_initial(initial):
        value = str(initial or os.getcwd())
        try:
            value = os.path.abspath(os.path.normpath(value))
        except Exception:
            value = os.getcwd()
        if not os.path.isdir(value):
            value = os.getcwd()
        return value

    def _navigate_typed(self):
        value = str(dpg.get_value(self.path_edit) or "").strip()
        if value:
            self._navigate(value)

    def _go_up(self):
        parent = os.path.dirname(self._current_path)
        if parent != self._current_path:
            self._navigate(parent)

    def _refresh(self):
        if not self.winfo_exists():
            return
        self._generation += 1
        generation = self._generation
        path = self._current_path
        self._set_status("Loading...")

        def worker():
            entries, error, modified = [], None, {}
            try:
                with os.scandir(path) as iterator:
                    for entry in iterator:
                        try:
                            if entry.is_dir(follow_symlinks=True):
                                entries.append((entry.name.casefold(), entry.name, entry.path))
                                try:
                                    modified[entry.path] = entry.stat(follow_symlinks=True).st_mtime
                                except OSError:
                                    modified[entry.path] = 0
                        except OSError:
                            continue
                entries.sort(key=lambda item: (item[0], item[1]))
            except (OSError, ValueError) as exc:
                error = str(exc)
            self.view.after(0, self._apply_entries, generation, path, entries, error, modified)

        threading.Thread(
            target=worker,
            name="winux-local-folder-list",
            daemon=True,
        ).start()

    def _apply_entries(self, generation, path, entries, error, modified=None):
        if not self.winfo_exists() or generation != self._generation:
            return
        if path != self._current_path:
            return
        if error:
            self._hide_new_folder()
            self._entries.clear()
            self._listing = []
            self.listbox.setItems([])
            self._set_status(error, error=True)
            return
        self._entries = {full_path: full_path for _, _, full_path in entries}
        self._folder_mtimes = modified or {}
        self._listing = entries
        self._filter_entries()
        if self._select_after_load in self.listbox.items:
            self.listbox.setCurrentKey(self._select_after_load, select=True)
        self._select_after_load = None
        if self._rename_after_load in self.listbox.items:
            self.view.after(20, self._begin_folder_rename, self._rename_after_load)

    def _enter_key(self, key):
        path = self._entries.get(key) or str(key or "")
        if path and os.path.isdir(path):
            self._navigate(path)

    def _select_folder(self):
        if self._rename_path is not None and not self._commit_folder_rename():
            return
        value = str(dpg.get_value(self.folder_edit) or "").strip()
        path = os.path.abspath(os.path.join(
            self._current_path, os.path.expandvars(os.path.expanduser(value))))
        if not os.path.isdir(path):
            self._set_status("Folder does not exist: {}".format(path), error=True)
            return
        self.finish(path)

    def finish(self, value):
        if self._finished:
            return
        self._finished = True
        self._hide_new_folder()
        self._folder_context_menu.delete()
        self._generation += 1
        try:
            if callable(self.on_result):
                self.on_result(value)
        finally:
            self.destroy()

    def destroy(self):
        self._hide_new_folder()
        if self._folder_context_menu is not None:
            self._folder_context_menu.delete()
        super().destroy()

    def _close_from_escape(self):
        if self._folder_menu_is_open():
            self._folder_context_menu.hide()
        elif self._rename_path is not None or self._rename_after_load is not None:
            self._hide_new_folder()
        elif self.address.editing:
            self.address.end_edit()
        else:
            self.finish(None)

    def _close_from_native(self):
        self.finish(None)
