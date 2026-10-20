"""Optional native-toolkit interoperability helpers.

These adapters are public compatibility surfaces for applications that still
host a small Tk/ttk island beside DearUIQt.  Backend-specific implementation
remains inside DearUIQt; consuming applications do not import renderer modules.
"""
from .backends.dearpygui import (
    SharedScrollerMetrics as QNativeScrollerMetrics,
    configure_ttk_scroller_styles,
    make_ttk_scroller,
)

__all__ = [
    "QNativeScrollerMetrics",
    "configure_ttk_scroller_styles",
    "make_ttk_scroller",
]
