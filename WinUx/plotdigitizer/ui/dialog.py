"""WinUx-native Plot Digitizer dialog built from shared Dear ImGui components."""
from __future__ import annotations

from pathlib import Path
from dataclasses import replace

try:
    import numpy as np
except Exception:  # optional fast texture conversion
    np = None
from DearUIQt.gui import QPainter, QCursor, QKeyboard, QPaintLayer, QTextureRegistry
from DearUIQt.core import Qt, QItemInputBinding, QGlobalInputBinding

from DearUIQt.widgets import QApplication, QCanvas, QToolButton, QFrame, QSpacer, QLabel, QToolTip, QRetainedItem

from ..core import AxisScale, DigitizerEngine, ExtractionSettings
from ..application import SmartDetectRunner, normalize_workspace_state
from ..core.extraction import detect_curve_colors
from DearUIQt import (
    ToolWindow, QtDataGridView, QtGridRow, QtListView, QtFusionPalette,
    QtListItem, ColorField, QPushButton, QMenu, QAction, QtConcurrent,
)
from ...ui import (
    FileSelector, ToolWorkspace, ToolCommandRow, style_image_canvas,
    style_tool_surface, item_rect, RibbonBar, CanvasCursor,
)
from ...ui.components.toolbar import ResourceTextures, toolbar_icon_theme, toolbar_fitted_icon_theme
from ...preferences.plot_digitizer import PlotDigitizerPreferences
from .markers import draw_marker, marker_metrics, cursor_hits_marker
from .preview import preview_geometry
from DearUIQt.tooltip import TOOLTIP_DELAY, TOOLTIP_WRAP_WIDTH, tooltip_theme
from DearUIQt.themes import transparent_header_cell_theme
from DearUIQt.layouts import QVBoxLayout, QHBoxLayout
from DearUIQt.runtime import QGuiRuntime

# Compatibility injection point for backend-neutral shortcut tests. Production
# resolves the renderer through DearUIQt; WinUx does not import backend modules.
dpg = None

def _renderer_backend():
    return dpg if dpg is not None else QGuiRuntime().backend


