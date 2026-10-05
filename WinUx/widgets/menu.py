"""Dear ImGui popup menus with a compact Qt/Fusion-like contract.

The renderer intentionally avoids Qt/Tk.  Each row is built from Dear PyGui
primitives so WinUx can show texture icons, check marks and hover-open submenus
without falling back to a second UI toolkit.
"""
from __future__ import annotations

from .core import QObject, Signal
from ..components.qt_style import QtFusionMetrics, QtFusionPalette


def _normalize_action(spec):
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
    item.setdefault("icon", None)
    item.setdefault("enabled", True)
    item.setdefault("visible", True)
    item.setdefault("checkable", False)
    item.setdefault("checked", False)
    item.setdefault("separator", item.get("label") == "---")
    item["children"] = [_normalize_action(child) for child in (item.get("children") or ())]
    return item


_MENU_THEME_TAG = "winux.imguiqt.menu"
_MENU_ROW_THEME_TAGS = {}
_MENU_TEXT_THEME_TAGS = {}


def _exists(backend, item):
    try:
        return bool(item is not None and backend.does_item_exist(item))
    except Exception:
        return False


def _menu_theme(backend):
    try:
        if backend.does_item_exist(_MENU_THEME_TAG):
            return _MENU_THEME_TAG
    except Exception:
        pass
    p = QtFusionPalette
    with backend.theme(tag=_MENU_THEME_TAG):
        with backend.theme_component(backend.mvAll):
            backend.add_theme_color(backend.mvThemeCol_WindowBg, p.MENU)
            backend.add_theme_color(backend.mvThemeCol_ChildBg, p.MENU)
            backend.add_theme_color(backend.mvThemeCol_PopupBg, p.MENU)
            backend.add_theme_color(backend.mvThemeCol_Text, p.TEXT)
            backend.add_theme_color(backend.mvThemeCol_TextDisabled, p.TEXT_DISABLED)
            backend.add_theme_color(backend.mvThemeCol_Separator, p.BORDER_LIGHT)
            backend.add_theme_color(backend.mvThemeCol_Border, p.BORDER)
            backend.add_theme_style(backend.mvStyleVar_WindowPadding, 4, 4)
            backend.add_theme_style(backend.mvStyleVar_ItemSpacing, 0, 0)
            backend.add_theme_style(backend.mvStyleVar_WindowRounding, QtFusionMetrics.POPUP_ROUNDING)
            backend.add_theme_style(backend.mvStyleVar_PopupRounding, QtFusionMetrics.POPUP_ROUNDING)
            backend.add_theme_style(backend.mvStyleVar_WindowBorderSize, 1)
    return _MENU_THEME_TAG


def _row_theme(backend, *, hovered=False, disabled=False):
    key = (bool(hovered), bool(disabled))
    cached = _MENU_ROW_THEME_TAGS.get(key)
    if _exists(backend, cached):
        return cached
    p = QtFusionPalette
    tag = "winux.imguiqt.menu.row.{}.{}".format(
        "hover" if hovered else "normal",
        "disabled" if disabled else "enabled",
    )
    with backend.theme(tag=tag):
        with backend.theme_component(backend.mvChildWindow):
            backend.add_theme_color(
                backend.mvThemeCol_ChildBg,
                p.MENU_HOVER if hovered and not disabled else p.MENU,
            )
            backend.add_theme_color(backend.mvThemeCol_Border, (0, 0, 0, 0))
            backend.add_theme_style(backend.mvStyleVar_WindowPadding, 0, 0)
            backend.add_theme_style(backend.mvStyleVar_ChildBorderSize, 0)
            backend.add_theme_style(backend.mvStyleVar_ChildRounding, 0)
            backend.add_theme_style(backend.mvStyleVar_ItemSpacing, 0, 0)
    _MENU_ROW_THEME_TAGS[key] = tag
    return tag


def _text_theme(backend, disabled=False):
    key = bool(disabled)
    cached = _MENU_TEXT_THEME_TAGS.get(key)
    if _exists(backend, cached):
        return cached
    p = QtFusionPalette
    tag = "winux.imguiqt.menu.text.{}".format("disabled" if disabled else "enabled")
    with backend.theme(tag=tag):
        with backend.theme_component(backend.mvText):
            backend.add_theme_color(
                backend.mvThemeCol_Text,
                p.TEXT_DISABLED if disabled else p.TEXT,
            )
    _MENU_TEXT_THEME_TAGS[key] = tag
    return tag


