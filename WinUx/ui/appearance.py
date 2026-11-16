"""One typography setup for WinUx, floating dialogs and detachable tools."""
from __future__ import annotations

import os
from pathlib import Path

from DearUIQt.gui import QFontDatabase
from DearUIQt.runtime import QGuiRuntime
from ..platform.resources import resource_path
from ..preferences.appearance import (
    DEFAULT_UI_FONT_FAMILY, DEFAULT_UI_FONT_SIZE, DEFAULT_UI_FONT_STYLE, DEFAULT_UI_THEME,
    normalize_ui_font_size, normalize_ui_font_style, normalize_ui_theme, resolve_ui_font_paths,
)



def _sync_static_palette_consumers():
    """Update already-imported class-level color aliases without eager imports."""
    import sys
    from DearUIQt.gui.palette import QtFusionPalette, color_scheme

    module = sys.modules.get("DearUIQt.dialogs.theme")
    DialogPalette = getattr(module, "DialogPalette", None) if module else None
    if DialogPalette is not None:
        values = {
            "WINDOW_BG": QtFusionPalette.WINDOW, "SURFACE": QtFusionPalette.BASE,
            "FOOTER": QtFusionPalette.WINDOW, "CHILD_BG": QtFusionPalette.WINDOW,
            "TEXT": QtFusionPalette.TEXT, "MUTED": QtFusionPalette.TEXT_MUTED,
            "TITLE": QtFusionPalette.TEXT, "BORDER": QtFusionPalette.BORDER,
            "FRAME_BG": QtFusionPalette.BASE, "FRAME_HOVER": QtFusionPalette.HIGHLIGHT_HOVER,
            "BUTTON": QtFusionPalette.BUTTON, "BUTTON_HOVER": QtFusionPalette.BUTTON_HOVER,
            "BUTTON_ACTIVE": QtFusionPalette.BUTTON_ACTIVE, "HEADER": QtFusionPalette.TOOLBAR,
            "HEADER_HOVER": QtFusionPalette.HIGHLIGHT_HOVER, "SELECT": QtFusionPalette.HIGHLIGHT_SOFT,
            "SELECT_TEXT": QtFusionPalette.TEXT, "ERROR": QtFusionPalette.DANGER,
            "SUCCESS": QtFusionPalette.SUCCESS,
        }
        for name, value in values.items():
            setattr(DialogPalette, name, value)

    module = sys.modules.get("DearUIQt.docking.dock_manager")
    DockManager = getattr(module, "DockManager", None) if module else None
    if DockManager is not None:
        for name, value in {
            "BG": QtFusionPalette.TITLE, "BORDER": QtFusionPalette.BORDER,
            "ACTIVE_BG": QtFusionPalette.BASE, "ACTIVE_HOVER": QtFusionPalette.WINDOW_ALT,
            "INACTIVE_BG": QtFusionPalette.WINDOW, "INACTIVE_HOVER": QtFusionPalette.BUTTON_HOVER,
            "TEXT": QtFusionPalette.TEXT, "ACCENT": QtFusionPalette.HIGHLIGHT,
            "SPLIT_COLOR": QtFusionPalette.BORDER_LIGHT,
        }.items():
            setattr(DockManager, name, value)

    module = sys.modules.get("DearUIQt.docking.dock_widget")
    DockWidget = getattr(module, "DockWidget", None) if module else None
    if DockWidget is not None:
        DockWidget.TEXT_COLOR = QtFusionPalette.TEXT
        DockWidget.GLYPH_COLOR = QtFusionPalette.TEXT_MUTED

    module = sys.modules.get("WinUx.ui.components.explorer.themes")
    manager = getattr(module, "ListViewThemeManager", None) if module else None
    if manager is not None:
        manager.refresh_application_palette()

    module = sys.modules.get("WinUx.dialogs.selectors.folder_browser_style")
    palette = getattr(module, "BrowserListPalette", None) if module else None
    if palette is not None:
        palette.refresh_application_palette(color_scheme())


