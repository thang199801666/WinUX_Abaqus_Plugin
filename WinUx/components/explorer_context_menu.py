"""Explorer-style context-menu state, rendering and keyboard behavior."""
from __future__ import annotations

import dearpygui.dearpygui as dpg

from .interaction_gate import register_pointer_protected_item, unregister_pointer_protected_item
from .qt_style import QtFusionPalette

EXPLORER_MENU_TAGS = set()

def normalize_menu_item(spec):
    """Return a mutable menu-item dictionary from tuple or dict input."""
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
    item.setdefault("enabled", True)
    item.setdefault("visible", True)
    item.setdefault("checkable", False)
    item.setdefault("checked", False)
    item.setdefault("separator", item.get("label") == "---")
    children = item.get("children") or []
    item["children"] = [normalize_menu_item(child) for child in children]
    return item

# Backward-compatible private spelling used by the original implementation.
_normalize_menu_item = normalize_menu_item
_EXPLORER_MENU_TAGS = EXPLORER_MENU_TAGS


class ExplorerContextMenuMixin:
    def set_context_menu(self, items):
        self.item_menu_spec = [_normalize_menu_item(x) for x in items]
        self._build_item_context_menu(rebuild=True); return self

    def _find_context_menu_action_spec(self, action, items=None):
        action = str(action)
        for item in (self.item_menu_spec if items is None else items):
            if str(item.get("action")) == action:
                return item
            child = self._find_context_menu_action_spec(
                action, item.get("children") or [])
            if child is not None:
                return child
        return None

    def set_context_menu_item_checked(self, action, checked):
        """Update a checkable context-menu row without rebuilding the popup.

        Checkable rows use the normal icon column as a native-looking check
        column.  This lets callers keep stateful commands (for example Job
        Viewer -> Plots) synchronized while the same reusable popup is used for
        different rows.
        """
        action = str(action)
        checked = bool(checked)
        spec = self._find_context_menu_action_spec(action)
        if spec is None:
            return False
        spec["checked"] = checked
        controls = self._context_menu_action_controls.get(action) or {}
        slot = controls.get("check_slot")
        if slot and dpg.does_item_exist(slot):
            self._render_context_menu_check_slot(
                slot, spec, bool(spec.get("enabled", True)))
        return True

    def set_context_menu_item_enabled(self, action, enabled):
        """Enable/disable an existing context-menu action without rebuilding it.

        Works for both top-level rows and submenu children. Disabled rows retain
        their Explorer-menu geometry and are rendered in muted gray.
        """
        action = str(action)
        enabled = bool(enabled)
        spec = self._find_context_menu_action_spec(action)
        if spec is not None:
            spec["enabled"] = enabled
        controls = self._context_menu_action_controls.get(action)
        if not controls:
            return False
        button = controls.get("button")
        icon = controls.get("icon")
        # Keep the Dear PyGui widgets technically enabled. DPG changes text
        # alignment and applies its own disabled colors when enabled=False,
        # which makes disabled labels jump to the center and ignores our gray
        # Explorer theme. Permission is enforced logically in the callback.
        if button and dpg.does_item_exist(button):
            dpg.configure_item(button, enabled=True)
            dpg.bind_item_theme(
                button,
                self._context_menu_button_theme if enabled else self._context_menu_disabled_button_theme,
            )
        if icon and dpg.does_item_exist(icon):
            dpg.configure_item(icon, enabled=True)
            dpg.bind_item_theme(
                icon,
                self._context_menu_icon_theme if enabled else self._context_menu_disabled_icon_theme,
            )
        check_slot = controls.get("check_slot")
        if check_slot and dpg.does_item_exist(check_slot) and spec is not None:
            self._render_context_menu_check_slot(check_slot, spec, enabled)
        return True

    def add_context_menu_item(self, label, action=None, icon=None, index=None, item_id=None, enabled=True, visible=True):
        spec = _normalize_menu_item({"id": item_id or action or label, "label": label, "action": action, "icon": icon, "enabled": enabled, "visible": visible})
        self.item_menu_spec.insert(len(self.item_menu_spec) if index is None else int(index), spec)
        self._build_item_context_menu(rebuild=True); return spec["id"]

    def remove_context_menu_item(self, item_id):
        self.item_menu_spec = [x for x in self.item_menu_spec if x.get("id") != item_id]
        self._build_item_context_menu(rebuild=True); return self

    def update_context_menu_item(self, item_id, **changes):
        item = next((x for x in self.item_menu_spec if x.get("id") == item_id), None)
        if item is None: raise KeyError(item_id)
        item.update(changes); self._build_item_context_menu(rebuild=True); return self

    def _build_item_context_menu(self, rebuild=False):
        self.itemmenu_tag = f"{self.uid}_itemmenu"
        if rebuild:
            self._delete_context_menu_windows()
        if dpg.does_item_exist(self.itemmenu_tag):
            return

        self._context_menu_group_tags = {}
        self._context_menu_group_rows = {}
        self._context_submenu_tags = {}
        self._context_menu_row_controls = {}
        self._context_keyboard_id = None
        self._active_context_submenu_group = None
        submenu_specs = []
        with dpg.window(
            tag=self.itemmenu_tag, popup=False, show=False, no_title_bar=True,
            no_saved_settings=True, no_resize=True, no_scrollbar=True,
            no_collapse=True, no_move=True, no_bring_to_front_on_focus=False,
            width=266, min_size=(266, 10), max_size=(266, 640),
        ):
            for spec in self.item_menu_spec:
                if spec.get("children"):
                    submenu_specs.append(spec)
                self._add_context_menu_item(spec, parent=self.itemmenu_tag)
        dpg.bind_item_theme(self.itemmenu_tag, self.theme_popup)
        _EXPLORER_MENU_TAGS.add(self.itemmenu_tag)
        register_pointer_protected_item(self.itemmenu_tag)

        # Child menus are independent popup windows, like Explorer fly-outs.
        for spec in submenu_specs:
            group_id = str(spec.get("id") or spec.get("label", "submenu"))
            submenu_tag = f"{self.uid}_submenu_{len(self._context_submenu_tags)}"
            self._context_submenu_tags[group_id] = submenu_tag
            with dpg.window(
                tag=submenu_tag, popup=False, show=False, no_title_bar=True,
                no_saved_settings=True, no_resize=True, no_scrollbar=True,
                no_collapse=True, no_move=True, no_bring_to_front_on_focus=False,
                width=244, min_size=(244, 10), max_size=(244, 500),
            ):
                for child in spec.get("children") or []:
                    self._add_context_menu_item(child, parent=submenu_tag, submenu=True)
            dpg.bind_item_theme(submenu_tag, self.theme_popup)
            _EXPLORER_MENU_TAGS.add(submenu_tag)
            register_pointer_protected_item(submenu_tag)

    def _delete_context_menu_windows(self):
        tags = [getattr(self, "itemmenu_tag", None)]
        tags.extend(getattr(self, "_context_submenu_tags", {}).values())
        for tag in tags:
            if tag:
                _EXPLORER_MENU_TAGS.discard(tag)
                unregister_pointer_protected_item(tag)
                if dpg.does_item_exist(tag):
                    dpg.delete_item(tag)

    def _render_context_menu_check_slot(self, slot, spec, enabled=True):
        """Render a check mark or the row icon into a fixed 28px menu slot."""
        if not slot or not dpg.does_item_exist(slot):
            return
        try:
            dpg.delete_item(slot, children_only=True)
        except Exception:
            pass
        color = (30, 105, 190, 255) if enabled else QtFusionPalette.TEXT_DISABLED
        if bool(spec.get("checked", False)):
            # Geometry avoids dependence on the active font atlas containing a
            # Unicode check-mark glyph.
            dpg.draw_line((7, 14), (11, 18), color=color, thickness=2.2, parent=slot)
            dpg.draw_line((11, 18), (21, 8), color=color, thickness=2.2, parent=slot)
            return
        texture = self._resolve_icon_texture(spec.get("icon")) if spec.get("icon") else None
        if texture:
            tint = (255, 255, 255, 255) if enabled else (170, 170, 170, 180)
            # Dear PyGui draw_image() uses the keyword ``color`` for
            # image tinting. ``tint_color`` belongs to image widgets and is
            # rejected by the bundled DPG build, which used to make WinUx
            # fail during startup as soon as a checkable menu row (Plots)
            # was constructed.
            dpg.draw_image(
                texture, (6, 6), (22, 22),
                uv_min=(0, 0), uv_max=(1, 1), color=tint, parent=slot)

    def _add_context_menu_item(self, spec, parent, submenu=False):
        if not spec.get("visible", True):
            return
        if spec.get("separator"):
            dpg.add_spacer(height=3, parent=parent)
            dpg.add_separator(parent=parent)
            dpg.add_spacer(height=3, parent=parent)
            return

        children = spec.get("children") or []
        label = str(spec.get("label", ""))
        enabled = bool(spec.get("enabled", True))
        icon = spec.get("icon")
        group_id = str(spec.get("id") or label)
        row_index = len(self._context_menu_group_tags) + len(self._context_submenu_tags)
        row_tag = f"{self.uid}_menu_row_{row_index}_{abs(hash((label, submenu))) % 100000}"
        # Submenu arrows are independent controls, not spaces appended to the
        # label.  This keeps every solid arrow in one right-aligned column no
        # matter how long the action text or which font/DPI is active.
        base_text_width = 210 if submenu else 232
        arrow_width = 16 if children else 0
        text_width = base_text_width - arrow_width
        callback = self._show_context_submenu if children else self._on_item_menu_action
        callback_data = group_id if children else spec.get("action")

        # Use equal-height image, label and optional arrow buttons. All controls
        # live in the same 28 px row.
        texture = self._resolve_icon_texture(icon) if icon else None
        group_tag = f"{row_tag}_group"
        icon_button = None
        check_slot = None
        arrow_button = None
        with dpg.group(tag=group_tag, parent=parent, horizontal=True, horizontal_spacing=0):
            if bool(spec.get("checkable", False)):
                check_slot = dpg.add_drawlist(width=28, height=28)
                self._render_context_menu_check_slot(check_slot, spec, enabled)
                with dpg.item_handler_registry() as check_handlers:
                    dpg.add_item_clicked_handler(
                        callback=callback, user_data=callback_data)
                dpg.bind_item_handler_registry(check_slot, check_handlers)
            elif texture:
                icon_button = dpg.add_image_button(
                    texture, width=16, height=16, enabled=True,
                    callback=callback, user_data=callback_data,
                )
                dpg.bind_item_theme(
                    icon_button,
                    self._context_menu_icon_theme if enabled else self._context_menu_disabled_icon_theme,
                )
            else:
                dpg.add_spacer(width=28, height=28)

            button = dpg.add_button(
                tag=row_tag, label=label,
                width=text_width, height=28, enabled=True,
                callback=callback, user_data=callback_data,
            )
            if children:
                # Draw the submenu indicator as geometry instead of a Unicode
                # glyph.  Some Dear PyGui font atlases do not include the
                # black-triangle character, which rendered as a replacement
                # symbol on Windows.  A draw primitive is DPI/font independent.
                arrow_button = dpg.add_drawlist(
                    tag=f"{row_tag}_arrow", width=arrow_width, height=28
                )
                arrow_color = (0, 0, 0, 255) if enabled else QtFusionPalette.TEXT_DISABLED
                dpg.draw_triangle(
                    (7, 12), (7, 16), (10, 14),
                    color=arrow_color, fill=arrow_color,
                    parent=arrow_button,
                )
                with dpg.item_handler_registry() as arrow_handlers:
                    dpg.add_item_clicked_handler(
                        callback=callback, user_data=callback_data
                    )
                dpg.bind_item_handler_registry(arrow_button, arrow_handlers)
        dpg.bind_item_theme(
            button,
            self._context_menu_button_theme if enabled else self._context_menu_disabled_button_theme,
        )
        self._context_menu_row_controls[group_id] = {
            "button": button,
            "spec": spec,
            "parent": parent,
            "submenu": bool(submenu),
        }
        action_key = spec.get("action")
        if action_key is not None:
            self._context_menu_action_controls[str(action_key)] = {
                "button": button,
                "icon": icon_button,
                "check_slot": check_slot,
            }
        if children:
            # Submenus are opened only by an explicit click/select.  Do not
            # bind an item-hover handler here; merely moving the mouse across
            # the parent row must not open or switch fly-out menus.
            self._context_menu_group_tags[group_id] = button
            self._context_menu_group_rows[group_id] = group_tag

    @staticmethod
    def _point_in_visible_window(tag, point=None):
        """Robust hit-test for the reusable context-menu windows.

        ``get_item_rect_min/max`` may keep stale geometry for a window that was
        hidden and shown again.  That caused a click on a menu action to be
        classified as an outside click, hiding the window before the button
        callback could run.  Prefer Dear PyGui's hover state, then fall back to
        the configured window position and measured/configured size.
        """
        if not tag or not dpg.does_item_exist(tag) or not dpg.is_item_shown(tag):
            return False
        try:
            if dpg.is_item_hovered(tag):
                return True
        except Exception:
            pass
        try:
            mx, my = point or dpg.get_mouse_pos(local=False)
            left, top = dpg.get_item_pos(tag)
            cfg = dpg.get_item_configuration(tag) or {}

            width = 0.0
            height = 0.0
            try:
                size = dpg.get_item_rect_size(tag)
                width, height = float(size[0]), float(size[1])
            except Exception:
                pass
            if width <= 1.0:
                width = float(cfg.get("width") or (244 if "_submenu_" in str(tag) else 266))
            if height <= 1.0:
                # Estimate only as a last-frame fallback.  Each normal row is
                # 28 px plus 2 px spacing; separators/spacers remain inside the
                # generous 38 px allowance used here.
                children = dpg.get_item_children(tag, 1) or []
                height = max(36.0, len(children) * 38.0 + 12.0)

            return (float(left) <= float(mx) <= float(left) + width and
                    float(top) <= float(my) <= float(top) + height)
        except Exception:
            return False

    def _context_window_size(self, tag, default_width):
        """Return a stable visible/configured size for a reusable menu window."""
        width = float(default_width)
        height = 36.0
        try:
            cfg = dpg.get_item_configuration(tag) or {}
            width = float(cfg.get("width") or width)
        except Exception:
            pass
        try:
            measured = dpg.get_item_rect_size(tag)
            if float(measured[0]) > 1.0:
                width = float(measured[0])
            if float(measured[1]) > 1.0:
                height = float(measured[1])
                return width, height
        except Exception:
            pass
        try:
            children = dpg.get_item_children(tag, 1) or []
            # Rows are 28 px with 2 px spacing. Separators and their spacers
            # are represented by separate children, so 30 px per child is a
            # safe estimate that prevents the window from crossing the app.
            height = max(36.0, min(640.0, len(children) * 30.0 + 12.0))
        except Exception:
            pass
        return width, height

    def _clamp_context_position(self, tag, x, y, default_width):
        """Clamp a menu window completely inside the Dear PyGui viewport."""
        width, height = self._context_window_size(tag, default_width)
        try:
            viewport_w = max(1.0, float(dpg.get_viewport_client_width()))
            viewport_h = max(1.0, float(dpg.get_viewport_client_height()))
        except Exception:
            viewport_w, viewport_h = 1280.0, 720.0
        margin = 2.0
        x = min(max(margin, float(x)), max(margin, viewport_w - width - margin))
        y = min(max(margin, float(y)), max(margin, viewport_h - height - margin))
        return x, y

    def _context_menu_spec_by_id(self, item_id, items=None):
        item_id = str(item_id or "")
        for spec in (self.item_menu_spec if items is None else items):
            group_id = str(spec.get("id") or spec.get("label", ""))
            if group_id == item_id:
                return spec
            child = self._context_menu_spec_by_id(
                item_id, spec.get("children") or [])
            if child is not None:
                return child
        return None

    @staticmethod
    def _context_keyboard_eligible(spec):
        return bool(
            spec
            and spec.get("visible", True)
            and not spec.get("separator", False)
            and spec.get("enabled", True)
        )

    def _context_keyboard_candidates(self):
        group = self._active_context_submenu_group
        if group:
            parent = self._context_menu_spec_by_id(group)
            specs = (parent or {}).get("children") or []
        else:
            specs = self.item_menu_spec
        return [
            str(spec.get("id") or spec.get("label", ""))
            for spec in specs if self._context_keyboard_eligible(spec)
        ]

    def _set_context_keyboard_id(self, item_id):
        """Apply a Qt QMenu-like keyboard focus row without changing enabled state."""
        previous = self._context_keyboard_id
        if previous:
            controls = self._context_menu_row_controls.get(str(previous)) or {}
            button = controls.get("button")
            spec = controls.get("spec") or {}
            if button and dpg.does_item_exist(button):
                dpg.bind_item_theme(
                    button,
                    self._context_menu_button_theme
                    if bool(spec.get("enabled", True))
                    else self._context_menu_disabled_button_theme,
                )
        self._context_keyboard_id = None if item_id is None else str(item_id)
        if self._context_keyboard_id:
            controls = self._context_menu_row_controls.get(
                self._context_keyboard_id) or {}
            button = controls.get("button")
            if button and dpg.does_item_exist(button):
                dpg.bind_item_theme(button, self._context_menu_keyboard_button_theme)
                try:
                    dpg.focus_item(button)
                except Exception:
                    pass

    def _on_context_menu_key(self, sender=None, app_data=None, user_data=None):
        if not self._context_menu_is_visible():
            return
        command = str(user_data or "")
        candidates = self._context_keyboard_candidates()
        if command in ("up", "down"):
            if not candidates:
                return
            try:
                index = candidates.index(str(self._context_keyboard_id))
            except ValueError:
                index = -1 if command == "down" else 0
            index = (index + (1 if command == "down" else -1)) % len(candidates)
            self._set_context_keyboard_id(candidates[index])
            return

        current = str(self._context_keyboard_id or "")
        if not current:
            if candidates:
                self._set_context_keyboard_id(candidates[0])
            return
        spec = self._context_menu_spec_by_id(current)
        if not self._context_keyboard_eligible(spec):
            return

        if command == "right":
            if spec.get("children"):
                self._show_context_submenu(user_data=current)
                child_candidates = self._context_keyboard_candidates()
                self._set_context_keyboard_id(
                    child_candidates[0] if child_candidates else None)
            return
        if command == "left":
            parent = self._active_context_submenu_group
            if parent:
                self._hide_context_submenus()
                self._set_context_keyboard_id(parent)
            return
        if command == "activate":
            if spec.get("children"):
                self._show_context_submenu(user_data=current)
                child_candidates = self._context_keyboard_candidates()
                self._set_context_keyboard_id(
                    child_candidates[0] if child_candidates else None)
                return
            action = spec.get("action")
            if action is not None:
                self._on_item_menu_action(None, None, action)

    def _context_menu_is_visible(self):
        if self.itemmenu_tag and dpg.does_item_exist(self.itemmenu_tag):
            try:
                return bool(dpg.is_item_shown(self.itemmenu_tag))
            except Exception:
                pass
        return False

    def _mouse_inside_context_menus(self):
        try:
            point = tuple(map(float, dpg.get_mouse_pos(local=False)))
        except Exception:
            point = None
        if self._point_in_visible_window(self.itemmenu_tag, point):
            return True
        return any(self._point_in_visible_window(tag, point)
                   for tag in self._context_submenu_tags.values())

    def _hide_context_submenus(self, except_tag=None):
        kept_group = None
        for group_id, tag in self._context_submenu_tags.items():
            if tag != except_tag and dpg.does_item_exist(tag):
                dpg.configure_item(tag, show=False)
            elif tag == except_tag:
                kept_group = group_id
        self._active_context_submenu_group = kept_group

    def _hide_context_menus(self):
        self._set_context_keyboard_id(None)
        self._hide_context_submenus()
        if dpg.does_item_exist(self.itemmenu_tag):
            dpg.configure_item(self.itemmenu_tag, show=False)

    def _show_context_submenu(self, sender=None, app_data=None, user_data=None):
        group_id = str(user_data or "")
        submenu_tag = self._context_submenu_tags.get(group_id)
        if not submenu_tag or not dpg.does_item_exist(submenu_tag):
            return
        self._hide_context_submenus(except_tag=submenu_tag)
        self._active_context_submenu_group = group_id
        # The parent menu is a normal borderless window, not a Dear PyGui
        # popup. Therefore opening a fly-out never hides the main menu.
        if dpg.does_item_exist(self.itemmenu_tag) and not dpg.is_item_shown(self.itemmenu_tag):
            dpg.configure_item(self.itemmenu_tag, show=True)
        try:
            # The callback may come from either the icon button or the text
            # button. Always use the registered parent-row text button for the
            # vertical anchor, and the main menu's right edge for the fly-out
            # horizontal position. This keeps placement identical regardless
            # of which part of the row was clicked.
            anchor = self._context_menu_group_tags.get(group_id, sender)

            # Window rect_min/rect_max are not reliable for a freshly shown
            # borderless DPG window: depending on the frame they can describe
            # the content region, or retain the previous hidden geometry.  Use
            # the actual window position plus its configured width instead.
            menu_pos = dpg.get_item_pos(self.itemmenu_tag)
            menu_cfg = dpg.get_item_configuration(self.itemmenu_tag) or {}
            menu_w = float(menu_cfg.get("width") or 266.0)
            menu_left = float(menu_pos[0])
            menu_top = float(menu_pos[1])
            menu_right = menu_left + menu_w

            # Align the child panel with the hovered parent row.  Clamp the row
            # coordinate to the main menu bounds in case DPG has not refreshed
            # the row rectangle yet on the first visible frame.
            row_min = dpg.get_item_rect_min(anchor)
            row_y = float(row_min[1])
            if row_y < menu_top - 2.0 or row_y > menu_top + 640.0:
                row_y = menu_top

            submenu_w, submenu_h = self._context_window_size(submenu_tag, 244.0)
            x = menu_right - 1.0
            y = row_y - 6.0
            viewport_w = float(dpg.get_viewport_client_width())

            # Explorer opens to the left only when there is not enough room on
            # the right. Keep a one-pixel overlap so no visual gap appears.
            if x + submenu_w + 2.0 > viewport_w:
                x = menu_left - submenu_w + 1.0
            x, y = self._clamp_context_position(
                submenu_tag, x, y, submenu_w
            )
            dpg.set_item_pos(submenu_tag, [x, y])
            dpg.configure_item(submenu_tag, show=True)
        except Exception:
            dpg.configure_item(submenu_tag, show=True)

    def _update_context_submenu_hover(self):
        """Show Explorer fly-outs while a parent group row is hovered.

        The fly-out remains visible while the pointer travels into that fly-out,
        so users can select its actions. It closes as soon as the pointer leaves
        both the parent group row and the child panel.
        """
        if not self._context_menu_is_visible():
            return False
        try:
            point = tuple(map(float, dpg.get_mouse_pos(local=False)))
        except Exception:
            point = None

        hovered_group = None
        for group_id, row_tag in self._context_menu_group_rows.items():
            if self._point_in_visible_window(row_tag, point):
                hovered_group = group_id
                break

        if hovered_group is not None:
            submenu_tag = self._context_submenu_tags.get(hovered_group)
            if submenu_tag and (
                self._active_context_submenu_group != hovered_group
                or not dpg.is_item_shown(submenu_tag)
            ):
                self._show_context_submenu(
                    sender=self._context_menu_group_tags.get(hovered_group),
                    user_data=hovered_group,
                )
            return True

        active_group = self._active_context_submenu_group
        active_tag = self._context_submenu_tags.get(active_group) if active_group else None
        if active_tag and self._point_in_visible_window(active_tag, point):
            return True

        if active_group is not None:
            self._hide_context_submenus()
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
            self._hide_context_menus()
            return
        targets = list(self.get_selected() or [self.items[context_index]]) if has_context_item else []
        self._hide_context_menus()
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