class ImGuiMenu(QObject):
    """Reusable icon-capable popup menu rendered only with Dear PyGui.

    The public surface is deliberately QMenu-like, but the implementation is a
    retained Dear ImGui widget.  Submenus are separate popup windows opened on
    row hover; rows support textures, checkable state and runtime enablement.
    """

    ROW_HEIGHT = 23
    ICON_SIZE = 16
    CHECK_SLOT = 16
    ICON_SLOT = 20
    ARROW_SLOT = 16
    LABEL_PAD = 8

    def __init__(self, actions=(), *, backend=None, after=None,
                 min_width=150, max_width=420, _parent_menu=None):
        super().__init__(after=after)
        if backend is None:
            import dearpygui.dearpygui as backend
        self.backend = backend
        self.triggered = Signal(self)
        self.aboutToShow = Signal(self)
        self.aboutToHide = Signal(self)
        self._actions = []
        self._items = {}
        self._rows = {}
        self._row_specs = {}
        self._handlers = []
        self._submenus = {}
        self._open_submenu = None
        self._context = None
        self._min_width = int(min_width)
        self._max_width = int(max_width)
        self._parent_menu = _parent_menu
        self._active_action = None
        self._keyboard_registry = None
        self.tag = backend.generate_uuid()
        with backend.window(
                tag=self.tag, popup=True, show=False, width=self._min_width,
                height=40, no_title_bar=True, no_resize=True, no_move=True,
                no_saved_settings=True, no_scrollbar=True,
                no_scroll_with_mouse=True):
            pass
        try:
            backend.bind_item_theme(self.tag, _menu_theme(backend))
        except Exception:
            pass
        self.setActions(actions)
        if self._parent_menu is None:
            self._install_keyboard_handlers()


    def _install_keyboard_handlers(self):
        b = self.backend
        try:
            with b.handler_registry() as registry:
                for key in (b.mvKey_Up, b.mvKey_Down, b.mvKey_Return,
                            b.mvKey_Escape, b.mvKey_Left, b.mvKey_Right):
                    b.add_key_press_handler(
                        key=key, callback=self._key_pressed, user_data=key)
            self._keyboard_registry = registry
        except Exception:
            self._keyboard_registry = None

    def _visible_action_ids(self):
        return [
            str(spec.get("action") or spec.get("id") or "")
            for spec in self._actions
            if spec.get("visible", True) and not spec.get("separator")
               and bool(spec.get("enabled", True))
        ]

    def _set_active_action(self, action_id):
        action_id = None if action_id is None else str(action_id)
        self._active_action = action_id
        for key in tuple(self._rows):
            self._set_row_hover(key, key == action_id)

    def _deepest_open_menu(self):
        menu = self
        seen = set()
        while menu._open_submenu is not None and id(menu) not in seen:
            seen.add(id(menu))
            child = menu._submenus.get(menu._open_submenu)
            if child is None:
                break
            menu = child
        return menu

    def _key_pressed(self, sender=None, app_data=None, user_data=None):
        root = self._root_menu()
        try:
            if not root.backend.is_item_shown(root.tag):
                return
        except Exception:
            return
        menu = root._deepest_open_menu()
        key = user_data
        ids = menu._visible_action_ids()
        if key == menu.backend.mvKey_Escape:
            root.hide()
            return
        if key == menu.backend.mvKey_Left and menu._parent_menu is not None:
            parent = menu._parent_menu
            parent._hide_open_submenu()
            return
        if not ids:
            return
        if menu._active_action not in ids:
            menu._set_active_action(ids[0])
        index = ids.index(menu._active_action)
        if key == menu.backend.mvKey_Up:
            menu._set_active_action(ids[(index - 1) % len(ids)])
            return
        if key == menu.backend.mvKey_Down:
            menu._set_active_action(ids[(index + 1) % len(ids)])
            return
        spec = menu._row_specs.get(menu._active_action)
        if spec is None:
            return
        if key == menu.backend.mvKey_Right and spec.get("children"):
            menu._show_submenu(menu._active_action, spec)
            child = menu._submenus.get(menu._active_action)
            if child is not None:
                child_ids = child._visible_action_ids()
                child._set_active_action(child_ids[0] if child_ids else None)
            return
        if key == menu.backend.mvKey_Return:
            menu._row_clicked(user_data=menu._active_action)

    def setActions(self, actions):
        self._actions = [_normalize_action(item) for item in (actions or ())]
        self._clear_rows()
        visible = [spec for spec in self._actions if spec.get("visible", True)]
        width = self._estimate_width(visible)
        height = 6
        for spec in visible:
            height += 7 if spec.get("separator") else self.ROW_HEIGHT
            self._build_row(spec, width)
        try:
            self.backend.configure_item(
                self.tag,
                width=max(self._min_width, min(self._max_width, width)),
                height=max(16, height),
            )
        except Exception:
            pass
        return self

    def _estimate_width(self, specs):
        longest = max((len(str(spec.get("label", ""))) for spec in specs), default=8)
        # Segoe UI 14 px is roughly 7 px per Latin glyph.  Leave stable slots
        # for check/icon/submenu arrow so labels align like QMenu rows.
        return max(
            self._min_width,
            min(self._max_width,
                self.CHECK_SLOT + self.ICON_SLOT + longest * 7 +
                self.ARROW_SLOT + self.LABEL_PAD * 3),
        )

    def _clear_rows(self):
        for submenu in tuple(self._submenus.values()):
            try:
                submenu.delete()
            except Exception:
                pass
        self._submenus.clear()
        self._open_submenu = None
        for registry in tuple(self._handlers):
            try:
                if self.backend.does_item_exist(registry):
                    self.backend.delete_item(registry)
            except Exception:
                pass
        self._handlers.clear()
        for child in list(self.backend.get_item_children(self.tag, 1) or []):
            try:
                self.backend.delete_item(child)
            except Exception:
                pass
        self._items.clear()
        self._rows.clear()
        self._row_specs.clear()

    def _glyph_color(self, enabled=True):
        return QtFusionPalette.TEXT if enabled else QtFusionPalette.TEXT_DISABLED

    def _redraw_check(self, canvas, *, checked=False, enabled=True):
        """Paint a compact Qt-style check mark with draw primitives."""
        if canvas is None:
            return
        b = self.backend
        try:
            b.delete_item(canvas, children_only=True)
        except Exception:
            pass
        if not checked:
            return
        color = self._glyph_color(enabled)
        b.draw_line((3, 12), (6, 15), color=color, thickness=1.4, parent=canvas)
        b.draw_line((6, 15), (12, 8), color=color, thickness=1.4, parent=canvas)

    def _redraw_submenu_arrow(self, canvas, *, visible=False, enabled=True):
        """Paint a compact right chevron without depending on font glyphs."""
        if canvas is None:
            return
        b = self.backend
        try:
            b.delete_item(canvas, children_only=True)
        except Exception:
            pass
        if not visible:
            return
        color = self._glyph_color(enabled)
        b.draw_line((5, 8), (9, 12), color=color, thickness=1.2, parent=canvas)
        b.draw_line((9, 12), (5, 16), color=color, thickness=1.2, parent=canvas)

    def _build_row(self, spec, width):
        b = self.backend
        if spec.get("separator"):
            b.add_spacer(parent=self.tag, height=3)
            b.add_separator(parent=self.tag)
            b.add_spacer(parent=self.tag, height=3)
            return
        action_id = str(spec.get("action") or spec.get("id") or "")
        row = b.add_child_window(
            parent=self.tag, width=max(1, int(width) - 8),
            height=self.ROW_HEIGHT, border=False,
            no_scrollbar=True, no_scroll_with_mouse=True,
        )
        self._rows[action_id] = row
        self._row_specs[action_id] = spec
        try:
            b.bind_item_theme(row, _row_theme(
                b, hovered=False, disabled=not bool(spec.get("enabled", True))))
        except Exception:
            pass

        # Fixed four-slot layout: check | icon | label | submenu arrow.
        with b.table(
                parent=row, header_row=False, width=-1, height=self.ROW_HEIGHT,
                policy=b.mvTable_SizingStretchProp, pad_outerX=False,
                borders_innerH=False, borders_outerH=False,
                borders_innerV=False, borders_outerV=False) as table:
            b.add_table_column(width_fixed=True, init_width_or_weight=self.CHECK_SLOT)
            b.add_table_column(width_fixed=True, init_width_or_weight=self.ICON_SLOT)
            b.add_table_column(width_stretch=True, init_width_or_weight=1.0)
            b.add_table_column(width_fixed=True, init_width_or_weight=self.ARROW_SLOT)
            with b.table_row():
                check_item = b.add_drawlist(width=self.CHECK_SLOT, height=self.ROW_HEIGHT)
                self._redraw_check(
                    check_item,
                    checked=bool(spec.get("checkable") and spec.get("checked")),
                    enabled=bool(spec.get("enabled", True)),
                )
                icon = spec.get("icon")
                if icon is not None:
                    try:
                        b.add_image(icon, width=self.ICON_SIZE, height=self.ICON_SIZE)
                    except Exception:
                        b.add_spacer(width=self.ICON_SIZE, height=self.ICON_SIZE)
                else:
                    b.add_spacer(width=self.ICON_SIZE, height=self.ICON_SIZE)
                label_item = b.add_text(str(spec.get("label", "")))
                arrow_item = b.add_drawlist(width=self.ARROW_SLOT, height=self.ROW_HEIGHT)
                self._redraw_submenu_arrow(
                    arrow_item,
                    visible=bool(spec.get("children")),
                    enabled=bool(spec.get("enabled", True)),
                )
        try:
            b.bind_item_theme(label_item, _text_theme(
                b, disabled=not bool(spec.get("enabled", True))))
        except Exception:
            pass
        self._items[action_id] = {
            "row": row,
            "check": check_item,
            "label": label_item,
            "arrow": arrow_item,
        }
        try:
            with b.item_handler_registry() as registry:
                b.add_item_hover_handler(
                    callback=self._row_hovered, user_data=action_id)
                b.add_item_clicked_handler(
                    button=b.mvMouseButton_Left,
                    callback=self._row_clicked, user_data=action_id)
            b.bind_item_handler_registry(row, registry)
            self._handlers.append(registry)
        except Exception:
            pass

    def _set_row_hover(self, action_id, hovered):
        spec = self._row_specs.get(action_id)
        row = self._rows.get(action_id)
        if spec is None or row is None:
            return
        try:
            self.backend.bind_item_theme(row, _row_theme(
                self.backend, hovered=bool(hovered),
                disabled=not bool(spec.get("enabled", True))))
        except Exception:
            pass

    def _row_hovered(self, sender=None, app_data=None, user_data=None):
        action_id = str(user_data or "")
        spec = self._row_specs.get(action_id)
        if spec is None:
            return
        self._set_active_action(action_id)
        if spec.get("children") and spec.get("enabled", True):
            self._show_submenu(action_id, spec)
        else:
            self._hide_open_submenu()

    def _row_clicked(self, sender=None, app_data=None, user_data=None):
        action_id = str(user_data or "")
        spec = self._row_specs.get(action_id)
        if spec is None or not spec.get("enabled", True):
            return
        if spec.get("children"):
            self._show_submenu(action_id, spec)
            return
        action = str(spec.get("action") or spec.get("id") or "")
        if spec.get("checkable"):
            spec["checked"] = not bool(spec.get("checked"))
            item = self._items.get(action_id, {})
            self._redraw_check(
                item.get("check"), checked=bool(spec["checked"]),
                enabled=bool(spec.get("enabled", True)))
        root = self._root_menu()
        root.triggered.emit(action, root._context)
        root.hide()

    def _root_menu(self):
        menu = self
        while menu._parent_menu is not None:
            menu = menu._parent_menu
        return menu

    def _show_submenu(self, action_id, spec):
        if self._open_submenu == action_id:
            return
        self._hide_open_submenu()
        submenu = self._submenus.get(action_id)
        if submenu is None:
            submenu = ImGuiMenu(
                spec.get("children") or (), backend=self.backend, after=self._after,
                min_width=self._min_width, max_width=self._max_width,
                _parent_menu=self,
            )
            # Leaf triggers are emitted by the root menu directly, but keep the
            # signal forwarding useful for programmatic callers/tests.
            self._submenus[action_id] = submenu
        row = self._rows.get(action_id)
        try:
            left, top = self.backend.get_item_rect_min(row)
            width, _height = self.backend.get_item_rect_size(row)
            submenu.popup((left + width - 2, top), context=self._root_menu()._context)
            self._open_submenu = action_id
        except Exception:
            pass

    def _hide_open_submenu(self):
        if self._open_submenu is None:
            return
        submenu = self._submenus.get(self._open_submenu)
        if submenu is not None:
            submenu.hide()
        self._open_submenu = None

    def popup(self, position=None, *, context=None):
        self._context = context
        if self._parent_menu is None:
            self.aboutToShow.emit(context)
        if position is not None:
            try:
                self.backend.set_item_pos(self.tag, tuple(position))
            except Exception:
                pass
        try:
            self.backend.configure_item(self.tag, show=True)
            ids = self._visible_action_ids()
            self._set_active_action(ids[0] if ids else None)
            return True
        except Exception:
            return False

    def hide(self):
        self._hide_open_submenu()
        for submenu in tuple(self._submenus.values()):
            try:
                submenu.hide()
            except Exception:
                pass
        try:
            self.backend.configure_item(self.tag, show=False)
        except Exception:
            return False
        if self._parent_menu is None:
            self.aboutToHide.emit(self._context)
        return True

    def context(self):
        return self._context

    def _find_spec(self, action):
        target = str(action)
        stack = list(self._actions)
        while stack:
            spec = stack.pop(0)
            if str(spec.get("action") or spec.get("id") or "") == target:
                return spec
            stack[0:0] = list(spec.get("children") or ())
        return None

    def setActionEnabled(self, action, enabled):
        target = str(action)
        spec = self._find_spec(target)
        if spec is None:
            return False
        spec["enabled"] = bool(enabled)
        # Specs that live in a child menu need their child renderer updated.
        for menu in self._walk_menus():
            local_spec = menu._row_specs.get(target)
            if local_spec is None:
                continue
            local_spec["enabled"] = bool(enabled)
            menu._set_row_hover(target, False)
            items = menu._items.get(target, {})
            label_item = items.get("label")
            if label_item is not None:
                try:
                    menu.backend.bind_item_theme(
                        label_item, _text_theme(menu.backend, disabled=not bool(enabled)))
                except Exception:
                    pass
            menu._redraw_check(
                items.get("check"), checked=bool(local_spec.get("checked")),
                enabled=bool(enabled))
            menu._redraw_submenu_arrow(
                items.get("arrow"), visible=bool(local_spec.get("children")),
                enabled=bool(enabled))
            return True
        return True

    def setActionChecked(self, action, checked):
        target = str(action)
        spec = self._find_spec(target)
        if spec is None:
            return False
        spec["checked"] = bool(checked)
        for menu in self._walk_menus():
            local_spec = menu._row_specs.get(target)
            if local_spec is None:
                continue
            local_spec["checked"] = bool(checked)
            item = menu._items.get(target, {}).get("check")
            if item is not None:
                menu._redraw_check(
                    item, checked=bool(checked),
                    enabled=bool(local_spec.get("enabled", True)))
            return True
        return True

    def _walk_menus(self):
        yield self
        for submenu in tuple(self._submenus.values()):
            yield from submenu._walk_menus()

    def delete(self):
        if self._deleted:
            return
        self._clear_rows()
        if self._keyboard_registry is not None:
            try:
                if self.backend.does_item_exist(self._keyboard_registry):
                    self.backend.delete_item(self._keyboard_registry)
            except Exception:
                pass
            self._keyboard_registry = None
        try:
            if self.backend.does_item_exist(self.tag):
                self.backend.delete_item(self.tag)
        finally:
            super().delete()


QMenu = ImGuiMenu

__all__ = ["ImGuiMenu", "QMenu"]
