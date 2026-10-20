"""Explorer context-menu state backed by DearUIQt :class:`QMenu`.

The Explorer used to own a second, renderer-specific menu engine beside
DearUIQt.  The public/compatibility methods remain here, while popup ownership,
submenus, keyboard navigation, check marks, shortcut columns, hit-testing and
popup input ownership now live in DearUIQt.
"""
from __future__ import annotations

from DearUIQt.gui import QCursor
from DearUIQt.widgets import QMenu

EXPLORER_MENU_TAGS = set()


def normalize_menu_item(spec):
    """Return a mutable QMenu-compatible dictionary from tuple/dict input."""
    if isinstance(spec, dict):
        item = dict(spec)
    elif isinstance(spec, (tuple, list)):
        if len(spec) < 2:
            raise ValueError("Menu tuple must contain at least (label, action)")
        item = {"label": spec[0], "action": spec[1]}
        if len(spec) > 2:
            item["icon"] = spec[2]
    else:
        raise TypeError("Menu item must be a dict, tuple or list")
    item.setdefault("id", item.get("action") or item.get("label"))
    item.setdefault("label", "")
    item.setdefault("action", None)
    item.setdefault("icon", None)
    item.setdefault("shortcut", None)
    item.setdefault("enabled", True)
    item.setdefault("visible", True)
    item.setdefault("checkable", False)
    item.setdefault("checked", False)
    item.setdefault("separator", item.get("label") == "---")
    item["children"] = [normalize_menu_item(child) for child in (item.get("children") or ())]
    return item


_normalize_menu_item = normalize_menu_item
_EXPLORER_MENU_TAGS = EXPLORER_MENU_TAGS


