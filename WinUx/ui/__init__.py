"""WinUx-specific UI composition built on top of :mod:`DearUIQt`.

Reusable widgets and Qt-style infrastructure live physically in the root-level
`DearUIQt/` package.  This module contains only WinUx application adapters,
behaviors and hosting services, while temporarily re-exporting DearUIQt names
for compatibility with older integrations.
"""
from importlib import import_module
import DearUIQt as _DearUIQt

_APP_LAZY_EXPORTS = {
    "FileDialog": ".file_dialog", "FileSelector": ".file_dialog",
    "configure_ui_context": ".appearance", "viewport_icon_options": ".appearance",
    "CanvasCursor": ".cursor", "apply_tool_cursor": ".cursor",
    "ToolWorkspace": ".workspace", "ToolPanel": ".workspace", "ToolBar": ".workspace",
    "ToolCommandRow": ".workspace", "style_image_canvas": ".workspace",
    "style_tool_surface": ".workspace", "item_rect": ".workspace",
    # WinUx configures resources/icons around the generic DearUIQt ribbon.
    "RibbonBar": ".ribbon",
    "SplitterLayoutMixin": ".behaviors", "PlotDockingMixin": ".behaviors",
    "ConsoleDockingMixin": ".behaviors", "PointerRoutingMixin": ".behaviors",
    "FloatingDialogController": ".hosting.floating_dialog",
    "ResultDialog": ".hosting.result_dialog",
    "DialogPrewarmPool": ".hosting.host",
    "QDialogHost": ".hosting.host", "QDialogHostPool": ".hosting.host",
    "QDialogLease": ".hosting.host", "QDialogHostManager": ".hosting.host",
}

__all__ = list(dict.fromkeys([*_APP_LAZY_EXPORTS, *_DearUIQt.__all__]))
__version__ = "2.0.0"


def __getattr__(name):
    module_name = _APP_LAZY_EXPORTS.get(name)
    if module_name is not None:
        value = getattr(import_module(module_name, __name__), name)
        globals()[name] = value
        return value
    try:
        value = getattr(_DearUIQt, name)
    except AttributeError:
        raise AttributeError("module {!r} has no attribute {!r}".format(__name__, name))
    globals()[name] = value
    return value


def __dir__():
    return sorted(set(globals()) | set(__all__))
