"""Dear ImGui theme helpers shared by Qt-style item views."""
from __future__ import annotations

from ..gui.palette import QtFusionMetrics, QtFusionPalette
from ..backends.dearpygui import add_dpg_scroller_style

_ITEM_VIEW_THEME = None
_LIST_VIEW_THEME = None
_CHECK_LIST_ROW_THEME = None
_CONTEXT_MENU_THEME = None
_ROW_THEME_CACHE = {}
_TEXT_THEME_CACHE = {}
LIST_CHECKBOX_PAD_Y = 3


def _theme_exists(backend, item):
    try:
        return bool(item is not None and backend.does_item_exist(item))
    except Exception:
        return False


def qt_item_view_theme(backend):
    """Shared QAbstractItemView/QHeaderView palette."""
    global _ITEM_VIEW_THEME
    if _theme_exists(backend, _ITEM_VIEW_THEME):
        return _ITEM_VIEW_THEME

    p = QtFusionPalette
    with backend.theme() as _ITEM_VIEW_THEME:
        with backend.theme_component(backend.mvTable):
            backend.add_theme_color(backend.mvThemeCol_TableHeaderBg, p.TOOLBAR)
            # ImGui table headers consume the generic Header hover/active roles
            # while TableHeaderBg supplies their normal surface.
            backend.add_theme_color(backend.mvThemeCol_Header, p.TOOLBAR)
            backend.add_theme_color(backend.mvThemeCol_HeaderHovered, p.HEADER_HOVER)
            backend.add_theme_color(backend.mvThemeCol_HeaderActive, p.HEADER_PRESSED)
            backend.add_theme_color(backend.mvThemeCol_Text, p.TEXT)
            backend.add_theme_color(backend.mvThemeCol_TableBorderStrong, p.BORDER)
            backend.add_theme_color(backend.mvThemeCol_TableBorderLight, p.BORDER_LIGHT)
            backend.add_theme_color(backend.mvThemeCol_TableRowBg, p.BASE)
            backend.add_theme_color(backend.mvThemeCol_TableRowBgAlt, p.ALTERNATE_BASE)
            backend.add_theme_style(backend.mvStyleVar_CellPadding, 6, 3)
            add_dpg_scroller_style(backend, track=p.WINDOW_ALT)
        with backend.theme_component(backend.mvSelectable):
            # Qt/Fusion list/table selection remains readable with dark text in
            # the light palette and acquires a blue NavHighlight on focus.
            backend.add_theme_color(backend.mvThemeCol_Header, p.HIGHLIGHT_SOFT)
            backend.add_theme_color(backend.mvThemeCol_HeaderHovered, p.HIGHLIGHT_HOVER)
            backend.add_theme_color(backend.mvThemeCol_HeaderActive, p.BUTTON_ACTIVE)
            backend.add_theme_color(backend.mvThemeCol_NavHighlight, p.FOCUS)
            backend.add_theme_color(backend.mvThemeCol_Text, p.TEXT)
            backend.add_theme_style(backend.mvStyleVar_SelectableTextAlign, 0.0, 0.5)
            backend.add_theme_style(backend.mvStyleVar_FrameRounding, 0)
            backend.add_theme_style(backend.mvStyleVar_FrameBorderSize, 0)
            backend.add_theme_style(backend.mvStyleVar_FramePadding, 5, 3)
        with backend.theme_component(backend.mvButton):
            # Dear PyGui renders sortable headers as buttons internally.
            backend.add_theme_color(backend.mvThemeCol_Button, p.TOOLBAR)
            backend.add_theme_color(backend.mvThemeCol_ButtonHovered, p.HEADER_HOVER)
            backend.add_theme_color(backend.mvThemeCol_ButtonActive, p.HEADER_PRESSED)
            backend.add_theme_color(backend.mvThemeCol_Text, p.TEXT)
            backend.add_theme_color(backend.mvThemeCol_Border, p.BORDER_LIGHT)
            backend.add_theme_style(backend.mvStyleVar_FrameRounding, 0)
            backend.add_theme_style(backend.mvStyleVar_FrameBorderSize, 1)
            backend.add_theme_style(backend.mvStyleVar_FramePadding, 6, 3)
            try:
                backend.add_theme_style(backend.mvStyleVar_ButtonTextAlign, 0.0, 0.5)
            except Exception:
                pass
    return _ITEM_VIEW_THEME



