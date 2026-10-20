from __future__ import annotations

import ctypes
import os
import sys
import time
from collections import deque
from ctypes import wintypes
from pathlib import Path, PurePosixPath

from DearUIQt.runtime import QGuiRuntime

from .ui.components import (
    ExplorerListView, FilePanel, JobsView, ResourceTextures,
    apply_white_explorer_theme, reset_component_runtime_resources,
)
from DearUIQt.widgets import DockDropPreview, DockManager, QDockWidget as DockWidget
from DearUIQt.core import Qt, QGlobalInputBinding, QItemInputBinding
from DearUIQt.layouts import QSplitterHandle, QHBoxLayout
from DearUIQt.gui import QAction, QFontDatabase
from DearUIQt.widgets import (
    QMenuBar, QApplication, QFrame, QLabel, QSpacer, QToolButton,
    QMainWindow, QRetainedItem, QImageView,
)
from .resources import resource_path
from .preferences.general import GeneralPreferences
from .dialogs.console_form import ConsoleDockPanel
from .controllers import validate_callbacks
from . import dialogs as _dialogs
from .diagnostics import crash_guard, log_event, log_exception
from .runtime import UIHangWatchdog, UiDispatcher
from .runtime.paths import safe_current_directory
from .runtime.dpg_callbacks import invoke_callback_job
from .ui.components.toolbar import (
    file_status_bar_theme, file_status_text_theme, resource_menu_theme,
)
from DearUIQt.themes import (
    application_theme, compact_layout_surface_theme, floating_window_theme,
    splitter_hitbox_theme, splitter_theme,
)
from .ui import (
    ConsoleDockingMixin, PlotDockingMixin, PointerRoutingMixin,
    SplitterLayoutMixin,
)
from DearUIQt.input_gate import (
    native_background_input_blocked, release_pointer_input,
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
            from .dialogs import inprocess_adapters
            return getattr(inprocess_adapters, name)
        # Explicit compatibility mode only. Keeping this import here prevents
        # accidental process-host selection through the normal public API.
        from .dialogs import floating_adapters
        return getattr(floating_adapters, name)
    return getattr(_dialogs, name)



class WinUXView(
        SplitterLayoutMixin, PlotDockingMixin, ConsoleDockingMixin,
        PointerRoutingMixin):
    # File/folder selectors share the QApplication/renderer event loop. With
    # DearUIQt native multi-window support they are owned HWNDs; otherwise they
    # are modal overlays in the main viewport. Neither path spawns a process.
    use_native_file_selectors = False
    WIDTH, HEIGHT = 850, 620
    MIN_PANEL_WIDTH = 260
    MIN_TOP_HEIGHT = 260
    MIN_BOTTOM_HEIGHT = 150
    # Job Plots use a QMainWindow-like dock area around Job Viewer.  Right is
    # the default, while Left/Top/Bottom are also available.  Each area keeps
    # its own 50/50 starting ratio and uses an orientation-correct splitter.
    PLOT_DOCK_DEFAULT_RATIO = 0.50
    MIN_JOB_VIEWER_WIDTH = 300
    MIN_PLOT_DOCK_WIDTH = 360
    MIN_JOB_VIEWER_DOCK_HEIGHT = 120
    MIN_PLOT_DOCK_HEIGHT = 180
    PLOT_DOCK_SEPARATOR_SIZE = 9
    CONSOLE_DOCK_DEFAULT_HEIGHT = 220
    MIN_CONSOLE_DOCK_HEIGHT = 150
    CONSOLE_DOCK_SEPARATOR_SIZE = 1
    PLOT_DOCK_AREAS = ("left", "right", "top", "bottom")
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
        self._show_hidden_files = self._general_preferences.load_show_hidden_files()
        try:
            self._console_dock_visible = bool(
                self._general_preferences.load_console_visible())
        except Exception:
            self._console_dock_visible = False
        self._console_dock_height = self.CONSOLE_DOCK_DEFAULT_HEIGHT
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
        self._console_dock_mode = "docked"
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
        self._console_keyboard_panel = None
        self._console_native_hwnd = None
        self._main_viewport_hwnd = None
        self._console_native_old_wndproc = None
        self._console_native_wndproc_callback = None
        # Native RMB ownership for the embedded terminal.  The WNDPROC consumes
        # both down/up so Dear ImGui never enters a right-button ActiveId state
        # on the custom console draw-list.
        self._dispatcher = UiDispatcher()
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
        self._resize_settle_delay = 0.12
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
        # QMainWindow-like dock state for the Plot tool.  Ratios are remembered
        # per dock area so moving Right -> Bottom -> Right restores the user's
        # previous split in each orientation instead of reusing an unrelated
        # width as a height.
        self._plot_dock_area = "right"
        self._plot_split_ratios = {
            area: self.PLOT_DOCK_DEFAULT_RATIO for area in self.PLOT_DOCK_AREAS
        }
        # Compatibility attribute retained for older integrations/tests.
        self._plot_split_ratio = self.PLOT_DOCK_DEFAULT_RATIO
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
        self._console_splitter_drag_start_height = 0.0
        self._console_splitter_drag_start_screen_y = None
        self._console_splitter_drag_start_delta_y = 0.0
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
                from .dialogs.prewarm_pool import start_dialog_prewarm
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
        # Shared QMainWindow-style docking feedback.  It is built lazily on the
        # first real drag so the native viewport already exists.  A viewport-
        # front drawlist guarantees that sibling child windows cannot cover the
        # preview rectangle.
        try:
            self._dock_drop_preview = DockDropPreview()
        except Exception:
            # Dock-drop highlighting is cosmetic.  Older/native DPG builds can
            # reject a viewport draw-list during early construction; keep the
            # app usable and simply omit the preview for this session.
            self._dock_drop_preview = None
            log_exception(
                "Dock drop preview initialization failed during startup",
                sys.exc_info(), fatal=False)
        self.terminal_font = None
        self._font_database = None
        try:
            terminal_path = (
                Path(os.environ.get("WINDIR", "C:/Windows"))
                / "Fonts" / "consola.ttf")
            if terminal_path.is_file():
                self._font_database = QFontDatabase(parent=self._qapplication)
                self.terminal_font = self._font_database.addApplicationFont(
                    terminal_path, 14)
        except Exception:
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
            )
            self.right = FilePanel(
                self.right_parent, "server", callbacks,
                current_path=PurePosixPath("/"),
                initial_path_label="Log-in", has_status=False,
                show_hidden_files=self._show_hidden_files,
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
            self._left_items_label = QLabel("0 items", parent=self._left_status_layout)
            left_items = self._left_items_label.tag
            self._left_items_label.setTheme(file_status_text_theme())
            self._left_status_spacer = QSpacer(8, 14, parent=self._left_status_layout)
            self._left_selected_label = QLabel("0 selected", parent=self._left_status_layout)
            left_selected = self._left_selected_label.tag
            self._left_selected_label.setTheme(file_status_text_theme(muted=True))

            self._right_status_layout = QHBoxLayout(parent=self._right_status_frame, spacing=0)
            self._right_items_label = QLabel("Not connected", parent=self._right_status_layout)
            right_items = self._right_items_label.tag
            self._right_items_label.setTheme(file_status_text_theme())
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
            self.jobs_view = JobsView(self.bottom_region, callbacks)
            self.job_plot_windows = {}
            self.job_plot_float_windows = {}
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
            self.plot_dock_manager = DockManager(
                self.plot_region,
                dock_area=self._plot_dock_area,
                tab_position="bottom",
                on_active_changed=self._job_plot_tab_activated,
                on_tab_tearoff=self._job_plot_tab_tearoff,
            )

            # SSH Console is an embedded QDockWidget-style tool panel.  It is
            # always docked below the shared Job Viewer / Plots workspace and
            # starts hidden on a fresh profile.  Visibility is restored from
            # the per-user settings document on subsequent launches.
            self._console_region_frame = QFrame(
                parent=self._layout_root_frame, pos=(0, 0), width=1, height=1,
                frame_shape=QFrame.NoFrame, no_scrollbar=True,
                no_scroll_with_mouse=True, show=self._console_dock_visible,
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
                dock_area="bottom",
                allowed_areas=DockWidget.BottomDockWidgetArea,
                on_visibility_change=lambda visible: self.set_console_visible(
                    visible, persist=True, request_login=bool(visible)),
                visible=self._console_dock_visible,
            )
            self.console_panel = ConsoleDockPanel(
                self, self.console_dock.content,
                self.callbacks["console_output"],
                self.callbacks["console_command"],
                self.callbacks["console_interrupt"],
                lambda message: self.after(
                    0, self.show_error, "SSH Console", message),
                completion_callback=self.callbacks.get("console_complete"),
                completion_list_callback=self.callbacks.get("console_completion_list"),
            )
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
            self._console_splitter_handle = QSplitterHandle(
                Qt.Vertical, parent=self.layout_root,
                handle_width=self.CONSOLE_DOCK_SPLITTER_GUTTER_SIZE,
                line_width=self.CONSOLE_DOCK_SEPARATOR_SIZE,
                visible=self._console_dock_visible)
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

        # Start hang detection only after native/Dear PyGui construction has
        # completed.  It is diagnostics only: thread creation/security-policy
        # failures must never prevent the main viewport from opening.
        try:
            self._watchdog = UIHangWatchdog()
            self._watchdog.add_snapshot_provider(
                "ui_dispatcher", self._dispatcher.snapshot)
        except Exception:
            self._watchdog = None
            log_exception(
                "UI hang watchdog could not start",
                sys.exc_info(), fatal=False)

        # One explicitly retained native transfer window, prepared after the
        # main UI is usable. No filesystem/network enumeration is performed.
        if self._native_dialogs:
            # Build the two reference tools hidden before the main viewport is
            # exposed. Menu clicks then only show retained native widgets.
            try:
                self._prepare_native_reference_tools()
            except Exception:
                # Optional tool preparation must not prevent the file/job
                # workspace from opening. Its normal menu route can retry.
                log_exception("Native reference tool preparation failed during startup", sys.exc_info(), fatal=False)
        self.after(1200, self._prewarm_transfer_center)
        # Warm Python dialog classes only after the main viewport is usable.
        # One import is resolved per GUI turn so first-click latency is paid
        # during idle time without a startup import burst or extra thread/process.
        self.after(1450, self._prewarm_inprocess_dialog_imports)
        self.after(1750, self._prewarm_retained_dialog_shells)

    def _prepare_native_reference_tools(self):
        from .dialogs.native_reference_tools import ReferenceChartDialog, PlotDigitizerDialog
        library = PlotDockingMixin._get_reference_chart_library(self)
        # Preconstruct only the bounded empty editor shell. Restoring a saved
        # dataset belongs to its menu session, never the main-window constructor.
        self._reference_chart_dialog = ReferenceChartDialog(self, [], lambda _result: None)
        self._reference_chart_dialog.hide()
        self._plot_digitizer_dialog = PlotDigitizerDialog(self, reference_library=library)
        self._plot_digitizer_dialog.hide()


    def _find_main_viewport_hwnd(self):
        """Resolve the Dear PyGui/GLFW main HWND without depending on a child view.

        The old implementation delegated to ``left.listview``.  That made the
        Console RMB/WM_CHAR hook disappear whenever the Explorer pane had not
        finished constructing (or its HWND helper temporarily returned 0).
        Resolve the process top-level window directly as a fallback and cache
        only handles that Windows still reports as valid.
        """
        if os.name != "nt":
            return None
        try:
            user32 = ctypes.windll.user32
            cached = int(getattr(self, "_main_viewport_hwnd", 0) or 0)
            if cached and user32.IsWindow(wintypes.HWND(cached)):
                return cached
        except Exception:
            pass

        # Keep the existing component-specific finder as the first fast path.
        try:
            listview = getattr(getattr(self, "left", None), "listview", None)
            finder = getattr(listview, "_find_own_top_level_hwnd", None)
            if callable(finder):
                hwnd = int(finder() or 0)
                if hwnd:
                    self._main_viewport_hwnd = hwnd
                    return hwnd
        except Exception:
            pass

        # Independent fallback: enumerate visible top-level windows owned by
        # this process.  Prefer the exact WinUX viewport title, then any
        # ownerless process window.  This works even before FilePanel/ListView
        # has reached its first stable layout frame.
        try:
            user32 = ctypes.windll.user32
            kernel32 = ctypes.windll.kernel32
            user32.IsWindowVisible.argtypes = [wintypes.HWND]
            user32.IsWindowVisible.restype = wintypes.BOOL
            user32.GetWindowThreadProcessId.argtypes = [
                wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
            user32.GetWindowThreadProcessId.restype = wintypes.DWORD
            user32.GetWindowTextLengthW.argtypes = [wintypes.HWND]
            user32.GetWindowTextLengthW.restype = ctypes.c_int
            user32.GetWindowTextW.argtypes = [
                wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
            user32.GetWindowTextW.restype = ctypes.c_int
            user32.GetWindow.argtypes = [wintypes.HWND, wintypes.UINT]
            user32.GetWindow.restype = wintypes.HWND
            process_id = int(kernel32.GetCurrentProcessId())
            candidates = []
            enum_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
            user32.EnumWindows.argtypes = [enum_type, wintypes.LPARAM]
            user32.EnumWindows.restype = wintypes.BOOL

            def visit(hwnd, _lparam):
                try:
                    pid = wintypes.DWORD()
                    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
                    if int(pid.value) != process_id or not user32.IsWindowVisible(hwnd):
                        return True
                    length = int(user32.GetWindowTextLengthW(hwnd) or 0)
                    buffer = ctypes.create_unicode_buffer(max(1, length + 1))
                    user32.GetWindowTextW(hwnd, buffer, len(buffer))
                    title = str(buffer.value or "")
                    owner = int(user32.GetWindow(hwnd, 4) or 0)  # GW_OWNER
                    score = 0
                    if title == "WinUX":
                        score += 100
                    elif title.lower().startswith("winux"):
                        score += 80
                    if owner == 0:
                        score += 20
                    candidates.append((score, int(hwnd), title))
                except Exception:
                    pass
                return True

            callback = enum_type(visit)
            user32.EnumWindows(callback, 0)
            if candidates:
                _score, hwnd, _title = max(candidates, key=lambda item: item[0])
                if hwnd:
                    self._main_viewport_hwnd = hwnd
                    return hwnd
        except Exception:
            pass
        return None

    def _install_console_character_hook(self):
        """Route WM_CHAR to the embedded console only while it owns focus.

        Dear PyGui exposes key-down handlers but no portable text-input callback
        for a custom drawn terminal.  The old floating console received WM_CHAR
        from its private viewport; the docked console now shares the main GLFW
        HWND, so subclass that window and consume characters only when the
        terminal explicitly owns keyboard input.  Pointer/context-menu input is
        deliberately left to Dear PyGui and all other messages continue through
        the previous WNDPROC unchanged.
        """
        if os.name != "nt" or self._console_native_wndproc_callback is not None:
            return bool(self._console_native_wndproc_callback)
        hwnd = self._find_main_viewport_hwnd()
        if not hwnd:
            return False
        try:
            user32 = ctypes.windll.user32
            is_64 = ctypes.sizeof(ctypes.c_void_p) == 8
            setter = (
                user32.SetWindowLongPtrW if is_64
                else user32.SetWindowLongW)
            setter.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_void_p]
            setter.restype = ctypes.c_void_p
            user32.CallWindowProcW.argtypes = [
                ctypes.c_void_p, wintypes.HWND, wintypes.UINT,
                wintypes.WPARAM, wintypes.LPARAM]
            user32.CallWindowProcW.restype = ctypes.c_ssize_t
            wndproc_type = ctypes.WINFUNCTYPE(
                ctypes.c_ssize_t, wintypes.HWND, wintypes.UINT,
                wintypes.WPARAM, wintypes.LPARAM)
            WM_CHAR = 0x0102
            GWL_WNDPROC = -4

            def dispatch(window, message, wparam, lparam):
                if message == WM_CHAR:
                    panel = getattr(self, "_console_keyboard_panel", None)
                    if (panel is not None
                            and getattr(panel, "keyboard_active", lambda: False)()):
                        self.after(0, panel.native_character, int(wparam))
                        return 0

                # RMB is intentionally *not* intercepted here.  The console
                # context menu is driven by a global Dear PyGui release observer
                # that opens a modeless surface after callback dispatch.  Keeping
                # WNDPROC limited to WM_CHAR avoids losing RMB to asymmetric
                # native DOWN/UP consumption or stale native hit-test data.

                return user32.CallWindowProcW(
                    self._console_native_old_wndproc,
                    window, message, wparam, lparam)

            def safe_dispatch(window, message, wparam, lparam):
                try:
                    return dispatch(window, message, wparam, lparam)
                except BaseException:
                    log_exception(
                        "SSH Console native character hook failed",
                        sys.exc_info(), fatal=False)
                    try:
                        return user32.CallWindowProcW(
                            self._console_native_old_wndproc,
                            window, message, wparam, lparam)
                    except BaseException:
                        return 0

            callback = wndproc_type(safe_dispatch)
            ctypes.set_last_error(0)
            old_proc = setter(
                wintypes.HWND(hwnd), GWL_WNDPROC,
                ctypes.cast(callback, ctypes.c_void_p))
            if not old_proc and ctypes.get_last_error():
                return False
            self._console_native_hwnd = int(hwnd)
            self._console_native_old_wndproc = old_proc
            self._console_native_wndproc_callback = callback
            log_event(
                "SSH Console dock character hook installed on hwnd={}".format(
                    int(hwnd)))
            return True
        except Exception:
            log_exception(
                "Failed to install SSH Console character hook",
                sys.exc_info(), fatal=False)
            return False


    # Compatibility alias for integrations using the old orientation name.


    def _build_menu(self):
        """Build the application QMenuBar using DearUIQt popup ownership.

        Dear PyGui's native ``dpg.menu`` popup is visually correct, but it is
        invisible to DearUIQt's application pointer grab. Explorer and splitter
        code intentionally perform geometry-based/global pointer polling, so a
        native menu can appear above them while they still react to the same
        mouse position.  A retained QMenuBar/QMenu stack gives the menu Qt-like
        popup semantics: while a menu is open the application body is logically
        pointer-blocked by QApplication/input_gate without a visual overlay.
        """
        menu_bar = getattr(self, "_menu_bar_wrapper", None)
        if menu_bar is None:
            menu_bar = QMenuBar(
                parent=getattr(self, "_main_window", None), height=20)
            self._menu_bar_wrapper = menu_bar

        def action(label, icon_name, callback, *, checkable=False, checked=False):
            item = QAction(
                label, menu_bar, checkable=bool(checkable), checked=bool(checked))
            texture = ResourceTextures.get(icon_name) if icon_name else None
            if texture:
                item.setIcon(texture)
            if checkable:
                item.toggled.connect(
                    lambda value, cb=callback: cb(bool(value)))
            else:
                item.triggered.connect(
                    lambda _checked=False, cb=callback: cb())
            return item

        separator = lambda key: {
            "id": "separator_{}".format(key), "label": "---",
            "separator": True, "action": "separator_{}".format(key),
        }

        menu_bar.addMenu("File", [
            action("Log-In...", "Login", self.show_login),
            action("Site Manager...", "Login",
                   lambda: self.callbacks["site_manager"]()),
            action("Settings...", "Settings", self.show_settings),
            separator("file_1"),
            action("Exit", "Exit", self._request_close),
        ])

        menu_bar.addMenu("Bookmarks", [
            action("Add Local Folder", "Folder",
                   lambda: self.callbacks["bookmark_command"]("add_local")),
            action("Add Server Folder", "Folder",
                   lambda: self.callbacks["bookmark_command"]("add_server")),
            separator("bookmarks_1"),
            action("Manage Bookmarks...", "Open_Folder",
                   lambda: self.callbacks["bookmark_command"]("manage")),
        ])

        menu_bar.addMenu("Commands", [
            action("Synchronize Preview...", "Refresh",
                   lambda: self.callbacks["sync_preview"]()),
        ])

        menu_bar.addMenu("Reference", [
            action("Chart...", "JobViewer", self._show_reference_chart_dialog),
            action("Plot Digitizer...", "JobViewer",
                   self._show_plot_digitizer_dialog),
        ])

        # QDockWidget owns its persistent toggleViewAction(). Reuse that exact
        # QAction in View instead of mirroring dock visibility in a second
        # action, matching QMainWindow/QDockWidget ownership semantics.
        console_action = self.console_dock.toggleViewAction()
        console_action.setText("Console")
        console_texture = ResourceTextures.get("CommandWindow")
        if console_texture:
            console_action.setIcon(console_texture)
        self.console_menu_item = console_action
        menu_bar.addMenu("View", [
            console_action,
            action("Transfer Center", "Download", self.show_transfer_center),
            separator("view_1"),
            action("Job Schedule", "JobViewer", self.show_job_schedule),
        ])

        menu_bar.addMenu("Help", [
            action("Manual", "Question", self.show_manual),
            action("Diagnostics...", "Information", self.show_diagnostics),
            separator("help_1"),
            action("About Winux", "Information", self.show_about),
        ])
        return menu_bar.tag

    @staticmethod
    def _add_icon_menu_item(parent, label, icon_name, callback):
        """Add one fixed-width menu command with a context-menu-sized icon."""
        row = QHBoxLayout(parent=parent, spacing=7)
        texture = ResourceTextures.get(icon_name)
        if texture:
            QImageView(texture, parent=row, width=18, height=18)
        else:
            QSpacer(width=18, height=18, parent=row)
        button = QToolButton(
            label, parent=row, width=188, height=23, auto_raise=True)
        button.clicked.connect(
            lambda: callback() if callable(callback) else None)
        return button.tag

    @staticmethod
    def _add_icon_toggle_menu_item(parent, label, icon_name, checked, callback):
        row = QHBoxLayout(parent=parent, spacing=7)
        texture = ResourceTextures.get(icon_name)
        if texture:
            QImageView(texture, parent=row, width=18, height=18)
        else:
            QSpacer(width=18, height=18, parent=row)
        button = QToolButton(
            label, parent=row, width=188, height=23, auto_raise=True)
        button.setCheckable(True)
        button.setChecked(bool(checked))
        button.toggled.connect(
            lambda value: callback(bool(value)) if callable(callback) else None)
        return button.tag

    @staticmethod
    def _run_icon_toggle_menu_item(sender=None, app_data=None, user_data=None):
        if callable(user_data):
            user_data(bool(app_data))

    @staticmethod
    def _run_icon_menu_item(sender=None, app_data=None, user_data=None):
        # Legacy retained commands may preserve a selected value after a popup
        # closes. Keep the reset behind DearUIQt rather than the renderer API.
        if sender is not None:
            try:
                QRetainedItem(sender).setValue(False)
            except Exception:
                pass
        if callable(user_data):
            user_data()

    def show_manual(self):
        manual = resource_path("WinUx_User_Manual_EN.pdf")
        if not manual.is_file():
            self.show_error("WinUx Manual", "Manual file was not found:\n{}".format(manual))
            return
        try:
            os.startfile(str(manual))
        except (AttributeError, OSError) as exc:
            self.show_error("WinUx Manual", "Could not open the manual:\n{}".format(exc))

    def show_about(self):
        self.show_message(
            "About Winux",
            "Winux - Abaqus Workspace\n\nSSH file transfer, job management, "
            "and Abaqus workflow tools.",
        )

    @crash_guard("Dear PyGui view lifecycle failed")
    def run(self):
        log_event("Dear PyGui viewport startup began")
        try:
            self._gui_runtime.show()
            log_event("Dear PyGui viewport shown")

            # Dear PyGui does not know the final native client/content
            # dimensions until at least one frame has been rendered. Applying
            # the layout before that first frame uses provisional sizes.
            if self._gui_runtime.isRunning():
                self._gui_runtime.renderFrame()
            log_event("Dear PyGui first frame rendered")

            self._pending_viewport_size = None
            self._resize_last_event = 0.0
            self._layout_dirty = True
            self._apply_split_layout(force=True)

            # Commit fitted dimensions before entering normal event processing.
            if self._gui_runtime.isRunning():
                self._gui_runtime.renderFrame()

            log_event("Dear PyGui render loop started")
            # Querying the native context can itself fail if GLFW/DPG was torn
            # down asynchronously by the host. Treat that as an orderly loop
            # termination instead of letting a Python exception escape run().
            while self._alive:
                try:
                    running = bool(self._gui_runtime.isRunning())
                except Exception:
                    log_exception(
                        "Dear PyGui running-state query failed",
                        sys.exc_info(), fatal=False)
                    break
                if not running:
                    break
                self.update()

            reason = (
                "application shutdown was requested"
                if not self._alive
                else "Dear PyGui reported that it was no longer running"
            )
            log_event("Dear PyGui render loop ended: {}".format(reason))
        finally:
            if self._watchdog is not None:
                self._watchdog.close()
            self._dispatcher.close()
            self._destroy_components()
            try:
                if self._gui_runtime.isRunning():
                    self._gui_runtime.stop()
            except Exception:
                log_exception(
                    "Failed to stop Dear PyGui during cleanup",
                    sys.exc_info(),
                    fatal=False,
                )
            try:
                preview = getattr(self, "_dock_drop_preview", None)
                if preview is not None:
                    try:
                        preview.destroy()
                    except Exception:
                        pass
                reset_component_runtime_resources()
            except Exception:
                log_exception(
                    "Failed to reset Dear PyGui component caches",
                    sys.exc_info(),
                    fatal=False,
                )
            try:
                self._gui_runtime.destroy()
                log_event("Dear PyGui context destroyed")
            except Exception:
                log_exception(
                    "Failed to destroy Dear PyGui context",
                    sys.exc_info(),
                    fatal=False,
                )

    def mainloop(self):
        self.run()

    def apply_general_preferences(self, values=None):
        values = self._general_preferences.load() if values is None else values
        self._show_hidden_files = bool(values.get("show_hidden_files", False))
        for panel in self.panels:
            panel.set_show_hidden_files(self._show_hidden_files)

    def _safe_frame_step(self, name, callback, *args, **kwargs):
        """Run one non-critical per-frame UI step without killing the app.

        Docking, splitters, cursor feedback and retained-list geometry all
        reference items whose lifetime can end between callbacks.  A single
        stale tag should degrade one interaction, not terminate WinUx.  Errors
        are retried on later frames and logged at most once every 15 seconds
        per step to avoid a failing optional visual path flooding the logs.
        """
        default = kwargs.pop("default", None)
        try:
            result = callback(*args, **kwargs)
        except Exception:
            now = time.monotonic()
            state = self._frame_step_errors.get(name)
            last_log = state[0] if state else 0.0
            failures = (state[1] if state else 0) + 1
            if not state or now - last_log >= 15.0:
                log_exception(
                    "Non-fatal UI frame step failed: {}".format(name),
                    sys.exc_info(), fatal=False)
                last_log = now
            self._frame_step_errors[name] = (last_log, failures)
            return default
        else:
            self._frame_step_errors.pop(name, None)
            return result

    def update(self):
        if self._watchdog is not None:
            self._safe_frame_step("watchdog heartbeat", self._watchdog.beat)

        # Native dialogs do not belong to Dear PyGui's item tree. Treat them
        # as a real Qt foreground surface, but do not let a transient native
        # focus/query failure terminate the entire render loop.
        native_input_blocked = bool(self._safe_frame_step(
            "native input gate", native_background_input_blocked,
            default=False))
        if native_input_blocked:
            self._safe_frame_step(
                "cancel splitter interactions", self._cancel_splitter_interactions)
            self._safe_frame_step(
                "release pointer input", release_pointer_input)
            self._safe_frame_step(
                "discard blocked DPG callbacks", self._drain_dpg_callbacks,
                True)
        else:
            # Splitter arbitration must happen before Dear PyGui's global
            # ListView callbacks are drained; otherwise the same physical press
            # can become both a divider resize and a file drag/drop.
            self._safe_frame_step(
                "pre-dispatch splitter input", self._pre_dispatch_splitter_input)
            self._safe_frame_step(
                "DPG callback dispatch", self._drain_dpg_callbacks)
            self._safe_frame_step(
                "file panel splitter input", self._update_file_panel_splitter_input)
        if not self._alive:
            return
        if self._console_native_wndproc_callback is None:
            self._safe_frame_step(
                "console character hook", self._install_console_character_hook)
        self._safe_frame_step("UI dispatcher drain", self._drain_queue)
        if not self._alive:
            return
        if self._startup_layout_frames > 0:
            self._startup_layout_frames -= 1
            self._layout_dirty = True
            self._safe_frame_step(
                "startup split layout", self._apply_split_layout, force=True)
        elif self._layout_dirty:
            self._safe_frame_step("split layout", self._apply_split_layout)
        if not native_input_blocked:
            # QTabBar-like drag/reorder must claim the pointer before splitters
            # or Explorer panes poll global mouse state, otherwise a tab tear-
            # off can simultaneously resize/select widgets underneath it.
            dock_manager = getattr(self, "plot_dock_manager", None)
            if dock_manager is not None:
                self._safe_frame_step(
                    "dock manager interaction", dock_manager.update_interaction)
            # All of these paths are interaction polish around transient DPG
            # items.  A stale tag after close/dock/resize is recoverable on the
            # next frame and must not be fatal to the application.
            for name, callback in (
                ("floating plot resize", self._update_floating_plot_resize_interaction),
                ("floating console resize", self._update_floating_console_resize_interaction),
                ("horizontal splitter input", self._update_horizontal_splitter_input),
                ("job plot splitter input", self._update_job_plot_splitter_input),
                ("console splitter input", self._update_console_splitter_input),
                ("floating plot docking", self._update_floating_plot_docking),
                ("floating console docking", self._update_floating_console_docking),
            ):
                self._safe_frame_step(name, callback)
            # Inline rename focus/selection cannot depend on per-ListView frame
            # callbacks: Dear PyGui provides only one callback slot per frame.
            for index, panel in enumerate(tuple(self.panels)):
                self._safe_frame_step(
                    "inline rename focus {}".format(index),
                    panel.listview._process_inline_rename_focus)
        self._safe_frame_step("job plot window sync", self._sync_job_plot_windows)
        self._safe_frame_step(
            "horizontal panel divider sync", self._sync_horizontal_panel_divider)

        # Rendering itself is intentionally still a hard boundary. If native
        # Dear PyGui cannot render a frame, continuing to call into that context
        # can cause an access violation; let the outer crash logger own that
        # exceptional case instead of spinning on an invalid context.
        running = False
        try:
            running = bool(self._gui_runtime.isRunning())
        except Exception:
            log_exception(
                "Dear PyGui running-state query failed during frame",
                sys.exc_info(), fatal=False)
            self._alive = False
        if running:
            self._rendering = True
            try:
                self._gui_runtime.renderFrame()
            finally:
                self._rendering = False
                self._render_generation += 1
            # Use freshly rendered geometry and service deferred layouts here.
            # Stale list/scroller resources can be recreated next frame, so
            # isolate them from the native render-loop lifetime.
            listviews = [panel.listview for panel in tuple(self.panels)]
            jobs_view = getattr(getattr(self, "jobs_view", None), "listview", None)
            if jobs_view is not None:
                listviews.append(jobs_view)
            for index, listview in enumerate(listviews):
                if getattr(listview, "_resize_layout_pending", False):
                    self._safe_frame_step(
                        "list layout {}".format(index), listview._layout_all)
                overlay = getattr(listview, "_scroller_arrow_overlay", None)
                if overlay is not None:
                    self._safe_frame_step(
                        "scroller overlay {}".format(index), overlay.update)
            self._safe_frame_step(
                "after-render callbacks", self._drain_after_render_callbacks)
        # GLFW may restore its arrow cursor while rendering. Apply splitter
        # feedback only when Dear PyGui owns pointer input; otherwise the
        # foreground native dialog is authoritative for cursor feedback.
        if not native_input_blocked:
            for name, callback in (
                ("file splitter cursor", self._update_file_panel_splitter_cursor),
                ("horizontal splitter cursor", self._update_horizontal_splitter_cursor),
                ("job plot splitter cursor", self._update_job_plot_splitter_cursor),
                ("console splitter cursor", self._update_console_splitter_cursor),
                ("floating plot resize cursor", self._apply_floating_plot_resize_cursor),
            ):
                self._safe_frame_step(name, callback)
        if self._watchdog is not None:
            self._safe_frame_step("watchdog heartbeat", self._watchdog.beat)


    def after(self, delay, callback, *args):
        return self._dispatcher.after(delay, callback, *args)

    def after_cancel(self, token):
        """Cancel a delayed GUI callback, matching Qt/Tk host scheduler APIs."""
        return self._dispatcher.after_cancel(token)

    def after_render(self, callback, *args):
        """Run a callback after at least one future Dear PyGui frame.

        When called from inside a DPG callback, the current frame is still
        rendering. Target the frame after the next one so queued modal deletion
        can be drained first and committed by rendering before a replacement
        modal is created.
        """
        if not callable(callback) or not self._alive:
            return None
        frames_ahead = 2 if self._rendering else 1
        target_generation = self._render_generation + frames_ahead
        self._after_render_callbacks.append(
            (target_generation, callback, args)
        )
        return target_generation

    def _drain_after_render_callbacks(self):
        if not self._after_render_callbacks:
            return
        while (self._after_render_callbacks and
               self._after_render_callbacks[0][0] <= self._render_generation):
            _generation, callback, args = self._after_render_callbacks.popleft()
            try:
                callback(*args)
            except Exception:
                self._handle_ui_callback_error(callback, sys.exc_info())

    def _drain_queue(self):
        # Bound worker-result processing per frame so a burst of completed
        # background work cannot starve Dear PyGui rendering/input.
        self._dispatcher.drain(
            self._handle_ui_callback_error,
            max_callbacks=256,
            time_budget_ms=6.0,
        )

    def add_watchdog_snapshot_provider(self, name, callback):
        if self._watchdog is not None:
            self._watchdog.add_snapshot_provider(name, callback)

    def _drain_dpg_callbacks(self, discard=False):
        """Dispatch or discard Dear PyGui callbacks on the UI thread.

        Native dialogs are separate top-level HWNDs. Dear PyGui's global
        handlers can still enqueue callbacks from physical mouse state even
        while WinUX is disabled or covered by a native dialog.  While the
        native input gate owns the pointer, drop those background callbacks
        rather than replaying them after the dialog closes.
        """
        try:
            queued = self._gui_runtime.callbackQueue() or ()
        except Exception:
            # Context teardown can race a final callback-queue poll. Missing one
            # batch during shutdown is safer than terminating the application.
            log_exception(
                "Dear PyGui callback queue retrieval failed",
                sys.exc_info(), fatal=False)
            return
        self._dpg_callbacks.extend(queued)
        if discard:
            self._preserve_native_close_requests()
            self._dpg_callbacks.clear()
            return
        # A shared deque permits a blocking modal to pump input recursively
        # without replaying the outer callback batch or starving its buttons.
        # Bound callback execution per frame: a burst of redraw/hover callbacks
        # must not delay frame presentation or an incoming dialog interaction.
        # The unprocessed FIFO tail is retained for the next rendered frame.
        from time import monotonic as _monotonic
        drain_started = _monotonic()
        processed = 0
        while self._dpg_callbacks and self._alive:
            if processed >= 256 or (processed and _monotonic() - drain_started >= 0.006):
                break
            # A callback can itself open a native modal. Stop immediately and
            # discard the remainder of the same physical input batch.
            native_gate = globals().get("native_background_input_blocked")
            blocked = False
            if callable(native_gate):
                try:
                    blocked = bool(native_gate())
                except Exception:
                    log_exception(
                        "Native input gate query failed while draining callbacks",
                        sys.exc_info(), fatal=False)
            if blocked:
                self._preserve_native_close_requests()
                self._dpg_callbacks.clear()
                break
            job = self._dpg_callbacks.popleft()
            processed += 1
            try:
                invoker = globals().get("invoke_callback_job")
                if callable(invoker):
                    invoker(job)
                else:
                    # Compatibility/failsafe for isolated callback-pump tests
                    # or a partially imported runtime. The normal application
                    # always uses the bounded safe invoker above.
                    runner = getattr(self._gui_runtime.backend, "run_callbacks", None)
                    if callable(runner):
                        runner([job])
            except Exception:
                callback = job[0] if isinstance(job, (tuple, list)) and job else None
                self._handle_ui_callback_error(callback, sys.exc_info())

    def _preserve_native_close_requests(self):
        """Keep OS Close events when dropping stale background pointer input.

        DPG puts its viewport-exit callback in the same queue as widget mouse
        handlers. The post-Esc modal release guard must consume the latter, but
        dropping WM_CLOSE means the user gets no confirmation at all. Marshal
        one close request onto the independent UI dispatcher instead.
        """
        if any(isinstance(job, (tuple, list)) and job
               and job[0] == self._request_close for job in self._dpg_callbacks):
            self.after(0, self._request_close)

    def _handle_ui_callback_error(self, callback, exc_info):
        callback_name = getattr(
            callback,
            "__qualname__",
            getattr(callback, "__name__", repr(callback)),
        )
        log_exception(
            "UI queue callback failed: {}".format(callback_name),
            exc_info,
            fatal=False,
        )
        try:
            self.show_error("WinUX", str(exc_info[1]))
        except Exception:
            # Error reporting is best-effort. A broken/closing dialog backend
            # must never turn an already-contained callback exception into an
            # application-ending second exception.
            log_exception(
                "Failed to display a UI callback error",
                sys.exc_info(),
                fatal=False,
            )

    def protocol(self, name, callback=None):
        if name == "WM_DELETE_WINDOW":
            self._close_callback = callback

    def winfo_exists(self):
        return self._alive

    def _hide_native_viewport(self):
        """Hide the OS viewport without entering Dear PyGui teardown."""
        if os.name != "nt":
            return
        try:
            from .platform import find_process_window
            hwnd = int(find_process_window("WinUX") or 0)
            if not hwnd:
                return
            user32 = ctypes.windll.user32
            user32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
            user32.ShowWindow.restype = wintypes.BOOL
            user32.ShowWindow(wintypes.HWND(hwnd), 0)  # SW_HIDE
        except Exception:
            pass

    def request_shutdown(self):
        """Make Close instantaneous and leave heavyweight teardown later.

        This method intentionally does *not* call ``dpg.stop_dearpygui`` or
        the renderer context-destroy API.  Calling those APIs while the UI dispatcher is
        inside a callback has produced SMAPython/GLFW deadlocks on Windows.
        The normal render-loop ``finally`` performs graceful teardown when the
        process is embedded; standalone WinUX is terminated by the controller
        after this method returns.
        """
        if not self._alive:
            return
        log_event("View shutdown requested")
        self._alive = False
        self._hide_native_viewport()
        self._release_horizontal_splitter_cursor_provider()

        chooser = getattr(self, "_local_folder_dialog", None)
        if chooser is not None:
            try:
                chooser.destroy()
            except Exception:
                pass

        from .dialogs.floating_dialog import close_floating_dialogs
        close_floating_dialogs(self)
        # Same-process dialogs must be terminally deleted while the Dear PyGui
        # context and QApplication dispatcher are still alive. Retained tools
        # normally hide on Close; application shutdown is their one hard delete.
        from .ui.hosting.inprocess_dialog import close_inprocess_dialogs
        close_inprocess_dialogs(self)
        application = getattr(self, "_qapplication", None)
        if application is not None:
            try:
                application.delete()
            except Exception:
                pass
            self._qapplication = None
        # Process-isolated windows are closed without waiting on the render thread.
        for name in ("login_dialog",
                     "transfer_center_dialog", "server_notepad_dialog"):
            dialog = getattr(self, name, None)
            if dialog is None:
                continue
            try:
                dialog.destroy(wait=False)
            except TypeError:
                try:
                    dialog.destroy()
                except Exception:
                    pass
            except Exception:
                pass

        if self._watchdog is not None:
            self._watchdog.close()
        self._dispatcher.close()
        self._after_render_callbacks.clear()
        self._dpg_callbacks.clear()

    def destroy(self):
        # Compatibility API used by older callers.  Request shutdown first,
        # then stop DPG only when control is outside a render callback.
        self.request_shutdown()
        try:
            if not self._rendering and self._gui_runtime.isRunning():
                self._gui_runtime.stop()
        except Exception:
            pass

    def _destroy_components(self):
        """Release ListView resources in reverse native-hook order."""
        if self._components_destroyed:
            return
        self._components_destroyed = True
        chooser = getattr(self, "_local_folder_dialog", None)
        if chooser is not None:
            try:
                chooser.destroy()
            except Exception:
                pass
        self._end_file_panel_splitter_drag()
        if getattr(self, "_horizontal_splitter_dragging", False):
            self._end_horizontal_splitter_drag()
        if getattr(self, "_plot_splitter_dragging", False):
            self._end_job_plot_splitter_drag()
        if getattr(self, "_console_splitter_dragging", False):
            self._end_console_splitter_drag()
        self._release_horizontal_splitter_cursor_provider()

        self._cancel_console_float_interaction()
        console_panel = getattr(self, "console_panel", None)
        if console_panel is not None:
            try:
                console_panel.destroy()
            except Exception:
                log_exception(
                    "Failed to destroy the SSH Console dock panel",
                    sys.exc_info(), fatal=False)
        console_dock = getattr(self, "console_dock", None)
        if console_dock is not None:
            try:
                console_dock.close()
            except Exception:
                log_exception(
                    "Failed to destroy the SSH Console dock widget",
                    sys.exc_info(), fatal=False)

        login = getattr(self, "login_dialog", None)
        if login is not None:
            try:
                login.destroy(wait=False)
            except Exception:
                log_exception(
                    "Failed to close the native SSH Login dialog",
                    sys.exc_info(),
                    fatal=False,
                )

        transfer_center = getattr(self, "transfer_center_dialog", None)
        if transfer_center is not None:
            try:
                transfer_center.destroy(wait=False)
            except Exception:
                log_exception(
                    "Failed to close the native Transfer Center",
                    sys.exc_info(),
                    fatal=False,
                )

        for plot_panel in list(getattr(self, "job_plot_windows", {}).values()):
            try:
                plot_panel.close(notify=False)
            except Exception:
                pass
        getattr(self, "job_plot_windows", {}).clear()
        dock_manager = getattr(self, "plot_dock_manager", None)
        if dock_manager is not None:
            try:
                dock_manager.close()
            except Exception:
                pass

        owners = [
            getattr(self, "left", None),
            getattr(self, "right", None),
            getattr(self, "jobs_view", None),
        ]
        for owner in reversed(owners):
            listview = getattr(owner, "listview", None)
            if listview is None:
                continue
            try:
                listview.destroy()
            except Exception:
                log_exception(
                    "Failed to destroy a ListView component",
                    sys.exc_info(),
                    fatal=False,
                )

    def _release_horizontal_splitter_cursor_provider(self):
        provider = ExplorerListView._external_cursor_provider
        if getattr(provider, "__self__", None) is self:
            ExplorerListView._external_cursor_provider = None

    def _request_close(self):
        if callable(self._close_callback):
            self._close_callback()
        else:
            self._alive = False

    def show_server_disconnected(self):
        self.right.set_disconnected()

    def display_server_directory(
            self, path, items, host, reset_history=False, record_history=True, **kwargs):
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
        self.jobs_view.display(jobs)
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
        return self.jobs_view.selected_values()

    def clear_job_selection(self):
        self.jobs_view.clear_selection()

    def show_login(self):
        dialog = getattr(self, "login_dialog", None)
        if dialog is not None and dialog.winfo_exists():
            dialog.lift()
            return dialog

        # A dropped SSH connection can leave the server-path chooser visible.
        # Do not stack another native modal on top of it: Dear PyGui's modal
        # stack is not reliable while the older dialog is being removed.
        server_path_dialog = getattr(self, "server_path_dialog", None)
        if (server_path_dialog is not None and
                server_path_dialog.winfo_exists()):
            server_path_dialog.destroy()
            return self.after_render(self.show_login)

        self.login_dialog = _dialog_type("LoginDialog")(
            self,
            self.callbacks["login"],
        )
        return self.login_dialog

    def show_transfer_progress(self, operation, cancel_event, items=None):
        center = self._get_transfer_center()
        return center.add_task(operation, cancel_event, items=items)

    def _get_transfer_center(self):
        center = getattr(self, "transfer_center_dialog", None)
        if center is None or not center.winfo_exists():
            center = _dialog_type("TransferCenterDialog")(self)
            self.transfer_center_dialog = center
        return center

    def _prewarm_transfer_center(self):
        """Prepare Transfer Center during an idle turn without process startup.

        The normal path builds one retained in-process Qt-style tool and hides
        it. Legacy process-host mode keeps its historical bounded prewarm pool.
        """
        if not self.winfo_exists() or getattr(self, "_floating_focus_suppressed", False):
            return
        if _use_inprocess_dialogs():
            # Build the retained widget tree during an idle UI turn. This pays
            # no process/IPC cost and makes the first explicit show a constant-
            # time visibility/activation transaction.
            self._get_transfer_center().hide()
            return
        try:
            from .ui.hosting.host import dialog_host_manager
            dialog_host_manager(self).refill()
        except Exception:
            # Idle preparation is optional and must never affect the main HWND.
            log_exception("Could not refill the floating dialog host pool", sys.exc_info())

    def _prewarm_inprocess_dialog_imports(self, index=0):
        """Incrementally resolve normal dialog classes during GUI idle time.

        This is intentionally import-only: retained heavy tools decide their own
        preconstruction policy, while transient dialogs still allocate widgets
        only when requested. No worker, subprocess or secondary event loop is
        created.
        """
        if not self.winfo_exists() or not _use_inprocess_dialogs():
            return False
        names = (
            # Resolving one transient class imports the shared transient module
            # and therefore warms Login/Job/Edit/file selectors/ODB/progress.
            "BlockingDialog",
            "SettingsDialog",
            "JobScheduleDialog",
            "BookmarksDialog",
            "SiteManagerDialog",
            "SyncPreviewDialog",
            "DiagnosticsDialog",
            "TransferCenterDialog",
        )
        index = max(0, int(index or 0))
        if index >= len(names):
            return True
        try:
            _dialog_type(names[index])
        except Exception:
            # Warmup is speculative; the normal click path remains authoritative.
            log_exception(
                "Could not warm in-process dialog {}".format(names[index]),
                sys.exc_info(), fatal=False)
        if index + 1 < len(names) and self.winfo_exists():
            self.after(24, self._prewarm_inprocess_dialog_imports, index + 1)
        return True

    def _prewarm_retained_dialog_shells(self, index=0):
        """Build common argument-free retained shells during idle turns.

        The shell remains hidden and shares QApplication's one GUI event loop.
        Settings page I/O keeps using its existing QThreadPool bridge, while no
        native dialog process or secondary renderer is created.
        """
        if not self.winfo_exists() or not _use_inprocess_dialogs():
            return False
        specs = (
            ("settings_dialog", "SettingsDialog"),
            ("diagnostics_dialog", "DiagnosticsDialog"),
        )
        index = max(0, int(index or 0))
        if index >= len(specs):
            return True
        attribute, class_name = specs[index]
        current = getattr(self, attribute, None)
        if current is None or not current.winfo_exists():
            try:
                current = _dialog_type(class_name)(self)
                setattr(self, attribute, current)
                current.hide()
            except Exception:
                # Keep idle warmup optional; the normal menu path can retry.
                setattr(self, attribute, None)
                log_exception(
                    "Could not prewarm retained {}".format(class_name),
                    sys.exc_info(), fatal=False)
        if index + 1 < len(specs) and self.winfo_exists():
            self.after(80, self._prewarm_retained_dialog_shells, index + 1)
        return True

    def show_transfer_center(self):
        center = self._get_transfer_center()
        center.show()
        return center

    def show_job_manager(self, paths, run_callback, compute_callback):
        self.job_manager_dialog = _dialog_type("JobManagerDialog")(
            self, paths, run_callback, compute_callback)
        return self.job_manager_dialog

    def show_server_notepad(self, path, on_load, on_save, on_reload):
        current = getattr(self, "server_notepad_dialog", None)
        if current is not None and current.winfo_exists():
            # One standalone editor window owns a Notepad++-style tab session.
            # If IPC has gone stale, do not keep returning a facade that can no
            # longer show a window; tear it down and launch a clean child.
            if current.queue_open(path):
                current.lift()
                return current
            try:
                current.destroy(wait=False)
            except Exception:
                pass
        self.server_notepad_dialog = _dialog_type("ServerNotepadDialog")(
            self, path, on_load=on_load, on_save=on_save, on_reload=on_reload)
        return self.server_notepad_dialog

    def show_odb_check(self, result):
        current = getattr(self, "odb_check_dialog", None)
        if current is not None and current.winfo_exists():
            current.destroy()
        self.odb_check_dialog = _dialog_type("ODBCheckDialog")(self, result)
        return self.odb_check_dialog

    def show_odb_extract(self, catalog, on_result):
        current = getattr(self, "odb_extract_dialog", None)
        if current is not None and current.winfo_exists():
            current.destroy()
        self.odb_extract_dialog = _dialog_type("ODBExtractDialog")(
            self, catalog, on_result)
        return self.odb_extract_dialog

    def show_odb_xy_results(self, result):
        current = getattr(self, "odb_xy_result_dialog", None)
        if current is not None and current.winfo_exists():
            current.destroy()
        self.odb_xy_result_dialog = _dialog_type("ODBXYResultDialog")(self, result)
        return self.odb_xy_result_dialog

    def _blocking_modal(
            self, title, message, kind="message", initial="",
            primary_text=None, secondary_text=None, intent="info"):
        return _dialog_type("BlockingDialog")(
            self, title, message, kind, initial,
            primary_text=primary_text,
            secondary_text=secondary_text,
            intent=intent,
        ).wait()

    def confirm_overwrite(self, message):
        return bool(self._blocking_modal(
            "Overwrite?", message, "confirm",
            primary_text="Replace", secondary_text="Cancel",
            intent="warning"))

    def confirm_action(
            self, title, message, primary_text=None,
            secondary_text="Cancel", intent="question"):
        return bool(self._blocking_modal(
            title, message, "confirm",
            primary_text=primary_text,
            secondary_text=secondary_text,
            intent=intent))

    def confirm_action_async(
            self, title, message, callback, primary_text=None,
            secondary_text="Cancel", intent="question"):
        """Show one asynchronous confirmation dialog on the UI queue."""
        title_key = str(title or "").casefold()
        if primary_text is None:
            if "overwrite" in title_key or "replace" in title_key:
                primary_text = "Replace"
                if intent == "question":
                    intent = "warning"
            elif "delete" in title_key:
                primary_text = "Delete"
                intent = "danger"
            elif "close" in title_key or "exit" in title_key:
                primary_text = "Exit"
            else:
                primary_text = "OK"
        requests = getattr(self, "_async_confirm_requests", None)
        if requests is None:
            requests = self._async_confirm_requests = deque()
        requests.append((title, message, callback, primary_text, secondary_text, intent))
        return self._drain_async_confirm_requests()

    def _drain_async_confirm_requests(self):
        """Serialize confirmations without dropping another action's callback."""
        if getattr(self, "_async_confirm_active", None) is not None:
            current = getattr(self, "_async_confirm_dialog", None)
            if current is not None and current.winfo_exists():
                current.lift()
            return None
        requests = getattr(self, "_async_confirm_requests", None)
        if not requests or not getattr(self, "_alive", True):
            return None
        title, message, callback, primary_text, secondary_text, intent = requests.popleft()
        token = self._async_confirm_active = object()

        def completed(value):
            if self._async_confirm_active is not token:
                return
            self._async_confirm_active = None
            self._async_confirm_dialog = None
            try:
                callback(value)
            finally:
                # ResultDialog completes after the old host's idle ACK. Start
                # the next request on a fresh UI turn, not inside teardown.
                self.after(0, self._drain_async_confirm_requests)

        try:
            dialog = _dialog_type("BlockingDialog")(
                self, title, message, "confirm", on_result=completed,
                primary_text=primary_text,
                secondary_text=secondary_text,
                intent=intent)
            self._async_confirm_dialog = dialog
            dialog.lift()
        except Exception:
            self._async_confirm_active = None
            self._async_confirm_dialog = None
            self.after(0, callback, False)
            self.after(0, self._drain_async_confirm_requests)
            raise
        return dialog

    def _show_message_dialog(self, title, message, intent="info"):
        # Informational dialogs never need a nested render loop. Starting a
        # second render_dearpygui_frame() loop from a menu/context callback is
        # undefined in Dear PyGui and is the main source of whole-app flicker.
        dialog = _dialog_type("BlockingDialog")(
            self, title, message, "message",
            primary_text="OK", intent=intent)
        dialog.lift()
        return dialog

    def show_error(self, title, message):
        return self._show_message_dialog(title, message, intent="error")

    def show_message(self, title, message):
        return self._show_message_dialog(title, message, intent="info")

    def ask_text(self, title, prompt, initial=""):
        return self._blocking_modal(title, prompt, "input", initial)

    def ask_text_async(self, title, prompt, initial="", callback=None):
        """Show one input dialog without starting a nested render loop."""
        current = getattr(self, "_async_text_dialog", None)
        if current is not None and current.winfo_exists():
            current.lift()
            return current

        def completed(value):
            self._async_text_dialog = None
            if callable(callback):
                callback(value)

        dialog = _dialog_type("BlockingDialog")(
            self, title, prompt, "input", initial, on_result=completed)
        self._async_text_dialog = dialog
        dialog.lift()
        return dialog

    def show_local_folder_dialog(self, initial, on_selected):
        """Open the local-folder browser on the shared QApplication event loop."""
        dialog = getattr(self, "_local_folder_dialog", None)
        if dialog is not None and dialog.winfo_exists():
            dialog.lift()
            return dialog

        def selected(path):
            current = getattr(self, "_local_folder_dialog", None)
            if current is dialog:
                self._local_folder_dialog = None
            if path and callable(on_selected):
                on_selected(path)

        dialog = _dialog_type("LocalFolderDialog")(self, initial, selected)
        self._local_folder_dialog = dialog
        return dialog

    def show_server_path(
            self, initial, suggestion_provider, on_selected, task_submitter=None):
        dialog = getattr(self, "server_path_dialog", None)
        if dialog is not None and dialog.winfo_exists():
            dialog.lift()
            return dialog

        self.server_path_dialog = _dialog_type("ServerPathDialog")(
            self,
            initial,
            suggestion_provider,
            on_selected=on_selected,
            task_submitter=task_submitter,
        )
        return self.server_path_dialog


    def show_settings(self):
        dialog = getattr(self, "settings_dialog", None)
        if dialog is not None and dialog.winfo_exists():
            dialog.lift()
            return dialog
        self.settings_dialog = _dialog_type("SettingsDialog")(self)
        self.settings_dialog.show()
        return self.settings_dialog

    def show_bookmarks(self, entries, on_open, on_remove, on_rename):
        dialog = getattr(self, "bookmarks_dialog", None)
        if dialog is not None and dialog.winfo_exists():
            dialog.refresh(entries, on_open, on_remove, on_rename)
            dialog.lift()
            return dialog
        self.bookmarks_dialog = _dialog_type("BookmarksDialog")(
            self, entries, on_open, on_remove, on_rename)
        self.bookmarks_dialog.show()
        return self.bookmarks_dialog

    def show_site_manager(self, sites, on_save, on_delete, on_connect):
        dialog = getattr(self, "site_manager_dialog", None)
        if dialog is not None and dialog.winfo_exists():
            dialog.refresh(sites, on_save=on_save, on_delete=on_delete, on_connect=on_connect)
            dialog.lift()
            return dialog
        self.site_manager_dialog = _dialog_type("SiteManagerDialog")(
            self, sites, on_save, on_delete, on_connect)
        self.site_manager_dialog.show()
        return self.site_manager_dialog

    def show_sync_preview(
            self, rows, local_path, server_path, on_refresh, on_transfer):
        dialog = getattr(self, "sync_preview_dialog", None)
        if dialog is not None and dialog.winfo_exists():
            dialog.refresh(rows, local_path, server_path, on_refresh, on_transfer)
            dialog.lift()
            return dialog
        self.sync_preview_dialog = _dialog_type("SyncPreviewDialog")(
            self, rows, local_path, server_path, on_refresh, on_transfer)
        self.sync_preview_dialog.show()
        return self.sync_preview_dialog

    def show_diagnostics(self):
        dialog = getattr(self, "diagnostics_dialog", None)
        if dialog is not None and dialog.winfo_exists():
            dialog.refresh()
            dialog.lift()
            return dialog
        self.diagnostics_dialog = _dialog_type("DiagnosticsDialog")(self)
        self.diagnostics_dialog.show()
        return self.diagnostics_dialog


    def show_job_schedule(self):
        dialog = getattr(self, "job_schedule_dialog", None)
        if dialog is not None and dialog.winfo_exists():
            # Hidden retained Job Schedule refreshes from showEvent().  Avoid a
            # second provider call on the same reopen transaction; an already
            # visible tool still refreshes explicitly when selected from View.
            was_visible = bool(getattr(dialog, "isVisible", lambda: True)())
            dialog.lift()
            if was_visible:
                dialog.refresh()
            return dialog
        self.job_schedule_dialog = _dialog_type("JobScheduleDialog")(
            self, self.callbacks["job_schedule"],
            self.callbacks["job_schedule_command"],
        )
        self.job_schedule_dialog.show()
        return self.job_schedule_dialog

    def edit_job(self, values, settings=None, callback=None):
        """Open and retain one non-blocking Edit Job dialog."""
        current = getattr(self, "edit_job_dialog", None)
        if current is not None and current.winfo_exists():
            current.lift()
            return current

        def completed(value):
            self.edit_job_dialog = None
            if callable(callback):
                callback(value)

        dialog = _dialog_type("JobEditDialog")(
            self, values, settings or {}, on_result=completed)
        self.edit_job_dialog = dialog
        dialog.lift()
        return dialog
