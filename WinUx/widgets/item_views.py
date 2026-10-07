"""Qt/Fusion-like item views rendered by the current Dear PyGui backend.

The classes in this module intentionally separate selection/current-row logic
from rendering.  They expose a small subset of Qt's ``QAbstractItemView`` /
``QTableView`` / ``QListView`` contracts while keeping WinUx on its existing
Dear PyGui render loop.

This is not a thin theme wrapper around ``dpg.add_listbox``.  Both views own
explicit current/anchor/selection state, keyboard navigation and stable row
keys so callers do not need to depend on Dear ImGui's implicit selection
semantics.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, Sequence

from .controls import QWidget
from .core import Signal
from .menu import ImGuiMenu
from ..components.qt_style import QtFusionMetrics, QtFusionPalette
from ..components.shared_scroller import add_dpg_scroller_style


@dataclass(frozen=True)
class QtGridColumn:
    key: str
    label: str
    width: float | None = None
    stretch: float = 1.0
    align: str = "left"
    sortable: bool = True


@dataclass(frozen=True)
class QtGridRow:
    """One stable row in :class:`QtDataGridView`.

    ``background`` is an optional RGBA tuple used for status/category tinting.
    ``data`` is intentionally opaque application metadata; the view never
    interprets it.  This mirrors Qt's model roles without forcing WinUx callers
    to build a full ``QAbstractItemModel`` for simple flat grids.
    """

    key: Any
    values: Sequence[Any]
    data: Any = None
    enabled: bool = True
    background: Any = None


@dataclass(frozen=True)
class QtListItem:
    key: Any
    text: str
    data: Any = None
    enabled: bool = True


class QtSelectionMode:
    SingleSelection = "single"
    ExtendedSelection = "extended"


class QtItemViewState:
    """Backend-independent current/anchor/selection state.

    The state mirrors the parts of ``QItemSelectionModel`` WinUx needs.  It is
    deliberately testable without a GUI backend.
    """

    def __init__(self, multiple=False):
        self.multiple = bool(multiple)
        self.keys: list[Any] = []
        self.selected: set[Any] = set()
        self.current: Any = None
        self.anchor: Any = None

    def replace(self, keys: Iterable[Any]):
        keys = list(keys)
        valid = set(keys)
        self.keys = keys
        self.selected.intersection_update(valid)
        if self.current not in valid:
            self.current = keys[0] if keys else None
        if self.anchor not in valid:
            self.anchor = self.current
        return self

    def clear(self):
        self.selected.clear()

    def select(self, key, *, ctrl=False, shift=False, selected=True):
        if key not in self.keys:
            return False
        old = set(self.selected)
        if not self.multiple:
            # Qt SingleSelection keeps the clicked row selected even when an
            # underlying toggle-style primitive reports its previous state.
            self.selected = {key}
        elif shift and self.anchor in self.keys:
            first, last = sorted((self.keys.index(self.anchor), self.keys.index(key)))
            if not ctrl:
                self.selected.clear()
            self.selected.update(self.keys[first:last + 1])
        elif ctrl:
            if selected:
                self.selected.add(key)
            else:
                self.selected.discard(key)
        else:
            # A plain click in ExtendedSelection starts a new one-row
            # selection; only Ctrl-click toggles a row off.
            self.selected = {key}
        self.current = key
        if not shift:
            self.anchor = key
        return old != self.selected

    def select_all(self):
        if self.multiple:
            self.selected = set(self.keys)

    def move(self, delta=0, *, absolute=None, ctrl=False, shift=False):
        if not self.keys:
            return None, False
        old_selection = set(self.selected)
        old_current = self.current
        index = self.keys.index(self.current) if self.current in self.keys else 0
        if absolute is not None:
            next_index = max(0, min(len(self.keys) - 1, int(absolute)))
        else:
            next_index = max(0, min(len(self.keys) - 1, index + int(delta)))
        key = self.keys[next_index]
        self.current = key
        if shift and self.multiple:
            anchor_index = self.keys.index(self.anchor) if self.anchor in self.keys else index
            first, last = sorted((anchor_index, next_index))
            if not ctrl:
                self.selected.clear()
            self.selected.update(self.keys[first:last + 1])
        elif not ctrl:
            self.selected = {key}
            self.anchor = key
        return key, old_selection != self.selected or old_current != self.current


_ITEM_VIEW_THEME = None
_LIST_VIEW_THEME = None
_CONTEXT_MENU_THEME = None
_ROW_THEME_CACHE = {}
_TEXT_THEME_CACHE = {}


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
            # WinUx's light palette and acquires a blue NavHighlight on focus.
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
    tag = "winux.imguiqt.itemrow.{}.{}.{}.{}".format(
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
    tag = "winux.imguiqt.itemtext.{}.{}.{}".format(
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

def qt_list_view_theme(backend):
    global _LIST_VIEW_THEME
    if _theme_exists(backend, _LIST_VIEW_THEME):
        return _LIST_VIEW_THEME
    p = QtFusionPalette
    with backend.theme() as _LIST_VIEW_THEME:
        with backend.theme_component(backend.mvChildWindow):
            backend.add_theme_color(backend.mvThemeCol_ChildBg, p.BASE)
            backend.add_theme_color(backend.mvThemeCol_Border, p.BORDER)
            backend.add_theme_style(backend.mvStyleVar_WindowPadding, 0, 0)
            backend.add_theme_style(backend.mvStyleVar_ChildRounding, 0)
            backend.add_theme_style(backend.mvStyleVar_ChildBorderSize, 1)
            backend.add_theme_style(backend.mvStyleVar_ItemSpacing, 0, 0)
            add_dpg_scroller_style(backend, track=p.WINDOW_ALT)
    return _LIST_VIEW_THEME


class _QtAbstractItemView(QWidget):
    def __init__(self, tag, *, parent=None, after=None, backend=None, multiple=False):
        super().__init__(tag, parent=parent, after=after, backend=backend)
        self.selectionChanged = Signal(self)
        self.currentChanged = Signal(self)
        self.activated = Signal(self)
        self.doubleClicked = Signal(self)
        self.focusChanged = Signal(self)
        self._state = QtItemViewState(multiple=multiple)
        self.multiple = bool(multiple)
        self._has_focus = False
        self._focus_handler_registry = None
        self._install_focus_tracking()

    def _install_focus_tracking(self):
        """Track focus at the view level, as QAbstractItemView does.

        Dear ImGui focuses the row/selectable, not the table/child container.
        A lightweight global mouse handler therefore translates pointer focus
        into one retained view-level flag.  It is used only for active vs
        inactive selection rendering and never captures the pointer.
        """
        b = self.backend
        try:
            with b.handler_registry() as registry:
                b.add_mouse_click_handler(
                    button=b.mvMouseButton_Left,
                    callback=self._focus_mouse_down,
                )
            self._focus_handler_registry = registry
        except Exception:
            self._focus_handler_registry = None

    def _focus_mouse_down(self, *_args):
        point = None
        try:
            point = tuple(map(float, self.backend.get_mouse_pos(local=False)))
        except Exception:
            pass
        focused = bool(point is not None and self._point_in_view(point))
        self._set_view_focus(focused)

    def _point_in_view(self, point):
        try:
            left, top = map(float, self.backend.get_item_rect_min(self.tag))
            width, height = map(float, self.backend.get_item_rect_size(self.tag))
            x, y = point
            return left <= x < left + width and top <= y < top + height
        except Exception:
            return False

    def _set_view_focus(self, focused):
        focused = bool(focused)
        if self._has_focus == focused:
            return False
        self._has_focus = focused
        self._sync_selection_visuals()
        self.focusChanged.emit(focused)
        return True

    def hasFocus(self):
        return bool(self._has_focus)

    def setFocus(self):
        self._set_view_focus(True)
        self._focus_current()
        return self

    def selectionMode(self):
        return (QtSelectionMode.ExtendedSelection
                if self.multiple else QtSelectionMode.SingleSelection)

    def setSelectionMode(self, mode):
        multiple = str(mode) == QtSelectionMode.ExtendedSelection
        if self.multiple == multiple:
            return self
        self.multiple = multiple
        self._state.multiple = multiple
        if not multiple and len(self.selected) > 1:
            keep = self.current if self.current in self.selected else next(iter(self.selected), None)
            self._state.selected = ({keep} if keep is not None else set())
            self._sync_selection_visuals()
            self.selectionChanged.emit(set(self.selected))
        return self

    def currentKey(self):
        return self.current

    @property
    def selected(self):
        # Compatibility with the historic QtTable API.  Callers intentionally
        # mutate this set in a few result dialogs, so expose the real set.
        return self._state.selected

    @selected.setter
    def selected(self, values):
        self._state.selected = set(values or ())
        self._sync_selection_visuals()

    @property
    def current(self):
        return self._state.current

    @current.setter
    def current(self, value):
        self._state.current = value

    @property
    def anchor(self):
        return self._state.anchor

    @anchor.setter
    def anchor(self, value):
        self._state.anchor = value

    def clearSelection(self):
        if not self.selected:
            return
        self.selected.clear()
        self._sync_selection_visuals()
        self.selectionChanged.emit(set())

    clear_selection = clearSelection

    def selectAll(self):
        self._set_view_focus(True)
        before = set(self.selected)
        self._state.select_all()
        if self.selected != before:
            self._sync_selection_visuals()
            self.selectionChanged.emit(set(self.selected))

    def selectedKeys(self):
        return [key for key in self._state.keys if key in self.selected]

    def setCurrentKey(self, key, *, select=True):
        if key not in self._state.keys:
            return False
        self._set_view_focus(True)
        old_current = self.current
        changed = self._state.select(key, selected=True) if select else False
        self.current = key
        current_changed = old_current != key
        if current_changed:
            self.currentChanged.emit(key)
        if changed or current_changed:
            self._sync_selection_visuals()
        if changed:
            self.selectionChanged.emit(set(self.selected))
        self._focus_current()
        return True

    def navigate(self, key, ctrl=False, shift=False):
        b = self.backend
        self._set_view_focus(True)
        if ctrl and key == b.mvKey_A and self.multiple:
            self.selectAll()
            return
        if ctrl and key == b.mvKey_Spacebar and self.current in self._state.keys:
            old = set(self.selected)
            if self.current in self.selected:
                self.selected.discard(self.current)
            else:
                if not self.multiple:
                    self.selected.clear()
                self.selected.add(self.current)
            if old != self.selected:
                self._sync_selection_visuals()
                self.selectionChanged.emit(set(self.selected))
            return
        if key == b.mvKey_Up:
            target, changed = self._state.move(-1, ctrl=ctrl, shift=shift)
        elif key == b.mvKey_Down:
            target, changed = self._state.move(1, ctrl=ctrl, shift=shift)
        elif key == b.mvKey_Home:
            target, changed = self._state.move(absolute=0, ctrl=ctrl, shift=shift)
        elif key == b.mvKey_End:
            target, changed = self._state.move(absolute=max(0, len(self._state.keys)-1), ctrl=ctrl, shift=shift)
        elif key == b.mvKey_Prior:
            target, changed = self._state.move(-10, ctrl=ctrl, shift=shift)
        elif key == b.mvKey_Next:
            target, changed = self._state.move(10, ctrl=ctrl, shift=shift)
        else:
            return
        if target is None:
            return
        self._sync_selection_visuals()
        self._focus_current()
        self.currentChanged.emit(target)
        if changed:
            self.selectionChanged.emit(set(self.selected))

    def _row_clicked(self, sender, value, key):
        b = self.backend
        self._set_view_focus(True)
        ctrl = bool(b.is_key_down(b.mvKey_LControl) or b.is_key_down(b.mvKey_RControl))
        shift = bool(b.is_key_down(b.mvKey_LShift) or b.is_key_down(b.mvKey_RShift))
        old_current = self.current
        changed = self._state.select(key, ctrl=ctrl, shift=shift, selected=bool(value))
        self._sync_selection_visuals()
        if old_current != self.current:
            self.currentChanged.emit(self.current)
        if changed:
            self.selectionChanged.emit(set(self.selected))
        try:
            double = bool(b.is_mouse_button_double_clicked(b.mvMouseButton_Left))
        except Exception:
            double = False
        if double:
            self.doubleClicked.emit(key)
            self.activated.emit(key)

    def _sync_selection_visuals(self):
        raise NotImplementedError

    def _focus_current(self):
        raise NotImplementedError

    def delete(self):
        registry = self._focus_handler_registry
        self._focus_handler_registry = None
        if registry is not None:
            try:
                if self.backend.does_item_exist(registry):
                    self.backend.delete_item(registry)
            except Exception:
                pass
        super().delete()


class ImGuiHeaderView:
    """Small QHeaderView-like facade over Dear ImGui table columns.

    Dear PyGui owns the native resize hit testing, while this facade keeps
    application code independent of table implementation details.  It exposes
    the QHeaderView properties WinUx actually uses and maps them to the table
    or individual column items.
    """

    Interactive = "interactive"
    Fixed = "fixed"
    Stretch = "stretch"

    def __init__(self, grid):
        self._grid = grid
        self._visible = True
        self._stretch_last = False
        self._sections_movable = False
        self._sections_clickable = True
        self._default_section_size = 100.0

    def isVisible(self):
        return bool(self._visible)

    def setVisible(self, visible):
        self._visible = bool(visible)
        self._grid.setHeaderVisible(self._visible)
        return self

    def setStretchLastSection(self, enabled):
        self._stretch_last = bool(enabled)
        columns = list(self._grid.columns)
        if columns:
            item = self._grid._column_item(columns[-1].key)
            if item is not None:
                try:
                    self._grid.backend.configure_item(
                        item,
                        width_fixed=not self._stretch_last,
                        width_stretch=self._stretch_last,
                        init_width_or_weight=(1.0 if self._stretch_last
                                              else self._default_section_size),
                    )
                except Exception:
                    pass
        return self

    def stretchLastSection(self):
        return bool(self._stretch_last)

    def setSectionsMovable(self, enabled):
        self._sections_movable = bool(enabled)
        try:
            self._grid.backend.configure_item(
                self._grid.tag, reorderable=self._sections_movable)
        except Exception:
            pass
        return self

    def sectionsMovable(self):
        return bool(self._sections_movable)

    def setSectionsClickable(self, enabled):
        self._sections_clickable = bool(enabled)
        try:
            self._grid.backend.configure_item(
                self._grid.tag, sortable=self._sections_clickable)
        except Exception:
            pass
        return self

    def sectionsClickable(self):
        return bool(self._sections_clickable)

    def setDefaultSectionSize(self, size):
        self._default_section_size = max(1.0, float(size))
        return self

    def defaultSectionSize(self):
        return float(self._default_section_size)

    def resizeSection(self, section, size):
        try:
            column = self._grid.columns[int(section)]
        except (IndexError, TypeError, ValueError):
            return False
        return self._grid.setColumnWidth(column.key, size)

    def sectionSize(self, section):
        try:
            column = self._grid.columns[int(section)]
        except (IndexError, TypeError, ValueError):
            return None
        return self._grid.columnWidth(column.key)

    def setSectionResizeMode(self, section, mode):
        try:
            column = self._grid.columns[int(section)]
        except (IndexError, TypeError, ValueError):
            return False
        item = self._grid._column_item(column.key)
        if item is None:
            return False
        mode = str(mode).lower()
        try:
            if mode == self.Stretch:
                self._grid.backend.configure_item(
                    item, width_fixed=False, width_stretch=True,
                    init_width_or_weight=max(.01, float(column.stretch or 1.0)))
            elif mode in (self.Fixed, self.Interactive):
                width = self._grid.columnWidth(column.key)
                if width is None:
                    width = column.width or self._default_section_size
                self._grid.backend.configure_item(
                    item, width_fixed=True, width_stretch=False,
                    init_width_or_weight=max(1.0, float(width)))
            else:
                return False
            return True
        except Exception:
            return False


QHeaderView = ImGuiHeaderView


class QtDataGridView(_QtAbstractItemView):
    """QTableView-like flat data grid with stable row keys."""

    def __init__(self, parent, columns, *, width=-1, height=-1, multiple=False,
                 after=None, backend=None, sortable=False, resizable=True,
                 reorderable=False, alternating_rows=True, grid_lines=True,
                 horizontal_scrollbar=True, on_activate=None):
        if backend is None:
            import dearpygui.dearpygui as backend
        normalized = []
        for index, column in enumerate(columns):
            if isinstance(column, QtGridColumn):
                normalized.append(column)
            elif isinstance(column, str):
                normalized.append(QtGridColumn(str(index), column))
            else:
                data = dict(column)
                normalized.append(QtGridColumn(
                    key=str(data.get("key", index)),
                    label=str(data.get("label", data.get("key", index))),
                    width=data.get("width"),
                    stretch=float(data.get("stretch", data.get("weight", 1.0))),
                    align=str(data.get("align", "left")),
                    sortable=bool(data.get("sortable", True)),
                ))
        self.columns = normalized
        self.rows: list[tuple[Any, tuple[Any, ...]]] = []
        self.row_data: dict[Any, Any] = {}
        self.row_backgrounds: dict[Any, Any] = {}
        self.row_enabled: dict[Any, bool] = {}
        self.items: dict[Any, Any] = {}
        self._cell_text_items: dict[Any, list[Any]] = {}
        self._row_tags: dict[Any, Any] = {}
        self._row_index: dict[Any, int] = {}
        self._sort_key = None
        self._sort_ascending = True
        self.sortChanged = Signal()
        self.contextMenuRequested = Signal()
        self._external_activate = on_activate
        self._context_specs = []
        self._context_items = {}
        self._context_key = None
        self._context_open_callback = None
        self._context_trigger_callback = None
        self._context_handler_registry = None
        self._context_popup = None
        self._context_menu = None
        # Compatibility with the draw-list item views serviced by WinUXView's
        # post-render layout loop. QTableView-backed grids do not need that
        # custom pass, but exposing the same tiny surface lets specialized
        # views migrate without branching the main render loop.
        self._resize_layout_pending = False
        self._scroller_arrow_overlay = None
        options = dict(
            parent=parent, header_row=True, width=width, height=height,
            scrollY=True, scrollX=bool(horizontal_scrollbar), freeze_rows=1,
            resizable=bool(resizable), reorderable=bool(reorderable),
            sortable=bool(sortable), row_background=bool(alternating_rows),
            borders_innerH=bool(grid_lines), borders_outerH=True,
            borders_innerV=bool(grid_lines), borders_outerV=True,
            policy=backend.mvTable_SizingStretchProp,
        )
        if sortable:
            options["callback"] = self._sort_specs_changed
        tag = backend.add_table(**options)
        super().__init__(tag, parent=None, after=after, backend=backend, multiple=multiple)
        self.sortChanged.owner = self
        self.contextMenuRequested.owner = self
        self._horizontal_header = ImGuiHeaderView(self)
        self._horizontal_header._sections_movable = bool(reorderable)
        self._horizontal_header._sections_clickable = bool(sortable)
        for column in self.columns:
            kwargs = dict(parent=self.tag, label=column.label, user_data=column.key,
                          no_sort=not column.sortable)
            if column.width is not None:
                kwargs.update(width_fixed=True, init_width_or_weight=float(column.width))
            else:
                kwargs.update(width_stretch=True, init_width_or_weight=max(.01, column.stretch))
            backend.add_table_column(**kwargs)
        try:
            backend.bind_item_theme(self.tag, qt_item_view_theme(backend))
        except Exception:
            pass
        if callable(on_activate):
            self.activated.connect(on_activate)

    def horizontalHeader(self):
        return self._horizontal_header

    def set_rows(self, rows):
        old_selected = set(self.selected)
        try:
            old_scroll_y = float(self.backend.get_y_scroll(self.tag))
        except Exception:
            old_scroll_y = 0.0
        try:
            old_scroll_x = float(self.backend.get_x_scroll(self.tag))
        except Exception:
            old_scroll_x = 0.0
        normalized = []
        self.row_data.clear()
        self.row_backgrounds.clear()
        self.row_enabled.clear()
        for row in rows:
            if isinstance(row, QtGridRow):
                key, values = row.key, tuple(row.values)
                self.row_data[key] = row.data
                self.row_enabled[key] = bool(row.enabled)
                if row.background is not None:
                    self.row_backgrounds[key] = row.background
            else:
                key, values = row
                values = tuple(values)
                self.row_enabled[key] = True
            normalized.append((key, values))
        self.rows = normalized
        if self._sort_key is not None:
            self._apply_sort_in_place()
        self._state.replace(key for key, _values in self.rows)
        self._delete_rows()
        for row_index, (key, values) in enumerate(self.rows):
            row_tag = self.backend.add_table_row(parent=self.tag)
            self._row_tags[key] = row_tag
            self._row_index[key] = row_index
            first = str(values[0]) if values else ""
            selectable = self.backend.add_selectable(
                label=first, span_columns=True, height=QtFusionMetrics.ROW_HEIGHT,
                default_value=key in self.selected, user_data=key,
                enabled=bool(self.row_enabled.get(key, True)),
                callback=self._row_clicked, parent=row_tag,
            )
            self.items[key] = selectable
            text_items = []
            for value in values[1:len(self.columns)]:
                text_items.append(self.backend.add_text(str(value), parent=row_tag))
            self._cell_text_items[key] = text_items
            background = self.row_backgrounds.get(key)
            if background is not None:
                try:
                    self.backend.highlight_table_row(self.tag, row_index, background)
                except Exception:
                    pass
        self._sync_selection_visuals()
        # Refreshing qstat/ODB data must not jump a user's scrolled table back
        # to the origin.  QAbstractItemView preserves viewport position across
        # a model refresh whenever the same view remains active.
        try:
            self.backend.set_y_scroll(self.tag, old_scroll_y)
        except Exception:
            pass
        try:
            self.backend.set_x_scroll(self.tag, old_scroll_x)
        except Exception:
            pass
        if old_selected != self.selected:
            self.selectionChanged.emit(set(self.selected))
        return self

    setRows = set_rows

    def _delete_rows(self):
        for row in list(self.backend.get_item_children(self.tag, 1) or []):
            try:
                self.backend.delete_item(row)
            except Exception:
                pass
        self.items.clear()
        self._cell_text_items.clear()
        self._row_tags.clear()
        self._row_index.clear()

    def rowValues(self, key):
        return next((values for row_key, values in self.rows if row_key == key), None)

    def selectedRows(self):
        return [(key, values) for key, values in self.rows if key in self.selected]

    def rowData(self, key):
        return self.row_data.get(key)

    def setRowBackground(self, key, color):
        if key not in self._row_index:
            return False
        if color is None:
            self.row_backgrounds.pop(key, None)
            try:
                self.backend.unhighlight_table_row(self.tag, self._row_index[key])
            except Exception:
                pass
        else:
            self.row_backgrounds[key] = color
            try:
                self.backend.highlight_table_row(self.tag, self._row_index[key], color)
            except Exception:
                pass
        return True

    def setColumnWidth(self, key, width):
        column = self._column_item(key)
        if column is None:
            return False
        try:
            self.backend.configure_item(
                column, width_fixed=True, width_stretch=False,
                init_width_or_weight=max(1.0, float(width)))
            return True
        except Exception:
            return False

    def columnWidth(self, key):
        column = self._column_item(key)
        if column is None:
            return None
        try:
            config = self.backend.get_item_configuration(column)
            value = config.get("init_width_or_weight")
            return None if value is None else float(value)
        except Exception:
            return None

    def _column_item(self, key):
        key = str(key)
        for item in list(self.backend.get_item_children(self.tag, 0) or []):
            try:
                if str(self.backend.get_item_user_data(item)) == key:
                    return item
            except Exception:
                pass
        return None

    def _layout_all(self):
        self._resize_layout_pending = False

    def resize(self, width=-1, height=-1):
        try:
            self.backend.configure_item(self.tag, width=width, height=height)
        except Exception:
            pass
        return self

    def setAlternatingRowColors(self, enabled):
        try:
            self.backend.configure_item(self.tag, row_background=bool(enabled))
        except Exception:
            pass
        return self

    def setShowGrid(self, enabled):
        enabled = bool(enabled)
        try:
            self.backend.configure_item(
                self.tag,
                borders_innerH=enabled,
                borders_innerV=enabled,
            )
        except Exception:
            pass
        return self

    def setHeaderVisible(self, visible):
        try:
            self.backend.configure_item(self.tag, header_row=bool(visible))
        except Exception:
            pass
        return self

    def setSortingEnabled(self, enabled):
        try:
            self.backend.configure_item(self.tag, sortable=bool(enabled))
        except Exception:
            pass
        return self

    def _apply_sort_in_place(self):
        if self._sort_key is None:
            return
        index = next((i for i, column in enumerate(self.columns)
                      if column.key == self._sort_key), None)
        if index is None:
            return
        def value(row):
            values = row[1]
            raw = values[index] if index < len(values) else ""
            if isinstance(raw, (int, float)):
                return (0, float(raw))
            text = str(raw).strip()
            try:
                return (0, float(text))
            except (TypeError, ValueError):
                return (1, text.casefold())
        self.rows.sort(key=value, reverse=not self._sort_ascending)

    def setContextMenu(self, items, *, on_open=None, on_trigger=None):
        """Attach the shared Dear ImGui ``ImGuiMenu`` to the grid."""
        self._context_specs = [_normalize_menu_spec(item) for item in (items or ())]
        self._context_open_callback = on_open
        self._context_trigger_callback = on_trigger
        self._delete_context_menu()
        if not self._context_specs:
            return self
        self._context_menu = ImGuiMenu(
            self._context_specs, backend=self.backend, after=self._after)
        self._context_menu.triggered.connect(self._context_triggered_from_menu)
        try:
            with self.backend.handler_registry() as registry:
                self.backend.add_mouse_click_handler(
                    button=self.backend.mvMouseButton_Right,
                    callback=self._context_mouse_down,
                )
            self._context_handler_registry = registry
        except Exception:
            self._context_handler_registry = None
        return self

    set_context_menu = setContextMenu

    def _context_mouse_down(self, *_args):
        point = None
        try:
            point = tuple(map(float, self.backend.get_mouse_pos(local=False)))
        except Exception:
            pass
        if point is None or not self._point_in_item(self.tag, point):
            return
        key = None
        for row_key, selectable in tuple(self.items.items()):
            if self._point_in_item(selectable, point):
                key = row_key
                break
        self._context_key = key
        if key is not None and key not in self.selected:
            self.setCurrentKey(key, select=True)
        if callable(self._context_open_callback):
            self._context_open_callback(key)
        self.contextMenuRequested.emit(key)
        if self._context_menu is not None:
            self._context_menu.popup(point, context=key)

    def _point_in_item(self, item, point):
        try:
            left, top = map(float, self.backend.get_item_rect_min(item))
            width, height = map(float, self.backend.get_item_rect_size(item))
            x, y = point
            return left <= x < left + width and top <= y < top + height
        except Exception:
            return False

    def _context_triggered_from_menu(self, action, context):
        self._context_key = context
        if callable(self._context_trigger_callback):
            self._context_trigger_callback(str(action), context)

    def setContextMenuItemEnabled(self, action, enabled):
        if self._context_menu is None:
            return False
        return self._context_menu.setActionEnabled(action, enabled)

    set_context_menu_item_enabled = setContextMenuItemEnabled

    def setContextMenuItemChecked(self, action, checked):
        if self._context_menu is None:
            return False
        return self._context_menu.setActionChecked(action, checked)

    set_context_menu_item_checked = setContextMenuItemChecked

    def _delete_context_menu(self):
        if self._context_handler_registry is not None:
            try:
                if self.backend.does_item_exist(self._context_handler_registry):
                    self.backend.delete_item(self._context_handler_registry)
            except Exception:
                pass
        self._context_handler_registry = None
        if self._context_menu is not None:
            try:
                self._context_menu.delete()
            except Exception:
                pass
        self._context_menu = None
        self._context_popup = None
        self._context_items.clear()

    def _sync_selection_visuals(self):
        for key, item in tuple(self.items.items()):
            selected = key in self.selected
            disabled = not bool(self.row_enabled.get(key, True))
            try:
                self.backend.set_value(item, selected)
                self.backend.bind_item_theme(
                    item, qt_item_row_theme(
                        self.backend,
                        selected=selected,
                        disabled=disabled,
                        current=(key == self.current),
                        active=self._has_focus,
                    ))
                cell_theme = qt_item_text_theme(
                    self.backend, selected=selected, disabled=disabled,
                    active=self._has_focus)
                for text_item in self._cell_text_items.get(key, ()):
                    self.backend.bind_item_theme(text_item, cell_theme)
            except Exception:
                pass

    def _focus_current(self):
        item = self.items.get(self.current)
        if item is not None:
            try:
                self.backend.focus_item(item)
            except Exception:
                pass

    def _sort_specs_changed(self, sender, app_data, user_data=None):
        specs = app_data or []
        if not specs:
            return
        # DPG currently reports [(column_id, direction), ...].  Resolve the
        # visible column index defensively because older builds use integer ids.
        spec = specs[0]
        try:
            column_id, direction = spec[0], spec[1]
        except Exception:
            return
        column_key = None
        children = list(self.backend.get_item_children(self.tag, 0) or [])
        if column_id in children:
            try:
                column_key = self.backend.get_item_user_data(column_id)
            except Exception:
                column_key = None
        if column_key is None and isinstance(column_id, int) and 0 <= column_id < len(self.columns):
            column_key = self.columns[column_id].key
        if column_key is None:
            return
        ascending = int(direction) >= 0
        self._sort_key, self._sort_ascending = column_key, ascending
        self._apply_sort_in_place()
        self.set_rows([
            QtGridRow(
                key=key,
                values=values,
                data=self.row_data.get(key),
                enabled=self.row_enabled.get(key, True),
                background=self.row_backgrounds.get(key),
            )
            for key, values in self.rows
        ])
        self.sortChanged.emit(column_key, ascending)

    def delete(self):
        self._delete_context_menu()
        super().delete()


class QtListView(_QtAbstractItemView):
    """QListView-like single-column item view with stable keys."""

    def __init__(self, parent, items=(), *, width=-1, height=-1,
                 visible_rows=None, multiple=False, after=None, backend=None,
                 on_activate=None):
        if backend is None:
            import dearpygui.dearpygui as backend
        if visible_rows is not None and (height is None or height == -1):
            height = int(visible_rows) * QtFusionMetrics.ROW_HEIGHT + 2
        tag = backend.add_child_window(
            parent=parent, width=width, height=height, border=True,
            no_scrollbar=False, no_scroll_with_mouse=False,
        )
        super().__init__(tag, parent=None, after=after, backend=backend, multiple=multiple)
        self.items: dict[Any, Any] = {}
        self._values: list[QtListItem] = []
        self.currentTextChanged = Signal(self)
        try:
            backend.bind_item_theme(self.tag, qt_list_view_theme(backend))
        except Exception:
            pass
        if callable(on_activate):
            self.activated.connect(on_activate)
        self.setItems(items)

    @staticmethod
    def _normalize_items(items: Iterable[Any]):
        normalized = []
        for index, item in enumerate(items or ()):
            if isinstance(item, QtListItem):
                normalized.append(item)
            elif isinstance(item, tuple) and len(item) >= 2:
                normalized.append(QtListItem(item[0], str(item[1]), item[2] if len(item) > 2 else None))
            else:
                normalized.append(QtListItem(item, str(item), item))
        return normalized

    def setItems(self, items):
        previous_current = self.current
        try:
            old_scroll_y = float(self.backend.get_y_scroll(self.tag))
        except Exception:
            old_scroll_y = 0.0
        self._values = self._normalize_items(items)
        keys = [item.key for item in self._values]
        self._state.replace(keys)
        # QListView does not implicitly select the first item after a model
        # reset. Keep an invalid current index until the user/caller chooses
        # one; this also prevents async suggestion lists from overwriting the
        # text the user is currently typing.
        if previous_current is None or previous_current not in keys:
            self._state.current = None
            self._state.anchor = None
        for child in list(self.backend.get_item_children(self.tag, 1) or []):
            try:
                self.backend.delete_item(child)
            except Exception:
                pass
        self.items.clear()
        for item in self._values:
            selectable = self.backend.add_selectable(
                parent=self.tag, label=item.text, width=-1,
                height=QtFusionMetrics.ROW_HEIGHT,
                default_value=item.key in self.selected,
                enabled=bool(item.enabled), user_data=item.key,
                callback=self._clicked,
            )
            self.items[item.key] = selectable
        self._sync_selection_visuals()
        try:
            self.backend.set_y_scroll(self.tag, old_scroll_y)
        except Exception:
            pass
        if previous_current != self.current:
            self.currentChanged.emit(self.current)
            self.currentTextChanged.emit(self.currentText())
        return self

    set_items = setItems

    def _clicked(self, sender, value, key):
        old_current = self.current
        self._row_clicked(sender, value, key)
        if old_current != self.current:
            self.currentTextChanged.emit(self.currentText())

    def setUniformItemSizes(self, enabled=True):
        # Rows already use one shared QtFusionMetrics.ROW_HEIGHT.  Retain the
        # familiar QListView property so callers can express intent without
        # depending on backend details.
        self._uniform_item_sizes = bool(enabled)
        return self

    def currentText(self):
        key = self.current
        item = next((item for item in self._values if item.key == key), None)
        return item.text if item is not None else ""

    def currentData(self):
        key = self.current
        item = next((item for item in self._values if item.key == key), None)
        return item.data if item is not None else None

    def setCurrentText(self, text):
        text = str(text)
        item = next((item for item in self._values if item.text == text), None)
        if item is None:
            return False
        changed = self.setCurrentKey(item.key, select=True)
        if changed:
            self.currentTextChanged.emit(item.text)
        return changed

    def _sync_selection_visuals(self):
        enabled_by_key = {value.key: bool(value.enabled) for value in self._values}
        for key, item in tuple(self.items.items()):
            selected = key in self.selected
            disabled = not enabled_by_key.get(key, True)
            try:
                self.backend.set_value(item, selected)
                self.backend.bind_item_theme(
                    item, qt_item_row_theme(
                        self.backend,
                        selected=selected,
                        disabled=disabled,
                        current=(key == self.current),
                        active=self._has_focus,
                    ))
            except Exception:
                pass

    def _focus_current(self):
        item = self.items.get(self.current)
        if item is not None:
            try:
                self.backend.focus_item(item)
            except Exception:
                pass


# Dear ImGui/Dear PyGui are the runtime backend.  Keep Qt* names as visual/
# behavioral compatibility contracts, but expose backend-explicit canonical
# aliases for new code so nobody mistakes the implementation for PyQt.
ImGuiItemViewState = QtItemViewState
ImGuiDataGridView = QtDataGridView
ImGuiListView = QtListView

# Familiar Qt names for callers that prefer model/view terminology.
QTableView = QtDataGridView
QListView = QtListView


__all__ = [
    "QtGridColumn", "QtGridRow", "QtListItem", "QtSelectionMode", "QtItemViewState",
    "QtDataGridView", "QtListView", "ImGuiItemViewState",
    "ImGuiDataGridView", "ImGuiListView", "ImGuiHeaderView", "QHeaderView",
    "QTableView", "QListView",
]
