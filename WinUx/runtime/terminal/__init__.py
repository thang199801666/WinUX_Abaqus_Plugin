"""Terminal buffer, stream decoding and VT emulation primitives."""
from __future__ import annotations
from importlib import import_module

_LAZY = {
    "TerminalBuffer": (".buffer", "TerminalBuffer"),
    "clean_output": (".buffer", "clean_output"),
    "TerminalStreamReader": (".stream", "TerminalStreamReader"),
    "VTTerminalScreen": (".vt", "VTTerminalScreen"),
    "terminal_text_width": (".vt", "terminal_text_width"),
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
