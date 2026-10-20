"""Small lazy-export helper used by DearUIQt's public namespaces.

The public packages (core/gui/widgets/layouts/modelview) deliberately avoid
importing the Dear PyGui backend until a concrete widget is constructed.
"""
from __future__ import annotations

from importlib import import_module


def resolve(module_globals, package, exports, name):
    target = exports.get(name)
    if target is None:
        raise AttributeError("module {!r} has no attribute {!r}".format(package, name))
    module_name, attr = target if isinstance(target, tuple) else (target, name)
    value = getattr(import_module(module_name, package), attr)
    module_globals[name] = value
    return value


def namespace_dir(module_globals, exports):
    return sorted(set(module_globals) | set(exports))
