"""Dear PyGui realtime History Output dock panel for Job Viewer."""

from __future__ import annotations

import time
from typing import Any, Dict, Iterable, Optional

import dearpygui.dearpygui as dpg

from ..services.odb_history_live import default_history_ids, merge_series_delta
from .dock_widget import DockWidget
from .interaction_gate import acquire_pointer_input, release_pointer_input
from .qt_style import QtFusionPalette
from ..widgets.imgui_qt_style import (
    checkbox_theme, command_button_theme, line_edit_theme, panel_surface_theme,
    tool_bar_theme,
)
from .tooltip import tooltip_theme


class JobPlotsWindow:
    """Embedded Job Viewer plot panel backed by Dear PyGui/ImPlot.

    The historical class name is retained for compatibility.  The component
    can live beside Job Viewer in the lower split workspace or be torn off as
    a floating Dear PyGui tool window without restarting the ODB monitor.
    """

    # Keep enough chart canvas visible when Job Viewer and Plots share a
    # 50/50 lower row, while still leaving room for long History Output names.
    LIST_WIDTH = 280
    MIN_LIST_WIDTH = 220
    MIN_PLOT_WIDTH = 340
    TOOLBAR_HEIGHT = 31
    OUTER_MARGIN = 8
    TOOLBAR_BODY_GAP = 5
    PANEL_GAP = 8
    HISTORY_ROW_GAP = 3
    INNER_PAD = 8
    BUTTON_ROW_GAP = 4
    CONTROL_SECTION_GAP = 10
    COUNT_RIGHT_PAD = 4
    SERIES_COLORS = (
        (0, 191, 255, 255),
        (255, 179, 0, 255),
        (76, 217, 100, 255),
        (255, 99, 132, 255),
        (178, 102, 255, 255),
        (0, 220, 190, 255),
        (255, 140, 66, 255),
        (120, 170, 255, 255),
    )

    def __init__(
            self, parent, job_id: str, job_name: str,
            on_selection_change=None, on_close=None, on_dock_change=None,
            on_dock_area_change=None, dock_area="right"):
        self.parent = parent
        self.job_id = str(job_id)
        self.job_name = str(job_name or "")
        self.on_selection_change = on_selection_change
        self.on_close = on_close
        self.on_dock_change = on_dock_change
        self.on_dock_area_change = on_dock_area_change
        self.dock_mode = "docked"
        self.dock_area = str(dock_area or "right").lower()
        self._drag_undock_requested = False
        self._drag_registry = None
        self._pointer_capture_owner = object()
        self.catalog: Dict[str, Dict[str, Any]] = {}
        self.selected_ids = set()
        self._selection_initialized = False
        self._checkboxes: Dict[str, Any] = {}
        self._series_tags: Dict[str, Any] = {}
        self._series_themes: Dict[str, Any] = {}
        self._series_points: Dict[str, list] = {}
        self._closed = False

        safe_job = "".join(ch if ch.isalnum() else "_" for ch in self.job_id)
        self.tag = "job_plots_window_{}".format(safe_job)
        if dpg.does_item_exist(self.tag):
            # A previously closed DPG window can remain registered but hidden
            # for the rest of the frame. View-level reuse handles live windows;
            # anything left here is stale and must not steal the new instance.
            try:
                dpg.delete_item(self.tag)
            except Exception:
                pass

        self._build_themes()
        label = "Plots - {}{}".format(
            self.job_name or "Job",
            " ({})".format(self.job_id) if self.job_id else "",
        )
        self.label = label
        self.dock = DockWidget(
            self.parent,
            title=label,
            tag=self.tag,
            on_float_change=self._dock_float_requested,
            on_close=self._handle_close,
            dock_area=self.dock_area,
            on_dock_area_change=self._dock_area_requested,
        )
        self.root = self.dock.root
        self.drag_handle = self.dock.drag_handle

        # QDockWidget normally embeds an ordinary QWidget/QToolBar client. Use
        # a compact, persistent light toolbar that stays identical whether the
        # panel is docked or detached into a floating tool window.
        self.toolbar = dpg.add_child_window(
            parent=self.dock.content, width=-1, height=self.TOOLBAR_HEIGHT,
            border=False, no_scrollbar=True, no_scroll_with_mouse=True)
        self.status_text = dpg.add_text("Waiting for ODB...", parent=self.toolbar)
        self.fit_button = dpg.add_button(
            label="Fit", width=48, height=22, parent=self.toolbar,
            callback=self._fit_axes)

        with dpg.handler_registry() as self._drag_registry:
            dpg.add_mouse_drag_handler(
                button=dpg.mvMouseButton_Left, threshold=10.0,
                callback=self._on_header_drag)
            dpg.add_mouse_release_handler(
                button=dpg.mvMouseButton_Left,
                callback=self._on_header_drag_release)

        # The body is a flush two-pane client area, similar to a QWidget with a
        # horizontal QSplitter: history list on the left, plot canvas on right.
        self.body_panel = dpg.add_child_window(
            parent=self.dock.content, width=-1, height=-1, border=False,
            no_scrollbar=True, no_scroll_with_mouse=True)
        with dpg.group(parent=self.body_panel, horizontal=True) as self.body_group:
            with dpg.child_window(
                    width=self.LIST_WIDTH, height=-1, border=True,
                    horizontal_scrollbar=False) as self.list_panel:
                self.filter_input = dpg.add_input_text(
                    hint="Filter history outputs...",
                    width=-1,
                    height=24,
                    callback=self._filter_changed,
                )
                self.all_button = dpg.add_button(
                    label="All", width=52, height=22,
                    callback=lambda: self._set_all(True))
                self.none_button = dpg.add_button(
                    label="None", width=52, height=22,
                    callback=lambda: self._set_all(False))
                self.count_text = dpg.add_text("0 outputs")
                self.header_separator = dpg.add_drawlist(width=1, height=1)
                self._header_separator_line = dpg.draw_line(
                    (0, 0), (1, 0), color=QtFusionPalette.BORDER,
                    thickness=1.0, parent=self.header_separator)
                self.history_container = dpg.add_child_window(
                    width=-1, height=-1, border=False,
                    no_scrollbar=False, horizontal_scrollbar=False)

            self.body_gap = dpg.add_spacer(width=self.PANEL_GAP)

            with dpg.child_window(
                    width=-1, height=-1, border=False,
                    no_scrollbar=True, no_scroll_with_mouse=True) as self.plot_panel:
                with dpg.plot(
                        label="History Output",
                        width=-1,
                        height=-1,
                        no_title=False,
                        no_mouse_pos=False,
                        crosshairs=False,
                        query=False,
                        tag="{}_plot".format(self.tag)) as self.plot:
                    dpg.add_plot_legend(
                        location=dpg.mvPlot_Location_NorthWest,
                        horizontal=False,
                        outside=False,
                    )
                    self.x_axis = dpg.add_plot_axis(
                        dpg.mvXAxis, label="Time")
                    self.y_axis = dpg.add_plot_axis(
                        dpg.mvYAxis, label="Value")

        dpg.bind_item_theme(self.toolbar, tool_bar_theme(dpg))
        dpg.bind_item_theme(self.body_panel, self._body_theme)
        dpg.bind_item_theme(self.body_group, self._body_theme)
        dpg.bind_item_theme(self.plot_panel, self._panel_theme)
        dpg.bind_item_theme(self.plot, self._plot_theme)
        dpg.bind_item_theme(self.list_panel, self._panel_theme)
        dpg.bind_item_theme(self.filter_input, line_edit_theme(dpg))
        for button in (self.fit_button, self.all_button, self.none_button):
            dpg.bind_item_theme(button, command_button_theme(dpg))
        self._history_rows: Dict[str, Any] = {}
        self._history_labels: Dict[str, Any] = {}
        self.sync_layout()
        try:
            dpg.focus_item(self.tag)
        except Exception:
            pass

    def _build_themes(self):
        with dpg.theme() as self._plot_theme:
            with dpg.theme_component(dpg.mvPlot):
                dpg.add_theme_color(
                    dpg.mvPlotCol_PlotBg, (255, 255, 255, 255),
                    category=dpg.mvThemeCat_Plots)
                dpg.add_theme_color(
                    dpg.mvPlotCol_FrameBg, (255, 255, 255, 255),
                    category=dpg.mvThemeCat_Plots)
                dpg.add_theme_color(
                    dpg.mvPlotCol_LegendBg, (255, 255, 255, 240),
                    category=dpg.mvThemeCat_Plots)
                dpg.add_theme_color(
                    dpg.mvPlotCol_LegendBorder, (182, 182, 182, 255),
                    category=dpg.mvThemeCat_Plots)
                for color_role in (
                        dpg.mvPlotCol_TitleText,
                        dpg.mvPlotCol_LegendText,
                        dpg.mvPlotCol_InlayText,
                        dpg.mvPlotCol_AxisText):
                    dpg.add_theme_color(
                        color_role, (20, 20, 20, 255),
                        category=dpg.mvThemeCat_Plots)
                dpg.add_theme_color(
                    dpg.mvPlotCol_AxisGrid, (216, 216, 216, 180),
                    category=dpg.mvThemeCat_Plots)
                dpg.add_theme_color(
                    dpg.mvPlotCol_AxisBg, (250, 250, 250, 255),
                    category=dpg.mvThemeCat_Plots)

        # Body/layout remains a zero-spacing container, while the visible list
        # and plot panes use the same QFrame-like surface contract as other
        # WinUx tool panels.
        with dpg.theme() as self._body_theme:
            with dpg.theme_component(dpg.mvChildWindow):
                dpg.add_theme_color(dpg.mvThemeCol_ChildBg, QtFusionPalette.BASE)
                dpg.add_theme_style(dpg.mvStyleVar_ChildBorderSize, 0)
                dpg.add_theme_style(dpg.mvStyleVar_WindowPadding, 0, 0)
                dpg.add_theme_style(dpg.mvStyleVar_ItemSpacing, 0, 0)
            with dpg.theme_component(dpg.mvGroup):
                dpg.add_theme_style(dpg.mvStyleVar_ItemSpacing, 0, 0)

        self._panel_theme = panel_surface_theme(
            dpg, bordered=True, compact=True)
        self._checkbox_theme = checkbox_theme(dpg)

        with dpg.theme() as self._history_label_theme:
            with dpg.theme_component(dpg.mvText):
                dpg.add_theme_color(
                    dpg.mvThemeCol_Text, (25, 25, 25, 255))

    def set_dock_mode(self, mode):
        mode = "floating" if str(mode).lower() == "floating" else "docked"
        self.dock_mode = mode
        self._drag_undock_requested = False
        if hasattr(self, "dock"):
            self.dock.set_floating(mode == "floating")
        self._sync_client_layout()

    def set_dock_area(self, area):
        area = str(area or "right").lower()
        if area not in ("left", "right", "top", "bottom"):
            area = "right"
        self.dock_area = area
        if hasattr(self, "dock"):
            self.dock.set_dock_area(area)

    def _dock_area_requested(self, area):
        callback = self.on_dock_area_change
        if callable(callback):
            callback(self.job_id, str(area or "right").lower())

    def _dock_float_requested(self, floating):
        desired = "floating" if bool(floating) else "docked"
        self._request_dock_mode(desired)

    def resize(self, width=None, height=None):
        if hasattr(self, "dock"):
            self.dock.sync_layout(width=width, height=height, force=True)
        self._sync_client_layout()

    def sync_layout(self):
        if hasattr(self, "dock"):
            self.dock.sync_layout()
        self._sync_client_layout()

    @staticmethod
    def _safe_configure(item, **kwargs):
        """Best-effort DPG reconfiguration across bundled runtime versions.

        Some older Dear PyGui builds raise ``SystemError`` rather than a normal
        Python exception when a config key is unsupported for a specific item
        type.  Layout synchronization must never escape into the UI callback
        loop because that creates repeated WinUX error dialogs every frame.
        """
        if item is None:
            return False
        try:
            if not dpg.does_item_exist(item):
                return False
            dpg.configure_item(item, **kwargs)
            return True
        except BaseException:
            return False

    def _sync_client_layout(self):
        if not hasattr(self, "dock") or not dpg.does_item_exist(self.dock.content):
            return
        try:
            content_w, content_h = map(int, dpg.get_item_rect_size(self.dock.content))
        except Exception:
            return
        if content_w <= 1 or content_h <= 1:
            return

        toolbar_h = self.TOOLBAR_HEIGHT
        margin = self.OUTER_MARGIN
        inner_pad = self.INNER_PAD
        body_y = toolbar_h + self.TOOLBAR_BODY_GAP
        body_w = max(1, content_w - 2 * margin)
        body_h = max(1, content_h - body_y - margin)
        usable_w = max(1, body_w - self.PANEL_GAP)

        list_width = min(
            self.LIST_WIDTH,
            max(self.MIN_LIST_WIDTH, usable_w // 3),
        )
        if usable_w - list_width < self.MIN_PLOT_WIDTH:
            list_width = max(180, usable_w - self.MIN_PLOT_WIDTH)
        plot_width = max(1, usable_w - list_width)

        try:
            status_size = dpg.get_text_size(dpg.get_value(self.status_text) or "")
            count_size = dpg.get_text_size(dpg.get_value(self.count_text) or "")
        except Exception:
            status_size = (7 * len(str(dpg.get_value(self.status_text) or "")), 14)
            count_size = (7 * len(str(dpg.get_value(self.count_text) or "")), 14)

        fit_w = 48
        fit_h = 22
        toolbar_w = max(1, content_w)
        fit_x = max(inner_pad, toolbar_w - inner_pad - fit_w)
        fit_y = max(3, (toolbar_h - fit_h) // 2)
        status_y = max(0, (toolbar_h - int(status_size[1])) // 2)

        header_y = inner_pad
        button_row_y = header_y + 24 + 8
        history_y = button_row_y + 22 + 8
        history_h = max(1, body_h - history_y - inner_pad)
        count_x = max(
            inner_pad + 52 + self.BUTTON_ROW_GAP + 52 + self.CONTROL_SECTION_GAP,
            max(inner_pad, list_width - inner_pad - int(count_size[0]) - self.COUNT_RIGHT_PAD),
        )

        self._safe_configure(
            self.toolbar, pos=(0, 0), width=toolbar_w,
            height=toolbar_h)
        self._safe_configure(self.status_text, pos=(inner_pad, status_y))
        self._safe_configure(
            self.fit_button, pos=(fit_x, fit_y), width=fit_w, height=fit_h)

        self._safe_configure(
            self.body_panel, pos=(margin, body_y),
            width=body_w, height=body_h)
        self._safe_configure(
            self.list_panel, width=max(180, list_width), height=body_h)
        self._safe_configure(self.body_gap, width=self.PANEL_GAP)
        self._safe_configure(
            self.plot_panel, width=plot_width, height=body_h)

        filter_w = max(80, list_width - 2 * inner_pad)
        self._safe_configure(
            self.filter_input, pos=(inner_pad, header_y),
            width=filter_w, height=24)
        self._safe_configure(
            self.all_button, pos=(inner_pad, button_row_y),
            width=52, height=22)
        self._safe_configure(
            self.none_button,
            pos=(inner_pad + 52 + self.BUTTON_ROW_GAP, button_row_y),
            width=52, height=22)
        self._safe_configure(self.count_text, pos=(count_x, button_row_y + 3))
        self._safe_configure(
            self.header_separator, pos=(inner_pad, history_y - 6),
            width=filter_w, height=1)
        self._safe_configure(
            self._header_separator_line,
            p1=(0, 0), p2=(max(1, filter_w), 0))
        self._safe_configure(
            self.history_container, pos=(inner_pad, history_y),
            width=filter_w, height=history_h)

    def _request_dock_mode(self, mode, pointer_pos=None, drag_anchor=None):
        callback = self.on_dock_change
        if callable(callback):
            callback(self.job_id, mode, pointer_pos, drag_anchor)

    def _toggle_dock(self, sender=None, app_data=None, user_data=None):
        desired = "docked" if self.dock_mode == "floating" else "floating"
        self._request_dock_mode(desired)

    def begin_pointer_capture(self):
        """Reserve global pointer input for a dock/floating-window drag."""
        return acquire_pointer_input(self._pointer_capture_owner)

    def end_pointer_capture(self):
        return release_pointer_input(self._pointer_capture_owner)

    def _on_header_drag(self, sender=None, app_data=None, user_data=None):
        if (self.dock_mode != "docked" or self._drag_undock_requested
                or not getattr(self.dock, "movable", True)):
            return
        try:
            active = dpg.is_item_active(self.drag_handle)
        except Exception:
            active = False
        if not active:
            return
        # From this point until physical mouse-up the dock drag exclusively
        # owns pointer input. This survives reparenting/hiding the embedded
        # title bar and prevents Explorer rubber-band/item-drag actions below.
        self.begin_pointer_capture()
        self._drag_undock_requested = True
        try:
            pointer = tuple(map(float, dpg.get_mouse_pos(local=False)))
        except Exception:
            pointer = None
        drag_anchor = None
        if pointer is not None:
            try:
                hx, hy = map(float, dpg.get_item_rect_min(self.drag_handle))
                drag_anchor = (
                    max(0.0, pointer[0] - hx),
                    max(0.0, pointer[1] - hy),
                )
            except Exception:
                drag_anchor = None
        self._request_dock_mode("floating", pointer, drag_anchor)

    def _on_header_drag_release(self, sender=None, app_data=None, user_data=None):
        self._drag_undock_requested = False
        self.end_pointer_capture()

    def exists(self):
        return (not self._closed and dpg.does_item_exist(self.tag))

    def focus(self):
        if self.exists():
            try:
                dpg.configure_item(self.tag, show=True)
                dpg.focus_item(self.plot if dpg.does_item_exist(self.plot) else self.tag)
            except Exception:
                pass

    def _cleanup_series_themes(self):
        for theme in list(self._series_themes.values()):
            if dpg.does_item_exist(theme):
                try:
                    dpg.delete_item(theme)
                except Exception:
                    pass
        self._series_themes.clear()

    def close(self, notify=False):
        self.end_pointer_capture()
        if self._closed:
            return
        self._closed = True
        self._cleanup_series_themes()
        if self._drag_registry and dpg.does_item_exist(self._drag_registry):
            try:
                dpg.delete_item(self._drag_registry)
            except Exception:
                pass
        if hasattr(self, "dock"):
            try:
                self.dock.close()
            except Exception:
                pass
        elif dpg.does_item_exist(self.tag):
            try:
                dpg.delete_item(self.tag)
            except Exception:
                pass
        if notify:
            callback = self.on_close
            if callable(callback):
                callback(self.job_id)

    def _handle_close(self, sender=None, app_data=None, user_data=None):
        self.close(notify=True)

    def set_waiting(self, message="Waiting for ODB..."):
        if self.exists():
            dpg.set_value(self.status_text, str(message))
            self._sync_client_layout()
            self._sync_client_layout()

    def set_status(self, message):
        if self.exists():
            dpg.set_value(self.status_text, str(message))
            self._sync_client_layout()

    def set_error(self, message):
        if self.exists():
            dpg.set_value(self.status_text, "Error: {}".format(message))
            self._sync_client_layout()

    def selection_items(self):
        return [
            dict(self.catalog[item_id])
            for item_id in self.catalog
            if item_id in self.selected_ids
        ]

    def set_catalog(self, payload):
        if not self.exists():
            return
        rows = list((payload or {}).get("historyOutputs") or [])
        previous_selected = set(self.selected_ids)
        self.catalog = {
            str(row.get("id") or ""): dict(row)
            for row in rows if str(row.get("id") or "")
        }
        if self._selection_initialized:
            self.selected_ids = {
                item_id for item_id in previous_selected
                if item_id in self.catalog
            }
        else:
            self.selected_ids = set(default_history_ids(rows))
            self._selection_initialized = True

        self._rebuild_history_list()
        self._remove_unselected_series()
        if dpg.does_item_exist(self.count_text):
            dpg.set_value(
                self.count_text,
                "{} outputs".format(len(self.catalog)))
            self._sync_client_layout()
        odb_name = str((payload or {}).get("odb") or "ODB")
        self.set_status("{} • live history catalog ready".format(odb_name))
        self._notify_selection_changed()

    def _rebuild_history_list(self):
        if not dpg.does_item_exist(self.history_container):
            return
        try:
            dpg.delete_item(self.history_container, children_only=True)
        except Exception:
            pass
        self._checkboxes.clear()
        self._history_rows.clear()
        self._history_labels.clear()
        for item_id, row in self.catalog.items():
            output = str(row.get("output") or "")
            display = str(row.get("displayName") or output or item_id)
            step = str(row.get("step") or "")
            region = str(row.get("historyRegion") or "")
            points = int(row.get("points") or 0)
            label = "{}  [{} pts]".format(display, points)
            row_group = dpg.add_group(parent=self.history_container)
            inline_group = dpg.add_group(parent=row_group, horizontal=True)
            checkbox = dpg.add_checkbox(
                label="",
                default_value=item_id in self.selected_ids,
                parent=inline_group,
                user_data=item_id,
                callback=self._checkbox_changed,
            )
            dpg.bind_item_theme(checkbox, self._checkbox_theme)
            dpg.add_spacer(parent=inline_group, width=7)
            label_text = dpg.add_text(label, parent=inline_group)
            dpg.bind_item_theme(label_text, self._history_label_theme)
            dpg.add_spacer(parent=row_group, height=self.HISTORY_ROW_GAP)
            self._checkboxes[item_id] = checkbox
            self._history_rows[item_id] = row_group
            self._history_labels[item_id] = label_text
            for tip_target in (checkbox, label_text):
                with dpg.tooltip(tip_target, delay=0.45, hide_on_activity=True) as tip:
                    dpg.add_text("Output: {}".format(output), wrap=420)
                    if step:
                        dpg.add_text("Step: {}".format(step), wrap=420)
                    if region:
                        dpg.add_text("Region: {}".format(region), wrap=420)
                dpg.bind_item_theme(tip, tooltip_theme())
        self._apply_filter()

    def _checkbox_changed(self, sender, app_data, user_data):
        item_id = str(user_data or "")
        if bool(app_data):
            self.selected_ids.add(item_id)
        else:
            self.selected_ids.discard(item_id)
            self._delete_series(item_id)
            self._series_points.pop(item_id, None)
        self._notify_selection_changed()

    def _set_all(self, checked):
        self.selected_ids = set(self.catalog) if checked else set()
        for item_id, checkbox in self._checkboxes.items():
            if dpg.does_item_exist(checkbox):
                dpg.set_value(checkbox, bool(checked))
        if not checked:
            for item_id in list(self._series_tags):
                self._delete_series(item_id)
            self._series_points.clear()
        self._notify_selection_changed()

    def _notify_selection_changed(self):
        callback = self.on_selection_change
        if callable(callback):
            callback(self.job_id, self.selection_items())

    def _filter_changed(self, sender=None, app_data=None, user_data=None):
        self._apply_filter()

    def _apply_filter(self):
        if not dpg.does_item_exist(self.filter_input):
            return
        needle = str(dpg.get_value(self.filter_input) or "").strip().casefold()
        for item_id, checkbox in self._checkboxes.items():
            row = self.catalog.get(item_id, {})
            haystack = " ".join((
                str(row.get("output") or ""),
                str(row.get("displayName") or ""),
                str(row.get("step") or ""),
                str(row.get("historyRegion") or ""),
            )).casefold()
            target = self._history_rows.get(item_id, checkbox)
            dpg.configure_item(target, show=(not needle or needle in haystack))

    def _series_theme(self, item_id):
        theme = self._series_themes.get(item_id)
        if theme is not None and dpg.does_item_exist(theme):
            return theme
        row = self.catalog.get(item_id, {})
        output = str(row.get("output") or "").strip().upper()
        if output == "ALLKE":
            color = (0, 191, 255, 255)
        elif output == "ALLIE":
            color = (255, 179, 0, 255)
        else:
            index = list(self.catalog).index(item_id) if item_id in self.catalog else 0
            color = self.SERIES_COLORS[index % len(self.SERIES_COLORS)]
        with dpg.theme() as theme:
            with dpg.theme_component(dpg.mvLineSeries):
                dpg.add_theme_color(
                    dpg.mvPlotCol_Line, color, category=dpg.mvThemeCat_Plots)
                dpg.add_theme_style(
                    dpg.mvPlotStyleVar_LineWeight, 1.6,
                    category=dpg.mvThemeCat_Plots)
        self._series_themes[item_id] = theme
        return theme

    def _delete_series(self, item_id):
        tag = self._series_tags.pop(item_id, None)
        if tag is not None and dpg.does_item_exist(tag):
            try:
                dpg.delete_item(tag)
            except Exception:
                pass

    def _remove_unselected_series(self):
        for item_id in list(self._series_tags):
            if item_id not in self.selected_ids or item_id not in self.catalog:
                self._delete_series(item_id)
                self._series_points.pop(item_id, None)

    def update_frame(self, payload):
        if not self.exists():
            return
        changed = False
        for row in (payload or {}).get("series") or []:
            item_id = str(row.get("id") or "")
            if not item_id or item_id not in self.selected_ids:
                continue
            points = merge_series_delta(self._series_points.get(item_id), row)
            self._series_points[item_id] = points
            catalog = self.catalog.get(item_id, {})
            label = str(
                row.get("displayName") or
                catalog.get("displayName") or
                catalog.get("output") or
                item_id)
            tag = self._series_tags.get(item_id)
            xs = [point[0] for point in points]
            ys = [point[1] for point in points]
            if tag is None or not dpg.does_item_exist(tag):
                tag = dpg.add_line_series(
                    xs, ys, label=label, parent=self.y_axis)
                self._series_tags[item_id] = tag
                dpg.bind_item_theme(tag, self._series_theme(item_id))
            else:
                try:
                    dpg.set_value(tag, [xs, ys])
                except Exception:
                    self._delete_series(item_id)
                    tag = dpg.add_line_series(
                        xs, ys, label=label, parent=self.y_axis)
                    self._series_tags[item_id] = tag
                    dpg.bind_item_theme(tag, self._series_theme(item_id))
            changed = True

        if changed:
            # Keep the chart viewport synchronized with every live ODB update.
            # The Auto fit checkbox was intentionally removed from the UI;
            # fitting is now the default Plot-panel behavior so newly appended
            # time/value ranges are always visible immediately.
            self._fit_axes()
            total_points = sum(
                len(self._series_points.get(item_id, ()))
                for item_id in self.selected_ids)
            stamp = time.strftime("%H:%M:%S")
            self.set_status(
                "Live • {} selected • {} points • updated {}".format(
                    len(self.selected_ids), total_points, stamp))

    def _fit_axes(self, sender=None, app_data=None, user_data=None):
        for axis in (self.x_axis, self.y_axis):
            if dpg.does_item_exist(axis):
                try:
                    dpg.fit_axis_data(axis)
                except Exception:
                    pass
