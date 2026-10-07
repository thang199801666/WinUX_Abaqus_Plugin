from __future__ import annotations

import ctypes
import os
import sys
from collections import deque
from ctypes import wintypes
from pathlib import Path, PurePosixPath

import dearpygui.dearpygui as dpg

from .components import (
    DockDropPreview, DockManager, DockWidget, ExplorerListView, FilePanel, JobsView, ResourceTextures,
    apply_white_explorer_theme, reset_component_runtime_resources,
)
from .resources import resource_path
from .general_preferences import GeneralPreferences
from .dialogs.console_form import ConsoleDockPanel
from .controllers import validate_callbacks
from . import dialogs as _dialogs
from .diagnostics import crash_guard, log_event, log_exception
from .runtime import UIHangWatchdog, UiDispatcher
from .runtime.dpg_callbacks import invoke_callback_job
from .components.qt_style import QtFusionPalette
from .components.toolbar import (
    file_status_bar_theme, file_status_text_theme, resource_menu_theme,
)
from .widgets.imgui_qt_style import (
    application_theme, splitter_hitbox_theme, splitter_theme,
)
from .ui import (
    ConsoleDockingMixin, PlotDockingMixin, PointerRoutingMixin,
    SplitterLayoutMixin,
)
from .components.interaction_gate import (
    native_background_input_blocked, release_pointer_input,
)


def __getattr__(name):
    # Preserve view.LoginDialog/etc. for integrations without resolving every
    # dialog backend when the application only needs its main window.
    if name in _dialogs.__all__:
        return getattr(_dialogs, name)
    raise AttributeError(name)


def _dialog_type(name):
    # Historical callers/tests can override the named constructor on this
    # module. Otherwise resolve it only when the user opens that dialog.
    return globals().get(name) or getattr(_dialogs, name)


