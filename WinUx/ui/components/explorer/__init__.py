"""Explorer-style list view components and interaction primitives."""
from __future__ import annotations
from importlib import import_module

_LAZY = {
    "ExplorerListView": (".list_view", "ExplorerListView"),
    "ListViewItem": (".list_view", "ListViewItem"),
    "ExplorerHeaderView": (".header_view", "ExplorerHeaderView"),
    "ListViewTheme": (".themes", "ListViewTheme"),
    "ListViewThemeManager": (".themes", "ListViewThemeManager"),
    "apply_white_explorer_theme": (".list_view", "apply_white_explorer_theme"),
    "reset_explorer_runtime_resources": (".list_view", "reset_explorer_runtime_resources"),
}
__all__ = list(_LAZY)

def __getattr__(name):
    target = _LAZY.get(name)
    if target is None:
        raise AttributeError(name)
    module_name, attribute_name = target
    value = getattr(import_module(module_name, __name__), attribute_name)
    globals()[name] = value
    return value

def __dir__():
    return sorted(set(globals()) | set(__all__))
