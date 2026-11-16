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
from DearUIQt.gui.palette import color_scheme
from DearUIQt.core import Qt, QItemInputBinding, QGlobalInputBinding

from DearUIQt.widgets import QApplication, QCanvas, QToolButton, QFrame, QSpacer, QLabel, QToolTip, QRetainedItem, QProgressBar

from ..core import AxisScale, AxisAnchor, DigitizerEngine, ExtractionSettings
from ..application import SmartDetectRunner, TickCalibrationRunner, normalize_workspace_state
from ..core.extraction import detect_curve_colors
from ..core.axis_labels import format_axis_value, parse_axis_value_input
from DearUIQt import (
    ToolWindow, QtDataGridView, QtGridRow, QtListView, QtFusionPalette,
    QtListItem, ColorField, QPushButton, QMenu, QAction, QtConcurrent, QEditTransaction,
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
from .controllers import (CanvasController, CalibrationController, DataController, ProjectController)
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

    def _renderer_backend(self):
        """Resolve the renderer through the historical dialog-level patch point."""
        return _renderer_backend()

    def _draw_axis_marker(self, *args, **kwargs):
        """Compatibility bridge for historical dialog-level marker patches."""
        return draw_axis_marker(*args, **kwargs)

    def _controller(self, attribute, controller_type):
        """Return a lazily attached feature controller.

        Lazy creation preserves the lightweight ``__new__`` fixtures used by
        existing tests/integrations while normal instances eagerly create all
        controllers in ``__init__``.
        """
        controller = getattr(self, attribute, None)
        if controller is None:
            controller = controller_type(self)
            setattr(self, attribute, controller)
        return controller

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
        self._edit_transaction = None
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
        self._canvas_controller = CanvasController(self)
        self._calibration_controller = CalibrationController(self)
        self._data_controller = DataController(self)
        self._project_controller = ProjectController(self)

        super().__init__(view, "Plot Digitizer", 1240, 780, footer=False, native=native)
        # QObject ownership is only valid after ToolWindow/QtDialog has initialized
        # the QObject base. Creating a parented transaction before this point makes
        # QObject.setParent() inspect an uninitialized PlotDigitizerDialog.
        self._edit_transaction = QEditTransaction(parent=self)
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
            'home', 'data', 'view_data', 'View Data', lambda: self._show_tool('data', sync_ribbon=True),
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
        self.ribbon.add_group('data', 'output', 'Export', width=144, layout='large')
        self.ribbon.add_button(
            'data', 'output', 'export_csv', 'Export CSV', self._choose_export_csv,
            image=ribbon_icon('export_csv'), tooltip='Export calibrated digitized data to CSV')
        self.ribbon.add_button(
            'data', 'output', 'export_excel', 'Export Excel', self._choose_export_excel,
            image=ribbon_icon('export_csv'), tooltip='Export calibrated data and calibration metadata to Excel (.xlsx) using XLPP')
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
            # Workflow page navigation must be driven only by explicit user
            # activation. currentChanged is intentionally *not* connected: it
            # can be emitted by model refresh/selection restoration and used to
            # make clicks in unrelated controls jump between workflow pages.
            self.tool_list.userActivated.connect(self._show_tool)
            self.tool_list.activated.connect(self._show_tool)
            self.tool_list.itemCheckChanged.connect(self._workflow_check_clicked)
            self._add_help(self.tool_list.tag,
                            "Choose a step. Checkboxes show completed work automatically: both axes calibrated, "
                            "points acquired, and current data opened for review. Clicking the checkbox or its text opens the step.")
        QSpacer(0, 8, parent=panel)

    def _status_surface_themes(self):
        p = QtFusionPalette
        scheme = color_scheme().strip().lower()
        inner = make_theme(theme_component(
            ThemeTarget.CHILD_WINDOW,
            colors={ThemeColor.CHILD_BACKGROUND: p.WINDOW,
                    ThemeColor.BORDER: (0, 0, 0, 0)},
            styles={ThemeStyle.WINDOW_PADDING: (0, 1),
                    ThemeStyle.ITEM_SPACING: (0, 0),
                    ThemeStyle.CHILD_BORDER_SIZE: 0,
                    ThemeStyle.CHILD_ROUNDING: 0}),
            backend=self.status_bar.backend,
            tag='winux.plotdigitizer.statusbar.inner.{}'.format(scheme), cache=True)
        progress = make_theme(theme_component(
            ThemeTarget.CHILD_WINDOW,
            colors={ThemeColor.CHILD_BACKGROUND: p.WINDOW,
                    ThemeColor.BORDER: (0, 0, 0, 0)},
            styles={ThemeStyle.WINDOW_PADDING: (0, 0),
                    ThemeStyle.ITEM_SPACING: (0, 0),
                    ThemeStyle.CHILD_BORDER_SIZE: 0,
                    ThemeStyle.CHILD_ROUNDING: 0}),
            backend=self.status_bar.backend,
            tag='winux.plotdigitizer.statusbar.progress.host.{}'.format(scheme), cache=True)
        return inner, progress

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
        self._status_inner_theme, self._status_progress_theme = self._status_surface_themes()

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
        self._status_grip_draws = []
        for start in (4, 7, 9):
            self._status_grip_draws.append((
                grip.drawLine((10, start), (start, 10), color=p.TEXT_MUTED), 'muted'))
            self._status_grip_draws.append((
                grip.drawLine((10, start + 1), (start + 1, 10), color=p.BASE), 'base'))

        # Child-window themes cannot express a top-only border, so draw the
        # one-pixel QStatusBar separator explicitly and resize it with the bar.
        self._status_top_rule_canvas = self.own_widget(QCanvas(
            width=1, height=1, parent=self.status_bar, pos=(0, 0)))
        self._status_top_rule_draw = QPainter(self._status_top_rule_canvas).drawLine(
            (0, 0), (1, 0), color=p.BORDER_LIGHT)

        self._set_progress_visible(False)
        self._layout_progress_text()

    def _refresh_theme_surfaces(self):
        """Refresh Plot Digitizer retained/raw surfaces after Light/Dark changes."""
        p = QtFusionPalette
        try:
            self._content_theme = style_tool_surface(
                self.content, padding=(self.OUTER_MARGIN, 0), spacing=(0, self.REGION_GAP))
        except Exception:
            pass
        try:
            self.ribbon.set_visual_style(self.ribbon.visual_style_key)
        except Exception:
            pass
        try:
            self._canvas_controller.refresh_theme()
        except Exception:
            pass
        try:
            self.status_bar.setTheme(status_bar_theme(backend=self.status_bar.backend))
            self._status_inner_theme, self._status_progress_theme = self._status_surface_themes()
            self._status_message_host.setTheme(self._status_inner_theme)
            self._status_progress_host.setTheme(self._status_progress_theme)
            self._status_grip_host.setTheme(self._status_progress_theme)
            self.status_bar.backend.bind_item_theme(
                self.status, status_text_theme(backend=self.status_bar.backend, muted=False))
            state = self.progress_bar._properties.get('state', 'normal')
            self.progress_bar.setState(state)
            self.status_bar.backend.configure_item(self._progress_text_draw, color=p.TEXT)
            for draw, role in getattr(self, '_status_grip_draws', ()):
                self.status_bar.backend.configure_item(
                    draw, color=p.TEXT_MUTED if role == 'muted' else p.BASE)
            self.status_bar.backend.configure_item(self._status_top_rule_draw, color=p.BORDER_LIGHT)
        except Exception:
            pass
        try:
            self._layout_progress_text()
        except Exception:
            pass
        return True

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
        return self._controller("_data_controller", DataController)._build_data_panel(panel)

    def _build_canvas_panel(self, parent):
        return self._controller("_canvas_controller", CanvasController)._build_canvas_panel(parent)

    def _build_canvas_view_tools(self):
        return self._controller("_canvas_controller", CanvasController)._build_canvas_view_tools()

    def _update_canvas_view_tool_states(self):
        return self._controller("_canvas_controller", CanvasController)._update_canvas_view_tool_states()

    def _canvas_view_tools_under_mouse(self):
        return self._controller("_canvas_controller", CanvasController)._canvas_view_tools_under_mouse()

    def _toggle_action(self, label, callback, *, parent, width=-1):
        return self._controller("_canvas_controller", CanvasController)._toggle_action(label, callback, parent=parent, width=width)

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
        return self._controller("_calibration_controller", CalibrationController)._build_axes_panel(parent)

    def _axis_snapping_changed(self, enabled):
        return self._controller("_calibration_controller", CalibrationController)._axis_snapping_changed(enabled)

    def _set_calibration_method(self, method, *, cancel_pending=True):
        return self._controller("_calibration_controller", CalibrationController)._set_calibration_method(method, cancel_pending=cancel_pending)

    def _refresh_calibration_actions(self):
        return self._controller("_calibration_controller", CalibrationController)._refresh_calibration_actions()

    def _begin_manual_calibration_point(self):
        return self._controller("_calibration_controller", CalibrationController)._begin_manual_calibration_point()

    def _reread_calibration_ticks(self):
        return self._controller("_calibration_controller", CalibrationController)._reread_calibration_ticks()

    def _build_auto_panel(self, parent):
        return self._controller("_calibration_controller", CalibrationController)._build_auto_panel(parent)

    def _sync_pick_color(self, rgb):
        return self._controller("_calibration_controller", CalibrationController)._sync_pick_color(rgb)

    def _pick_color_button_theme(self, *, focused=False, disabled=False):
        return self._controller("_calibration_controller", CalibrationController)._pick_color_button_theme(focused=focused, disabled=disabled)

    def _build_auto_settings_panel(self, parent, *, ui=None):
        return self._controller("_calibration_controller", CalibrationController)._build_auto_settings_panel(parent, ui=ui)

    def _build_point_editor(self, parent):
        return self._controller("_calibration_controller", CalibrationController)._build_point_editor(parent)

    def _show_tool(self, tool, *, sync_ribbon=False):
        return self._controller("_calibration_controller", CalibrationController)._show_tool(
            tool, sync_ribbon=sync_ribbon)

    def _workflow_check_clicked(self, key, _checked):
        return self._controller("_calibration_controller", CalibrationController)._workflow_check_clicked(key, _checked)

    def _refresh_workflow_completion(self):
        return self._controller("_calibration_controller", CalibrationController)._refresh_workflow_completion()

    def _apply_calibration_values(self):
        return self._controller("_calibration_controller", CalibrationController)._apply_calibration_values()

    def _build_extraction_options(self, panel, *, ui=None):
        return self._controller("_calibration_controller", CalibrationController)._build_extraction_options(panel, ui=ui)

    def _calibration_axis_changed(self):
        return self._controller("_calibration_controller", CalibrationController)._calibration_axis_changed()

    def _calibration_point_selected(self, key, *_):
        return self._controller("_calibration_controller", CalibrationController)._calibration_point_selected(key, *_)

    def _refresh_calibration_points(self):
        return self._controller("_calibration_controller", CalibrationController)._refresh_calibration_points()

    def _begin_place_axis_point(self):
        return self._controller("_calibration_controller", CalibrationController)._begin_place_axis_point()

    def _place_calibration_draft(self, axis, px, py):
        return self._controller("_calibration_controller", CalibrationController)._place_calibration_draft(axis, px, py)

    def _begin_add_calibration_point(self, value_text=None):
        return self._controller("_calibration_controller", CalibrationController)._begin_add_calibration_point(value_text)

    def _update_calibration_point_value(self):
        return self._controller("_calibration_controller", CalibrationController)._update_calibration_point_value()

    def _repick_calibration_point(self):
        return self._controller("_calibration_controller", CalibrationController)._repick_calibration_point()

    def _remove_calibration_point(self):
        return self._controller("_calibration_controller", CalibrationController)._remove_calibration_point()

    def _anchor_row(self, table, key, label):
        return self._controller("_calibration_controller", CalibrationController)._anchor_row(table, key, label)

    def _anchor_value_changed(self, key, value):
        return self._controller("_calibration_controller", CalibrationController)._anchor_value_changed(key, value)

    def _anchor_pick_value(self, key):
        return self._controller("_calibration_controller", CalibrationController)._anchor_pick_value(key)

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
        if _event in ("data_preview_changed", "calibration_preview_changed"):
            # Live gesture updates must not run the full refresh path: that path
            # intentionally clears point/drag state for committed data changes.
            # The engine has already recomputed curve/calibration data, so a
            # lightweight redraw is sufficient until the transaction commits.
            self._redraw()
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
        self.ribbon.set_button_enabled("export_excel", can_export)
        if hasattr(self, "export_data_button"):
            self.set_control_enabled(self.export_data_button, can_export)
        if hasattr(self, "export_excel_button"):
            self.set_control_enabled(self.export_excel_button, can_export)

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
        return self._controller("_data_controller", DataController)._refresh_data_summary()

    def _select_all_data_points(self):
        return self._controller("_data_controller", DataController)._select_all_data_points()

    def _clear_data_selection(self):
        return self._controller("_data_controller", DataController)._clear_data_selection()

    def _refresh_dataset_list(self):
        return self._controller("_data_controller", DataController)._refresh_dataset_list()

    def _refresh_dataset_controls(self):
        return self._controller("_data_controller", DataController)._refresh_dataset_controls()

    def _coordinate_mode_changed(self, *_args):
        return self._controller("_data_controller", DataController)._coordinate_mode_changed(*_args)

    def _refresh_grid(self):
        return self._controller("_data_controller", DataController)._refresh_grid()

    def _refresh_anchor_values(self):
        return self._controller("_data_controller", DataController)._refresh_anchor_values()

    def _fmt(self, value):
        return self._controller("_data_controller", DataController)._fmt(value)

    def _fmt_axis(self, value, axis_or_scale):
        return self._controller("_data_controller", DataController)._fmt_axis(value, axis_or_scale)

    def _dataset_selected(self, index):
        return self._controller("_data_controller", DataController)._dataset_selected(index)

    def _dataset_index_for_object(self, target):
        return self._controller("_data_controller", DataController)._dataset_index_for_object(target)

    def _dataset_visibility_changed(self, key, visible):
        return self._controller("_data_controller", DataController)._dataset_visibility_changed(key, visible)

    def _dataset_context_open(self, key, position):
        return self._controller("_data_controller", DataController)._dataset_context_open(key, position)

    def _dataset_context_action(self, action, target):
        return self._controller("_data_controller", DataController)._dataset_context_action(action, target)

    def _add_dataset(self):
        return self._controller("_data_controller", DataController)._add_dataset()

    def _delete_dataset(self):
        return self._controller("_data_controller", DataController)._delete_dataset()

    def _settings(self):
        return self._controller("_data_controller", DataController)._settings()

    def _scale_changed(self, *_args):
        return self._controller("_data_controller", DataController)._scale_changed(*_args)

    def _detect_area(self):
        return self._controller("_data_controller", DataController)._detect_area()

    def _auto_color(self):
        return self._controller("_data_controller", DataController)._auto_color()

    def _palette_selected(self, _sender, value, *_args):
        return self._controller("_data_controller", DataController)._palette_selected(_sender, value, *_args)

    def _color_changed(self, value):
        return self._controller("_data_controller", DataController)._color_changed(value)

    def _calibrate_area(self):
        return self._controller("_data_controller", DataController)._calibrate_area()

    def _undo(self):
        return self._controller("_data_controller", DataController)._undo()

    def _refresh_history_commands(self):
        return self._controller("_data_controller", DataController)._refresh_history_commands()

    def _refresh_history_buttons(self, key, enabled):
        return self._controller("_data_controller", DataController)._refresh_history_buttons(key, enabled)

    def _trigger_history_command(self, key):
        return self._controller("_data_controller", DataController)._trigger_history_command(key)

    def _redo(self):
        return self._controller("_data_controller", DataController)._redo()

    def _cancel_history_jobs(self):
        return self._controller("_data_controller", DataController)._cancel_history_jobs()

    def _extract_curve(self):
        return self._controller("_data_controller", DataController)._extract_curve()

    def _extraction_status(self, ok, dataset_index=None):
        return self._controller("_data_controller", DataController)._extraction_status(ok, dataset_index)

    def _smart_detect(self):
        return self._controller("_data_controller", DataController)._smart_detect()

    def _start_extraction(self, *, auto_detect):
        return self._controller("_data_controller", DataController)._start_extraction(auto_detect=auto_detect)

    def _smart_finished(self, result, settings, dataset_index, error):
        return self._controller("_data_controller", DataController)._smart_finished(result, settings, dataset_index, error)

    def _set_edit_enabled(self, enabled):
        return self._controller("_data_controller", DataController)._set_edit_enabled(enabled)

    def _edit_mode_toggled(self, enabled):
        return self._controller("_data_controller", DataController)._edit_mode_toggled(enabled)

    def _toggle_edit_mode(self):
        return self._controller("_data_controller", DataController)._toggle_edit_mode()

    # ---------- point editing ----------
    def _reset_point_gesture(self):
        return self._controller("_data_controller", DataController)._reset_point_gesture()

    def _select_canvas_points(self, keys):
        return self._controller("_data_controller", DataController)._select_canvas_points(keys)

    def _finish_point_gesture(self, point):
        return self._controller("_data_controller", DataController)._finish_point_gesture(point)

    def _clear_point_selection(self):
        return self._controller("_data_controller", DataController)._clear_point_selection()

    def _key_point(self, key):
        return self._controller("_data_controller", DataController)._key_point(key)

    def _point_selected(self, key):
        return self._controller("_data_controller", DataController)._point_selected(key)

    def _data_selection_changed(self, *_args):
        return self._controller("_data_controller", DataController)._data_selection_changed(*_args)

    def _data_selection_finished(self, *_args):
        return self._controller("_data_controller", DataController)._data_selection_finished(*_args)

    def _point_keys(self):
        return self._controller("_data_controller", DataController)._point_keys()

    def _navigate_point(self, step):
        return self._controller("_data_controller", DataController)._navigate_point(step)

    def _refresh_point_editor(self):
        return self._controller("_data_controller", DataController)._refresh_point_editor()

    def _apply_point(self):
        return self._controller("_data_controller", DataController)._apply_point()

    def _delete_selected_canvas_points(self):
        return self._controller("_data_controller", DataController)._delete_selected_canvas_points()

    def _delete_points(self):
        return self._controller("_data_controller", DataController)._delete_points()

    def _clear_points(self):
        return self._controller("_data_controller", DataController)._clear_points()

    def _request_clean(self, mode):
        return self._controller("_data_controller", DataController)._request_clean(mode)

    def _open_sample_count_dialog(self, mode):
        return self._controller("_data_controller", DataController)._open_sample_count_dialog(mode)

    def _open_samples_dialog(self, mode='count'):
        return self._controller("_data_controller", DataController)._open_samples_dialog(mode)

    def _apply_sample_count(self, mode, before, target):
        return self._controller("_data_controller", DataController)._apply_sample_count(mode, before, target)

    def _increase_samples(self):
        return self._controller("_data_controller", DataController)._increase_samples()

    def _reduce_samples(self):
        return self._controller("_data_controller", DataController)._reduce_samples()

    def _simplify_samples(self):
        return self._controller("_data_controller", DataController)._simplify_samples()

    def _apply_sample_simplification(self, max_error):
        return self._controller("_data_controller", DataController)._apply_sample_simplification(max_error)

    def _smooth_curve(self):
        return self._controller("_data_controller", DataController)._smooth_curve()

    # ---------- canvas ----------
    def _install_mouse_handlers(self):
        return self._controller("_canvas_controller", CanvasController)._install_mouse_handlers()

    def _handle_key_event(self, event):
        key = QGlobalInputBinding.qtKeyForNative(event.key(), _renderer_backend())
        if key in (Qt.Key_Delete, Qt.Key_Escape) and self._edit_key(
                None, key=key, modifiers=event.modifiers()):
            return True
        return super()._handle_key_event(event)

    def _native_delete_snapshot(self):
        return self._controller("_canvas_controller", CanvasController)._native_delete_snapshot()

    def _poll_delete_key(self):
        return self._controller("_canvas_controller", CanvasController)._poll_delete_key()

    def _edit_key(self, _sender, _app_data=None, key=None, *, modifiers=None):
        return self._controller("_canvas_controller", CanvasController)._edit_key(_sender, _app_data, key, modifiers=modifiers)

    def _accepts_edit_shortcut(self, *, allow_editor=False):
        return self._controller("_canvas_controller", CanvasController)._accepts_edit_shortcut(allow_editor=allow_editor)

    def _focus_canvas_keyboard(self):
        return self._controller("_canvas_controller", CanvasController)._focus_canvas_keyboard()

    def _mouse_in_canvas(self):
        return self._controller("_canvas_controller", CanvasController)._mouse_in_canvas()

    def _canvas_rect(self):
        return self._controller("_canvas_controller", CanvasController)._canvas_rect()

    def _image_to_canvas(self, px, py):
        return self._controller("_canvas_controller", CanvasController)._image_to_canvas(px, py)

    def _canvas_to_image(self, mouse):
        return self._controller("_canvas_controller", CanvasController)._canvas_to_image(mouse)

    def _begin_pick(self, mode):
        return self._controller("_canvas_controller", CanvasController)._begin_pick(mode)

    def _cancel_pick(self):
        return self._controller("_canvas_controller", CanvasController)._cancel_pick()

    def _calibration_markers(self):
        return self._controller("_calibration_controller", CalibrationController)._calibration_markers()

    def _calibration_marker(self, key):
        return self._controller("_calibration_controller", CalibrationController)._calibration_marker(key)

    def _calibration_point_index(self, key):
        return self._controller("_calibration_controller", CalibrationController)._calibration_point_index(key)

    def _calibration_marker_label_key(self, key):
        return self._controller("_calibration_controller", CalibrationController)._calibration_marker_label_key(key)

    def _calibration_point_display_key(self, axis, index):
        return self._controller("_calibration_controller", CalibrationController)._calibration_point_display_key(axis, index)

    def _nearest_anchor(self, px, py):
        return self._controller("_calibration_controller", CalibrationController)._nearest_anchor(px, py)

    def _anchor_display_pixel(self, key):
        return self._controller("_calibration_controller", CalibrationController)._anchor_display_pixel(key)

    def _mouse_left(self, *_args):
        return self._controller("_calibration_controller", CalibrationController)._mouse_left(*_args)

    def _nearest_point(self, px, py):
        return self._controller("_calibration_controller", CalibrationController)._nearest_point(px, py)

    def _mouse_left_up(self, *_args):
        return self._controller("_calibration_controller", CalibrationController)._mouse_left_up(*_args)

    def _start_tick_calibration(self, rect, *, merge_region_history=False):
        return self._controller("_calibration_controller", CalibrationController)._start_tick_calibration(rect, merge_region_history=merge_region_history)

    def _region_aligned(self, rect):
        return self._controller("_calibration_controller", CalibrationController)._region_aligned(rect)

    def _tick_calibration_finished(self, detection, rect, error, *, region_revision=None):
        return self._controller("_calibration_controller", CalibrationController)._tick_calibration_finished(detection, rect, error, region_revision=region_revision)

    def _offer_manual_axis_bounds(self, axes=('x', 'y')):
        return self._controller("_calibration_controller", CalibrationController)._offer_manual_axis_bounds(axes)

    def _reveal_manual_axis_bounds(self, rect):
        return self._controller("_calibration_controller", CalibrationController)._reveal_manual_axis_bounds(rect)

    def _paint_detected_axis_ticks(self, painter):
        return self._controller("_calibration_controller", CalibrationController)._paint_detected_axis_ticks(painter)

    def _mouse_middle_down(self, *_args):
        return self._controller("_canvas_controller", CanvasController)._mouse_middle_down(*_args)

    def _mouse_middle_up(self, *_args):
        return self._controller("_canvas_controller", CanvasController)._mouse_middle_up(*_args)

    def _mouse_move(self, *_args):
        return self._controller("_canvas_controller", CanvasController)._mouse_move(*_args)

    def _canvas_pointer_tick(self):
        return self._controller("_canvas_controller", CanvasController)._canvas_pointer_tick()

    def _sync_canvas_cursor(self):
        return self._controller("_canvas_controller", CanvasController)._sync_canvas_cursor()

    def _mouse_wheel(self, _sender, app_data):
        return self._controller("_canvas_controller", CanvasController)._mouse_wheel(_sender, app_data)

    def _zoom_at(self, factor, mouse=None):
        return self._controller("_canvas_controller", CanvasController)._zoom_at(factor, mouse)

    def _fit_view(self):
        return self._controller("_canvas_controller", CanvasController)._fit_view()

    def _one_to_one(self):
        return self._controller("_canvas_controller", CanvasController)._one_to_one()

    def _paint_calibration_markers(self, painter, cw, ch):
        return self._controller("_canvas_controller", CanvasController)._paint_calibration_markers(painter, cw, ch)

    def _redraw(self):
        return self._controller("_canvas_controller", CanvasController)._redraw()

    def _paint_pointer(self):
        return self._controller("_canvas_controller", CanvasController)._paint_pointer()

    def _paint_preview(self, painter):
        return self._controller("_canvas_controller", CanvasController)._paint_preview(painter)

    def _load_texture(self, image=None):
        return self._controller("_canvas_controller", CanvasController)._load_texture(image)

    # ---------- file actions ----------
    def _file_picker(self, *, directory=False, save=False, extensions=(), callback=None, default_filename=''):
        return self._controller("_project_controller", ProjectController)._file_picker(directory=directory, save=save, extensions=extensions, callback=callback, default_filename=default_filename)

    def _choose_open_image(self):
        return self._controller("_project_controller", ProjectController)._choose_open_image()

    def _open_image(self, path):
        return self._controller("_project_controller", ProjectController)._open_image(path)

    def _choose_load_project(self):
        return self._controller("_project_controller", ProjectController)._choose_load_project()

    def _load_project(self, path):
        return self._controller("_project_controller", ProjectController)._load_project(path)

    def _choose_save_project(self):
        return self._controller("_project_controller", ProjectController)._choose_save_project()

    def _choose_save_project_as(self):
        return self._controller("_project_controller", ProjectController)._choose_save_project_as()

    def _save_project(self, path):
        return self._controller("_project_controller", ProjectController)._save_project(path)

    def _capture_project_view(self):
        return self._controller("_project_controller", ProjectController)._capture_project_view()

    def _project_frame(self):
        return self._controller("_project_controller", ProjectController)._project_frame()

    def _restore_project_view(self, state, generation, after_frame):
        return self._controller("_project_controller", ProjectController)._restore_project_view(state, generation, after_frame)

    def _restore_project_camera(self, state, generation, after_frame):
        return self._controller("_project_controller", ProjectController)._restore_project_camera(state, generation, after_frame)

    def _choose_export_csv(self):
        return self._controller("_project_controller", ProjectController)._choose_export_csv()

    def _export_csv(self, path):
        return self._controller("_project_controller", ProjectController)._export_csv(path)

    def _choose_export_excel(self):
        return self._controller("_project_controller", ProjectController)._choose_export_excel()

    def _export_excel(self, path):
        return self._controller("_project_controller", ProjectController)._export_excel(path)

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
        return self._controller("_canvas_controller", CanvasController)._layout_canvas()

    def _schedule_data_layout(self):
        return self._controller("_canvas_controller", CanvasController)._schedule_data_layout()

    def _layout_data_grid(self):
        return self._controller("_canvas_controller", CanvasController)._layout_data_grid()

    def _apply_layout(self):
        super()._apply_layout()
        if hasattr(self, "canvas"):
            self.view.after(0, self._layout_canvas)

    def layout_dialog(self):
        return self._controller("_canvas_controller", CanvasController).layout_dialog()

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
