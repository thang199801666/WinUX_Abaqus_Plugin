"""Public styling/theme namespace for DearUIQt applications.

Theme factories remain renderer-aware, but applications no longer need to
import implementation modules from ``DearUIQt.qt`` or dialog internals.
"""
from .._lazy import resolve, namespace_dir

_EXPORTS = {
    # Declarative renderer-neutral theme specification API
    "ThemeTarget": ".spec", "ThemeColor": ".spec", "ThemeStyle": ".spec",
    "ThemeComponentSpec": ".spec", "ThemeSpec": ".spec",
    "QTheme": ".resource",
    "theme_component": ".spec", "theme_spec": ".spec",
    "create_theme": ".spec", "make_theme": ".spec", "with_scrollbar": ".spec",
    # Core widget/style metrics and factories
    "METRICS": "..gui.style",
    "application_theme": ".factories",
    "fusion_desktop_theme": ".factories",
    "worksheet_theme_spec": ".factories",
    "inline_editor_theme_spec": ".factories",
    "button_theme": ".factories",
    "splitter_theme": ".factories",
    "splitter_hitbox_theme": ".factories",
    "panel_surface_theme": ".factories",
    "plot_surface_theme": ".factories",
    "panel_header_theme": ".factories",
    "status_text_theme": ".factories",
    "text_theme": ".factories",
    "tool_bar_theme": ".factories",
    "tool_button_theme": ".factories",
    "path_bar_theme": ".factories",
    "status_bar_theme": ".factories",
    "menu_bar_theme": ".factories",
    "command_button_theme": ".factories",
    "menu_surface_theme": ".factories",
    "menu_button_theme": ".factories",
    "menu_image_button_theme": ".factories",
    "viewport_surface_theme": ".factories",
    "compact_layout_surface_theme": ".factories",
    "floating_window_theme": ".factories",
    "compact_stack_theme": ".factories",
    "aligned_cell_theme": ".factories",
    "transparent_header_cell_theme": ".factories",
    "transfer_list_theme": ".factories",
    "transfer_row_theme": ".factories",
    "form_row_theme": ".factories",
    "transfer_progress_host_theme": ".factories",
    "transfer_progress_text_theme": ".factories",
    "progress_theme": ".factories",
    "transfer_status_text_theme": ".factories",
    # Dialog design tokens/themes
    "DialogMetrics": "..dialogs.theme",
    "body_theme": "..dialogs.theme",
    "surface_theme": "..dialogs.theme",
    "muted_text_theme": "..dialogs.theme",
    "error_text_theme": "..dialogs.theme",
}

__all__ = list(_EXPORTS)

def __getattr__(name):
    return resolve(globals(), __name__, _EXPORTS, name)

def __dir__():
    return namespace_dir(globals(), _EXPORTS)
