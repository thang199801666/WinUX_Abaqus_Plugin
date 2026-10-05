from __future__ import annotations

from typing import Any, Dict, Iterable, Optional

import dearpygui.dearpygui as dpg

from .explorer_list_view import ExplorerListView, ListViewItem
from .explorer_themes import ListViewTheme
from .shared_scroller import SharedScrollerMetrics
from .toolbar import ResourceTextures


class JobsView:
    """PBS jobs rendered by the same ExplorerListView used for files."""

    COLUMNS = (
        {"key": "job_id", "label": "Job ID", "weight": 1.0, "align": "center", "visible": True},
        {"key": "job_name", "label": "Name", "weight": 1.0, "align": "left", "visible": True},
        {"key": "user", "label": "User", "weight": 1.0, "align": "left", "visible": True},
        {"key": "tokens", "label": "Tokens", "weight": 1.0, "align": "center", "visible": True},
        {"key": "status", "label": "Status", "weight": 1.0, "align": "center", "visible": True},
        {"key": "elapsed", "label": "Elapsed", "weight": 1.0, "align": "center", "visible": True},
    )

    FIXED_COLUMN_WIDTH = 120.0
    NAME_MIN_WIDTH = 1.0

    MENU = (
        ("Check Job", "check", "Check_File", True),
        ("Edit Job", "edit", "Edit", True),
        ("Cancel Job", "cancel", "Delete", True),
        ("Open Temp", "open_temp", "Open_Folder", True),
        ("Hot Download", "hot_download", "Download", True),
        ("---", None, None, True),
        ("View Details", "details", "Details", True),
        ("---", None, None, True),
        ("Refresh", "refresh", "Refresh", True),
    )

    def __init__(self, parent: str | int, callbacks: Optional[Dict[str, Any]] = None):
        self.callbacks = callbacks or {}
        self._plots_open_job_id = None
        self._plots_open_job_ids = set()
        self.container = dpg.add_child_window(
            parent=parent, width=-1, height=-1, border=False,
            no_scrollbar=True, no_scroll_with_mouse=True,
        )
        self.body = self.container
        self.listview = self._create_listview()
        self._context_fallback_registry = None
        self._install_context_menu_fallback()
        # Remove the outer child window's default 8 px padding. The ListView
        # already owns its border and scrollable body; retaining both layers'
        # chrome makes the inner pane larger than its container and creates an
        # unnecessary horizontal scrollbar on startup.
        dpg.bind_item_theme(self.container, self.listview.theme_pane)
        self.table = self.listview.window_tag
        self._apply_default_column_widths()

    def resize(self, width, height):
        width = max(1, int(width))
        height = max(1, int(height))

        # ``bottom_region`` owns the explicit dimensions. Both nested layers
        # fill its content box instead of repeating the parent's pixel size,
        # which can overflow by a border/DPI rounding pixel and create outer
        # horizontal/vertical scrollbars.
        dpg.configure_item(self.container, width=-1, height=-1)
        self.listview.resize(width=-1, height=-1)

        if self.listview.auto_width_enabled:
            self.listview._fit_columns_auto_width(
                self.listview._available_width())
            self.listview._last_available_width = self.listview._available_width()
        else:
            self._fit_name_column_to_available_width(width)
        self._layout_now_and_next_frame()

    def _apply_default_column_widths(self):
        fixed = self.FIXED_COLUMN_WIDTH
        for key in ("job_id", "user", "tokens", "status", "elapsed"):
            self.listview._column_widths[key] = fixed
        self._fit_name_column_to_available_width(reset_fixed=True)

    def _fit_name_column_to_available_width(
            self, container_width=None, reset_fixed=False):
        if container_width is None:
            try:
                container_width = float(dpg.get_item_rect_size(self.container)[0])
            except Exception:
                container_width = 0.0

        # Reserve border and the vertical scrollbar gutter. This makes the sum
        # of all column widths equal the actual visible row/header width and
        # prevents a horizontal overflow during arbitrary viewport resizing.
        if container_width and container_width > 20:
            available = max(1.0, float(container_width) - (SharedScrollerMetrics.THICKNESS + 4.0))
        else:
            available = max(1.0, float(self.listview._available_width()))
        widths = self.listview._column_widths
        fixed_keys = ("job_id", "user", "tokens", "status", "elapsed")
        if reset_fixed:
            # Establish the initial Job Viewer layout once.
            for key in fixed_keys:
                widths[key] = self.FIXED_COLUMN_WIDTH

        # Every non-Name width is authoritative after initialization, including
        # values chosen manually by the user. Recompute Name from the remaining
        # space instead of applying a delta; this prevents startup/layout
        # measurement errors from accumulating into an oversized Name column.
        occupied = sum(float(widths[key]) for key in fixed_keys)
        widths["job_name"] = max(
            self.NAME_MIN_WIDTH,
            available - occupied,
        )
        self.listview._last_available_width = available

    def _layout_now_and_next_frame(self):
        def apply_layout(sender=None, app_data=None):
            if not dpg.does_item_exist(self.container):
                return
            try:
                actual_width = float(dpg.get_item_rect_size(self.container)[0])
                if actual_width > 20:
                    if self.listview.auto_width_enabled:
                        self.listview._fit_columns_auto_width(
                            self.listview._available_width())
                        self.listview._last_available_width = self.listview._available_width()
                    else:
                        self._fit_name_column_to_available_width(actual_width)
                self.listview._text_fit_cache.clear()
                self.listview._resize_layout_pending = True
                self.listview._layout_all()
            except Exception:
                pass

        apply_layout()
        try:
            dpg.set_frame_callback(dpg.get_frame_count() + 1, apply_layout)
        except Exception:
            pass

    def _create_listview(self):
        menu = [
            {"id": action or label, "label": label, "action": action,
             "icon": ResourceTextures.get(icon) if icon else None,
             "enabled": enabled, "separator": action is None}
            for label, action, icon, enabled in self.MENU
        ]
        # ODB actions in Job Viewer resolve the job's output file from the
        # scheduler/job metadata first. They never depend on the Server file
        # pane selection or its current directory.
        menu.insert(1, {
            "id": "job_check_odb_group",
            "label": "Check ODB",
            "icon": ResourceTextures.get("Check_File"),
            "children": [
                {
                    "id": "job_check_odb_quick",
                    "label": "Quick Check",
                    "action": "job_check_odb",
                    "icon": ResourceTextures.get("Check_File"),
                    "enabled": False,
                },
                {
                    "id": "job_extract_odb_data",
                    "label": "Extract Data",
                    "action": "job_extract_odb",
                    "icon": ResourceTextures.get("Details"),
                    "enabled": False,
                },
            ],
        })
        menu.insert(2, {
            "id": "job_plots",
            "label": "Plots",
            "action": "job_plots",
            "icon": ResourceTextures.get("JobViewer"),
            "enabled": False,
            "checkable": True,
            "checked": False,
        })
        listview = ExplorerListView(
            parent=self.body, items=[], columns=self.COLUMNS,
            width=-1, height=-1, show_status_bar=False,
            open_files_on_double_click=False, item_menu=menu,
            on_selection_change=lambda _items: None,
            on_item_menu_action=self._menu_action,
            on_context_menu_open=self._context_open,
            show_column_separators=True, single_selection=True,
            horizontal_scrollbar=False,
            auto_fit_column_key="job_name",
            auto_fit_min_width=self.NAME_MIN_WIDTH,
            preserve_column_widths_on_startup=True,
            theme=ListViewTheme.JOB_VIEWER,
            tag="jobs_list",
        )
        listview.set_metrics(row_height=23, header_height=26, cell_padding=6)
        return listview

    def _install_context_menu_fallback(self):
        """Guarantee Job Viewer right-click even if the global pointer poller
        is consumed by a splitter/dock interaction in the same frame.

        ExplorerListView keeps its normal global right-click path.  This direct
        body handler is only a fallback: it waits one frame and opens the menu
        only when that primary path did not already do so.
        """
        try:
            with dpg.item_handler_registry() as registry:
                dpg.add_item_clicked_handler(
                    button=dpg.mvMouseButton_Right,
                    callback=self._context_body_right_clicked,
                )
            dpg.bind_item_handler_registry(self.listview.body_window, registry)
            body_anchor = getattr(self.listview, "body_tooltip_anchor", None)
            if body_anchor and dpg.does_item_exist(body_anchor):
                dpg.bind_item_handler_registry(body_anchor, registry)
            self._context_fallback_registry = registry
        except Exception:
            self._context_fallback_registry = None

    def _context_body_right_clicked(self, sender=None, app_data=None, user_data=None):
        def ensure_menu(*_args, **_kwargs):
            if not dpg.does_item_exist(self.container):
                return
            try:
                if self.listview._context_menu_is_visible():
                    return
            except Exception:
                pass
            try:
                self.listview._on_right_click()
            except Exception:
                pass

        try:
            dpg.set_frame_callback(dpg.get_frame_count() + 1, ensure_menu)
        except Exception:
            ensure_menu()

    def _menu_action(self, action, _items):
        callback = self.callbacks.get("job_command")
        if callback:
            callback(str(action))

    def set_plots_open_job(self, job_id=None):
        """Mark the one Job whose Plot panel is currently open."""
        if job_id is None:
            self._plots_open_job_id = None
            self._plots_open_job_ids.clear()
            return
        key = str(job_id)
        self._plots_open_job_id = key
        self._plots_open_job_ids = {key}

    def set_plots_open_jobs(self, job_ids, active_job_id=None):
        """Synchronize the single Plot checkmark used by Job Viewer."""
        keys = [str(job_id) for job_id in (job_ids or ()) if str(job_id)]
        active = None if active_job_id is None else str(active_job_id)
        key = active if active in keys else (keys[0] if keys else None)
        self._plots_open_job_id = key
        self._plots_open_job_ids = ({key} if key is not None else set())

    def remove_plots_open_job(self, job_id):
        key = str(job_id)
        self._plots_open_job_ids.discard(key)
        if self._plots_open_job_id == key:
            self._plots_open_job_id = next(iter(self._plots_open_job_ids), None)

    def _context_open(self, items):
        owner = str(items[0].data.get("user", "")) if items else ""
        selected_job_id = str(items[0].data.get("job_id", "")) if items else ""
        self.listview.set_context_menu_item_checked(
            "job_plots",
            bool(selected_job_id) and selected_job_id in self._plots_open_job_ids,
        )
        current_user = str(self.callbacks.get("job_user", lambda: "")())
        can_modify = bool(owner) and owner.casefold() == current_user.casefold()
        protected = {
            "check", "edit", "cancel", "open_temp", "hot_download",
            "job_check_odb", "job_extract_odb", "job_plots",
        }
        # Keep every command visible. Permission-sensitive commands retain
        # their normal row geometry and are simply disabled/muted when the
        # selected job belongs to another user.
        for action in protected:
            self.listview.set_context_menu_item_enabled(action, can_modify)

    def clear(self):
        self.listview.set_items([])

    def clear_selection(self):
        self.listview.clear_selection()

    def selected_values(self):
        selected = self.listview.get_selected()
        if not selected:
            return None
        data = selected[0].data
        return (
            data["job_id"], data["job_name"], data["user"],
            data["tokens"], data["status"], data["elapsed"],
        )

    def display(self, jobs: Iterable[Any]):
        selected_ids = {
            item.data.get("job_id") for item in self.listview.get_selected()
        }
        items = []
        for job in jobs:
            values = (
                getattr(job, "job_id", ""), getattr(job, "name", ""),
                getattr(job, "user", ""), getattr(job, "tokens", ""),
                getattr(job, "status", ""), getattr(job, "elapsed", ""),
            )
            status = str(values[4]).strip().casefold()
            fill = ((205, 244, 213, 255) if status in ("r", "running") else
                    (255, 237, 213, 255) if status in ("q", "queued") else None)
            items.append(ListViewItem(
                name=str(values[0]), path=str(values[0]), is_dir=False,
                item_type="Job", data={
                    "job_id": str(values[0]), "job_name": str(values[1]),
                    "user": str(values[2]), "tokens": str(values[3]),
                    "status": str(values[4]), "elapsed": str(values[5]),
                    "row_fill": fill,
                },
            ))
        self.listview.set_items(items)
        selected = [
            index for index, item in enumerate(self.listview.items)
            if item.data.get("job_id") in selected_ids
        ]
        if selected:
            self.listview.select_indices(selected)