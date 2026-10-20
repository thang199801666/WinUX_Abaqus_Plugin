"""Dear PyGui realtime History Output dock panel for Job Viewer."""

from __future__ import annotations

import time
import re
from typing import Any, Dict, Iterable, Optional

from ...services.odb_history_live import default_history_ids, merge_series_delta
from ...services.reference_charts import (ReferenceChartLibrary, evaluate_reference_formula, resolve_reference_formula_ids)
from .. import QDockWidget as DockWidget
from DearUIQt.widgets import (
    QCheckBox, QLineEdit, QToolButton, QFrame, QLabel, QSpacer, QSeparator,
    QCanvas, QPlotWidget, QPlotAxis, QLineSeries, QRetainedItem, QMenu, QToolTip,
)
from DearUIQt.layouts import QHBoxLayout, QVBoxLayout
from DearUIQt.input_gate import (
    acquire_pointer_input, release_pointer_input,
    register_pointer_protected_item, unregister_pointer_protected_item,
)
from DearUIQt.gui import QtFusionPalette, QFontMetrics, QCursor
from DearUIQt.themes import (
    METRICS,
    panel_surface_theme, compact_layout_surface_theme, plot_surface_theme, text_theme,
    panel_header_theme, status_text_theme,
)
from DearUIQt.tooltip import tooltip_theme
from .toolbar import ResourceTextures, plot_panel_icon_theme


