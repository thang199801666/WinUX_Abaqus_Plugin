"""Shared Explorer input-state helpers.

This module owns modal/popup input gating and keyboard modifier sampling so
Explorer pointer dispatch can be decomposed without importing the monolithic
ExplorerListView implementation.  ``explorer_list_view`` re-exports the public
modal registration helpers for backward compatibility with existing dialogs.
"""
from __future__ import annotations

import dearpygui.dearpygui as dpg

from .explorer_context_menu import EXPLORER_MENU_TAGS
from .interaction_gate import register_pointer_protected_item, unregister_pointer_protected_item

EXPLORER_MODAL_TAGS = set()


def register_modal_window(tag):
    """Register a modal tag and protect it from global Explorer handlers."""
    if tag is not None:
        EXPLORER_MODAL_TAGS.add(tag)
        register_pointer_protected_item(tag)
    return tag


def unregister_modal_window(tag):
    """Remove a tag previously registered with :func:`register_modal_window`."""
    EXPLORER_MODAL_TAGS.discard(tag)
    unregister_pointer_protected_item(tag)


def visible_modal_window_exists():
    """Return True while any visible modal Dear PyGui window owns input."""
    stale = []
    for item in tuple(EXPLORER_MODAL_TAGS):
        try:
            if not dpg.does_item_exist(item):
                stale.append(item)
            elif dpg.is_item_shown(item):
                return True
        except Exception:
            stale.append(item)
    for item in stale:
        EXPLORER_MODAL_TAGS.discard(item)

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


def modal_input_is_blocked():
    """Return True for any visible modal dialog, including registered ones."""
    return visible_modal_window_exists()


def visible_popup_window_exists():
    """Return True while a registered Explorer context menu is visible."""
    stale = []
    for item in tuple(EXPLORER_MENU_TAGS):
        try:
            if not dpg.does_item_exist(item):
                stale.append(item)
            elif dpg.is_item_shown(item):
                return True
        except Exception:
            stale.append(item)
    for item in stale:
        EXPLORER_MENU_TAGS.discard(item)
    return False


def overlay_window_owns_input():
    return visible_modal_window_exists() or visible_popup_window_exists()


def hovered(tag):
    if not dpg.does_item_exist(tag):
        return False
    try:
        return bool(dpg.is_item_hovered(tag))
    except KeyError:
        try:
            return bool(dpg.get_item_state(tag).get("hovered", False))
        except Exception:
            return False


def key_down(*names):
    for name in names:
        const = getattr(dpg, name, None)
        if const is not None and dpg.is_key_down(const):
            return True
    return False


def ctrl_down():
    return key_down("mvKey_LControl", "mvKey_RControl", "mvKey_Control")


def shift_down():
    return key_down("mvKey_LShift", "mvKey_RShift", "mvKey_Shift")


def alt_down():
    return key_down("mvKey_LAlt", "mvKey_RAlt", "mvKey_Alt")


# Backward-compatible private spellings used by the existing implementation.
_EXPLORER_MODAL_TAGS = EXPLORER_MODAL_TAGS
_visible_modal_window_exists = visible_modal_window_exists
_modal_input_is_blocked = modal_input_is_blocked
_visible_popup_window_exists = visible_popup_window_exists
_overlay_window_owns_input = overlay_window_owns_input
_hovered = hovered
_key_down = key_down
_ctrl_down = ctrl_down
_shift_down = shift_down
_alt_down = alt_down