def configure_color_scheme(view, preferences=None, *, apply_runtime=False):
    """Select and optionally rebind the WinUx Light/Dark application palette."""
    preferences = preferences or {}
    scheme = normalize_ui_theme(preferences.get("ui_theme", DEFAULT_UI_THEME))
    from DearUIQt.gui.palette import color_scheme as active_color_scheme, set_color_scheme
    previous_scheme = active_color_scheme()
    scheme = set_color_scheme(scheme)
    _sync_static_palette_consumers()
    view.ui_theme = scheme

    # Theme resources are retained native objects.  Whenever the process palette
    # changes, forget every palette-derived cache before any live dialog/control
    # asks for its replacement theme.  This is required in floating dialog hosts
    # as well as in the main WinUx process.
    if scheme != previous_scheme:
        try:
            from DearUIQt.dialogs.theme import invalidate_dialog_theme_cache
            invalidate_dialog_theme_cache()
        except Exception:
            pass
        try:
            from DearUIQt.modelview.themes import invalidate_modelview_theme_cache
            invalidate_modelview_theme_cache()
        except Exception:
            pass
        try:
            from DearUIQt.widgets.menu import invalidate_menu_theme_cache
            invalidate_menu_theme_cache()
        except Exception:
            pass
        try:
            from DearUIQt.tooltip import invalidate_tooltip_theme_cache
            invalidate_tooltip_theme_cache()
        except Exception:
            pass

    if not apply_runtime:
        return scheme

    # Retained theme resources already materialized under the previous scheme
    # cannot be recolored in place. Create scheme-specific resources and rebind
    # the live top-level surfaces and list controls.
    try:
        from DearUIQt.themes import (
            application_theme, compact_layout_surface_theme, floating_window_theme,
        )
        app_theme = application_theme()
        view._app_theme = app_theme
        runtime = getattr(view, "_gui_runtime", None)
        if runtime is not None:
            runtime.setApplicationTheme(app_theme)
        main_window = getattr(view, "_main_window", None)
        if main_window is not None:
            main_window.setTheme(app_theme)
            # Main-window controls are retained across Settings changes.  Walk
            # the QObject-owned QWidget tree and ask stateful controls to
            # rematerialize palette-derived themes.  Application-owned raw
            # surfaces (Explorer, dock panels, etc.) are refreshed explicitly
            # below because they are not all QObject children of QMainWindow.
            try:
                from DearUIQt.widgets import QWidget
                for widget in main_window.findChildren(QWidget):
                    try:
                        refresh = getattr(widget, "refreshTheme", None)
                        if callable(refresh):
                            refresh()
                            continue
                        refresh = getattr(widget, "_refresh_style", None)
                        if callable(refresh):
                            refresh()
                    except Exception:
                        pass
            except Exception:
                pass
        menu_bar = getattr(view, "_menu_bar_wrapper", None)
        refresh_menu = getattr(menu_bar, "refreshTheme", None)
        if callable(refresh_menu):
            refresh_menu()
        view._panel_layout_theme = compact_layout_surface_theme()
        view._floating_dock_window_theme = floating_window_theme()
        try:
            from DearUIQt.widgets import QRetainedItem
            for tag in (
                getattr(view, "layout_root", None), getattr(view, "session_tabs_region", None),
                getattr(view, "top_region", None),
                getattr(view, "file_panels_table", None), getattr(view, "left_parent", None),
                getattr(view, "right_parent", None), getattr(view, "file_status_region", None),
                getattr(view, "left_status_window", None), getattr(view, "right_status_window", None),
                getattr(view, "bottom_region", None), getattr(view, "plot_region", None),
                getattr(view, "console_region", None),
            ):
                if tag is not None:
                    QRetainedItem(tag).setTheme(view._panel_layout_theme)
        except Exception:
            pass
        try:
            from .components.toolbar import file_status_bar_theme, file_status_text_theme
            for frame_name in ("_file_status_frame", "_left_status_frame", "_right_status_frame"):
                frame = getattr(view, frame_name, None)
                if frame is not None:
                    frame.setTheme(file_status_bar_theme())
            for label_name, muted in (
                ("_left_items_label", False), ("_left_selected_label", True),
                ("_right_items_label", False), ("_right_selected_label", True),
            ):
                label = getattr(view, label_name, None)
                if label is not None:
                    label.setTheme(file_status_text_theme(muted=muted))
        except Exception:
            pass
    except Exception:
        pass

    try:
        from .components.toolbar import invalidate_toolbar_theme_cache
        invalidate_toolbar_theme_cache()
    except Exception:
        pass
    session_tabs = getattr(view, "session_tabs", None)
    if session_tabs is not None:
        try:
            session_tabs.apply_theme()
        except Exception:
            pass
    for panel in getattr(view, "panels", ()):
        try:
            panel.apply_theme()
        except Exception:
            pass
    jobs = getattr(view, "jobs_view", None)
    if jobs is not None:
        try:
            refresh = getattr(jobs, "refreshTheme", None)
            if callable(refresh):
                refresh()
            else:
                listview = getattr(jobs, "listview", None)
                if listview is not None:
                    listview.set_theme(listview.get_theme())
        except Exception:
            pass
    compact = getattr(view, "_compact_job_monitor", None)
    if compact is not None:
        try:
            refresh = getattr(compact, "refreshTheme", None)
            if callable(refresh):
                refresh()
            else:
                listview = getattr(compact, "listview", None)
                if listview is not None:
                    listview.set_theme(listview.get_theme())
        except Exception:
            pass
    console_panel = getattr(view, "console_panel", None)
    if console_panel is not None:
        try:
            console_panel.refreshTheme()
        except Exception:
            pass
    console_dock = getattr(view, "console_dock", None)
    if console_dock is not None:
        try:
            console_dock.refreshTheme()
        except Exception:
            pass

    # Job Plot docks are lazy retained clients and are not QObject children of
    # QMainWindow. Refresh both live jobs and the empty placeholder so dock
    # title chrome/toolbars/menus never keep the previous palette.
    plot_windows = list((getattr(view, "job_plot_windows", {}) or {}).values())
    placeholder = getattr(view, "_empty_job_plot_window", None)
    if placeholder is not None:
        plot_windows.append(placeholder)
    seen_plots = set()
    for plot_window in plot_windows:
        if plot_window is None or id(plot_window) in seen_plots:
            continue
        seen_plots.add(id(plot_window))
        try:
            refresh = getattr(plot_window, "refreshTheme", None)
            if callable(refresh):
                refresh()
                continue
            dock = getattr(plot_window, "dock", None)
            refresh = getattr(dock, "refreshTheme", None)
            if callable(refresh):
                refresh()
        except Exception:
            pass
    try:
        from .native.native_dialog_host import apply_native_theme_chrome
        resolver = getattr(view, "_find_main_viewport_hwnd", None)
        hwnd = int(resolver() or 0) if callable(resolver) else 0
        if hwnd:
            apply_native_theme_chrome(hwnd)
    except Exception:
        pass

    # Rebind every in-process QDialog immediately.  Floating dialogs live in a
    # different renderer process, so broadcast the same palette change over the
    # existing dialog IPC channel as well.
    try:
        from DearUIQt.dialogs.qt_dialog import refresh_open_dialog_themes
        refresh_open_dialog_themes()
    except Exception:
        pass
    for dialog in tuple(getattr(view, "_floating_dialogs", ())):
        try:
            if not getattr(dialog, "_closed", False):
                dialog.post_latest("set_theme", scheme)
        except Exception:
            pass
    return scheme