class JobPlotsWindow:
    """Embedded Job Viewer plot panel backed by Dear PyGui/ImPlot.

    The historical class name is retained for compatibility.  The component
    lives beside Job Viewer in the lower split workspace. When detached, its
    model is retained here while a process-isolated native dock client renders
    snapshots; detaching does not restart the ODB monitor.
    """

    # Keep enough chart canvas visible when Job Viewer and Plots share a
    # 50/50 lower row, while still leaving room for long History Output names.
    LIST_WIDTH = 280
    MIN_LIST_WIDTH = 220
    MIN_PLOT_WIDTH = 340
    TOOLBAR_HEIGHT = 38
    ICON_SIZE = 20
    ICON_BUTTON_WIDTH = 30
    ICON_GAP = 6
    HEADER_HEIGHT = 18
    OUTER_MARGIN = 6
    TOOLBAR_BODY_GAP = 6
    PANEL_GAP = 8
    HISTORY_ROW_GAP = 3
    INNER_PAD = 7
    BUTTON_ROW_GAP = 4
    CONTROL_SECTION_GAP = 10
    COUNT_RIGHT_PAD = 4
    BUTTON_HEIGHT = METRICS.button_height
    EDIT_HEIGHT = METRICS.control_height
    TOP_SECTION_PAD = 8
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
            on_dock_area_change=None, dock_area="right", reference_library=None,
            on_reference_manage=None, after=None):
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
        self._formula_required_ids = set()
        self._selection_initialized = False
        self._checkboxes: Dict[str, Any] = {}
        self._series_tags: Dict[str, Any] = {}
        self._series_objects: Dict[str, QLineSeries] = {}
        self._series_themes: Dict[str, Any] = {}  # compatibility: styles are now series-owned
        self._series_points: Dict[str, list] = {}
        self._closed = False
        self.reference_library = reference_library or ReferenceChartLibrary()
        self.on_reference_manage = on_reference_manage
        self._after = after or (lambda delay, callback, *args: callback(*args))
        self._reference_series_tags = {}
        self._reference_series_objects = {}
        self._reference_themes = {}  # compatibility: styles are now series-owned
        self._reference_menu_items = {}
        self._client_layout_signature = None
        self._font_probe_cache = None
        self._font_probe_checked_at = 0.0
        self._native_revision = 0
        self._plot_tooltips = []

        safe_job = "".join(ch if ch.isalnum() else "_" for ch in self.job_id)
        self.tag = "job_plots_window_{}".format(safe_job)
        stale = QRetainedItem(self.tag)
        if stale.exists():
            # A previously closed retained window can remain registered but
            # hidden for the rest of the frame. View-level reuse handles live
            # windows; anything left here must not steal the new instance.
            stale.deleteNative()

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
        self._dock_content_widget = self.dock.contentWidget()
        self._drag_handle_widget = self.dock.dragHandleWidget()

        # QDockWidget normally embeds an ordinary QWidget/QToolBar client. Use
        # a compact, persistent light toolbar that stays identical whether the
        # panel is docked or detached into a floating tool window.
        self._toolbar_frame = QFrame(
            parent=self._dock_content_widget, width=-1, height=self.TOOLBAR_HEIGHT,
            frame_shape=QFrame.NoFrame, no_scrollbar=True,
            no_scroll_with_mouse=True)
        self.toolbar = self._toolbar_frame.tag
        self._status_label = QLabel("Waiting for ODB...", parent=self._toolbar_frame)
        self.status_text = self._status_label.tag
        self.fit_button = self._icon_button(
            "fit", "Fit plot to data", self._fit_axes,
            parent=self._toolbar_frame)
        self.reference_button = self._icon_button(
            "reference", "Reference charts: show or manage overlays",
            lambda: self._after(1, self._open_reference_menu),
            parent=self._toolbar_frame)
        self._reference_menu = QMenu((), min_width=220, max_width=420)
        self._reference_menu.triggered.connect(self._reference_menu_triggered)
        self.reference_popup = self._reference_menu.tag
        register_pointer_protected_item(self.reference_popup)

        # r71: DockManager owns default QDockWidget title-bar gestures so a
        # single Plot dock can use the same live left/right/top/bottom/center
        # targets as tab drags.  The historical per-window global drag handler
        # detached immediately and therefore bypassed nested docking previews.
        # Keep the legacy helper methods below as compatibility shims, but do
        # not register a competing global mouse handler here.
        self._drag_registry = None

        # The body is a flush two-pane client area, similar to a QWidget with a
        # horizontal QSplitter: history list on the left, plot canvas on right.
        self._body_frame = QFrame(
            parent=self._dock_content_widget, width=-1, height=-1, frame_shape=QFrame.NoFrame,
            no_scrollbar=True, no_scroll_with_mouse=True)
        self.body_panel = self._body_frame.tag
        self._body_layout = QHBoxLayout(parent=self._body_frame, spacing=0)
        self.body_group = self._body_layout.tag

        self._list_frame = QFrame(
            parent=self._body_layout, width=self.LIST_WIDTH, height=-1,
            frame_shape=QFrame.StyledPanel, no_scrollbar=False,
            no_scroll_with_mouse=False, horizontal_scrollbar=False)
        self.list_panel = self._list_frame.tag
        self._history_header_label = QLabel("History outputs", parent=self._list_frame)
        self.filter_input = QLineEdit(
            "", parent=self._list_frame, width=-1,
            placeholder="Search outputs...")
        self.filter_input.textEdited.connect(lambda _text: self._apply_filter())
        self.all_button = self._icon_button(
            "select_all", "Select all history outputs",
            lambda: self._set_all(True), parent=self._list_frame)
        self.none_button = self._icon_button(
            "select_none", "Deselect all history outputs",
            lambda: self._set_all(False), parent=self._list_frame)
        self._count_label = QLabel("0 / 0", parent=self._list_frame)
        self._count_label.setToolTip("Selected / total history outputs")
        self.count_text = self._count_label.tag
        self._header_separator_canvas = QCanvas(
            width=1, height=1, parent=self._list_frame)
        self.header_separator = self._header_separator_canvas.tag
        self._header_separator_line = self._header_separator_canvas.painter().drawLine(
            (0, 0), (1, 0), color=QtFusionPalette.BORDER_LIGHT, thickness=1.0)
        self._history_frame = QFrame(
            parent=self._list_frame, width=-1, height=-1, frame_shape=QFrame.NoFrame,
            no_scrollbar=False, no_scroll_with_mouse=False,
            horizontal_scrollbar=False)
        self.history_container = self._history_frame.tag

        self._body_gap_widget = QSpacer(self.PANEL_GAP, 0, parent=self._body_layout)
        self.body_gap = self._body_gap_widget.tag

        self._plot_frame = QFrame(
            parent=self._body_layout, width=-1, height=-1, frame_shape=QFrame.NoFrame,
            no_scrollbar=True, no_scroll_with_mouse=True)
        self.plot_panel = self._plot_frame.tag
        self._plot_widget = QPlotWidget(
            "History Output", parent=self._plot_frame, width=-1, height=-1,
            mouse_position=True, crosshairs=False, query=False,
            tag="{}_plot".format(self.tag))
        self.plot = self._plot_widget.tag
        self._plot_widget.addLegend(location=QPlotWidget.NorthWest, horizontal=False, outside=False)
        self._x_axis_widget = self._plot_widget.addAxis(QPlotAxis.XAxis, "Time")
        self._y_axis_widget = self._plot_widget.addAxis(QPlotAxis.YAxis, "Value")
        self.x_axis = self._x_axis_widget.tag
        self.y_axis = self._y_axis_widget.tag

        self._toolbar_frame.setTheme(panel_header_theme())
        self._status_label.setTheme(status_text_theme(muted=True))
        self._count_label.setTheme(status_text_theme(muted=True))
        self._history_header_label.setTheme(panel_header_theme())
        self._body_frame.setTheme(self._body_theme)
        QRetainedItem(self.body_group).setTheme(self._body_theme)
        self._plot_frame.setTheme(self._panel_theme)
        self._plot_widget.setTheme(self._plot_theme)
        self._list_frame.setTheme(self._panel_theme)
        self._history_rows: Dict[str, Any] = {}
        self._history_labels: Dict[str, Any] = {}
        self.reference_library.subscribe(self._refresh_references)
        self._refresh_references()
        self.sync_layout()
        self.dock.setFocus()

    def _icon_button(self, name, tooltip, callback, *, parent):
        """Create a single clickable DearUIQt icon button (no overlay hit layer)."""
        texture = ResourceTextures.get("job_plots_icons/" + name, pixel_size=32)
        # Source deployments without optional icons stay operable; the shipped
        # archive contains all four PNGs so users normally see only the icon.
        fallback_glyph = {"fit": "F", "reference": "R", "select_all": "+", "select_none": "–"}
        button = QToolButton(
            "" if texture else fallback_glyph.get(name, "?"),
            parent=parent, icon=texture, icon_size=(self.ICON_SIZE, self.ICON_SIZE),
            auto_raise=True)
        button.setTheme(plot_panel_icon_theme())
        button.clicked.connect(callback)
        tip = QToolTip(button, delay=0.55, hide_on_activity=True)
        tip.setTheme(tooltip_theme())
        QLabel(tooltip, parent=tip, wrap=280)
        self._plot_tooltips.append(tip)
        return button

    def _build_themes(self):
        # Plot-specific renderer roles are centralized in DearUIQt; WinUx only
        # selects the semantic Fusion surface. Layout/text surfaces use the
        # same declarative theme contract as the rest of the shell.
        self._plot_theme = plot_surface_theme()
        self._body_theme = compact_layout_surface_theme(
            padding=(0, 0), spacing=(0, 0), child_border=0,
            tag="winux.jobplots.body", cache=True)
        self._panel_theme = panel_surface_theme(bordered=True, compact=True)
        self._history_label_theme = text_theme(
            color=(25, 25, 25, 255), tag="winux.jobplots.history.text", cache=True)

    def set_dock_mode(self, mode):
        mode = "floating" if str(mode).lower() == "floating" else "docked"
        self.dock_mode = mode
        self._drag_undock_requested = False
        if hasattr(self, "dock"):
            self.dock.set_floating(mode == "floating")
        self._sync_client_layout(force=True)

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
        self._sync_client_layout(force=True)

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
            retained = QRetainedItem(getattr(item, "tag", item))
            if not retained.exists():
                return False
            retained.configure(**kwargs)
            return True
        except BaseException:
            return False

    def _sync_client_layout(self, force=False):
        if not hasattr(self, "dock") or not self._dock_content_widget.exists():
            return False
        geometry = self._dock_content_widget.globalGeometry()
        content_w, content_h = geometry.width(), geometry.height()
        if content_w <= 1 or content_h <= 1:
            return False

        status_value = self._status_label.text()
        count_value = self._count_label.text()
        # sync_layout() is invoked every rendered frame, even when neither the
        # Plot client nor any text changes. get_text_size() crosses into Dear
        # PyGui and is substantially more expensive than comparing cached
        # values. Probe font metrics periodically (and immediately on a forced
        # layout) so a font/DPI change still causes an automatic relayout.
        now = time.monotonic()
        metrics = None
        if (force or self._font_probe_cache is None or
                now - self._font_probe_checked_at >= 0.4):
            metrics = QFontMetrics()
            font_probe_size = metrics.size("M")
            self._font_probe_cache = (
                font_probe_size.width(), font_probe_size.height())
            self._font_probe_checked_at = now
        font_probe = self._font_probe_cache
        signature = (content_w, content_h, status_value, count_value, font_probe)
        if not force and signature == self._client_layout_signature:
            return False
        if metrics is None:
            metrics = QFontMetrics()

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

        status_metric = metrics.size(status_value)
        count_metric = metrics.size(count_value)
        status_size = (status_metric.width(), status_metric.height())
        count_size = (count_metric.width(), count_metric.height())

        icon_w = self.ICON_BUTTON_WIDTH
        toolbar_w = max(1, content_w)
        fit_x = max(inner_pad, toolbar_w - inner_pad - icon_w)
        reference_x = max(inner_pad, fit_x - self.ICON_GAP - icon_w)
        fit_y = max(0, (toolbar_h - self.BUTTON_HEIGHT) // 2)
        status_y = max(0, (toolbar_h - int(status_size[1])) // 2)

        # Header / filter / actions are three visually separate rows. Leave a
        # fixed hit area for each image button, even in a narrow dock.
        header_y = self.TOP_SECTION_PAD
        filter_y = header_y + self.HEADER_HEIGHT + 4
        button_row_y = filter_y + self.EDIT_HEIGHT + 7
        history_y = button_row_y + self.BUTTON_HEIGHT + 10
        history_h = max(1, body_h - history_y - inner_pad)
        count_x = max(
            inner_pad + 2 * icon_w + self.ICON_GAP + 12,
            list_width - inner_pad - int(count_size[0]) - self.COUNT_RIGHT_PAD,
        )
        count_y = button_row_y + max(0, (self.BUTTON_HEIGHT - int(count_size[1])) // 2)

        self._safe_configure(
            self.toolbar, pos=(0, 0), width=toolbar_w,
            height=toolbar_h)
        self._safe_configure(self.status_text, pos=(inner_pad, status_y),
                             wrap=max(40, reference_x - inner_pad - 8))
        # Image-button width/height describe glyph pixels, not outer frames.
        # Configure positions only; QToolButton and the icon theme own sizing.
        self._safe_configure(self.fit_button, pos=(fit_x, fit_y))
        self._safe_configure(self.reference_button, pos=(reference_x, fit_y))

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
            self._history_header_label, pos=(inner_pad, header_y))
        self._safe_configure(
            self.filter_input, pos=(inner_pad, filter_y),
            width=filter_w, height=self.EDIT_HEIGHT)
        self._safe_configure(self.all_button, pos=(inner_pad, button_row_y))
        self._safe_configure(self.none_button,
                             pos=(inner_pad + icon_w + self.ICON_GAP, button_row_y))
        self._safe_configure(self.count_text, pos=(count_x, count_y))
        self._safe_configure(
            self.header_separator, pos=(inner_pad, history_y - 7),
            width=filter_w, height=1)
        self._safe_configure(
            self._header_separator_line,
            p1=(0, 0), p2=(max(1, filter_w), 0))
        self._safe_configure(
            self.history_container, pos=(inner_pad, history_y),
            width=filter_w, height=history_h)
        self._client_layout_signature = signature
        return True

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
            active = self._drag_handle_widget.isActive()
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
            point = QCursor.pos()
            pointer = (float(point.x()), float(point.y()))
        except Exception:
            pointer = None
        drag_anchor = None
        if pointer is not None:
            try:
                handle_pos = self._drag_handle_widget.globalPos()
                hx, hy = float(handle_pos.x()), float(handle_pos.y())
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
        return (not self._closed and self.dock.exists())

    def focus(self):
        if self.exists():
            self.dock.show()
            if not self._plot_widget.setFocus():
                self.dock.setFocus()

    def _cleanup_series_themes(self):
        for theme in list(self._series_themes.values()):
            try:
                if hasattr(theme, "delete"):
                    theme.delete()
                else:
                    retained = QRetainedItem(theme)
                    if retained.exists():
                        retained.deleteNative()
            except Exception:
                pass
        self._series_themes.clear()

    def close(self, notify=False):
        self.end_pointer_capture()
        if self._closed:
            return
        self._closed = True
        self.reference_library.unsubscribe(self._refresh_references)
        unregister_pointer_protected_item(self.reference_popup)
        try:
            self._reference_menu.delete()
        except Exception:
            pass
        self._clear_reference_series()
        self._cleanup_series_themes()
        if self._drag_registry:
            try:
                if hasattr(self._drag_registry, "delete"):
                    self._drag_registry.delete()
                else:
                    retained = QRetainedItem(self._drag_registry)
                    if retained.exists():
                        retained.deleteNative()
            except Exception:
                pass
        if hasattr(self, "dock"):
            try:
                self.dock.close()
            except Exception:
                pass
        else:
            retained = QRetainedItem(self.tag)
            if retained.exists():
                retained.deleteNative()
        if notify:
            callback = self.on_close
            if callable(callback):
                callback(self.job_id)

    def _handle_close(self, sender=None, app_data=None, user_data=None):
        self.close(notify=True)

    def _open_reference_menu(self):
        if not self.exists():
            return
        if not self.reference_library.snapshot():
            self._manage_references()
            return
        geometry = self.reference_button.globalGeometry()
        self._reference_menu.popup((geometry.left(), geometry.bottom()))

    def _reference_menu_triggered(self, action, _context=None):
        action = str(action or "")
        if action == "manage":
            self._manage_references()
        elif action.startswith("reference:"):
            series_id = action.split(":", 1)[1]
            item = next((row for row in self.reference_library.snapshot()
                         if str(row.get("id")) == series_id), None)
            if item is not None:
                self._set_reference_enabled(series_id, not bool(item.get("enabled")))

    def _manage_references(self, *_args):
        self._reference_menu.hide()
        if callable(self.on_reference_manage):
            self._after(1, self.on_reference_manage)
        else:
            self.set_error("Reference Chart manager is unavailable in this view")

    def _reference_toggled(self, _sender, enabled, series_id):
        self._after(1, self._set_reference_enabled, series_id, bool(enabled))

    def _set_reference_enabled(self, series_id, enabled):
        if not self.exists():
            return
        try:
            self.reference_library.set_enabled(series_id, enabled)
        except (OSError, ValueError) as exc:
            self._refresh_references()
            self.set_error("Could not save reference selection: {}".format(exc))

    def _clear_reference_series(self):
        for series in tuple(self._reference_series_objects.values()):
            try:
                series.delete()
            except Exception:
                pass
        self._reference_series_objects.clear()
        self._reference_series_tags.clear()
        self._reference_themes.clear()

    def _refresh_references(self, sync_dependencies=True):
        if not self.exists():
            return
        self._native_revision = getattr(self, "_native_revision", 0) + 1
        references = self.reference_library.snapshot()
        if sync_dependencies:
            self._sync_formula_dependencies(notify=True)

        self._reference_menu_items.clear()
        menu_actions = [{
            "id": "manage", "action": "manage",
            "label": "Add / manage reference series...",
        }, {"id": "reference-separator", "separator": True, "label": "---"}]
        for item in references:
            series_id = str(item["id"])
            action = "reference:{}".format(series_id)
            menu_actions.append({
                "id": action, "action": action, "label": item["name"],
                "checkable": True, "checked": bool(item["enabled"]),
            })
            self._reference_menu_items[series_id] = action
        self._reference_menu.setActions(menu_actions)
        self._clear_reference_series()
        colors = ((163, 56, 157, 255), (128, 91, 12, 255), (38, 112, 143, 255),
                  (181, 55, 42, 255), (76, 104, 45, 255), (82, 73, 151, 255))
        rendered = 0
        for index, item in enumerate(references):
            series_id = item["id"]
            if not item["enabled"]:
                continue

            plot_items = [item]
            if item.get("kind") == "formula":
                try:
                    plot_items = evaluate_reference_formula(
                        item.get("formula", ""), self.reference_formula_sources())
                except (TypeError, ValueError, re.error):
                    plot_items = []

            for formula_index, plot_item in enumerate(plot_items):
                points = plot_item.get("points") or []
                if not points:
                    continue
                xs, ys = zip(*points)
                plot_id = (series_id if len(plot_items) == 1
                           else "{}:{}".format(series_id, formula_index))
                series = self._plot_widget.addLineSeries(
                    list(xs), list(ys), axis=self._y_axis_widget,
                    label="Reference: {}".format(plot_item.get("name") or item["name"]),
                    color=colors[index % len(colors)], width=2.0,
                    marker=(QLineSeries.CircleMarker if len(points) == 1 else QLineSeries.NoMarker))
                self._reference_series_objects[plot_id] = series
                self._reference_series_tags[plot_id] = series.tag
                rendered += 1
        if rendered:
            self._fit_axes()

    def _set_status_message(self, message):
        if not self.exists():
            return
        self._status_label.setText(str(message))
        self._native_revision = getattr(self, "_native_revision", 0) + 1
        self._sync_client_layout()

    def set_waiting(self, message="Waiting for ODB..."):
        self._set_status_message(message)

    def set_status(self, message):
        self._set_status_message(message)

    def set_error(self, message):
        self._set_status_message("Error: {}".format(message))

    def selection_items(self):
        requested = set(self.selected_ids) | set(self._formula_required_ids)
        return [
            dict(self.catalog[item_id])
            for item_id in self.catalog
            if item_id in requested
        ]

    def _sync_formula_dependencies(self, notify=False):
        required = set()
        catalog_rows = []
        for item_id, row in self.catalog.items():
            item = dict(row or {})
            item["id"] = str(item_id)
            catalog_rows.append(item)
        for reference in self.reference_library.snapshot():
            if not reference.get("enabled") or reference.get("kind") != "formula":
                continue
            try:
                required.update(resolve_reference_formula_ids(
                    reference.get("formula", ""), catalog_rows))
            except (TypeError, ValueError, re.error):
                continue
        changed = required != self._formula_required_ids
        self._formula_required_ids = required
        if notify and changed:
            self._notify_selection_changed()
        return changed

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
        self._update_history_count()
        self._sync_client_layout()
        odb_name = str((payload or {}).get("odb") or "ODB")
        self.set_status("{} | live history catalog ready".format(odb_name))
        self._sync_formula_dependencies(notify=False)
        self._notify_selection_changed()

    def _rebuild_history_list(self):
        history = QRetainedItem(self.history_container)
        if not history.exists():
            return
        history.clear()
        self._checkboxes.clear()
        self._history_rows.clear()
        self._history_labels.clear()
        for item_id, row in self.catalog.items():
            output = str(row.get("output") or "")
            display = str(row.get("displayName") or output or item_id)
            step = str(row.get("step") or "")
            region = str(row.get("historyRegion") or "")
            points = int(row.get("points") or 0)
            label = "{}  ·  {:,} pts".format(display, points)
            row_layout = QVBoxLayout(parent=self.history_container, spacing=0)
            row_group = row_layout.tag
            inline_layout = QHBoxLayout(parent=row_layout, spacing=0)
            inline_group = inline_layout.tag
            checkbox = QCheckBox(
                "", checked=item_id in self.selected_ids,
                parent=inline_group)
            checkbox.clicked.connect(
                lambda checked, item_id=item_id, checkbox=checkbox:
                self._checkbox_changed(checkbox.tag, checked, item_id))
            QSpacer(7, 0, parent=inline_layout)
            label_widget = QLabel(label, parent=inline_layout)
            label_widget.setTheme(self._history_label_theme)
            label_text = label_widget.tag
            QSpacer(0, self.HISTORY_ROW_GAP, parent=row_layout)
            self._checkboxes[item_id] = checkbox
            self._history_rows[item_id] = row_group
            self._history_labels[item_id] = label_text
            for tip_target in (checkbox, label_widget):
                tip = QToolTip(tip_target, delay=0.45, hide_on_activity=True)
                tip.setTheme(tooltip_theme())
                QLabel("Output: {}".format(output), wrap=420, parent=tip)
                if step:
                    QLabel("Step: {}".format(step), wrap=420, parent=tip)
                if region:
                    QLabel("Region: {}".format(region), wrap=420, parent=tip)
        self._apply_filter()

    def _update_history_count(self):
        if self._count_label.exists():
            text = "{} / {}".format(len(self.selected_ids), len(self.catalog))
            if self._count_label.text() != text:
                self._count_label.setText(text)
                # Reposition the right-aligned count when its width changes
                # (e.g. 9/100 -> 10/100), without rebuilding any history rows.
                if self._client_layout_signature is not None:
                    self._sync_client_layout()

    def _checkbox_changed(self, sender, app_data, user_data):
        item_id = str(user_data or "")
        checked = bool(app_data)
        if checked:
            self.selected_ids.add(item_id)
        else:
            self.selected_ids.discard(item_id)
            self._delete_series(item_id)
            self._series_points.pop(item_id, None)
        self._update_history_count()
        self._notify_selection_changed()

    def _set_all(self, checked):
        self.selected_ids = set(self.catalog) if checked else set()
        for item_id, checkbox in self._checkboxes.items():
            if not checkbox._deleted:
                checkbox.setChecked(bool(checked))
        if not checked:
            for item_id in list(self._series_tags):
                self._delete_series(item_id)
            self._series_points.clear()
        self._update_history_count()
        self._notify_selection_changed()

    def _notify_selection_changed(self):
        self._native_revision = getattr(self, "_native_revision", 0) + 1
        callback = self.on_selection_change
        if callable(callback):
            callback(self.job_id, self.selection_items())

    def set_selected_ids(self, ids, notify=True):
        """Apply a dock client's selection without replacing its ODB monitor."""
        selected = set(map(str, ids)) & set(self.catalog)
        changed = selected != self.selected_ids
        self.selected_ids = selected
        for item_id, checkbox in self._checkboxes.items():
            if not checkbox._deleted:
                enabled = item_id in selected
                checkbox.setChecked(enabled)
        self._remove_unselected_series()
        self._update_history_count()
        if changed and notify:
            self._notify_selection_changed()

    def native_snapshot(self):
        return {"catalog": [dict(row) for row in self.catalog.values()],
                "selected": sorted(self.selected_ids),
                "series": [{"id": key, "points": [list(p) for p in points], "reset": True}
                           for key, points in self._series_points.items()],
                "references": self.reference_library.snapshot(),
                "status": self._status_label.text()}

    def _filter_changed(self, sender=None, app_data=None, user_data=None):
        self._apply_filter()

    def _apply_filter(self):
        if self.filter_input._deleted:
            return
        needle = str(self.filter_input.text() or "").strip().casefold()
        for item_id, checkbox in self._checkboxes.items():
            row = self.catalog.get(item_id, {})
            haystack = " ".join((
                str(row.get("output") or ""),
                str(row.get("displayName") or ""),
                str(row.get("step") or ""),
                str(row.get("historyRegion") or ""),
            )).casefold()
            target = self._history_rows.get(item_id, checkbox.tag)
            QRetainedItem(target).setVisible(not needle or needle in haystack)

    def _series_color(self, item_id):
        row = self.catalog.get(item_id, {})
        output = str(row.get("output") or "").strip().upper()
        if output == "ALLKE":
            return (0, 191, 255, 255)
        if output == "ALLIE":
            return (255, 179, 0, 255)
        index = list(self.catalog).index(item_id) if item_id in self.catalog else 0
        return self.SERIES_COLORS[index % len(self.SERIES_COLORS)]

    def _delete_series(self, item_id):
        self._series_tags.pop(item_id, None)
        series = self._series_objects.pop(item_id, None)
        if series is not None:
            try:
                series.delete()
            except Exception:
                pass

    def _remove_unselected_series(self):
        for item_id in list(self._series_tags):
            if (item_id not in self.selected_ids and item_id not in self._formula_required_ids) or item_id not in self.catalog:
                self._delete_series(item_id)
                self._series_points.pop(item_id, None)

    def update_frame(self, payload):
        if not self.exists():
            return
        changed = False
        for row in (payload or {}).get("series") or []:
            item_id = str(row.get("id") or "")
            if (not item_id or
                    (item_id not in self.selected_ids and
                     item_id not in self._formula_required_ids)):
                continue
            points = merge_series_delta(self._series_points.get(item_id), row)
            self._series_points[item_id] = points
            if item_id in self.selected_ids:
                catalog = self.catalog.get(item_id, {})
                label = str(
                    row.get("displayName") or
                    catalog.get("displayName") or
                    catalog.get("output") or
                    item_id)
                series = self._series_objects.get(item_id)
                xs = [point[0] for point in points]
                ys = [point[1] for point in points]
                if series is None or not series.exists():
                    series = self._plot_widget.addLineSeries(
                        xs, ys, axis=self._y_axis_widget, label=label,
                        color=self._series_color(item_id), width=1.6)
                    self._series_objects[item_id] = series
                    self._series_tags[item_id] = series.tag
                else:
                    series.setData(xs, ys)
            changed = True

        if changed:
            self._refresh_references(sync_dependencies=False)
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
                "Live | {} selected | {} points | updated {}".format(
                    len(self.selected_ids), total_points, stamp))

    def reference_formula_sources(self):
        """Return a serializable snapshot of the current Plot history catalog/data."""
        rows = []
        for item_id, catalog in self.catalog.items():
            row = dict(catalog or {})
            row["id"] = str(item_id)
            row["points"] = [list(point[:2]) for point in self._series_points.get(item_id, ())
                             if isinstance(point, (list, tuple)) and len(point) >= 2]
            rows.append(row)
        return rows

    def _fit_axes(self, sender=None, app_data=None, user_data=None):
        for axis in (self._x_axis_widget, self._y_axis_widget):
            axis.fitData()
