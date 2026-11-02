from __future__ import annotations

from pathlib import Path, PurePosixPath
from ...runtime.paths import safe_current_directory
import os
from typing import Any, Callable, Dict, List, Optional, Tuple, Union

from .explorer.list_view import ExplorerListView, ListViewItem
from .explorer.list_model import FILE_METADATA_KEYS
from ...services.file_color_rules import FileColorRules
from ...services.file_filter import compile_file_filter
from ...services.file_types import file_type_name
from ...preferences.navigation import NavigationPreferences
from .toolbar import (
    FileToolbar, ResourceTextures, file_status_bar_theme, file_status_text_theme,
)
from DearUIQt.themes import (
    panel_surface_theme, ThemeTarget, ThemeColor, ThemeStyle,
    theme_component, make_theme,
)
from DearUIQt.widgets import QFrame, QLabel, QSpacer, QRetainedItem
from DearUIQt.layouts import QHBoxLayout
from DearUIQt.gui import QCursor


class ValueProxy:
    """Compatibility value facade over a retained DearUIQt item."""
    def __init__(self, tag: Optional[Union[int, str]] = None):
        self.tag = tag

    def _item(self):
        return QRetainedItem(self.tag) if self.tag is not None else None

    def set(self, value: Any) -> None:
        item = self._item()
        if item is not None and item.exists():
            item.setValue(str(value))

    def get(self) -> str:
        item = self._item()
        if item is not None and item.exists():
            return str(item.value(""))
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
        show_hidden_files: bool = False,
        file_colors: bool = True,
        file_color_rules=None,
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
        self._pending_created_rename: Optional[Dict[str, Any]] = None
        self._source_items: List[ListViewItem] = []
        self._filter_query = ""
        self._show_hidden_files = bool(show_hidden_files)
        self._file_colors = bool(file_colors)
        self._color_rules = FileColorRules(file_color_rules)
        self._pinned_parent: Optional[ListViewItem] = None
        self.status_prefix = ""
        
        self._container_theme = self._create_container_theme()

        # 2. Container chính
        self._container_widget = QFrame(
            parent=parent, width=-1, height=-1, frame_shape=QFrame.StyledPanel,
            no_scrollbar=True, no_scroll_with_mouse=True,
        )
        self.container = self._container_widget.tag
        self._container_widget.setTheme(self._container_theme)

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
        self._body_widget = QFrame(
            parent=self._container_widget, width=-1,
            height=-body_offset if self.has_status else -1,
            frame_shape=QFrame.NoFrame, no_scrollbar=True,
            no_scroll_with_mouse=True,
        )
        self.body = self._body_widget.tag
        self._body_widget.setTheme(
            panel_surface_theme(bordered=False, compact=True, alternate=False))

        if self.has_status:
            # A dedicated fixed-height child prevents the status text from being
            # pushed upward/downward when the parent or ListView is resized.
            self._status_widget = QFrame(
                parent=self._container_widget, width=-1, height=self.STATUS_HEIGHT,
                frame_shape=QFrame.NoFrame, no_scrollbar=True,
                no_scroll_with_mouse=True,
            )
            self.status_window = self._status_widget.tag
            self._status_widget.setTheme(file_status_bar_theme())
            self._status_layout = QHBoxLayout(parent=self._status_widget, spacing=0)
            self._status_label = QLabel("0 items", parent=self._status_layout)
            self.status_tag = self._status_label.tag
            self._status_label.setTheme(file_status_text_theme())
            self._status_spacer = QSpacer(8, 14, parent=self._status_layout)
            self._status_separator = self._status_spacer.tag
            self._selected_status_label = QLabel("0 selected", parent=self._status_layout)
            self.selected_status_tag = self._selected_status_label.tag
            self._selected_status_label.setTheme(file_status_text_theme(muted=True))
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
        self._column_preferences = NavigationPreferences()
        state = self._column_preferences.load_columns(self.panel_id)
        if state:
            self.listview.restore_column_state(state)
        self.listview.on_columns_change = lambda state: self._column_preferences.save_columns(self.panel_id, state)

    @classmethod
    def local(cls, parent, callbacks):
        current = safe_current_directory()
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
        self.listview._set_keyboard_focus(True)

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

    def focus_created_item(self, path: Any, commit: Callable[[str], None]) -> bool:
        """Select a freshly created item, reveal it, and start renaming it.

        Mirrors Windows Explorer: the new entry is selected, scrolled into
        view and its inline rename editor opens immediately. The refreshed
        listing arrives asynchronously, so when the row is not part of the
        current listing yet the request stays queued and is applied by the
        next ``display()`` of the same folder.
        """
        row = self.row_for_path(path)
        if row is None:
            row = self._row_for_path_identity(path)
        if row is None:
            self._pending_created_rename = {
                "path": path,
                "commit": commit,
                "folder": self._path_identity(self.current_path),
            }
            return False
        self._pending_created_rename = None
        self.select_row(row)
        self._consume_created_rename_row(row, commit)
        return True

    def _row_for_path_identity(self, path):
        target = self._path_identity(path)
        return next(
            (index for index, item in enumerate(self.listview.items)
             if self._path_identity(item.data.get("path") or item.path) == target),
            None,
        )

    def _consume_created_rename_row(self, row, commit):
        if not callable(commit):
            return
        # Creation enters the editor directly instead of begin_inline_rename().
        # Install the same commit callback before activation (including the
        # deferred scroll path), otherwise Enter is rejected by _rename_commit.
        self._rename_commit_callback = commit
        try:
            self.listview.begin_rename_for_created_item(int(row))
        except Exception:
            self.listview.begin_inline_rename(int(row))

    def _consume_pending_created_rename(self):
        pending = self._pending_created_rename
        if not pending:
            return
        if self._path_identity(self.current_path) != pending["folder"]:
            self._pending_created_rename = None
            return
        row = self.row_for_path(pending["path"])
        if row is None:
            row = self._row_for_path_identity(pending["path"])
        if row is None:
            return
        self._pending_created_rename = None
        self.select_row(row)
        self._consume_created_rename_row(row, pending["commit"])

    @staticmethod
    def _point_in_item(tag, x, y):
        if not tag:
            return False
        item = QRetainedItem(tag)
        if not item.exists():
            return False
        try:
            rect = item.globalGeometry()
        except Exception:
            return False
        return (rect.width() > 1 and rect.height() > 1
                and rect.contains((float(x), float(y))))

    def screen_rect(self):
        """Return the stable outer pane rectangle in viewport coordinates.

        Dragging uses global mouse handlers.  Child-window rectangles can be
        stale for one frame while the source pane owns mouse capture, so the
        outer FilePanel container is the authoritative hit-test target.
        """
        for tag in (getattr(self, "container", None), getattr(self, "body", None)):
            if not tag:
                continue
            item = QRetainedItem(tag)
            if not item.exists():
                continue
            try:
                rect = item.globalGeometry()
            except Exception:
                continue
            if rect.width() > 2 and rect.height() > 2:
                return (rect.left(), rect.top(),
                        rect.left() + rect.width(), rect.top() + rect.height())
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
            body_item = QRetainedItem(body)
            by = float(body_item.globalGeometry().top())
            scroll_y = body_item.verticalScrollValue()
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
            x, y = QCursor.pos().toTuple()
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
            x, y = QCursor.pos().toTuple()
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
        return make_theme(theme_component(
            ThemeTarget.CHILD_WINDOW,
            colors={
                ThemeColor.CHILD_BACKGROUND: self.BACKGROUND_COLOR,
                ThemeColor.BORDER: self.BORDER_COLOR,
                ThemeColor.TEXT: self.TEXT_COLOR,
            },
            styles={
                ThemeStyle.WINDOW_PADDING: (0, 0),
                ThemeStyle.ITEM_SPACING: (0, 0),
                ThemeStyle.CHILD_BORDER_SIZE: 1,
            },
        ))

    def _create_listview(self) -> Any:
        listview = ExplorerListView(
            parent=self.body,
            name_color_provider=self._color_rules if self._file_colors else None,
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
        odb_tools = [{
            "id": "check_odb_quick" if self.panel_id == "server" else "check_odb_local",
            "label": "Quick Check",
            "action": "check_odb",
            "icon": icon("Check_File"),
            "enabled": False,
        }]
        if self.panel_id == "server":
            odb_tools.append({
                "id": "extract_odb_data",
                "label": "Extract Data",
                "action": "extract_odb",
                "icon": icon("Details"),
                "enabled": False,
            })
        odb_tools.append({
            "id": "upgrade_odb",
            "label": "Upgrade ODB",
            "action": "upgrade_odb",
            "icon": icon("Editor_Reload"),
            "enabled": False,
        })
        menu.append({
            "id": "odb_tools_group",
            "label": "Odb Tools",
            "icon": icon("Check_File"),
            "children": odb_tools,
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
        """Synchronize every Explorer menu action with live UI state.

        The menu structure is retained and never rebuilt here.  Only QAction-
        like enabled state changes, so opening a context menu remains cheap and
        selection/focus are not disturbed.
        """
        all_items = list(items or [])
        real_items = [item for item in all_items if not item.data.get("parent")]
        selected_count = len(real_items)
        has_selection = selected_count > 0
        single_real = selected_count == 1
        single_target = len(all_items) == 1
        single_file = single_real and not bool(real_items[0].is_dir)

        try:
            server_connected = bool(self.callbacks.get(
                "server_connected", lambda: True)())
        except Exception:
            server_connected = False
        source_ready = self.panel_id != "server" or server_connected

        try:
            clipboard_available = bool(self.callbacks.get(
                "file_clipboard_available", lambda: False)())
        except Exception:
            clipboard_available = False
        paste_ready = clipboard_available and (
            self.panel_id != "server" or server_connected)

        def suffix(item, extension):
            if item is None or bool(item.is_dir):
                return False
            name = str(item.name or item.data.get("path") or item.path or "")
            return name.casefold().endswith(extension)

        only_item = real_items[0] if single_real else None
        can_check_inp = source_ready and single_file and suffix(only_item, ".inp")
        can_check_odb = source_ready and single_file and suffix(only_item, ".odb")
        # Upgrade ODB is a batch operation over the ODB subset of the current
        # selection.  Explorer-style mixed selections are valid: unrelated
        # files/folders are ignored instead of disabling the command.
        can_upgrade_odb = (
            source_ready and any(suffix(item, ".odb") for item in real_items)
        )
        can_run_job = (
            self.panel_id == "server" and server_connected
            and any(suffix(item, ".inp") for item in real_items)
        )
        can_open = source_ready and single_target
        can_modify_selection = source_ready and has_selection
        can_rename = source_ready and single_real

        # Selection-sensitive core operations.
        states = {
            "command:open": can_open,
            "command:copy": can_modify_selection,
            "command:cut": can_modify_selection,
            "command:paste": paste_ready,
            "command:rename": can_rename,
            "command:delete": can_modify_selection,
            "check_inp": can_check_inp,
            "upgrade_odb": can_upgrade_odb,
            "odb_tools_group": can_check_odb or can_upgrade_odb,
            "command:refresh": source_ready,
            "new_group": source_ready,
            "command:new_folder": source_ready,
            "command:new_file": source_ready,
        }

        if self.panel_id == "server":
            states.update({
                "run_job": can_run_job,
                "check_odb": can_check_odb,
                "extract_odb": can_check_odb,
                "edit_server_file": (
                    server_connected and single_file
                    and int(only_item.size or 0) <= 8 * 1024 * 1024
                ),
                "command:download_selected": server_connected and has_selection,
            })
            quick_extensions = (".odb", ".sta", ".dat", ".inp")
            quick_group = False
            for extension in quick_extensions:
                enabled = server_connected and bool(self.visible_files(extension))
                states["quick:{}".format(extension)] = enabled
                quick_group = quick_group or enabled
            states["quick_download_group"] = quick_group
        else:
            states.update({
                "check_odb": can_check_odb,
                # Upload always requires a live destination server, even though
                # the selected source items are local.
                "command:upload_selected": server_connected and has_selection,
            })
            quick_extensions = (".inp", ".dat")
            quick_group = False
            for extension in quick_extensions:
                enabled = server_connected and bool(self.visible_files(extension))
                states["quick:{}".format(extension)] = enabled
                quick_group = quick_group or enabled
            states["quick_upload_group"] = quick_group

        for action, enabled in states.items():
            self.listview.set_context_menu_item_enabled(action, bool(enabled))

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
        elif action == "upgrade_odb":
            # Pass only real ODB files from a potentially mixed selection.
            # The controller repeats this filter defensively for non-menu
            # callers, but filtering here also excludes folders named *.odb.
            odb_paths = [
                item.data.get("path") or item.path
                for item in list(items or [])
                if (not item.data.get("parent") and not bool(item.is_dir)
                    and str(item.name or item.data.get("path") or item.path or "")
                    .casefold().endswith(".odb"))
            ]
            self.callbacks["upgrade_odb"](self, odb_paths)
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

        if self._container_widget.exists():
            self._container_widget.resize(-1, height)
        if self._body_widget.exists():
            self._body_widget.resize(-1, body_height)
        if self.has_status and self.status_window and self._status_widget.exists():
            self._status_widget.resize(-1, self.STATUS_HEIGHT)

        if hasattr(self, "listview") and self.listview:
            list_window = getattr(self.listview, "window_tag", None)
            if list_window:
                list_window_item = QRetainedItem(list_window)
                if list_window_item.exists():
                    list_window_item.resize(-1, body_height)

            list_body = getattr(self.listview, "body_window", None)
            scroller = getattr(self.listview, "_scroller_arrow_overlay", None)
            if scroller is not None:
                list_body = scroller.container
            if list_body:
                list_body_item = QRetainedItem(list_body)
                if list_body_item.exists():
                    pinned_height = (
                        self.listview.ROW_HEIGHT
                        if getattr(self.listview, "_pinned_item", None) is not None
                        else 0
                    )
                    list_body_item.resize(
                        -1,
                        max(
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
        return bool(compile_file_filter(query)(item))

    def _filtered_items(self) -> List[ListViewItem]:
        matches = compile_file_filter(self._filter_query)
        return [
            item for item in self._visible_source_items()
            if matches(item)
        ]

    @staticmethod
    def _is_hidden_item(item: Any) -> bool:
        return bool(
            getattr(item, "is_hidden", False)
            or getattr(item, "data", {}).get("is_hidden", False)
            or str(getattr(item, "name", "")).startswith(".")
        )

    def _visible_source_items(self) -> List[ListViewItem]:
        if getattr(self, "_show_hidden_files", False):
            return self._source_items
        return [item for item in self._source_items if not self._is_hidden_item(item)]

    def set_file_colors(self, enabled: bool, rules=None) -> None:
        self._file_colors = bool(enabled)
        if rules is not None:
            self._color_rules = FileColorRules(rules)
        self.listview.name_color_provider = self._color_rules if self._file_colors else None
        self.listview.refresh_row_visuals()

    def set_show_hidden_files(self, enabled: bool) -> None:
        enabled = bool(enabled)
        if enabled == self._show_hidden_files:
            return
        self._show_hidden_files = enabled
        self._render_items(self._filtered_items())
        self._update_item_status()
        self.selected_status.set("0 selected")

    def _update_item_status(self, filtered=None) -> None:
        if not self.has_status:
            return
        prefix = "{} | ".format(self.status_prefix) if self.status_prefix else ""
        if self._filter_query.strip():
            # Query-local visibility snapshot: count matches without allocating
            # another filtered list or rescanning hidden flags for the total.
            source = self._visible_source_items()
            total = len(source)
            if filtered is None:
                matches = compile_file_filter(self._filter_query)
                visible = sum(1 for item in source if matches(item))
            else:
                visible = len(filtered)
            self.status.set(f"{prefix}{visible} of {total} items")
        else:
            # No search means the label needs only a total, not a filter pass.
            # Do not cache counts across calls: hidden metadata may change.
            total = (len(self._source_items) if getattr(self, "_show_hidden_files", False) else
                     sum(1 for item in self._source_items if not self._is_hidden_item(item)))
            self.status.set(f"{prefix}{total} items")

    def apply_filter(self, query: str) -> bool:
        """Filter the current folder without another filesystem round trip."""
        try:
            compile_file_filter(str(query or ''))
        except ValueError as exc:
            # An incomplete/invalid mask while typing must not empty the pane,
            # clear selection or escape into the render loop. Keep the last
            # valid filter and report the error without opening a modal.
            self.status.set('Invalid filter (previous results kept): {}'.format(exc))
            return False
        self._filter_query = str(query or "")
        filtered = self._filtered_items()
        self._render_items(filtered, incremental=True)
        self._update_item_status(filtered)
        self.selected_status.set('{} selected'.format(len(self.selected_transfer_paths())))
        return True

    @staticmethod
    def _convert(item: Any, existing=None) -> ListViewItem:
        values = (
            item.name,
            str(item.path),
            bool(item.is_dir),
            int(getattr(item, "size", 0) or 0),
            float(getattr(item, "modified", 0) or 0),
        )
        item_type = getattr(item, "type_text", None)
        data = {"source": item, "path": item.path,
                **{key: getattr(item, key, None) for key in FILE_METADATA_KEYS},
                "is_hidden": bool(getattr(item, "is_hidden", False))}
        if existing is None:
            return ListViewItem(*values, item_type=item_type, data=data)
        attributes = ("name", "path", "is_dir", "size", "mtime", "item_type", "extension")
        updated = values + (item_type or file_type_name(item.name, bool(item.is_dir)),
                            os.path.splitext(item.name)[1])
        changed = (any(getattr(existing, key) != value for key, value in zip(attributes, updated)) or
                   any(existing.data.get(key) != value for key, value in data.items() if key != "source"))
        for key, value in zip(attributes, updated):
            setattr(existing, key, value)
        # Even equal metadata snapshots must point at the latest source object.
        # Preserve unrelated row-local data, as the preceding refresh did.
        existing.data.update(data)
        if changed:
            existing.refresh_display_cache()
        return existing

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
        self._consume_pending_created_rename()

        if self.has_status:
            self._update_item_status()
            self.selected_status.set("0 selected")

    def _render_items(self, converted: List[ListViewItem], *, incremental=False) -> None:
        """Render an already converted subset while retaining folder state."""
        pinned_parent = self._pinned_parent
        if hasattr(self, "listview") and self.listview:
            self.listview.current_path = str(self.current_path)
            if incremental:
                # The folder/parent row and native scroll owner are unchanged.
                # Do not show/rebuild the pane or reset its focus/selection.
                self.listview.set_items(converted, incremental=True)
                return
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
            try:
                # set_items() has already laid out the complete replacement.
                # A second full pass doubles per-cell measurement/configuration
                # during folder navigation without changing any geometry.
                QRetainedItem(self.listview.window_tag).show()
                QRetainedItem(self.listview.body_window).show()
            except Exception:
                # The first native frame may not expose child rectangles yet;
                # ExplorerListView's layout watcher retries on later frames.
                pass


    @staticmethod
    def _path_identity(value: Any) -> str:
        if isinstance(value, PurePosixPath):
            # Remote Linux paths are case-sensitive even on a Windows client.
            return str(value)
        text = os.fspath(value) if hasattr(value, "__fspath__") else str(value)
        text = os.path.normpath(text)
        return os.path.normcase(text) if os.name == "nt" else text

    @classmethod
    def _item_signature(cls, item: Any) -> tuple:
        # getattr's default expression is evaluated even when the attribute
        # exists. Read loaded row metadata once, not once per fallback field.
        # This local reference is discarded after the call; no stat/cache TTL
        # or mutable-listing invalidation policy changes here.
        data = getattr(item, "data", None) or {}
        path = data.get("path")
        if path is None:
            path = getattr(item, "path", None)
        modified = getattr(item, "modified", getattr(item, "mtime", 0.0))
        return (
            cls._path_identity(path or getattr(item, "name", "")),
            bool(getattr(item, "is_dir", False)),
            int(getattr(item, "size", 0) or 0),
            int(float(modified or 0.0) * 1_000_000),
            cls._is_hidden_item(item),
            tuple(getattr(item, key, data.get(key))
                  for key in FILE_METADATA_KEYS),
        )

    def refresh_directory(self, path: Any, items: List[Any]):
        """Refresh the current folder while preserving Explorer-like state.

        Reconcile metadata in place, preserving rendered rows and native scroll.
        No deferred scroll restoration is needed for this incremental path.
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

        previous = {self._path_identity(item.data.get("path", item.path)): item
                    for item in self._source_items}
        converted = []
        for source in items:
            existing = previous.get(self._path_identity(source.path))
            # Keep identity-dependent style/selection caches and external row
            # references alive while attaching the latest filesystem snapshot.
            converted.append(self._convert(source, existing=existing))
        self._source_items = converted
        self._render_items(self._filtered_items(), incremental=True)
        self._consume_pending_created_rename()
        if self.has_status:
            self._update_item_status()
            self.selected_status.set("{} selected".format(len(self.listview.selected)))
        return None

    def restore_vertical_scroll(self, value: float) -> None:
        body = getattr(getattr(self, "listview", None), "body_window", None)
        if not body:
            return
        try:
            item = QRetainedItem(body)
            if not item.exists():
                return
            maximum = item.verticalScrollMaximum()
            item.setVerticalScrollValue(max(0.0, min(float(value), maximum)))
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
        from ...runtime.rename_result import RenameResult
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
