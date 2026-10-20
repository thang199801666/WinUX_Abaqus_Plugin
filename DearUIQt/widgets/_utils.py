"""Shared internal helpers for retained Dear ImGui controls."""
from __future__ import annotations

def _bind_focus_state_handlers(backend, item, callback):
    """Bind passive focus/activation handlers without changing ImGui focus.

    The callbacks only refresh visual state.  They never call ``focus_item``
    from a mouse event, which keeps native InputText caret placement intact.
    """
    try:
        with backend.item_handler_registry() as registry:
            if hasattr(backend, "add_item_focus_handler"):
                backend.add_item_focus_handler(callback=callback)
            if hasattr(backend, "add_item_activated_handler"):
                backend.add_item_activated_handler(callback=callback)
            if hasattr(backend, "add_item_deactivated_handler"):
                backend.add_item_deactivated_handler(callback=callback)
        backend.bind_item_handler_registry(item, registry)
        return registry
    except Exception:
        return None


def _delete_aux_item(backend, item):
    try:
        if item and backend.does_item_exist(item):
            backend.delete_item(item)
    except Exception:
        pass



__all__ = ["_bind_focus_state_handlers", "_delete_aux_item"]
