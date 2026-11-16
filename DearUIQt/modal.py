"""Shared modal registry, independent of Explorer or other application views."""
from .backends import dpg
from .input_gate import register_pointer_protected_item, unregister_pointer_protected_item

MODAL_TAGS = set()
_legacy_scan = None


def register_modal_window(tag):
    global _legacy_scan
    _legacy_scan = None
    if tag is not None:
        MODAL_TAGS.add(tag)
        register_pointer_protected_item(tag)
    return tag


def unregister_modal_window(tag):
    global _legacy_scan
    _legacy_scan = None
    MODAL_TAGS.discard(tag)
    unregister_pointer_protected_item(tag)


def visible_modal_window_exists():
    global _legacy_scan
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
    # Managed Qt dialogs update this stack synchronously, including when a
    # modal opens during the current callback batch. Never cache that boundary.
    from .core.application import QApplication
    app = QApplication.instance()
    if app is not None and app.activeModalWidget() is not None:
        return True
    try:
        getter = getattr(dpg, "get_windows", None)
        items = tuple(getter() if getter is not None else dpg.get_all_items())
        try:
            frame = int(dpg.get_frame_count())
        except (AttributeError, TypeError, ValueError):
            frame = None
        key = (frame, items)
        if frame is not None and _legacy_scan is not None and _legacy_scan[0] == key:
            return _legacy_scan[1]
        for item in items:
            try:
                config = dpg.get_item_configuration(item) or {}
                if config.get("modal", False) and dpg.is_item_shown(item):
                    _legacy_scan = (key, True) if frame is not None else None
                    return True
            except Exception:
                continue
    except Exception:
        pass
    else:
        _legacy_scan = (key, False) if frame is not None else None
    return False
