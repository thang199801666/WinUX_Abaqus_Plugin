"""Shared modal registry, independent of Explorer or other application views."""
from .backends import dpg
from .input_gate import register_pointer_protected_item, unregister_pointer_protected_item

MODAL_TAGS = set()


def register_modal_window(tag):
    if tag is not None:
        MODAL_TAGS.add(tag)
        register_pointer_protected_item(tag)
    return tag


def unregister_modal_window(tag):
    MODAL_TAGS.discard(tag)
    unregister_pointer_protected_item(tag)


def visible_modal_window_exists():
    stale = []
    for item in tuple(MODAL_TAGS):
        try:
            if not dpg.does_item_exist(item):
                stale.append(item)
            elif dpg.is_item_shown(item):
                return True
        except Exception:
            stale.append(item)
    for item in stale:
        unregister_modal_window(item)
    try:
        getter = getattr(dpg, "get_windows", None)
        items = getter() if getter is not None else dpg.get_all_items()
        for item in items:
            try:
                config = dpg.get_item_configuration(item) or {}
                if config.get("modal", False) and dpg.is_item_shown(item):
                    return True
            except Exception:
                continue
    except Exception:
        pass
    return False