def configure_ui_context(view, preferences=None, *, load_terminal=True):
    """Install the saved application font on the active DearUIQt context.

    ``preferences`` may be the already-loaded ``GeneralPreferences`` dictionary
    so the main window does not re-read settings.json during startup. Floating
    hosts and standalone tools can omit it and load the shared preference once.
    """
    runtime = QGuiRuntime()
    runtime.configureApplication(manual_callback_management=True)
    if preferences is None:
        try:
            from ..preferences.general import GeneralPreferences
            preferences = GeneralPreferences().load()
        except Exception:
            preferences = {}
    preferences = preferences or {}
    # Every UI context (main window, floating dialog worker, standalone tool)
    # selects the persisted palette before creating controls.  This prevents a
    # dark application from spawning a light first frame/dialog.
    configure_color_scheme(view, preferences, apply_runtime=False)
    requested_family = preferences.get("ui_font_family", DEFAULT_UI_FONT_FAMILY)
    size = normalize_ui_font_size(
        preferences.get("ui_font_size", DEFAULT_UI_FONT_SIZE))
    style = normalize_ui_font_style(requested_family, preferences.get("ui_font_style", DEFAULT_UI_FONT_STYLE))
    family, body_path, heading_path = resolve_ui_font_paths(requested_family, style)
    if body_path is None:
        # Non-Windows/test hosts can still run with Dear ImGui's default font.
        view.ui_font_family = family
        view.ui_font_size = size
        view.ui_font_style = style
        return False

    database = QFontDatabase()
    body_font = database.addApplicationFont(body_path, size)
    if body_font is None:
        view.ui_font_family = family
        view.ui_font_size = size
        view.ui_font_style = style
        return False

    old_database = getattr(view, "_font_database", None)
    view._font_database = database
    view.body_qfont = body_font
    view.body_font = body_font.nativeId()

    heading_font = None
    if heading_path is not None:
        heading_font = database.addApplicationFont(heading_path, size)
    if heading_font is None:
        heading_font = body_font
    view.heading_qfont = heading_font
    view.heading_font = heading_font.nativeId()

    if load_terminal:
        terminal_path = Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts" / "consola.ttf"
        if terminal_path.is_file():
            terminal_font = database.addApplicationFont(terminal_path, size)
            if terminal_font is not None:
                view.terminal_qfont = terminal_font
                view.terminal_font = terminal_font.nativeId()

    runtime.setApplicationFont(body_font)
    # Font changes are a geometry change, not paint-only.  Feed the measured
    # line height into DearUIQt control metrics, then refresh live controls so
    # buttons/editors/combos remain vertically centred at every font size.
    try:
        from DearUIQt.gui.style import set_application_typography
        from DearUIQt.widgets.widget import QWidget
        set_application_typography(runtime.backend, body_font)
        QWidget.refreshApplicationTypography(runtime.backend)
    except Exception:
        pass
    view.ui_font_family = family
    view.ui_font_size = size
    view.ui_font_style = style

    # The old atlas cannot be dropped before the new application font is bound.
    # Keep it alive if the renderer/view still references explicit old font ids;
    # normal startup has no old database at all.
    if old_database is not None and old_database is not database:
        retained = getattr(view, "_retired_font_databases", None)
        if retained is None:
            retained = view._retired_font_databases = []
        retained.append(old_database)
        # Keep a couple of generations alive so renderer commands from the
        # current/previous frame cannot reference a deleted atlas, but never
        # retain every font change for the lifetime of the application.
        while len(retained) > 3:
            stale = retained.pop(0)
            try:
                stale.delete()
            except Exception:
                pass
    return True


def viewport_icon_options():
    """Use the WinUx application icon for every native tool/dialog viewport."""
    icon = resource_path("WinUx.ico")
    return {"small_icon": str(icon), "large_icon": str(icon)} if icon.is_file() else {}