class ExplorerContextMenuMixin:
    # ------------------------------------------------------------------
    # Compatibility surface for the former Explorer-owned popup shield.
    # QMenu now owns a logical QApplication popup grab; no visual shield exists.
    def _active_context_menu(self):
        item = getattr(self, "_item_context_menu", None)
        if item is not None and item.isVisible():
            return item
        header = getattr(self, "_header_context_menu", None)
        if header is not None and header.isVisible():
            return header
        return item or header

    def _ensure_context_input_shield(self):
        menu = self._active_context_menu()
        return getattr(menu, "_input_shield_tag", None) if menu is not None else None

    def _show_context_input_shield(self):
        menu = self._active_context_menu()
        return bool(menu is not None and menu._show_input_shield())

    def _hide_context_input_shield(self):
        for menu in (getattr(self, "_item_context_menu", None),
                     getattr(self, "_header_context_menu", None)):
            if menu is not None:
                menu._hide_input_shield()

    def _acquire_context_popup_input(self):
        # QMenu.popup() owns the application popup grab.  Keep this method so
        # older Explorer collaborators do not need to know where ownership moved.
        self._context_popup_input_owned = False
        return False

    def _release_context_popup_input(self, *, consume_pointer=False):
        self._context_popup_input_owned = False
        self._hide_context_input_shield()

    # ------------------------------------------------------------------ item menu
    def set_context_menu(self, items):
        self.item_menu_spec = [normalize_menu_item(x) for x in items]
        self._build_item_context_menu(rebuild=True)
        return self

    def _find_context_menu_action_spec(self, action, items=None):
        action = str(action)
        for item in (self.item_menu_spec if items is None else items):
            if str(item.get("action")) == action:
                return item
            child = self._find_context_menu_action_spec(action, item.get("children") or [])
            if child is not None:
                return child
        return None

    def set_context_menu_item_checked(self, action, checked):
        action = str(action)
        spec = self._find_context_menu_action_spec(action)
        if spec is None:
            return False
        spec["checked"] = bool(checked)
        menu = getattr(self, "_item_context_menu", None)
        return bool(menu is None or menu.setActionChecked(action, bool(checked)))

    def set_context_menu_item_enabled(self, action, enabled):
        action = str(action)
        spec = self._find_context_menu_action_spec(action)
        if spec is None:
            return False
        spec["enabled"] = bool(enabled)
        menu = getattr(self, "_item_context_menu", None)
        return bool(menu is None or menu.setActionEnabled(action, bool(enabled)))

    def add_context_menu_item(self, label, action=None, icon=None, index=None,
                              item_id=None, enabled=True, visible=True):
        spec = normalize_menu_item({
            "id": item_id or action or label, "label": label, "action": action,
            "icon": icon, "enabled": enabled, "visible": visible,
        })
        self.item_menu_spec.insert(
            len(self.item_menu_spec) if index is None else int(index), spec)
        self._build_item_context_menu(rebuild=True)
        return spec["id"]

    def remove_context_menu_item(self, item_id):
        self.item_menu_spec = [x for x in self.item_menu_spec if x.get("id") != item_id]
        self._build_item_context_menu(rebuild=True)
        return self

    def update_context_menu_item(self, item_id, **changes):
        item = next((x for x in self.item_menu_spec if x.get("id") == item_id), None)
        if item is None:
            raise KeyError(item_id)
        item.update(changes)
        item["children"] = [normalize_menu_item(x) for x in item.get("children") or ()]
        self._build_item_context_menu(rebuild=True)
        return self

    def _build_item_context_menu(self, rebuild=False):
        menu = getattr(self, "_item_context_menu", None)
        if rebuild and menu is not None:
            EXPLORER_MENU_TAGS.discard(menu.tag)
            menu.delete()
            menu = None
        if menu is None or not menu.exists():
            menu = QMenu(
                self.item_menu_spec, after=getattr(self, "after", None),
                min_width=266, max_width=420)
            menu.triggered.connect(
                lambda action, _context: self._on_item_menu_action(None, None, action))
            self._item_context_menu = menu
            EXPLORER_MENU_TAGS.add(menu.tag)
        else:
            menu.setActions(self.item_menu_spec)
        self.itemmenu_tag = menu.tag
        # Compatibility aliases retained until all Explorer collaborators stop
        # reaching into the old renderer-owned menu bookkeeping.
        self._context_menu_group_tags = {}
        self._context_menu_group_rows = {}
        self._context_submenu_tags = {}
        self._context_menu_row_controls = {}
        self._context_menu_action_controls = {}
        self._active_context_submenu_group = None
        return menu

    def _show_item_context_menu(self, position=None):
        menu = self._build_item_context_menu()
        if position is None:
            point = QCursor.screenPos(backend=getattr(self, "backend", None))
            position = (point.x(), point.y())
        menu.setActions(self.item_menu_spec)
        return menu.popupGlobal(position, context={"index": self._context_item_index})

    # --------------------------------------------------------------- header menu
    def _header_menu_specs(self):
        specs = []
        visible_count = len(self._visible_columns())
        for column in self.columns:
            key = str(column.get("key"))
            shown = bool(column.get("visible", True))
            specs.append({
                "id": f"column:{key}", "action": f"column:{key}",
                "label": str(column.get("label") or key),
                "checkable": True, "checked": shown,
                "enabled": (not shown or visible_count > 1),
            })
        specs.extend([
            {"separator": True, "label": "---", "id": "header-separator"},
            {"id": "auto-width", "action": "auto-width", "label": "Auto Width",
             "checkable": True, "checked": bool(self.auto_width_enabled)},
        ])
        return specs

    def _build_header_context_menu(self):
        menu = getattr(self, "_header_context_menu", None)
        if menu is not None and menu.exists():
            return menu
        menu = QMenu(
            self._header_menu_specs(), after=getattr(self, "after", None),
            min_width=220, max_width=320)
        menu.triggered.connect(self._on_header_menu_triggered)
        self._header_context_menu = menu
        self.header_menu_tag = menu.tag
        EXPLORER_MENU_TAGS.add(menu.tag)
        return menu

    def _sync_header_context_menu_state(self):
        menu = self._build_header_context_menu()
        menu.setActions(self._header_menu_specs())
        return menu

    def _on_header_menu_triggered(self, action, _context=None):
        action = str(action)
        if action.startswith("column:"):
            key = action.split(":", 1)[1]
            column = next((c for c in self.columns if str(c.get("key")) == key), None)
            if column is not None:
                self.set_column_visible(key, not bool(column.get("visible", True)))
        elif action == "auto-width":
            self.set_auto_width(not bool(self.auto_width_enabled))
        self._sync_header_context_menu_state()

    def _on_header_column_check(self, sender=None, app_data=None, user_data=None):
        key = str(user_data or "")
        try:
            self.set_column_visible(key, bool(app_data))
        finally:
            self._sync_header_context_menu_state()

    def _on_header_auto_width_check(self, sender=None, app_data=None, user_data=None):
        self.set_auto_width(bool(app_data))
        self._sync_header_context_menu_state()

    def _show_header_context_menu(self):
        self._hide_context_menus()
        menu = self._sync_header_context_menu_state()
        point = QCursor.screenPos(backend=getattr(self, "backend", None))
        return menu.popupGlobal((point.x(), point.y()), context={"header": True})

    # ------------------------------------------------------- compatibility helpers
    def _delete_context_menu_windows(self):
        self._hide_context_menus()
        for name in ("_item_context_menu", "_header_context_menu"):
            menu = getattr(self, name, None)
            if menu is not None:
                EXPLORER_MENU_TAGS.discard(menu.tag)
                try:
                    menu.delete()
                except Exception:
                    pass
                setattr(self, name, None)
        self.itemmenu_tag = None
        self.header_menu_tag = None
        self._context_submenu_tags = {}

    def _render_context_menu_check_slot(self, slot, spec, enabled=True):
        # Retained compatibility hook: QMenu now owns check-slot painting.
        action = spec.get("action") if spec else None
        menu = getattr(self, "_item_context_menu", None)
        if action is not None and menu is not None:
            menu.setActionEnabled(action, enabled)
            menu.setActionChecked(action, bool(spec.get("checked")))

    def _add_context_menu_item(self, spec, parent=None, submenu=False):
        # QMenu materializes the normalized specification in one pass.
        return normalize_menu_item(spec)

    @staticmethod
    def _context_keyboard_eligible(spec):
        return bool(spec and spec.get("visible", True) and
                    not spec.get("separator") and spec.get("enabled", True))

    def _context_menu_spec_by_id(self, item_id, items=None):
        target = str(item_id)
        for spec in (self.item_menu_spec if items is None else items):
            if str(spec.get("id") or spec.get("action") or "") == target:
                return spec
            found = self._context_menu_spec_by_id(target, spec.get("children") or [])
            if found is not None:
                return found
        return None

    def _context_keyboard_candidates(self):
        menu = getattr(self, "_item_context_menu", None)
        if menu is None:
            return []
        target = menu._deepest_open_menu()
        return target._visible_action_ids()

    def _set_context_keyboard_id(self, item_id):
        self._context_keyboard_id = None if item_id is None else str(item_id)
        menu = getattr(self, "_item_context_menu", None)
        if menu is not None and menu.isVisible():
            target = menu._deepest_open_menu()
            target._set_active_action(self._context_keyboard_id)

    def _on_context_menu_key(self, sender=None, app_data=None, user_data=None):
        menu = getattr(self, "_item_context_menu", None)
        if menu is None or not menu.isVisible():
            return False
        handled = menu.navigate(user_data)
        target = menu._deepest_open_menu()
        self._context_keyboard_id = target._active_action
        return handled

    def _context_menu_is_visible(self):
        return any(menu is not None and menu.isVisible() for menu in (
            getattr(self, "_item_context_menu", None),
            getattr(self, "_header_context_menu", None),
        ))

    def _mouse_inside_context_menus(self):
        point = QCursor.pos()
        return any(menu is not None and menu.isVisible() and
                   menu.containsPopupPoint(point) for menu in (
                       getattr(self, "_item_context_menu", None),
                       getattr(self, "_header_context_menu", None),
                   ))

    def _point_in_visible_window(self, tag, point=None):
        for menu in (getattr(self, "_item_context_menu", None),
                     getattr(self, "_header_context_menu", None)):
            if menu is not None and menu.tag == tag and menu.isVisible():
                point = QCursor.pos() if point is None else point
                return menu.containsPopupPoint(point)
        return False

    def _context_window_size(self, tag, default_width):
        for menu in (getattr(self, "_item_context_menu", None),
                     getattr(self, "_header_context_menu", None)):
            if menu is not None and menu.tag == tag:
                geometry = menu.globalGeometry(clipped=False)
                return float(geometry.width() or default_width), float(geometry.height() or 36)
        return float(default_width), 36.0

    def _clamp_context_position(self, tag, x, y, default_width):
        # QMenu.popup() performs viewport clamping. Preserve this helper as an
        # identity adapter for old pointer-dispatch collaborators.
        return float(x), float(y)

    def _hide_context_submenus(self, except_tag=None):
        menu = getattr(self, "_item_context_menu", None)
        if menu is not None:
            menu._hide_open_submenu()
        self._active_context_submenu_group = None

    def _hide_context_menus(self, *, consume_pointer=False):
        for menu in (getattr(self, "_item_context_menu", None),
                     getattr(self, "_header_context_menu", None)):
            if menu is not None:
                menu.hide(consume_pointer=consume_pointer)
        self._context_keyboard_id = None
        self._context_popup_input_owned = False

    def _show_context_submenu(self, sender=None, app_data=None, user_data=None):
        menu = getattr(self, "_item_context_menu", None)
        return bool(menu is not None and menu.navigate("right"))

    def _update_context_submenu_hover(self):
        # QMenu rows own hover-open submenu routing internally.
        return self._mouse_inside_context_menus()

    def _on_item_menu_action(self, sender, app_data, user_data):
        action = str(user_data)
        spec = self._find_context_menu_action_spec(action)
        # Widgets remain technically enabled so Dear PyGui preserves the same
        # left-aligned row geometry. Ignore clicks for logically disabled
        # commands and leave the context menu open, like Windows Explorer.
        if spec is not None and not bool(spec.get("enabled", True)):
            return

        # Snapshot all callback state before hiding the reusable windows.  This
        # prevents focus/selection changes during window hide from invalidating
        # the action or its target list.
        context_index = self._context_item_index
        has_context_item = (
            context_index is not None
            and 0 <= context_index < len(self.items)
        )
        command = action.split(":", 1)[1] if action.startswith("command:") else action
        if not has_context_item and command not in {
            "new_folder", "new_file", "paste", "refresh",
        }:
            self._hide_context_menus(consume_pointer=True)
            return
        targets = list(self.get_selected() or [self.items[context_index]]) if has_context_item else []
        self._hide_context_menus(consume_pointer=True)
        if action == "open" and targets:
            self.activate_item(targets[0])
            return
        if action == "copy":
            self.copy_selected(); return
        if action == "cut":
            self.cut_selected(); return
        if action == "paste":
            destination = targets[0].path if len(targets) == 1 and targets[0].is_dir else self.current_path
            self.paste(destination); return
        if action == "rename":
            if self.on_item_menu_action:
                self.on_item_menu_action("command:rename", targets)
            else:
                self.begin_inline_rename(self._context_item_index)
            return
        if action == "delete":
            if self.on_item_menu_action:
                self.on_item_menu_action("command:delete", targets)
            return
        if self.on_item_menu_action:
            self.on_item_menu_action(action, targets)