class WinUXView(
        SplitterLayoutMixin, PlotDockingMixin, ConsoleDockingMixin,
        PointerRoutingMixin):
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
    PLOT_DOCK_SEPARATOR_SIZE = 1
    CONSOLE_DOCK_DEFAULT_HEIGHT = 220
    MIN_CONSOLE_DOCK_HEIGHT = 150
    CONSOLE_DOCK_SEPARATOR_SIZE = 1
    PLOT_DOCK_AREAS = ("left", "right", "top", "bottom")
    # Keep every visible divider hairline-thin, but make the pointer target much
    # larger than the painted handle. Vertical splitters already acquire well
    # with a 10 px halo. Horizontal dividers need a taller Y grab band on high
    # DPI displays, so they deliberately use a larger orientation-specific halo.
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
    SPLITTER_HIT_PADDING = 10
    HORIZONTAL_SPLITTER_HIT_PADDING = 18
    # Compatibility value retained for older integrations; no longer used by
    # the Local/Server splitter implementation.
    FILE_PANEL_SPLITTER_HIT_PADDING = 6
    FILE_STATUS_HEIGHT = 20
    APP_PADDING = 4
    DOCK_SNAP_DISTANCE = 56

    @crash_guard("WinUXView initialization failed")
    def __init__(self, callbacks):
        self.callbacks = validate_callbacks(callbacks)
        self._general_preferences = GeneralPreferences()
        try:
            self._console_dock_visible = bool(
                self._general_preferences.load_console_visible())
        except Exception:
            self._console_dock_visible = False
        self._console_dock_height = self.CONSOLE_DOCK_DEFAULT_HEIGHT
        # QDockWidget-style Console state.  Visibility is persisted separately
        # from docking mode: a visible Console may either occupy the bottom dock
        # site or live in a detachable floating tool window.
        self._console_dock_mode = "docked"
        self._console_float_window = None
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
        self._watchdog = None
        # Callbacks that must run only after a rendered frame (most notably
        # actions accepted from a closing modal). Dear PyGui does not fully
        # release a modal until rendering advances, while after(0) is drained
        # immediately in the same UI iteration.
        self._render_generation = 0
        self._rendering = False
        self._after_render_callbacks = []
        self._dpg_callbacks = deque()
        # Compatibility for integrations that inspect the old queue attribute.
        self._queue = self._dispatcher.queue
        self._alive = True

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

        dpg.create_context()
        # Run input callbacks on the render/UI thread. The default DPG worker
        # otherwise mutates/queries the native item registry concurrently with
        # layout, modal deletion and rendering (seen in native crash traces).
        dpg.configure_app(manual_callback_management=True)
        apply_white_explorer_theme()
        # Shared QMainWindow-style docking feedback.  It is built lazily on the
        # first real drag so the native viewport already exists.  A viewport-
        # front drawlist guarantees that sibling child windows cannot cover the
        # preview rectangle.
        self._dock_drop_preview = DockDropPreview()
        self.terminal_font = None
        try:
            terminal_path = (
                Path(os.environ.get("WINDIR", "C:/Windows"))
                / "Fonts" / "consola.ttf")
            if terminal_path.is_file():
                with dpg.font_registry():
                    self.terminal_font = dpg.add_font(
                        str(terminal_path), 14)
        except Exception:
            self.terminal_font = None

        # Zero-spacing layout theme for the two file panels.
        with dpg.theme() as self._panel_layout_theme:
            with dpg.theme_component(dpg.mvAll):
                dpg.add_theme_style(dpg.mvStyleVar_ItemSpacing, 0, 0)
                dpg.add_theme_style(dpg.mvStyleVar_ItemInnerSpacing, 0, 0)
                dpg.add_theme_style(dpg.mvStyleVar_WindowPadding, 0, 0)
                dpg.add_theme_style(dpg.mvStyleVar_ChildBorderSize, 0)
                dpg.add_theme_style(dpg.mvStyleVar_CellPadding, 0, 0)

        # One application-wide Dear ImGui theme defines the Qt/Fusion state
        # palette for every control that does not own a more specific theme.
        # This keeps focus/hover/pressed visuals consistent across menu bars,
        # dock controls and ordinary widgets instead of falling back to the
        # stock Dear ImGui palette.
        self._app_theme = application_theme(dpg)

        # Windows 11 / Qt-like floating dock chrome. The built-in Dear ImGui
        # resize grip is disabled on detached docks; FloatingWindowResizer
        # restores native-feeling border/corner resizing without a grip glyph.
        with dpg.theme() as self._floating_dock_window_theme:
            with dpg.theme_component(dpg.mvAll):
                dpg.add_theme_color(dpg.mvThemeCol_Border, QtFusionPalette.BORDER)
                dpg.add_theme_color(dpg.mvThemeCol_ResizeGrip, (0, 0, 0, 0))
                dpg.add_theme_color(dpg.mvThemeCol_ResizeGripHovered, (0, 0, 0, 0))
                dpg.add_theme_color(dpg.mvThemeCol_ResizeGripActive, (0, 0, 0, 0))
                dpg.add_theme_color(dpg.mvThemeCol_WindowBg, QtFusionPalette.WINDOW)
                dpg.add_theme_color(dpg.mvThemeCol_TitleBg, QtFusionPalette.TITLE)
                dpg.add_theme_color(dpg.mvThemeCol_TitleBgActive, QtFusionPalette.TITLE_ACTIVE)
                dpg.add_theme_color(dpg.mvThemeCol_TitleBgCollapsed, QtFusionPalette.TITLE)
                dpg.add_theme_color(dpg.mvThemeCol_Text, QtFusionPalette.TEXT)
                dpg.add_theme_style(dpg.mvStyleVar_WindowRounding, 1)
                dpg.add_theme_style(dpg.mvStyleVar_WindowBorderSize, 1)
                dpg.add_theme_style(dpg.mvStyleVar_WindowPadding, 0, 0)
                title_align = getattr(dpg, "mvStyleVar_WindowTitleAlign", None)
                if title_align is not None:
                    dpg.add_theme_style(title_align, 0.0, 0.5)

        with dpg.window(
            tag="winux_primary", label="WinUX",
            no_scrollbar=True, no_scroll_with_mouse=True,
        ):
            self.menu_bar = self._build_menu()

            # A single root child owns the complete content area. The top and
            # bottom regions are positioned absolutely inside this root instead
            # of being stacked by Dear PyGui. This prevents a 1-2 px DPI/menu
            # rounding error from increasing the primary window content height
            # and permanently showing its vertical scrollbar.
            self.layout_root = dpg.add_child_window(
                width=-1, height=-1, border=False,
                no_scrollbar=True, no_scroll_with_mouse=True,
            )

            # Local/Server panes are positioned around a real vertical gutter.
            # The gutter is layout space, not an invisible halo over either
            # ListView, matching the QSplitter behavior used elsewhere.
            self.top_region = dpg.add_child_window(
                parent=self.layout_root,
                pos=(0, 0),
                width=-1, height=476, border=False,
                no_scrollbar=True, no_scroll_with_mouse=True,
            )
            # Compatibility marker for code that still inspects the historical
            # table attribute; it no longer participates in layout.
            self.file_panels_table = dpg.add_group(
                parent=self.top_region, show=False)
            self.left_parent = dpg.add_child_window(
                parent=self.top_region, pos=(0, 0),
                width=400, height=476, border=False,
                no_scrollbar=True, no_scroll_with_mouse=True,
            )
            self.right_parent = dpg.add_child_window(
                parent=self.top_region, pos=(409, 0),
                width=400, height=476, border=False,
                no_scrollbar=True, no_scroll_with_mouse=True,
            )
            self.file_panel_separator = dpg.add_button(
                parent=self.top_region, label="", pos=(404, 0),
                width=self.SPLITTER_SIZE, height=476)
            self.file_panel_separator_hitbox = dpg.add_button(
                parent=self.top_region, label="", pos=(400, 0),
                width=self.FILE_PANEL_SPLITTER_GUTTER_SIZE, height=476)

            # Status text is owned by one fixed strip below both file lists.
            # Panels therefore do not create status children inside their own
            # resizable containers.
            self.left = FilePanel(
                self.left_parent, "local", callbacks,
                current_path=Path.cwd(),
                initial_path_label=str(Path.cwd()),
                has_status=False,
            )
            self.right = FilePanel(
                self.right_parent, "server", callbacks,
                current_path=PurePosixPath("/"),
                initial_path_label="Log-in", has_status=False,
            )
            self.panels = [self.left, self.right]

            self.file_status_region = dpg.add_child_window(
                parent=self.layout_root, pos=(0, 476), width=-1,
                height=self.FILE_STATUS_HEIGHT, border=False,
                no_scrollbar=True, no_scroll_with_mouse=True,
            )
            # Use two absolutely positioned status children instead of a
            # second independent table. Their divider is updated from the real
            # Local/Server panel widths, so the Server text never drifts when
            # the upper table divider is resized.
            self.left_status_window = dpg.add_child_window(
                parent=self.file_status_region, pos=(0, 0), width=500,
                height=self.FILE_STATUS_HEIGHT, border=False,
                no_scrollbar=True, no_scroll_with_mouse=True,
            )
            self.right_status_window = dpg.add_child_window(
                parent=self.file_status_region, pos=(500, 0), width=500,
                height=self.FILE_STATUS_HEIGHT, border=False,
                no_scrollbar=True, no_scroll_with_mouse=True,
            )
            dpg.bind_item_theme(self.file_status_region, file_status_bar_theme())
            dpg.bind_item_theme(self.left_status_window, file_status_bar_theme())
            dpg.bind_item_theme(self.right_status_window, file_status_bar_theme())

            def status_separator(parent):
                return dpg.add_spacer(parent=parent, width=8, height=14)

            with dpg.group(parent=self.left_status_window, horizontal=True) as left_status_group:
                left_items = dpg.add_text("0 items")
                dpg.bind_item_theme(left_items, file_status_text_theme())
                status_separator(left_status_group)
                left_selected = dpg.add_text("0 selected")
                dpg.bind_item_theme(left_selected, file_status_text_theme(muted=True))
            with dpg.group(parent=self.right_status_window, horizontal=True) as right_status_group:
                right_items = dpg.add_text("Not connected")
                dpg.bind_item_theme(right_items, file_status_text_theme())
                status_separator(right_status_group)
                right_selected = dpg.add_text("0 selected")
                dpg.bind_item_theme(right_selected, file_status_text_theme(muted=True))
            self.left.attach_external_status(left_items, left_selected)
            self.right.attach_external_status(right_items, right_selected)

            self.bottom_region = dpg.add_child_window(
                parent=self.layout_root,
                pos=(0, 508),
                width=-1, height=-1, border=False,
                no_scrollbar=True, no_scroll_with_mouse=True,
            )
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
            self.plot_region = dpg.add_child_window(
                parent=self.layout_root, pos=(0, 0), width=1, height=1,
                border=False, no_scrollbar=True, no_scroll_with_mouse=True,
                show=False,
            )
            dpg.bind_item_theme(self.plot_region, self._panel_layout_theme)
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
            self.console_region = dpg.add_child_window(
                parent=self.layout_root, pos=(0, 0), width=1, height=1,
                border=False, no_scrollbar=True, no_scroll_with_mouse=True,
                show=self._console_dock_visible,
            )
            dpg.bind_item_theme(self.console_region, self._panel_layout_theme)
            self.console_dock = DockWidget(
                self.console_region,
                "SSH Console",
                "winux_ssh_console_dock",
                on_float_change=self._console_float_requested,
                on_close=self.hide_console,
                features=DockWidget.AllDockWidgetFeatures,
                dock_area="bottom",
                allowed_areas=DockWidget.BottomDockWidgetArea,
            )
            self.console_panel = ConsoleDockPanel(
                self, self.console_dock.content,
                self.callbacks["console_output"],
                self.callbacks["console_command"],
                self.callbacks["console_interrupt"],
                lambda message: self.after(
                    0, self.show_error, "SSH Console", message),
            )
            # QDockWidget title dragging is a host operation because the live
            # dock root must be reparented into a top-level tool window.  Keep
            # the handler global (as DPG requires for mouse drag/release) but
            # start a tear-off only while the Console title handle owns the
            # press.
            with dpg.handler_registry() as self._console_dock_drag_registry:
                dpg.add_mouse_drag_handler(
                    button=dpg.mvMouseButton_Left, threshold=8.0,
                    callback=self._on_console_dock_header_drag)
                dpg.add_mouse_release_handler(
                    button=dpg.mvMouseButton_Left,
                    callback=self._on_console_dock_header_drag_release)
            self.console_separator = dpg.add_button(
                parent=self.layout_root, label="", pos=(0, 0), width=1,
                height=self.CONSOLE_DOCK_SEPARATOR_SIZE,
                show=self._console_dock_visible,
            )
            self.console_separator_hitbox = dpg.add_button(
                parent=self.layout_root, label="", pos=(0, 0), width=1,
                height=self.CONSOLE_DOCK_SPLITTER_GUTTER_SIZE,
                show=self._console_dock_visible,
            )
            self.job_plot_separator = dpg.add_button(
                parent=self.layout_root, label="", pos=(0, 0),
                width=self.PLOT_DOCK_SEPARATOR_SIZE, height=1, show=False,
            )
            self.job_plot_separator_hitbox = dpg.add_button(
                parent=self.layout_root, label="", pos=(0, 0),
                width=(self.PLOT_DOCK_SEPARATOR_SIZE
                       + 2 * self.SPLITTER_HIT_PADDING),
                height=1, show=False,
            )

            # File/Job Viewer splitter gets its own real gutter instead of
            # overlapping the Job Viewer header with an invisible 37px halo.
            # The visible line stays 1px, centred in the gutter; the entire
            # gutter is an easy-to-grab resize surface.
            splitter_gutter_y = 500
            splitter_line_y = (
                splitter_gutter_y
                + (self.FILE_JOB_SPLITTER_GUTTER_SIZE - self.SPLITTER_SIZE) // 2
            )
            self.horizontal_splitter = dpg.add_button(
                parent=self.layout_root, label="",
                # The first dynamic layout pass will replace this position.
                pos=(0, splitter_line_y),
                width=-1, height=self.SPLITTER_SIZE,
            )
            self.horizontal_splitter_hitbox = dpg.add_button(
                parent=self.layout_root, label="",
                pos=(0, splitter_gutter_y),
                width=-1, height=self.FILE_JOB_SPLITTER_GUTTER_SIZE,
            )
            # Retain the old attribute for callers created against earlier
            # builds while using the orientation-correct name internally.
            self.vertical_splitter = self.horizontal_splitter
            # Shared QSplitter chrome: one painted pixel and a separate
            # transparent grab gutter.  Hover/drag feedback changes only the
            # line colour, never the layout thickness.
            self._splitter_theme = splitter_theme(dpg, active=False)
            self._plot_splitter_hover_theme = splitter_theme(dpg, active=True)
            for item in (self.horizontal_splitter, self.file_panel_separator,
                         self.job_plot_separator, self.console_separator):
                dpg.bind_item_theme(item, self._splitter_theme)
            self._splitter_hitbox_theme = splitter_hitbox_theme(dpg)
            for hitbox in (self.horizontal_splitter_hitbox,
                           self.file_panel_separator_hitbox,
                           self.job_plot_separator_hitbox,
                           self.console_separator_hitbox):
                dpg.bind_item_theme(hitbox, self._splitter_hitbox_theme)

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
            dpg.bind_item_theme(item, self._panel_layout_theme)
        dpg.bind_item_theme("winux_primary", self._app_theme)

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
            dpg.create_viewport(**viewport_options)
        except TypeError:
            viewport_options.pop("small_icon", None)
            viewport_options.pop("large_icon", None)
            dpg.create_viewport(**viewport_options)
        dpg.setup_dearpygui()
        dpg.set_primary_window("winux_primary", True)
        dpg.set_exit_callback(self._request_close)
        dpg.set_viewport_resize_callback(self._on_viewport_resize)
        ExplorerListView._external_cursor_provider = (
            self._splitter_native_cursor_provider)

        # Start hang detection only after native/Dear PyGui construction has
        # completed.  Slow first-time imports must not be reported as a UI hang.
        self._watchdog = UIHangWatchdog()
        self._watchdog.add_snapshot_provider(
            "ui_dispatcher", self._dispatcher.snapshot)

        # Start floating-dialog workers as soon as the main DPG context is
        # ready.  The old path waited until after the viewport had already been
        # shown and rendered two frames, so an early Settings/Login/etc. click
        # frequently missed the warm pool and paid a full ``abaqus python``
        # process launch.  Preparation is asynchronous and never blocks this
        # constructor or the main UI thread.
        from .dialogs.prewarm_pool import start_dialog_prewarm
        start_dialog_prewarm(self)


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
        """Build native roots with icons on the command items only."""
        with dpg.menu_bar() as menu_bar:
            with dpg.menu(label="File") as file_menu:
                self._add_icon_menu_item(
                    file_menu, "Log-In...", "Login", self.show_login)
                self._add_icon_menu_item(
                    file_menu, "Site Manager...", "Login",
                    lambda: self.callbacks["site_manager"]())
                self._add_icon_menu_item(
                    file_menu, "Settings...", "Settings", self.show_settings)
                dpg.add_separator(parent=file_menu)
                self._add_icon_menu_item(
                    file_menu, "Exit", "Exit", self._request_close)

            with dpg.menu(label="Bookmarks") as bookmarks_menu:
                self._add_icon_menu_item(
                    bookmarks_menu, "Add Local Folder", "Folder",
                    lambda: self.callbacks["bookmark_command"]("add_local"))
                self._add_icon_menu_item(
                    bookmarks_menu, "Add Server Folder", "Folder",
                    lambda: self.callbacks["bookmark_command"]("add_server"))
                dpg.add_separator(parent=bookmarks_menu)
                self._add_icon_menu_item(
                    bookmarks_menu, "Manage Bookmarks...", "Open_Folder",
                    lambda: self.callbacks["bookmark_command"]("manage"))

            with dpg.menu(label="Commands") as commands_menu:
                self._add_icon_menu_item(
                    commands_menu, "Synchronize Preview...", "Refresh",
                    lambda: self.callbacks["sync_preview"]())

            with dpg.menu(label="View") as view_menu:
                self.console_menu_item = self._add_icon_toggle_menu_item(
                    view_menu, "Console", "CommandWindow",
                    self._console_dock_visible, self._console_menu_toggled)
                self._add_icon_menu_item(
                    view_menu, "Transfer Center", "Download",
                    self.show_transfer_center)
                dpg.add_separator(parent=view_menu)
                self._add_icon_menu_item(
                    view_menu, "Job Schedule", "JobViewer",
                    self.show_job_schedule)

            with dpg.menu(label="Help") as help_menu:
                self._add_icon_menu_item(
                    help_menu, "Manual", "Question", self.show_manual)
                self._add_icon_menu_item(
                    help_menu, "Diagnostics...", "Information",
                    self.show_diagnostics)
                dpg.add_separator(parent=help_menu)
                self._add_icon_menu_item(
                    help_menu, "About Winux", "Information",
                    self.show_about)
        # Dear ImGui owns the menus, but explicitly restore the roomy WinUx/
        # WinSCP-era density.  Leaving this unbound inherits the app-wide compact
        # ItemSpacing and produces the cramped "FileBookmarksCommands" look.
        menu_theme = resource_menu_theme()
        dpg.bind_item_theme(menu_bar, menu_theme)
        for root_menu in (file_menu, bookmarks_menu, commands_menu, view_menu, help_menu):
            dpg.bind_item_theme(root_menu, menu_theme)
        return menu_bar

    @staticmethod
    def _add_icon_menu_item(parent, label, icon_name, callback):
        """Add one fixed-width menu command with a context-menu-sized icon."""
        with dpg.group(
                parent=parent, horizontal=True, horizontal_spacing=7):
            texture = ResourceTextures.get(icon_name)
            if texture:
                dpg.add_image(
                    texture, width=18, height=18, track_offset=0.5)
            else:
                dpg.add_spacer(width=18, height=18)
            # A native menu item sizes itself from its content over successive
            # frames when it shares a row with another widget. An explicitly
            # sized selectable gives the popup its final width immediately.
            return dpg.add_selectable(
                label=label,
                width=188,
                callback=WinUXView._run_icon_menu_item,
                user_data=callback,
            )

    @staticmethod
    def _add_icon_toggle_menu_item(parent, label, icon_name, checked, callback):
        with dpg.group(
                parent=parent, horizontal=True, horizontal_spacing=7):
            texture = ResourceTextures.get(icon_name)
            if texture:
                dpg.add_image(
                    texture, width=18, height=18, track_offset=0.5)
            else:
                dpg.add_spacer(width=18, height=18)
            return dpg.add_selectable(
                label=label, width=188, default_value=bool(checked),
                callback=WinUXView._run_icon_toggle_menu_item,
                user_data=callback,
            )

    @staticmethod
    def _run_icon_toggle_menu_item(sender=None, app_data=None, user_data=None):
        if callable(user_data):
            user_data(bool(app_data))

    @staticmethod
    def _run_icon_menu_item(sender=None, app_data=None, user_data=None):
        # Selectables close menu popups by default. Reset their stored state so
        # the command is not still highlighted when the menu is opened again.
        if sender is not None:
            try:
                dpg.set_value(sender, False)
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
            dpg.show_viewport()
            log_event("Dear PyGui viewport shown")

            # Dear PyGui does not know the final native client/content
            # dimensions until at least one frame has been rendered. Applying
            # the layout before that first frame uses provisional sizes.
            if dpg.is_dearpygui_running():
                dpg.render_dearpygui_frame()
            log_event("Dear PyGui first frame rendered")

            self._pending_viewport_size = None
            self._resize_last_event = 0.0
            self._layout_dirty = True
            self._apply_split_layout(force=True)

            # Commit the fitted dimensions before normal event processing.
            if dpg.is_dearpygui_running():
                dpg.render_dearpygui_frame()

            log_event("Dear PyGui render loop started")
            # Floating-dialog prewarm starts during view construction, before
            # the first visible interaction can request a dialog.
            while dpg.is_dearpygui_running() and self._alive:
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
                if dpg.is_dearpygui_running():
                    dpg.stop_dearpygui()
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
                dpg.destroy_context()
                log_event("Dear PyGui context destroyed")
            except Exception:
                log_exception(
                    "Failed to destroy Dear PyGui context",
                    sys.exc_info(),
                    fatal=False,
                )

    def mainloop(self):
        self.run()

    def update(self):
        if self._watchdog is not None:
            self._watchdog.beat()

        # Native dialogs do not belong to Dear PyGui's item tree.  Treat them
        # as a real Qt foreground surface: a modal blocks the complete parent;
        # a modeless/tool window blocks the covered screen region.  Clear any
        # DPG pointer grab that was active before the native window appeared.
        native_input_blocked = native_background_input_blocked()
        if native_input_blocked:
            release_pointer_input()
            self._drain_dpg_callbacks(discard=True)
        else:
            # Splitter arbitration must happen before Dear PyGui's global
            # ListView callbacks are drained; otherwise the same physical press
            # can become both a divider resize and a file drag/drop.
            self._pre_dispatch_splitter_input()
            self._drain_dpg_callbacks()
            self._update_file_panel_splitter_input()
        if not self._alive:
            return
        if self._console_native_wndproc_callback is None:
            self._install_console_character_hook()
        self._drain_queue()
        if not self._alive:
            return
        if self._startup_layout_frames > 0:
            self._startup_layout_frames -= 1
            self._layout_dirty = True
            self._apply_split_layout(force=True)
        elif self._layout_dirty:
            self._apply_split_layout()
        if not native_input_blocked:
            # QTabBar-like drag/reorder must claim the pointer before splitters
            # or Explorer panes poll global mouse state, otherwise a tab tear-
            # off can simultaneously resize/select widgets underneath it.
            dock_manager = getattr(self, "plot_dock_manager", None)
            if dock_manager is not None:
                dock_manager.update_interaction()
            # Border/corner resizing claims the pointer before splitters poll
            # the global mouse state, matching native Qt mouse-grab behaviour.
            self._update_floating_plot_resize_interaction()
            self._update_floating_console_resize_interaction()
            self._update_horizontal_splitter_input()
            self._update_job_plot_splitter_input()
            self._update_console_splitter_input()
            self._update_floating_plot_docking()
            self._update_floating_console_docking()
            # Inline rename focus/selection cannot depend on per-ListView frame
            # callbacks: Dear PyGui provides only one callback slot per frame.
            for panel in self.panels:
                panel.listview._process_inline_rename_focus()
        self._sync_job_plot_windows()
        self._sync_horizontal_panel_divider()
        if dpg.is_dearpygui_running():
            self._rendering = True
            try:
                dpg.render_dearpygui_frame()
            finally:
                self._rendering = False
                self._render_generation += 1
            # Use freshly rendered geometry and service deferred layouts here.
            # DPG only has one frame-callback slot: a replaced callback must
            # not leave column/canvas sizes stale and hide overflow scrollers.
            for listview in [panel.listview for panel in self.panels] + [self.jobs_view.listview]:
                if listview._resize_layout_pending:
                    listview._layout_all()
                overlay = getattr(listview, "_scroller_arrow_overlay", None)
                if overlay is not None:
                    overlay.update()
            self._drain_after_render_callbacks()
        # GLFW may restore its arrow cursor while rendering. Apply splitter
        # feedback only when Dear PyGui owns pointer input; otherwise the
        # foreground native dialog is authoritative for cursor feedback.
        if not native_input_blocked:
            self._update_file_panel_splitter_cursor()
            self._update_horizontal_splitter_cursor()
            self._update_job_plot_splitter_cursor()
            self._update_console_splitter_cursor()
            self._apply_floating_plot_resize_cursor()
        if self._watchdog is not None:
            self._watchdog.beat()


    def after(self, delay, callback, *args):
        return self._dispatcher.after(delay, callback, *args)

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
        ready = []
        pending = []
        for generation, callback, args in self._after_render_callbacks:
            if generation <= self._render_generation:
                ready.append((callback, args))
            else:
                pending.append((generation, callback, args))
        self._after_render_callbacks = pending
        for callback, args in ready:
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
        queued = dpg.get_callback_queue() or ()
        if discard:
            self._dpg_callbacks.clear()
            return
        self._dpg_callbacks.extend(queued)
        # A shared deque permits a blocking modal to pump input recursively
        # without replaying the outer callback batch or starving its buttons.
        while self._dpg_callbacks and self._alive:
            # A callback can itself open a native modal. Stop immediately and
            # discard the remainder of the same physical input batch.
            native_gate = globals().get("native_background_input_blocked")
            if callable(native_gate) and native_gate():
                self._dpg_callbacks.clear()
                break
            job = self._dpg_callbacks.popleft()
            try:
                invoke_callback_job(job)
            except Exception:
                callback = job[0] if isinstance(job, (tuple, list)) and job else None
                self._handle_ui_callback_error(callback, sys.exc_info())

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
            log_exception(
                "Failed to display a UI callback error",
                sys.exc_info(),
                fatal=True,
            )
            raise

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
        ``dpg.destroy_context``.  Calling those APIs while the UI dispatcher is
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
            if not self._rendering and dpg.is_dearpygui_running():
                dpg.stop_dearpygui()
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
            self, path, items, host, reset_history=False, **kwargs):
        if reset_history:
            self.right.history = []
            self.right.history_index = -1
        self.right.status_prefix = str(host)
        self.right.display(path, items)

    def display_jobs(self, jobs):
        self.jobs_view.display(jobs)
        dialog = getattr(self, "job_manager_dialog", None)
        if dialog is not None:
            dialog.job_view_updated(jobs)

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
        center = self.show_transfer_center()
        return center.add_task(operation, cancel_event, items=items)

    def show_transfer_center(self):
        center = getattr(self, "transfer_center_dialog", None)
        if center is None or not center.winfo_exists():
            center = _dialog_type("TransferCenterDialog")(self)
            self.transfer_center_dialog = center
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
        current = getattr(self, "_async_confirm_dialog", None)
        if current is not None and current.winfo_exists():
            current.lift()
            return current

        def completed(value):
            self._async_confirm_dialog = None
            callback(value)

        dialog = _dialog_type("BlockingDialog")(
            self, title, message, "confirm", on_result=completed,
            primary_text=primary_text,
            secondary_text=secondary_text,
            intent=intent)
        self._async_confirm_dialog = dialog
        dialog.lift()
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
        """Open the Dear ImGui local-folder browser as a real floating dialog."""
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
        return self.settings_dialog

    def show_bookmarks(self, entries, on_open, on_remove, on_rename):
        dialog = getattr(self, "bookmarks_dialog", None)
        if dialog is not None and dialog.winfo_exists():
            dialog.refresh(entries)
            dialog.lift()
            return dialog
        self.bookmarks_dialog = _dialog_type("BookmarksDialog")(
            self, entries, on_open, on_remove, on_rename)
        self.bookmarks_dialog.show()
        return self.bookmarks_dialog

    def show_site_manager(self, sites, on_save, on_delete, on_connect):
        dialog = getattr(self, "site_manager_dialog", None)
        if dialog is not None and dialog.winfo_exists():
            dialog.refresh(sites)
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
            dialog.refresh(rows, local_path, server_path)
            dialog.lift()
            return dialog
        self.sync_preview_dialog = _dialog_type("SyncPreviewDialog")(
            self, rows, local_path, server_path, on_refresh, on_transfer)
        self.sync_preview_dialog.show()
        return self.sync_preview_dialog

    def show_diagnostics(self):
        dialog = getattr(self, "diagnostics_dialog", None)
        if dialog is not None and dialog.winfo_exists():
            dialog.lift()
            return dialog
        self.diagnostics_dialog = _dialog_type("DiagnosticsDialog")(self)
        return self.diagnostics_dialog


    def show_job_schedule(self):
        dialog = getattr(self, "job_schedule_dialog", None)
        if dialog is not None and dialog.winfo_exists():
            dialog.refresh()
            dialog.lift()
            return dialog
        self.job_schedule_dialog = _dialog_type("JobScheduleDialog")(
            self, self.callbacks["job_schedule"],
            self.callbacks["job_schedule_command"],
        )
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
