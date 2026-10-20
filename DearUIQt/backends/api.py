"""Renderer backend contracts used by DearUIQt and host applications."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable


class BackendCapabilityError(RuntimeError):
    pass


@runtime_checkable
class RendererBackend(Protocol):
    """Structural minimum for a retained DearUIQt renderer.

    Concrete widgets request additional capabilities only when they need them;
    this protocol intentionally covers the common retained-item lifecycle.
    """

    def does_item_exist(self, item): ...
    def configure_item(self, item, **kwargs): ...
    def delete_item(self, item): ...
    def set_value(self, item, value): ...
    def get_value(self, item): ...


@dataclass(frozen=True)
class BackendCapabilities:
    retained_items: bool = False
    windows: bool = False
    child_windows: bool = False
    handlers: bool = False
    scrolling: bool = False
    tables: bool = False
    drawing: bool = False
    plots: bool = False
    textures: bool = False
    themes: bool = False
    native_windows: bool = False

    def supports(self, name):
        if not hasattr(self, name):
            raise ValueError("unknown backend capability: {}".format(name))
        return bool(getattr(self, name))


def _has(backend, *names):
    return all(callable(getattr(backend, name, None)) for name in names)


def backend_capabilities(backend):
    if backend is None:
        return BackendCapabilities()
    return BackendCapabilities(
        retained_items=_has(backend, "does_item_exist", "configure_item", "delete_item"),
        windows=_has(backend, "add_window"),
        child_windows=_has(backend, "add_child_window"),
        handlers=_has(backend, "handler_registry") or _has(backend, "item_handler_registry"),
        scrolling=(
            _has(backend, "get_y_scroll", "set_y_scroll") or
            _has(backend, "get_x_scroll", "set_x_scroll")
        ),
        tables=_has(backend, "add_table", "add_table_column"),
        drawing=any(callable(getattr(backend, name, None)) for name in (
            "draw_line", "draw_rectangle", "draw_text", "draw_circle")),
        plots=_has(backend, "add_plot"),
        textures=any(callable(getattr(backend, name, None)) for name in (
            "add_static_texture", "add_dynamic_texture", "add_texture_registry")),
        themes=_has(backend, "theme", "theme_component"),
        native_windows=_has(getattr(backend, "internal_dpg", backend),
            "dearuiqt_enable_native_windows", "dearuiqt_native_windows_enabled",
            "dearuiqt_configure_native_window", "dearuiqt_native_window_handle"),
    )


def require_backend_capability(backend, *names):
    capabilities = backend_capabilities(backend)
    missing = [name for name in names if not capabilities.supports(name)]
    if missing:
        raise BackendCapabilityError(
            "renderer does not provide required capability/capabilities: {}".format(
                ", ".join(missing)))
    return capabilities


__all__ = [
    "RendererBackend", "BackendCapabilities", "BackendCapabilityError",
    "backend_capabilities", "require_backend_capability",
]
