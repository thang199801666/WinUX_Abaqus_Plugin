"""Public component API with lazy backend imports.

UI components are imported lazily so lightweight services can use the package
without eagerly loading the Dear PyGui native extension.
"""

from __future__ import annotations

from importlib import import_module


_LAZY_COMPONENTS = {
    "SharedScrollerMetrics": ("DearUIQt.backends.dearpygui", "SharedScrollerMetrics"),
    "SharedScrollerPalette": ("DearUIQt.backends.dearpygui", "SharedScrollerPalette"),
    "DpgScrollerArrowOverlay": ("DearUIQt.backends.dearpygui", "DpgScrollerArrowOverlay"),
    "add_dpg_scroller_style": ("DearUIQt.backends.dearpygui", "add_dpg_scroller_style"),
    "configure_ttk_scroller_styles": ("DearUIQt.backends.dearpygui", "configure_ttk_scroller_styles"),
    "make_ttk_scroller": ("DearUIQt.backends.dearpygui", "make_ttk_scroller"),
    "ExplorerListView": (".explorer_list_view", "ExplorerListView"),
    "ExplorerHeaderView": (".explorer_header_view", "ExplorerHeaderView"),
    "ListViewItem": (".explorer_list_view", "ListViewItem"),
    "apply_white_explorer_theme": (".explorer_list_view", "apply_white_explorer_theme"),
    "reset_explorer_runtime_resources": (".explorer_list_view", "reset_explorer_runtime_resources"),
    "FilePanel": (".file_panel", "FilePanel"),
    "DockWidget": ("DearUIQt.widgets", "DockWidget"),
    "DockDropPreview": ("DearUIQt.docking", "DockDropPreview"),
    "DockManager": ("DearUIQt.widgets", "DockManager"),
    "FloatingWindowResizer": ("DearUIQt.docking.floating_window_resizer", "FloatingWindowResizer"),
    "JobsView": (".jobs_view", "JobsView"),
    "JobPlotsWindow": (".job_plots", "JobPlotsWindow"),
    "reset_pointer_input_gate": ("DearUIQt.input_gate", "reset_pointer_input_gate"),
    "QtComboBox": ("DearUIQt.widgets", "QtComboBox"),
    "ResourceMenuBar": (".toolbar", "ResourceMenuBar"),
    "ResourceTextures": (".toolbar", "ResourceTextures"),
    "add_resource_button": (".toolbar", "add_resource_button"),
    "reset_toolbar_runtime_resources": (".toolbar", "reset_toolbar_runtime_resources"),
}

__all__ = [
    "SharedScrollerMetrics",
    "DpgScrollerArrowOverlay",
    "add_dpg_scroller_style",
    "SharedScrollerPalette",
    "ExplorerListView",
    "ExplorerHeaderView",
    "ListViewItem",
    "apply_white_explorer_theme",
    "reset_component_runtime_resources",
    "FilePanel",
    "DockWidget",
    "DockDropPreview",
    "DockManager",
    "FloatingWindowResizer",
    "JobsView",
    "JobPlotsWindow",
    "ResourceMenuBar",
    "ResourceTextures",
    "add_resource_button",
]


def __getattr__(name):
    target = _LAZY_COMPONENTS.get(name)
    if target is None:
        raise AttributeError(
            "module {!r} has no attribute {!r}".format(__name__, name))
    module_name, attribute_name = target
    value = getattr(import_module(module_name, __name__), attribute_name)
    globals()[name] = value
    return value


def __dir__():
    return sorted(set(globals()) | set(__all__) | set(_LAZY_COMPONENTS))


def reset_component_runtime_resources():
    """Reset cached Dear PyGui tags after a context is destroyed.

    Imports stay local so standalone non-DPG helpers can import this package
    without loading the Dear PyGui native extension.
    """
    __getattr__("reset_explorer_runtime_resources")()
    __getattr__("reset_toolbar_runtime_resources")()
    __getattr__("reset_pointer_input_gate")()