def qt_item_row_theme(backend, *, selected=False, disabled=False, current=False, active=True):
    """Return a QAbstractItemView-like row theme for one interaction state.

    Qt distinguishes *selection* from the *current index*.  Active selected
    rows use the accent fill, inactive selections become neutral gray, and the
    current index receives a one-pixel focus rectangle without changing row
    height.  Keeping these roles separate makes keyboard navigation readable
    in grids with extended selection instead of painting every selected row as
    if it owned keyboard focus.
    """
    state = (bool(selected), bool(disabled), bool(current), bool(active))
    cached = _ROW_THEME_CACHE.get(state)
    if _theme_exists(backend, cached):
        return cached
    p = QtFusionPalette
    tag = "dearuiqt.qt.itemrow.{}.{}.{}.{}".format(
        "selected" if selected else "normal",
        "disabled" if disabled else "enabled",
        "current" if current else "other",
        "active" if active else "inactive",
    )
    try:
        if backend.does_item_exist(tag):
            _ROW_THEME_CACHE[state] = tag
            return tag
    except Exception:
        pass
    with backend.theme(tag=tag):
        with backend.theme_component(backend.mvSelectable):
            if disabled:
                selected_fill = p.SELECTION_INACTIVE
                hover = p.SELECTION_INACTIVE
                pressed = p.SELECTION_INACTIVE
                text = p.TEXT_DISABLED
                border = p.SELECTION_INACTIVE_BORDER
            elif selected and active:
                selected_fill = p.SELECTION_ACTIVE
                hover = p.SELECTION_ACTIVE_HOVER
                pressed = p.SELECTION_ACTIVE_PRESSED
                text = p.SELECTION_TEXT
                border = p.SELECTION_BORDER
            elif selected:
                selected_fill = p.SELECTION_INACTIVE
                hover = p.SELECTION_INACTIVE
                pressed = p.SELECTION_INACTIVE
                text = p.TEXT
                border = p.SELECTION_INACTIVE_BORDER
            else:
                # Header is only painted while selected.  For an unselected
                # row the hover role is the visible state; keep it subtle like
                # QAbstractItemView::item:hover.
                selected_fill = p.HIGHLIGHT_SOFT
                hover = p.HIGHLIGHT_HOVER if active else p.WINDOW_ALT
                pressed = p.BUTTON_ACTIVE if active else p.SELECTION_INACTIVE
                text = p.TEXT
                border = p.FOCUS if active else p.SELECTION_INACTIVE_BORDER
            backend.add_theme_color(backend.mvThemeCol_Header, selected_fill)
            backend.add_theme_color(backend.mvThemeCol_HeaderHovered, hover)
            backend.add_theme_color(backend.mvThemeCol_HeaderActive, pressed)
            backend.add_theme_color(backend.mvThemeCol_Text, text)
            backend.add_theme_color(backend.mvThemeCol_TextDisabled, p.TEXT_DISABLED)
            backend.add_theme_color(backend.mvThemeCol_NavHighlight, p.FOCUS)
            backend.add_theme_color(backend.mvThemeCol_Border, border)
            backend.add_theme_style(backend.mvStyleVar_SelectableTextAlign, 0.0, 0.5)
            backend.add_theme_style(backend.mvStyleVar_FrameRounding, 0)
            backend.add_theme_style(backend.mvStyleVar_FrameBorderSize, 1 if current else 0)
            # Reserve one pixel internally for the current-index rectangle so
            # the row never jumps when current changes.
            backend.add_theme_style(backend.mvStyleVar_FramePadding, 5, 2)
    _ROW_THEME_CACHE[state] = tag
    return tag


def qt_item_text_theme(backend, *, selected=False, disabled=False, active=True):
    """Qt display-role text for non-primary cells in a selected table row.

    ``span_columns`` gives the first selectable a full-row background, but
    Dear ImGui does not automatically recolor the sibling ``mvText`` widgets
    in the remaining columns.  QTableView does, so keep those display-role
    cells synchronized with the row's active/inactive selection palette.
    """
    state = (bool(selected), bool(disabled), bool(active))
    cached = _TEXT_THEME_CACHE.get(state)
    if _theme_exists(backend, cached):
        return cached
    p = QtFusionPalette
    tag = "dearuiqt.qt.itemtext.{}.{}.{}".format(
        "selected" if selected else "normal",
        "disabled" if disabled else "enabled",
        "active" if active else "inactive",
    )
    try:
        if backend.does_item_exist(tag):
            _TEXT_THEME_CACHE[state] = tag
            return tag
    except Exception:
        pass
    color = p.SELECTION_TEXT if selected else p.TEXT
    if selected and not active:
        color = p.TEXT
    if disabled:
        color = p.TEXT_DISABLED
    with backend.theme(tag=tag):
        with backend.theme_component(backend.mvText):
            backend.add_theme_color(backend.mvThemeCol_Text, color)
    _TEXT_THEME_CACHE[state] = tag
    return tag


