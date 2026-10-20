"""QtWidgets-compatible facade over DearUIQt's public widget namespaces."""
from . import widgets as _widgets
from . import layouts as _layouts
from . import modelview as _modelview

_NAMESPACES = (_widgets, _layouts, _modelview)
__all__ = list(dict.fromkeys(
    name for namespace in _NAMESPACES for name in namespace.__all__
))

def __getattr__(name):
    if name not in __all__:
        raise AttributeError("module {!r} has no attribute {!r}".format(__name__, name))
    for namespace in _NAMESPACES:
        if name in namespace.__all__:
            value = getattr(namespace, name)
            globals()[name] = value
            return value
    raise AttributeError(name)

def __dir__():
    return sorted(set(globals()) | set(__all__))
