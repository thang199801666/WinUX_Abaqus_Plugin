"""WinUx-native Plot Digitizer dialog built from shared Dear ImGui components."""
from __future__ import annotations

from pathlib import Path
from dataclasses import replace
import math
import os

try:
    import numpy as np
except Exception:  # optional fast texture conversion
    np = None
from DearUIQt.gui import QPainter, QCursor, QKeyboard, QPaintLayer, QTextureRegistry, QFontMetrics
from DearUIQt.core import Qt, QItemInputBinding, QGlobalInputBinding

from DearUIQt.widgets import QApplication, QCanvas, QToolButton, QFrame, QSpacer, QLabel, QToolTip, QRetainedItem, QProgressBar

from ..core import AxisScale, AxisAnchor, DigitizerEngine, ExtractionSettings
from ..application import SmartDetectRunner, TickCalibrationRunner, normalize_workspace_state
from ..core.extraction import detect_curve_colors
from ..core.axis_labels import format_axis_value, parse_axis_value_input
from DearUIQt import (
    ToolWindow, QtDataGridView, QtGridRow, QtListView, QtFusionPalette,
    QtListItem, ColorField, QPushButton, QMenu, QAction, QtConcurrent,
)
from ...ui import (
    FileSelector, ToolWorkspace, ToolCommandRow, style_image_canvas,
    style_tool_surface, item_rect, CanvasCursor,
)
from ...ui.components.toolbar import ResourceTextures, toolbar_icon_theme, toolbar_fitted_icon_theme
from ...preferences.plot_digitizer import PlotDigitizerPreferences
from .markers import draw_marker, draw_axis_marker, marker_metrics, cursor_hits_marker
from .preview import preview_geometry
from .ribbon_style import DIGITIZER_RIBBON_DISPLAY, DigitizerRibbonBar
from .checklist import DigitizerCheckList, rounded_checkbox_theme
from .samples_dialog import SamplesDialog
from DearUIQt.tooltip import TOOLTIP_DELAY, TOOLTIP_WRAP_WIDTH, tooltip_theme
from DearUIQt.themes import (transparent_header_cell_theme, button_theme, status_bar_theme,
                            status_text_theme, make_theme, ThemeSpec, ThemeTarget, ThemeColor,
                            ThemeStyle, theme_component)
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
    EXPORT_SORT_OPTIONS = {"Original order": "original", "Sort by X": "x", "Sort by Y": "y"}

    @classmethod
    def _icon(cls, name: str) -> str:
        return f"{cls.ICON_ROOT}/{name}.png"

    RIGHT_WIDTH = 288
    CANVAS_MIN_WIDTH = 420
    OUTER_MARGIN = 6
    REGION_GAP = 8
    STATUS_HEIGHT = 22
    STATUS_ROW_HEIGHT = 18
    PROGRESS_HEIGHT = 14
    STATUS_BUTTON_HEIGHT = 18
    CANVAS_VIEW_TOOLS_WIDTH = 128
    CANVAS_VIEW_TOOLS_HEIGHT = 32
    NATIVE_RESIZABLE = True
    ALLOW_MINIMIZE = True
    ALLOW_MAXIMIZE = True
    NATIVE_DEFER_CLOSE = True

    def __init__(self, view, reference_sink=None, reference_library=None, *, native=None):
        # reference_library is retained only for compatibility with old callers.
        if reference_sink is None and reference_library is not None:
            from ..integration.winux import WinUxReferenceSink
            reference_sink = WinUxReferenceSink(reference_library)
        self.reference_sink = reference_sink
        self._plot_preference_store = PlotDigitizerPreferences()
        self._plot_preferences = self._plot_preference_store.load()
        self._preference_refreshing = False
        self._preference_controls = {}
        self._settings_dialog = None
        self._sample_count_dialog = None
        self.engine = DigitizerEngine()
        self.engine.subscribe(self._engine_changed)
        self._icon_action_draws = {}
        self._icon_action_canvases = {}
        self._icon_action_hovered = {}
        self._pick_color_rgb = None
        self._pick_color_themes = {}
        self._smart_runner = SmartDetectRunner(
            self.engine,
            lambda callback, *args: self.view.after(0, callback, *args),
            submitter=QtConcurrent.run)
        self._tick_calibration_runner = TickCalibrationRunner(
            self.engine,
            lambda callback, *args: self.view.after(0, callback, *args),
            submitter=QtConcurrent.run)
        self._reuse_safe_on_close = True
        self._close_confirmation_pending = False
        self._close_confirmation_dialog = None
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
        self._project_path = None
        self._auto_fit = True
        self._canvas_size = None
        self._data_layout_pending = False
        self._data_grid_height = 300
        self._selected_point = None
        self._edit_enabled = False
        self._hover_point = None
        self._sample_pixel = None
        self._drag_start = None
        self._region_first_corner = None
        self._region_press = None
        self._region_alignment_preview = None
        self._drag_preview = None
        self._drag_target = None
        self._anchor_drag_target = None
        self._anchor_drag_preview = None
        self._hover_anchor = None
        self._point_press = None
        self._rubberband_active = False
        self._rubberband_end = None
        self._rubberband_base = set()
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
        self._reviewed_datasets = set()
        self._calibration_sequence = []
        self._calibration_draft = None
        self._manual_bounds_axes = set()
        self._calibration_method = 'smart'
        self._disclosures = {}
        self._project_load_generation = 0
        self._image_load_generation = 0
        self._image_load_future = None
        self._progress_jobs = {}
        self._status_summary = 'Ready.'
        self._status_detail = 'Ready.'
        self._status_visible = None

        super().__init__(view, "Plot Digitizer", 1240, 780, footer=False, native=native)
        self.preferred_size = (1240, 780)
        self.setMinimumSize(1100, 680)
        # ImGui fallback windows and native HWNDs must share the same close
        # transaction.  In particular, clicking the caption X must not inherit
        # Escape's edit-state machine and silently close without confirmation.
        QRetainedItem(self.tag).configure(
            on_close=lambda *_args: self._close_from_native())
        QRetainedItem(self.content).configure(
            width=0, height=0, no_scrollbar=True, no_scroll_with_mouse=True)
        # Keep the proven flat child-window structure.  Vertical padding is
        # zero so the final status bar can meet the client-area bottom edge;
        # the horizontal 6 px margin remains for the workspace/ribbon.
        self._content_theme = style_tool_surface(
            self.content, padding=(self.OUTER_MARGIN, 0), spacing=(0, self.REGION_GAP))

        self._build_toolbar()
        self._build_workspace()
        self._build_statusbar()
        self._canvas_cursor = CanvasCursor(self.view, window=self.tag)

        self._install_mouse_handlers()
        self._delete_key_consumed = False
        key_state = self._native_delete_snapshot()
        self._delete_key_down = key_state[0] if key_state is not None else False
        # A secondary native HWND can miss renderer key/visibility callbacks.
        # Keep the recovery on a dialog-owned timer, not a canvas event handler.
        self._delete_key_timer = self.create_timer(16, self._poll_delete_key)
        self.enter_editors.update((self.point_x, self.point_y,
                                   self.calibration_point_value, self.new_calibration_value,
                                   *self.anchor_value.values()))
        self._refresh_all()
        self._show_tool("axes")
        self.view.after(0, self._layout_canvas)

    # ---------- layout ----------
    def _build_toolbar(self):
        # Plot Digitizer deliberately omits the Quick Access Toolbar. The command
        # Home follows the workflow; Data holds refinement/export. Camera
        # commands live on the canvas overlay rather than a separate ribbon tab.
        self.ribbon = self.own_widget(DigitizerRibbonBar(
            self.content, quick_access=False, display_template=DIGITIZER_RIBBON_DISPLAY,
            visual_style="clean", tab_style="underline", group_style="separator",
            after=self.view.after))
        def ribbon_icon(name):
            # Preserve the user's original artwork, including Save As sharing
            # the existing save icon. Layout changes must not replace resources.
            return self._icon("save_project" if name == "save_project_as" else name)

        def menu_entry(key, label, icon, callback, ribbon_label):
            return {'id': key, 'label': label,
                    'icon': self._icon_texture(icon, pixel_size=24), 'callback': callback,
                    'ribbon_label': ribbon_label, 'ribbon_image': self._icon(icon)}

        # Keep frequent commands direct and group related operations in menus.
        self.ribbon.add_tab("home", "Home", activate=True)
        self.ribbon.add_group("home", "file", "File", width=72, layout="large")
        self.ribbon.add_menu_button(
            "home", "file", "open_image", "Open", [
                menu_entry('open_image_0', 'Open Image...', 'open_image', self._choose_open_image, 'Open'),
                menu_entry('open_image_1', 'Open Project...', 'load_project', self._choose_load_project, 'Open Project')],
            image=ribbon_icon("open_image"), tooltip="Open a chart image or an existing project")
        self.ribbon.add_menu_button(
            "home", "file", "save_project", "Save", [
                menu_entry('save_project_0', 'Save Project (Ctrl+S)', 'save_project', self._choose_save_project, 'Save'),
                menu_entry('save_project_1', 'Save Project As... (Ctrl+Shift+S)', 'save_project', self._choose_save_project_as, 'Save As')],
            image=ribbon_icon("save_project"), tooltip="Save this project or save a new copy")
        self.ribbon.add_menu_button(
            'home', 'file', 'clean', 'Clear', [
                menu_entry('clean_0', 'Clear All Markers (keep image)...', 'delete_item', lambda: self._request_clean('markers'), 'Clear'),
                None,
                menu_entry('clean_2', 'New Project...', 'reset', lambda: self._request_clean('project'), 'New')],
            image=self._icon('delete_item'), tooltip='Clear markers or start an empty project; confirmation required')
        self.ribbon.add_group("home", "plot_area", "1. Axes", width=72, layout="large")
        # Keep the existing command id/icon for saved integrations; only its
        # public label and selection gesture change.
        self.ribbon.add_button(
            "home", "plot_area", "box", "Select Plot", lambda: self._begin_pick("area"),
            image=ribbon_icon("plot_area"), width=84,
            tooltip="Drag a rectangle or click two opposite corners to select the chart area and detect axis tick values")
        self.ribbon.add_button(
            'home', 'plot_area', 'read_axes', 'Read Ticks', self._reread_calibration_ticks,
            image=ribbon_icon('calibrate_axes'), enabled=False,
            tooltip='Read axis ticks again in the selected region; missing values open for manual entry')

        self.ribbon.add_group('home', 'extract', '2. Extract', width=72, layout='large')
        self.ribbon.add_button(
            "home", "extract", "pick_color", "Pick Color", lambda: self._begin_pick("curve"),
            image=ribbon_icon("sample_color"), enabled=False,
            tooltip="Click a curve stroke to sample its color, then return to the normal cursor. Esc cancels.")
        self.ribbon.add_button(
            'home', 'extract', 'extract', 'Extract', self._extract_curve,
            image=ribbon_icon('extract_points'), enabled=False,
            tooltip='Pick Color first, then extract the sampled curve into points. Ctrl+Z undoes extraction.')

        self.edit_button = self.ribbon.add_button(
            "home", "extract", "edit", "Edit Points", self._edit_mode_toggled,
            image=self._icon("edit_points"), checkable=True, enabled=False,
            tooltip="Edit Points (S): click to add/select; drag empty space to select multiple points. Ctrl/Shift adds to the selection. Esc clears the selection; Delete/Del removes selected points.")
        self.delete_points_button = self.ribbon.add_button(
            'home', 'extract', 'delete_points', 'Delete', self._delete_points,
            image=self._icon('delete_points'), enabled=False,
            tooltip='Delete selected points from the canvas or data table. Ctrl+Z restores them.')
        self.ribbon.add_group('home', 'data', '3. Data', width=72, layout='large')
        self.ribbon.add_button(
            'home', 'data', 'view_data', 'View Data', lambda: self._show_tool('data'),
            image=ribbon_icon('view_data'), enabled=False,
            tooltip='Review X/Y values, copy selected cells, refine samples and export CSV on the Data tab')

        self.ribbon.add_group("home", "history", "History", width=72, layout="large")
        self.undo_button = self.ribbon.add_button(
            "home", "history", "undo", "Undo", lambda: self._trigger_history_command("undo"),
            image=ribbon_icon("undo"), tooltip="Undo the last edit (Ctrl+Z)")
        self.redo_button = self.ribbon.add_button(
            "home", "history", "redo", "Redo", lambda: self._trigger_history_command("redo"),
            image=ribbon_icon("redo"), tooltip="Redo the last edit (Ctrl+Y / Ctrl+Shift+Z)")
        self._history_actions = {}
        for key, label, callback in (("undo", "Undo", self._undo), ("redo", "Redo", self._redo)):
            command = self.own_widget(QAction(label, after=self.view.after))
            command.triggered.connect(lambda checked, execute=callback: execute())
            command.changed.connect(lambda name=key, action=command:
                                    self._refresh_history_buttons(name, action.isEnabled()))
            self._history_actions[key] = command
        self._refresh_history_commands()

        # Settings is a first-class ribbon command, visible on the default Home
        # tab rather than an extra step in the digitizing workflow.
        self.ribbon.add_group("home", "tools", "Tools", width=72, layout="large")
        self.ribbon.add_button(
            "home", "tools", "settings", "Settings", self._open_settings,
            image=ribbon_icon("settings"),
            tooltip="Customize the canvas, markers and mouse interaction")

        self.ribbon.add_tab('data', 'Data')
        self.ribbon.add_group('data', 'refine', 'Refine points', width=72, layout='large')
        self.ribbon.add_button('data', 'refine', 'data_delete', 'Delete', self._delete_points,
                               image=ribbon_icon('delete_points'), enabled=False,
                               tooltip='Delete selected data points (Del). Ctrl+Z restores them.')
        for key, label, icon, callback, tooltip in (
                ('smooth_curve', 'Smooth', 'reduce_samples', self._smooth_curve,
                 'Smooth curve points. Ctrl+Z restores the original points.'),
                ('samples', 'Resample', 'reduce_samples', self._open_samples_dialog,
                 'Set sample count/factor or simplify by geometric error. Ctrl+Z undoes the change.')):
            self.ribbon.add_button('data', 'refine', key, label, callback,
                                   image=self._icon(icon), enabled=False, tooltip=tooltip)
        self.ribbon.add_group('data', 'output', 'Export', width=72, layout='large')
        self.ribbon.add_button(
            'data', 'output', 'export_csv', 'Export CSV', self._choose_export_csv,
            image=ribbon_icon('export_csv'), tooltip='Export calibrated digitized data to CSV')
        self.ribbon.add_group('data', 'history', 'History', width=72, layout='large')
        for key, label, shortcut in (('undo', 'Undo', 'Ctrl+Z'), ('redo', 'Redo', 'Ctrl+Y / Ctrl+Shift+Z')):
            self.ribbon.add_button('data', 'history', 'data_' + key, label,
                                   lambda name=key: self._trigger_history_command(name),
                                   image=ribbon_icon(key), enabled=False,
                                   tooltip='{} the last edit ({})'.format(label, shortcut))

    def _build_workspace(self):
        # A child-window host reserves bottom space reliably. A negative table
        # height alone does not constrain its fill-height panel children.
        # Normal flow already supplies the gap before the status bar; reserving
        # REGION_GAP again would leave an extra blank strip at the bottom.
        self._workspace_host = self.own_widget(QFrame(
            parent=self.content, width=-1, height=-self.STATUS_HEIGHT,
            frame_shape=QFrame.NoFrame, no_scrollbar=True, no_scroll_with_mouse=True))
        style_tool_surface(self._workspace_host.tag, padding=(0, 0), spacing=(0, 0))
        self.workspace = self.own_widget(ToolWorkspace(
            self._workspace_host, column_widths=(None, self.RIGHT_WIDTH),
            column_gap=self.REGION_GAP, panel_padding=(0, 0), panel_spacing=(6, 8),
            after=self.view.after))
        self.canvas_panel = self.workspace.panel(0).tag
        self.settings_panel = self.workspace.panel(1, scroll=True).tag
        # One shared right sidebar: image/workflow/datasets remain above the
        # active tool. Preserve the dataset_panel alias for workspace state.
        self.dataset_panel = self.settings_panel
        self._build_canvas_panel(self.canvas_panel)
        self._build_dataset_panel(self.dataset_panel)
        self._build_settings_panel(self.settings_panel)

    def _build_dataset_panel(self, parent):
        panel = parent
        with self.section("Datasets", parent=panel) as group:
            self._dataset_commands = self.own_widget(ToolCommandRow(group, after=self.view.after))
            self.add_dataset_button = self.action(
                "New", self._add_dataset, parent=self._dataset_commands.cell(0, 0), width=-1)
            self.delete_dataset_button = self.action(
                "Delete", self._delete_dataset, parent=self._dataset_commands.cell(0, 1), width=-1)
            QSpacer(0, 6, parent=group)
            self.dataset_list = self.own_widget(DigitizerCheckList(group, [], visible_rows=1,
                                                          after=self.view.after, context_menu_requests=True))
            self.dataset_list.currentChanged.connect(self._dataset_selected)
            self.dataset_list.itemCheckChanged.connect(self._dataset_visibility_changed)
            self.dataset_list.contextMenuRequested.connect(self._dataset_context_open)
            self._add_help(self.dataset_list.tag,
                            "Click a row to make it active; its checkbox shows/hides the curve. "
                            "Each row shows its point count. Right-click to lock or unlock.")
            self.dataset_menu = self.own_widget(QMenu([], after=self.view.after, min_width=140))
            self.dataset_menu.triggered.connect(self._dataset_context_action)
        # Keep adjacent group boxes visually separated.  The shared sidebar is
        # intentionally compact, but a small native spacer prevents the
        # Datasets border and Workflow caption from reading as one block.
        QSpacer(0, 8, parent=panel)
        with self.section("Workflow", parent=panel) as group:
            self.tool_list = self.own_widget(DigitizerCheckList(group, [
                QtListItem("axes", "Calibrate Axes", checked=False),
                QtListItem("extract", "Extract Curve", checked=False),
                QtListItem("data", "Review Data", checked=False),
            ], visible_rows=3, completion_colors=True, after=self.view.after))
            self.tool_list.currentChanged.connect(self._show_tool)
            self.tool_list.itemCheckChanged.connect(self._workflow_check_clicked)
            self._add_help(self.tool_list.tag,
                            "Choose a step. Checkboxes show completed work automatically: both axes calibrated, "
                            "points acquired, and current data opened for review. Clicking the checkbox or its text opens the step.")
        QSpacer(0, 8, parent=panel)

    def _build_statusbar(self):
        """Build a compact Qt-like QStatusBar strip.

        The status area should read as native window chrome, not as another
        content panel: light alternate surface, one-pixel top separator,
        left-aligned message, compact permanent progress controls and a subtle
        resize grip at the bottom-right.
        """
        self.status_bar = self.own_widget(QFrame(
            parent=self.content, width=-1, height=self.STATUS_HEIGHT,
            frame_shape=QFrame.NoFrame, no_scrollbar=True, no_scroll_with_mouse=True))
        self.status_bar.setTheme(status_bar_theme(backend=self.status_bar.backend))
        QRetainedItem(self.status_bar.tag).configure(always_use_window_padding=True)

        p = QtFusionPalette
        self._status_inner_theme = make_theme(theme_component(
            ThemeTarget.CHILD_WINDOW,
            colors={ThemeColor.CHILD_BACKGROUND: p.WINDOW,
                    ThemeColor.BORDER: (0, 0, 0, 0)},
            styles={ThemeStyle.WINDOW_PADDING: (0, 1),
                    ThemeStyle.ITEM_SPACING: (0, 0),
                    ThemeStyle.CHILD_BORDER_SIZE: 0,
                    ThemeStyle.CHILD_ROUNDING: 0}),
            backend=self.status_bar.backend,
            tag='winux.plotdigitizer.statusbar.inner', cache=True)
        self._status_progress_theme = make_theme(theme_component(
            ThemeTarget.CHILD_WINDOW,
            colors={ThemeColor.CHILD_BACKGROUND: p.WINDOW,
                    ThemeColor.BORDER: (0, 0, 0, 0)},
            styles={ThemeStyle.WINDOW_PADDING: (0, 0),
                    ThemeStyle.ITEM_SPACING: (0, 0),
                    ThemeStyle.CHILD_BORDER_SIZE: 0,
                    ThemeStyle.CHILD_ROUNDING: 0}),
            backend=self.status_bar.backend,
            tag='winux.plotdigitizer.statusbar.progress.host', cache=True)

        # Qt keeps transient status text on the left and permanent widgets on
        # the right.  The last narrow cell is a visual QSizeGrip analogue.
        self._status_row = self.own_widget(ToolCommandRow(
            self.status_bar, columns=4, column_widths=(None, 176, 54, 13), gap=4,
            after=self.view.after))
        self._status_columns = self.status_bar.backend.get_item_children(self._status_row.tag, 0)
        self._status_message_host = self.own_widget(QFrame(
            parent=self._status_row.cell(0, 0), width=-1, height=self.STATUS_ROW_HEIGHT,
            frame_shape=QFrame.NoFrame, no_scrollbar=True, no_scroll_with_mouse=True))
        self._status_message_host.setTheme(self._status_inner_theme)
        QRetainedItem(self._status_message_host.tag).configure(always_use_window_padding=True)
        self.status = self.note('Ready.', parent=self._status_message_host.tag)
        self.status_bar.backend.bind_item_theme(
            self.status, status_text_theme(backend=self.status_bar.backend, muted=False))
        self._status_help = self._add_help(self.status, 'Ready.')

        self._status_progress_host = self.own_widget(QFrame(
            parent=self._status_row.cell(0, 1), width=-1, height=self.STATUS_ROW_HEIGHT,
            frame_shape=QFrame.NoFrame, no_scrollbar=True, no_scroll_with_mouse=True))
        self._status_progress_host.setTheme(self._status_progress_theme)
        self.progress_bar = self.own_widget(QProgressBar(
            parent=self._status_progress_host, after=self.view.after))
        self.progress_bar.setFixedHeight(self.PROGRESS_HEIGHT)
        self.progress_bar.setValue(0)
        self.progress_bar.setFormat('')
        # Vertically center the compact progress indicator inside the 18 px
        # permanent-widget row, mirroring QStatusBar's widget alignment.
        QRetainedItem(self.progress_bar.tag).configure(pos=(0, 2))
        self._progress_text_canvas = self.own_widget(QCanvas(
            width=176, height=self.PROGRESS_HEIGHT, parent=self._status_progress_host, pos=(0, 2)))
        self._progress_text_draw = QPainter(self._progress_text_canvas).drawText(
            (0, 0), 'Ready', color=QtFusionPalette.TEXT)
        self._progress_text = 'Ready'

        self.cancel_process_button = self.own_widget(QPushButton(
            'Cancel', parent=self._status_row.cell(0, 2), width=-1, height=self.STATUS_BUTTON_HEIGHT,
            after=self.view.after))
        self.cancel_process_button.setThemeProvider(lambda focused=False, disabled=False: button_theme(
            backend=self.cancel_process_button.backend, focused=focused, disabled=disabled,
            frame_padding=(6, 0)))
        self.cancel_process_button.clicked.connect(lambda *_: self._cancel_process())

        # QSizeGrip-like visual cue from the reference Qt status bar. Window
        # resizing itself remains native; these lines are intentionally passive.
        self._status_grip_host = self.own_widget(QFrame(
            parent=self.status_bar, width=11, height=11,
            frame_shape=QFrame.NoFrame, no_scrollbar=True, no_scroll_with_mouse=True))
        self._status_grip_host.setTheme(self._status_progress_theme)
        QRetainedItem(self._status_grip_host.tag).configure(always_use_window_padding=True)
        self._status_grip_canvas = self.own_widget(QCanvas(
            width=11, height=11, parent=self._status_grip_host))
        grip = QPainter(self._status_grip_canvas)
        for start in (4, 7, 9):
            grip.drawLine((10, start), (start, 10), color=p.TEXT_MUTED)
            grip.drawLine((10, start + 1), (start + 1, 10), color=p.BASE)

        # Child-window themes cannot express a top-only border, so draw the
        # one-pixel QStatusBar separator explicitly and resize it with the bar.
        self._status_top_rule_canvas = self.own_widget(QCanvas(
            width=1, height=1, parent=self.status_bar, pos=(0, 0)))
        self._status_top_rule_draw = QPainter(self._status_top_rule_canvas).drawLine(
            (0, 0), (1, 0), color=p.BORDER_LIGHT)

        self._set_progress_visible(False)
        self._layout_progress_text()

    def _set_progress_visible(self, visible):
        if getattr(self, '_status_progress_visible', None) == visible:
            return
        self._status_progress_visible = visible
        self._status_progress_host.setVisible(visible)
        self.cancel_process_button.setVisible(visible)
        # Hiding a widget alone leaves its fixed table column reserved. Qt
        # returns that space to the message when permanent widgets disappear.
        for column in self._status_columns[1:3]:
            self.status_bar.backend.configure_item(column, enabled=visible)

    def _set_progress_text(self, text):
        self._progress_text = text
        QRetainedItem(self._progress_text_draw).configure(text=text)
        self._layout_progress_text()

    def _layout_progress_text(self):
        self._layout_status_text()
        if not hasattr(self, '_progress_text_canvas') or not self.winfo_exists():
            return
        bounds = QRetainedItem(self._status_progress_host.tag).globalGeometry()
        if bounds.width() <= 0:
            return
        metrics = QFontMetrics(backend=self._progress_text_canvas.backend)
        self._progress_text_canvas.resize(bounds.width() - 1, self.PROGRESS_HEIGHT)
        QRetainedItem(self._progress_text_draw).configure(pos=(
            max(0, round((bounds.width() - 1 - metrics.horizontalAdvance(self._progress_text)) / 2)),
            max(0, round((self.PROGRESS_HEIGHT - metrics.height()) / 2))))

    def _begin_progress(self, key, message):
        self._progress_jobs.pop(key, None)
        self._progress_jobs[key] = (None, message)
        self.progress_bar.setState('normal')
        self._show_progress()
        self.view.after(20, self._layout_progress_text)
        self._set_status({'ticks': 'Reading axes...', 'extract': 'Extracting points...',
                          'image': 'Opening image...'}.get(key, 'Working...'), details=message)

    def _show_progress(self):
        if not self._progress_jobs:
            return
        self._set_progress_visible(True)
        value, _message = next(reversed(self._progress_jobs.values()))
        self.progress_bar.setValue(0 if value is None else value)
        self._set_progress_text('Working...' if value is None else '{}%'.format(int(value * 100)))

    def _tick_calibration_progress(self, value, message):
        if not self.winfo_exists() or 'ticks' not in self._progress_jobs:
            return
        self._progress_jobs['ticks'] = (min(.99, max(0.0, value)), message)
        if next(reversed(self._progress_jobs)) == 'ticks':
            self._show_progress()
            phase = ('Aligning axes...' if 'align' in message.lower() else
                     'Reading X ticks...' if message.startswith('X ') or 'X tick' in message else
                     'Reading Y ticks...' if message.startswith('Y ') or 'Y label' in message else
                     'Reading axes...')
            self._set_status(phase, details=message)

    def _finish_progress(self, key, success=True):
        if key not in self._progress_jobs:
            return
        self._progress_jobs.pop(key)
        if self._progress_jobs:
            self._show_progress()
        else:
            self.progress_bar.setState('normal' if success else 'error')
            self.progress_bar.setValue(1 if success else 0)
            self._set_progress_text('100%' if success else 'Stopped')
            self._set_progress_visible(False)
        if key == 'ticks':
            self._refresh_calibration_actions()

    def _cancel_process(self):
        if not self._progress_jobs:
            return
        key = next(reversed(self._progress_jobs))
        if key == 'ticks':
            self._tick_calibration_runner.cancel()
            self._region_alignment_preview = None
            self._redraw()
        elif key == 'extract':
            self._smart_runner.cancel()
            self._refresh_dataset_controls()
            self._refresh_workflow()
        elif key == 'image':
            # Pillow decoding cannot be interrupted mid-call, but a cancelled
            # load must never replace the current image when decoding returns.
            self._image_load_generation += 1
            future = self._image_load_future
            if future is not None:
                future.cancel()
        self._finish_progress(key, False)
        self._set_status({'ticks': 'Calibration cancelled.',
                          'extract': 'Extraction cancelled.',
                          'image': 'Image loading cancelled.'}.get(key, 'Cancelled.'))

    def _add_help(self, item, text):
        tooltip = self.own_widget(QToolTip(
            item, parent=self, delay=TOOLTIP_DELAY, hide_on_activity=True,
            ))
        label = QLabel(text, parent=tooltip, wrap=TOOLTIP_WRAP_WIDTH)
        tooltip.setTheme(tooltip_theme())
        # Image metadata updates this text later; preserve the text-item return.
        return label.tag

    def _build_data_panel(self, panel):
        with self.section("Review Data", parent=panel) as group:
            self.coordinate_mode = self.combo(["Chart X/Y", "Image pixels"],
                                              parent=group, width=-1,
                                              default_value="Chart X/Y", callback=self._coordinate_mode_changed)
            self._data_actions = {}
            for key, label, callback in (
                    ('select_all', 'Select all', self._select_all_data_points),
                    ('deselect', 'Deselect', self._clear_data_selection),
                    ('increase', 'Increase samples', self._increase_samples),
                    ('reduce', 'Reduce samples', self._reduce_samples),
                    ('simplify', 'Simplify by error', self._simplify_samples),
                    ('delete', 'Delete selected', self._delete_points),
                    ('clear', 'Clear all points', self._clear_points)):
                action = QAction(label, parent=self)
                action.triggered.connect(lambda _checked=False, callback=callback: callback())
                self._data_actions[key] = action
            self.data_coordinate_info = self.note("Showing image pixels until axes are calibrated.", parent=group, wrap=240)
            self.data_summary = self.note("No points in this dataset.", parent=group, wrap=240)
            self.result_grid = self.own_widget(QtDataGridView(
                    group,
                    [
                        {"key": "n", "label": "#", "width": 34, "align": "center"},
                        {"key": "x", "label": "X", "stretch": 1.0},
                        {"key": "y", "label": "Y", "stretch": 1.0},
                    ],
                    height=300, after=self.view.after, multiple=True,
                     sortable=False, resizable=True, horizontal_scrollbar=False))
            self.data_worksheet = self.result_grid.enableSpreadsheet(
                first_column=1, read_only=True, on_error=self._set_status)
            self.data_worksheet.selectionFinished.connect(self._data_selection_finished)
            self._add_help(self.result_grid.tag,
                           "Select X/Y cells, drag or Shift-click to extend, Ctrl+A/C to copy to Excel. "
                           "Edit point coordinates with the point editor; the results grid is read-only.")
            self.result_grid.currentChanged.connect(self._point_selected)
            self.result_grid.selectionChanged.connect(self._data_selection_changed)

            # One inspector and one optional settings area. Point-editing
            # commands remain available from the ribbon/shortcuts; View Data
            # itself stays focused on coordinates and export.
            with self.disclosure("Options", parent=group) as options:
                # Keep the persisted panel id stable across the inspector
                # redesign: existing .pdg projects store "reduction" here.
                self._disclosures["reduction"] = QRetainedItem(options).parentItem()
                form = self.form_layout(options, label_width=100)
                self.reduction_error = self.form_layout_row(form, "Max error (px)", lambda host: self.spin_float(
                    0.5, parent=host, minimum=0.0, maximum=10.0, step=0.1, decimals=2))
                self._add_help(self.reduction_error, "Maximum geometric error in image pixels. Set 0 for collinear-only reduction.")
                self.export_scope = self.form_layout_row(form, "Export scope", lambda host: self.combo(
                    ["All datasets", "Active dataset"], parent=host, width=-1,
                    default_value="All datasets", callback=lambda *_: self._refresh_export_controls()))
                self.export_sort = self.form_layout_row(form, "CSV order", lambda host: self.combo(
                    list(self.EXPORT_SORT_OPTIONS), parent=host, width=-1, default_value="Original order"))
                self._add_help(self.export_sort,
                               "Sort calibrated X or Y values in ascending order within each dataset, "
                               "or keep the original point order. Does not change the data table.")
            QSpacer(0, 6, parent=group)
            self._data_options_layout_binding = QItemInputBinding(
                self._disclosures["reduction"], parent=self).onClick(
                    Qt.LeftButton, lambda *_: self._schedule_data_layout()).activate()
            self.export_data_button = self.action(
                "Export CSV", self._choose_export_csv, parent=group, width=-1)
            self._add_help(self.export_data_button,
                           "Export calibrated X/Y data using the scope and sort options above. Calibrate all four axis anchors first.")

    def _build_canvas_panel(self, parent):
        # The canvas is a real framed surface that exists before an image is
        # loaded.  The drawlist only owns image/marker rendering inside it.
        self._canvas_frame_widget = self.own_widget(QFrame(
            parent=parent, width=self.CANVAS_MIN_WIDTH, height=440,
            frame_shape=QFrame.StyledPanel, no_scrollbar=True,
            no_scroll_with_mouse=True))
        self.canvas_frame = self._canvas_frame_widget.tag
        style_image_canvas(self.canvas_frame)
        self._canvas_widget = QCanvas(
            parent=self._canvas_frame_widget, width=self.CANVAS_MIN_WIDTH - 2,
            height=438)
        self.canvas = self._canvas_widget.tag
        self._build_canvas_view_tools()

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

    def _build_canvas_view_tools(self):
        # A sibling of the drawlist survives image/marker repainting and floats
        # inside the canvas frame without taking a row away from the image.
        self._canvas_view_toolbar = self.own_widget(QFrame(
            parent=self._canvas_frame_widget, width=self.CANVAS_VIEW_TOOLS_WIDTH,
            height=self.CANVAS_VIEW_TOOLS_HEIGHT, pos=(8, 6),
            frame_shape=QFrame.NoFrame, no_scrollbar=True, no_scroll_with_mouse=True))
        self._canvas_view_toolbar.setTheme(make_theme(theme_component(
            ThemeTarget.CHILD_WINDOW,
            colors={ThemeColor.CHILD_BACKGROUND: (0, 0, 0, 0),
                    ThemeColor.BORDER: (0, 0, 0, 0), ThemeColor.BORDER_SHADOW: (0, 0, 0, 0)},
            styles={ThemeStyle.WINDOW_PADDING: (2, 2), ThemeStyle.ITEM_SPACING: (4, 0),
                    ThemeStyle.CHILD_BORDER_SIZE: 0, ThemeStyle.CHILD_ROUNDING: 0})))
        # The renderer may not report hovered/active for a transparent child
        # overlay (or a disabled ImageButton). Drive the visible base fill from
        # actual pointer geometry instead of relying solely on native states.
        self._canvas_view_themes = {}
        for state, alpha in (('idle', 0), ('hover', 95), ('pressed', 170)):
            self._canvas_view_themes[state] = make_theme(*(theme_component(
                target,
                colors={ThemeColor.BUTTON: (0, 120, 215, alpha) if enabled else (120, 130, 140, alpha),
                        ThemeColor.BUTTON_HOVERED: (0, 120, 215, alpha) if enabled else (120, 130, 140, alpha),
                        ThemeColor.BUTTON_ACTIVE: (0, 120, 215, alpha) if enabled else (120, 130, 140, alpha),
                        ThemeColor.BORDER: (0, 0, 0, 0)},
                # Identical padding also prevents the disabled last icon from
                # inheriting larger global metrics and being clipped.
                styles={ThemeStyle.FRAME_BORDER_SIZE: 0, ThemeStyle.FRAME_ROUNDING: 3,
                        ThemeStyle.FRAME_PADDING: (2, 2), ThemeStyle.ALPHA: 1.0 if enabled else .6},
                enabled_state=enabled)
                for enabled in (True, False)
                for target in (ThemeTarget.PUSH_BUTTON, ThemeTarget.IMAGE_BUTTON)))
        row = self.own_widget(QHBoxLayout(parent=self._canvas_view_toolbar, spacing=4))
        self._canvas_view_buttons = {}
        self._canvas_view_tool_states = {}
        for key, icon, tooltip, callback in (
                ('fit', 'fit_view', 'Fit Image: fit the whole chart to the canvas', self._fit_view),
                ('one_to_one', 'one_to_one', 'Actual Size: one image pixel per screen pixel (1:1)', self._one_to_one),
                ('zoom_out', 'zoom_out', 'Zoom Out', lambda: self._zoom_at(1 / 1.15)),
                ('zoom_in', 'zoom_in', 'Zoom In', lambda: self._zoom_at(1.15))):
            button = self._icon_only_action(icon, callback, parent=row, tooltip=tooltip,
                                            button_size=28, icon_size=24)
            # These 64px assets include generous transparent margins. Display
            # their central 48px square so the artwork fills the 24px icon slot
            # without enlarging the buttons or changing their hit rectangles.
            self.control_wrapper(button).backend.configure_item(
                button, uv_min=(.125, .125), uv_max=(.875, .875))
            self.control_wrapper(button).setTheme(self._canvas_view_themes['idle'])
            self._canvas_view_buttons[key] = button
            self._canvas_view_tool_states[key] = 'idle'
            self.set_control_enabled(button, False)

    def _update_canvas_view_tool_states(self):
        point = QCursor.pos()
        down = bool(QCursor.buttons(backend=_renderer_backend()) & Qt.LeftButton)
        visible = self._canvas_view_toolbar.isVisible()
        for key, tag in self._canvas_view_buttons.items():
            button = self.control_wrapper(tag)
            hovered = visible and button.globalGeometry().contains(point)
            pressed = hovered and (button._pointer_pressed or down)
            state = 'pressed' if pressed else 'hover' if hovered else 'idle'
            if self._canvas_view_tool_states[key] != state:
                self._canvas_view_tool_states[key] = state
                button.setTheme(self._canvas_view_themes[state])

    def _canvas_view_tools_under_mouse(self):
        toolbar = getattr(self, '_canvas_view_toolbar', None)
        return bool(toolbar is not None and toolbar.isVisible()
                    and toolbar.globalGeometry().contains(QCursor.pos()))

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
            wrapper = self._control_wrappers[button]
            wrapper.setThemeProvider(lambda focused=False, disabled=False, tag=button, role=role:
                button_theme(role=role, focused=focused, disabled=disabled,
                             checked=self._control_wrappers[tag].isChecked(),
                             hovered=self._icon_action_hovered.get(tag, False)))
            try:
                self.own_widget(QItemInputBinding(
                    overlay_widget, parent=self
                ).onClick(
                    Qt.LeftButton,
                    lambda *_args, tag=button: self._click_icon_action(tag),
                ).onVisible(
                    lambda *_args, tag=button: self._sync_icon_action_hover(tag)
                ).activate())
            except Exception:
                pass
        return button

    def _click_icon_action(self, button):
        wrapper = self._control_wrappers.get(button)
        if wrapper is not None:
            wrapper.click()

    def _sync_icon_action_hover(self, button):
        """The icon drawlist is a separate native hover target from its button."""
        wrapper = self._control_wrappers.get(button)
        overlay = self._icon_action_canvases.get(button)
        if wrapper is None or overlay is None:
            return
        hovered = bool(wrapper.isEnabled() and (wrapper.underMouse() or overlay.underMouse()))
        if hovered != self._icon_action_hovered.get(button, False):
            self._icon_action_hovered[button] = hovered
            wrapper._refresh_style()

    def set_control_enabled(self, item, enabled):
        super().set_control_enabled(item, enabled)
        image = self._icon_action_draws.get(item)
        if image is not None:
            retained = QRetainedItem(image)
            if retained.exists():
                retained.configure(
                    color=(255, 255, 255, 255) if enabled else (155, 155, 155, 170))

    def _icon_only_action(self, icon_name, callback, *, parent, tooltip="", button_size=22, framed=False,
                          icon_size=None):
        """Create a compact icon-only action for dense tool rows."""
        if framed:
            # Plain square +/- controls use outer button dimensions, unlike
            # ImageButton dimensions which describe only the inner texture.
            button = self.action(
                {'add_item': '+', 'delete_item': '-', 'pick_anchor': '+'}.get(icon_name, ''),
                callback, parent=parent, width=button_size, height=button_size)
            if tooltip:
                self._add_help(button, tooltip)
            return button
        texture = self._icon_texture(icon_name, pixel_size=32)
        if not texture:
            glyph = {'add_item': '+', 'delete_item': '-'}.get(icon_name, '')
            return self.action(glyph, callback, parent=parent, width=button_size, height=button_size)
        render_size = max(16, min(int(button_size) - 4,
                                 self.COMPACT_ICON_RENDER_SIZE if icon_size is None else int(icon_size)))
        control = QToolButton(
            "", parent=self._native_parent_tag(parent), after=self.view.after, icon=texture,
            width=button_size, height=button_size, auto_raise=not framed,
            icon_size=(int(render_size), int(render_size)))
        control.clicked.connect(callback)
        button = control.tag
        self.own_widget(control)
        self._control_wrappers[button] = control
        if not framed:
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
        self._tool_pages["extract"] = manual_page
        with self.section("Extract Curve", parent=manual_page) as panel:
            self._build_auto_panel(panel)

        data_page_layout = QVBoxLayout(parent=parent, spacing=0, show=False)
        data_page = data_page_layout.tag
        self._tool_pages["data"] = data_page
        self._build_data_panel(data_page)

        self._build_point_editor(parent)
        # Create hidden controls once so dataset/engine synchronization remains
        # live; Settings itself is an owned dialog, never a workflow page.
        from .settings import PlotDigitizerSettingsDialog
        self._settings_dialog = self.own_dialog(PlotDigitizerSettingsDialog(self))

    def _open_settings(self):
        if self._pick_mode is not None:
            self._cancel_pick()
        self._refresh_dataset_controls()
        self._settings_dialog.show()

    def _build_plot_preferences_panel(self, parent, *, ui=None):
        """Build settings with controls owned by the separate settings dialog."""
        ui = ui or self
        self._build_auto_settings_panel(parent, ui=ui)
        with ui.section("Canvas & markers", parent=parent) as panel:
            ui.note("Display options apply immediately and are saved for future sessions. "
                      "They do not change chart data or saved calibration.", parent=panel, wrap=380)
            for key, title in (
                ("show_automatic_points", "Show extracted points"),
                ("show_manual_points", "Show manual points"),
                ("show_crosshair", "Show cursor crosshair"),
            ):
                self._preference_checkbox(key, title, panel, ui=ui)
            marker_form = ui.form_layout(panel, label_width=100)
            self._preference_spinner("marker_size_percent", "Marker size (%)", marker_form, step=10, ui=ui)
        with ui.section("Preview / Magnifier", parent=parent) as panel:
            self._preference_checkbox("show_magnifier", "Show preview panel", panel, ui=ui)
            preview_form = ui.form_layout(panel, label_width=130)
            self._preference_spinner("preview_zoom", "Preview zoom (x)", preview_form, ui=ui)
            self._preference_spinner("preview_size", "Panel size (px)", preview_form, step=20, ui=ui)
            self._preference_checkbox("preview_crosshair", "Show preview crosshair", panel, ui=ui)
            ui.note("Zoom: 1x-20x relative to the canvas. The preview follows the cursor "
                    "and keeps the last sampled position when you leave the image.", parent=panel, wrap=380)
        with ui.section("Navigation", parent=parent) as panel:
            self._preference_checkbox("mouse_wheel_zoom", "Mouse wheel zoom", panel, ui=ui)
            navigation_form = ui.form_layout(panel, label_width=130)
            self._preference_spinner("wheel_zoom_percent", "Wheel zoom step (%)", navigation_form, ui=ui)
            self._preference_checkbox("fit_images_on_open", "Fit newly opened images", panel, ui=ui)
            ui.note("Existing .pdg projects preserve their saved pan/zoom.", parent=panel, wrap=380)

    def _preference_spinner(self, key, title, form, *, step=1, ui=None):
        ui = ui or self
        minimum, maximum = PlotDigitizerPreferences.INT_RANGES[key]
        control = ui.form_layout_row(form, title, lambda host: ui.spin_int(
            self._plot_preferences[key], parent=host, minimum=minimum, maximum=maximum,
            step=step, width=-1,
            callback=lambda _sender, value, *_: self._preference_changed(key, value)))
        self._preference_controls[key] = control
        return control

    def _preference_checkbox(self, key, title, parent, *, ui=None):
        ui = ui or self
        control = ui.checkbox(title, checked=self._plot_preferences[key], parent=parent)
        ui._control_wrappers[control].setThemeProvider(lambda focused=False, disabled=False:
            rounded_checkbox_theme(ui._control_wrappers[control].backend, focused=focused, compact=True))
        self._preference_controls[key] = control
        ui._control_wrappers[control].toggled.connect(
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
                if key in PlotDigitizerPreferences.INT_RANGES:
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
        with self.section("Calibration", parent=parent) as panel:
            self.snap_to_axes = self.checkbox('Snap to Axes', checked=True, parent=panel)
            self._control_wrappers[self.snap_to_axes].setThemeProvider(lambda focused=False, disabled=False:
                rounded_checkbox_theme(self._control_wrappers[self.snap_to_axes].backend, focused=focused, compact=True))
            self._control_wrappers[self.snap_to_axes].toggled.connect(self._axis_snapping_changed)
            self._add_help(self.snap_to_axes,
                'Snap selected plot areas to detected axis lines. Turn off to keep the exact drawn rectangle.')
            QSpacer(0, 6, parent=panel)
            self.calibration_hint = self.note("", parent=panel, wrap=240)
            self.set_control_visible(self.calibration_hint, False)
            form = self.form_layout(panel, label_width=46)
            self.calibration_axis = self.form_layout_row(form, "Axis", lambda host: self.combo(
                ["X", "Y"], parent=host, default_value="X",
                callback=lambda *_: self._calibration_axis_changed()))
            QSpacer(0, 6, parent=panel)
            tick_commands = self.own_widget(ToolCommandRow(panel, after=self.view.after))
            self.add_axis_point_button = self.action(
                'Add Tick', self._begin_place_axis_point,
                parent=tick_commands.cell(0, 0), width=-1, height=26)
            self.auto_detect_ticks_button = self.action(
                'Read Ticks', self._reread_calibration_ticks,
                parent=tick_commands.cell(0, 1), width=-1, height=26)
            self._add_help(self.add_axis_point_button,
                'Place a new tick on the image, drag it into position, then enter Value and click Set Value. Esc discards the draft.')
            self._add_help(self.auto_detect_ticks_button,
                'Read tick values automatically in the selected plot area, or select a plot area first.')
            QSpacer(0, 6, parent=panel)

            self.calibration_grid = self.own_widget(QtDataGridView(
                panel, [{"key": "n", "label": "Tick", "width": 44},
                        {"key": "pixel", "label": "Pixel", "stretch": 1.0},
                        {"key": "value", "label": "Value", "stretch": 1.0}],
                height=150, after=self.view.after, multiple=False, sortable=False,
                resizable=True, horizontal_scrollbar=False))
            self.calibration_grid.currentChanged.connect(self._calibration_point_selected)
            self._calibration_table_help = self._add_help(self.calibration_grid.tag,
                'Select a tick to edit it. Use Select Plot on the ribbon to select the chart and read axes; '
                'Add Tick places a draggable manual tick; enter its Value and click Set Value. Manual Calibration provides two-point bounds.')
            self._selected_calibration_point = None
            self._calibration_editor = self.own_widget(QVBoxLayout(parent=panel, spacing=6))
            self.calibration_selected_info = self.note('Selected tick', parent=self._calibration_editor.tag)
            values = self.form_layout(self._calibration_editor.tag, label_width=46)
            self.calibration_point_value = self.form_layout_row(values, "Value", lambda host: self.line_edit(
                "0", parent=host, width=-1, on_enter=True,
                callback=lambda *_: self._update_calibration_point_value()))
            commands = self.own_widget(ToolCommandRow(self._calibration_editor, after=self.view.after))
            self.update_calibration_button = self.action(
                "Set Value", self._update_calibration_point_value, parent=commands.cell(0, 0), width=-1)
            self.repick_calibration_button = self.action(
                "Pick Position", self._repick_calibration_point, parent=commands.cell(0, 1), width=-1)
            self.remove_calibration_button = self.action(
                "Delete Tick", self._remove_calibration_point, parent=self._calibration_editor, width=-1, height=24)
            self._calibration_editor.hide()
            QSpacer(0, 8, parent=panel)
            scales = self.own_widget(ToolCommandRow(panel, gap=6, after=self.view.after))
            for column, axis in enumerate(('x', 'y')):
                scale_form = self.form_layout(scales.cell(0, column).tag, label_width=14)
                control = self.form_layout_row(scale_form, axis.upper(), lambda host: self.combo(
                    [s.value for s in AxisScale], parent=host, default_value=AxisScale.LINEAR.value,
                    callback=self._scale_changed))
                setattr(self, 'scale_' + axis, control)
                self._add_help(control, '{} axis scale'.format(axis.upper()))
            self.anchor_value = {}
            self.anchor_pick_buttons = {}
            QSpacer(0, 8, parent=panel)
            with self.disclosure("Manual Calibration", parent=panel) as bounds:
                self._disclosures['axes'] = QRetainedItem(bounds).parentItem()
                QSpacer(0, 6, parent=bounds)
                new_value = self.form_layout(bounds, label_width=60)
                self.new_calibration_value = self.form_layout_row(new_value, 'New value', lambda host: self.line_edit(
                    '0', parent=host, width=-1, on_enter=True,
                    callback=lambda *_: self._begin_manual_calibration_point()))
                QSpacer(0, 6, parent=bounds)
                self.add_calibration_button = self.action('Pick tick on image', self._begin_manual_calibration_point,
                    parent=bounds, width=-1, height=28, role='primary')
                QSpacer(0, 8, parent=bounds)
                x_form = self.form_layout(bounds, label_width=26)
                for key, label in (("x1", "X1"), ("x2", "X2")):
                    self._anchor_row(x_form, key, label)
                QSpacer(0, 6, parent=bounds)
                y_form = self.form_layout(bounds, label_width=26)
                for key, label in (("y1", "Y1"), ("y2", "Y2")):
                    self._anchor_row(y_form, key, label)
                QSpacer(0, 8, parent=bounds)
                self.apply_calibration_button = self._icon_action(
                    "Apply Axis Values", "apply_changes", self._apply_calibration_values,
                    parent=bounds, width=-1)
                self._add_help(self.apply_calibration_button,
                    'Applying these bounds replaces the multi-point fit with two points per axis.')
                QSpacer(0, 6, parent=bounds)
                self.calibrate_area_button = self._icon_action(
                    "Use Plot Edges", "plot_area", self._calibrate_area,
                    parent=bounds, width=-1)
                self._add_help(self.calibrate_area_button, "Map all four entered values to the edges of the selected plot area, replacing the tick fit.")
                QSpacer(0, 6, parent=bounds)
                self.reset_axes_button = self._icon_action(
                    "Reset Axes", "reset", self.engine.reset_calibration,
                    parent=bounds, width=-1)
            self._set_calibration_method(self._calibration_method, cancel_pending=False)

    def _axis_snapping_changed(self, enabled):
        enabled = bool(enabled)
        if enabled == self.engine.calibration.snap_to_axes:
            return  # Programmatic refresh after load/Undo is not a new edit.
        was_busy = self._tick_calibration_runner.busy
        if was_busy:
            self._tick_calibration_runner.cancel()
            self._region_alignment_preview = None
            self._finish_progress('ticks', False)
        self.engine.set_axis_snapping(enabled)
        if was_busy:
            self._start_tick_calibration(self.engine.plot_rect)

    def _set_calibration_method(self, method, *, cancel_pending=True):
        if method not in ('manual', 'smart'):
            raise ValueError('Unknown calibration method.')
        changed = method != self._calibration_method
        if changed and cancel_pending and (self._pick_mode is not None or self._calibration_draft is not None):
            self._cancel_pick()
        if method == 'manual' and self._tick_calibration_runner.busy:
            self._tick_calibration_runner.cancel()
            self._region_alignment_preview = None
            self._finish_progress('ticks', False)
            self._set_status('Calibration cancelled.', details='Manual calibration selected; existing ticks were kept.')
            self._redraw()
        self._calibration_method = method
        self._refresh_calibration_actions()

    def _refresh_calibration_actions(self):
        if not hasattr(self, 'add_calibration_button'):
            return
        has_image = self.engine.image is not None
        busy = self._tick_calibration_runner.busy
        self.set_control_enabled(self.add_calibration_button, has_image and not busy)
        self.set_control_enabled(self.new_calibration_value, has_image and not busy)
        self.set_control_enabled(self.add_axis_point_button, has_image)
        self.set_control_enabled(self.auto_detect_ticks_button, has_image and not busy)
        self.ribbon.set_button_enabled('read_axes', has_image and not busy)
        selected = self._selected_calibration_point is not None
        self._calibration_editor.setVisible(selected)
        for control in (self.update_calibration_button, self.repick_calibration_button, self.remove_calibration_button):
            self.set_control_enabled(control, selected and not busy)
        if selected:
            axis, index = self._selected_calibration_point
            self.set_control_value(self.calibration_selected_info,
                'New {} tick: enter Value, Set Value'.format(axis.upper()) if index == 'draft' else
                'Selected tick: {}{}'.format(axis.upper(), index + 1))

    def _begin_manual_calibration_point(self):
        self._begin_add_calibration_point(self.control_value(self.new_calibration_value))

    def _reread_calibration_ticks(self):
        if self.engine.image is None:
            return self._set_status('Open an image first.')
        self._show_tool('axes')
        self._set_calibration_method('smart')
        if self.engine.plot_rect is None:
            return self._begin_pick('area')
        self._start_tick_calibration(self.engine.plot_rect)

    def _build_auto_panel(self, parent):
        self.pick_color_button = self.action(
            "Pick Color", lambda: self._begin_pick("curve"),
            parent=parent, width=-1, height=28)
        self._pick_color_button_help = self._add_help(self.pick_color_button,
            "Click here, then click a curve stroke on the image to sample its color. Esc cancels.")
        self._control_wrappers[self.pick_color_button].setThemeProvider(self._pick_color_button_theme)
        QSpacer(0, 6, parent=parent)
        self.extract_button = self.action(
            "Extract", self._extract_curve, role="primary",
            parent=parent, width=-1, height=28)
        self._add_help(self.extract_button,
                       "Extract the sampled curve. Manual and automatic points are kept in the same dataset. Settings controls extraction options.")
        self.smart_button = self.extract_button

    def _sync_pick_color(self, rgb):
        color = tuple(rgb[:3]) if rgb is not None else None
        if color != self._pick_color_rgb:
            previous = self._pick_color_themes
            self._pick_color_rgb = color
            self._pick_color_themes = {}
            self._control_wrappers[self.pick_color_button].setThemeProvider(self._pick_color_button_theme)
            for theme in previous.values():
                theme.delete()
        label = '#{:02X}{:02X}{:02X}'.format(*rgb[:3]) if rgb is not None else 'No color selected'
        self.set_control_value(self._pick_color_button_help, 'Pick Color: {}. Click this button, then click a curve stroke on the image. Esc cancels.'.format(label))

    def _pick_color_button_theme(self, *, focused=False, disabled=False):
        button = self._control_wrappers[self.pick_color_button]
        color = self._pick_color_rgb
        if color is None or disabled:
            return button_theme(backend=button.backend, focused=focused, disabled=disabled)
        if focused not in self._pick_color_themes:
            # Choose black/white by contrast ratio, not a brightness threshold
            # (saturated greens/yellows otherwise get unreadable white text).
            linear = [v / 12.92 if v <= .04045 else ((v + .055) / 1.055) ** 2.4
                      for v in (channel / 255 for channel in color)]
            luminance = sum(v * w for v, w in zip(linear, (.2126, .7152, .0722)))
            dark_text = (luminance + .05) / .05 >= 1.05 / (luminance + .05)
            text = (0, 0, 0, 255) if dark_text else (255, 255, 255, 255)
            target = 255 if dark_text else 0
            def shade(amount):
                return tuple(round(c + (target - c) * amount) for c in color) + (255,)
            self._pick_color_themes[focused] = ThemeSpec((theme_component(
                ThemeTarget.PUSH_BUTTON,
                colors={ThemeColor.BUTTON: (*color, 255),
                        ThemeColor.BUTTON_HOVERED: shade(.12),
                        ThemeColor.BUTTON_ACTIVE: shade(.22),
                        ThemeColor.TEXT: text,
                        ThemeColor.BORDER: QtFusionPalette.FOCUS if focused else QtFusionPalette.BORDER},
                styles={ThemeStyle.FRAME_BORDER_SIZE: 1, ThemeStyle.FRAME_ROUNDING: 3,
                        ThemeStyle.FRAME_PADDING: (8, 3), ThemeStyle.BUTTON_TEXT_ALIGN: (.5, .5)}),
                )).createObject(parent=self)
        return self._pick_color_themes[focused]

    def _build_auto_settings_panel(self, parent, *, ui=None):
        """Keep advanced controls available without crowding the workflow page."""
        ui = ui or self
        with ui.section("Automatic extraction settings", parent=parent) as panel:
            self.curve_color = ui.own_widget(ColorField(panel, after=self.view.after))
            ui.enter_editors.add(self.curve_color.editor.tag)
            self.curve_color.changed.connect(self._color_changed)
            self.palette_combo = ui.combo(["Find image colors..."], parent=panel,
                                            default_value="Find image colors...", callback=self._palette_selected)
            ui.set_control_visible(self.palette_combo, False)
            tolerance_form = ui.form_layout(panel, label_width=100)
            self.tolerance = ui.form_layout_row(tolerance_form, "Tolerance", lambda host: ui.spin_int(
                55, parent=host, minimum=1, maximum=255, step=1, width=-1,
                callback=lambda _sender, value, *_: self._setting_changed("tolerance", value)))
            QSpacer(0, 6, parent=panel)
            self.find_colors_button = ui.action(
                "Find Colors", self._auto_color, parent=panel, width=-1)
            with ui.disclosure("Advanced", parent=panel) as advanced:
                self._disclosures["advanced"] = QRetainedItem(advanced).parentItem()
                self._build_extraction_options(advanced, ui=ui)

    def _build_point_editor(self, parent):
        point_editor_layout = QVBoxLayout(
            parent=parent, spacing=0, show=False)
        self.point_editor_container = point_editor_layout.tag
        with self.section("Selected point", parent=self.point_editor_container) as panel:
            self.point_info = self.status_text("", parent=panel)
            QSpacer(0, 6, parent=panel)
            point_fields_layout = QVBoxLayout(parent=panel, spacing=0)
            self.point_fields = point_fields_layout.tag
            coordinate_row = self.own_widget(ToolCommandRow(self.point_fields, after=self.view.after))
            x_form = self.form_layout(coordinate_row.cell(0, 0).tag, label_width=14)
            y_form = self.form_layout(coordinate_row.cell(0, 1).tag, label_width=14)
            self.point_x = self.form_layout_row(x_form, "X", lambda host: self.line_edit(
                "", parent=host, on_enter=True, callback=lambda *_: self._apply_point()))
            self.point_y = self.form_layout_row(y_form, "Y", lambda host: self.line_edit(
                "", parent=host, on_enter=True, callback=lambda *_: self._apply_point()))
            QSpacer(0, 6, parent=panel)
            self.point_navigation = self.own_widget(ToolCommandRow(
                panel, columns=2, after=self.view.after))
            self.previous_point_button = self.action(
                "Previous", lambda: self._navigate_point(-1),
                parent=self.point_navigation.cell(0, 0), width=-1)
            self.next_point_button = self.action(
                "Next", lambda: self._navigate_point(1),
                parent=self.point_navigation.cell(0, 1), width=-1)
            self._add_help(self.point_x, "Edit X, then press Enter to update the point.")
            self._add_help(self.point_y, "Edit Y, then press Enter to update the point.")
            self._add_help(self.previous_point_button, "Select the previous point on the image and in the table (P).")
            self._add_help(self.next_point_button, "Select the next point on the image and in the table (N).")

    def _show_tool(self, tool):
        tool = {'manual': 'extract', 'automatic': 'extract'}.get(tool, tool)
        if tool == "settings":
            self._open_settings()
            return
        if tool not in self._tool_pages:
            return
        self.ribbon.set_active_tab('data' if tool == 'data' else 'home')
        if tool == self._active_tool:
            return
        if self._pick_mode is not None or self._calibration_draft is not None:
            self._cancel_pick()
        self._active_tool = tool
        if tool != "axes":
            self._anchor_drag_target = None
            self._anchor_drag_preview = None
            self._hover_anchor = None
        for name, page in self._tool_pages.items():
            self.set_control_visible(page, name == tool)
        self.active_table = self.result_grid if tool == "data" else None
        QRetainedItem(self.settings_panel).setVerticalScrollValue(0)
        if self.tool_list.currentKey() != tool:
            self.tool_list.setCurrentKey(tool, select=True)
        self._refresh_point_editor()

        self._refresh_workflow_completion()

    def _workflow_check_clicked(self, key, _checked):
        # Completion is derived from actual work, never a user-toggled flag.
        self._show_tool(key)
        self._refresh_workflow_completion()

    def _refresh_workflow_completion(self):
        dataset = self.engine.active_dataset
        has_points = bool(dataset.extracted_pixels or dataset.manual_points)
        if self._active_tool == 'data' and has_points:
            self._reviewed_datasets.add(id(dataset))
        completed = (self.engine.calibration_ready(), has_points,
                     has_points and id(dataset) in self._reviewed_datasets)
        self.tool_list.setItems([
            QtListItem(key, text, checked=checked)
            for key, text, checked in zip(('axes', 'extract', 'data'),
                                         ('Calibrate Axes', 'Extract Curve', 'Review Data'), completed)])

    def _apply_calibration_values(self):
        try:
            values = {}
            for key, item in self.anchor_value.items():
                if self._manual_bounds_axes and key[0] not in self._manual_bounds_axes:
                    continue
                if not str(self.control_value(item)).strip():
                    raise ValueError('Enter a value for {}.'.format(key.upper()))
                scale = getattr(self.engine.calibration, "scale_" + key[0])
                values[key] = parse_axis_value_input(self.control_value(item), scale)
            if self._manual_bounds_axes:
                self.engine.set_axis_bounds(values)
                self._manual_bounds_axes.clear()
            else:
                self.engine.set_anchor_values(values)
            self.set_control_visible(self.calibration_hint, False)
            self._refresh_anchor_values()
            self._set_status("Axes calibrated.")
        except ValueError as exc:
            self._set_status(str(exc))

    def _build_extraction_options(self, panel, *, ui=None):
        ui = ui or self
        settings_form = ui.form_layout(panel, label_width=100)
        for key, label, value, minimum, maximum in (
            ("continuity", "Continuity (px)", 28, 1, 250),
            ("smoothing", "Smoothing", 3, 0, 30),
            ("stride", "Sample stride", 1, 1, 50),
            ("minimum_saturation", "Min saturation", 70, 0, 255),
            ("max_gap", "Max gap", 25, 0, 500),
        ):
            control = ui.form_layout_row(
                settings_form, label,
                lambda host, v=value, lo=minimum, hi=maximum, k=key: ui.spin_int(
                    v, parent=host, minimum=lo, maximum=hi, step=1, width=-1,
                    callback=lambda _sender, value, *_: self._setting_changed(k, value)))
            setattr(self, key, control)
        row = ui.own_widget(ToolCommandRow(panel, after=self.view.after))
        self.detect_area_button = ui.action(
            "Detect Area", self._detect_area,
            parent=row.cell(0, 0), width=-1)
        self.reset_area_button = ui.action(
            "Reset Area", lambda: self.engine.set_plot_rect(None),
            parent=row.cell(0, 1), width=-1)
        self.roi_info = ui.status_text("", parent=panel)

    def _calibration_axis_changed(self):
        if self._pick_mode in ("calibration_x", "calibration_y") or self._calibration_draft is not None:
            self._cancel_pick()
        self._selected_calibration_point = None
        self._refresh_calibration_points()

    def _calibration_point_selected(self, key, *_):
        previous = self._selected_calibration_point
        self._selected_calibration_point = None
        if key:
            axis, index = str(key).split(":")
            if index == 'draft':
                if self._calibration_draft is not None and self._calibration_draft['axis'] == axis:
                    self._selected_calibration_point = (axis, 'draft')
                    if previous != self._selected_calibration_point:
                        self.set_control_value(self.calibration_point_value, '')
                    self._refresh_calibration_actions()
                return
            index = int(index)
            points = self.engine.calibration_points(axis)
            if axis.upper() == self.control_value(self.calibration_axis) and 0 <= index < len(points):
                self._selected_calibration_point = (axis, index)
                if self._anchor_drag_target is None:
                    self.calibration_grid.setFocus()
                self.set_control_value(self.calibration_point_value, self._fmt_axis(points[index].value, axis))
        self._refresh_calibration_actions()

    def _refresh_calibration_points(self):
        if not hasattr(self, "calibration_grid"):
            return
        axis = self.control_value(self.calibration_axis).lower()
        points = self.engine.calibration_points(axis)
        through_ticks = getattr(self.engine.calibration, "mapping_" + axis) == "ticks"
        fit = None if through_ticks else self.engine.calibration._fit(axis)
        logarithmic = getattr(self.engine.calibration, "scale_" + axis) in (AxisScale.LOG10, AxisScale.LN)
        errors = [(fit[0] * (p.px if axis == "x" else p.py) + fit[1]
                   - (math.log(p.value) if logarithmic else p.value)) for p in points] if fit else []
        rows = [
            QtGridRow("{}:{}".format(axis, i), ("{}{}{}".format(axis.upper(),
                't' if self.engine.calibration.box_rect is not None else '', i + 1),
                self._fmt(p.px if axis == "x" else p.py), self._fmt_axis(p.value, axis)))
            for i, p in enumerate(points)]
        draft = self._calibration_draft
        if draft is not None and draft['axis'] == axis:
            rows.append(QtGridRow(axis + ':draft', (axis.upper() + ' new',
                self._fmt(draft['px'] if axis == 'x' else draft['py']), 'Enter value')))
        self.calibration_grid.setRows(rows)
        selected = self._selected_calibration_point
        if selected is not None and (selected[0] != axis or
                (selected[1] == 'draft' and draft is None) or
                (selected[1] != 'draft' and selected[1] >= len(points))):
            self._selected_calibration_point = None
        self._refresh_calibration_actions()
        if through_ticks:
            info = "{}: {} ticks | Piecewise mapping".format(axis.upper(), len(points))
        elif fit is None:
            info = ("{}: two-point calibration.".format(axis.upper()) if len(points) >= 2 else
                    "{}: {} tick(s) | Need at least 2".format(axis.upper(), len(points)))
        else:
            rmse = math.sqrt(sum(e * e for e in errors) / len(errors))
            info = "{}: {} points | RMSE: {}{}".format(
                axis.upper(), len(points), self._fmt(rmse), " (ln units)" if logarithmic else "")
        self.set_control_value(self._calibration_table_help,
            '{}\nSelect a tick to edit. Use Select Plot on the ribbon for automatic calibration; '
            'Add Tick places a draggable manual tick; enter Value and click Set Value.'.format(info))

    def _begin_place_axis_point(self):
        if self.engine.image is None:
            return self._set_status('Open an image first.')
        if self._calibration_draft is not None:
            self._cancel_pick()
        axis = self.control_value(self.calibration_axis).lower()
        self._begin_pick('calibration_' + axis)
        self._calibration_pick = (axis, None, None)
        self._set_status('Place a new {} tick. Esc cancels.'.format(axis.upper()),
                         details='Click the image, drag the new marker to its tick, then enter Value and click Set Value.')

    def _place_calibration_draft(self, axis, px, py):
        box = self.engine.calibration.box_rect
        if box is not None:
            px, py = (px, box[3]) if axis == 'x' else (box[0], py)
        self._calibration_draft = dict(axis=axis, px=px, py=py)
        self._selected_calibration_point = (axis, 'draft')
        self._refresh_calibration_points()
        self.calibration_grid.setCurrentKey(axis + ':draft', select=True, focus=False)

    def _begin_add_calibration_point(self, value_text=None):
        if self.engine.image is None:
            return self._set_status("Open an image first.")
        try:
            axis = self.control_value(self.calibration_axis).lower()
            scale = getattr(self.engine.calibration, "scale_" + axis)
            value = parse_axis_value_input(
                self.control_value(self.calibration_point_value) if value_text is None else value_text, scale)
            if scale in (AxisScale.LOG10, AxisScale.LN) and value <= 0:
                raise ValueError("Logarithmic tick values must be > 0.")
            self._begin_pick("calibration_" + axis)
            self._calibration_pick = (axis, None, value)
        except ValueError as exc:
            self._set_status(str(exc))

    def _update_calibration_point_value(self):
        selected = self._selected_calibration_point
        if selected is None:
            return self._set_status("Select a calibration tick first.")
        try:
            axis, _index = selected
            scale = getattr(self.engine.calibration, "scale_" + axis)
            value = parse_axis_value_input(self.control_value(self.calibration_point_value), scale)
            if selected[1] == 'draft':
                draft = self._calibration_draft
                self.engine.add_calibration_point(axis, draft['px'], draft['py'], value)
                index = len(self.engine.calibration_points(axis)) - 1
                self._calibration_draft = None
                self._selected_calibration_point = (axis, index)
                self._refresh_calibration_points()
                self.calibration_grid.setCurrentKey('{}:{}'.format(axis, index), select=True)
                self._set_status('{} tick added.'.format(axis.upper()))
                self._redraw()
                return
            self.engine.update_calibration_point(*selected, value=value)
            self._set_status("Tick updated.")
        except (ValueError, IndexError) as exc:
            self._set_status(str(exc))

    def _repick_calibration_point(self):
        selected = self._selected_calibration_point
        if selected is None:
            return
        axis, index = selected
        if index == 'draft':
            self._begin_pick('calibration_' + axis)
            self._calibration_pick = (axis, 'draft', None)
            return
        point = self.engine.calibration_points(axis)[index]
        self._begin_pick("calibration_" + axis)
        self._calibration_pick = (axis, index, point.value)

    def _remove_calibration_point(self):
        selected = self._selected_calibration_point
        if selected is None:
            return
        if selected[1] == 'draft':
            self._cancel_pick()
            return
        try:
            self._selected_calibration_point = None
            self.calibration_grid.current = self.calibration_grid.anchor = None
            self.calibration_grid.clearSelection()
            self._anchor_drag_target = self._anchor_drag_preview = self._hover_anchor = None
            self.engine.remove_calibration_point(*selected)
            self._set_status("Tick removed.", details='At least two points per axis are required.')
        except (ValueError, IndexError) as exc:
            self._set_status(str(exc))

    def _anchor_row(self, table, key, label):
        def build(host):
            row_layout = self.own_widget(ToolCommandRow(
                host, column_widths=(None, 26), gap=6, after=self.view.after))
            self.anchor_value[key] = self.line_edit(
                "", parent=row_layout.cell(0, 0).tag, width=-1,
                on_enter=True,
                callback=lambda _sender, value, *_: self._anchor_value_changed(key, value))
            self.set_control_enabled(self.anchor_value[key], False)
            self.anchor_pick_buttons[key] = self._icon_only_action(
                "pick_anchor", lambda: self._begin_pick(key), parent=row_layout.cell(0, 1),
                tooltip="Pick {} anchor".format(label), button_size=26, framed=True)
        self.form_layout_row(table, label, build)

    def _anchor_value_changed(self, key, value):
        if key[0] in self._manual_bounds_axes:
            # Stage the pair. A single entered endpoint must not confirm the
            # other endpoint's hidden 0/1 seed or erase the detected axis.
            self._set_status('Enter both {} values, then Apply Axis Values.'.format(key[0].upper()))
            return
        anchor = getattr(self.engine.calibration, key)
        if anchor is None:
            return
        try:
            scale = getattr(self.engine.calibration, "scale_" + key[0])
            parsed = parse_axis_value_input(value, scale)
            self.engine.set_anchor(key, anchor.px, anchor.py, parsed)
        except ValueError as exc:
            self._set_status(str(exc))

    def _anchor_pick_value(self, key):
        """Return a safe temporary value for a newly picked axis anchor.

        Axis-value editors stay disabled until their pixel anchor exists, so a
        first click needs a valid seed value. Existing anchors retain their
        edited value. New linear anchors use 0/1 where possible; logarithmic
        anchors use positive 1/10 seeds. If the paired anchor already owns the
        preferred seed, choose a distinct value so partial calibration remains
        valid.
        """
        calibration = self.engine.calibration
        existing = getattr(calibration, key)
        if existing is not None:
            return existing.value
        axis = key[0]
        scale = calibration.scale_x if axis == "x" else calibration.scale_y
        linear_like = scale in (AxisScale.LINEAR, AxisScale.DATETIME)
        preferred = (1.0 if key.endswith("2") else 0.0) if linear_like else (10.0 if key.endswith("2") else 1.0)
        other_key = axis + ("1" if key.endswith("2") else "2")
        other = getattr(calibration, other_key)
        if other is None or other.value != preferred:
            return preferred
        if linear_like:
            return other.value + (1.0 if key.endswith("2") else -1.0)
        return other.value * (10.0 if key.endswith("2") else 0.1)

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
        if _event == 'data_changed':
            self._reviewed_datasets.discard(id(self.engine.active_dataset))
        elif _event in ('calibration_changed', 'state_restored', 'image_changed', 'project_loaded'):
            self._reviewed_datasets.clear()
        if _event in ('active_dataset_changed', 'dataset_list_changed', 'image_changed', 'project_loaded'):
            self._reviewed_datasets.intersection_update(id(ds) for ds in self.engine.datasets)
        # Engine events precede the deferred heavy UI refresh. Keep command
        # availability current even if a key/click follows in the same batch.
        self._refresh_history_commands()
        if _event == "data_changed":
            self._reset_point_gesture()
        if _event in ("active_dataset_changed", "dataset_list_changed", "state_restored", "image_changed", "project_loaded"):
            self._clear_point_selection()
            self._hover_point = None
            self._drag_target = self._drag_preview = self._drag_start = None
            self._region_first_corner = self._region_press = None
            self._region_alignment_preview = None
            self._reset_point_gesture()
            # Undo/Redo restores point data, not the user's interaction mode.
            # Revalidate the mode against the restored image/dataset lock.
            self._set_edit_enabled(self._edit_enabled if _event == "state_restored" else False)
        if _event in ("active_dataset_changed", "dataset_list_changed", "image_changed", "project_loaded"):
            self._sample_pixel = None
        if _event in ("image_changed", "project_loaded"):
            self._preview_pixel = None
        if _event in ("state_restored", "image_changed", "project_loaded"):
            self._calibration_draft = None
            self._manual_bounds_axes.clear()
            self._display_axis_ticks = None
            self._anchor_drag_target = self._anchor_drag_preview = self._hover_anchor = None
            if self._pick_mode in ("calibration_x", "calibration_y"):
                self._pick_mode = None
                self._calibration_pick = None
                self.set_control_visible(self.calibration_hint, False)
        if _event in ("image_changed", "project_loaded"):
            self._project_load_generation += 1
            self._calibration_sequence = []
            self._pick_mode = None
            self._calibration_pick = None
            self._selected_calibration_point = None
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
        self._refresh_workflow_completion()
        image = self.engine.image
        anchors = sum(getattr(self.engine.calibration, key) is not None for key in ("x1", "x2", "y1", "y2"))
        ds = self.engine.active_dataset
        title = 'Plot Digitizer'
        if image is not None:
            title += ' - ' + Path(self.engine.image_path or 'Embedded image').name
        if self.windowTitle() != title:
            self.setWindowTitle(title)
        if (getattr(self.view, 'is_standalone_ui_host', False)
                and getattr(self.view, '_native_hwnd', 0)
                and getattr(self, '_viewport_title', None) != title):
            if QGuiRuntime().setViewportTitle(title):
                self._viewport_title = title
        has_image = image is not None
        for control in (*self.anchor_pick_buttons.values(), self.detect_area_button):
            self.set_control_enabled(control, has_image)
        for key, editor in self.anchor_value.items():
            self.set_control_enabled(editor, getattr(self.engine.calibration, key) is not None)
        self.set_control_enabled(self.apply_calibration_button, has_image and anchors == 4)
        self.set_control_enabled(self.calibrate_area_button, has_image and self.engine.plot_rect is not None)
        self.set_control_enabled(self.reset_axes_button, anchors > 0)
        self.set_control_enabled(self.reset_area_button, has_image and self.engine.plot_rect is not None)
        self.set_control_enabled(self.delete_dataset_button, len(self.engine.datasets) > 1 and not ds.locked)
        self.ribbon.set_button_enabled('box', has_image)
        for button in self._canvas_view_buttons.values():
            self.set_control_enabled(button, has_image)
        self.ribbon.set_button_enabled('view_data', has_image)
        self.ribbon.set_button_enabled("save_project", True)
        self._refresh_calibration_actions()
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
        if not hasattr(self, "_data_actions"):
            return
        ds = self.engine.active_dataset
        has_points = bool(ds.extracted_pixels or ds.manual_points)
        selected = bool(self._selected_point is not None or self.result_grid.selectedKeys())
        self.ribbon.set_button_enabled('delete_points', not ds.locked and selected)
        self.ribbon.set_button_enabled('data_delete', not ds.locked and selected)
        self._data_actions['delete'].setEnabled(not ds.locked and selected)
        self._data_actions['clear'].setEnabled(not ds.locked and has_points)
        point_count = len(ds.extracted_pixels) + len(ds.manual_points)
        can_resample = not ds.locked and not self._smart_runner.busy
        self._data_actions['increase'].setEnabled(can_resample and point_count >= 2)
        self._data_actions['reduce'].setEnabled(can_resample and point_count >= 3)
        self._data_actions['simplify'].setEnabled(can_resample and
                                                  (len(ds.extracted_pixels) > 2 or len(ds.manual_points) > 2))
        for key, minimum in (('smooth_curve', 3), ('samples', 2)):
            self.ribbon.set_button_enabled(key, can_resample and point_count >= minimum)
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
        self._data_actions['select_all'].setEnabled(count > 0)
        self._data_actions['deselect'].setEnabled(selected > 0 or self._selected_point is not None)

    def _select_all_data_points(self):
        self.data_worksheet.command('all')
        self._refresh_point_actions()

    def _clear_data_selection(self):
        self._clear_point_selection()
        self._refresh_point_editor()
        self._redraw()

    def _refresh_dataset_list(self):
        self.dataset_list.setItems([
            QtListItem(i, "{}  |  {} pts{}".format(ds.name,
                       len(ds.extracted_pixels) + len(ds.manual_points), " [Locked]" if ds.locked else ""),
                       ds, checked=ds.visible)
            for i, ds in enumerate(self.engine.datasets)
        ])
        count = len(self.engine.datasets)
        # No empty second row for a single curve; grow up to four rows,
        # then use the list's own scrolling for larger projects.
        row_height = self.dataset_list.rowHeight()
        self.dataset_list.setFixedHeight(min(4, max(1, count)) * row_height + 2)
        if self.dataset_list.currentKey() != self.engine.active_dataset_index:
            self.dataset_list.setCurrentKey(self.engine.active_dataset_index, select=True)

    def _refresh_dataset_controls(self):
        if not self.winfo_exists():
            return
        ds = self.engine.active_dataset
        self.curve_color.setColor(ds.curve_rgb)
        self._sync_pick_color(ds.curve_rgb)
        unlocked = not ds.locked
        if not unlocked and self._edit_enabled:
            self._set_edit_enabled(False)
        has_image = self.engine.image is not None
        for control in (self.pick_color_button, self.find_colors_button):
            self.set_control_enabled(control, unlocked and has_image)
        self.ribbon.set_button_enabled("pick_color", unlocked and has_image)
        self.ribbon.set_button_enabled("edit", unlocked and has_image)
        self._refresh_point_actions()
        can_extract = (unlocked and has_image and ds.curve_rgb is not None
                       and not self._smart_runner.busy)
        self.set_control_enabled(self.smart_button, can_extract)
        self.set_control_enabled(self.extract_button, can_extract)
        self.ribbon.set_button_enabled('extract', can_extract)
        self.curve_color.setEnabled(unlocked and has_image)
        self.set_control_enabled(self.palette_combo, unlocked and has_image)
        for control, field in (("tolerance", "tolerance"), ("continuity", "continuity"),
                               ("smoothing", "smoothing"), ("stride", "stride"),
                               ("minimum_saturation", "minimum_saturation"),
                               ("max_gap", "max_gap_columns")):
            self.set_control_value(getattr(self, control), getattr(ds.settings, field))
            self.set_control_enabled(getattr(self, control), unlocked)

    def _coordinate_mode_changed(self, *_args):
        """Refresh only the coordinate presentation for View Data."""
        self._refresh_grid()

    def _refresh_grid(self):
        ds = self.engine.active_dataset
        rows = []
        index = 1
        calibrated = self.engine.calibration_ready()
        pixels = self.control_value(self.coordinate_mode) == "Image pixels" or not calibrated
        self.set_control_visible(self.data_coordinate_info, not calibrated)
        for i, (px, py) in enumerate(ds.extracted_pixels):
            x, y = (px, py) if pixels else (ds.extracted_data[i] if i < len(ds.extracted_data) else (None, None))
            rows.append(QtGridRow("auto:{}".format(i), (index, self._fmt(x) if pixels else self._fmt_axis(x, 'x'),
                                                        self._fmt(y) if pixels else self._fmt_axis(y, 'y'))))
            index += 1
        for i, p in enumerate(ds.manual_points):
            x, y = (p.px, p.py) if pixels else (p.x, p.y)
            rows.append(QtGridRow("manual:{}".format(i), (index, self._fmt(x) if pixels else self._fmt_axis(x, 'x'),
                                                          self._fmt(y) if pixels else self._fmt_axis(y, 'y'))))
            index += 1
        self.result_grid.setRows(rows)
        self._refresh_point_editor()

    def _refresh_anchor_values(self):
        cal = self.engine.calibration
        self._manual_bounds_axes.difference_update(self.engine.auto_tick_verified_axes)
        self._manual_bounds_axes.intersection_update(
            axis for axis in ('x', 'y')
            if all(getattr(cal, axis + suffix) is not None for suffix in ('1', '2')))
        pending = {axis for axis in ('x', 'y')
                   if axis not in self.engine.auto_tick_verified_axes
                   and not getattr(cal, 'points_' + axis)
                   and all(getattr(cal, axis + suffix) is not None for suffix in ('1', '2'))}
        newly_pending = pending - self._manual_bounds_axes
        self._manual_bounds_axes.update(pending)
        self._control_wrappers[self.snap_to_axes].setChecked(cal.snap_to_axes)
        self.set_control_value(self.scale_x, cal.scale_x.value)
        self.set_control_value(self.scale_y, cal.scale_y.value)
        for key in ("x1", "x2", "y1", "y2"):
            anchor = getattr(cal, key)
            editor = self.anchor_value[key]
            self.set_control_enabled(editor, anchor is not None)
            if key[0] in newly_pending:
                self.set_control_value(editor, '')
            if key[0] not in self._manual_bounds_axes:
                verified = (cal.box_rect is None or key[0] in self.engine.auto_tick_verified_axes
                            or bool(getattr(cal, 'points_' + key[0])))
                self.set_control_value(editor, self._fmt_axis(anchor.value, key[0])
                                       if anchor is not None and verified else "")
        self._refresh_calibration_points()
        self.set_control_value(self.roi_info, "Area: {}".format(self.engine.plot_rect or "full image / calibrated bounds"))

    @staticmethod
    def _fmt(value):
        if value is None:
            return ""
        try:
            return "{:.10g}".format(float(value))
        except Exception:
            return str(value)

    def _fmt_axis(self, value, axis_or_scale):
        if isinstance(axis_or_scale, AxisScale):
            scale = axis_or_scale
        else:
            scale = getattr(self.engine.calibration, "scale_" + str(axis_or_scale).lower())
        return format_axis_value(value, scale)

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
        actions = [{"label": "Unlock" if target.locked else "Lock", "action": action}]
        self.dataset_menu.setActions(actions)
        self.dataset_menu.popupGlobal(context=target)

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
        self._set_status("Found {} colors.".format(len(self._palette))
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
            values = []
            for key in ("x1", "x2", "y1", "y2"):
                scale = getattr(self.engine.calibration, "scale_" + key[0])
                values.append(parse_axis_value_input(self.control_value(self.anchor_value[key]), scale))
            self.engine.calibrate_plot_rect(*values)
            self._set_status("Axes calibrated.")
        except ValueError as exc:
            self._set_status(str(exc))

    def _undo(self):
        label = self.engine._undo_stack[-1][0] if self.engine.can_undo else ''
        if self.engine.can_undo:
            self._cancel_history_jobs()
        if self.engine.undo():
            self._cancel_pick()
            self._set_status('Undo: {}.'.format(label))

    def _refresh_history_commands(self):
        for key, command in getattr(self, "_history_actions", {}).items():
            if not command._deleted:
                command.setEnabled(self.engine.can_undo if key == "undo" else self.engine.can_redo)

    def _refresh_history_buttons(self, key, enabled):
        for button in (key, 'data_' + key):
            self.ribbon.set_button_enabled(button, enabled)

    def _trigger_history_command(self, key):
        if not self.winfo_exists():
            return False
        self._refresh_history_commands()
        return self._history_actions[key].trigger()

    def _redo(self):
        label = self.engine._redo_stack[-1][0] if self.engine.can_redo else ''
        if self.engine.can_redo:
            self._cancel_history_jobs()
        if self.engine.redo():
            self._cancel_pick()
            self._set_status('Redo: {}.'.format(label))

    def _cancel_history_jobs(self):
        # Undo must not leave a running OCR/extraction job able to commit later.
        for key, runner in (('ticks', self._tick_calibration_runner), ('extract', self._smart_runner)):
            if runner.busy:
                runner.cancel()
                self._finish_progress(key, False)
        self._region_alignment_preview = None
        self._refresh_dataset_controls()

    def _extract_curve(self):
        if not self.engine.image:
            return self._set_status("Open an image first.")
        self._show_tool("extract")
        if self.engine.active_dataset.curve_rgb is None:
            return self._set_status('Pick Color before extracting points.')
        self._start_extraction(auto_detect=False)

    def _extraction_status(self, ok, dataset_index=None):
        if not ok:
            return self._set_status("No curve points found.", details='Check the sampled color and extraction tolerance in Settings.')
        ds = self.engine.active_dataset if dataset_index is None else self.engine.datasets[dataset_index]
        if not self.engine.calibration_ready():
            self._set_status("Extracted {} points; axes not calibrated.".format(len(ds.extracted_pixels)))
        else:
            self._set_status("Extracted {} points.".format(len(ds.extracted_data)))

    def _smart_detect(self):
        self._start_extraction(auto_detect=True)

    def _start_extraction(self, *, auto_detect):
        if not self.engine.image:
            return self._set_status("Open an image first.")
        if self.engine.active_dataset.locked:
            return self._set_status("Unlock this dataset before extracting.")
        if not auto_detect and self.engine.active_dataset.curve_rgb is None:
            return self._set_status('Pick Color before extracting points.')
        if self._smart_runner.busy:
            return
        settings = self._settings()
        dataset_index = self.engine.active_dataset_index
        self.set_control_enabled(self.smart_button, False)
        self.set_control_enabled(self.extract_button, False)
        self.ribbon.set_button_enabled('extract', False)
        self._set_status("Extracting points...")
        self._begin_progress('extract', 'Extracting curve in the background...')
        try:
            started = self._smart_runner.submit(settings, dataset_index, self._smart_finished, auto_detect=auto_detect)
        except Exception as exc:
            started = False
            self._set_status('Extraction could not start: {}'.format(exc))
        if not started:
            self._finish_progress('extract', False)
            self._refresh_dataset_controls()
        self._refresh_workflow()

    def _smart_finished(self, result, settings, dataset_index, error):
        if not self.winfo_exists():
            return
        self._finish_progress('extract', not error and result is not None and not result.error)
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
        if enabled and (self.engine.active_dataset.locked or self.engine.image is None):
            enabled = False
        self._edit_enabled = enabled
        self.ribbon.set_button_checked("edit", enabled)
        if not enabled:
            self._reset_point_gesture()
            self._drag_target = None
            self._drag_preview = None
            self._hover_point = None
        self._refresh_point_actions()
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
            self._show_tool("extract")
            self._set_edit_enabled(True)
            self._set_status("Edit enabled.", quiet=True)
        else:
            self._set_edit_enabled(False)
            self._set_status("Edit disabled.", quiet=True)
        self._redraw()

    def _toggle_edit_mode(self):
        self._edit_mode_toggled(not self._edit_enabled)

    # ---------- point editing ----------
    def _reset_point_gesture(self):
        self._point_press = self._rubberband_end = None
        self._rubberband_active = False
        self._rubberband_base = set()

    def _select_canvas_points(self, keys):
        """Update selection without focusing the hidden Data-page table."""
        self.result_grid.selected = set(keys)
        current = next(iter(keys)) if len(keys) == 1 else None
        self.result_grid.current = self.result_grid.anchor = current
        self._selected_point = self._key_point(current)
        self.data_worksheet.reset_selection()
        if current is not None:
            row = self._point_keys().index(self._selected_point)
            self.data_worksheet.select_range((row, 0), (row, 1), focus=False)
        self._focus_canvas_keyboard()
        self._refresh_point_editor()
        self._redraw()

    def _finish_point_gesture(self, point):
        start, active, base = self._point_press, self._rubberband_active, self._rubberband_base
        if start is None:
            return
        scale = max(.001, self._fit_scale * self._zoom)
        active = active or max(abs(point[i] - start[i]) for i in (0, 1)) * scale >= 4
        self._reset_point_gesture()
        if not self._edit_enabled or self.engine.active_dataset.locked:
            return self._redraw()
        if active:
            left, right = sorted((start[0], point[0]))
            top, bottom = sorted((start[1], point[1]))
            keys = set(base)
            ds = self.engine.active_dataset
            if ds.visible:
                for source, points in (("auto", ds.extracted_pixels),
                                       ("manual", [(p.px, p.py) for p in ds.manual_points])):
                    if self._marker_visible(source):
                        keys.update("{}:{}".format(source, index) for index, (x, y) in enumerate(points)
                                    if left <= x <= right and top <= y <= bottom)
            self._select_canvas_points(keys)
            self._set_status("{} points selected.".format(len(keys)), quiet=True)
        else:
            try:
                self.engine.add_manual_point(*start)
                index = len(self.engine.active_dataset.manual_points) - 1
                self._refresh_grid()
                self._select_canvas_points({"manual:{}".format(index)})
                self._set_status("Point added.", quiet=True)
            except ValueError as exc:
                self._set_status(str(exc))

    def _clear_point_selection(self):
        self._selected_point = None
        worksheet = getattr(self, 'data_worksheet', None)
        if worksheet is not None:
            worksheet.reset_selection()
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
        if self.data_worksheet.isDragging():
            return
        if self._selected_point is not None and self._active_tool == 'data':
            self.result_grid.setFocus()
        if self._selected_point is not None and self._active_tool != "data":
            self._show_tool("extract")
        self._refresh_point_editor()
        self._redraw()

    def _data_selection_changed(self, *_args):
        if not self.data_worksheet.isDragging():
            self._refresh_point_editor()

    def _data_selection_finished(self, *_args):
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
        if self._pick_mode is not None or self._calibration_draft is not None:
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
        # Navigation selects exactly one XY row, even if a previous table
        # operation left a multi-cell/multi-row range highlighted.
        row = next(index for index, (row_key, _values) in enumerate(self.result_grid.rows) if row_key == text_key)
        self.data_worksheet.select_range((row, 0), (row, 1), focus=False)
        if self._selected_point != key:
            self._point_selected(text_key)
        return True

    def _refresh_point_editor(self):
        if not hasattr(self, "point_info"):
            return
        if self.data_worksheet.isDragging():
            return
        self._schedule_data_layout()
        self._refresh_point_actions()
        selected = self._selected_point
        keys = self._point_keys()
        show = bool(keys) and (self._active_tool == "extract" or (
            self._active_tool == "data" and selected is not None and len(self.result_grid.selectedKeys()) <= 1))
        self.set_control_visible(self.point_editor_container, show)
        if selected is None:
            self.set_control_visible(self.point_fields, False)
            count = len(self.result_grid.selectedKeys())
            self.set_control_value(self.point_info, "{} points selected".format(count) if count > 1 else "Select a point")
            self.set_control_enabled(self.previous_point_button, bool(keys))
            self.set_control_enabled(self.next_point_button, bool(keys))
            self._control_wrappers[self.point_x].setText("")
            self._control_wrappers[self.point_y].setText("")
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
            formatted = self._fmt(value) if in_pixels else self._fmt_axis(value, label)
            self._control_wrappers[field].setText(formatted)
            if self.control_value(field) != formatted:
                self.set_control_value(field, formatted)
            self.set_control_enabled(field, editable)
        position = keys.index(selected)
        self.set_control_value(self.point_info, "{} {}/{} | {}".format(
            "Auto" if selected[0] == "auto" else "Manual", position + 1, len(keys),
            "px" if in_pixels else "X/Y"))
        self.set_control_enabled(self.previous_point_button, position > 0)
        self.set_control_enabled(self.next_point_button, position < len(keys) - 1)

    def _apply_point(self):
        if self._selected_point is None:
            return self._set_status("Select a point first.")
        try:
            in_pixels = self.control_value(self.coordinate_mode) == "Image pixels" or not self.engine.calibration_ready()
            if in_pixels:
                x, y = float(self.control_value(self.point_x)), float(self.control_value(self.point_y))
            else:
                x = parse_axis_value_input(self.control_value(self.point_x), self.engine.calibration.scale_x)
                y = parse_axis_value_input(self.control_value(self.point_y), self.engine.calibration.scale_y)
            if in_pixels:
                self.engine.move_point(*self._selected_point, x, y)
            else:
                self.engine.set_point_values(*self._selected_point, x, y)
            self._set_status("Point updated.", quiet=True)
        except (ValueError, IndexError) as exc:
            self._set_status(str(exc))

    def _delete_selected_canvas_points(self):
        if not self._edit_enabled:
            return self._set_status("Select points in Edit mode first.")
        self._delete_points()

    def _delete_points(self):
        points = [self._key_point(key) for key in self.result_grid.selectedKeys()]
        if not points and self._selected_point is not None:
            points = [self._selected_point]
        if not points:
            return self._set_status("Select points first.")
        try:
            self._reset_point_gesture()
            self._drag_target = self._drag_preview = None
            self.engine.remove_points(points)
            self._clear_point_selection()
            self._refresh_point_actions()
            self._set_status("Deleted {} points.".format(len(points)))
        except (ValueError, IndexError) as exc:
            self._set_status(str(exc))

    def _clear_points(self):
        try:
            self.engine.clear_points()
            self._clear_point_selection()
            self._set_status("Dataset cleared.")
        except ValueError as exc:
            self._set_status(str(exc))

    def _request_clean(self, mode):
        if mode not in ('project', 'markers'):
            raise ValueError('Unknown clean operation.')
        if getattr(self, '_closed', False):
            return
        if getattr(self, '_clean_confirmation_pending', False):
            dialog = getattr(self, '_clean_confirmation_dialog', None)
            if dialog is not None:
                dialog.lift()
            return
        self._clean_confirmation_pending = True
        self._clean_confirmation_dialog = None
        title = 'New Project' if mode == 'project' else 'Clear All Markers'
        message = ('Remove the image, all datasets, axis calibration and plot area from this project?\n\n'
                   'Unsaved changes will be lost. This cannot be undone. Saved files are not deleted.'
                   if mode == 'project' else
                   'Remove all data points (including locked datasets), axis calibration and plot area?\n\n'
                   'The image and dataset settings will be kept. Ctrl+Z restores the markers.')
        def finished(confirmed):
            self._clean_confirmation_pending = False
            self._clean_confirmation_dialog = None
            if not confirmed or getattr(self, '_closed', False):
                return
            # Invalidate pending file loads as well as OCR/extraction results.
            self._image_load_generation += 1
            self._project_load_generation += 1
            future = self._image_load_future
            if future is not None:
                future.cancel()
            self._cancel_pick()
            self._display_axis_ticks = None
            self._selected_calibration_point = None
            if mode == 'project':
                self._project_path = None
                self.engine.clean_project()
                if self._texture_tag is not None:
                    self._texture_tag.delete()
                    self._texture_tag = None
            else:
                self.engine.clean_markers()
            self._refresh_all()
            self._set_status('Project cleared.' if mode == 'project' else
                             'Markers cleared.')
        try:
            options = dict(primary_text=title, secondary_text='Cancel', intent='warning', parent=self)
            confirm = getattr(self.view, 'confirm_action_async', None)
            if callable(confirm):
                dialog = confirm(title, message, finished, **options)
            else:
                from ...dialogs.blocking_form import BlockingDialog
                dialog = BlockingDialog(self.view, title, message, 'confirm', on_result=finished, **options)
                dialog.lift()
            if self._clean_confirmation_pending:
                self._clean_confirmation_dialog = dialog
        except Exception:
            self._clean_confirmation_pending = False
            self._clean_confirmation_dialog = None
            raise

    def _open_sample_count_dialog(self, mode):
        return self._open_samples_dialog(mode)

    def _open_samples_dialog(self, mode="count"):
        if self._smart_runner.busy:
            return self._set_status("Wait for extraction to finish before changing samples.")
        ds = self.engine.active_dataset
        if ds.locked:
            return self._set_status("Unlock this dataset before changing its samples.")
        current = len(ds.extracted_pixels) + len(ds.manual_points)
        if current < 2:
            return self._set_status("Add at least 2 points before changing samples.")

        existing = getattr(self, "_sample_count_dialog", None)
        if existing is not None and existing.winfo_exists():
            existing.lift()
            return existing

        revision = self.engine.revision

        def completed(settings):
            self._sample_count_dialog = None
            if settings is None or not self.winfo_exists():
                return
            if self.engine.active_dataset is not ds or self.engine.revision != revision:
                return self._set_status("Dataset changed. Reopen Resample to use the latest points.")
            if settings['mode'] == 'simplify':
                error = settings['max_error']
                self._control_wrappers[self.reduction_error].setValue(error)
                self._apply_sample_simplification(error)
            else:
                target = settings['target']
                self._apply_sample_count('increase' if target >= current else 'reduce', current, target)

        dialog = self.own_dialog(SamplesDialog(
            self.view, current, mode=mode, max_error=float(self.control_value(self.reduction_error)),
            on_result=completed, parent=self))
        self._sample_count_dialog = dialog
        dialog.lift()
        return dialog

    def _apply_sample_count(self, mode, before, target):
        try:
            if mode == "increase":
                added = self.engine.increase_samples(target_count=target)
                if added:
                    self._cancel_pick()
                    self._clear_point_selection()
                    self._refresh_point_editor()
                    self._set_status(
                         "Samples increased: {} -> {}.".format(
                            before, before + added))
                else:
                    self._set_status("Sample count stayed at {}.".format(before))
                return

            removed = self.engine.reduce_sample_count(target_count=target)
            after = before - removed
            if removed:
                self._cancel_pick()
                self._clear_point_selection()
                self._refresh_point_editor()
                if after == target:
                    self._set_status(
                        "Samples reduced: {} -> {}.".format(
                            before, after))
                else:
                    self._set_status(
                        "Samples reduced: {} -> {} (target {}).".format(
                            before, after, target))
            else:
                self._set_status("Sample count stayed at {}.".format(before))
        except ValueError as exc:
            self._set_status(str(exc))

    def _increase_samples(self):
        return self._open_sample_count_dialog("increase")

    def _reduce_samples(self):
        return self._open_sample_count_dialog("reduce")

    def _simplify_samples(self):
        return self._open_samples_dialog("simplify")

    def _apply_sample_simplification(self, max_error):
        if self._smart_runner.busy:
            return self._set_status("Wait for extraction to finish before simplifying samples.")
        ds = self.engine.active_dataset
        before = len(ds.extracted_pixels) + len(ds.manual_points)
        try:
            removed = self.engine.reduce_samples(max_error)
            if removed:
                self._cancel_pick()
                self._clear_point_selection()
                self._refresh_point_editor()
                self._set_status("Samples simplified: {} -> {}.".format(before, before - removed))
            else:
                self._set_status("No redundant samples found at this error tolerance.")
        except ValueError as exc:
            self._set_status(str(exc))

    def _smooth_curve(self):
        if self._smart_runner.busy:
            return self._set_status("Wait for extraction to finish before smoothing the curve.")
        ds = self.engine.active_dataset
        count = len(ds.extracted_pixels) + len(ds.manual_points)
        if count < 3:
            return self._set_status("Add at least 3 points before smoothing the curve.")
        try:
            moved = self.engine.smooth_curve()
            if moved:
                self._cancel_pick()
                self._clear_point_selection()
                self._refresh_point_editor()
                self._set_status(
                    "Curve smoothed ({} points).".format(count))
            else:
                self._set_status("Curve points are already evenly distributed along the current path.")
        except ValueError as exc:
            self._set_status(str(exc))

    # ---------- canvas ----------
    def _install_mouse_handlers(self):
        binding = QGlobalInputBinding(backend=_renderer_backend(), parent=self)
        native_delete = QGlobalInputBinding.nativeKeyFor(Qt.Key_Delete, _renderer_backend())
        if native_delete is not None:
            # Standalone workers use QDialog's legacy keyboard dispatcher when
            # no QApplication exists; give that route the same document command.
            self.shortcuts[(native_delete, False)] = lambda: self._edit_key(None, key=Qt.Key_Delete)
        binding.onMouseClick(Qt.LeftButton, self._mouse_left)
        binding.onMouseRelease(Qt.LeftButton, self._mouse_left_up)
        binding.onMouseClick(Qt.MiddleButton, self._mouse_middle_down)
        binding.onMouseRelease(Qt.MiddleButton, self._mouse_middle_up)
        binding.onMouseMove(self._mouse_move)
        binding.onMouseWheel(self._mouse_wheel)
        for key in (Qt.Key_Z, Qt.Key_Y, Qt.Key_Delete,
                    Qt.Key_A, Qt.Key_S, Qt.Key_N, Qt.Key_P,
                    Qt.Key_Left, Qt.Key_Right, Qt.Key_Up, Qt.Key_Down):
            binding.onKeyPress(key, self._edit_key, user_data=key)
        self._input_binding = binding.activate()
        self._handler_registry = None  # compatibility: no native registry escapes DearUIQt

    def _handle_key_event(self, event):
        key = QGlobalInputBinding.qtKeyForNative(event.key(), _renderer_backend())
        if key in (Qt.Key_Delete, Qt.Key_Escape) and self._edit_key(
                None, key=key, modifiers=event.modifiers()):
            return True
        return super()._handle_key_event(event)

    def _native_delete_snapshot(self):
        """Read a physical Delete edge with strict native window ownership."""
        if os.name != 'nt':
            return None
        try:
            import ctypes
            user32 = ctypes.windll.user32
            down = bool(user32.GetAsyncKeyState(0x2E) & 0x8000)
            if not down:
                return False, Qt.NoModifier, False
            modifiers = Qt.NoModifier
            for key, flag in ((0x10, Qt.ShiftModifier), (0x11, Qt.ControlModifier),
                              (0x12, Qt.AltModifier), (0x5B, Qt.MetaModifier), (0x5C, Qt.MetaModifier)):
                if user32.GetAsyncKeyState(key) & 0x8000:
                    modifiers |= flag
            native = getattr(self, '_native_window_backend', None)
            resolver = getattr(self.view, '_find_main_viewport_hwnd', None)
            hwnd = int(native.winId(self.tag) or 0) if native is not None else 0
            if not hwnd:
                hwnd = int(resolver() or 0) if callable(resolver) else 0
            from ...ui.native.dialog_focus import foreground_hwnd, window_state
            owned = bool(hwnd and foreground_hwnd() == hwnd and all(window_state(hwnd)))
            return down, modifiers, owned
        except (AttributeError, OSError, TypeError, ValueError):
            return None

    def _poll_delete_key(self):
        if getattr(self, '_closed', False) or getattr(self, '_visible_state', True) is False:
            return
        state = self._native_delete_snapshot()
        native_press = False
        if state is not None:
            down, modifiers, owned = state
            previous = getattr(self, '_delete_key_down', False)
            self._delete_key_down = down
            if not down:
                self._delete_key_consumed = False
            if not owned:
                return  # Never turn another application's Delete into a document edit.
            native_press = down and not previous
        else:
            modifiers = QKeyboard.modifiers(backend=_renderer_backend())
        calibration = (self._active_tool == 'axes' and
                       getattr(self, '_selected_calibration_point', None) is not None)
        data = ((self._edit_enabled or self._active_tool == 'data') and
                (self._selected_point is not None or self.result_grid.selectedKeys()))
        pressed = native_press if state is not None else QKeyboard.isKeyPressed(Qt.Key_Delete, backend=_renderer_backend())
        if (calibration or data) and pressed:
            self._edit_key(None, key=Qt.Key_Delete, modifiers=modifiers)

    def _edit_key(self, _sender, _app_data=None, key=None, *, modifiers=None):
        if key is None:
            key = QGlobalInputBinding.qtKeyForNative(_app_data, _renderer_backend())
        if modifiers is None:
            modifiers = QKeyboard.modifiers(backend=_renderer_backend())
        if modifiers & (Qt.AltModifier | Qt.MetaModifier):
            return
        ctrl = bool(modifiers & Qt.ControlModifier)
        shift = bool(modifiers & Qt.ShiftModifier)
        if ctrl and key == Qt.Key_S:
            if self._accepts_edit_shortcut(allow_editor=True):
                (self._choose_save_project_as if shift else self._choose_save_project)()
                return True
            return
        if not self._accepts_edit_shortcut():
            return
        if not ctrl and key == Qt.Key_Delete:
            if getattr(self, '_pick_mode', None) is not None:
                return
            state = self._native_delete_snapshot()
            if state is not None and state[0]:
                if not state[2]:
                    return
                if getattr(self, '_delete_key_consumed', False):
                    return True
            if self._active_tool == 'axes':
                if getattr(self, '_selected_calibration_point', None) is None:
                    return
                self._remove_calibration_point()
                self._redraw()
            elif ((self._edit_enabled and (self._selected_point is not None or self.result_grid.selectedKeys()))
                  or (self._active_tool == 'data' and self.result_grid.hasFocus())):
                self._delete_points()
            else:
                return
            if state is not None and state[0]:
                self._delete_key_consumed = True
            return True
        worksheet = getattr(self, 'data_worksheet', None)
        if (worksheet is not None and worksheet.owns_keyboard()
                and key in (Qt.Key_Left, Qt.Key_Right, Qt.Key_Up, Qt.Key_Down)):
            return  # Cell navigation must not also nudge the selected canvas point.
        if not ctrl and key in (Qt.Key_N, Qt.Key_P) and self._active_tool in ("extract", "data"):
            self._navigate_point(1 if key == Qt.Key_N else -1)
            return
        if ctrl and key == Qt.Key_Z:
            self._trigger_history_command("redo" if shift else "undo")
            return True
        elif ctrl and not shift and key == Qt.Key_Y:
            self._trigger_history_command("redo")
            return True
        elif not ctrl and key == Qt.Key_Escape and self._edit_enabled and (
                self._selected_point is not None or self.result_grid.selectedKeys()):
            self._clear_point_selection()
            self._refresh_point_editor()
            self._redraw()
            self._set_status("Selection cleared.", quiet=True)
            return True
        elif not ctrl and self._mouse_in_canvas():
            modes = {Qt.Key_A: "manual"}
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

    def _accepts_edit_shortcut(self, *, allow_editor=False):
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
        application = QApplication.instance()
        if application is not None:
            modal = application.activeModalWidget()
            if modal is not None and modal is not self:
                return False
            if application.activePopupWidget() is not None:
                return False
        if getattr(self, '_close_confirmation_pending', False):
            return False
        selector = getattr(getattr(self, "_file_dialog", None), "dialog", None)
        if selector is not None and selector.winfo_exists():
            return False
        settings = getattr(self, "_settings_dialog", None)
        if settings is not None and settings.isVisible():
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
        # A QCanvas is backed by a renderer drawlist. Some backends cannot give
        # that native item keyboard focus, leaving the previously focused
        # InputText/table active even after a point was clicked. DearUIQt's
        # logical focus object is authoritative for that canvas interaction.
        # Resolve it *before* the Win32 foreground check: process-hosted tools
        # can expose a renderer/client HWND that differs from GetForegroundWindow
        # even though this exact canvas owns the current keyboard interaction.
        canvas_keyboard_focus = False
        try:
            application = QApplication.instance()
            canvas_keyboard_focus = bool(
                application is not None
                and application.focusObject() is getattr(self, "_canvas_widget", None)
            )
        except Exception:
            pass
        resolver = getattr(self.view, "_find_main_viewport_hwnd", None)
        native = getattr(self, "_native_window_backend", None)
        hwnd = int(native.winId(self.tag) or 0) if native is not None else 0
        if not hwnd:
            hwnd = resolver() if callable(resolver) else 0
        if hwnd:
            from ...ui.native.dialog_focus import foreground_hwnd, window_state
            if not all(window_state(hwnd)):
                return False
            foreground = foreground_hwnd()
            # Do not reject a canvas command solely because the platform host
            # reports a different top-level/client HWND. The renderer only
            # generates this key event while its viewport is receiving input,
            # and logical canvas focus is set by the actual point click.
            if foreground and foreground != hwnd and not canvas_keyboard_focus:
                return False
        if not allow_editor and not canvas_keyboard_focus:
            # ImGui nav focus can report a containing child window even while
            # InputText owns the caret. Do not route its Delete into the data.
            for item in getattr(self, "enter_editors", ()):
                if QRetainedItem(item, backend=_renderer_backend()).nativeState().get("active", False):
                    return False
        focused_item = QRetainedItem.focusedItem(backend=_renderer_backend())
        if focused_item is not None and not canvas_keyboard_focus:
            try:
                item_type = focused_item.itemType()
                if not allow_editor and any(kind in item_type for kind in ("Input", "Combo", "Slider", "Drag", "Color")):
                    return False
                # Embedded/test hosts can contain sibling tool windows. Their
                # buttons/tables must not route document commands to this one.
                visited = set()
                def native_id(item):
                    if isinstance(item, str):
                        value = _renderer_backend().get_alias_id(item)
                        return value if isinstance(value, int) and value else item
                    return item
                owner = native_id(self.tag)
                item = native_id(focused_item.tag)
                while item and item != owner and item not in visited:
                    visited.add(item)
                    item = native_id(QRetainedItem(item, backend=_renderer_backend()).parentItem())
                if item != owner:
                    return False
            except Exception:
                # A stale focus ID during deferred widget deletion is not
                # permission to edit the document behind it.
                return False
        return True

    def _focus_canvas_keyboard(self):
        """Give the paint canvas logical keyboard focus even if its drawlist cannot own native focus.

        Dear PyGui drawlists are not normal focusable controls on every backend.
        A point click can therefore leave an InputText/table reported as the
        renderer-focused item.  Document shortcuts such as Delete must follow
        the canvas interaction, not that stale native focus.
        """
        canvas = getattr(self, "_canvas_widget", None)
        if canvas is None:
            return False
        native_focused = False
        try:
            native_focused = bool(canvas.setFocus())
        except Exception:
            pass
        try:
            application = QApplication.instance()
            if application is not None:
                application.setFocusObject(canvas)
                return True
        except Exception:
            pass
        return native_focused

    def _mouse_in_canvas(self):
        return (self._canvas_widget.exists() and self._canvas_widget.underMouse()
                and not self._canvas_view_tools_under_mouse())

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
        if mode == 'area':
            self._show_tool('axes')
            self._set_calibration_method('smart')
        elif mode in ('calibration_x', 'calibration_y', 'x1', 'x2', 'y1', 'y2'):
            self._set_calibration_method('manual')
        if mode in ("curve", "manual", "edit", "delete") and self.engine.active_dataset.locked:
            return self._set_status("Unlock this dataset before editing its curve.")
        if mode == 'curve':
            self._show_tool('extract')
        if mode in ("manual", "edit", "delete"):
            self._edit_mode_toggled(True)
            return
        self._region_first_corner = self._region_press = None
        self._drag_start = self._drag_preview = None
        self._region_alignment_preview = None
        if self._edit_enabled:
            self._set_edit_enabled(False)
        self._calibration_sequence = []
        if mode in ("manual", "edit", "delete"):
            self._show_tool("extract")
        elif mode == "curve":
            self._show_tool("extract")
        elif mode in ("area", "x1", "x2", "y1", "y2", "calibration_x", "calibration_y"):
            self._show_tool("axes")
        self._pick_mode = mode
        help_text = {"area": "Select Plot: drag a rectangle or click two opposite corners around the chart axes. X1/Y1 use bottom-left, X2 bottom-right and Y2 top-left.",
                     "edit": "Drag a marker to move it.",
                     "curve": "Click directly on the curve stroke to sample its color.",
                     "manual": "Click to add points. Use the magnifier for precision.",
                     "calibration_x": "Click the known X tick to add or reposition a calibration point.",
                     "calibration_y": "Click the known Y tick to add or reposition a calibration point."}
        self._set_status({'area': 'Select chart region.', 'curve': 'Pick curve color. Esc cancels.',
                          'calibration_x': 'Pick X tick.', 'calibration_y': 'Pick Y tick.'}.get(
                              mode, 'Pick {} tick.'.format(mode.upper())),
                         details=help_text.get(mode, "Click the known {} tick on the image.".format(mode.upper())) + " Esc cancels.")
        if mode in ("calibration_x", "calibration_y"):
            self.set_control_visible(self.calibration_hint, True)
            self.set_control_value(self.calibration_hint, help_text[mode] + " Esc cancels.")
        elif mode in ("x1", "x2", "y1", "y2"):
            self.set_control_visible(self.calibration_hint, True)
            self.set_control_value(
                self.calibration_hint,
                "Click {} on a known axis tick. Esc cancels.".format(mode.upper()))
        elif mode == "area":
            self.set_control_visible(self.calibration_hint, True)
            self.set_control_value(
                self.calibration_hint,
                "Select Plot: drag a rectangle or click two opposite corners. Esc cancels.")
        self._paint_pointer()

    def _cancel_pick(self):
        had_draft = getattr(self, '_calibration_draft', None) is not None
        self._calibration_draft = None
        if had_draft:
            self._selected_calibration_point = None
            self._refresh_calibration_points()
        self._reset_point_gesture()
        self._pick_mode = None
        self._calibration_pick = None
        self._calibration_sequence = []
        if hasattr(self, "calibration_hint"):
            self.set_control_value(self.calibration_hint, "")
            self.set_control_visible(self.calibration_hint, False)
        self._drag_start = self._drag_preview = self._drag_target = None
        self._region_first_corner = self._region_press = None
        self._anchor_drag_target = self._anchor_drag_preview = self._hover_anchor = None
        if had_draft:
            self._redraw()
        else:
            self._paint_pointer()
        self._set_status("Ready.")

    def _calibration_markers(self):
        boxed = self.engine.calibration.box_rect is not None
        for axis in ("x", "y"):
            points = getattr(self.engine.calibration, "points_" + axis)
            if boxed:
                corners = [getattr(self.engine.calibration, axis + suffix) for suffix in ('1', '2')]
                for suffix, point in zip(('1', '2'), corners):
                    if point is not None:
                        yield axis + suffix, point
                for index, point in enumerate(points):
                    if any(c is not None and abs(c.px - point.px) < 1e-9 and abs(c.py - point.py) < 1e-9
                           and abs(c.value - point.value) < 1e-9 for c in corners):
                        continue  # The corner already represents this exact measured tick.
                    yield '{}t{}'.format(axis, index + 1), point
                continue
            if points:
                for index, point in enumerate(points):
                    yield "{}{}".format(axis, index + 1), point
            else:
                for key in (axis + "1", axis + "2"):
                    point = getattr(self.engine.calibration, key)
                    if point is not None:
                        yield key, point
        draft = getattr(self, '_calibration_draft', None)
        if draft is not None:
            yield draft['axis'] + 'draft', AxisAnchor(draft['px'], draft['py'], 0)

    def _calibration_marker(self, key):
        if key.endswith('draft'):
            draft = self._calibration_draft
            return None if draft is None else AxisAnchor(draft['px'], draft['py'], 0)
        if self.engine.calibration.box_rect is not None and 't' not in key:
            return getattr(self.engine.calibration, key, None)
        points = getattr(self.engine.calibration, "points_" + key[0])
        if points:
            index = int(key[2:] if key[1:2] == 't' else key[1:]) - 1
            return points[index] if 0 <= index < len(points) else None
        return getattr(self.engine.calibration, key, None)

    def _calibration_point_index(self, key):
        if key.endswith('draft'):
            return 'draft'
        points = getattr(self.engine.calibration, 'points_' + key[0])
        if key[1:2] == 't':
            return int(key[2:]) - 1
        if self.engine.calibration.box_rect is None:
            return int(key[1:]) - 1 if points else None
        corner = getattr(self.engine.calibration, key, None)
        return next((i for i, point in enumerate(points) if corner is not None and
                     abs(point.px - corner.px) < 1e-9 and abs(point.py - corner.py) < 1e-9 and
                     abs(point.value - corner.value) < 1e-9), None)

    def _calibration_marker_label_key(self, key):
        """Return the user-facing marker name shown next to a calibration handle.

        For boxed Y-axis calibration, measured Y ticks should be numbered from
        the origin upward so the first interior tick above ``Y1`` reads
        ``Yt2``.  Internally the stored point order can differ (for example
        top-to-bottom after auto-detect), so compute the displayed ordinal from
        the actual marker position instead of reusing the raw storage index.
        """
        if key.endswith('draft'):
            return key[0].upper() + ' new'
        if key.startswith('yt') and self.engine.calibration.box_rect is not None:
            point = self._calibration_marker(key)
            points = list(getattr(self.engine.calibration, 'points_y') or [])
            if point is not None and points:
                corners = [getattr(self.engine.calibration, suffix) for suffix in ('y1', 'y2')]
                interior = [candidate for candidate in points
                            if not any(c is not None and
                                       abs(c.px - candidate.px) < 1e-9 and
                                       abs(c.py - candidate.py) < 1e-9 and
                                       abs(c.value - candidate.value) < 1e-9
                                       for c in corners)]
                if interior:
                    ordered = sorted(interior, key=lambda candidate: (-(candidate.py), candidate.px, candidate.value))
                    for rank, candidate in enumerate(ordered, start=2):
                        if (abs(candidate.px - point.px) < 1e-9 and
                                abs(candidate.py - point.py) < 1e-9 and
                                abs(candidate.value - point.value) < 1e-9):
                            return f'Yt{rank}'
        return key[0].upper() + key[1:]

    def _nearest_anchor(self, px, py):
        """Return the nearest calibration anchor under the pointer in Calibration/Axes mode."""
        if self._active_tool != "axes" or self._pick_mode is not None:
            return None
        scale = max(.001, self._fit_scale * self._zoom)
        # Keep the target easy to grab on screen regardless of image zoom.
        hit_radius = 10.0 / scale
        best_key, best_distance = None, None
        preferred_axis = (self.control_value(self.calibration_axis).lower()
                          if hasattr(self, 'calibration_axis') else 'x')
        for key, anchor in self._calibration_markers():
            distance = (anchor.px - px) ** 2 + (anchor.py - py) ** 2
            if distance <= hit_radius ** 2 and (best_distance is None or distance < best_distance or
                    (distance == best_distance and key[0] == preferred_axis and best_key[0] != preferred_axis)):
                best_key, best_distance = key, distance
        return best_key

    def _anchor_display_pixel(self, key):
        """Return the pixel used to draw an anchor, including an in-progress drag preview."""
        if self._anchor_drag_target == key and self._anchor_drag_preview is not None:
            return self._anchor_drag_preview
        anchor = self._calibration_marker(key)
        return None if anchor is None else (anchor.px, anchor.py)

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
        self._focus_canvas_keyboard()
        mode = self._pick_mode
        if mode is None and self._active_tool == "axes":
            anchor_key = self._nearest_anchor(px, py)
            if anchor_key is not None:
                anchor = self._calibration_marker(anchor_key)
                self._anchor_drag_target = anchor_key
                self._anchor_drag_preview = (anchor.px, anchor.py)
                self._hover_anchor = anchor_key
                self._hover_point = None
                point_index = self._calibration_point_index(anchor_key)
                if point_index is not None:
                    self.set_control_value(self.calibration_axis, anchor_key[0].upper())
                    self._refresh_calibration_points()
                    self.calibration_grid.setCurrentKey(
                        "{}:{}".format(anchor_key[0], point_index), select=True, focus=False)
                self._set_status("Moving {} anchor.".format(anchor_key.upper()), quiet=True)
                self._redraw()
                return
        if mode in ("calibration_x", "calibration_y"):
            try:
                axis, index, value = self._calibration_pick
                if value is None:
                    self.set_control_value(self.calibration_point_value, '')
                    self._place_calibration_draft(axis, px, py)
                    self._pick_mode = self._calibration_pick = None
                    self.set_control_visible(self.calibration_hint, False)
                    self._set_status('Drag the new {} tick, then enter Value and click Set Value. Esc cancels.'.format(axis.upper()))
                    self._redraw()
                    return
                if index is None:
                    self.engine.add_calibration_point(axis, px, py, value)
                    index = len(self.engine.calibration_points(axis)) - 1
                else:
                    self.engine.update_calibration_point(axis, index, px=px, py=py)
                self._pick_mode = None
                self._calibration_pick = None
                self.set_control_visible(self.calibration_hint, False)
                self._refresh_calibration_points()
                self.calibration_grid.setCurrentKey("{}:{}".format(axis, index), select=True)
                self._set_status("{} tick added.".format(axis.upper()))
                self._redraw()
            except (ValueError, IndexError) as exc:
                self._set_status(str(exc))
        elif mode in ("x1", "x2", "y1", "y2"):
            try:
                self.engine.set_anchor(mode, px, py, self._anchor_pick_value(mode))
                self._pick_mode = None
                self._calibration_sequence = []
                self.set_control_visible(self.calibration_hint, False)
                self._set_status("{} anchor set.".format(mode.upper()))
            except ValueError as exc:
                self._set_status(str(exc))
        elif mode == "curve":
            try:
                rgb = self.engine.sample_curve_color(px, py)
                self._sample_pixel = None
                self._pick_mode = None
                self._set_status(
                    "Color picked: #{:02X}{:02X}{:02X}.".format(*rgb))
                self._redraw()
            except ValueError as exc:
                self._set_status(str(exc))
        elif mode == "area":
            self._region_press = (px, py)
            self._drag_start = self._region_first_corner or (px, py)
            self._drag_preview = (px, py)
            self._paint_pointer()
        elif mode in (None, "edit"):
            if not self._edit_enabled or self.engine.active_dataset.locked:
                return
            selected = self._nearest_point(px, py)
            if selected is None:
                self._point_press = self._rubberband_end = (px, py)
                self._rubberband_active = False
                modifiers = QKeyboard.modifiers(backend=_renderer_backend())
                self._rubberband_base = (set(self.result_grid.selectedKeys())
                                        if modifiers & (Qt.ControlModifier | Qt.ShiftModifier) else set())
            else:
                self._select_canvas_points({"{}:{}".format(*selected)})
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
        if (self._drag_start is None and self._drag_target is None and
                self._anchor_drag_target is None and self._point_press is None):
            return
        if self._pick_mode == 'area' and self._region_press is None:
            return  # Hover/duplicate release while waiting for the second click.
        point = self._canvas_to_image(QCursor.pos().toTuple())
        if point is None or self.engine.image is None:
            return self._cancel_pick()
        px = max(0, min(self.engine.image.width - 1, point[0]))
        py = max(0, min(self.engine.image.height - 1, point[1]))
        if self._pick_mode == 'area' and self._drag_start is not None:
            scale = max(.001, self._fit_scale * self._zoom)
            moved = max(abs(value - origin) for value, origin in zip((px, py), self._region_press)) * scale
            first_click = self._region_first_corner is None and moved < 4
            too_small = (abs(round(px) - round(self._drag_start[0])) < 2 or
                         abs(round(py) - round(self._drag_start[1])) < 2)
            if first_click or too_small:
                self._region_first_corner = self._drag_start
                self._region_press = None
                self._drag_preview = (px, py)
                message = ('First corner set. Click the opposite corner. Esc cancels.' if first_click else
                           'Choose an opposite corner to make a region at least 3 by 3 pixels. Esc cancels.')
                self._set_status('Pick opposite corner.' if first_click else 'Region too small.', details=message)
                if hasattr(self, 'calibration_hint'):
                    self.set_control_value(self.calibration_hint, message)
                self._paint_pointer()
                return
        if self._point_press is not None:
            return self._finish_point_gesture((px, py))
        try:
            if self._anchor_drag_target is not None:
                key = self._anchor_drag_target
                preview = self._anchor_drag_preview or (px, py)
                px = max(0, min(self.engine.image.width - 1, preview[0]))
                py = max(0, min(self.engine.image.height - 1, preview[1]))
                anchor = self._calibration_marker(key)
                if key.endswith('draft'):
                    self._place_calibration_draft(key[0], px, py)
                    self._set_status('New {} tick positioned. Enter Value and click Set Value.'.format(key[0].upper()))
                elif abs(px - anchor.px) > 1e-9 or abs(py - anchor.py) > 1e-9:
                    point_index = self._calibration_point_index(key)
                    if point_index is not None:
                        self.engine.update_calibration_point(key[0], point_index, px=px, py=py)
                    else:
                        self.engine.set_anchor(key, px, py, anchor.value)
                    self._set_status("{} anchor moved.".format(key.upper()), quiet=True)
                else:
                    self._set_status("{} anchor selected.".format(key.upper()), quiet=True)
            elif self._drag_start is not None:
                rect = (*self._drag_start, px, py)
                # Commit the Smart Region and corner anchors immediately. Numeric tick
                # OCR is intentionally background work so releasing the mouse
                # can never stall the renderer on a difficult/high-resolution
                # chart.
                self.engine.set_plot_rect_with_corner_anchors(rect, detect_ticks=False)
                self._display_axis_ticks = None
                self._pick_mode = None
                self._calibration_sequence = []
                self._show_tool("axes")
                if hasattr(self, "calibration_hint"):
                    self.set_control_visible(self.calibration_hint, False)
                self._start_tick_calibration(self.engine.plot_rect, merge_region_history=True)
            elif self._drag_target is not None:
                if self._drag_preview is not None:
                    px = max(0, min(self.engine.image.width - 1, self._drag_preview[0]))
                    py = max(0, min(self.engine.image.height - 1, self._drag_preview[1]))
                old_px, old_py = self.engine.point_pixels(*self._drag_target)
                if abs(px - old_px) > 1e-9 or abs(py - old_py) > 1e-9:
                    self.engine.move_point(*self._drag_target, px, py)
                    self._set_status("Point moved.", quiet=True)
                else:
                    self._set_status("Point selected.", quiet=True)
        except (ValueError, IndexError) as exc:
            self._set_status(str(exc))
        finally:
            self._drag_start = self._drag_preview = self._drag_target = None
            self._region_first_corner = self._region_press = None
            self._anchor_drag_target = self._anchor_drag_preview = None
            self._redraw()

    def _start_tick_calibration(self, rect, *, merge_region_history=False):
        if rect is None or self.engine.image is None:
            return
        self._manual_bounds_axes.clear()
        self._set_calibration_method('smart', cancel_pending=False)
        self._selected_calibration_point = None
        self.calibration_grid.current = self.calibration_grid.anchor = None
        self.calibration_grid.clearSelection()
        self._region_alignment_preview = None
        snap = self.engine.calibration.snap_to_axes
        self._begin_progress('ticks', 'Aligning region to horizontal and vertical axes...' if snap
                             else 'Reading tick labels in the selected rectangle...')
        try:
            region_revision = self.engine.revision if merge_region_history else None
            finished = self._tick_calibration_finished
            if region_revision is not None:
                finished = lambda detection, area, error: self._tick_calibration_finished(
                    detection, area, error, region_revision=region_revision)
            started = self._tick_calibration_runner.submit(
                rect, finished,
                on_progress=self._tick_calibration_progress,
                on_region=self._region_aligned, align_axes=snap)
        except Exception as exc:
            self._finish_progress('ticks', False)
            self._set_status('Tick detection could not start: {}'.format(exc))
            self._offer_manual_axis_bounds()
            return
        if not started:
            self._finish_progress('ticks', False)
            self._set_status("Region selected; enter calibration ticks.")
            self._offer_manual_axis_bounds()
        self._refresh_calibration_actions()

    def _region_aligned(self, rect):
        if (not self.winfo_exists() or not self.engine.calibration.snap_to_axes or
                'ticks' not in self._progress_jobs or self._pick_mode == 'area'):
            return
        # Show the aligned rectangle while OCR runs, without changing engine
        # revision/source checks. Commit geometry and readings together later.
        self._region_alignment_preview = tuple(rect)
        self._redraw()

    def _tick_calibration_finished(self, detection, rect, error, *, region_revision=None):
        if not self.winfo_exists():
            return
        self._region_alignment_preview = None
        if self.engine.plot_rect is None or tuple(self.engine.plot_rect) != tuple(rect):
            self._finish_progress('ticks', False)
            return  # A stale result must never open editors for a newer Box.
        if error:
            self._redraw()
            self._finish_progress('ticks', False)
            if "discarded" not in str(error).lower():
                self._set_status("Calibration stopped.", details=str(error))
                if 'cancel' not in str(error).lower():
                    self._offer_manual_axis_bounds()
            else:
                self._set_status('Calibration cancelled.', details='Plot area or calibration changed.')
            return
        if detection is None:
            self._finish_progress('ticks', False)
            self._redraw()
            self._offer_manual_axis_bounds()
            return
        try:
            applied = self.engine.apply_tick_calibration_detection(
                detection, expected_rect=rect)
            if applied and region_revision is not None:
                self.engine.merge_region_tick_history(region_revision)
        except (ValueError, IndexError) as exc:
            self._finish_progress('ticks', False)
            self._set_status("Calibration could not be applied.", details=str(exc))
            self._redraw()
            return

        self._finish_progress('ticks', applied)

        # The OCR result is not the same as the four calibration anchors.
        # Keep the whole verified tick sequence for drawing on the canvas.
        # Never paint guessed or unverified ticks as measured labels.
        if applied:
            self._display_axis_ticks = detection
        details, missing, unread = [], [], 0
        for reading in (detection.x, detection.y):
            axis = reading.axis.upper()
            measured = [tick for tick in reading.ticks if tick.bbox != (0, 0, 0, 0)]
            count = len(reading.unread_positions)
            unread += count
            if reading.ready:
                details.append('{}: {} | {} measured ticks | {} unread'.format(
                    axis, reading.scale.value, len(measured), count))
            else:
                missing.append(axis)
                details.append('{}: not recognized. Initial anchors are placeholders, not measured values.'.format(axis))
            if measured:
                values = [tick.value for tick in measured]
                details.append('{} range: {} .. {}'.format(axis, self._fmt_axis(min(values), reading.scale), self._fmt_axis(max(values), reading.scale)))
        if detection.aligned_rect is not None and tuple(detection.aligned_rect) != tuple(rect):
            details.append('Region aligned to detected axes.')
        if not applied or len(missing) == 2:
            summary = 'Axes not recognized.'
        elif missing:
            summary = 'Calibration incomplete: {} not recognized.'.format(', '.join(missing))
        elif unread:
            summary = 'Axes calibrated; {} unread ticks.'.format(unread)
        else:
            summary = 'Axes calibrated.'
        if missing or unread:
            details.append('Review the Calibration table and enter missing tick values manually.')
        self._set_status(summary, details='\n'.join(details))
        self._refresh_all()
        if missing:
            self._offer_manual_axis_bounds([axis.lower() for axis in missing])

    def _offer_manual_axis_bounds(self, axes=('x', 'y')):
        """Expose blank endpoint editors without confirming internal Box seeds."""
        if self.engine.plot_rect is None:
            return
        axes = {axis for axis in axes if axis not in self.engine.auto_tick_verified_axes}
        if not axes:
            return
        if any(getattr(self.engine.calibration, axis + suffix) is None
               for axis in axes for suffix in ('1', '2')):
            self.engine.prepare_manual_axis_bounds(axes)
        newly_missing = axes - self._manual_bounds_axes
        self._manual_bounds_axes.update(axes)
        self._show_tool('axes')
        self.set_control_value(self._disclosures['axes'], True)
        self._refresh_anchor_values()
        for key, editor in self.anchor_value.items():
            if key[0] in newly_missing:
                self.set_control_value(editor, '')
        self.set_control_value(self.calibration_hint,
            'Axis detection incomplete. Enter {} endpoint values below, then Apply Axis Values. '
            'Detected axes are kept.'.format('/'.join(axis.upper() for axis in sorted(axes))))
        self.set_control_visible(self.calibration_hint, True)
        QRetainedItem(self.settings_panel).setVerticalScrollValue(10000)
        # The disclosure's new height is available only after a layout frame.
        self.view.after(60, self._reveal_manual_axis_bounds, tuple(self.engine.plot_rect))

    def _reveal_manual_axis_bounds(self, rect):
        if (self.winfo_exists() and self._manual_bounds_axes
                and self.engine.plot_rect is not None and tuple(self.engine.plot_rect) == rect
                and self._active_tool == 'axes' and self.control_value(self._disclosures['axes'])):
            QRetainedItem(self.settings_panel).setVerticalScrollValue(10000)

    def _paint_detected_axis_ticks(self, painter):
        """Show all accepted major ticks, not only the four box anchors.

        Coordinates are source-image pixel coordinates; they must be converted
        via the same pan/zoom transform as the calibration anchors.
        """
        detection = getattr(self, "_display_axis_ticks", None)
        rect = self.engine.plot_rect
        if detection is None or rect is None:
            return
        left, top, right, bottom = rect
        for axis, reading, ink in (
                ("x", detection.x, (0, 120, 215, 255)),
                ("y", detection.y, (30, 150, 80, 255))):
            if not reading.ready:
                continue
            # Manual edits replace the automatic multi-point fit.
            if len(reading.ticks) >= 3 and not getattr(self.engine.calibration, "points_" + axis):
                continue
            current = getattr(self.engine.calibration, "points_" + axis)
            expected = {(t.position, t.value) for t in reading.ticks if t.bbox != (0, 0, 0, 0)}
            if current and {(p.px if axis == "x" else p.py, p.value) for p in current} != expected:
                continue  # Manual correction invalidates the old interpolated labels.
            for tick in reading.ticks[:40]:
                if tick.bbox != (0, 0, 0, 0) and getattr(self.engine.calibration, "points_" + axis):
                    continue  # Measured ticks are drawn as editable markers below.
                inferred = tick.bbox == (0, 0, 0, 0)
                display_value = tick.text if (reading.scale == AxisScale.DATETIME and not inferred and tick.text) else self._fmt_axis(tick.value, reading.scale)
                label = ("~" if inferred else "") + display_value
                if axis == "x":
                    if not left - 2 <= tick.position <= right + 2:
                        continue
                    x, y = self._image_to_canvas(tick.position, bottom)
                    painter.drawLine((x, y), (x, y + 5), color=ink)
                    painter.drawText((x + 3, y + 10), label,
                                     color=ink, size=12)
                else:
                    if not top - 2 <= tick.position <= bottom + 2:
                        continue
                    x, y = self._image_to_canvas(left, tick.position)
                    painter.drawLine((x - 5, y), (x, y), color=ink)
                    painter.drawText((x + 9, y - 10), label,
                                     color=ink, size=12)

    def _mouse_middle_down(self, *_args):
        if self._mouse_in_canvas():
            self._reset_point_gesture()
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
        if self._anchor_drag_target is not None:
            if point is not None:
                self._anchor_drag_preview = (
                    max(0., min(self.engine.image.width - 1., point[0])),
                    max(0., min(self.engine.image.height - 1., point[1])))
                self._preview_pixel = self._anchor_drag_preview
            self._hover_anchor = self._anchor_drag_target
            self._hover_point = None
            self._cursor_over_marker = True
            self._redraw()
            return
        if self._point_press is not None:
            position = self._canvas_to_image(now)
            if position is not None:
                self._rubberband_end = position
                scale = max(.001, self._fit_scale * self._zoom)
                if max(abs(position[i] - self._point_press[i]) for i in (0, 1)) * scale >= 4:
                    self._rubberband_active = True
            self._hover_point = None
            self._paint_pointer()
            return
        if point is not None:
            self._preview_pixel = (
                max(0., min(self.engine.image.width - 1., point[0])),
                max(0., min(self.engine.image.height - 1., point[1])))
        if point is not None and 0 <= point[0] < self.engine.image.width and 0 <= point[1] < self.engine.image.height:
            self._cursor_pixel = point
            self._hover_anchor = self._nearest_anchor(*point)
            self._cursor_over_marker = bool(self._hover_anchor) or cursor_hits_marker(
                self.engine.datasets, *point, self._fit_scale * self._zoom,
                size_scale=self._plot_preferences["marker_size_percent"] / 100.0,
                show_automatic=self._plot_preferences["show_automatic_points"],
                show_manual=self._plot_preferences["show_manual_points"])
            if self._drag_start is not None or self._drag_target is not None:
                self._drag_preview = point
            if (self._hover_anchor is None and self._drag_target is None and self._edit_enabled and
                    self._pick_mode in (None, "edit") and not self.engine.active_dataset.locked):
                self._hover_point = self._nearest_point(*point)
            else:
                self._hover_point = None
        else:
            self._cursor_pixel = None
            self._hover_point = None
            self._hover_anchor = None
        self._paint_pointer()

    def _canvas_pointer_tick(self):
        """Refresh hover and recover document keys missed by native callbacks."""
        self._layout_canvas()
        self._update_canvas_view_tool_states()
        if self._middle_drag:
            self._sync_canvas_cursor()
        else:
            self._mouse_move()

        # Share press-edge recovery with the dialog-owned timer. Native windows
        # may omit this visibility callback altogether, so it is not the sole
        # source of keyboard input.
        self._poll_delete_key()

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
        if self._canvas_view_tools_under_mouse() and not (self._middle_drag or self._anchor_drag_target is not None):
            cursor.update(None)
            return
        mode = ("move" if self._middle_drag or self._anchor_drag_target is not None else
                "color_pick" if self._pick_mode == "curve" else
                "point" if self._hover_anchor is not None else
                "blank" if self._cursor_canvas is not None and self._plot_preferences["show_crosshair"] else None)
        (x, y), (width, height) = self._canvas_rect()
        cursor.update(
            mode, (x, y, x + width, y + height),
            capture=self._middle_drag or self._anchor_drag_target is not None,
            screen_coordinates=self._native_window_backend is not None)

    def _mouse_wheel(self, _sender, app_data):
        if (self._plot_preferences["mouse_wheel_zoom"] and
                self._mouse_in_canvas() and self.engine.image is not None):
            factor = 1 + self._plot_preferences.get("wheel_zoom_percent", 12) / 100.0
            self._zoom_at(factor if app_data > 0 else 1 / factor, mouse=QCursor.pos().toTuple())

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

    def _paint_calibration_markers(self, painter, cw, ch):
        cal = self.engine.calibration
        colors = {'x': (0, 120, 215, 255), 'y': (30, 150, 80, 255)}
        origin_drawn = False
        for key, anchor in self._calibration_markers():
            x, y = self._image_to_canvas(*self._anchor_display_pixel(key))
            corner = key in ('x1', 'x2', 'y1', 'y2') and (cal.box_rect is not None or not getattr(cal, 'points_' + key[0]))
            origin = (corner and key.endswith('1') and cal.x1 is not None and cal.y1 is not None and
                      abs(cal.x1.px - cal.y1.px) < 1e-9 and abs(cal.x1.py - cal.y1.py) < 1e-9)
            if not origin or not origin_drawn:
                draw_axis_marker(self.canvas, (x, y), key[0],
                                 kind='origin' if origin else ('corner' if corner else 'tick'),
                                 color=(140, 60, 180, 255) if origin else colors[key[0]])
            origin_drawn = origin_drawn or origin
            verified = key[0] in self.engine.auto_tick_verified_axes or bool(getattr(cal, 'points_' + key[0]))
            estimated = (corner and bool(getattr(cal, 'points_' + key[0])) and
                         self._calibration_point_index(key) is None)
            value = (('~' if estimated else '') + self._fmt_axis(anchor.value, key[0])) if verified else '?'
            if key.endswith('draft'):
                value = '?'
            label = '{} = {}'.format(self._calibration_marker_label_key(key), value)
            label_width = len(label) * 7
            if key.startswith('x'):
                label_x, label_y = x - label_width / 2, y + 14
            else:
                label_x, label_y = x - label_width - 14, y - 7
            label_x = max(6, min(cw - label_width - 6, label_x))
            label_y = max(6, min(ch - 20, label_y))
            painter.drawText((label_x, label_y), label, color=colors[key[0]], size=14)

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
            left, top, right, bottom = self._region_alignment_preview or self.engine.plot_rect
            painter.drawRect(
                self._image_to_canvas(left, top), self._image_to_canvas(right, bottom),
                color=(30, 150, 80, 180), fill=(0, 0, 0, 0))
        self._paint_detected_axis_ticks(painter)
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
                                color=color, outline=(255, 255, 255, 235), thickness=1.0)
            if self._plot_preferences["show_manual_points"]:
                for p in ds.manual_points:
                    x, y = self._image_to_canvas(p.px, p.py)
                    draw_marker(self.canvas, (x, y), manual_metrics.radius, marker_style,
                                color=color, outline=(255, 255, 255, 235), thickness=1.0)
        # Calibration symbols stay above data markers even at coincident pixels.
        self._paint_calibration_markers(painter, cw, ch)
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
        selected_points = set(self.result_grid.selectedKeys())
        if self._selected_point is not None:
            selected_points.add("{}:{}".format(*self._selected_point))
        for key in selected_points:
            selected_point = self._key_point(key)
            if not self._marker_visible(selected_point[0]):
                continue
            try:
                selected = self._image_to_canvas(*self.engine.point_pixels(*selected_point))
                radius = self._marker_metrics(max(0.05, scale), selected_point[0]).selection_radius + 1
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
        if self._rubberband_active and self._point_press is not None and self._rubberband_end is not None:
            a, b = self._image_to_canvas(*self._point_press), self._image_to_canvas(*self._rubberband_end)
            painter.drawRect((min(a[0], b[0]), min(a[1], b[1])),
                             (max(a[0], b[0]), max(a[1], b[1])),
                             color=(0, 120, 215, 255), fill=(0, 120, 215, 35))
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
        anchor_key = self._anchor_drag_target or self._hover_anchor
        if anchor_key is not None and self._active_tool == "axes":
            anchor_pixel = self._anchor_display_pixel(anchor_key)
            if anchor_pixel is not None:
                painter.drawEllipse(
                    self._image_to_canvas(*anchor_pixel), 9,
                    color=(240, 130, 20, 255) if self._anchor_drag_target else (0, 120, 215, 230),
                    fill=(0, 0, 0, 0), thickness=2)
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
        """Keep the last pointer sample visible at the configured magnification."""
        if self.engine.image is None or self._texture_tag is None:
            return
        iw, ih = self.engine.image.size
        point = self._preview_pixel or (iw / 2., ih / 2.)
        _, (cw, ch) = self._canvas_rect()
        preferences = getattr(self, '_plot_preferences', PlotDigitizerPreferences.DEFAULTS)
        magnification = preferences.get("preview_zoom", 5)
        size = max(1, min(preferences.get("preview_size", 140), cw - 20, ch - 20))
        geometry = preview_geometry((iw, ih), point, self._fit_scale * self._zoom, size,
                                    magnification=magnification)
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
        if preferences.get("preview_crosshair", True):
            painter.drawLine((p0[0], my), (p1[0], my), color=color)
            painter.drawLine((mx, p0[1]), (mx, p1[1]), color=color)
        painter.drawText((p0[0] + 3, p0[1] + 3), "{}x".format(magnification),
                         color=(0, 120, 215, 255), size=12)

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
        self._begin_progress('image', 'Opening image...')

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
                    self.set_control_value(self.anchor_value[key], "")
                    self.set_control_enabled(self.anchor_value[key], False)
                self._load_texture(self.engine.image)
                self.view.after(1, self._fit_view if self._auto_fit else self._one_to_one)
                self._finish_progress('image')
                self._set_status("")
            except Exception as exc:
                self._finish_progress('image', False)
                self._set_status("Could not open image: {}".format(exc))

        def failed(exc):
            if generation == self._image_load_generation:
                self._finish_progress('image', False)
                self._set_status("Could not open image: {}".format(exc))

        try:
            self._image_load_future = self.runAsync(
                self.engine.read_image, path, on_result=loaded, on_error=failed)
        except Exception as exc:
            failed(exc)

    def _choose_load_project(self):
        self._file_picker(extensions=(".pdg", ".json"), callback=self._load_project)

    def _load_project(self, path):
        try:
            state = self.engine.load_project(path, view_validator=normalize_workspace_state)
            self._project_path = str(Path(path).resolve())
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
                application = QApplication.instance()
                if application is not None:
                    application.primaryScreen().resizeWindow(max(1100, int(width)), max(720, int(height)))
                else:
                    QGuiRuntime().configureViewport(width=max(1100, int(width)), height=max(720, int(height)))
            self.view.after(1, self._restore_project_view, state, generation, self._project_frame() + 2)
            self._set_status("Project loaded.")
        except Exception as exc:
            self._set_status("Could not load project: {}".format(exc))

    def _choose_save_project(self):
        if self._project_path:
            return self._save_project(self._project_path)
        return self._choose_save_project_as()

    def _choose_save_project_as(self):
        self._file_picker(save=True, extensions=(".pdg",), callback=self._save_project,
                          default_filename=Path(self._project_path).name if self._project_path else "plot_digitizer.pdg")

    def _save_project(self, path):
        try:
            path = str(path)
            if Path(path).suffix.casefold() not in (".pdg", ".json"):
                path += ".pdg"
            self.engine.save_project(path, view_state=self._capture_project_view())
            self._project_path = str(Path(path).resolve())
            self._file_directory = str(Path(self._project_path).parent)
            self._set_status("Project saved.")
        except Exception as exc:
            self._set_status("Could not save project: {}".format(exc))

    def _capture_project_view(self):
        _, size = self._canvas_rect()
        application = QApplication.instance()
        if application is not None:
            geometry = application.primaryScreen().windowGeometry()
            viewport_size = [geometry.width(), geometry.height()]
        else:
            viewport = QGuiRuntime().viewportSize()
            viewport_size = [max(1, viewport.width()), max(1, viewport.height())]
        state = {
            "version": 1, "tool": self._active_tool or "axes",
            "calibration_method": self._calibration_method,
            "ribbon_tab": self.ribbon.active_tab() or "home", "ribbon_minimized": self.ribbon.is_minimized(),
            "coordinate_mode": self.control_value(self.coordinate_mode),
            "export_scope": self.control_value(self.export_scope),
            "export_sort": self.EXPORT_SORT_OPTIONS[self.control_value(self.export_sort)],
            "reduction_error": float(self.control_value(self.reduction_error)),
            "auto_fit": self._auto_fit, "scale": self._fit_scale * self._zoom, "zoom": self._zoom,
            "pan": list(self._pan), "canvas_size": list(size),
            "viewport_size": viewport_size,
            "selected_point": self._selected_point,
            "selected_rows": list(self.result_grid.selectedKeys()), "grid_current": self.result_grid.currentKey(),
            "edit_enabled": self._edit_enabled,
            "anchor_text": {key: str(self.control_value(editor)) for key, editor in self.anchor_value.items()},
            "dataset_name_text": self.engine.active_dataset.name,
            "point_x_text": str(self.control_value(self.point_x)), "point_y_text": str(self.control_value(self.point_y)),
            "sample_pixel": self._sample_pixel, "cursor_pixel": self._cursor_pixel,
            "palette": [list(color) for color in self._palette], "palette_selection": self.control_value(self.palette_combo),
            "pick_mode": self._pick_mode, "calibration_sequence": list(self._calibration_sequence),
            "disclosures": {key: bool(self.control_value(item)) for key, item in self._disclosures.items()},
            "dataset_scroll": QRetainedItem(self.dataset_panel).verticalScrollValue(), "settings_scroll": QRetainedItem(self.settings_panel).verticalScrollValue(),
        }
        return normalize_workspace_state(state, self.engine)

    @staticmethod
    def _project_frame():
        application = QApplication.instance()
        return application.frameCount() if application is not None else _renderer_backend().get_frame_count()

    def _restore_project_view(self, state, generation, after_frame):
        if not self.winfo_exists() or generation != self._project_load_generation:
            return
        if self._project_frame() < after_frame:
            self.view.after(1, self._restore_project_view, state, generation, after_frame)
            return
        self._refresh_all()
        if not state:
            self._set_calibration_method('smart' if self.engine.calibration.box_rect is not None else 'manual',
                                         cancel_pending=False)
            self._fit_view()
            return
        self._set_calibration_method(state['calibration_method'], cancel_pending=False)
        self.set_control_value(self.coordinate_mode, state["coordinate_mode"])
        self.set_control_value(self.export_scope, state["export_scope"])
        self.set_control_value(self.export_sort, next(
            label for label, value in self.EXPORT_SORT_OPTIONS.items() if value == state["export_sort"]))
        self._control_wrappers[self.reduction_error].setValue(state["reduction_error"])
        self._refresh_grid()
        self._set_edit_enabled(state["edit_enabled"])
        # Older projects could save the former embedded Settings page. It is
        # no longer a workflow and loading a project must not open a modal.
        self._show_tool("axes" if state["tool"] == "settings" else state["tool"])
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
        self._calibration_sequence = []
        self.set_control_visible(self.calibration_hint, self._pick_mode in ("x1", "x2", "y1", "y2"))
        if self._pick_mode in ("x1", "x2", "y1", "y2"):
            self.set_control_value(
                self.calibration_hint,
                "Click {} on a known axis tick. Esc cancels.".format(self._pick_mode.upper()))
        for key, text in state["anchor_text"].items():
            editor = self.anchor_value[key]
            anchor = getattr(self.engine.calibration, key)
            restored = text if anchor is not None else ""
            self._control_wrappers[editor].setText(restored)
            self.set_control_value(editor, restored)
            self.set_control_enabled(editor, anchor is not None)
        for field, key in ((self.point_x, "point_x_text"), (self.point_y, "point_y_text")):
            if state[key] is not None:
                self._control_wrappers[field].setText(state[key])
                self.set_control_value(field, state[key])
        # Apply camera/scroll after disclosure/ribbon changes settle as well.
        self.view.after(1, self._restore_project_camera, state, generation, self._project_frame() + 2)
        self._refresh_export_controls()

    def _restore_project_camera(self, state, generation, after_frame):
        if not self.winfo_exists() or generation != self._project_load_generation:
            return
        if self._project_frame() < after_frame:
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
        if self.dataset_panel != self.settings_panel:
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
            order = self.EXPORT_SORT_OPTIONS[self.control_value(self.export_sort)]
            self.engine.export_csv(path, dataset_index, sort_by=None if order == "original" else order)
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

    def _set_status(self, text, *, details=None, quiet=False):
        if quiet and getattr(self, '_progress_jobs', {}):
            return  # Selection/edit chatter must not replace active work status.
        if getattr(self, "status", None) and QRetainedItem(self.status).exists():
            self._status_summary = ' '.join(str(text or 'Ready.').split())
            self._status_detail = str(details if details is not None else text or 'Ready.')
            self._layout_status_text()
            if getattr(self, '_status_help', None):
                QRetainedItem(self._status_help).setValue(self._status_detail)

    def _layout_status_text(self):
        if not getattr(self, 'status', None) or not QRetainedItem(self.status).exists():
            return
        # Window chrome is full-bleed, unlike the inset ribbon/workspace. Anchor
        # to the client area's bottom, not the padded normal-flow cursor.
        window = QRetainedItem(self.tag).globalGeometry()
        content = QRetainedItem(self.content).globalGeometry()
        client_width = window.x() + window.width() - content.x()
        client_height = window.y() + window.height() - content.y()
        if client_width > 0 and client_height > 0:
            QRetainedItem(self.content).configure(width=client_width, height=client_height)
        if content.width() > 0 and content.height() > 0:
            QRetainedItem(self.status_bar.tag).configure(
                pos=(0, max(0, content.height() - self.STATUS_HEIGHT)),
                width=content.width(), height=self.STATUS_HEIGHT)
            self.status_bar.backend.configure_item(
                self._status_grip_host.tag,
                pos=(max(0, content.width() - 13), self.STATUS_HEIGHT - 13))
        if hasattr(self, '_status_top_rule_canvas') and self._status_top_rule_canvas.exists():
            bar = QRetainedItem(self.status_bar.tag).globalGeometry()
            if bar.width() > 0:
                self._status_top_rule_canvas.resize(bar.width(), 1)
                QRetainedItem(self._status_top_rule_draw).configure(p2=(max(1, bar.width() - 1), 0))
        value = self._status_summary
        host = QRetainedItem(self._status_message_host.tag).globalGeometry()
        width = max(0, host.width() - 4)
        metrics = QFontMetrics(backend=self._status_message_host.backend)
        # ImGui carries the table row's text baseline into this child. Offset
        # that baseline as well as centering the glyphs in the compact strip.
        QRetainedItem(self.status).configure(pos=(
            0, round((self.STATUS_ROW_HEIGHT - metrics.height()) / 2) - 4))
        if metrics.horizontalAdvance(value) > width:
            low, high = 0, len(value)
            while low < high:
                middle = (low + high + 1) // 2
                if metrics.horizontalAdvance(value[:middle].rstrip() + '\u2026') <= width:
                    low = middle
                else:
                    high = middle - 1
            value = (value[:low].rstrip() + '\u2026'
                     if metrics.horizontalAdvance('\u2026') <= width else '')
        if value != self._status_visible:
            self._status_visible = value
            self.set_status_text(self.status, value)

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
        self._layout_progress_text()
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
            self._canvas_view_toolbar.move(
                max(6, (frame_size[0] - self.CANVAS_VIEW_TOOLS_WIDTH) // 2), 6)
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
        if (self._active_tool != "data" or self._data_layout_pending
                or self.data_worksheet.isDragging()):
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
        if (not self.winfo_exists() or self._active_tool != "data"
                or self.data_worksheet.isDragging()):
            return
        tail = self.export_data_button
        if self.control_visible(self.point_editor_container):
            tail = self.next_point_button
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

    def _request_close_confirmation(self):
        """Ask before the user exits Plot Digitizer.

        The main WinUx view already owns a serialized confirmation queue.  The
        standalone Plot Digitizer host intentionally stays application-neutral,
        so it falls back to the same retained BlockingDialog locally.  Keeping
        this transaction here makes caption-X, native WM_CLOSE and final Escape
        all obey one policy without making programmatic teardown interactive.
        """
        if getattr(self, "_closed", False):
            return False
        if self._close_confirmation_pending:
            dialog = self._close_confirmation_dialog
            if dialog is None:
                current = getattr(self.view, "_async_confirm_dialog", None)
                if getattr(current, "_requested_parent", None) is self:
                    dialog = self._close_confirmation_dialog = current
            if dialog is not None:
                dialog.lift()
            return False

        self._close_confirmation_pending = True
        message = (
            "Are you sure you want to exit Plot Digitizer?\n\n"
            "Any unsaved changes will be lost."
        )
        try:
            confirm_async = getattr(self.view, "confirm_action_async", None)
            if callable(confirm_async):
                dialog = confirm_async(
                    "Confirm Exit Plot Digitizer",
                    message,
                    self._close_confirmation_finished,
                    primary_text="Exit",
                    secondary_text="Cancel",
                    intent="warning",
                    parent=self,
                )
                if callable(getattr(dialog, "lift", None)):
                    self._close_confirmation_dialog = dialog
                return True

            # StandaloneUiHost deliberately exposes only scheduling primitives.
            # Reuse WinUx's normal retained message-box implementation rather
            # than inventing a second visual style for this one confirmation.
            from ...dialogs.blocking_form import BlockingDialog
            dialog = BlockingDialog(
                self.view,
                "Confirm Exit Plot Digitizer",
                message,
                "confirm",
                on_result=self._close_confirmation_finished,
                primary_text="Exit",
                secondary_text="Cancel",
                intent="warning",
                parent=self,
            )
            self._close_confirmation_dialog = dialog
            dialog.lift()
            return True
        except Exception:
            self._close_confirmation_pending = False
            self._close_confirmation_dialog = None
            raise

    def _close_confirmation_finished(self, confirmed):
        self._close_confirmation_pending = False
        # BlockingDialog invokes the callback before destroying itself. Clear
        # this reference first so confirmed teardown cannot destroy the child a
        # second time from PlotDigitizerDialog.destroy().
        self._close_confirmation_dialog = None
        if confirmed and not getattr(self, "_closed", False):
            self.destroy()

    def _close_from_native(self):
        self._request_close_confirmation()

    def reject(self):
        self._close_from_escape()

    def _close_from_escape(self):
        if self._point_press is not None:
            self._reset_point_gesture()
            self._redraw()
            self._set_status("Selection cancelled.")
        elif self._edit_enabled and (
                self._selected_point is not None or self.result_grid.selectedKeys()):
            self._clear_point_selection()
            self._refresh_point_editor()
            self._redraw()
            self._set_status("Selection cleared.", quiet=True)
        elif self._pick_mode is not None or getattr(self, '_calibration_draft', None) is not None:
            self._cancel_pick()
        elif self._edit_enabled:
            self._edit_mode_toggled(False)
        else:
            self._request_close_confirmation()

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
        clean_dialog = getattr(self, '_clean_confirmation_dialog', None)
        self._clean_confirmation_dialog = None
        self._clean_confirmation_pending = False
        if clean_dialog is not None:
            clean_dialog.finish(False)
        self._close_confirmation_pending = False
        close_dialog, self._close_confirmation_dialog = self._close_confirmation_dialog, None
        if close_dialog is not None:
            try:
                # Complete the shared confirmation queue as cancelled, rather
                # than leaving its active token stranded during tool teardown.
                close_dialog.finish(False)
            except Exception:
                try:
                    close_dialog.destroy()
                except Exception:
                    pass
        if self._settings_dialog is not None:
            self._settings_dialog.destroy()
            self._settings_dialog = None
        if self._sample_count_dialog is not None:
            self._sample_count_dialog.destroy()
            self._sample_count_dialog = None
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
            self._reuse_safe_on_close = bool(self._tick_calibration_runner.close()) and self._reuse_safe_on_close
        except Exception:
            self._reuse_safe_on_close = False
        # QtDialog now performs visual close before retained-object teardown;
        # the heavyweight DPG registries above follow the same deferred path.
        super().destroy()