def qt_context_menu_theme(backend):
    """Compact QMenu-like theme used by reusable item views."""
    global _CONTEXT_MENU_THEME
    if _theme_exists(backend, _CONTEXT_MENU_THEME):
        return _CONTEXT_MENU_THEME
    p = QtFusionPalette
    with backend.theme() as _CONTEXT_MENU_THEME:
        with backend.theme_component(backend.mvAll):
            backend.add_theme_color(backend.mvThemeCol_WindowBg, p.MENU)
            backend.add_theme_color(backend.mvThemeCol_PopupBg, p.MENU)
            backend.add_theme_color(backend.mvThemeCol_Text, p.TEXT)
            backend.add_theme_color(backend.mvThemeCol_TextDisabled, p.TEXT_DISABLED)
            backend.add_theme_color(backend.mvThemeCol_Separator, p.BORDER_LIGHT)
            backend.add_theme_color(backend.mvThemeCol_Border, p.BORDER)
            backend.add_theme_color(backend.mvThemeCol_Header, p.MENU_HOVER)
            backend.add_theme_color(backend.mvThemeCol_HeaderHovered, p.MENU_HOVER)
            backend.add_theme_color(backend.mvThemeCol_HeaderActive, p.MENU_ACTIVE)
            backend.add_theme_style(backend.mvStyleVar_WindowPadding, 4, 3)
            backend.add_theme_style(backend.mvStyleVar_ItemSpacing, 5, 2)
            backend.add_theme_style(backend.mvStyleVar_WindowRounding, QtFusionMetrics.POPUP_ROUNDING)
            backend.add_theme_style(backend.mvStyleVar_PopupRounding, QtFusionMetrics.POPUP_ROUNDING)
            backend.add_theme_style(backend.mvStyleVar_WindowBorderSize, 1)
    return _CONTEXT_MENU_THEME


def _normalize_menu_spec(spec):
    if isinstance(spec, dict):
        item = dict(spec)
    elif isinstance(spec, (tuple, list)):
        if len(spec) < 2:
            raise ValueError("menu tuples require at least (label, action)")
        item = {"label": spec[0], "action": spec[1]}
    else:
        raise TypeError("menu item must be a dict, tuple, or list")
    item.setdefault("id", item.get("action") or item.get("label"))
    item.setdefault("label", "")
    item.setdefault("action", None)
    item.setdefault("enabled", True)
    item.setdefault("visible", True)
    item.setdefault("checkable", False)
    item.setdefault("checked", False)
    item.setdefault("separator", item.get("label") == "---")
    item["children"] = [_normalize_menu_spec(child) for child in (item.get("children") or ())]
    return item

def qt_check_list_row_theme(backend):
    global _CHECK_LIST_ROW_THEME
    if not _theme_exists(backend, _CHECK_LIST_ROW_THEME):
        with backend.theme() as _CHECK_LIST_ROW_THEME:
            with backend.theme_component(backend.mvChildWindow):
                backend.add_theme_color(backend.mvThemeCol_ChildBg, QtFusionPalette.BASE)
                backend.add_theme_style(backend.mvStyleVar_WindowPadding, 0, 0)
                backend.add_theme_style(backend.mvStyleVar_ItemSpacing, 0, 0)
                backend.add_theme_style(backend.mvStyleVar_ChildBorderSize, 0)
                backend.add_theme_style(backend.mvStyleVar_ChildRounding, 0)
    return _CHECK_LIST_ROW_THEME


def qt_list_view_theme(backend):
    global _LIST_VIEW_THEME
    if _theme_exists(backend, _LIST_VIEW_THEME):
        return _LIST_VIEW_THEME
    p = QtFusionPalette
    with backend.theme() as _LIST_VIEW_THEME:
        with backend.theme_component(backend.mvChildWindow):
            backend.add_theme_color(backend.mvThemeCol_ChildBg, p.BASE)
            backend.add_theme_color(backend.mvThemeCol_Border, p.BORDER)
            backend.add_theme_style(backend.mvStyleVar_WindowPadding, 6, 0)
            backend.add_theme_style(backend.mvStyleVar_ChildRounding, 0)
            backend.add_theme_style(backend.mvStyleVar_ChildBorderSize, 1)
            backend.add_theme_style(backend.mvStyleVar_ItemSpacing, 0, 0)
            add_dpg_scroller_style(backend, track=p.WINDOW_ALT)
        with backend.theme_component(backend.mvCheckbox):
            backend.add_theme_style(backend.mvStyleVar_FramePadding, 3, LIST_CHECKBOX_PAD_Y)
            backend.add_theme_style(backend.mvStyleVar_FrameBorderSize, 1)
            backend.add_theme_color(backend.mvThemeCol_FrameBg, p.BASE)
            backend.add_theme_color(backend.mvThemeCol_CheckMark, p.HIGHLIGHT)
    return _LIST_VIEW_THEME



__all__ = [
    "qt_item_view_theme", "qt_item_row_theme", "qt_item_text_theme",
    "qt_context_menu_theme", "qt_list_view_theme",
]
