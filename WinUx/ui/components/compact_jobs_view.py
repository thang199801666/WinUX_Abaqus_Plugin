from __future__ import annotations

from typing import Any, Iterable

from DearUIQt.widgets import QFrame, QRetainedItem
from DearUIQt.backends import dpg
from DearUIQt.core import Qt, QItemInputBinding
from DearUIQt.runtime import QGuiRuntime
from DearUIQt.input_gate import popup_input_is_blocked, popup_input_active

from .explorer.list_view import ExplorerListView, ListViewItem
from .explorer.themes import ListViewTheme
from .jobs_view import JobsView


class CompactJobsView:
    """Small job-only surface used by WinUx compact/top-most mode.

    Only Job ID, name and scheduler status are displayed. Full metadata is
    retained for the same context commands and permissions as Job Viewer.
    """

    ROW_HEIGHT = 25
    HEADER_HEIGHT = 27
    VISIBLE_ROWS = 4
    HEIGHT = HEADER_HEIGHT + ROW_HEIGHT * VISIBLE_ROWS + 3
    MIN_WIDTH = 260
    DRAG_WIDTH = 76
    BUTTON_SIZE = 22
    CONTROL_INSET = 6
    RESIZE_GRIP = BUTTON_SIZE + CONTROL_INSET
    CONTROL_WIDTH = BUTTON_SIZE + 2 * CONTROL_INSET

    COLUMNS = (
        {"key": "job_id", "label": "Job ID", "weight": 0.8,
         "align": "center", "visible": True},
        {"key": "job_name", "label": "Name", "weight": 1.6,
         "align": "left", "visible": True},
        {"key": "status", "label": "Status", "weight": 0.7,
         "align": "center", "visible": True},
    )

    def __init__(self, parent, on_restore, on_close=None, jobs_view=None):
        self._jobs_view = jobs_view
        self.callbacks = jobs_view.callbacks if jobs_view is not None else {}
        self._root = QFrame(
            parent=parent, pos=(0, 0), width=-1, height=-1,
            frame_shape=QFrame.NoFrame, no_scrollbar=True,
            no_scroll_with_mouse=True,
        )
        self.root = self._root.tag
        self._body = QFrame(
            parent=self._root, pos=(0, 0), width=-1,
            height=-1, frame_shape=QFrame.NoFrame,
            no_scrollbar=True, no_scroll_with_mouse=True,
        )
        self.body = self._body.tag
        self.listview = ExplorerListView(
            parent=self._body, items=[], columns=self.COLUMNS,
            width=-1, height=-1, show_status_bar=False,
            open_files_on_double_click=False, item_menu=JobsView.job_context_menu(),
            on_selection_change=lambda _items: None,
            on_item_menu_action=self._menu_action,
            on_context_menu_open=self._context_open,
            show_column_separators=True, single_selection=True,
            horizontal_scrollbar=False, vertical_scrollbar=False,
            auto_fit_column_key="job_name", auto_fit_min_width=80,
            preserve_column_widths_on_startup=False,
            theme=ListViewTheme.JOB_VIEWER,
            tag="compact_jobs_list",
        )
        self.listview.set_metrics(
            row_height=self.ROW_HEIGHT, header_height=self.HEADER_HEIGHT, cell_padding=6)
        self._gui_runtime = QGuiRuntime()
        self._context_bindings = []
        for target in (self.listview.body_window, self.listview.body_tooltip_anchor):
            binding = QItemInputBinding(QRetainedItem(target), parent=self._root)
            binding.onClick(Qt.RightButton, self._context_body_right_clicked).activate()
            self._context_bindings.append(binding)
        # A final child window paints above the list, within the main HWND.
        # The bundled native-window renderer does not paint viewport drawlists
        # here, even when their draw commands report show=True.
        # Header controls must never cover job cells, including the first row.
        self._controls = {
            action: QFrame(
                parent=self._root, pos=(x, 0), width=self.CONTROL_WIDTH,
                height=self.HEADER_HEIGHT,
                frame_shape=QFrame.NoFrame, show=False,
                no_scrollbar=True, no_scroll_with_mouse=True,
            )
            for action, x in (("restore", 0), ("close", 412),
                              ("move", 192), ("resize", 434))
        }
        with dpg.theme() as self._controls_theme:
            with dpg.theme_component(dpg.mvAll):
                dpg.add_theme_style(dpg.mvStyleVar_WindowPadding, 0, 0)
                dpg.add_theme_style(dpg.mvStyleVar_ChildBorderSize, 0)
                dpg.add_theme_color(dpg.mvThemeCol_ChildBg, (0, 0, 0, 0))
        for control in self._controls.values():
            dpg.bind_item_theme(control.tag, self._controls_theme)
        self._on_restore = on_restore
        self._on_close = on_close
        self._hovered = False
        self._restore_layer = None
        self._control_layers = {}
        self._restore_handler_registry = None
        self._control_items = []
        self._control_backgrounds = {}
        self._control_boxes = {}
        self._control_width = 460
        self._build_restore_overlay()

    def _build_restore_overlay(self):
        try:
            for action, control in self._controls.items():
                tag = "compact_jobs_{}_draw_layer".format(action)
                if dpg.does_item_exist(tag):
                    dpg.delete_item(tag)
                self._control_layers[action] = dpg.add_drawlist(
                    width=self.DRAG_WIDTH if action == "move" else 48,
                    height=48, parent=control.tag, tag=tag)
            self._restore_layer = self._control_layers["restore"]
            self._layout_controls()
            registry_tag = "compact_jobs_restore_mouse_handlers"
            if dpg.does_item_exist(registry_tag):
                dpg.delete_item(registry_tag)
            with dpg.handler_registry(tag=registry_tag) as registry:
                dpg.add_mouse_click_handler(
                    button=dpg.mvMouseButton_Left, callback=self._on_control_press)
                dpg.add_mouse_release_handler(
                    button=dpg.mvMouseButton_Left, callback=self._on_control_click)
            self._restore_handler_registry = registry
        except Exception:
            self._restore_layer = None
            self._restore_handler_registry = None

    def _layout_controls(self):
        """Draw header-only controls and the bottom-right resize grip."""
        for item in self._control_items:
            if dpg.does_item_exist(item):
                dpg.delete_item(item)
        self._control_items = []
        self._control_backgrounds = {}
        button_y = (self.HEADER_HEIGHT - self.BUTTON_SIZE) / 2
        self._control_boxes = {
            "restore": (self.CONTROL_INSET, button_y, self.BUTTON_SIZE, self.BUTTON_SIZE),
            "close": (self.CONTROL_INSET, button_y, self.BUTTON_SIZE, self.BUTTON_SIZE),
            "move": (0, button_y, self.DRAG_WIDTH, self.BUTTON_SIZE),
            "resize": (0, 0, self.BUTTON_SIZE, self.BUTTON_SIZE),
        }
        for action, (x, y, w, h) in self._control_boxes.items():
            layer = self._control_layers[action]
            cx, cy = x + w / 2, y + h / 2
            background = dpg.draw_rectangle(
                (x, y), (x + w, y + h), parent=layer,
                color=(255, 255, 255, 45), fill=(34, 34, 38, 255),
                rounding=h / 2, thickness=1, show=self._hovered)
            self._control_items.append(background)
            self._control_backgrounds[action] = background
            if action == "move":
                for dx in (-10, 0, 10):
                    for dy in (-3.5, 3.5):
                        self._control_items.append(dpg.draw_circle(
                            (cx + dx, cy + dy), 1.6, parent=layer,
                            color=(255, 255, 255, 255), fill=(255, 255, 255, 255),
                            show=self._hovered))
                continue
            if action == "resize":
                segments = [((-5, 2), (2, -5)), ((-2, 5), (5, -2))]
            # Vector icons stay crisp without relying on an icon font.
            elif action == "close":
                segments = [((-5, -5), (5, 5)), ((5, -5), (-5, 5))]
            else:
                # Expand corners: return to the full application.
                segments = [
                    ((-5, -1), (-5, -5)), ((-5, -5), (-1, -5)),
                    ((1, -5), (5, -5)), ((5, -5), (5, -1)),
                    ((5, 1), (5, 5)), ((5, 5), (1, 5)),
                    ((-1, 5), (-5, 5)), ((-5, 5), (-5, 1)),
                ]
            for start, end in segments:
                self._control_items.append(dpg.draw_line(
                    (cx + start[0], cy + start[1]),
                    (cx + end[0], cy + end[1]), parent=layer,
                    color=(255, 255, 255, 255), thickness=1.8,
                    show=self._hovered))

    def _control_hit(self):
        if not self._hovered:
            return None
        try:
            # Pointer and rect_min share renderer-global coordinates (desktop
            # coordinates when native multi-window rendering is enabled).
            mx, my = map(float, dpg.get_mouse_pos(local=False))
            for action, (x, y, w, h) in self._control_boxes.items():
                ox, oy = dpg.get_item_rect_min(self._control_layers[action])
                if x <= mx - ox < x + w and y <= my - oy < y + h:
                    return action
        except Exception:
            return None
        return None

    def _on_control_press(self, sender=None, app_data=None, user_data=None):
        self._pressed_control = None if popup_input_is_blocked(self) else self._control_hit()

    def _on_control_click(self, sender=None, app_data=None, user_data=None):
        # Global DPG click handlers also see clicks delivered to a native menu
        # above PiP. Never let Restore/Close activate through that popup.
        pressed = getattr(self, "_pressed_control", None)
        self._pressed_control = None
        if popup_input_is_blocked(self):
            return
        action = self._control_hit()
        if action != pressed:
            return
        callback = {"restore": self._on_restore, "close": self._on_close}.get(action)
        if callable(callback):
            self.set_hovered(False)
            callback()

    def is_restore_target(self, x, y):
        rx, ry, width, height = self._control_boxes["restore"]
        return rx <= x < rx + width and ry <= y < ry + height

    def _set_restore_visible(self, visible):
        visible = bool(visible)
        for control in self._controls.values():
            control.setVisible(visible)
        for item in self._control_items:
            if item and dpg.does_item_exist(item):
                try:
                    dpg.configure_item(item, show=visible)
                except Exception:
                    pass

    def resize(self, width, height):
        width = max(self.MIN_WIDTH, int(width))
        height = max(self.HEIGHT, int(height))
        self._root.resize(width, height)
        QRetainedItem(self._body.tag).configure(
            pos=(0, 0), width=width, height=height)
        self.listview.resize(width=-1, height=-1)
        if self._restore_layer is not None:
            self._control_width = width
            QRetainedItem(self._controls["close"].tag).configure(
                pos=(width - self.CONTROL_WIDTH, 0))
            QRetainedItem(self._controls["move"].tag).configure(
                pos=((width - self.DRAG_WIDTH) // 2, 0),
                width=self.DRAG_WIDTH, height=self.HEADER_HEIGHT)
            QRetainedItem(self._controls["resize"].tag).configure(
                pos=(width - self.RESIZE_GRIP, height - self.RESIZE_GRIP),
                width=self.RESIZE_GRIP, height=self.RESIZE_GRIP)
        try:
            self.listview._fit_columns_auto_width(self.listview._available_width())
            self.listview._resize_layout_pending = True
        except Exception:
            pass

    @classmethod
    def native_hit_test(cls, x, y, width, height):
        """Win32 non-client targets; job cells remain normal client input."""
        if not (0 <= x < width and 0 <= y < height):
            return None
        border = 6
        left, right = x < border, x >= width - border
        top, bottom = y < border, y >= height - border
        if left and top:
            return 13  # HTTOPLEFT
        if right and top:
            return 14  # HTTOPRIGHT
        if left and bottom:
            return 16  # HTBOTTOMLEFT
        if (right and bottom or
                x >= width - cls.RESIZE_GRIP and y >= height - cls.RESIZE_GRIP):
            return 17  # HTBOTTOMRIGHT
        if left:
            return 10  # HTLEFT
        if right:
            return 11  # HTRIGHT
        if top:
            return 12  # HTTOP
        if bottom:
            return 15  # HTBOTTOM
        drag_left = (width - cls.DRAG_WIDTH) // 2
        if drag_left <= x < drag_left + cls.DRAG_WIDTH and 3 <= y < 24:
            return 2  # HTCAPTION: let Windows handle dragging, including DPI.
        return None

    def set_hovered(self, hovered):
        hovered = bool(hovered) and not popup_input_active()
        changed = hovered != self._hovered
        self._hovered = hovered
        if changed:
            self._set_restore_visible(hovered)
        active = self._control_hit()
        for action, item in self._control_backgrounds.items():
            if item and dpg.does_item_exist(item):
                fill = ((196, 43, 48, 245) if action == "close"
                        else (70, 70, 78, 255)) if action == active else (34, 34, 38, 255)
                dpg.configure_item(item, fill=fill)

    def display(self, jobs: Iterable[Any]):
        selected_ids = {
            item.data.get("job_id") for item in self.listview.get_selected()
        }
        items = []
        for job in jobs or ():
            job_id = str(getattr(job, "job_id", ""))
            name = str(getattr(job, "name", ""))
            status = str(getattr(job, "status", ""))
            normalized = status.strip().casefold()
            fill = ((205, 244, 213, 255)
                    if normalized in ("r", "running") else
                    (255, 237, 213, 255)
                    if normalized in ("q", "queued") else None)
            items.append(ListViewItem(
                name=job_id, path=job_id, is_dir=False, item_type="Job",
                data={
                    "job_id": job_id,
                    "job_name": name,
                    "status": status,
                    "user": str(getattr(job, "user", "")),
                    "tokens": str(getattr(job, "tokens", "")),
                    "elapsed": str(getattr(job, "elapsed", "")),
                    "row_fill": fill,
                },
            ))
        self.listview.set_items(items)
        selected = [index for index, item in enumerate(items)
                    if item.data.get("job_id") in selected_ids]
        if selected:
            self.listview.select_indices(selected)
        self.listview.refresh_row_visuals()

    def _context_open(self, items):
        self._plots_open_job_ids = (
            self._jobs_view._plots_open_job_ids if self._jobs_view is not None else set())
        JobsView._context_open(self, items)

    def _context_body_right_clicked(self, *_args):
        def ensure_menu(*_args):
            if (self._root.exists() and self._root.isVisible()
                    and not self.listview._context_menu_is_visible()):
                self.listview._on_right_click()
        self._gui_runtime.invokeNextFrame(ensure_menu)

    def _menu_action(self, action, items):
        JobsView._menu_action(self, action, items)

    def selected_values(self):
        return JobsView.selected_values(self)

    def show(self):
        self._root.show()

    def hide(self):
        self._pressed_control = None
        self.set_hovered(False)
        self.listview._hide_context_menus()
        self.listview.cancel_pointer_gesture(suppress_release=True)
        self._root.hide()

    def destroy(self):
        self._set_restore_visible(False)
        try:
            self.listview.destroy()
        except Exception:
            pass
        for item in (self._restore_handler_registry, *self._control_layers.values()):
            if item and dpg.does_item_exist(item):
                try:
                    dpg.delete_item(item)
                except Exception:
                    pass
        self._restore_handler_registry = None
        self._restore_layer = None
        try:
            self._root.delete()
        except Exception:
            pass
        if dpg.does_item_exist(self._controls_theme):
            dpg.delete_item(self._controls_theme)
