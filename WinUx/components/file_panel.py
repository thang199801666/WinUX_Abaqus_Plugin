from __future__ import annotations

from pathlib import Path, PurePosixPath
import os
from typing import Any, Callable, Dict, List, Optional, Tuple, Union
import dearpygui.dearpygui as dpg

from .explorer_list_view import ExplorerListView, ListViewItem
from .toolbar import (
    FileToolbar, ResourceTextures, file_status_bar_theme, file_status_text_theme,
)
from ..widgets.imgui_qt_style import panel_surface_theme


class ValueProxy:
    """Proxy object để truy cập/gán text an toàn trên Dear PyGui tags."""
    def __init__(self, tag: Optional[Union[int, str]] = None):
        self.tag = tag

    def set(self, value: Any) -> None:
        if self.tag is not None and dpg.does_item_exist(self.tag):
            dpg.set_value(self.tag, str(value))

    def get(self) -> str:
        if self.tag is not None and dpg.does_item_exist(self.tag):
            return str(dpg.get_value(self.tag))
        return ""


class FilePanel:
    """Complete local or server file panel for the Dear PyGui view layer."""

    # --- Thống nhất kích thước chuẩn ---
    TOOLBAR_HEIGHT = 34
    STATUS_HEIGHT = 20
    BACKGROUND_COLOR = (255, 255, 255, 255)
    TEXT_COLOR = (30, 30, 30, 255)
    BORDER_COLOR = (220, 220, 220, 255)
    # The bordered panel has one content pixel on each vertical edge.
    # Reserve these pixels so the last ListView row/scrollbar is never clipped.
    CONTAINER_VERTICAL_INSET = 2

    def __init__(
        self,
        parent: Union[int, str],
        panel_id: str,
        callbacks: Dict[str, Callable],
        current_path: Any = None,
        initial_path_label: str = "",
        has_toolbar: bool = True,
        has_status: bool = True,
    ):
        self.panel_id = panel_id
        self.callbacks = callbacks
        self.current_path = current_path
        self.has_toolbar = has_toolbar
        self.has_status = has_status
        self.external_status = False

        self.history: List[Any] = []
        self.history_index: int = -1
        self._sort: Optional[Tuple[Any, bool]] = None
        self._last_size: Tuple[int, int] = (0, 0)
        self._rename_commit_callback: Optional[Callable[[str], None]] = None
        self._source_items: List[ListViewItem] = []
        self._filter_query = ""
        self._pinned_parent: Optional[ListViewItem] = None
        self.status_prefix = ""
        
        self._container_theme = self._create_container_theme()

        # 2. Container chính
        self.container = dpg.add_child_window(
            parent=parent,
            border=True,
            width=-1,
            height=-1,
            no_scrollbar=True,
            no_scroll_with_mouse=True,
        )
        dpg.bind_item_theme(self.container, self._container_theme)

        # 3. Toolbar (nếu có)
        if self.has_toolbar:
            self.toolbar = FileToolbar(
                self.container,
                self,
                callbacks,
                initial_path_label=initial_path_label,
            )
            self.path_button_tag = getattr(self.toolbar, "path_button", None)
        else:
            self.toolbar = None
            self.path_button_tag = None

        # The status strip is created after the body so it remains below the
        # file list, matching the old GUI.
        body_offset = self.STATUS_HEIGHT if self.has_status else 0
        self.body = dpg.add_child_window(
            parent=self.container,
            border=False,
            width=-1,
            height=-body_offset if self.has_status else -1,
            no_scrollbar=True,
            no_scroll_with_mouse=True,
        )
        dpg.bind_item_theme(
            self.body, panel_surface_theme(
                dpg, bordered=False, compact=True, alternate=False))

        if self.has_status:
            # A dedicated fixed-height child prevents the status text from being
            # pushed upward/downward when the parent or ListView is resized.
            self.status_window = dpg.add_child_window(
                parent=self.container,
                border=False,
                width=-1,
                height=self.STATUS_HEIGHT,
                no_scrollbar=True,
                no_scroll_with_mouse=True,
            )
            dpg.bind_item_theme(self.status_window, file_status_bar_theme())
            with dpg.group(parent=self.status_window, horizontal=True):
                self.status_tag = dpg.add_text("0 items")
                dpg.bind_item_theme(self.status_tag, file_status_text_theme())
                self._status_separator = dpg.add_spacer(width=8, height=14)
                self.selected_status_tag = dpg.add_text("0 selected")
                dpg.bind_item_theme(
                    self.selected_status_tag, file_status_text_theme(muted=True))
            self.status = ValueProxy(self.status_tag)
            self.selected_status = ValueProxy(self.selected_status_tag)
        else:
            self.status_window = None
            self.status_tag = None
            self.selected_status_tag = None
            self.status = ValueProxy(None)
            self.selected_status = ValueProxy(None)

        # 6. List View
        self.listview = self._create_listview()

    @classmethod
    def local(cls, parent, callbacks):
        current = Path.cwd()
        return cls(
            parent, "local", callbacks, current_path=current,
            initial_path_label=str(current),
        )

    @classmethod
    def server(cls, parent, callbacks):
        return cls(
            parent, "server", callbacks,
            current_path=PurePosixPath("/"), initial_path_label="Log-in",
        )

    def attach_external_status(self, status_tag, selected_status_tag):
        """Use status text owned by the main layout instead of this panel.

        The shared strip remains fixed between both file ListViews and the Job
        Viewer, independent of panel resizing.
        """
        self.external_status = True
        self.has_status = True
        self.status_window = None
        self.status_tag = status_tag
        self.selected_status_tag = selected_status_tag
        self.status = ValueProxy(status_tag)
        self.selected_status = ValueProxy(selected_status_tag)

    def set_disconnected(self):
        if self.panel_id != "server":
            return
        if self.toolbar:
            self.toolbar.set_path_text("Log-in")
        if self.has_status:
            self.status.set("Not connected")

    def focus(self):
        self.listview._has_focus = True
        self.listview._update_selection_draws()

    @property
    def is_focused(self):
        return bool(self.listview._has_focus)

    def clear_selection(self):
        self.listview.clear_selection()

    def select_row(self, row):
        self.listview.select_indices([int(row)])

    def item_for_row(self, row):
        try:
            return self.listview.items[int(row)]
        except (TypeError, ValueError, IndexError):
            return None

    def row_for_path(self, path):
        return next(
            (index for index, item in enumerate(self.listview.items)
             if (item.data.get("path") or item.path) == path),
            None,
        )

    def select_path(self, path):
        row = self.row_for_path(path)
        if row is not None:
            self.listview.select_indices([row])
            return True
        return False

    @staticmethod
    def _point_in_item(tag, x, y):
        if not tag or not dpg.does_item_exist(tag):
            return False
        try:
            x0, y0 = map(float, dpg.get_item_rect_min(tag))
            width, height = map(float, dpg.get_item_rect_size(tag))
        except Exception:
            return False
        return width > 1 and height > 1 and x0 <= x < x0 + width and y0 <= y < y0 + height

    def screen_rect(self):
        """Return the stable outer pane rectangle in viewport coordinates.

        Dragging uses global mouse handlers.  Child-window rectangles can be
        stale for one frame while the source pane owns mouse capture, so the
        outer FilePanel container is the authoritative hit-test target.
        """
        for tag in (getattr(self, "container", None), getattr(self, "body", None)):
            if not tag or not dpg.does_item_exist(tag):
                continue
            try:
                x0, y0 = map(float, dpg.get_item_rect_min(tag))
                width, height = map(float, dpg.get_item_rect_size(tag))
            except Exception:
                continue
            if width > 2 and height > 2:
                return x0, y0, x0 + width, y0 + height
        return None

    def contains_screen_point(self, x, y):
        """Return True when a viewport-space point is inside this file pane."""
        rect = self.screen_rect()
        if rect is None:
            return False
        x0, y0, x1, y1 = rect
        x, y = float(x), float(y)
        return x0 <= x < x1 and y0 <= y < y1

    def _drop_row_at_point(self, x, y):
        """Return (is_pinned, row_index) for an explicit viewport-space point."""
        lv = self.listview
        x, y = float(x), float(y)
        pinned_tag = getattr(lv, "pinned_canvas", None)
        if lv._pinned_item is not None and self._point_in_item(pinned_tag, x, y):
            return True, None

        body = getattr(lv, "body_window", None)
        if not self._point_in_item(body, x, y):
            return False, None
        try:
            _bx, by = map(float, dpg.get_item_rect_min(body))
            scroll_y = float(dpg.get_y_scroll(body))
        except Exception:
            return False, None
        index = int((y - by + scroll_y) // max(1, lv.ROW_HEIGHT))
        if 0 <= index < len(lv.items):
            return False, index
        return False, None

    def drop_destination_at(self, x, y):
        """Resolve Explorer-style destination for a drop point.

        A folder row receives the transfer. Every other location in the pane
        (file row, header, or blank area) resolves to the pane's current folder.
        """
        pinned, index = self._drop_row_at_point(x, y)
        if pinned and self.listview._pinned_item is not None:
            item = self.listview._pinned_item
            return item.data.get("path") or item.path
        item = self.item_for_row(index)
        if item is not None and item.is_dir:
            return item.data.get("path") or item.path
        return self.current_path

    def drop_destination_at_mouse(self):
        try:
            x, y = dpg.get_mouse_pos(local=False)
        except Exception:
            return self.current_path
        return self.drop_destination_at(x, y)

    def set_external_drop_highlight_at(self, x, y, enabled=True):
        if not enabled or not getattr(self, "listview", None):
            self.clear_external_drop_highlight()
            return
        pinned, index = self._drop_row_at_point(x, y)
        if pinned and self.listview._pinned_item is not None:
            self.listview.set_external_drop_target(pinned=True)
            return
        item = self.item_for_row(index)
        if item is not None and item.is_dir:
            self.listview.set_external_drop_target(index=index)
        else:
            self.listview.clear_external_drop_target()

    def set_external_drop_highlight_at_mouse(self, enabled=True):
        try:
            x, y = dpg.get_mouse_pos(local=False)
        except Exception:
            self.clear_external_drop_highlight()
            return
        self.set_external_drop_highlight_at(x, y, enabled)

    def clear_external_drop_highlight(self):
        if getattr(self, "listview", None):
            self.listview.clear_external_drop_target()

    def visible_files(self, extension=None):
        extension = str(extension or "").casefold()
        return [
            item.data.get("path") or item.path
            for item in self.listview.items
            if not item.is_dir and not item.data.get("parent")
            and (not extension or str(item.data.get("path") or item.path)
                 .casefold().endswith(extension))
        ]

    def apply_sort(self, column, descending):
        key = {"#0": "name", "modified": "date"}.get(column, column)
        self.listview.sort_key = key
        self.listview.sort_ascending = not bool(descending)
        self.listview._sort_and_refresh_in_place()
        self._sort = (column, bool(descending))

    def _create_container_theme(self):
        with dpg.theme() as container_theme:
            with dpg.theme_component(dpg.mvChildWindow):
                dpg.add_theme_color(dpg.mvThemeCol_ChildBg, self.BACKGROUND_COLOR)
                dpg.add_theme_color(dpg.mvThemeCol_Border, self.BORDER_COLOR)
                dpg.add_theme_color(dpg.mvThemeCol_Text, self.TEXT_COLOR)
                dpg.add_theme_style(dpg.mvStyleVar_WindowPadding, 0, 0)
                dpg.add_theme_style(dpg.mvStyleVar_ItemSpacing, 0, 0)
                dpg.add_theme_style(dpg.mvStyleVar_ChildBorderSize, 1)
        return container_theme

    def _create_listview(self) -> Any:
        listview = ExplorerListView(
            parent=self.body,
            items=[],
            width=-1,
            height=-1,
            show_status_bar=False,
            open_files_on_double_click=False,
            item_menu=self._context_menu_spec(),
            on_selection_change=lambda _items: self._selection_changed(),
            on_activate=self._activate_item,
            on_item_menu_action=self._menu_action,
            on_context_menu_open=self._context_menu_open,
            on_rename_commit=self._rename_commit,
            on_drag_start=(
                (lambda _items: self.callbacks["drag_start"](self))
                if self.callbacks.get("drag_start") else None
            ),
            on_drag_motion=lambda x, y: self.callbacks["drag_motion"](self, x, y),
             on_drop=lambda x, y, copy, dragged=None: self.callbacks["drop"](
                 self, x, y, copy, dragged),
             on_external_drop=(
                 (lambda paths, x, y: self.callbacks["external_drop"](
                     self, paths, x, y))
                 if self.callbacks.get("external_drop") else None
             ),
             on_external_drop_missed=(
                 (lambda: self.callbacks["external_drop_missed"](self))
                 if self.callbacks.get("external_drop_missed") else None
             ),
             on_shell_drag=(
                 (lambda items, hwnd: self.callbacks["shell_drag"](
                     self, items, hwnd))
                 if self.panel_id == "local"
                 and self.callbacks.get("shell_drag") else None
             ),
             on_sort_change=self._sort_changed,
            theme="Explorer",
            auto_fit_column_key="name",
            auto_fit_min_width=180,
            tag=f"{self.panel_id}_file_list",
        )
        # Use the same metrics and header contract as ImGuiDataGridView.  The
        # file renderer remains specialized for Shell icons/drag/drop/rename,
        # but visually behaves like a compact QTreeView/QHeaderView.
        listview.set_metrics(row_height=23, header_height=26, cell_padding=6)
        listview.setAlternatingRowColors(False)
        listview.setShowGrid(False)
        header = listview.horizontalHeader()
        header.setSectionsMovable(False)
        header.setSectionsClickable(True)
        header.setSectionResizeMode(0, header.Stretch)
        return listview

    def _sort_changed(self, key, ascending):
        column = {"name": "#0", "date": "modified"}.get(key, key)
        self._sort = (column, not ascending)
        callback = self.callbacks.get("sort_changed")
        if callback:
            callback(self, column, not ascending)

    def _context_menu_spec(self) -> List[Any]:
        menu: List[Any] = []
        icon = ResourceTextures.get
        if self.panel_id == "server":
            menu.append(("Run Job", "run_job", icon("Execute")))
            menu.append({
                "id": "check_odb_group",
                "label": "Check ODB",
                "icon": icon("Check_File"),
                "children": [
                    {
                        "id": "check_odb_quick",
                        "label": "Quick Check",
                        "action": "check_odb",
                        "icon": icon("Check_File"),
                        "enabled": False,
                    },
                    {
                        "id": "extract_odb_data",
                        "label": "Extract Data",
                        "action": "extract_odb",
                        "icon": icon("Details"),
                        "enabled": False,
                    },
                ],
            })
        else:
            # Local ODB inspection uses the same result dialog as the server
            # action, but runs Abaqus against the selected local file.
            menu.append({
                "id": "check_odb_local",
                "label": "Check ODB",
                "action": "check_odb",
                "icon": icon("Check_File"),
                "enabled": False,
            })
        menu.extend([("Check INP", "check_inp", icon("Check_File")), ("---", None)])
        if self.panel_id == "local":
            # Works with the complete ListView selection, so Ctrl/Shift click
            # can upload many files/folders in one batch.
            menu.append({
                "label": "Upload selected",
                "action": "command:upload_selected",
                "icon": icon("Upload"),
                "shortcut": "F5",
            })
            menu.append({
                "id": "quick_upload_group",
                "label": "Quick Upload",
                "icon": icon("Upload"),
                "children": [
                    ("Upload *.inp", "quick:.inp", icon("Upload")),
                    ("Upload *.dat", "quick:.dat", icon("Upload")),
                ],
            })
        else:
            menu.append({
                "label": "Download selected",
                "action": "command:download_selected",
                "icon": icon("Download"),
                "shortcut": "F5",
            })
            menu.append({
                "id": "quick_download_group",
                "label": "Quick Download",
                "icon": icon("Download"),
                "children": [
                    ("Download *.odb", "quick:.odb", icon("Download")),
                    ("Download *.sta", "quick:.sta", icon("Download")),
                    ("Download *.dat", "quick:.dat", icon("Download")),
                    ("Download *.inp", "quick:.inp", icon("Download")),
                ],
            })
        menu.append(("---", None))
        if self.panel_id == "server":
            menu.append({
                "id": "server_notepad_edit",
                "label": "Edit in WinUx Notepad",
                "action": "edit_server_file",
                "shortcut": "F4",
                "icon": icon("Edit"),
                "enabled": False,
            })
        menu.extend([
            ("Open", "command:open", icon("Open_Folder")),
            ("Copy", "command:copy", icon("Copy")),
            ("Cut", "command:cut", icon("Cut")),
            ("Paste", "command:paste", icon("Paste")),
            ("---", None),
            {
                "label": "Rename",
                "action": "command:rename",
                "icon": icon("Rename"),
                "shortcut": "F2",
            },
            {
                "label": "Delete",
                "action": "command:delete",
                "icon": icon("Delete"),
                "shortcut": "Del",
            },
            {
                "id": "new_group",
                "label": "New",
                "icon": icon("New"),
                "children": [
                    {
                        "label": "New Folder",
                        "action": "command:new_folder",
                        "icon": icon("Folder"),
                        "shortcut": "F7",
                    },
                    {
                        "label": "New File",
                        "action": "command:new_file",
                        "icon": icon("New"),
                    },
                ],
            },
            {
                "label": "Refresh",
                "action": "command:refresh",
                "icon": icon("Refresh"),
                "shortcut": "Ctrl+R",
            },
        ])
        return menu

    def _context_menu_open(self, items: List[ListViewItem]) -> None:
        """Update context-sensitive ODB actions without rebuilding popup."""
        real_items = [
            item for item in list(items or [])
            if not item.data.get("parent")
        ]
        can_check_odb = (
            len(real_items) == 1
            and not bool(real_items[0].is_dir)
            and str(real_items[0].name or "").casefold().endswith(".odb")
        )
        self.listview.set_context_menu_item_enabled(
            "check_odb", can_check_odb)
        if self.panel_id == "server":
            self.listview.set_context_menu_item_enabled(
                "extract_odb", can_check_odb)
            can_edit_server = (
                len(real_items) == 1
                and not bool(real_items[0].is_dir)
                and int(real_items[0].size or 0) <= 8 * 1024 * 1024
            )
            self.listview.set_context_menu_item_enabled(
                "edit_server_file", can_edit_server)

    def _menu_action(self, action: Any, items: List[ListViewItem]) -> None:
        action = str(action or "")
        # ExplorerListView snapshots the complete context-menu selection before
        # hiding the popup. Preserve that snapshot instead of reading the live
        # selection again after focus has moved to the menu/modal.
        paths = [
            item.data.get("path") or item.path
            for item in list(items or [])
            if not item.data.get("parent")
        ]
        if action == "run_job":
            self.callbacks["run_job"](self)
        elif action == "check_inp":
            self.callbacks["check_inp"](self)
        elif action == "check_odb":
            self.callbacks["check_odb"](self, paths)
        elif action == "extract_odb":
            self.callbacks["extract_odb"](self, paths)
        elif action == "edit_server_file":
            self.callbacks["edit_server_file"](self, paths)
        elif action.startswith("quick:"):
            self.callbacks["quick_transfer"](self, action.split(":", 1)[1])
        elif action.startswith("command:"):
            self.callbacks["command"](
                self, action.split(":", 1)[1], paths)

    def _activate_pinned_parent(self, item: ListViewItem) -> None:
        """Open the pinned ``..`` row without looking it up in normal rows."""
        callback = self.callbacks.get("double_click")
        if callback is not None:
            callback(self, item)

    def _activate_item(self, item: ListViewItem) -> bool:
        try:
            row = self.listview.items.index(item)
        except ValueError:
            return False
        if "double_click" in self.callbacks:
            self.callbacks["double_click"](self, row)
        return False

    def toolbar_height_changed(self) -> None:
        """Reflow the list immediately when the search row opens/closes."""
        width, height = self._last_size
        if width > 0 and height > 0:
            self._last_size = (0, 0)
            self.resize(width, height)

    def resize(self, width: float, height: float) -> None:
        width = max(1, int(width))
        height = max(1, int(height))
        if (width, height) == self._last_size:
            return
        self._last_size = (width, height)

        top_offset = (self.toolbar.height if self.has_toolbar and self.toolbar else 0)
        bottom_offset = self.STATUS_HEIGHT if (self.has_status and not self.external_status) else 0
        body_height = max(1, height - top_offset - bottom_offset - self.CONTAINER_VERTICAL_INSET)

        if dpg.does_item_exist(self.container):
            dpg.configure_item(self.container, width=-1, height=height)
        if dpg.does_item_exist(self.body):
            dpg.configure_item(self.body, width=-1, height=body_height)
        if self.has_status and self.status_window and dpg.does_item_exist(self.status_window):
            dpg.configure_item(
                self.status_window, width=-1, height=self.STATUS_HEIGHT
            )

        if hasattr(self, "listview") and self.listview:
            list_window = getattr(self.listview, "window_tag", None)
            if list_window and dpg.does_item_exist(list_window):
                dpg.configure_item(list_window, width=-1, height=body_height)

            list_body = getattr(self.listview, "body_window", None)
            scroller = getattr(self.listview, "_scroller_arrow_overlay", None)
            if scroller is not None:
                list_body = scroller.container
            if list_body and dpg.does_item_exist(list_body):
                pinned_height = (
                    self.listview.ROW_HEIGHT
                    if getattr(self.listview, "_pinned_item", None) is not None
                    else 0
                )
                dpg.configure_item(
                    list_body,
                    width=-1,
                    height=max(
                        1,
                        body_height
                        - self.listview.HEADER_HEIGHT
                        - pinned_height,
                    ),
                )

            if hasattr(self.listview, "_resize_layout_pending"):
                self.listview._resize_layout_pending = True

    def _selection_changed(self) -> None:
        if not self.has_status:
            return
        selected = len(self.selected_transfer_paths())
        self._update_item_status()
        self.selected_status.set(f"{selected} selected")

    @staticmethod
    def _matches_filter(item: ListViewItem, query: str) -> bool:
        query = str(query or "").strip().casefold()
        if not query:
            return True
        values = (
            getattr(item, "name", ""),
            getattr(item, "item_type", ""),
            getattr(item, "path", ""),
        )
        return any(query in str(value or "").casefold() for value in values)

    def _filtered_items(self) -> List[ListViewItem]:
        return [
            item for item in self._source_items
            if self._matches_filter(item, self._filter_query)
        ]

    def _update_item_status(self) -> None:
        if not self.has_status:
            return
        visible = len(self._filtered_items())
        total = len(self._source_items)
        prefix = "{} | ".format(self.status_prefix) if self.status_prefix else ""
        if self._filter_query.strip():
            self.status.set(f"{prefix}{visible} of {total} items")
        else:
            self.status.set(f"{prefix}{total} items")

    def apply_filter(self, query: str) -> None:
        """Filter the current folder without another filesystem round trip."""
        self._filter_query = str(query or "")
        self._render_items(self._filtered_items())
        self._update_item_status()
        self.selected_status.set("0 selected")

    @staticmethod
    def _convert(item: Any) -> ListViewItem:
        return ListViewItem(
            item.name,
            str(item.path),
            bool(item.is_dir),
            int(getattr(item, "size", 0) or 0),
            float(getattr(item, "modified", 0) or 0),
            item_type=getattr(item, "type_text", None),
            data={"source": item, "path": item.path},
        )

    def display(self, path: Any, items: List[Any], record_history: bool = True) -> None:
        path_changed = path != self.current_path
        self.current_path = path
        if path_changed:
            self._filter_query = ""
            if self.toolbar:
                self.toolbar.clear_search()
        if record_history:
            del self.history[self.history_index + 1 :]
            if not self.history or self.history[-1] != path:
                self.history.append(path)
            self.history_index = len(self.history) - 1

        if self.toolbar:
            self.toolbar.set_path_text(str(path))

        converted: List[ListViewItem] = []
        parent = getattr(path, "parent", None)
        pinned_parent = None
        if parent is not None and parent != path:
            pinned_parent = ListViewItem(
                "..",
                str(parent),
                True,
                0,
                0.0,
                item_type="Parent folder",
                data={"parent": True, "path": parent},
            )
        converted.extend(self._convert(x) for x in items)
        self._source_items = converted
        self._pinned_parent = pinned_parent
        self._render_items(self._filtered_items())

        if self.has_status:
            self._update_item_status()
            self.selected_status.set("0 selected")

    def _render_items(self, converted: List[ListViewItem]) -> None:
        """Render an already converted subset while retaining folder state."""
        pinned_parent = self._pinned_parent
        if hasattr(self, "listview") and self.listview:
            self.listview.current_path = str(self.current_path)
            # Update the pinned parent state without rendering it separately.
            # set_items() rebuilds the pinned row and body together, preventing
            # two consecutive redraws during every folder navigation.
            self.listview._pinned_item = pinned_parent
            self.listview._pinned_command = (
                (lambda item=pinned_parent: self._activate_pinned_parent(item))
                if pinned_parent is not None else None
            )
            self.listview._pinned_hovered = False
            self.listview._pinned_last_click_time = 0.0
            self.listview.set_items(converted)
            if hasattr(self.listview, "_resize_layout_pending"):
                self.listview._resize_layout_pending = True
            try:
                self.listview._layout_all()
                dpg.show_item(self.listview.window_tag)
                dpg.show_item(self.listview.body_window)
            except Exception:
                # The first native frame may not expose child rectangles yet;
                # ExplorerListView's layout watcher retries on later frames.
                pass


    @staticmethod
    def _path_identity(value: Any) -> str:
        text = os.fspath(value) if hasattr(value, "__fspath__") else str(value)
        text = os.path.normpath(text)
        return os.path.normcase(text) if os.name == "nt" else text

    @classmethod
    def _item_signature(cls, item: Any) -> Tuple[str, bool, int, int]:
        path = getattr(item, "path", None)
        if path is None and hasattr(item, "data"):
            path = item.data.get("path")
        modified = getattr(item, "modified", getattr(item, "mtime", 0.0))
        return (
            cls._path_identity(path or getattr(item, "name", "")),
            bool(getattr(item, "is_dir", False)),
            int(getattr(item, "size", 0) or 0),
            int(float(modified or 0.0) * 1_000_000),
        )

    def refresh_directory(self, path: Any, items: List[Any]):
        """Refresh the current folder while preserving Explorer-like state.

        Returns the previous vertical scroll offset when a redraw occurred, or
        ``None`` when the watcher event did not change visible directory data.
        """
        if self._path_identity(path) != self._path_identity(self.current_path):
            return None

        current_signature = tuple(sorted(
            (self._item_signature(item) for item in self._source_items),
            key=lambda row: row[0],
        ))
        incoming_signature = tuple(sorted(
            (self._item_signature(item) for item in items),
            key=lambda row: row[0],
        ))
        if current_signature == incoming_signature:
            return None

        selected = {
            self._path_identity(value) for value in self.selected_transfer_paths()
        }
        listview = getattr(self, "listview", None)
        body = getattr(listview, "body_window", None)
        scroll_y = 0.0
        if body and dpg.does_item_exist(body):
            try:
                scroll_y = float(dpg.get_y_scroll(body))
            except Exception:
                scroll_y = 0.0
        had_focus = bool(getattr(listview, "_has_focus", False))

        self.display(path, items, record_history=False)

        rows = [
            index for index, item in enumerate(self.listview.items)
            if self._path_identity(item.data.get("path") or item.path) in selected
        ]
        if rows:
            self.listview.select_indices(rows)
        else:
            self.selected_status.set("0 selected")
        self.listview._has_focus = had_focus
        self.listview._update_selection_draws()
        self.restore_vertical_scroll(scroll_y)
        return scroll_y

    def restore_vertical_scroll(self, value: float) -> None:
        body = getattr(getattr(self, "listview", None), "body_window", None)
        if not body or not dpg.does_item_exist(body):
            return
        try:
            maximum = float(dpg.get_y_scroll_max(body))
            dpg.set_y_scroll(body, max(0.0, min(float(value), maximum)))
        except Exception:
            pass


    def selected_paths(self) -> List[Any]:
        if hasattr(self, "listview") and hasattr(self.listview, "get_selected"):
            return [x.data.get("path") or x.path for x in self.listview.get_selected()]
        return []

    def selected_transfer_paths(self) -> List[Any]:
        if hasattr(self, "listview") and hasattr(self.listview, "get_selected"):
            return [
                x.data.get("path") or x.path
                for x in self.listview.get_selected()
                if not x.data.get("parent")
            ]
        return []

    def drag_transfer_paths(self) -> List[Any]:
        """Return the immutable source set for the active drag gesture."""
        listview = getattr(self, "listview", None)
        dragged = list(getattr(listview, "_drag_source_items", []) or [])
        if dragged:
            return [
                item.data.get("path") or item.path
                for item in dragged
                if not item.data.get("parent")
            ]
        return self.selected_transfer_paths()

    def parent_selected(self) -> bool:
        return any(x.data.get("parent") for x in self.listview.get_selected()) if self.listview else False

    def selected_parent_path(self) -> Optional[Any]:
        if self.listview:
            for item in self.listview.get_selected():
                if item.data.get("parent"):
                    return item.data.get("path") or item.path
        return None

    def set_sort_indicator(self, column: Any, descending: bool) -> None:
        self.apply_sort(column, descending)

    def cancel_drag(self) -> None:
        if hasattr(self, "listview"):
            try:
                self.listview.clear_external_drop_target()
            except Exception:
                pass
            if hasattr(self.listview, "cancel_operations"):
                try:
                    self.listview.cancel_operations()
                except Exception:
                    pass

    def begin_inline_rename(self, row: Union[int, str], commit: Callable[[str], None]) -> None:
        if not hasattr(self, "listview"):
            return
        idx = int(row)
        self._rename_commit_callback = commit
        self.listview.begin_inline_rename(idx)

    def _rename_commit(self, item: ListViewItem, new_name: str) -> Any:
        callback = self._rename_commit_callback
        if callback is None:
            return False
        result = callback(new_name)
        if result is False or result is None:
            return False
        from ..runtime.rename_result import RenameResult
        if isinstance(result, RenameResult):
            result.then(lambda success: self._rename_callback_completed(callback, success))
            return result
        self._rename_commit_callback = None
        return result

    def _rename_callback_completed(self, callback, success):
        if success and self._rename_commit_callback is callback:
            self._rename_commit_callback = None

    def refocus_inline_rename(self) -> bool:
        if not hasattr(self, "listview"):
            return False
        return bool(self.listview.refocus_inline_rename())
