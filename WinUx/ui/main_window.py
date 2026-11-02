from __future__ import annotations

import ctypes
import os
import sys
from collections import deque
from pathlib import PurePosixPath

from DearUIQt.runtime import QGuiRuntime

from .components import (
    ExplorerListView, FilePanel, apply_white_explorer_theme,
)
from DearUIQt.widgets import QDockWidget as DockWidget
from DearUIQt.core import Qt, QGlobalInputBinding, QItemInputBinding
from DearUIQt.layouts import QSplitterHandle, QHBoxLayout
from DearUIQt.widgets import (
    QMenuBar, QApplication, QFrame, QLabel, QSpacer,
    QMainWindow, QRetainedItem, QCanvas,
)
from ..platform.resources import resource_path
from ..preferences.general import GeneralPreferences
from ..controllers.callbacks import validate_callbacks
from .. import dialogs as _dialogs
from ..diagnostics import crash_guard, log_event, log_exception
from ..runtime import UiDispatcher
from ..runtime.paths import safe_current_directory
from .components.toolbar import (
    file_status_bar_theme, file_status_text_theme,
)
from DearUIQt.themes import (
    application_theme, compact_layout_surface_theme, floating_window_theme,
    splitter_hitbox_theme, splitter_theme,
)
from . import (
    ApplicationMenuMixin, CompactJobMonitorMixin, ConsoleDockingMixin,
    DialogFacadeMixin, PlotDockingMixin, PointerRoutingMixin,
    SplitterLayoutMixin, StartupDockingMixin, ViewLifecycleMixin,
)


def __getattr__(name):
    # Preserve view.LoginDialog/etc. for integrations without resolving every
    # dialog backend when the application only needs its main window.
    if name in _dialogs.__all__:
        return getattr(_dialogs, name)
    raise AttributeError(name)


_INPROCESS_DIALOG_TYPES = frozenset({
    # All DearUIQt/DPG application dialogs share the main QApplication event
    # loop. Server Notepad remains a standalone editor service rather than a
    # QDialog and is therefore intentionally outside this routing table.
    "BlockingDialog", "LoginDialog", "JobEditDialog", "JobManagerDialog",
    "LocalFolderDialog", "ServerPathDialog", "ProgressDialog",
    "ODBCheckDialog", "ODBExtractDialog", "ODBXYResultDialog",
    "SettingsDialog", "DiagnosticsDialog", "BookmarksDialog",
    "SiteManagerDialog", "SyncPreviewDialog", "JobScheduleDialog",
    "TransferCenterDialog",
})


def _use_inprocess_dialogs():
    """Use one QApplication/renderer event loop for dialogs by default.

    ``WINUX_DIALOG_PROCESS_HOSTS=1`` is the explicit legacy escape hatch for an
    installation that still needs process-isolated dialog hosts. The historical
    ``WINUX_INPROCESS_DIALOGS`` flag is still accepted, but now defaults on.
    """
    process_hosts = str(
        os.environ.get("WINUX_DIALOG_PROCESS_HOSTS", "0")
    ).strip().lower()
    if process_hosts not in {"0", "false", "off", "no", ""}:
        return False
    return str(
        os.environ.get("WINUX_INPROCESS_DIALOGS", "1")
    ).strip().lower() not in {"0", "false", "off", "no"}


def _dialog_type(name):
    # Tests/integrations can still override a constructor on this module. Normal
    # application dialogs resolve to in-process forms and therefore incur no
    # process spawn, IPC handshake or secondary render loop.
    override = globals().get(name)
    if override is not None:
        return override
    if name in _INPROCESS_DIALOG_TYPES:
        if _use_inprocess_dialogs():
            from ..dialogs import inprocess_adapters
            return getattr(inprocess_adapters, name)
        # Explicit compatibility mode only. Keeping this import here prevents
        # accidental process-host selection through the normal public API.
        from ..dialogs import floating_adapters
        return getattr(floating_adapters, name)
    return getattr(_dialogs, name)