class PlotDigitizerDialog(ToolWindow):
    """Plot digitizer using the same retained Dear ImGui controls as WinUx."""

    REUSABLE_HOST = True
    ICON_ROOT = "plotdigitizer_icons"
    DECORATIVE_ICON_SIZE = 16
    COMPACT_ICON_RENDER_SIZE = 18
    ICON_ACTION_HEIGHT = 26
    ICON_ACTION_GUTTER = 26

    @classmethod
    def _icon(cls, name: str) -> str:
        return f"{cls.ICON_ROOT}/{name}.png"

    LEFT_WIDTH = 210
    RIGHT_WIDTH = 288
    CANVAS_MIN_WIDTH = 420
    OUTER_MARGIN = 6
    REGION_GAP = 8
    NATIVE_RESIZABLE = True
    ALLOW_MINIMIZE = True
    ALLOW_MAXIMIZE = True

    def __init__(self, view, reference_sink=None, reference_library=None):
        # reference_library is retained only for compatibility with old callers.
        if reference_sink is None and reference_library is not None:
            from ..integration.winux import WinUxReferenceSink
            reference_sink = WinUxReferenceSink(reference_library)
        self.reference_sink = reference_sink
        self._plot_preference_store = PlotDigitizerPreferences()
        self._plot_preferences = self._plot_preference_store.load()
        self._preference_refreshing = False
        self._preference_controls = {}
        self.engine = DigitizerEngine()
        self.engine.subscribe(self._engine_changed)
        self._icon_action_draws = {}
        self._icon_action_canvases = {}
        self._smart_runner = SmartDetectRunner(
            self.engine,
            lambda callback, *args: self.view.after(0, callback, *args),
            submitter=QtConcurrent.run)
        self._reuse_safe_on_close = True
        self._pick_mode = None
        self._texture_tag = None
        self._texture_registry = None
        self._handler_registry = None
        self._input_binding = None
        self._canvas_resize_binding = None
        self._canvas_visible_binding = None
        self._fit_scale = 1.0
        self._zoom = 1.0
        self._pan = [0.0, 0.0]
        self._middle_drag = False
        self._last_mouse = (0.0, 0.0)
        self._file_dialog = None
        self._file_directory = ""
        self._auto_fit = True
        self._canvas_size = None
        self._data_layout_pending = False
        self._data_grid_height = 300
        self._selected_point = None
        self._edit_enabled = False
        self._hover_point = None
        self._sample_pixel = None
        self._drag_start = None
        self._drag_preview = None
        self._drag_target = None
        self._cursor_pixel = None
        self._preview_pixel = None
        self._cursor_canvas = None
        self._cursor_over_marker = False
        self._canvas_cursor = None
        self._pointer_layer = None
        self._palette = []
        self._refresh_pending = False
        self._tool_pages = {}
        self._active_tool = None
        self._calibration_sequence = []
        self._disclosures = {}
        self._project_load_generation = 0
        self._image_load_generation = 0
        self._image_load_future = None

        super().__init__(view, "Plot Digitizer", 1240, 780, footer=False)
        self.preferred_size = (1240, 780)
        self.setMinimumSize(1100, 680)
        QRetainedItem(self.content).configure(no_scrollbar=True, no_scroll_with_mouse=True)
        self._content_theme = style_tool_surface(
            self.content, padding=(self.OUTER_MARGIN, self.OUTER_MARGIN), spacing=(0, self.REGION_GAP))

        self._build_toolbar()
        self._build_workspace()
        self._canvas_cursor = CanvasCursor(self.view, window=self.tag)

        self._install_mouse_handlers()
        self.enter_editors.update((self.dataset_name, self.curve_color.editor.tag,
                                   self.point_x, self.point_y, *self.anchor_value.values()))
        self._refresh_all()
        self._show_tool("axes")
        self.view.after(0, self._layout_canvas)

    # ---------- layout ----------
    def _build_toolbar(self):
        # Plot Digitizer deliberately omits the Quick Access Toolbar. The command
        # count is small enough that Home/View tabs provide a cleaner CAD ribbon.
        self.ribbon = self.own_widget(RibbonBar(
            self.content, quick_access=False, density="compact", after=self.view.after))
        # Keep the original compact ribbon geometry, but use more of each tile
        # for the icon itself so the PNG remains readable without larger buttons.
        self.ribbon.LARGE_ICON_SIZE = 32

        # Plot Digitizer has a deliberately small command set, so every ribbon
        # command is a full-height large button rather than a three-row stack.
        self.ribbon.add_tab("home", "Home", activate=True)
        self.ribbon.add_group("home", "image", "Image", width=72, layout="large")
        self.ribbon.add_button(
            "home", "image", "open_image", "Open Image", self._choose_open_image,
            width=64, image=self._icon("open_image"), tooltip="Open a chart image")

        self.ribbon.add_group("home", "project", "Project", width=140, layout="large")
        self.ribbon.add_button(
            "home", "project", "load_project", "Load Project", self._choose_load_project,
            width=64, image=self._icon("load_project"), tooltip="Load a Plot Digitizer project")
        self.ribbon.add_button(
            "home", "project", "save_project", "Save Project", self._choose_save_project,
            width=64, image=self._icon("save_project"), tooltip="Save the current project")

        self.ribbon.add_group("home", "export", "Export", width=72, layout="large")
        self.ribbon.add_button(
            "home", "export", "export_csv", "Export CSV", self._choose_export_csv,
            width=64, image=self._icon("export_csv"), tooltip="Export digitized data to CSV")

        self.ribbon.add_group("home", "history", "History", width=140, layout="large")
        self.undo_button = self.ribbon.add_button(
            "home", "history", "undo", "Undo", lambda: self._trigger_history_command("undo"),
            width=64, image=self._icon("undo"), tooltip="Undo the last edit (Ctrl+Z)")
        self.redo_button = self.ribbon.add_button(
            "home", "history", "redo", "Redo", lambda: self._trigger_history_command("redo"),
            width=64, image=self._icon("redo"), tooltip="Redo the last edit (Ctrl+Y / Ctrl+Shift+Z)")
        self._history_actions = {}
        for key, label, callback in (("undo", "Undo", self._undo), ("redo", "Redo", self._redo)):
            command = self.own_widget(QAction(label, after=self.view.after))
            command.triggered.connect(lambda checked, execute=callback: execute())
            command.changed.connect(lambda name=key, action=command:
                                    self.ribbon.set_button_enabled(name, action.isEnabled()))
            self._history_actions[key] = command
        self._refresh_history_commands()

        # Settings is a first-class ribbon command, visible on the default Home
        # tab rather than an extra step in the digitizing workflow.
        self.ribbon.add_group("home", "preferences", "Preferences", width=76, layout="large")
        self.ribbon.add_button(
            "home", "preferences", "settings", "Settings", lambda: self._show_tool("settings"),
            width=68, image=self._icon("settings"),
            tooltip="Customize the canvas, markers and mouse interaction")

        self.ribbon.add_tab("view", "View")
        self.ribbon.add_group("view", "zoom", "Zoom", width=276, layout="large")
        self.ribbon.add_button(
            "view", "zoom", "fit", "Fit", self._fit_view,
            width=64, image=self._icon("fit_view"), tooltip="Fit image to canvas")
        self.ribbon.add_button(
            "view", "zoom", "one_to_one", "1:1", self._one_to_one,
            width=64, image=self._icon("one_to_one"), tooltip="Show image at 1:1 scale")
        self.ribbon.add_button(
            "view", "zoom", "zoom_out", "Zoom Out", lambda: self._zoom_at(1 / 1.15),
            width=64, image=self._icon("zoom_out"), tooltip="Zoom out")
        self.ribbon.add_button(
            "view", "zoom", "zoom_in", "Zoom In", lambda: self._zoom_at(1.15),
            width=64, image=self._icon("zoom_in"), tooltip="Zoom in")

        self.ribbon.add_group("view", "plot_area", "Plot Area", width=72, layout="large")
        self.ribbon.add_button(
            "view", "plot_area", "box", "Box", lambda: self._begin_pick("area"),
            width=64, image=self._icon("plot_area"), tooltip="Select the plot area")

    def _build_workspace(self):
        self.workspace = self.own_widget(ToolWorkspace(
            self.content, column_widths=(self.LEFT_WIDTH, None, self.RIGHT_WIDTH),
            column_gap=self.REGION_GAP, panel_padding=(0, 0), panel_spacing=(6, 8),
            after=self.view.after))
        self.dataset_panel = self.workspace.panel(0, scroll=True).tag
        self.canvas_panel = self.workspace.panel(1).tag
        self.settings_panel = self.workspace.panel(2, scroll=True).tag
        self._build_dataset_panel(self.dataset_panel)
        self._build_canvas_panel(self.canvas_panel)
        self._build_settings_panel(self.settings_panel)

    def _build_dataset_panel(self, parent):
        panel = parent
        with self.section("Image", parent=panel) as group:
            self.project_info = self.note("No image loaded", parent=group, wrap=170)
            self._image_details = self._add_help(self.project_info, "Open a chart image from Home.")
        with self.section("Workflow", parent=panel) as group:
            self.note("Choose a step, then use the panel on the right to calibrate, digitize and review data.",
                      parent=group, wrap=190)
            self.tool_list = self.own_widget(QtListView(group, [
                QtListItem("axes", "Axes / Calibration"),
                QtListItem("manual", "Manual Extraction"),
                QtListItem("automatic", "Automatic Extraction"),
                QtListItem("data", "View Data"),
            ], visible_rows=4, after=self.view.after))
            self.tool_list.currentChanged.connect(self._show_tool)
        with self.section("Datasets", parent=panel) as group:
            self.note("Manage series and control which datasets are visible on the canvas.",
                      parent=group, wrap=190)
            row_layout = QHBoxLayout(parent=group, spacing=6)
            row = row_layout.tag
            self.dataset_name = self.line_edit(self.engine.active_dataset.name, parent=row_layout, width=-68,
                                                on_enter=True, callback=self._dataset_name_changed)
            add_dataset = self._icon_only_action(
                "add_item", self._add_dataset, parent=row,
                tooltip="Add dataset", button_size=22)
            self._add_help(add_dataset, "Create a new dataset / series")
            self.delete_dataset_button = self._icon_only_action(
                "delete_item", self._delete_dataset, parent=row,
                tooltip="Delete active dataset", button_size=22)
            self.dataset_list = self.own_widget(QtListView(group, [], visible_rows=5,
                                                          after=self.view.after, context_menu_requests=True))
            self.dataset_list.currentChanged.connect(self._dataset_selected)
            self.dataset_list.itemCheckChanged.connect(self._dataset_visibility_changed)
            self.dataset_list.contextMenuRequested.connect(self._dataset_context_open)
            self.dataset_menu = self.own_widget(QMenu([], after=self.view.after, min_width=140))
            self.dataset_menu.triggered.connect(self._dataset_context_action)
        self.status = self.note("", parent=panel, wrap=190)
        self.set_control_visible(self.status, False)

    def _add_help(self, item, text):
        tooltip = self.own_widget(QToolTip(
            item, parent=self, delay=TOOLTIP_DELAY, hide_on_activity=True,
            ))
        label = QLabel(text, parent=tooltip, wrap=TOOLTIP_WRAP_WIDTH)
        tooltip.setTheme(tooltip_theme())
        # Image metadata updates this text later; preserve the text-item return.
        return label.tag

    def _build_data_panel(self, panel):
        with self.section("View Data", parent=panel) as group:
            self.note("Review the extracted samples, clean them up and prepare the CSV export.",
                      parent=group, wrap=240)
            self.coordinate_mode = self.combo(["Chart X/Y", "Image pixels"], parent=group,
                                              default_value="Chart X/Y", callback=lambda *_: self._refresh_grid())
            self.data_coordinate_info = self.note("Showing image pixels until axes are calibrated.", parent=group, wrap=240)
            self.data_summary = self.note("No points in this dataset.", parent=group, wrap=240)
            selection_tools = self.own_widget(ToolCommandRow(group, after=self.view.after))
            self.select_all_points_button = self.action(
                "Select All", self._select_all_data_points, parent=selection_tools.cell(0, 0))
            self.clear_selection_button = self.action(
                "Deselect", self._clear_data_selection, parent=selection_tools.cell(0, 1))
            tools = self.own_widget(ToolCommandRow(group, after=self.view.after))
            self.delete_points_button = self._icon_action(
                "Delete", "delete_points", self._delete_points,
                parent=tools.cell(0, 0), width=-1)
            self.clear_points_button = self._icon_action(
                "Clear All", "clear_points", self._clear_points,
                role="danger", parent=tools.cell(0, 1), width=-1)
            self.reduce_samples_button = self._icon_action(
                "Reduce Samples", "reduce_samples", self._reduce_samples,
                parent=group, width=-1)
            self._add_help(self.reduce_samples_button,
                           "Reduce the active dataset while preserving endpoints and curve shape. Ctrl+Z restores the samples.")
            with self.disclosure("Reduction options", parent=group) as options:
                self._disclosures["reduction"] = QRetainedItem(options).parentItem()
                form = self.form_layout(options, label_width=100)
                self.reduction_error = self.form_layout_row(form, "Max error (px)", lambda host: self.spin_float(
                    0.5, parent=host, minimum=0.0, maximum=10.0, step=0.1, decimals=2))
                self._add_help(self.reduction_error, "Maximum geometric error in image pixels. Set 0 for collinear-only reduction.")
            self.result_grid = self.own_widget(QtDataGridView(
                    group,
                    [
                        {"key": "n", "label": "#", "width": 34, "align": "center"},
                        {"key": "x", "label": "X", "stretch": 1.0},
                        {"key": "y", "label": "Y", "stretch": 1.0},
                    ],
                    height=300, after=self.view.after, multiple=True,
                    sortable=False, resizable=True, horizontal_scrollbar=False))
            self.result_grid.currentChanged.connect(self._point_selected)
            self.result_grid.selectionChanged.connect(lambda *_: self._refresh_point_actions())
            self.note("CSV export", parent=group)
            self.export_scope = self.combo(["All datasets", "Active dataset"], parent=group,
                                           default_value="All datasets", callback=lambda *_: self._refresh_export_controls())
            self.export_sort_x = self.checkbox("Sort CSV by X", checked=False, parent=group)
            self.export_data_button = self.action(
                "Export CSV", self._choose_export_csv, parent=group)
            self._add_help(self.export_data_button,
                           "Export calibrated X/Y data using the scope and sort options above. Calibrate all four axis anchors first.")

    def _build_canvas_panel(self, parent):
        # The canvas is a real framed surface that exists before an image is
        # loaded.  The drawlist only owns image/marker rendering inside it.
        self._canvas_frame_widget = QFrame(
            parent=parent, width=self.CANVAS_MIN_WIDTH, height=440,
            frame_shape=QFrame.StyledPanel, no_scrollbar=True,
            no_scroll_with_mouse=True)
        self.canvas_frame = self._canvas_frame_widget.tag
        style_image_canvas(self.canvas_frame)
        self._canvas_widget = QCanvas(
            parent=self._canvas_frame_widget, width=self.CANVAS_MIN_WIDTH - 2,
            height=438)
        self.canvas = self._canvas_widget.tag

        self._canvas_resize_binding = (
            QItemInputBinding(parent, parent=self)
            .onResize(lambda *_: self.view.after(0, self._layout_canvas))
            .activate()
        )
        # mvChildWindow does not support a visible handler in some bundled
        # renderers. The QCanvas drawlist does and shares the frame visibility.
        self._canvas_visible_binding = (
            QItemInputBinding(self._canvas_widget, parent=self)
            .onVisible(lambda *_: self._canvas_pointer_tick())
            .activate()
        )
        self._texture_registry = QTextureRegistry(parent=self, visible=False)

    def _toggle_action(self, label, callback, *, parent, width=-1):
        """Create a WinUx-styled checkable push button and retain its wrapper."""
        widget = self.own_widget(QPushButton(
            label, width=int(width), parent=parent, after=self.view.after,
            checkable=True))
        widget.toggled.connect(callback)
        self._control_wrappers[widget.tag] = widget
        self._remember_focusable(widget.tag)
        return widget.tag

    def _icon_texture(self, name, *, pixel_size=32):
        return ResourceTextures.get(self._icon(name), pixel_size=pixel_size)

    @staticmethod
    def _native_parent_tag(parent):
        """Resolve DearUIQt/QLayout wrappers to the native DearPyGui parent tag."""
        if parent is None:
            return None
        tag = getattr(parent, "tag", None)
        if tag is not None:
            return tag
        layout_tag = getattr(parent, "_layout_tag", None)
        if callable(layout_tag):
            try:
                resolved = layout_tag()
            except Exception:
                resolved = None
            if resolved is not None:
                return resolved
        return parent

    def _icon_action(self, label, icon_name, callback, *, parent, width=-1,
                     role="secondary", checkable=False, toggled=None):
        """Create one real QPushButton with a raster icon drawn inside its frame.

        Dear PyGui does not expose a native image+text push button.  Keep the
        retained QPushButton as the canonical control, then place a small draw
        layer over its left gutter.  The overlay forwards clicks to the same
        wrapper, so enable/disable, focus, default and checkable semantics stay
        on one control instead of rendering a second button beside it.
        """
        native_parent = self._native_parent_tag(parent)
        host_width = int(width) if isinstance(width, (int, float)) and int(width) > 0 else -1
        host_frame = QFrame(
            parent=native_parent, width=host_width, height=self.ICON_ACTION_HEIGHT,
            frame_shape=QFrame.NoFrame, no_scrollbar=True,
            no_scroll_with_mouse=True)
        host = host_frame.tag
        host_frame.setTheme(transparent_header_cell_theme())

        # Reserve a little optical room for the icon while preserving the
        # standard centered QPushButton caption and stable Qt-style height.
        display_label = "   " + str(label)
        if checkable:
            button = self._toggle_action(
                display_label,
                toggled if toggled is not None else callback,
                parent=host,
                width=-1,
            )
        else:
            button = self.action(
                display_label,
                callback,
                role=role,
                parent=host,
                width=-1,
                height=self.ICON_ACTION_HEIGHT,
            )

        texture = self._icon_texture(icon_name, pixel_size=32)
        if texture:
            overlay_widget = QCanvas(
                self.ICON_ACTION_GUTTER, self.ICON_ACTION_HEIGHT,
                parent=host, pos=(0, 0))
            overlay = overlay_widget.tag
            inset = max(3, (self.ICON_ACTION_HEIGHT - self.DECORATIVE_ICON_SIZE) // 2)
            image = QPainter(overlay_widget).drawImage(
                texture,
                (5, inset),
                (5 + self.DECORATIVE_ICON_SIZE, inset + self.DECORATIVE_ICON_SIZE),
                color=(255, 255, 255, 255))
            self._icon_action_draws[button] = image
            self._icon_action_canvases[button] = overlay_widget
            try:
                self.own_widget(QItemInputBinding(
                    overlay_widget, parent=self
                ).onClick(
                    Qt.LeftButton,
                    lambda *_args, tag=button: self._click_icon_action(tag),
                ).activate())
            except Exception:
                pass
        return button

    def _click_icon_action(self, button):
        wrapper = self._control_wrappers.get(button)
        if wrapper is not None:
            wrapper.click()

    def set_control_enabled(self, item, enabled):
        super().set_control_enabled(item, enabled)
        image = self._icon_action_draws.get(item)
        if image is not None:
            retained = QRetainedItem(image)
            if retained.exists():
                retained.configure(
                    color=(255, 255, 255, 255) if enabled else (155, 155, 155, 170))

    def _icon_only_action(self, icon_name, callback, *, parent, tooltip="", button_size=22):
        """Create a compact icon-only action for dense tool rows."""
        texture = self._icon_texture(icon_name, pixel_size=32)
        if not texture:
            return self.action("", callback, parent=parent, width=button_size, height=button_size)
        render_size = max(16, min(int(button_size) - 4, self.COMPACT_ICON_RENDER_SIZE))
        control = QToolButton(
            "", parent=self._native_parent_tag(parent), icon=texture,
            icon_size=(int(render_size), int(render_size)))
        control.clicked.connect(callback)
        button = control.tag
        control.setTheme(toolbar_fitted_icon_theme())
        if tooltip:
            self._add_help(button, tooltip)
        self._remember_focusable(button)
        return button

    def _build_settings_panel(self, parent):
        axes_page_layout = QVBoxLayout(parent=parent, spacing=0)
        axes_page = axes_page_layout.tag
        self._tool_pages["axes"] = axes_page
        self._build_axes_panel(axes_page)

        manual_page_layout = QVBoxLayout(parent=parent, spacing=0, show=False)
        manual_page = manual_page_layout.tag
        self._tool_pages["manual"] = manual_page
        with self.section("Manual Extraction", parent=manual_page) as panel:
            self.note("Add, edit and remove points directly on the chart image.", parent=panel, wrap=240)
            self.manual_commands = self.own_widget(ToolCommandRow(panel, after=self.view.after))
            self.add_point_button = self._icon_action(
                "Add Point (A)", "add_point", lambda: self._begin_pick("manual"),
                role="primary", parent=self.manual_commands.cell(0, 0), width=-1)
            self.edit_points_button = self._icon_action(
                "Edit Points (S)", "edit_points", self._toggle_edit_mode,
                parent=self.manual_commands.cell(0, 1), width=-1,
                checkable=True, toggled=self._edit_mode_toggled)
            self.delete_point_mode_button = self._icon_action(
                "Delete Point (D)", "delete_points", lambda: self._begin_pick("delete"),
                role="danger", parent=panel, width=-1)
            self._add_help(self.add_point_button, "Click the image to add points. Escape exits point picking.")
            self._add_help(self.edit_points_button, "Drag markers to refine their position. Arrow keys nudge the selected point.")

        auto_page_layout = QVBoxLayout(parent=parent, spacing=0, show=False)
        auto_page = auto_page_layout.tag
        self._tool_pages["automatic"] = auto_page
        self._build_auto_panel(auto_page)

        data_page_layout = QVBoxLayout(parent=parent, spacing=0, show=False)
        data_page = data_page_layout.tag
        self._tool_pages["data"] = data_page
        self._build_data_panel(data_page)

        preferences_layout = QVBoxLayout(parent=parent, spacing=0, show=False)
        self._tool_pages["settings"] = preferences_layout.tag
        self._build_plot_preferences_panel(preferences_layout.tag)
        self._build_point_editor(parent)

    def _build_plot_preferences_panel(self, parent):
        """A lightweight in-workspace settings page, not another modal/window."""
        with self.section("Canvas & markers", parent=parent) as panel:
            self.note("Display options apply immediately and are saved for future sessions. "
                      "They do not change chart data or saved calibration.", parent=panel, wrap=246)
            for key, title in (
                ("show_automatic_points", "Show extracted points"),
                ("show_manual_points", "Show manual points"),
                ("show_crosshair", "Show cursor crosshair"),
                ("show_magnifier", "Show magnifier preview"),
            ):
                self._preference_checkbox(key, title, panel)
            marker_form = self.form_layout(panel, label_width=100)
            control = self.form_layout_row(marker_form, "Marker size (%)", lambda host: self.spin_int(
                self._plot_preferences["marker_size_percent"], parent=host,
                minimum=50, maximum=250, step=10, width=-1,
                callback=lambda _sender, value, *_: self._preference_changed("marker_size_percent", value)))
            self._preference_controls["marker_size_percent"] = control
        with self.section("Navigation", parent=parent) as panel:
            self._preference_checkbox("mouse_wheel_zoom", "Mouse wheel zoom", panel)
            self._preference_checkbox("fit_images_on_open", "Fit newly opened images", panel)
            self.note("Existing .pdg projects preserve their saved pan/zoom.", parent=panel, wrap=246)
        with self.section("Defaults", parent=parent) as panel:
            self._icon_action("Restore Default Settings", "reset", self._reset_plot_preferences,
                              parent=panel, width=-1)

    def _preference_checkbox(self, key, title, parent):
        control = self.checkbox(title, checked=self._plot_preferences[key], parent=parent)
        self._preference_controls[key] = control
        self._control_wrappers[control].toggled.connect(
            lambda checked, setting=key: self._preference_changed(setting, checked))

    def _preference_changed(self, key, value):
        if self._preference_refreshing:
            return
        updated = dict(self._plot_preferences)
        updated[key] = value
        updated = PlotDigitizerPreferences.normalize(updated)
        if updated == self._plot_preferences:
            return
        self._plot_preferences = updated
        try:
            self._plot_preference_store.save(updated)
        except OSError as exc:
            self._set_status("Settings applied, but could not be saved: {}".format(exc))
        # Update the actual drawlist and hover hit-testing rather than merely
        # changing a checkbox without affecting the image.
        self._redraw()
        self._mouse_move()

    def _reset_plot_preferences(self):
        defaults = dict(PlotDigitizerPreferences.DEFAULTS)
        self._plot_preferences = defaults
        self._preference_refreshing = True
        try:
            for key, tag in self._preference_controls.items():
                widget = self._control_wrappers[tag]
                if key == "marker_size_percent":
                    widget.setValue(defaults[key])
                else:
                    widget.setChecked(defaults[key])
        finally:
            self._preference_refreshing = False
        try:
            self._plot_preference_store.save(defaults)
        except OSError as exc:
            self._set_status("Defaults applied, but could not be saved: {}".format(exc))
        else:
            self._set_status("Plot Digitizer settings restored to defaults.")
        self._redraw()
        self._mouse_move()

    def _marker_metrics(self, zoom, source):
        return marker_metrics(zoom, source, self._plot_preferences["marker_size_percent"] / 100.0)

    def _marker_visible(self, source):
        return self._plot_preferences["show_manual_points" if source == "manual" else "show_automatic_points"]

    def _build_axes_panel(self, parent):
        with self.section("Axes", parent=parent) as panel:
            self.note("Calibrate the chart first so extracted samples can be converted into real X/Y values.",
                      parent=panel, wrap=240)
            self.calibration_info = self.status_text("Calibration: 0 / 4 anchors", parent=panel)
            self.calibrate_button = self._icon_action(
                "Align Axes - Pick 4 Points", "calibrate_axes", self._start_calibration,
                role="primary", parent=panel, width=-1)
            self._add_help(self.calibrate_button, "Pick X1, X2, Y1 and Y2 on known axis ticks, enter their values, then apply calibration.")
            self.calibration_hint = self.note("", parent=panel, wrap=240)
            self.set_control_visible(self.calibration_hint, False)
            self.anchor_value = {}
            self.anchor_pick_buttons = {}
            x_form = self.form_layout(panel, label_width=26)
            for key, label in (("x1", "X1"), ("x2", "X2")):
                self._anchor_row(x_form, key, label)
            QSpacer(0, 4, parent=panel)
            y_form = self.form_layout(panel, label_width=26)
            for key, label in (("y1", "Y1"), ("y2", "Y2")):
                self._anchor_row(y_form, key, label)
            self.apply_calibration_button = self._icon_action(
                "Apply Calibration", "apply_changes", self._apply_calibration_values,
                role="primary", parent=panel, width=-1)
            with self.disclosure("Axis options", parent=panel) as options:
                self._disclosures["axes"] = QRetainedItem(options).parentItem()
                self.calibrate_area_button = self._icon_action(
                    "Calibrate Area", "plot_area", self._calibrate_area,
                    parent=options, width=-1)
                self._add_help(self.calibrate_area_button, "Map the entered axis values to the edges of the selected Box area.")
                scales = self.form_layout(options, label_width=48)
                self.scale_x = self.form_layout_row(scales, "X scale", lambda host: self.combo(
                    [s.value for s in AxisScale], parent=host,
                    default_value=AxisScale.LINEAR.value, callback=self._scale_changed))
                self.scale_y = self.form_layout_row(scales, "Y scale", lambda host: self.combo(
                    [s.value for s in AxisScale], parent=host,
                    default_value=AxisScale.LINEAR.value, callback=self._scale_changed))
                self.reset_axes_button = self._icon_action(
                    "Reset Axes", "reset", self.engine.reset_calibration,
                    parent=options, width=-1)

    def _build_auto_panel(self, parent):
        with self.section("Automatic Extraction", parent=parent) as panel:
            self.note("Sample the curve color, tune detection tolerance and extract points automatically.",
                      parent=panel, wrap=240)
            self.curve_color = self.own_widget(ColorField(panel, after=self.view.after))
            self.curve_color.changed.connect(self._color_changed)
            self.pick_curve_button = self._icon_action(
                "Sample Color", "sample_color", lambda: self._begin_pick("curve"),
                parent=self.curve_color.tag, width=94)
            self._add_help(self.pick_curve_button, "Click a curve stroke to sample its color. Use View > Box to restrict the extraction area.")
            self.palette_combo = self.combo(["Find image colors..."], parent=panel,
                                            default_value="Find image colors...", callback=self._palette_selected)
            self.set_control_visible(self.palette_combo, False)
            tolerance_form = self.form_layout(panel, label_width=100)
            self.tolerance = self.form_layout_row(tolerance_form, "Tolerance", lambda host: self.spin_int(
                55, parent=host, minimum=1, maximum=255, step=1, width=-1,
                callback=lambda _sender, value, *_: self._setting_changed("tolerance", value)))
            self.automatic_commands = self.own_widget(ToolCommandRow(panel, after=self.view.after))
            self.find_colors_button = self._icon_action(
                "Find Colors", "find_colors", self._auto_color,
                parent=self.automatic_commands.cell(0, 0), width=-1)
            self.extract_button = self._icon_action(
                "Extract Points", "extract_points", self._extract_curve,
                role="primary", parent=self.automatic_commands.cell(0, 1), width=-1)
            self.smart_button = self.extract_button
            with self.disclosure("Advanced", parent=panel) as advanced:
                self._disclosures["advanced"] = QRetainedItem(advanced).parentItem()
                self._build_extraction_options(advanced)

    def _build_point_editor(self, parent):
        point_editor_layout = QVBoxLayout(
            parent=parent, spacing=0, show=False)
        self.point_editor_container = point_editor_layout.tag
        with self.section("Point", parent=self.point_editor_container) as panel:
            self.point_navigation = self.own_widget(ToolCommandRow(
                panel, columns=3, column_widths=(30, None, 30), after=self.view.after))
            self.previous_point_button = self._icon_only_action(
                "previous_point", lambda: self._navigate_point(-1),
                parent=self.point_navigation.cell(0, 0), tooltip="Previous point (P)", button_size=22)
            self.point_info = self.status_text("", parent=self.point_navigation.cell(0, 1).tag)
            self.next_point_button = self._icon_only_action(
                "next_point", lambda: self._navigate_point(1),
                parent=self.point_navigation.cell(0, 2), tooltip="Next point (N)", button_size=22)
            self._add_help(self.previous_point_button, "Previous point (P)")
            self._add_help(self.next_point_button, "Next point (N)")
            point_fields_layout = QVBoxLayout(parent=panel, spacing=0)
            self.point_fields = point_fields_layout.tag
            form = self.form_layout(self.point_fields, label_width=28)
            self.point_x = self.form_layout_row(form, "X", lambda host: self.line_edit(
                "", parent=host, on_enter=True, callback=lambda *_: self._apply_point()))
            self.point_y = self.form_layout_row(form, "Y", lambda host: self.line_edit(
                "", parent=host, on_enter=True, callback=lambda *_: self._apply_point()))
            self.apply_point_button = self._icon_action(
                "Apply Point", "apply_changes", self._apply_point,
                parent=self.point_fields, width=-1)

    def _show_tool(self, tool):
        if tool not in self._tool_pages or tool == self._active_tool:
            return
        if self._pick_mode is not None:
            self._cancel_pick()
        self._active_tool = tool
        for name, page in self._tool_pages.items():
            self.set_control_visible(page, name == tool)
        self.active_table = self.result_grid if tool == "data" else None
        QRetainedItem(self.settings_panel).setVerticalScrollValue(0)
        if tool == "settings":
            # Settings is opened from the ribbon, not the workflow list. Clear
            # the previous workflow highlight; otherwise it misleadingly
            # looks as though a calibration/extraction page is still active.
            self.tool_list.clearSelection()
            self.tool_list.current = None
        elif self.tool_list.currentKey() != tool:
            self.tool_list.setCurrentKey(tool, select=True)
        self._refresh_point_editor()

    def _start_calibration(self):
        if self.engine.image is None:
            return self._set_status("Open an image first.")
        self._show_tool("axes")
        self._calibration_sequence = ["x1", "x2", "y1", "y2"]
        self._begin_pick("x1")

    def _apply_calibration_values(self):
        try:
            self.engine.set_anchor_values({key: float(self.control_value(item)) for key, item in self.anchor_value.items()})
            self.set_control_visible(self.calibration_hint, False)
            self._set_status("Axes calibrated. Choose Manual or Automatic Extraction to acquire data.")
        except ValueError as exc:
            self._set_status(str(exc))

    def _build_extraction_options(self, panel):
        settings_form = self.form_layout(panel, label_width=100)
        for key, label, value, minimum, maximum in (
            ("continuity", "Continuity (px)", 28, 1, 250),
            ("smoothing", "Smoothing", 3, 0, 30),
            ("stride", "Sample stride", 1, 1, 50),
            ("minimum_saturation", "Min saturation", 70, 0, 255),
            ("max_gap", "Max gap", 25, 0, 500),
        ):
            control = self.form_layout_row(
                settings_form, label,
                lambda host, v=value, lo=minimum, hi=maximum, k=key: self.spin_int(
                    v, parent=host, minimum=lo, maximum=hi, step=1, width=-1,
                    callback=lambda _sender, value, *_: self._setting_changed(k, value)))
            setattr(self, key, control)
        row = self.own_widget(ToolCommandRow(panel, after=self.view.after))
        self.detect_area_button = self._icon_action(
            "Detect Area", "detect_area", self._detect_area,
            parent=row.cell(0, 0), width=-1)
        self.reset_area_button = self._icon_action(
            "Reset Area", "reset", lambda: self.engine.set_plot_rect(None),
            parent=row.cell(0, 1), width=-1)
        self.roi_info = self.status_text("", parent=panel)

    def _anchor_row(self, table, key, label):
        def build(host):
            row_layout = QHBoxLayout(parent=host, spacing=5)
            self.anchor_value[key] = self.line_edit(
                "1" if key.endswith("2") else "0", parent=row_layout, width=-49,
                on_enter=True,
                callback=lambda _sender, value, *_: self._anchor_value_changed(key, value))
            self.anchor_pick_buttons[key] = self._icon_only_action(
                "pick_anchor", lambda: self._begin_pick(key), parent=row_layout,
                tooltip="Pick {} anchor".format(label), button_size=22)
        self.form_layout_row(table, label, build)

    def _anchor_value_changed(self, key, value):
        anchor = getattr(self.engine.calibration, key)
        if anchor is None:
            return
        try:
            self.engine.set_anchor(key, anchor.px, anchor.py, float(value))
        except ValueError as exc:
            self._set_status(str(exc))

    def _setting_changed(self, key, value):
        field = "max_gap_columns" if key == "max_gap" else key
        try:
            self.engine.set_settings(replace(self.engine.active_dataset.settings, **{field: int(value)}))
        except ValueError as exc:
            self._set_status(str(exc))
            self._refresh_dataset_controls()

    # ---------- engine / data ----------
    def _engine_changed(self, _event, _engine):
        if not self.winfo_exists():
            return
        # Engine events precede the deferred heavy UI refresh. Keep command
        # availability current even if a key/click follows in the same batch.
        self._refresh_history_commands()
        if _event in ("active_dataset_changed", "dataset_list_changed", "state_restored", "image_changed", "project_loaded"):
            self._clear_point_selection()
            self._hover_point = None
            self._drag_target = self._drag_preview = self._drag_start = None
            self._set_edit_enabled(False)
        if _event in ("active_dataset_changed", "dataset_list_changed", "image_changed", "project_loaded"):
            self._sample_pixel = None
        if _event in ("image_changed", "project_loaded"):
            self._preview_pixel = None
        if _event in ("image_changed", "project_loaded"):
            self._project_load_generation += 1
            self._calibration_sequence = []
            self._pick_mode = None
            self._show_tool("axes")
            self._palette = []
            if hasattr(self, "calibration_hint"):
                self.set_control_visible(self.calibration_hint, False)
            if hasattr(self, "palette_combo"):
                self.set_control_items(self.palette_combo, ["Find image colors..."])
            self.set_control_visible(self.palette_combo, False)
        if not self._refresh_pending:
            self._refresh_pending = True
            self.view.after(0, self._refresh_all)

    def _refresh_all(self):
        self._refresh_pending = False
        if not self.winfo_exists():
            return
        self._refresh_dataset_list()
        self._refresh_dataset_controls()
        self._refresh_grid()
        self._refresh_anchor_values()
        self._refresh_point_editor()
        self._refresh_workflow()
        self._refresh_history_commands()
        self._redraw()

    def _refresh_workflow(self):
        image = self.engine.image
        anchors = sum(getattr(self.engine.calibration, key) is not None for key in ("x1", "x2", "y1", "y2"))
        ds = self.engine.active_dataset
        self.set_control_value(self.project_info, Path(self.engine.image_path or "Embedded image").name if image is not None else "No image loaded")
        self.set_control_value(self._image_details, "{}\n{} x {} pixels".format(
            self.engine.image_path, image.width, image.height) if image is not None else "Open a chart image from Home.")
        has_image = image is not None
        for control in (self.calibrate_button, *self.anchor_pick_buttons.values(),
                        self.detect_area_button):
            self.set_control_enabled(control, has_image)
        self.set_control_enabled(self.apply_calibration_button, has_image and anchors == 4)
        self.set_control_enabled(self.calibrate_area_button, has_image and self.engine.plot_rect is not None)
        self.set_control_enabled(self.reset_axes_button, anchors > 0)
        self.set_control_enabled(self.reset_area_button, has_image and self.engine.plot_rect is not None)
        self.set_control_enabled(self.delete_dataset_button, len(self.engine.datasets) > 1 and not ds.locked)
        for key in ("fit", "one_to_one", "zoom_out", "zoom_in", "box"):
            self.ribbon.set_button_enabled(key, has_image)
        self.ribbon.set_button_enabled("save_project", True)
        self._refresh_export_controls()
        self._refresh_point_actions()

    def _refresh_export_controls(self):
        active = self.engine.active_dataset
        datasets = ([active] if self.control_value(self.export_scope) == "Active dataset" else self.engine.datasets)
        ready = self.engine.calibration_ready()
        can_export = ready and any(ds.extracted_pixels or ds.manual_points for ds in datasets)
        self.ribbon.set_button_enabled("export_csv", can_export)
        if hasattr(self, "export_data_button"):
            self.set_control_enabled(self.export_data_button, can_export)

    def _refresh_point_actions(self):
        if not hasattr(self, "delete_points_button"):
            return
        ds = self.engine.active_dataset
        has_points = bool(ds.extracted_pixels or ds.manual_points)
        selected = bool(self._selected_point is not None or self.result_grid.selectedKeys())
        self.set_control_enabled(self.delete_points_button, not ds.locked and selected)
        self.set_control_enabled(self.clear_points_button, not ds.locked and has_points)
        self.set_control_enabled(self.reduce_samples_button, not ds.locked and not self._smart_runner.busy and
                                 (len(ds.extracted_pixels) > 2 or len(ds.manual_points) > 2))
        self._refresh_data_summary()

    def _refresh_data_summary(self):
        if not hasattr(self, "data_summary"):
            return
        dataset = self.engine.active_dataset
        count = len(dataset.extracted_pixels) + len(dataset.manual_points)
        selected = len(self.result_grid.selectedKeys())
        if count:
            text = "{} | {} points | {} selected".format(dataset.name, count, selected)
            pixels = (self.control_value(self.coordinate_mode) == "Image pixels"
                      or not self.engine.calibration_ready())
            text += " | " + ("px" if pixels else "X/Y")
            if dataset.locked:
                text += " | Locked"
        else:
            text = "No points in this dataset. Use Manual or Automatic Extraction."
        if text != getattr(self, "_data_summary_text", None):
            self._data_summary_text = text
            self.set_control_value(self.data_summary, text)
            self._schedule_data_layout()
        self.set_control_enabled(self.select_all_points_button, count > 0)
        self.set_control_enabled(self.clear_selection_button,
                                 selected > 0 or self._selected_point is not None)

    def _select_all_data_points(self):
        self.result_grid.selectAll()
        self._refresh_point_actions()

    def _clear_data_selection(self):
        self._clear_point_selection()
        self._refresh_point_editor()
        self._redraw()

    def _refresh_dataset_list(self):
        self.dataset_list.setItems([
            QtListItem(i, "{}{}{}".format(ds.name,
                       " ({})".format(len(ds.extracted_pixels) + len(ds.manual_points))
                       if ds.extracted_pixels or ds.manual_points else "", " [Locked]" if ds.locked else ""),
                       ds, checked=ds.visible)
            for i, ds in enumerate(self.engine.datasets)
        ])
        # Avoid a tall empty list for a single curve; grow up to five rows,
        # then use the list's own scrolling for larger projects.
        row_height = self.dataset_list.rowHeight()
        self.dataset_list.setFixedHeight(min(5, max(2, len(self.engine.datasets))) * row_height + 2)
        if self.dataset_list.currentKey() != self.engine.active_dataset_index:
            self.dataset_list.setCurrentKey(self.engine.active_dataset_index, select=True)

    def _refresh_dataset_controls(self):
        if not self.winfo_exists():
            return
        ds = self.engine.active_dataset
        # Give each dataset its own InputText identity so Dear ImGui does not
        # reuse the previous dataset's cached text-edit buffer.
        QRetainedItem(self.dataset_name).configure(use_internal_label=False,
                           label="##{}_dataset_{}_{}".format(
                               self.tag, self.engine.active_dataset_index, hash(ds.name)))
        self._control_wrappers[self.dataset_name].setText(ds.name)
        self.set_control_enabled(self.dataset_name, not ds.locked)
        self.curve_color.setColor(ds.curve_rgb)
        unlocked = not ds.locked
        if not unlocked and self._edit_enabled:
            self._set_edit_enabled(False)
        has_image = self.engine.image is not None
        has_points = bool(ds.extracted_pixels or ds.manual_points)
        for control in (self.pick_curve_button, self.add_point_button, self.find_colors_button):
            self.set_control_enabled(control, unlocked and has_image)
        for control in (self.edit_points_button, self.delete_point_mode_button):
            self.set_control_enabled(control, unlocked and has_image and has_points)
        self._refresh_point_actions()
        can_extract = unlocked and self.engine.image is not None and not self._smart_runner.busy
        self.set_control_enabled(self.smart_button, can_extract)
        self.set_control_enabled(self.extract_button, can_extract)
        self.curve_color.setEnabled(unlocked and has_image)
        self.set_control_enabled(self.palette_combo, unlocked and has_image)
        for control, field in (("tolerance", "tolerance"), ("continuity", "continuity"),
                               ("smoothing", "smoothing"), ("stride", "stride"),
                               ("minimum_saturation", "minimum_saturation"),
                               ("max_gap", "max_gap_columns")):
            self.set_control_value(getattr(self, control), getattr(ds.settings, field))
            self.set_control_enabled(getattr(self, control), unlocked)

    def _refresh_grid(self):
        ds = self.engine.active_dataset
        rows = []
        index = 1
        calibrated = self.engine.calibration_ready()
        pixels = self.control_value(self.coordinate_mode) == "Image pixels" or not calibrated
        self.set_control_visible(self.data_coordinate_info, not calibrated)
        for i, (px, py) in enumerate(ds.extracted_pixels):
            x, y = (px, py) if pixels else (ds.extracted_data[i] if i < len(ds.extracted_data) else (None, None))
            rows.append(QtGridRow("auto:{}".format(i), (index, self._fmt(x), self._fmt(y))))
            index += 1
        for i, p in enumerate(ds.manual_points):
            x, y = (p.px, p.py) if pixels else (p.x, p.y)
            rows.append(QtGridRow("manual:{}".format(i), (index, self._fmt(x), self._fmt(y))))
            index += 1
        self.result_grid.setRows(rows)
        self._refresh_point_editor()

    def _refresh_anchor_values(self):
        cal = self.engine.calibration
        self.set_control_value(self.scale_x, cal.scale_x.value)
        self.set_control_value(self.scale_y, cal.scale_y.value)
        for key in ("x1", "x2", "y1", "y2"):
            anchor = getattr(cal, key)
            if anchor is not None:
                self.set_control_value(self.anchor_value[key], self._fmt(anchor.value))
        count = sum(getattr(cal, key) is not None for key in ("x1", "x2", "y1", "y2"))
        self.set_control_value(self.calibration_info, "X [{} .. {}]  Y [{} .. {}]".format(
            self._fmt(cal.x1.value), self._fmt(cal.x2.value), self._fmt(cal.y1.value), self._fmt(cal.y2.value)) if cal.ready()
                      else "Calibration: {} / 4 anchors".format(count))
        self.set_control_value(self.roi_info, "Area: {}".format(self.engine.plot_rect or "full image / calibrated bounds"))

    @staticmethod
    def _fmt(value):
        if value is None:
            return ""
        try:
            return "{:.10g}".format(float(value))
        except Exception:
            return str(value)

    def _dataset_name_changed(self, _sender=None, value=None, _user_data=None):
        text = str(value if value is not None else self.control_value(self.dataset_name)).strip()
        if text:
            self.engine.update_dataset(name=text)

    def _dataset_selected(self, index):
        target = self.dataset_list.itemData(index)
        current = self._dataset_index_for_object(target)
        if current is not None:
            self.engine.set_active_dataset(current)

    def _dataset_index_for_object(self, target):
        return next((index for index, dataset in enumerate(self.engine.datasets) if dataset is target), None)

    def _dataset_visibility_changed(self, key, visible):
        index = self._dataset_index_for_object(self.dataset_list.itemData(key))
        if index is None:
            self._refresh_dataset_list()
            return
        self.engine.update_dataset(visible=bool(visible), dataset_index=index)

    def _dataset_context_open(self, key, position):
        target = self.dataset_list.itemData(key)
        index = self._dataset_index_for_object(target)
        if index is None:
            return
        self.engine.set_active_dataset(index)
        self._refresh_dataset_list()
        action = "unlock" if target.locked else "lock"
        self.dataset_menu.setActions([{"label": "Unlock" if target.locked else "Lock", "action": action}])
        self.dataset_menu.popup(position, context=target)

    def _dataset_context_action(self, action, target):
        index = self._dataset_index_for_object(target)
        if index is not None and action in ("lock", "unlock"):
            self.engine.update_dataset(locked=action == "lock", dataset_index=index)

    def _add_dataset(self):
        self.engine.add_dataset()

    def _delete_dataset(self):
        try:
            self.engine.remove_dataset(self.engine.active_dataset_index)
        except ValueError as exc:
            self._set_status(str(exc))

    def _settings(self):
        return ExtractionSettings(
            tolerance=int(self.control_value(self.tolerance)),
            continuity=int(self.control_value(self.continuity)),
            smoothing=int(self.control_value(self.smoothing)),
            stride=int(self.control_value(self.stride)),
            minimum_saturation=int(self.control_value(self.minimum_saturation)),
            max_gap_columns=int(self.control_value(self.max_gap)),
        )

    def _scale_changed(self, *_args):
        try:
            self.engine.set_axis_scale(self.control_value(self.scale_x), self.control_value(self.scale_y))
        except ValueError as exc:
            self._set_status(str(exc))
            self._refresh_anchor_values()

    def _detect_area(self):
        if not self.engine.image:
            return self._set_status("Open an image first.")
        ok = self.engine.detect_plot_area()
        self._set_status("Plot area detected." if ok else "Could not detect plot area.")

    def _auto_color(self):
        if not self.engine.image:
            return self._set_status("Open an image first.")
        self._palette = detect_curve_colors(self.engine.image, self.engine.plot_roi(),
                                             int(self.control_value(self.minimum_saturation)))
        labels = ["#{:02X}{:02X}{:02X}".format(*rgb) for rgb in self._palette]
        self.set_control_items(self.palette_combo, labels or ["No colored curves found"])
        self.set_control_visible(self.palette_combo, len(labels) > 1)
        self.set_control_value(self.palette_combo, labels[0] if labels else "No colored curves found")
        if self._palette:
            try:
                self._sample_pixel = None
                self.engine.set_curve_color(self._palette[0])
            except ValueError as exc:
                return self._set_status(str(exc))
        self._set_status("Found {} distinct colors. Choose one color per dataset.".format(len(self._palette))
                         if self._palette else "No colored strokes found. Use Pick Color for a black or gray curve.")

    def _palette_selected(self, _sender, value, *_args):
        self._color_changed(value)

    def _color_changed(self, value):
        try:
            text = str(value).strip().lstrip("#")
            if len(text) != 6:
                raise ValueError("Enter a curve color as #RRGGBB.")
            self._sample_pixel = None
            self.engine.set_curve_color(tuple(int(text[i:i+2], 16) for i in (0, 2, 4)))
        except ValueError as exc:
            self._set_status(str(exc))

    def _calibrate_area(self):
        try:
            values = [float(self.control_value(self.anchor_value[key])) for key in ("x1", "x2", "y1", "y2")]
            self.engine.calibrate_plot_rect(*values)
            self._set_status("Plot area calibrated using the entered chart tick values.")
        except ValueError as exc:
            self._set_status(str(exc))

    def _undo(self):
        if self.engine.undo():
            self._cancel_pick()
            self._set_status("Last edit undone.")

    def _refresh_history_commands(self):
        for key, command in getattr(self, "_history_actions", {}).items():
            if not command._deleted:
                command.setEnabled(self.engine.can_undo if key == "undo" else self.engine.can_redo)

    def _trigger_history_command(self, key):
        if not self.winfo_exists():
            return False
        self._refresh_history_commands()
        return self._history_actions[key].trigger()

    def _redo(self):
        if self.engine.redo():
            self._cancel_pick()
            self._set_status("Edit restored.")

    def _extract_curve(self):
        if not self.engine.image:
            return self._set_status("Open an image first.")
        self._show_tool("automatic")
        if self.engine.active_dataset.curve_rgb is None:
            return self._start_extraction(auto_detect=True)
        self._start_extraction(auto_detect=False)

    def _extraction_status(self, ok, dataset_index=None):
        if not ok:
            return self._set_status("No curve points were found. Check color and tolerance.")
        ds = self.engine.active_dataset if dataset_index is None else self.engine.datasets[dataset_index]
        if not self.engine.calibration_ready():
            self._set_status("Found {} curve pixels. Set X1, X2, Y1, Y2 to obtain chart X / Y data.".format(
                len(ds.extracted_pixels)))
        else:
            self._set_status("Extracted {} X / Y points. Review data or export CSV.".format(
                len(ds.extracted_data)))

    def _smart_detect(self):
        self._start_extraction(auto_detect=True)

    def _start_extraction(self, *, auto_detect):
        if not self.engine.image:
            return self._set_status("Open an image first.")
        if self.engine.active_dataset.locked:
            return self._set_status("Unlock this dataset before extracting.")
        if self._smart_runner.busy:
            return
        settings = self._settings()
        dataset_index = self.engine.active_dataset_index
        self.set_control_enabled(self.smart_button, False)
        self.set_control_enabled(self.extract_button, False)
        self._set_status("Extracting curve in the background...")
        if not self._smart_runner.submit(settings, dataset_index, self._smart_finished, auto_detect=auto_detect):
            self._refresh_dataset_controls()
        self._refresh_workflow()

    def _smart_finished(self, result, settings, dataset_index, error):
        if not self.winfo_exists():
            return
        self.set_control_enabled(self.smart_button, True)
        self.set_control_enabled(self.extract_button, True)
        self._refresh_dataset_controls()
        self._refresh_workflow()
        if error:
            return self._set_status("Extraction stopped: {}".format(error))
        if result is None or result.error:
            return self._set_status("Extraction failed: {}".format(result.error if result else "Unknown error"))
        try:
            if self.engine.apply_smart_detect_result(result, settings, dataset_index=dataset_index):
                self._clear_point_selection()
                self._extraction_status(True, dataset_index)
            else:
                self._set_status("No usable curve found. Pick the stroke color and select its plot area.")
        except ValueError as exc:
            self._set_status(str(exc))

    def _set_edit_enabled(self, enabled):
        enabled = bool(enabled)
        if enabled and self.engine.active_dataset.locked:
            enabled = False
        self._edit_enabled = enabled
        wrapper = self._control_wrappers.get(getattr(self, "edit_points_button", None))
        if wrapper is not None and wrapper.isChecked() != enabled:
            wrapper.setChecked(enabled)
        if not enabled:
            self._drag_target = None
            self._drag_preview = None
            self._hover_point = None
        self._paint_pointer()

    def _edit_mode_toggled(self, enabled):
        if enabled and self.engine.active_dataset.locked:
            self._set_edit_enabled(False)
            return self._set_status("Unlock this dataset before editing its points.")
        if enabled and self.engine.image is None:
            self._set_edit_enabled(False)
            return self._set_status("Open an image first.")
        if enabled:
            if self._pick_mode is not None:
                self._cancel_pick()
            self._show_tool("manual")
            self._edit_enabled = True
            self._set_status("Edit Points enabled. You can drag any marker to reposition it.")
        else:
            self._edit_enabled = False
            self._drag_target = self._drag_preview = None
            self._hover_point = None
            self._set_status("Edit Points disabled. Markers can still be dragged directly when selected.")
        self._redraw()

    def _toggle_edit_mode(self):
        wrapper = self._control_wrappers.get(getattr(self, "edit_points_button", None))
        if wrapper is None:
            return
        if self.engine.active_dataset.locked:
            return self._set_status("Unlock this dataset before editing its points.")
        if self.engine.image is None:
            return self._set_status("Open an image first.")
        wrapper.setChecked(not wrapper.isChecked())

    # ---------- point editing ----------
    def _clear_point_selection(self):
        self._selected_point = None
        if hasattr(self, "result_grid"):
            self.result_grid.current = None
            self.result_grid.anchor = None
            self.result_grid.clearSelection()

    @staticmethod
    def _key_point(key):
        if not key:
            return None
        source, index = str(key).split(":", 1)
        return source, int(index)

    def _point_selected(self, key):
        self._selected_point = self._key_point(key)
        if self._selected_point is not None and self._active_tool != "data":
            self._show_tool("manual")
        self._refresh_point_editor()
        self._redraw()

    def _point_keys(self):
        dataset = self.engine.active_dataset
        return ([("auto", index) for index in range(len(dataset.extracted_pixels))] +
                [("manual", index) for index in range(len(dataset.manual_points))])

    def _navigate_point(self, step):
        keys = self._point_keys()
        if not keys or step not in (-1, 1):
            return False
        if self._selected_point in keys:
            position = keys.index(self._selected_point) + step
            if not 0 <= position < len(keys):
                return False
        else:
            position = 0 if step == 1 else len(keys) - 1
        if self._pick_mode is not None:
            self._cancel_pick()
        key = keys[position]
        if self.engine.image is not None:
            px, py = self.engine.point_pixels(*key)
            x, y = self._image_to_canvas(px, py)
            _, (width, height) = self._canvas_rect()
            if not (0 <= x < width and 0 <= y < height):
                scale = self._fit_scale * self._zoom
                self._pan = [width / 2 - px * scale, height / 2 - py * scale]
                self._auto_fit = False
        text_key = "{}:{}".format(*key)
        if not any(row_key == text_key for row_key, _values in self.result_grid.rows):
            self._refresh_grid()
        self.result_grid.setCurrentKey(text_key, select=True)
        if self._selected_point != key:
            self._point_selected(text_key)
        return True

    def _refresh_point_editor(self):
        if not hasattr(self, "point_info"):
            return
        self._schedule_data_layout()
        self._refresh_point_actions()
        selected = self._selected_point
        keys = self._point_keys()
        show = bool(keys) and self._active_tool in ("manual", "data")
        self.set_control_visible(self.point_editor_container, show)
        if selected is None:
            self.set_control_visible(self.point_fields, False)
            self.set_control_value(self.point_info, "Select a point")
            self.set_control_enabled(self.previous_point_button, bool(keys))
            self.set_control_enabled(self.next_point_button, bool(keys))
            self._control_wrappers[self.point_x].setText("")
            self._control_wrappers[self.point_y].setText("")
            self.set_control_enabled(self.apply_point_button, False)
            return
        try:
            px, py = self.engine.point_pixels(*selected)
        except (IndexError, ValueError):
            self._selected_point = None
            return self._refresh_point_editor()
        self.set_control_visible(self.point_fields, True)
        in_pixels = self.control_value(self.coordinate_mode) == "Image pixels" or not self.engine.calibration_ready()
        x, y = (px, py) if in_pixels else self.engine.pixel_to_data(px, py)
        editable = not self.engine.active_dataset.locked
        identity = hash((selected, in_pixels, x, y, editable))
        for field, value, label in ((self.point_x, x, "x"), (self.point_y, y, "y")):
            # Point changes need a fresh InputText identity, not the previous
            # marker's cached edit buffer. Preserve retained wrapper values too.
            QRetainedItem(field).configure(use_internal_label=False,
                               label="##{}_point_{}_{}".format(self.tag, label, identity))
            self._control_wrappers[field].setText(self._fmt(value))
            if self.control_value(field) != self._fmt(value):
                self.set_control_value(field, self._fmt(value))
            self.set_control_enabled(field, editable)
        position = keys.index(selected)
        self.set_control_value(self.point_info, "{} {}/{} | {}".format(
            "Auto" if selected[0] == "auto" else "Manual", position + 1, len(keys),
            "px" if in_pixels else "X/Y"))
        self.set_control_enabled(self.previous_point_button, position > 0)
        self.set_control_enabled(self.next_point_button, position < len(keys) - 1)
        self.set_control_enabled(self.apply_point_button, editable)

    def _apply_point(self):
        if self._selected_point is None:
            return self._set_status("Select a point first.")
        try:
            x, y = float(self.control_value(self.point_x)), float(self.control_value(self.point_y))
            if self.control_value(self.coordinate_mode) == "Image pixels" or not self.engine.calibration_ready():
                self.engine.move_point(*self._selected_point, x, y)
            else:
                self.engine.set_point_values(*self._selected_point, x, y)
            self._set_status("Point updated. Ctrl+Z undoes the edit.")
        except (ValueError, IndexError) as exc:
            self._set_status(str(exc))

    def _delete_points(self):
        points = [self._key_point(key) for key in self.result_grid.selectedKeys()]
        if not points and self._selected_point is not None:
            points = [self._selected_point]
        if not points:
            return self._set_status("Select points in the table or on the image first.")
        try:
            self.engine.remove_points(points)
            self._clear_point_selection()
            self._set_status("Deleted {} point(s). Ctrl+Z restores them.".format(len(points)))
        except (ValueError, IndexError) as exc:
            self._set_status(str(exc))

    def _clear_points(self):
        try:
            self.engine.clear_points()
            self._clear_point_selection()
            self._set_status("Dataset points cleared. Ctrl+Z restores them.")
        except ValueError as exc:
            self._set_status(str(exc))

    def _reduce_samples(self):
        if self._smart_runner.busy:
            return self._set_status("Wait for extraction to finish before reducing samples.")
        ds = self.engine.active_dataset
        before = len(ds.extracted_pixels) + len(ds.manual_points)
        try:
            removed = self.engine.reduce_samples(float(self.control_value(self.reduction_error)))
            if removed:
                self._cancel_pick()
                self._clear_point_selection()
                self._refresh_point_editor()
                self._set_status("Reduced samples: {} -> {} (removed {}). Ctrl+Z restores them.".format(
                    before, before - removed, removed))
            else:
                self._set_status("No redundant samples found at this error tolerance.")
        except ValueError as exc:
            self._set_status(str(exc))

    # ---------- canvas ----------
    def _install_mouse_handlers(self):
        binding = QGlobalInputBinding(backend=_renderer_backend(), parent=self)
        binding.onMouseClick(Qt.LeftButton, self._mouse_left)
        binding.onMouseRelease(Qt.LeftButton, self._mouse_left_up)
        binding.onMouseClick(Qt.MiddleButton, self._mouse_middle_down)
        binding.onMouseRelease(Qt.MiddleButton, self._mouse_middle_up)
        binding.onMouseMove(self._mouse_move)
        binding.onMouseWheel(self._mouse_wheel)
        for key in (Qt.Key_Z, Qt.Key_Y, Qt.Key_Delete,
                    Qt.Key_A, Qt.Key_S, Qt.Key_D, Qt.Key_N, Qt.Key_P,
                    Qt.Key_Left, Qt.Key_Right, Qt.Key_Up, Qt.Key_Down):
            binding.onKeyPress(key, self._edit_key, user_data=key)
        self._input_binding = binding.activate()
        self._handler_registry = None  # compatibility: no native registry escapes DearUIQt

    def _edit_key(self, _sender, _app_data=None, key=None):
        if key is None:
            key = QGlobalInputBinding.qtKeyForNative(_app_data, _renderer_backend())
        if not self._accepts_edit_shortcut():
            return
        modifiers = QKeyboard.modifiers(backend=_renderer_backend())
        if modifiers & (Qt.AltModifier | Qt.MetaModifier):
            return
        ctrl = bool(modifiers & Qt.ControlModifier)
        shift = bool(modifiers & Qt.ShiftModifier)
        if not ctrl and key in (Qt.Key_N, Qt.Key_P) and self._active_tool in ("manual", "data"):
            self._navigate_point(1 if key == Qt.Key_N else -1)
            return
        if ctrl and key == Qt.Key_Z:
            self._trigger_history_command("redo" if shift else "undo")
        elif ctrl and not shift and key == Qt.Key_Y:
            self._trigger_history_command("redo")
        elif not ctrl and key == Qt.Key_Delete and (self._mouse_in_canvas() or self.result_grid.hasFocus()):
            self._delete_points()
        elif not ctrl and self._mouse_in_canvas():
            modes = {Qt.Key_A: "manual", Qt.Key_D: "delete"}
            if key == Qt.Key_S:
                self._toggle_edit_mode()
            elif key in modes:
                self._begin_pick(modes[key])
            elif self._selected_point is not None and key in (Qt.Key_Left, Qt.Key_Right, Qt.Key_Up, Qt.Key_Down):
                step = 10 if shift else 1
                dx = -step if key == Qt.Key_Left else step if key == Qt.Key_Right else 0
                dy = -step if key == Qt.Key_Up else step if key == Qt.Key_Down else 0
                try:
                    px, py = self.engine.point_pixels(*self._selected_point)
                    self.engine.move_point(*self._selected_point,
                        max(0, min(self.engine.image.width - 1, px + dx)),
                        max(0, min(self.engine.image.height - 1, py + dy)))
                except (ValueError, IndexError) as exc:
                    self._set_status(str(exc))

    def _accepts_edit_shortcut(self):
        """Local editor shortcut scope, not an application-wide key dispatcher."""
        if not self.winfo_exists():
            return False
        if hasattr(self, "_visible_state"):
            if not self.isVisible():
                return False
        else:
            # Compatibility for partially constructed host/test objects. Real
            # QtDialog instances use the retained visibility state above.
            try:
                if not QRetainedItem(self.tag, backend=_renderer_backend()).isVisible():
                    return False
            except Exception:
                pass
        from DearUIQt.input_gate import native_modal_input_active
        if native_modal_input_active():
            return False
        selector = getattr(getattr(self, "_file_dialog", None), "dialog", None)
        if selector is not None and selector.winfo_exists():
            return False
        menu = getattr(self, "dataset_menu", None)
        if menu is not None and not getattr(menu, "_deleted", False):
            visible = getattr(menu, "isVisible", None)
            if callable(visible):
                if visible():
                    return False
            else:
                try:
                    if QRetainedItem(getattr(menu, "tag", menu), backend=_renderer_backend()).isVisible():
                        return False
                except Exception:
                    pass
        resolver = getattr(self.view, "_find_main_viewport_hwnd", None)
        hwnd = resolver() if callable(resolver) else 0
        if hwnd:
            from ...ui.native.dialog_focus import foreground_hwnd, window_state
            if foreground_hwnd() != hwnd or not all(window_state(hwnd)):
                return False
        focused_item = QRetainedItem.focusedItem(backend=_renderer_backend())
        if focused_item is not None:
            try:
                item_type = focused_item.itemType()
                if any(kind in item_type for kind in ("Input", "Combo", "Slider", "Drag", "Color")):
                    return False
                # Embedded/test hosts can contain sibling tool windows. Their
                # buttons/tables must not route document commands to this one.
                visited = set()
                item = focused_item.tag
                while item and item != self.tag and item not in visited:
                    visited.add(item)
                    item = QRetainedItem(item, backend=_renderer_backend()).parentItem()
                if item != self.tag:
                    return False
            except Exception:
                # A stale focus ID during deferred widget deletion is not
                # permission to edit the document behind it.
                return False
        return True

    def _mouse_in_canvas(self):
        return self._canvas_widget.exists() and self._canvas_widget.underMouse()

    def _canvas_rect(self):
        try:
            rect = self._canvas_widget.globalGeometry()
            return rect.topLeft().toTuple(), (rect.width(), rect.height())
        except Exception:
            return (0, 0), (1, 1)

    def _image_to_canvas(self, px, py):
        scale = self._fit_scale * self._zoom
        return self._pan[0] + px * scale, self._pan[1] + py * scale

    def _canvas_to_image(self, mouse):
        (ox, oy), _ = self._canvas_rect()
        scale = self._fit_scale * self._zoom
        if scale <= 0:
            return None
        return ((mouse[0] - ox - self._pan[0]) / scale,
                (mouse[1] - oy - self._pan[1]) / scale)

    def _begin_pick(self, mode):
        if self.engine.image is None:
            return self._set_status("Open an image first.")
        if mode in ("curve", "manual", "edit", "delete") and self.engine.active_dataset.locked:
            return self._set_status("Unlock this dataset before editing its curve.")
        if mode == "edit":
            self._show_tool("manual")
            wrapper = self._control_wrappers.get(self.edit_points_button)
            if wrapper is not None and not wrapper.isChecked():
                wrapper.setChecked(True)
            return
        if mode in ("manual", "delete") and self._edit_enabled:
            self._set_edit_enabled(False)
        if not self._calibration_sequence or mode != self._calibration_sequence[0]:
            self._calibration_sequence = []
        if mode in ("manual", "edit", "delete"):
            self._show_tool("manual")
        elif mode == "curve":
            self._show_tool("automatic")
        elif mode in ("x1", "x2", "y1", "y2"):
            self._show_tool("axes")
        self._pick_mode = mode
        help_text = {"area": "Drag a rectangle around the plot axes, excluding titles and legends.",
                     "delete": "Click a point to delete it. Ctrl+Z restores deleted points.",
                     "edit": "Drag a marker to move it.",
                     "curve": "Click directly on the curve stroke to sample its color.",
                     "manual": "Click to add points. Use the magnifier for precision."}
        self._set_status(help_text.get(mode, "Click the known {} tick on the image.".format(mode.upper())) + " Esc cancels.")
        if self._calibration_sequence:
            self.set_control_visible(self.calibration_hint, True)
            self.set_control_value(self.calibration_hint, "Step {} / 4: click {} on the image. Use the magnifier for precision.".format(
                5 - len(self._calibration_sequence), mode.upper()))

    def _cancel_pick(self):
        self._pick_mode = None
        self._calibration_sequence = []
        if hasattr(self, "calibration_hint"):
            self.set_control_value(self.calibration_hint, "")
            self.set_control_visible(self.calibration_hint, False)
        self._drag_start = self._drag_preview = self._drag_target = None
        self._paint_pointer()
        self._set_status("Ready.")

    def _mouse_left(self, *_args):
        if not self._mouse_in_canvas() or self.engine.image is None:
            return
        mouse = QCursor.pos().toTuple()
        p = self._canvas_to_image(mouse)
        if p is None:
            return
        if not (0 <= p[0] < self.engine.image.width and 0 <= p[1] < self.engine.image.height):
            return
        px, py = p
        mode = self._pick_mode
        if mode in ("x1", "x2", "y1", "y2"):
            try:
                value = float(self.control_value(self.anchor_value[mode]))
                self.engine.set_anchor(mode, px, py, value)
                self._pick_mode = None
                if self._calibration_sequence and mode == self._calibration_sequence[0]:
                    self._calibration_sequence.pop(0)
                    if self._calibration_sequence:
                        self._begin_pick(self._calibration_sequence[0])
                    else:
                        self.set_control_value(self.calibration_hint, "All 4 points selected. Enter the tick values and click Apply Calibration.")
                        self._set_status("Axis points selected. Enter the known tick values and Apply Calibration.")
                else:
                    self._set_status("{} anchor set.".format(mode.upper()))
            except ValueError as exc:
                self._set_status(str(exc))
        elif mode == "curve":
            try:
                rgb = self.engine.sample_curve_color(px, py)
                self._sample_pixel = None
                self._pick_mode = None
                self._set_status(
                    "Sampled #{:02X}{:02X}{:02X}. Extract Points will follow pixels within the selected color tolerance.".format(*rgb))
                self._redraw()
            except ValueError as exc:
                self._set_status(str(exc))
        elif mode == "manual":
            try:
                self.engine.add_manual_point(px, py)
                index = len(self.engine.active_dataset.manual_points) - 1
                self._selected_point = ("manual", index)
                self.result_grid.setCurrentKey("manual:{}".format(index), select=True)
                self._set_status("Manual point added and selected. Keep clicking to add points; Esc exits Add Point mode.")
            except ValueError as exc:
                self._set_status(str(exc))
        elif mode == "area":
            self._drag_start = (px, py)
            self._drag_preview = (px, py)
        elif mode == "delete":
            selected = self._nearest_point(px, py)
            if selected is not None:
                try:
                    self.engine.remove_points([selected])
                    self._clear_point_selection()
                    self._set_status("Point deleted. Ctrl+Z restores it; click another point or Esc to finish.")
                except (ValueError, IndexError) as exc:
                    self._set_status(str(exc))
        elif mode in (None, "edit"):
            selected = self._nearest_point(px, py)
            if selected is not None:
                self._selected_point = selected
                self.result_grid.setCurrentKey("{}:{}".format(*selected), select=True)
                if not self.engine.active_dataset.locked:
                    self._drag_target = selected
                    self._drag_preview = self.engine.point_pixels(*selected)
                self._refresh_point_editor()
                self._redraw()

    def _nearest_point(self, px, py):
        ds = self.engine.active_dataset
        if not ds.visible:
            return None
        scale = max(.001, self._fit_scale * self._zoom)
        closest, best = None, None
        for source, points in (("auto", ds.extracted_pixels),
                               ("manual", [(p.px, p.py) for p in ds.manual_points])):
            if source == "auto" and not self._plot_preferences["show_automatic_points"]:
                continue
            if source == "manual" and not self._plot_preferences["show_manual_points"]:
                continue
            hit_radius = self._marker_metrics(scale, source).hit_radius / scale
            radius2 = hit_radius ** 2
            for index, (x, y) in enumerate(points):
                distance = (x - px) ** 2 + (y - py) ** 2
                if distance <= radius2 and (best is None or distance <= best):
                    closest, best = (source, index), distance
        return closest

    def _mouse_left_up(self, *_args):
        if self._drag_start is None and self._drag_target is None:
            return
        point = self._canvas_to_image(QCursor.pos().toTuple())
        if point is None or self.engine.image is None:
            return self._cancel_pick()
        px = max(0, min(self.engine.image.width - 1, point[0]))
        py = max(0, min(self.engine.image.height - 1, point[1]))
        try:
            if self._drag_start is not None:
                self.engine.set_plot_rect((*self._drag_start, px, py))
                self._pick_mode = None
                self._set_status("Plot area selected. Enter axis bounds and Calibrate Area, or Pick each tick.")
            elif self._drag_target is not None:
                if self._drag_preview is not None:
                    px = max(0, min(self.engine.image.width - 1, self._drag_preview[0]))
                    py = max(0, min(self.engine.image.height - 1, self._drag_preview[1]))
                old_px, old_py = self.engine.point_pixels(*self._drag_target)
                if abs(px - old_px) > 1e-9 or abs(py - old_py) > 1e-9:
                    self.engine.move_point(*self._drag_target, px, py)
                    self._set_status("Point moved. Ctrl+Z undoes the move.")
                else:
                    self._set_status("Point selected. Drag the marker to reposition it.")
        except (ValueError, IndexError) as exc:
            self._set_status(str(exc))
        finally:
            self._drag_start = self._drag_preview = self._drag_target = None
            self._redraw()

    def _mouse_middle_down(self, *_args):
        if self._mouse_in_canvas():
            self._auto_fit = False
            self._middle_drag = True
            self._last_mouse = QCursor.pos().toTuple()
            self._cursor_canvas = self._cursor_pixel = None
            self._hover_point = None
            self._cursor_over_marker = False
            self._paint_pointer()

    def _mouse_middle_up(self, *_args):
        self._middle_drag = False
        self._mouse_move()

    def _mouse_move(self, *_args):
        now = QCursor.pos().toTuple()
        if self._middle_drag:
            self._pan[0] += now[0] - self._last_mouse[0]
            self._pan[1] += now[1] - self._last_mouse[1]
            self._last_mouse = now
            self._redraw()
            return
        inside = self._mouse_in_canvas()
        (ox, oy), (width, height) = self._canvas_rect()
        local = (now[0] - ox, now[1] - oy)
        self._cursor_canvas = local if inside and 0 <= local[0] < width and 0 <= local[1] < height else None
        self._cursor_over_marker = False
        point = self._canvas_to_image(now) if inside and self.engine.image is not None else None
        if point is not None:
            self._preview_pixel = (
                max(0., min(self.engine.image.width - 1., point[0])),
                max(0., min(self.engine.image.height - 1., point[1])))
        if point is not None and 0 <= point[0] < self.engine.image.width and 0 <= point[1] < self.engine.image.height:
            self._cursor_pixel = point
            self._cursor_over_marker = cursor_hits_marker(
                self.engine.datasets, *point, self._fit_scale * self._zoom,
                size_scale=self._plot_preferences["marker_size_percent"] / 100.0,
                show_automatic=self._plot_preferences["show_automatic_points"],
                show_manual=self._plot_preferences["show_manual_points"])
            if self._drag_start is not None or self._drag_target is not None:
                self._drag_preview = point
            if self._drag_target is None and self._pick_mode in (None, "edit") and not self.engine.active_dataset.locked:
                self._hover_point = self._nearest_point(*point)
            else:
                self._hover_point = None
        else:
            self._cursor_pixel = None
            self._hover_point = None
        self._paint_pointer()

    def _canvas_pointer_tick(self):
        """Refresh hover even while stationary, after pan/zoom or popup changes."""
        self._layout_canvas()
        if self._middle_drag:
            self._sync_canvas_cursor()
        else:
            self._mouse_move()
        schedule = getattr(self.view, "after_render", None)
        if callable(schedule):
            schedule(self._sync_canvas_cursor)

    def _sync_canvas_cursor(self):
        cursor = getattr(self, "_canvas_cursor", None)
        if cursor is None:
            return
        if not self.winfo_exists() or not self.isVisible():
            cursor.update(None)
            return
        mode = ("move" if self._middle_drag else
                "blank" if self._cursor_canvas is not None and self._plot_preferences["show_crosshair"] else None)
        (x, y), (width, height) = self._canvas_rect()
        cursor.update(mode, (x, y, x + width, y + height), capture=self._middle_drag,
                      screen_coordinates=self._native_window_backend is not None)

    def _mouse_wheel(self, _sender, app_data):
        if (self._plot_preferences["mouse_wheel_zoom"] and
                self._mouse_in_canvas() and self.engine.image is not None):
            self._zoom_at(1.12 if app_data > 0 else 1 / 1.12, mouse=QCursor.pos().toTuple())

    def _zoom_at(self, factor, mouse=None):
        if self.engine.image is None:
            return
        self._auto_fit = False
        (ox, oy), (cw, ch) = self._canvas_rect()
        local = (mouse[0] - ox, mouse[1] - oy) if mouse is not None else (cw / 2, ch / 2)
        old_scale = self._fit_scale * self._zoom
        anchor = ((local[0] - self._pan[0]) / old_scale, (local[1] - self._pan[1]) / old_scale)
        self._zoom = max(0.05, min(40.0, self._zoom * float(factor)))
        new_scale = self._fit_scale * self._zoom
        self._pan = [local[0] - anchor[0] * new_scale, local[1] - anchor[1] * new_scale]
        self._redraw()

    def _fit_view(self):
        self._auto_fit = True
        if self.engine.image is None:
            return
        _, (cw, ch) = self._canvas_rect()
        if cw <= 2 or ch <= 2:
            return
        iw, ih = self.engine.image.size
        self._fit_scale = min(cw / iw, ch / ih)
        self._zoom = 1.0
        self._pan = [(cw - iw * self._fit_scale) / 2, (ch - ih * self._fit_scale) / 2]
        self._redraw()

    def _one_to_one(self):
        if self.engine.image is None:
            return
        self._auto_fit = False
        self._fit_scale = 1.0
        self._zoom = 1.0
        self._pan = [0.0, 0.0]
        self._redraw()

    def _redraw(self):
        if not self._canvas_widget.exists():
            return
        old_layer, self._pointer_layer = self._pointer_layer, None
        if hasattr(old_layer, "delete"):
            old_layer.delete()
        self._canvas_widget.clear()
        _, (cw, ch) = self._canvas_rect()
        if self.engine.image is None or self._texture_tag is None:
            # The canvas is a persistent workspace surface.  Keep it completely
            # blank before an image is loaded; loading an image only adds content
            # to this existing canvas instead of changing the workspace geometry.
            self._pointer_layer = QPaintLayer(self._canvas_widget)
            self._paint_pointer()
            return
        iw, ih = self.engine.image.size
        scale = self._fit_scale * self._zoom
        p0 = tuple(self._pan)
        p1 = (self._pan[0] + iw * scale, self._pan[1] + ih * scale)
        painter = QPainter(self._canvas_widget)
        painter.drawImage(self._texture_tag, p0, p1)
        cal = self.engine.calibration
        if self.engine.plot_rect:
            left, top, right, bottom = self.engine.plot_rect
            painter.drawRect(
                self._image_to_canvas(left, top), self._image_to_canvas(right, bottom),
                color=(30, 150, 80, 180), fill=(0, 0, 0, 0))
        colors = {"x1": (0, 120, 215, 255), "x2": (0, 120, 215, 255),
                  "y1": (30, 150, 80, 255), "y2": (30, 150, 80, 255)}
        for key in ("x1", "x2", "y1", "y2"):
            a = getattr(cal, key)
            if a is None:
                continue
            x, y = self._image_to_canvas(a.px, a.py)
            painter.drawEllipse(
                (x, y), 5, fill=colors[key], color=(255, 255, 255, 255))
            offset = -20 if key.startswith("x") else 8
            label = "{} = {}".format(key.upper(), self._fmt(a.value))
            label_x = max(6, min(cw - len(label) * 7 - 6, x + 8))
            label_y = max(6, min(ch - 20, y + offset))
            painter.drawText((label_x, label_y), label, color=colors[key], size=14)
        zoom_scale = max(0.05, scale)
        auto_metrics = self._marker_metrics(zoom_scale, "auto")
        manual_metrics = self._marker_metrics(zoom_scale, "manual")
        for ds in self.engine.datasets:
            if not ds.visible:
                continue
            rgb = ds.curve_rgb or (220, 80, 40)
            color = (*rgb, 255)
            marker_style = getattr(ds, "marker_style", "circle")
            if self._plot_preferences["show_automatic_points"]:
                for px, py in ds.extracted_pixels[::max(1, len(ds.extracted_pixels) // 1200 or 1)]:
                    x, y = self._image_to_canvas(px, py)
                    draw_marker(self.canvas, (x, y), auto_metrics.radius, marker_style,
                                color=color, outline=(255, 255, 255, 210), thickness=1.0)
            if self._plot_preferences["show_manual_points"]:
                for p in ds.manual_points:
                    x, y = self._image_to_canvas(p.px, p.py)
                    draw_marker(self.canvas, (x, y), manual_metrics.radius, marker_style,
                                color=color, outline=(255, 255, 255, 255), thickness=1.15)
        if (self._hover_point is not None and self._hover_point != self._selected_point and
                self._marker_visible(self._hover_point[0])):
            try:
                hovered = self._image_to_canvas(*self.engine.point_pixels(*self._hover_point))
                radius = self._marker_metrics(max(0.05, scale), self._hover_point[0]).selection_radius
                painter.drawEllipse(
                    hovered, radius, color=(0, 120, 215, 220),
                    fill=(0, 0, 0, 0), thickness=2)
            except (IndexError, ValueError):
                self._hover_point = None
        if self._selected_point is not None and self._marker_visible(self._selected_point[0]):
            try:
                selected = self._image_to_canvas(*self.engine.point_pixels(*self._selected_point))
                radius = self._marker_metrics(max(0.05, scale), self._selected_point[0]).selection_radius + 1
                painter.drawEllipse(
                    selected, radius, color=(240, 130, 20, 255),
                    fill=(0, 0, 0, 0), thickness=2)
            except (IndexError, ValueError):
                self._selected_point = None
        self._pointer_layer = QPaintLayer(self._canvas_widget)
        self._paint_pointer()

    def _paint_pointer(self):
        self._sync_canvas_cursor()
        layer = self._pointer_layer
        if layer is None or not layer.exists():
            return
        layer.clear()
        painter = layer.painter()
        preferences = getattr(self, "_plot_preferences", PlotDigitizerPreferences.DEFAULTS)
        if self._middle_drag:
            if preferences["show_magnifier"]:
                self._paint_preview(painter)
            return
        if self._drag_start is not None and self._drag_preview is not None:
            a = self._image_to_canvas(*self._drag_start)
            b = self._image_to_canvas(*self._drag_preview)
            painter.drawRect(
                (min(a[0], b[0]), min(a[1], b[1])),
                (max(a[0], b[0]), max(a[1], b[1])),
                color=(0, 120, 215, 255), fill=(0, 120, 215, 25))
        if (self._drag_target is not None and self._drag_preview is not None and
                self._marker_visible(self._drag_target[0])):
            radius = self._marker_metrics(max(0.05, self._fit_scale * self._zoom), self._drag_target[0]).selection_radius + 1
            painter.drawEllipse(
                self._image_to_canvas(*self._drag_preview), radius,
                color=(240, 130, 20, 255), fill=(0, 0, 0, 0), thickness=2)
        elif self._hover_point is not None and self._marker_visible(self._hover_point[0]):
            try:
                radius = self._marker_metrics(max(0.05, self._fit_scale * self._zoom), self._hover_point[0]).selection_radius
                painter.drawEllipse(
                    self._image_to_canvas(*self.engine.point_pixels(*self._hover_point)), radius,
                    color=(0, 120, 215, 220), fill=(0, 0, 0, 0), thickness=2)
            except (IndexError, ValueError):
                self._hover_point = None
        _, (cw, ch) = self._canvas_rect()
        color = (0, 120, 215, 180)
        local = self._cursor_canvas
        if local is not None and preferences["show_crosshair"]:
            x, y = local
            painter.drawLine((0, y), (cw, y), color=color)
            painter.drawLine((x, 0), (x, ch), color=color)
            if self._cursor_over_marker:
                painter.drawRect((x - 4, y - 4), (x + 4, y + 4),
                                 color=(0, 120, 215, 255),
                                 fill=(255, 255, 255, 160), thickness=1)
        if preferences["show_magnifier"]:
            self._paint_preview(painter)

    def _paint_preview(self, painter):
        """Keep the last pointer sample visible, magnified 5x over the canvas."""
        if self.engine.image is None or self._texture_tag is None:
            return
        iw, ih = self.engine.image.size
        point = self._preview_pixel or (iw / 2., ih / 2.)
        _, (cw, ch) = self._canvas_rect()
        size = max(1, min(140, cw - 20, ch - 20))
        geometry = preview_geometry((iw, ih), point, self._fit_scale * self._zoom, size)
        p0 = (max(8, cw - size - 10), 10)
        p1 = (p0[0] + size, p0[1] + size)
        painter.drawRect(
            (p0[0]-1, p0[1]-1), (p1[0]+1, p1[1]+1),
            color=QtFusionPalette.FOCUS, fill=QtFusionPalette.BASE)
        painter.drawImage(
            self._texture_tag,
            (p0[0] + geometry.image_min[0], p0[1] + geometry.image_min[1]),
            (p0[0] + geometry.image_max[0], p0[1] + geometry.image_max[1]),
            uv_min=geometry.uv_min, uv_max=geometry.uv_max)
        mx, my = p0[0] + size / 2., p0[1] + size / 2.
        color = (0, 120, 215, 180)
        painter.drawLine((p0[0], my), (p1[0], my), color=color)
        painter.drawLine((mx, p0[1]), (mx, p1[1]), color=color)
        painter.drawText((p0[0] + 3, p0[1] + 3), "5x", color=(0, 120, 215, 255), size=12)

    def _load_texture(self, image=None):
        """Upload the already-decoded Pillow image to DearPyGui.

        Do not call ``dpg.load_image`` here.  The engine is the single owner of
        image decoding, which keeps standalone and WinUx-hosted behaviour
        identical and also supports every format Pillow can decode.
        """
        image = image or self.engine.image
        if image is None:
            raise RuntimeError("No decoded image is available.")
        rgba = image.convert("RGBA")
        w, h = rgba.size
        if np is not None:
            pixels = (np.asarray(rgba, dtype=np.float32).reshape(-1) / 255.0).tolist()
        else:
            pixels = [channel / 255.0 for pixel in rgba.getdata() for channel in pixel]
        if self._texture_tag is not None and hasattr(self._texture_tag, "delete"):
            self._texture_tag.delete()
        self._texture_tag = self._texture_registry.addStaticTexture(int(w), int(h), pixels)

    # ---------- file actions ----------
    def _file_picker(self, *, directory=False, save=False, extensions=(), callback=None, default_filename=""):
        if self._file_dialog is not None:
            try:
                self._file_dialog.close()
            except Exception:
                pass
        def selected(path):
            self._file_directory = str(Path(path).parent)
            if callable(callback):
                callback(path)

        self._file_dialog = FileSelector(
            view=self.view,
            accepted=selected,
            cancelled=lambda: self._set_status("Ready."),
            extensions=extensions,
            directory=directory,
            save=save,
            default_filename=default_filename,
            initial=self._file_directory or (str(Path(self.engine.image_path).parent)
                                             if self.engine.image_path else ""),
        )
        return self._file_dialog.open()

    def _choose_open_image(self):
        self._file_picker(extensions=(".png", ".jpg", ".jpeg", ".bmp", ".tif", ".tiff"), callback=self._open_image)

    def _open_image(self, path):
        # Decoding large images on the render thread makes the native viewport
        # appear hung. Only decode off-thread; applying engine/UI state stays on
        # the dialog thread so DearPyGui and engine listeners remain serialized.
        self._image_load_generation += 1
        generation = self._image_load_generation
        previous = self._image_load_future
        if previous is not None and not previous.isFinished():
            previous.cancel()
        self._set_status("Opening image...")

        def loaded(result):
            if generation != self._image_load_generation:
                return
            image, resolved = result
            try:
                self.engine.apply_image(image, resolved)
                self._auto_fit = self._plot_preferences["fit_images_on_open"]
                self._pick_mode = None
                self._set_edit_enabled(False)
                self._sample_pixel = None
                for key in self.anchor_value:
                    self.set_control_value(self.anchor_value[key], "1" if key.endswith("2") else "0")
                self._load_texture(self.engine.image)
                self.view.after(1, self._fit_view if self._auto_fit else self._one_to_one)
                self._set_status("")
            except Exception as exc:
                self._set_status("Could not open image: {}".format(exc))

        def failed(exc):
            if generation == self._image_load_generation:
                self._set_status("Could not open image: {}".format(exc))

        self._image_load_future = self.runAsync(
            self.engine.read_image, path, on_result=loaded, on_error=failed)

    def _choose_load_project(self):
        self._file_picker(extensions=(".pdg", ".json"), callback=self._load_project)

    def _load_project(self, path):
        try:
            state = self.engine.load_project(path, view_validator=normalize_workspace_state)
            generation = self._project_load_generation
            self._auto_fit = state.get("auto_fit", True)
            self._pick_mode = None
            self._set_edit_enabled(False)
            self._sample_pixel = None
            if self.engine.image is not None:
                self._load_texture(self.engine.image)
            else:
                if self._texture_tag is not None and hasattr(self._texture_tag, "delete"):
                    self._texture_tag.delete()
                self._texture_tag = None
            self._file_directory = str(Path(path).resolve().parent)
            for key, editor in self.anchor_value.items():
                self._control_wrappers[editor].setText("1" if key.endswith("2") else "0")
            native_context = (getattr(self.view, "is_standalone_ui_host", False) or
                              getattr(self, "_floating_kind", None) == "plotdigitizer")
            if native_context and state.get("viewport_size"):
                width, height = state["viewport_size"]
                QApplication.instance().primaryScreen().resizeWindow(max(1100, int(width)), max(720, int(height)))
            self.view.after(1, self._restore_project_view, state, generation, (QApplication.instance().frameCount() if QApplication.instance() is not None else 0) + 2)
            self._set_status("Project loaded.")
        except Exception as exc:
            self._set_status("Could not load project: {}".format(exc))

    def _choose_save_project(self):
        self._file_picker(save=True, extensions=(".pdg",), callback=self._save_project, default_filename="plot_digitizer.pdg")

    def _save_project(self, path):
        try:
            path = str(path)
            if Path(path).suffix.casefold() not in (".pdg", ".json"):
                path += ".pdg"
            self.engine.save_project(path, view_state=self._capture_project_view())
            self._set_status("Project saved.")
        except Exception as exc:
            self._set_status("Could not save project: {}".format(exc))

    def _capture_project_view(self):
        _, size = self._canvas_rect()
        state = {
            "version": 1, "tool": self._active_tool or "axes",
            "ribbon_tab": self.ribbon.active_tab() or "home", "ribbon_minimized": self.ribbon.is_minimized(),
            "coordinate_mode": self.control_value(self.coordinate_mode),
            "export_scope": self.control_value(self.export_scope), "export_sort_x": bool(self.control_value(self.export_sort_x)),
            "reduction_error": float(self.control_value(self.reduction_error)),
            "auto_fit": self._auto_fit, "scale": self._fit_scale * self._zoom, "zoom": self._zoom,
            "pan": list(self._pan), "canvas_size": list(size),
            "viewport_size": list((QApplication.instance().primaryScreen().windowGeometry().width(),
                                   QApplication.instance().primaryScreen().windowGeometry().height()))
                             if QApplication.instance() is not None else [0, 0],
            "selected_point": self._selected_point,
            "selected_rows": list(self.result_grid.selectedKeys()), "grid_current": self.result_grid.currentKey(),
            "edit_enabled": self._edit_enabled,
            "anchor_text": {key: str(self.control_value(editor)) for key, editor in self.anchor_value.items()},
            "dataset_name_text": str(self.control_value(self.dataset_name)),
            "point_x_text": str(self.control_value(self.point_x)), "point_y_text": str(self.control_value(self.point_y)),
            "sample_pixel": self._sample_pixel, "cursor_pixel": self._cursor_pixel,
            "palette": [list(color) for color in self._palette], "palette_selection": self.control_value(self.palette_combo),
            "pick_mode": self._pick_mode, "calibration_sequence": list(self._calibration_sequence),
            "disclosures": {key: bool(self.control_value(item)) for key, item in self._disclosures.items()},
            "dataset_scroll": QRetainedItem(self.dataset_panel).verticalScrollValue(), "settings_scroll": QRetainedItem(self.settings_panel).verticalScrollValue(),
        }
        return normalize_workspace_state(state, self.engine)

    def _restore_project_view(self, state, generation, after_frame):
        if not self.winfo_exists() or generation != self._project_load_generation:
            return
        if (QApplication.instance().frameCount() if QApplication.instance() is not None else 0) < after_frame:
            self.view.after(1, self._restore_project_view, state, generation, after_frame)
            return
        self._refresh_all()
        if not state:
            self._fit_view()
            return
        self.set_control_value(self.coordinate_mode, state["coordinate_mode"])
        self.set_control_value(self.export_scope, state["export_scope"])
        self._control_wrappers[self.export_sort_x].setChecked(state["export_sort_x"])
        self._control_wrappers[self.reduction_error].setValue(state["reduction_error"])
        self._refresh_grid()
        self._set_edit_enabled(state["edit_enabled"])
        self._show_tool(state["tool"])
        self._selected_point = tuple(state["selected_point"]) if state["selected_point"] else None
        self.result_grid.selected = {"{}:{}".format(*key) for key in state["selected_rows"]}
        self.result_grid.current = "{}:{}".format(*state["grid_current"]) if state["grid_current"] else None
        self._refresh_point_editor()
        self.ribbon.set_active_tab(state["ribbon_tab"])
        self.ribbon.set_minimized(state["ribbon_minimized"])
        self._sample_pixel, self._cursor_pixel = state["sample_pixel"], state["cursor_pixel"]
        self._palette = [tuple(round(channel) for channel in color) for color in state["palette"]]
        labels = ["#{:02X}{:02X}{:02X}".format(*color) for color in self._palette]
        self.set_control_items(self.palette_combo, labels or ["Find image colors..."])
        self.set_control_visible(self.palette_combo, len(labels) > 1)
        if state["palette_selection"]:
            self.set_control_value(self.palette_combo, state["palette_selection"])
        for key, opened in state["disclosures"].items():
            self.set_control_value(self._disclosures[key], opened)
        self._pick_mode = state["pick_mode"]
        self._calibration_sequence = state["calibration_sequence"]
        if self._calibration_sequence:
            self.set_control_value(self.calibration_hint, "Step {} / 4: click {} on the image.".format(
                5 - len(self._calibration_sequence), self._calibration_sequence[0].upper()))
            self.set_control_visible(self.calibration_hint, True)
        for key, text in state["anchor_text"].items():
            editor = self.anchor_value[key]
            self._control_wrappers[editor].setText(text)
            self.set_control_value(editor, text)
        for field, key in ((self.dataset_name, "dataset_name_text"),
                           (self.point_x, "point_x_text"), (self.point_y, "point_y_text")):
            if state[key] is not None:
                self._control_wrappers[field].setText(state[key])
                self.set_control_value(field, state[key])
        # Apply camera/scroll after disclosure/ribbon changes settle as well.
        self.view.after(1, self._restore_project_camera, state, generation, (QApplication.instance().frameCount() if QApplication.instance() is not None else 0) + 2)
        self._refresh_export_controls()

    def _restore_project_camera(self, state, generation, after_frame):
        if not self.winfo_exists() or generation != self._project_load_generation:
            return
        if (QApplication.instance().frameCount() if QApplication.instance() is not None else 0) < after_frame:
            self.view.after(1, self._restore_project_camera, state, generation, after_frame)
            return
        if state["auto_fit"]:
            self._fit_view()
        else:
            _, (width, height) = self._canvas_rect()
            self._auto_fit = False
            self._zoom = state["zoom"]
            self._fit_scale = state["scale"] / state["zoom"]
            self._pan = [state["pan"][0] + (width - state["canvas_size"][0]) / 2,
                         state["pan"][1] + (height - state["canvas_size"][1]) / 2]
            self._redraw()
        QRetainedItem(self.dataset_panel).setVerticalScrollValue(state["dataset_scroll"])
        QRetainedItem(self.settings_panel).setVerticalScrollValue(state["settings_scroll"])

    def _choose_export_csv(self):
        self._show_tool("data")
        self._file_picker(save=True, extensions=(".csv",), callback=self._export_csv, default_filename="digitized_data.csv")

    def _export_csv(self, path):
        try:
            if not str(path).lower().endswith(".csv"):
                path += ".csv"
            dataset_index = (self.engine.active_dataset_index
                             if self.control_value(self.export_scope) == "Active dataset" else None)
            self.engine.export_csv(path, dataset_index, sort_by_x=bool(self.control_value(self.export_sort_x)))
            self._set_status("CSV exported.")
        except Exception as exc:
            self._set_status("Could not export CSV: {}".format(exc))

    # ---------- reference integration ----------
    def _add_to_reference(self):
        if self.reference_sink is None or not getattr(self.reference_sink, "available", True):
            return self._set_status("Reference library is unavailable.")
        try:
            item = self.reference_sink.add_dataset(self.engine.active_dataset)
            self._set_status("Added '{}' to Reference Chart.".format(item["name"]))
        except Exception as exc:
            self._set_status("Could not add reference: {}".format(exc))

    def _set_status(self, text):
        if getattr(self, "status", None) and QRetainedItem(self.status).exists():
            value = "" if text == "Ready." else str(text or "")
            self.set_status_text(self.status, value)
            self.set_control_visible(self.status, bool(value))

    def handle_command(self, command, *args, **kwargs):
        if command == "reference_status":
            self._set_status(args[0])
            return
        if command == "open_image":
            self._open_image(args[0])
            return
        if command == "open_file_selector":
            self._choose_open_image()
            return
        super().handle_command(command, *args, **kwargs)

    def _layout_canvas(self):
        if not self.winfo_exists() or not hasattr(self, "canvas_frame"):
            return
        try:
            bounds = item_rect(self.canvas_panel)
            if bounds is None:
                return
            px, py, right, bottom = bounds
            pw, ph = right - px, bottom - py
            frame_bounds = item_rect(self.canvas_frame)
            if frame_bounds is None:
                return
            fy = frame_bounds[1]
            if pw <= 2 or ph <= 2:
                return

            # Region spacing belongs to the workspace, not to nested panels.
            # Fill the canvas panel down to the same bottom edge as the sidebars.
            frame_size = (
                max(self.CANVAS_MIN_WIDTH, int(pw - 1)),
                max(120, int(py + ph - fy - 1)),
            )
            canvas_size = (max(1, frame_size[0] - 2), max(1, frame_size[1] - 2))
            size = (frame_size, canvas_size)
            if size == self._canvas_size:
                return
            self._canvas_size = size
            self._canvas_frame_widget.resize(*frame_size)
            self._canvas_widget.resize(*canvas_size)
            self._schedule_data_layout()
        except (KeyError, ValueError):
            return
        if self._auto_fit and self.engine.image is not None:
            self.view.after(1, self._fit_view)
        else:
            self._redraw()

    def _schedule_data_layout(self):
        """Measure after page/selection layout, coalescing resize bursts."""
        if self._active_tool != "data" or self._data_layout_pending:
            return
        self._data_layout_pending = True

        def deliver():
            self._data_layout_pending = False
            self._layout_data_grid()

        schedule = getattr(self.view, "after_render", None)
        if callable(schedule):
            schedule(deliver)
        else:
            self.view.after(16, deliver)

    def _layout_data_grid(self):
        """Give the table remaining inspector space; scroll rows, not panels.

        Include the point editor when it is open so selecting a row does not
        push its editable coordinates below a fixed 300px table. Small windows
        may still scroll once the readable minimum table height is reached.
        """
        if not self.winfo_exists() or self._active_tool != "data":
            return
        tail = self.export_data_button
        if self._point_keys():
            tail = self.apply_point_button if self._selected_point is not None else self.point_info
        panel = item_rect(self.settings_panel)
        bottom_control = item_rect(tail)
        if panel is None or bottom_control is None:
            return
        scroll = QRetainedItem(self.settings_panel).verticalScrollValue()
        free = panel[3] - bottom_control[3] - scroll - self.REGION_GAP
        height = max(100, int(round(self._data_grid_height + free)))
        if abs(height - self._data_grid_height) <= 1:
            return
        self._data_grid_height = height
        self.result_grid.setFixedHeight(height)

    def _apply_layout(self):
        super()._apply_layout()
        if hasattr(self, "canvas"):
            self.view.after(0, self._layout_canvas)

    def layout_dialog(self):
        self.view.after(0, self._layout_canvas)

    def _close_from_native(self):
        self.destroy()

    def reject(self):
        self._close_from_escape()

    def _close_from_escape(self):
        if self._pick_mode is not None:
            self._cancel_pick()
        else:
            self.destroy()

    def canReuseHost(self):
        return bool(self.REUSABLE_HOST and self._reuse_safe_on_close)

    def _finalize_visual_destroy(self, *_args, **_kwargs):
        """Release heavyweight Plot Digitizer registries only after SW_HIDE.

        Deleting the texture registry can free a multi-megapixel RGBA upload and
        is noticeably more expensive than merely closing the window.  Keeping it
        out of the synchronous close path makes the native dialog disappear as
        soon as the user requests Close; host recycling can finish afterwards.
        """
        input_binding, self._input_binding = self._input_binding, None
        texture_registry = self._texture_registry
        self._handler_registry = None
        self._texture_registry = None
        try:
            super()._finalize_visual_destroy(*_args, **_kwargs)
        finally:
            if input_binding is not None:
                try:
                    input_binding.delete()
                except Exception:
                    pass
            try:
                if texture_registry is not None:
                    texture_registry.delete()
            except Exception:
                pass

    def destroy(self):
        if self._closed:
            return
        cursor, self._canvas_cursor = self._canvas_cursor, None
        if cursor is not None:
            cursor.close()
        self._image_load_generation += 1
        if self._file_dialog is not None:
            self._file_dialog.close()
            self._file_dialog = None
        try:
            self.engine.unsubscribe(self._engine_changed)
        except Exception:
            pass
        try:
            # A running image extraction cannot be force-stopped safely.  The
            # task is detached from this form and its late delivery is ignored,
            # but this particular host lease is retired so no form-specific
            # computation survives into the next recycled viewport.
            self._reuse_safe_on_close = bool(self._smart_runner.close())
        except Exception:
            self._reuse_safe_on_close = False
        # QtDialog now performs visual close before retained-object teardown;
        # the heavyweight DPG registries above follow the same deferred path.
        super().destroy()
