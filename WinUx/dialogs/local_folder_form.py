from __future__ import annotations

import os
import threading
from datetime import datetime

import dearpygui.dearpygui as dpg

from .qt_dialog import QtDialog
from .folder_browser_address import FolderAddressBar
from ..widgets import QtListItem, QtListView
from ..widgets.item_views import qt_item_view_theme
from ..components.tooltip import add_styled_tooltip
from ..platform.windows_icons import WindowsIconRegistry
from ..platform.folder_browser_places import quick_access_places, drive_stock_id
from .folder_browser_style import (
    GLYPHS, browser_surface_theme, browser_layout_theme, load_navigation_font,
    navigation_button, navigation_button_theme, new_folder_texture,
)


class FolderListView(QtListView):
    """Keep shared selection/keyboard behavior with compact folder-icon rows."""

    def __init__(self, *args, on_sort=None, **kwargs):
        self.details = {}
        self.icons = {}
        self.sort_column, self.sort_ascending = 0, True
        self.empty_text = "This folder is empty."
        self.details_mode = True
        self.on_sort = on_sort
        super().__init__(*args, **kwargs)

    def setItems(self, items):
        super().setItems(items)
        for tag in self.items.values():
            # Selectable uses zero for fill-available width; unlike a
            # child window, negative width is a literal invisible extent.
            dpg.configure_item(tag, width=0, height=23)
        self.icons.clear()
        self.table = dpg.add_table(
            parent=self.tag, header_row=self.details_mode, width=-1,
            policy=dpg.mvTable_SizingStretchProp, sortable=self.details_mode,
            callback=self._sorted, freeze_rows=1 if self.details_mode else 0,
            borders_innerH=False, borders_innerV=True,
            borders_outerH=True, borders_outerV=True, pad_outerX=False,
            row_background=True)
        dpg.bind_item_theme(self.table, qt_item_view_theme(dpg))
        name_column = dpg.add_table_column(parent=self.table, label="Name", width_stretch=True,
                             init_width_or_weight=1.0, default_sort=self.sort_column == 0,
                             prefer_sort_ascending=self.sort_ascending,
                             prefer_sort_descending=not self.sort_ascending)
        self.detail_columns = ()
        self._column_keys = {name_column: 0}
        if self.details_mode:
            date_column = dpg.add_table_column(parent=self.table, label="Date modified", width_fixed=True,
                                 init_width_or_weight=135, default_sort=self.sort_column == 1,
                                 prefer_sort_ascending=self.sort_ascending,
                                 prefer_sort_descending=not self.sort_ascending)
            type_column = dpg.add_table_column(parent=self.table, label="Type", width_fixed=True,
                                 init_width_or_weight=80, no_sort=True)
            self.detail_columns = (date_column, type_column)
            self._column_keys[date_column] = 1
        for item in self._values:
            tag = self.items[item.key]
            row = dpg.add_table_row(parent=self.table)
            name = dpg.add_group(parent=row, horizontal=True, horizontal_spacing=5)
            texture = WindowsIconRegistry.get_path_icon(item.data)
            self.icons[item.key] = dpg.add_image(texture, parent=name, width=16, height=16)
            dpg.move_item(tag, parent=name)
            dpg.configure_item(tag, span_columns=True)
            if self.details_mode:
                modified = self.details.get(item.key, 0)
                date = datetime.fromtimestamp(modified).strftime("%m/%d/%Y %H:%M") if modified else ""
                dpg.add_text(date, parent=row)
                dpg.add_text("File folder", parent=row)
        if not self._values:
            dpg.add_text(self.empty_text, parent=self.tag, color=(110, 110, 110, 255))
        return self

    def _sorted(self, _sender, specs, _user_data):
        # DPG sort specs contain column item IDs, not positional indices.
        if specs and self.on_sort:
            self.on_sort([(self._column_keys[column], direction)
                          for column, direction in specs if column in self._column_keys])


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
        self._creating_folder = False
        self._select_after_load = None
        super().__init__(view, "Select Folder", 780, 490)
        dpg.configure_item(self.tag, on_close=lambda *_args: self._close_from_native())
        self.preferred_size = (780, 490)
        dpg.configure_item(self.content, no_scrollbar=True, no_scroll_with_mouse=True)
        dpg.bind_item_theme(self.content, browser_surface_theme(padding=(8, 6)))
        self._navigation_font = load_navigation_font()
        self._navigation_theme = navigation_button_theme()
        with dpg.table(parent=self.content, header_row=False, width=-1,
                       policy=dpg.mvTable_SizingStretchProp, pad_outerX=False) as location:
            dpg.bind_item_theme(location, browser_layout_theme())
            dpg.add_table_column(width_fixed=True, init_width_or_weight=96 if self._navigation_font else 186)
            dpg.add_table_column(width_stretch=True)
            dpg.add_table_column(width_fixed=True, init_width_or_weight=180)
            with dpg.table_row() as location_row:
                with dpg.group(parent=location_row, horizontal=True, horizontal_spacing=2) as nav:
                    self.back_button = self._nav_button(nav, "Back", self._go_back)
                    self.forward_button = self._nav_button(nav, "Forward", self._go_forward)
                    self.up_button = self._nav_button(nav, "Up", self._go_up)
                with dpg.table(parent=location_row, header_row=False, width=-1,
                               policy=dpg.mvTable_SizingStretchProp, pad_outerX=False) as address_layout:
                    dpg.bind_item_theme(address_layout, browser_layout_theme())
                    dpg.add_table_column(width_stretch=True)
                    dpg.add_table_column(width_fixed=True, init_width_or_weight=28)
                    with dpg.table_row() as address_row:
                        self.address = FolderAddressBar(self, address_row)
                        self.address_icon = self.address.icon
                        self.path_edit = self.address.editor
                        self.breadcrumbs = self.address.breadcrumbs
                        self._nav_button(address_row, "Refresh", self._refresh)
                with dpg.table(parent=location_row, header_row=False, width=-1,
                               policy=dpg.mvTable_SizingStretchProp, pad_outerX=False) as search_layout:
                    dpg.bind_item_theme(search_layout, browser_layout_theme())
                    dpg.add_table_column(width_fixed=True, init_width_or_weight=22)
                    dpg.add_table_column(width_stretch=True)
                    with dpg.table_row() as search_row:
                        if self._navigation_font:
                            icon = dpg.add_text(chr(GLYPHS["Search"]), parent=search_row)
                            dpg.bind_item_font(icon, self._navigation_font)
                        else:
                            dpg.add_text("Find", parent=search_row)
                        self.filter_edit = self.line_edit(
                            "", parent=search_row, hint="Search this folder",
                            callback=lambda *_args: self._filter_entries())

        with dpg.table(parent=self.content, header_row=False, width=-1,
                       policy=dpg.mvTable_SizingStretchProp, pad_outerX=False) as command_layout:
            dpg.bind_item_theme(command_layout, browser_layout_theme())
            dpg.add_table_column(width_stretch=True)
            dpg.add_table_column(width_fixed=True, init_width_or_weight=92)
            with dpg.table_row() as command_row:
                with dpg.group(parent=command_row, horizontal=True, horizontal_spacing=0) as new_actions:
                    icon = dpg.add_image_button(
                        new_folder_texture(), parent=new_actions, width=16, height=16,
                        callback=lambda *_args: self._show_new_folder())
                    dpg.bind_item_theme(icon, self._navigation_theme)
                    add_styled_tooltip(icon, "New folder (Ctrl+Shift+N)")
                    self.new_folder_button = self.action(
                        "New folder", self._show_new_folder, "secondary",
                        parent=new_actions, width=82, height=26)
                self.view_mode = self.combo(
                    ["Details", "List"], parent=command_row,
                    default_value="Details", width=-1,
                    callback=lambda _s, value, _u: self._change_view(value))
        with dpg.group(parent=self.content, horizontal=True, show=False) as self.new_folder_row:
            dpg.add_text("Name:")
            self.new_folder_edit = self.line_edit(
                "New folder", parent=self.new_folder_row, width=-155, on_enter=True, auto_select_all=True,
                callback=lambda *_args: self._create_folder())
            self.create_folder_button = self.action(
                "Create", self._create_folder, parent=self.new_folder_row, width=60)
            self.action("Cancel", self._hide_new_folder, parent=self.new_folder_row, width=60)
        dpg.add_separator(parent=self.content)

        self.workspace = dpg.add_child_window(
            parent=self.content, width=-1, height=-38, border=False,
            no_scrollbar=True, no_scroll_with_mouse=True)
        dpg.bind_item_theme(self.workspace, browser_surface_theme())
        with dpg.group(parent=self.workspace, horizontal=True, horizontal_spacing=5):
            self.places = dpg.add_child_window(
                width=164, height=-1, border=True, no_scrollbar=False)
            dpg.bind_item_theme(self.places, browser_surface_theme((250, 250, 250, 255), (7, 6)))
            self.quick_group = self._place_section("Quick access")
            for label, path in quick_access_places():
                self._add_place(label, path, WindowsIconRegistry.get_icon(is_dir=True),
                                parent=self.quick_group)
            dpg.add_spacer(parent=self.places, height=6)
            self.drive_group = self._place_section("This PC", WindowsIconRegistry.get_stock_icon(94))
            for drive in self._drives():
                self._add_place(drive, drive, WindowsIconRegistry.get_stock_icon(drive_stock_id(drive)),
                                is_drive=True, parent=self.drive_group)
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
        dpg.bind_item_theme(self.listbox.tag, browser_surface_theme())
        self.listbox.activated.connect(self._enter_key)
        self.listbox.currentChanged.connect(self._selection_changed)
        folder_form = self.form_layout(parent=self.content, label_width=52)
        self.folder_edit = self.form_layout_row(
            folder_form, "Folder",
            lambda parent: self.line_edit(
                self._current_path, parent=parent, on_enter=True,
                callback=lambda *_args: self._select_folder()),
        )
        self.enter_editors.update((self.path_edit, self.folder_edit, self.filter_edit, self.new_folder_edit))
        self.status = self.status_text("")
        self.button_box([
            ("Select Folder", self._select_folder, "primary", True),
            ("Cancel", lambda: self.finish(None), "secondary", False),
        ], status_item=self.status)
        dpg.configure_item(self.tag, min_size=(620, 400))
        self._update_navigation()
        self._refresh()
        self._load_place_icons()
        self._install_browser_keys()
        self.view.after(0, self._apply_layout)

    def _nav_button(self, parent, name, callback):
        return navigation_button(parent, name, callback,
                                 self._navigation_font, self._navigation_theme)

    def _place_section(self, title, texture=None):
        with dpg.group(parent=self.places, horizontal=True, horizontal_spacing=4) as header:
            toggle = dpg.add_button(parent=header, width=18, height=24,
                                    label=chr(GLYPHS["Expanded"]) if self._navigation_font else "v")
            dpg.bind_item_theme(toggle, self._navigation_theme)
            if self._navigation_font:
                dpg.bind_item_font(toggle, self._navigation_font)
            if texture:
                dpg.add_image(texture, parent=header, width=16, height=16)
            text = dpg.add_selectable(parent=header, label=title, height=22, width=0)
        body = dpg.add_group(parent=self.places, indent=14)

        def change(*_args):
            dpg.set_value(text, False)
            shown = not dpg.get_item_configuration(body)["show"]
            dpg.configure_item(body, show=shown)
            label = chr(GLYPHS["Expanded" if shown else "Collapsed"]) if self._navigation_font else ("v" if shown else ">")
            dpg.configure_item(toggle, label=label)
        dpg.configure_item(toggle, callback=change)
        dpg.configure_item(text, callback=change)
        return body

    def _add_place(self, label, path, texture, is_drive=False, parent=None):
        with dpg.group(parent=parent or self.places, horizontal=True, horizontal_spacing=6) as row:
            if label == "Home" and self._navigation_font:
                home = dpg.add_text(chr(GLYPHS["Home"]), parent=row, color=(0, 120, 215, 255))
                dpg.bind_item_font(home, self._navigation_font)
                image = None
            else:
                image = dpg.add_image(texture, parent=row, width=16, height=16)
            button = dpg.add_selectable(
                parent=row, label=label, width=0, height=22,
                callback=lambda _s, _a, _u, p=str(path): self._navigate(p))
        add_styled_tooltip(button, str(path))
        self.place_buttons[label] = button
        self._place_items[str(path)] = (image, button, is_drive)

    def _change_view(self, value):
        self.listbox.details_mode = value == "Details"
        self._filter_entries()

    def _apply_layout(self):
        super()._apply_layout()
        if hasattr(self, "address") and self.winfo_exists():
            self.address.refresh()

    def _install_browser_keys(self):
        with dpg.handler_registry() as registry:
            for key in (dpg.mvKey_L, dpg.mvKey_F4, dpg.mvKey_F5, dpg.mvKey_N,
                        dpg.mvKey_Left, dpg.mvKey_Right):
                dpg.add_key_press_handler(key=key, callback=self._browser_key)
        self._control_handler_registries.append(registry)

    def _browser_key(self, _sender, key, _user_data=None):
        if not self.winfo_exists() or not dpg.is_item_shown(self.tag):
            return
        ctrl = dpg.is_key_down(dpg.mvKey_LControl) or dpg.is_key_down(dpg.mvKey_RControl)
        shift = dpg.is_key_down(dpg.mvKey_LShift) or dpg.is_key_down(dpg.mvKey_RShift)
        alt = dpg.is_key_down(dpg.mvKey_LAlt) or dpg.is_key_down(dpg.mvKey_RAlt)
        if (key == dpg.mvKey_L and ctrl) or key == dpg.mvKey_F4:
            self.address.begin_edit()
        elif key == dpg.mvKey_F5:
            self._refresh()
        elif key == dpg.mvKey_N and ctrl and shift:
            self._show_new_folder()
        elif key == dpg.mvKey_Left and alt:
            self._go_back()
        elif key == dpg.mvKey_Right and alt:
            self._go_forward()

    def _show_new_folder(self):
        if self._creating_folder:
            return
        self.address.end_edit()
        dpg.show_item(self.new_folder_row)
        dpg.set_value(self.new_folder_edit, "New folder")
        self.focus_editor(self.new_folder_edit)

    def _hide_new_folder(self):
        dpg.hide_item(self.new_folder_row)

    def _create_folder(self):
        if self._creating_folder:
            return
        name = str(dpg.get_value(self.new_folder_edit) or "").strip()
        if not name or name in (".", "..") or any(char in name for char in "\\/"):
            dpg.set_value(self.status, "Enter a folder name, without path separators.")
            return
        parent = self._current_path
        path = os.path.join(parent, name)
        self._creating_folder = True
        dpg.configure_item(self.create_folder_button, enabled=False)
        dpg.set_value(self.status, "Creating folder...")

        def worker():
            error = None
            try:
                os.mkdir(path)
            except (OSError, ValueError) as exc:
                error = str(exc)
            self.view.after(0, self._folder_created, parent, path, error)
        threading.Thread(target=worker, name="winux-folder-create", daemon=True).start()

    def _folder_created(self, parent, path, error):
        if not self.winfo_exists():
            return
        self._creating_folder = False
        dpg.configure_item(self.create_folder_button, enabled=True)
        if parent != self._current_path:
            return
        if error:
            dpg.set_value(self.status, "Could not create folder: {}".format(error))
            return
        self._hide_new_folder()
        dpg.set_value(self.filter_edit, "")
        self._select_after_load = path
        self._refresh()

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
        image_tag, button, is_drive = items
        if image is not None:
            texture = WindowsIconRegistry.get_path_icon(path, image)
            if image_tag:
                dpg.configure_item(image_tag, texture_tag=texture)
            list_icon = self.listbox.icons.get(path)
            if list_icon:
                dpg.configure_item(list_icon, texture_tag=texture)
            if os.path.normcase(path) == os.path.normcase(self._current_path):
                dpg.configure_item(self.address_icon, texture_tag=texture)
        if is_drive and name:
            dpg.configure_item(button, label=name)

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
        dpg.configure_item(self.back_button, enabled=bool(self._back_paths))
        dpg.configure_item(self.forward_button, enabled=bool(self._forward_paths))
        dpg.configure_item(self.up_button,
                           enabled=os.path.dirname(self._current_path) != self._current_path)
        current = os.path.normcase(self._current_path)
        parents = [path for path in self._place_items
                   if current == os.path.normcase(path) or
                   current.startswith(os.path.normcase(path).rstrip("\\/") + os.sep)]
        active = max(parents, key=len) if parents else None
        for path, (_, button, _) in self._place_items.items():
            dpg.set_value(button, path == active)

    def _navigate(self, value, remember=True):
        value = os.path.expandvars(os.path.expanduser(str(value).strip()))
        candidate = os.path.abspath(os.path.join(self._current_path, value))
        if not os.path.isdir(candidate):
            dpg.set_value(self.status, "Folder does not exist: {}".format(candidate))
            self._update_navigation()
            return False
        if remember and candidate != self._current_path:
            self._back_paths.append(self._current_path)
            self._forward_paths.clear()
        self._current_path = candidate
        self._select_after_load = None
        self._hide_new_folder()
        dpg.set_value(self.path_edit, candidate)
        dpg.configure_item(self.address_icon, texture_tag=WindowsIconRegistry.get_path_icon(candidate))
        self._update_breadcrumbs()
        dpg.set_value(self.folder_edit, candidate)
        dpg.set_value(self.filter_edit, "")
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
        self.enter_editors = {self.path_edit, self.folder_edit, self.filter_edit, self.new_folder_edit,
                              *self.listbox.items.values()}
        dpg.set_value(self.status, "{} folder(s)".format(len(entries)))

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
        dpg.set_value(self.status, "Loading...")

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
            self._entries.clear()
            self._listing = []
            self.listbox.setItems([])
            dpg.set_value(self.status, error)
            return
        self._entries = {full_path: full_path for _, _, full_path in entries}
        self._folder_mtimes = modified or {}
        self._listing = entries
        self._filter_entries()
        if self._select_after_load in self.listbox.items:
            self.listbox.setCurrentKey(self._select_after_load, select=True)
        self._select_after_load = None

    def _enter_key(self, key):
        path = self._entries.get(key) or str(key or "")
        if path and os.path.isdir(path):
            self._navigate(path)

    def _select_folder(self):
        value = str(dpg.get_value(self.folder_edit) or "").strip()
        path = os.path.abspath(os.path.join(
            self._current_path, os.path.expandvars(os.path.expanduser(value))))
        if not os.path.isdir(path):
            dpg.set_value(self.status, "Folder does not exist: {}".format(path))
            return
        self.finish(path)

    def finish(self, value):
        if self._finished:
            return
        self._finished = True
        self._generation += 1
        try:
            if callable(self.on_result):
                self.on_result(value)
        finally:
            self.destroy()

    def _close_from_escape(self):
        if dpg.is_item_shown(self.new_folder_row):
            self._hide_new_folder()
        elif self.address.editing:
            self.address.end_edit()
        else:
            self.finish(None)

    def _close_from_native(self):
        self.finish(None)