class WinUXView(
        ViewLifecycleMixin, StartupDockingMixin, ApplicationMenuMixin,
        DialogFacadeMixin, CompactJobMonitorMixin, SplitterLayoutMixin,
        PlotDockingMixin, ConsoleDockingMixin, PointerRoutingMixin):
    # File/folder selectors share the QApplication/renderer event loop. With
    # DearUIQt native multi-window support they are owned HWNDs; otherwise they
    # are modal overlays in the main viewport. Neither path spawns a process.
    use_native_file_selectors = False
    WIDTH, HEIGHT = 850, 620
    COMPACT_JOB_WIDTH = 360
    COMPACT_JOB_HEIGHT = 130  # 27px header + four 25px rows + frame spacing.
    COMPACT_JOB_MARGIN = 0
    COMPACT_JOB_CORNER_RADIUS = 12  # Fallback only; Windows 11 uses native DWM corners.
    MIN_RESIZABLE_PANE_SIZE = 50
    MIN_PANEL_WIDTH = MIN_RESIZABLE_PANE_SIZE
    MIN_TOP_HEIGHT = MIN_RESIZABLE_PANE_SIZE
    MIN_BOTTOM_HEIGHT = MIN_RESIZABLE_PANE_SIZE
    # Job Plots use a QMainWindow-like dock area around Job Viewer.  Right is
    # the default, while Left/Top/Bottom are also available.  Each area keeps
    # its own 50/50 starting ratio and uses an orientation-correct splitter.
    PLOT_DOCK_DEFAULT_RATIO = 0.50
    MIN_JOB_VIEWER_WIDTH = MIN_RESIZABLE_PANE_SIZE
    MIN_PLOT_DOCK_WIDTH = MIN_RESIZABLE_PANE_SIZE
    MIN_JOB_VIEWER_DOCK_HEIGHT = MIN_RESIZABLE_PANE_SIZE
    MIN_PLOT_DOCK_HEIGHT = MIN_RESIZABLE_PANE_SIZE
    PLOT_DOCK_SEPARATOR_SIZE = 9
    CONSOLE_DOCK_DEFAULT_HEIGHT = 220
    CONSOLE_DOCK_DEFAULT_WIDTH = 320
    MIN_CONSOLE_DOCK_HEIGHT = MIN_RESIZABLE_PANE_SIZE
    MIN_CONSOLE_DOCK_WIDTH = MIN_RESIZABLE_PANE_SIZE
    CONSOLE_DOCK_SEPARATOR_SIZE = 1
    PLOT_DOCK_AREAS = ("left", "right", "top", "bottom")
    CONSOLE_DOCK_AREAS = ("left", "right", "top", "bottom")
    # Keep every visible divider hairline-thin, but make the pointer target much
    # larger than the painted handle, but reserve real space rather than
    # overlapping list rows/headers with invisible resize halos.
    SPLITTER_SIZE = 1
    # Dedicated File/Job Viewer gutter.  Unlike the other horizontal splitters,
    # this one sits immediately above the Job Viewer header, so it owns real
    # layout space instead of borrowing a large invisible halo from the header.
    FILE_JOB_SPLITTER_GUTTER_SIZE = 9
    # Local/Server uses the same real-gutter model as File/Job Viewer: the
    # visible divider stays 1 px, while a dedicated layout strip owns input.
    FILE_PANEL_SPLITTER_GUTTER_SIZE = 9
    # The Console divider also owns real layout space instead of an invisible
    # hit halo overlapping Job Viewer/Plots.
    CONSOLE_DOCK_SPLITTER_GUTTER_SIZE = 9
    # Compatibility constants only; workspace handles no longer borrow pane space.
    SPLITTER_HIT_PADDING = 10
    HORIZONTAL_SPLITTER_HIT_PADDING = 18
    # Compatibility value retained for older integrations; no longer used by
    # the Local/Server splitter implementation.
    FILE_PANEL_SPLITTER_HIT_PADDING = 6
    FILE_STATUS_HEIGHT = 20
    APP_PADDING = 2
    DOCK_SNAP_DISTANCE = 56

    @crash_guard("WinUXView initialization failed")
    def __init__(self, callbacks):
        self.callbacks = validate_callbacks(callbacks)
        self._general_preferences = GeneralPreferences()
        general_values = self._general_preferences.load()
        self._show_hidden_files = general_values['show_hidden_files']
        self._file_colors = general_values['file_colors']
        self._file_color_rules = general_values['file_color_rules']
        self._preserve_file_timestamps = general_values['preserve_file_timestamps']
        try:
            self._console_dock_visible = bool(
                self._general_preferences.load_console_visible())
        except Exception:
            self._console_dock_visible = False
        try:
            self._persisted_dock_state = self._general_preferences.load_dock_state()
        except Exception:
            self._persisted_dock_state = {}
        console_state = dict(self._persisted_dock_state.get("console") or {})
        plot_state = dict(self._persisted_dock_state.get("plot") or {})
        try:
            self._console_dock_height = max(self.MIN_CONSOLE_DOCK_HEIGHT, int(
                console_state.get("height", self.CONSOLE_DOCK_DEFAULT_HEIGHT)))
        except Exception:
            self._console_dock_height = self.CONSOLE_DOCK_DEFAULT_HEIGHT
        try:
            self._console_dock_width = max(self.MIN_CONSOLE_DOCK_WIDTH, int(
                console_state.get("width", self.CONSOLE_DOCK_DEFAULT_WIDTH)))
        except Exception:
            self._console_dock_width = self.CONSOLE_DOCK_DEFAULT_WIDTH
        self._console_dock_area = str(console_state.get("area") or "bottom").lower()
        if self._console_dock_area not in self.CONSOLE_DOCK_AREAS:
            self._console_dock_area = "bottom"
        self._console_dock_scope = (
            "outer" if str(console_state.get("scope") or "inner").lower() == "outer"
            else "inner")
        # An external terminal host may outlive the viewport geometry saved
        # in a previous session and appear as an empty independent window on
        # startup. Always initialize the console inside the main dock; explicit
        # Undock remains available after the main viewport is ready.
        self._console_dock_mode = "docked"
        self._plot_dock_scope = (
            "outer" if str(plot_state.get("scope") or "inner").lower() == "outer"
            else "inner")
        # Reference charts are application-level data, not Job Plot state.
        # Keep the handles on the main view so Reference -> Chart works even
        # before any job/ODB Plot dock has ever been opened.
        self._reference_chart_library = None
        self._reference_chart_dialog = None
        self._plot_digitizer_dialog = None
        # Process-isolated floating dialogs are expensive Abaqus children
        # (typically one SMALncMain + one SMAPython).  Do not keep hidden
        # dialog hosts resident after the user closes them: a hidden cache of
        # several dialogs looks like a process leak in Task Manager and holds
        # native runtime resources for no user-visible benefit.  One warm host
        # is still maintained by the prewarm pool for responsive reopening.
        self._dialog_resident_limit = 0
        # QDockWidget-style Console state.  Visibility is persisted separately
        # from docking mode: a visible Console may either occupy the bottom dock
        # site or live in a detachable floating tool window.
        self._console_float_window = None
        self._native_console_host = None
        self._native_plot_hosts = {}
        self._console_float_resizer = None
        self._console_float_geometry = {}
        self._console_float_last_position = None
        self._console_float_dragging = False
        self._console_float_mouse_was_down = False
        self._console_synthetic_float_drag = None
        self._console_dock_drag_requested = False
        self._console_dock_drag_owner = object()
        self._console_dock_drag_registry = None
        self._empty_plot_dock_drag_registry = None
        self._console_keyboard_panel = None
        self._console_native_hwnd = None
        self._main_viewport_hwnd = None
        self._console_native_old_wndproc = None
        self._console_native_wndproc_callback = None
        # Native RMB ownership for the embedded terminal.  The WNDPROC consumes
        # both down/up so Dear ImGui never enters a right-button ActiveId state
        # on the custom console draw-list.
        self._dispatcher = UiDispatcher()
        from ..runtime.frame_clock import AdaptiveFrameClock
        self._frame_clock = AdaptiveFrameClock()
        self._dispatcher.set_wake_callback(self._wake_ui_frame)
        # One logical QApplication owns focus/posted-event semantics for every
        # in-process QWidget/QDialog.  It reuses WinUx's dispatcher and creates
        # no worker thread or secondary render loop.
        application = QApplication.instance()
        self._qapplication = application or QApplication(after=self.after)
        self._watchdog = None
        # Callbacks that must run only after a rendered frame (most notably
        # actions accepted from a closing modal). Dear PyGui does not fully
        # release a modal until rendering advances, while after(0) is drained
        # immediately in the same UI iteration.
        self._render_generation = 0
        self._rendering = False
        # Targets are appended in monotonically non-decreasing render
        # generations. A deque lets each frame consume only callbacks that are
        # actually due instead of partitioning/copying the entire pending list.
        self._after_render_callbacks = deque()
        self._dpg_callbacks = deque()
        # Compatibility for integrations that inspect the old queue attribute.
        self._queue = self._dispatcher.queue
        self._alive = True
        # Compact Job Monitor reuses the main HWND instead of spawning another
        # UI process.  It is created lazily so ordinary launches pay no cost.
        self._compact_job_monitor_active = False
        self._compact_job_monitor = None
        self._compact_saved_window_rect = None
        self._compact_last_jobs = []
        self._compact_hover_polling = False
        # Per-frame interaction code touches many transient DPG items. A stale
        # item during resize/dock/rename must not tear down the whole render
        # loop. Track failures for rate-limited non-fatal logging.
        self._frame_step_errors = {}

        self._top_ratio = 0.66
        self._last_content_size = (0, 0)
        self._last_panel_divider = (
            self.WIDTH - self.FILE_PANEL_SPLITTER_GUTTER_SIZE) * 0.5
        # Until the user deliberately moves the Local/Server splitter, keep it
        # centred from the *actual* current client width.  Startup can render a
        # few small intermediate frames before the viewport reaches its final
        # size; persisting a clamped divider from one of those frames made the
        # left pane start much narrower than the right pane.
        self._file_panel_splitter_user_adjusted = False
        self._pending_viewport_size = None
        self._resize_last_event = 0.0
        # Native resize gets a lightweight layout at most ~30 Hz, followed by
        # one full child reflow after a short quiet period.  This feels much
        # smoother than freezing layout for 120 ms while also avoiding a full
        # ListView/plot relayout on every WM_SIZE event.
        self._resize_live_interval = 1.0 / 60.0
        self._resize_settle_delay = 0.075
        self._last_live_resize_layout = 0.0
        self._layout_dirty = True
        self._layout_updating = False
        self._splitter_cursor_active = False
        # Each splitter gesture owns a distinct global pointer token.  Dear
        # PyGui dispatches ListView mouse handlers globally, so without this
        # ownership a table/splitter resize can simultaneously start a file
        # drag/drop in the row under the pointer.
        self._file_panel_splitter_owner = object()
        self._horizontal_splitter_owner = object()
        self._plot_splitter_owner = object()
        self._console_splitter_owner = object()
        self._splitter_press_was_down = False
        self._file_panel_splitter_dragging = False
        self._file_panel_splitter_mouse_was_down = False
        self._file_panel_splitter_drag_start_divider = 0.0
        self._file_panel_splitter_drag_start_screen_x = None
        self._file_panel_splitter_drag_start_delta_x = 0.0
        self._file_panel_splitter_cursor_active = False
        self._horizontal_splitter_dragging = False
        self._horizontal_splitter_drag_offset = 0.0
        self._horizontal_splitter_mouse_adjustment = 0.0
        self._horizontal_splitter_mouse_was_down = False
        self._horizontal_splitter_drag_start_top = 0.0
        self._horizontal_splitter_drag_start_delta_y = 0.0
        self._horizontal_splitter_drag_start_screen_y = None
        # Last rendered File/Job workspace geometry.  Horizontal splitter drag
        # starts from these layout-relative values so mouse-down never snaps the
        # divider when root content has a top offset or a clamped split ratio.
        self._horizontal_splitter_live_top_height = None
        self._horizontal_splitter_live_workspace_size = None
        # QMainWindow-like dock state for the Plot tool.  Ratios are remembered
        # per dock area so moving Right -> Bottom -> Right restores the user's
        # previous split in each orientation instead of reusing an unrelated
        # width as a height.
        self._plot_dock_area = str(plot_state.get("area") or "right").lower()
        if self._plot_dock_area not in self.PLOT_DOCK_AREAS:
            self._plot_dock_area = "right"
        saved_ratios = dict(plot_state.get("split_ratios") or {})
        self._plot_split_ratios = {}
        for area in self.PLOT_DOCK_AREAS:
            try:
                ratio = float(saved_ratios.get(area, self.PLOT_DOCK_DEFAULT_RATIO))
            except Exception:
                ratio = self.PLOT_DOCK_DEFAULT_RATIO
            self._plot_split_ratios[area] = min(1.0, max(0.0, ratio))
        # Compatibility attribute retained for older integrations/tests.
        self._plot_split_ratio = self._plot_split_ratios[self._plot_dock_area]
        self._plot_default_mode = (
            "floating" if str(plot_state.get("mode") or "docked").lower() == "floating"
            else "docked")
        # Persist Plot visibility independently from its dock/floating mode,
        # mirroring the SSH Console contract.  The actual dock is restored only
        # after the first rendered frame so startup never constructs Plot UI on
        # the cold path unless the user left it visible in the previous session.
        self._plot_dock_visible = bool(plot_state.get("visible", False))
        saved_plot_geometry = plot_state.get("float_geometry") or {}
        self._plot_saved_float_geometry = (
            dict(saved_plot_geometry) if isinstance(saved_plot_geometry, dict) else {})
        self._plot_splitter_dragging = False
        self._plot_splitter_mouse_was_down = False
        self._plot_splitter_drag_start_width = 0.0
        self._plot_splitter_drag_start_height = 0.0
        self._plot_splitter_drag_start_delta_x = 0.0
        self._plot_splitter_drag_start_delta_y = 0.0
        self._plot_splitter_drag_start_screen_x = None
        self._plot_splitter_drag_start_screen_y = None
        self._plot_splitter_cursor_active = False
        self._console_splitter_dragging = False
        self._console_splitter_mouse_was_down = False
        self._console_splitter_drag_start_extent = 0.0
        self._console_splitter_drag_start_screen = None
        self._console_splitter_drag_start_delta = 0.0
        self._console_splitter_cursor_active = False
        self._plot_float_last_positions = {}
        # In-session equivalent of QMainWindow/QDockWidget geometry state.
        # Re-floating a dock restores its last detached size/position instead
        # of always jumping to a hard-coded 900x500 window.
        self._plot_float_geometries = {}
        self._plot_float_dragging = set()
        # Floating Qt-like tool windows disable Dear ImGui's built-in resize
        # grip and use border/corner hit-testing instead. One controller is
        # retained per detached Plot dock so all four corners (and edges) can
        # resize without the triangular lower-right grip.
        self._plot_float_resizers = {}
        # A dock/title tab tear-off begins in an embedded widget, so the new
        # top-level DPG window cannot inherit native OS drag capture. Track that
        # gesture explicitly and move the floating window under the cursor until
        # release, matching QDockWidget/QTabBar tear-off continuity.
        self._plot_synthetic_float_drag = {}
        self._plot_float_mouse_was_down = False
        self._native_resize_ns_cursor = None
        self._native_resize_ew_cursor = None
        self._native_resize_nwse_cursor = None
        self._native_resize_nesw_cursor = None
        self._native_arrow_cursor = None
        self._close_callback = None
        self._startup_layout_frames = 8
        self._components_destroyed = False

        self._gui_runtime = QGuiRuntime()
        self._gui_runtime.createContext(manual_callbacks=True)
        self._native_dialogs = False
        if (self._gui_runtime.supportsNativeWindows() and
                str(os.environ.get("WINUX_NATIVE_WINDOWS", "1")).strip().lower() not in {"0", "false", "off", "no"}):
            self._gui_runtime.enableNativeWindows()
            self._native_dialogs = True
            log_event("DearUIQt native reference/in-process tools enabled: shared process/context")
        # Native DPG registries require a live context. Installing this bridge
        # alongside the logical QApplication above crashes in handler_registry
        # with an access violation (not a catchable Python exception).
        # Run input callbacks on the UI thread: DPG's default callback worker
        # must not mutate/query the registry concurrently with native rendering.
        try:
            self._qapplication.installInputBackend(self._gui_runtime.backend)
        except Exception:
            # The centralized Qt-style input bridge improves focus routing but
            # is not required for rendering the application. If an older DPG
            # backend rejects one handler/key registration, keep WinUx alive;
            # widget-local handlers remain available as a degraded fallback.
            log_exception(
                "QApplication input bridge installation failed during startup",
                sys.exc_info(), fatal=False)
        activity_callback = self.callbacks.get("user_activity")
        self._qapplication.userActivity.connect(self._frame_clock.input)
        if callable(activity_callback):
            try:
                self._qapplication.userActivity.connect(activity_callback)
            except Exception:
                log_exception(
                    "QApplication user-activity hook failed during startup",
                    sys.exc_info(), fatal=False)
        # Process-host prewarming is legacy-only. The normal in-process path
        # constructs QDialogs directly on this application's GUI event loop and
        # therefore has no worker/socket pool to warm.
        if not _use_inprocess_dialogs():
            try:
                # Keep process-host modules completely out of normal startup.
                from ..dialogs.prewarm_pool import start_dialog_prewarm
                start_dialog_prewarm(self)
            except Exception:
                # Legacy prewarming is optional and never a startup dependency.
                # Any host failure falls back to a cold compatibility dialog.
                log_exception(
                    "Floating dialog prewarm failed during startup",
                    sys.exc_info(), fatal=False)
                self._dialog_host_pool = None
                self._dialog_prewarm_pool = None
        try:
            apply_white_explorer_theme()
        except Exception:
            # Dear ImGui's default palette is usable.  Keep WinUx alive if a
            # font/theme API is unavailable in an older bundled DPG runtime.
            log_exception(
                "Explorer theme warm-up failed during startup",
                sys.exc_info(), fatal=False)
        # Shared QMainWindow-style docking feedback is genuinely lazy.  Creating
        # a viewport-front draw-list before the first frame adds native registry
        # work to every launch even though most sessions never drag a dock.
        self._dock_drop_preview = None
        # The terminal font is only needed when the SSH Console is actually
        # opened.  Loading/registering a Windows font before the first viewport
        # frame adds native filesystem/font work to every cold start.
        self.terminal_font = None
        self._font_database = None

        # Zero-spacing shell layout is expressed through DearUIQt theme roles;
        # WinUx no longer depends on renderer style constants here.
        self._panel_layout_theme = compact_layout_surface_theme()

        # One application-wide Dear ImGui theme defines the Qt/Fusion state
        # palette for every control that does not own a more specific theme.
        # This keeps focus/hover/pressed visuals consistent across menu bars,
        # dock controls and ordinary widgets instead of falling back to the
        # stock Dear ImGui palette.
        self._app_theme = application_theme()

        # Detached dock chrome is owned by DearUIQt; renderer feature probes
        # (including optional title alignment) stay behind the theme boundary.
        self._floating_dock_window_theme = floating_window_theme()

        self.primary_window_tag = "winux_primary"
        with QMainWindow(
            "WinUX", width=self.WIDTH, height=self.HEIGHT,
            tag=self.primary_window_tag, no_scrollbar=True,
            no_scroll_with_mouse=True) as self._main_window:
            # Create the menu-bar surface first so it stays above the central
            # content, but populate actions only after QDockWidget ownership is
            # established (View -> Console reuses toggleViewAction()).
            self._menu_bar_wrapper = QMenuBar(
                parent=self._main_window, height=20)
            self.menu_bar = self._menu_bar_wrapper.tag

            # A single root child owns the complete content area. The top and
            # bottom regions are positioned absolutely inside this root instead
            # of being stacked by Dear PyGui. This prevents a 1-2 px DPI/menu
            # rounding error from increasing the primary window content height
            # and permanently showing its vertical scrollbar.
            self._layout_root_frame = QFrame(
                parent=self._main_window, width=-1, height=-1, frame_shape=QFrame.NoFrame,
                no_scrollbar=True, no_scroll_with_mouse=True,
            )
            self.layout_root = self._layout_root_frame.tag

            # Local/Server panes are positioned around a real vertical gutter.
            # The gutter is layout space, not an invisible halo over either
            # ListView, matching the QSplitter behavior used elsewhere.
            self._top_region_frame = QFrame(
                parent=self._layout_root_frame, pos=(0, 0), width=-1, height=476,
                frame_shape=QFrame.NoFrame, no_scrollbar=True,
                no_scroll_with_mouse=True,
            )
            self.top_region = self._top_region_frame.tag
            # Compatibility marker for code that still inspects the historical
            # table attribute; it no longer participates in layout.
            self._file_panels_compat_layout = QHBoxLayout(
                parent=self._top_region_frame, show=False)
            self.file_panels_table = self._file_panels_compat_layout.tag
            self._left_parent_frame = QFrame(
                parent=self._top_region_frame, pos=(0, 0), width=400, height=476,
                frame_shape=QFrame.NoFrame, no_scrollbar=True,
                no_scroll_with_mouse=True,
            )
            self.left_parent = self._left_parent_frame.tag
            self._right_parent_frame = QFrame(
                parent=self._top_region_frame, pos=(409, 0), width=400, height=476,
                frame_shape=QFrame.NoFrame, no_scrollbar=True,
                no_scroll_with_mouse=True,
            )
            self.right_parent = self._right_parent_frame.tag
            self._file_panel_splitter_handle = QSplitterHandle(
                Qt.Horizontal, parent=self.top_region,
                handle_width=self.FILE_PANEL_SPLITTER_GUTTER_SIZE,
                line_width=self.SPLITTER_SIZE)
            self._file_panel_splitter_handle.setGeometry(
                400, 0, self.FILE_PANEL_SPLITTER_GUTTER_SIZE, 476)
            self.file_panel_separator = self._file_panel_splitter_handle.lineTag()
            self.file_panel_separator_hitbox = self._file_panel_splitter_handle.hitBoxTag()

            # Status text is owned by one fixed strip below both file lists.
            # Panels therefore do not create status children inside their own
            # resizable containers.
            initial_local_path = safe_current_directory()
            self.left = FilePanel(
                self.left_parent, "local", callbacks,
                current_path=initial_local_path,
                initial_path_label=str(initial_local_path),
                has_status=False,
                show_hidden_files=self._show_hidden_files,
                file_colors=self._file_colors,
                file_color_rules=self._file_color_rules,
            )
            self.right = FilePanel(
                self.right_parent, "server", callbacks,
                current_path=PurePosixPath("/"),
                initial_path_label="Log-in", has_status=False,
                show_hidden_files=self._show_hidden_files,
                file_colors=self._file_colors,
                file_color_rules=self._file_color_rules,
            )
            self.panels = [self.left, self.right]

            self._file_status_frame = QFrame(
                parent=self._layout_root_frame, pos=(0, 476), width=-1,
                height=self.FILE_STATUS_HEIGHT, frame_shape=QFrame.NoFrame,
                no_scrollbar=True, no_scroll_with_mouse=True,
            )
            self.file_status_region = self._file_status_frame.tag
            # Use two absolutely positioned status children instead of a
            # second independent table. Their divider is updated from the real
            # Local/Server panel widths, so the Server text never drifts when
            # the upper table divider is resized.
            self._left_status_frame = QFrame(
                parent=self._file_status_frame, pos=(0, 0), width=500,
                height=self.FILE_STATUS_HEIGHT, frame_shape=QFrame.NoFrame,
                no_scrollbar=True, no_scroll_with_mouse=True,
            )
            self.left_status_window = self._left_status_frame.tag
            self._right_status_frame = QFrame(
                parent=self._file_status_frame, pos=(500, 0), width=500,
                height=self.FILE_STATUS_HEIGHT, frame_shape=QFrame.NoFrame,
                no_scrollbar=True, no_scroll_with_mouse=True,
            )
            self.right_status_window = self._right_status_frame.tag
            self._file_status_frame.setTheme(file_status_bar_theme())
            self._left_status_frame.setTheme(file_status_bar_theme())
            self._right_status_frame.setTheme(file_status_bar_theme())

            self._left_status_layout = QHBoxLayout(parent=self._left_status_frame, spacing=0)
            self._left_status_padding = QSpacer(2, 14, parent=self._left_status_layout)
            self._left_items_label = QLabel("0 items", parent=self._left_status_layout)
            left_items = self._left_items_label.tag
            self._left_items_label.setTheme(file_status_text_theme())
            self._left_status_spacer = QSpacer(8, 14, parent=self._left_status_layout)
            self._left_selected_label = QLabel("0 selected", parent=self._left_status_layout)
            left_selected = self._left_selected_label.tag
            self._left_selected_label.setTheme(file_status_text_theme(muted=True))

            self._right_status_layout = QHBoxLayout(parent=self._right_status_frame, spacing=0)
            self._right_status_padding = QSpacer(2, 14, parent=self._right_status_layout)
            self._server_connection_canvas = QCanvas(
                14, self.FILE_STATUS_HEIGHT, parent=self._right_status_layout)
            self._server_connection_dot = self._server_connection_canvas.painter().drawEllipse(
                (6, 10), 4, color=(190, 45, 45, 255), fill=(210, 55, 55, 255))
            self._server_connection_dot_center = (6, 10)
            self._server_connection_alignment_pending = False
            self._server_connection_state = False
            self._right_items_label = QLabel("Not connected", parent=self._right_status_layout)
            right_items = self._right_items_label.tag
            self._right_items_label.setTheme(file_status_text_theme())
            from DearUIQt.tooltip import add_styled_tooltip
            self._server_connection_tooltip = add_styled_tooltip(
                right_items, 'SSH connection\nGreen: connected\nRed: disconnected')
            self._server_connection_alignment_binding = (
                QItemInputBinding(right_items, parent=self._main_window)
                .onResize(self._queue_server_connection_alignment).activate())
            self._queue_server_connection_alignment()
            self._right_status_spacer = QSpacer(8, 14, parent=self._right_status_layout)
            self._right_selected_label = QLabel("0 selected", parent=self._right_status_layout)
            right_selected = self._right_selected_label.tag
            self._right_selected_label.setTheme(file_status_text_theme(muted=True))
            self.left.attach_external_status(left_items, left_selected)
            self.right.attach_external_status(right_items, right_selected)

            self._bottom_region_frame = QFrame(
                parent=self._layout_root_frame, pos=(0, 508), width=-1, height=-1,
                frame_shape=QFrame.NoFrame, no_scrollbar=True,
                no_scroll_with_mouse=True,
            )
            self.bottom_region = self._bottom_region_frame.tag
            # Job Viewer is substantial (table, handlers, menus, themes).  Keep
            # only its parent shell on the cold-start path and build the viewer
            # after the first rendered frame.  Public methods call
            # _ensure_jobs_view() so external behaviour remains synchronous.
            self.jobs_view = None
            self.job_plot_windows = {}
            self.job_plot_float_windows = {}
            self._empty_job_plot_window = None
            self._plot_dock_open = False

            # Realtime Job Plots share the lower work area with Job Viewer in
            # any Qt-like Left/Right/Top/Bottom dock area. The thin separator
            # changes orientation with the active area and keeps a larger
            # transparent hitbox so it remains easy to drag.
            # Create the plot content first and the splitter controls after it
            # so the transparent grab strip stays above both lower panes.
            self._plot_region_frame = QFrame(
                parent=self._layout_root_frame, pos=(0, 0), width=1, height=1,
                frame_shape=QFrame.NoFrame, no_scrollbar=True,
                no_scroll_with_mouse=True, show=False,
            )
            self.plot_region = self._plot_region_frame.tag
            self._plot_region_frame.setTheme(self._panel_layout_theme)
            # DockManager is needed only after the first Job Plot is opened.
            # Deferring it avoids constructing tab/dock infrastructure during
            # ordinary launches that never use realtime plots.
            self.plot_dock_manager = None

            # SSH Console is an embedded QDockWidget-style tool panel.  It can
            # dock on all four sides of the shared Job Viewer / Plots workspace
            # and starts hidden on a fresh profile. Visibility is restored from
            # the per-user settings document on subsequent launches.
            self._console_region_frame = QFrame(
                parent=self._layout_root_frame, pos=(0, 0), width=1, height=1,
                frame_shape=QFrame.NoFrame, no_scrollbar=True,
                no_scroll_with_mouse=True, show=(
                    self._console_dock_visible and self._console_dock_mode == "docked"),
            )
            self.console_region = self._console_region_frame.tag
            self._console_region_frame.setTheme(self._panel_layout_theme)
            self.console_dock = DockWidget(
                self.console_region,
                "SSH Console",
                "winux_ssh_console_dock",
                on_float_change=self._console_float_requested,
                on_close=self.hide_console,
                features=DockWidget.AllDockWidgetFeatures,
                dock_area=self._console_dock_area,
                allowed_areas=(DockWidget.LeftDockWidgetArea
                               | DockWidget.RightDockWidgetArea
                               | DockWidget.TopDockWidgetArea
                               | DockWidget.BottomDockWidgetArea),
                on_visibility_change=lambda visible: self.set_console_visible(
                    visible, persist=True, request_login=bool(visible)),
                visible=self._console_dock_visible,
            )
            # Construct the terminal widget only when it is visible.  A fresh
            # profile keeps Console hidden, so importing/building the custom
            # terminal before the first frame only increases startup latency.
            self.console_panel = None
            if self._console_dock_visible:
                self._ensure_console_panel()
            self._build_menu()
            # QDockWidget title dragging is a host operation because the live
            # dock root must be reparented into a top-level tool window.  Keep
            # the handler global (as DPG requires for mouse drag/release) but
            # start a tear-off only while the Console title handle owns the
            # press.
            self._console_dock_drag_registry = (
                QGlobalInputBinding(parent=self._qapplication)
                .onMouseDrag(
                    Qt.LeftButton, self._on_console_dock_header_drag, threshold=8.0)
                .onMouseRelease(
                    Qt.LeftButton, self._on_console_dock_header_drag_release)
                .activate()
            )
            # The empty View->Plots placeholder is not registered in
            # DockManager, so give its QDockWidget title the same global drag
            # threshold/release path used by SSH Console. Real Job Plots remain
            # owned by DockManager to avoid duplicate drag handling.
            self._empty_plot_dock_drag_registry = (
                QGlobalInputBinding(parent=self._qapplication)
                .onMouseDrag(
                    Qt.LeftButton, self._on_empty_plot_dock_header_drag, threshold=8.0)
                .onMouseRelease(
                    Qt.LeftButton, self._on_empty_plot_dock_header_drag_release)
                .activate()
            )
            self._console_splitter_handle = QSplitterHandle(
                Qt.Vertical, parent=self.layout_root,
                handle_width=self.CONSOLE_DOCK_SPLITTER_GUTTER_SIZE,
                line_width=self.CONSOLE_DOCK_SEPARATOR_SIZE,
                visible=(self._console_dock_visible and self._console_dock_mode == "docked"))
            self.console_separator = self._console_splitter_handle.lineTag()
            self.console_separator_hitbox = self._console_splitter_handle.hitBoxTag()
            self._job_plot_splitter_handle = QSplitterHandle(
                Qt.Horizontal, parent=self.layout_root,
                handle_width=self.PLOT_DOCK_SEPARATOR_SIZE,
                line_width=self.SPLITTER_SIZE, visible=False)
            self.job_plot_separator = self._job_plot_splitter_handle.lineTag()
            self.job_plot_separator_hitbox = self._job_plot_splitter_handle.hitBoxTag()

            # File/Job Viewer splitter gets its own real gutter instead of
            # overlapping the Job Viewer header with an invisible 37px halo.
            # The visible line stays 1px, centred in the gutter; the entire
            # gutter is an easy-to-grab resize surface.
            splitter_gutter_y = 500
            splitter_line_y = (
                splitter_gutter_y
                + (self.FILE_JOB_SPLITTER_GUTTER_SIZE - self.SPLITTER_SIZE) // 2
            )
            self._horizontal_splitter_handle = QSplitterHandle(
                Qt.Vertical, parent=self.layout_root,
                handle_width=self.FILE_JOB_SPLITTER_GUTTER_SIZE,
                line_width=self.SPLITTER_SIZE)
            # The first dynamic layout pass will replace this geometry.
            self._horizontal_splitter_handle.setGeometry(
                0, splitter_gutter_y, -1, self.FILE_JOB_SPLITTER_GUTTER_SIZE)
            self.horizontal_splitter = self._horizontal_splitter_handle.lineTag()
            self.horizontal_splitter_hitbox = self._horizontal_splitter_handle.hitBoxTag()
            self._horizontal_splitter_handlers = (
                QItemInputBinding(
                    self.horizontal_splitter_hitbox, parent=self._main_window)
                .onClick(Qt.LeftButton, self._on_horizontal_splitter_pressed)
                .activate()
            )
            # Retain the old attribute for callers created against earlier
            # builds while using the orientation-correct name internally.
            self.vertical_splitter = self.horizontal_splitter
            # Shared QSplitter chrome: one painted pixel and a separate
            # transparent grab gutter.  Hover/drag feedback changes only the
            # line colour, never the layout thickness.
            self._splitter_theme = splitter_theme(active=False)
            self._plot_splitter_hover_theme = splitter_theme(active=True)
            for item in (self.horizontal_splitter, self.file_panel_separator,
                         self.job_plot_separator, self.console_separator):
                QRetainedItem(item).setTheme(self._splitter_theme)
            self._splitter_hitbox_theme = splitter_hitbox_theme()
            for hitbox in (self.horizontal_splitter_hitbox,
                           self.file_panel_separator_hitbox,
                           self.job_plot_separator_hitbox,
                           self.console_separator_hitbox):
                QRetainedItem(hitbox).setTheme(self._splitter_hitbox_theme)

            # Dock feedback is rendered by the shared viewport-front
            # DockDropPreview.  Keep compatibility attributes for integrations
            # that inspect the former per-panel drawlists.
            self.plot_dock_preview = None
            self._plot_dock_preview_rect = None
            self.console_dock_preview = None
            self._console_dock_preview_rect = None
            # Splitter input is polled exactly once per application frame.
            # Explorer ListViews already own global mouse registries; adding a
            # second drag callback here caused duplicate full layout passes.

        # ItemSpacing is evaluated on the parent that lays out its children.
        # Therefore the zero-spacing theme must also be bound to the primary
        # window; binding it only to the child windows does not remove the gap
        # between top_region and bottom_region. That hidden gap was enough to
        # overflow the content region and show the right-side scrollbar.
        for item in (
            self.layout_root,
            self.top_region,
            self.file_panels_table,
            self.left_parent,
            self.right_parent,
            self.file_status_region,
            self.left_status_window,
            self.right_status_window,
            self.bottom_region,
            self.plot_region,
            self.console_region,
        ):
            QRetainedItem(item).setTheme(self._panel_layout_theme)
        self._main_window.setTheme(self._app_theme)

        # Do not let the native X button terminate the render loop before the
        # controller has shown and resolved a pending-schedule warning.
        viewport_options = {
            "title": "WinUX",
            "width": self.WIDTH,
            "height": self.HEIGHT,
            "disable_close": True,
        }
        # Dear PyGui accepts ICO paths for the native Windows title-bar and
        # taskbar icons. Keep a compatibility fallback for older DPG builds.
        app_icon = resource_path("WinUx.ico")
        if app_icon.is_file():
            viewport_options.update(
                small_icon=str(app_icon),
                large_icon=str(app_icon),
            )
        try:
            self._gui_runtime.createViewport(**viewport_options)
        except TypeError:
            viewport_options.pop("small_icon", None)
            viewport_options.pop("large_icon", None)
            self._gui_runtime.createViewport(**viewport_options)
        self._gui_runtime.setup()
        self._gui_runtime.setPrimaryWindow("winux_primary", True)
        self._gui_runtime.setExitCallback(self._request_close)
        self._gui_runtime.setViewportResizeCallback(self._on_viewport_resize)
        ExplorerListView._external_cursor_provider = (
            self._splitter_native_cursor_provider)

        # Keep diagnostics and secondary work out of the first-frame path.
        # They are attached immediately after the first rendered frame so the
        # native window can become visible before any extra thread/table setup.
        self.after_render(self._finish_deferred_startup)

        # Reference Chart and Plot Digitizer are retained after first use, but
        # they are no longer constructed before the main viewport appears.
        # Their normal menu routes already create them lazily, which removes
        # two large native tool trees from the cold-start critical path.
        # Create tool widget trees only on first use. Hidden speculative
        # Settings/Diagnostics/Transfer Center trees still own native items,
        # themes and timers for the entire session even when never opened.
        # The normal menu paths already retain/reuse tools after first use.
        # Warm Python dialog classes only after the main viewport is usable.
        # One import is resolved per GUI turn so first-click latency is paid
        # during idle time without a startup import burst or extra thread/process.
        self.after(1450, self._prewarm_inprocess_dialog_imports)


    def display_server_directory(
            self, path, items, host, reset_history=False, record_history=True, **kwargs):
        self.set_server_connection_state(True)
        same_directory = (not reset_history
                          and path == self.right.current_path
                          and str(host) == self.right.status_prefix)
        if reset_history:
            self.right.history = []
            self.right.history_index = -1
        self.right.status_prefix = str(host)
        if same_directory:
            self.right.refresh_directory(path, items)
            # A no-op snapshot must also replace the navigation "Loading..."
            # message without touching rows, selection or the scroll owner.
            if self.right.has_status:
                self.right._update_item_status()
        else:
            self.right.display(path, items, record_history=record_history)

    def display_jobs(self, jobs):
        jobs = list(jobs or ())
        self._compact_last_jobs = jobs
        compact = getattr(self, "_compact_job_monitor", None)
        if getattr(self, "_compact_job_monitor_active", False):
            if compact is None:
                compact = self._ensure_compact_job_monitor()
            compact.display(jobs)
        else:
            self._ensure_jobs_view().display(jobs)
            if compact is not None:
                compact.display(jobs)
        dialog = getattr(self, "job_manager_dialog", None)
        if dialog is not None:
            dialog.job_view_updated(jobs)

    def display_job_poll_error(self, error):
        dialog = getattr(self, "job_manager_dialog", None)
        if dialog is not None:
            callback = getattr(dialog, "job_view_failed", None)
            if callable(callback):
                callback(error)

    def selected_job_values(self):
        if self._compact_job_monitor_active and self._compact_job_monitor is not None:
            return self._compact_job_monitor.selected_values()
        return self._ensure_jobs_view().selected_values()

    def clear_job_selection(self):
        self._ensure_jobs_view().clear_selection()


