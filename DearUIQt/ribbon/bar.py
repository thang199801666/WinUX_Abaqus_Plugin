"""Reusable Autodesk/Office-style ribbon surface for Dear ImGui applications.

The public model intentionally mirrors desktop ribbon terminology::

    RibbonBar
      -> Application menu / Quick Access Toolbar
      -> RibbonTab
          -> RibbonGroup / panel
              -> large button
              -> auto-stacked small buttons
              -> menu button / split button

Feature dialogs only work with stable string keys.  Dear PyGui item ownership,
layout, popup menus, checked state, minimize/restore state and themes stay inside
this module.
"""
from __future__ import annotations

from typing import Callable, Iterable, TYPE_CHECKING
from ..contracts import RibbonResources
from ..gui.palette import QtFusionPalette
from ..widgets.widget import QWidget

if TYPE_CHECKING:
    from ..widgets.menu import QMenu


from .themes import RibbonThemeFactory
from .state import RibbonStateMixin
from .internals import RibbonInternalsMixin


class RibbonBar(RibbonStateMixin, RibbonInternalsMixin, QWidget):
    """Create and manage an Inventor/Office-like ribbon bar.

    Buttons are key-addressable so callers can enable, check, relabel or hide a
    command later without retaining Dear PyGui implementation details.
    """

    QUICK_ACCESS_HEIGHT = 25
    TAB_HEIGHT = 30
    BODY_HEIGHT = 124
    GROUP_FOOTER_HEIGHT = 20
    GROUP_GAP = 2
    COMMAND_GAP = 2
    GROUP_HORIZONTAL_PADDING = 3
    CONTROLS_HORIZONTAL_PADDING = 2
    LARGE_BUTTON_WIDTH = 96
    LARGE_BUTTON_HEIGHT = 82
    LARGE_ICON_SIZE = 40
    LARGE_LABEL_HEIGHT = 28
    TILE_FONT_SIZE = 9

    DENSITY_PRESETS = {
        "normal": {},
        "compact": {
            "TAB_HEIGHT": 28,
            "BODY_HEIGHT": 92,
            "GROUP_FOOTER_HEIGHT": 20,
            "LARGE_BUTTON_WIDTH": 66,
            "LARGE_BUTTON_HEIGHT": 54,
            "LARGE_ICON_SIZE": 24,
            "LARGE_LABEL_HEIGHT": 18,
        },
    }
    TILE_LINE_HEIGHT = 11
    TILE_TEXT_MARGIN = 6
    SMALL_BUTTON_WIDTH = 98
    SMALL_BUTTON_HEIGHT = 20
    SMALL_ROWS = 3
    SPLIT_ARROW_WIDTH = 22

    def __init__(
        self,
        parent,
        *,
        height: int | None = None,
        quick_access: bool = True,
        density: str = "normal",
        after=None,
        backend=None,
        texture_loader=None,
        icon_path_resolver=None,
        resources: RibbonResources | None = None,
    ):
        if backend is None:
            from ..backends import get_backend
            backend = get_backend()
        self.backend = backend
        self.after = after
        resources = (resources or RibbonResources()).merged(
            texture_loader=texture_loader,
            icon_path_resolver=icon_path_resolver,
        )
        self.resources = resources
        self.texture_loader = resources.texture_loader
        self.icon_path_resolver = resources.icon_path_resolver
        density = str(density or "normal").strip().lower()
        if density not in self.DENSITY_PRESETS:
            raise ValueError("Ribbon density must be 'normal' or 'compact'.")
        self.density = density
        for name, value in self.DENSITY_PRESETS[density].items():
            setattr(self, name, value)
        self._show_quick_access = bool(quick_access)
        self._quick_height = self.QUICK_ACCESS_HEIGHT if self._show_quick_access else 0
        minimum = self._quick_height + self.TAB_HEIGHT + self.BODY_HEIGHT + 6
        self._expanded_height = max(minimum, int(height or minimum))
        self.height = self._expanded_height
        self._minimized = False
        self._tabs: dict[str, dict] = {}
        self._groups: dict[tuple[str, str], dict] = {}
        self._buttons: dict[str, dict] = {}
        self._menus: list[QMenu] = []
        self._active_tab: str | None = None
        self._themes: dict[tuple, object] = {}
        self._theme_factory = RibbonThemeFactory(self)
        self._application_button = None

        tag = backend.add_child_window(
            parent=parent,
            width=-1,
            height=self.height,
            border=False,
            no_scrollbar=True,
            no_scroll_with_mouse=True,
        )
        super().__init__(tag, parent=parent, after=after, backend=backend)
        backend.bind_item_theme(self.tag, self._surface_theme("root"))

        if self._show_quick_access:
            self.quick_access = backend.add_child_window(
                parent=self.tag,
                width=-1,
                height=self.QUICK_ACCESS_HEIGHT,
                border=False,
                no_scrollbar=True,
                no_scroll_with_mouse=True,
            )
            backend.bind_item_theme(self.quick_access, self._surface_theme("quick"))
            self.quick_row = backend.add_group(
                parent=self.quick_access, horizontal=True, horizontal_spacing=2)
        else:
            self.quick_access = None
            self.quick_row = None

        self.tab_strip = backend.add_child_window(
            parent=self.tag,
            width=-1,
            height=self.TAB_HEIGHT,
            border=False,
            no_scrollbar=True,
            no_scroll_with_mouse=True,
        )
        backend.bind_item_theme(self.tab_strip, self._surface_theme("tabs"))
        self.tab_row = backend.add_group(
            parent=self.tab_strip, horizontal=True, horizontal_spacing=0)

        self.body = backend.add_child_window(
            parent=self.tag,
            width=-1,
            height=self.BODY_HEIGHT,
            border=True,
            no_scrollbar=True,
            no_scroll_with_mouse=True,
        )
        backend.bind_item_theme(self.body, self._surface_theme("body"))

    # ------------------------------------------------------ application / QAT
    def add_application_menu(
        self,
        key: str,
        label: str,
        entries: Iterable,
        *,
        width: int = 38,
        tooltip: str | None = None,
    ):
        """Add the application/file menu button at the left of the QAT."""
        if self.quick_row is None:
            raise RuntimeError("Quick Access Toolbar is disabled for this ribbon.")
        if self._application_button is not None:
            raise ValueError("Ribbon application menu already exists.")
        key = self._key(key, "button")
        if key in self._buttons:
            raise ValueError("Ribbon button {!r} already exists.".format(key))
        menu = self._create_menu(key, entries, min_width=210)
        record = {
            "key": key,
            "label": str(label),
            "callback": None,
            "checkable": False,
            "checked": False,
            "enabled": True,
            "scope": "application",
            "icon": None,
            "size": "quick",
            "menu": menu,
        }
        tag = self.backend.add_button(
            label=str(label),
            parent=self.quick_row,
            width=max(30, int(width)),
            height=self.QUICK_ACCESS_HEIGHT - 4,
            callback=lambda *_args, button_key=key: self._popup_menu(button_key, menu),
        )
        record.update({"tag": tag, "items": [tag]})
        self._buttons[key] = record
        self._application_button = tag
        self.backend.bind_item_theme(tag, self._application_theme())
        self._add_tooltip(tag, tooltip)
        return tag

    def add_quick_button(
        self,
        key: str,
        label: str,
        callback: Callable | None = None,
        *,
        width: int = 28,
        image: str | None = None,
        enabled: bool = True,
        checkable: bool = False,
        checked: bool = False,
        tooltip: str | None = None,
    ):
        """Add a compact Quick Access Toolbar command."""
        if self.quick_row is None:
            raise RuntimeError("Quick Access Toolbar is disabled for this ribbon.")
        key = self._key(key, "button")
        if key in self._buttons:
            raise ValueError("Ribbon button {!r} already exists.".format(key))
        record = {
            "key": key,
            "label": str(label),
            "callback": callback,
            "checkable": bool(checkable),
            "checked": bool(checked),
            "enabled": bool(enabled),
            "scope": "quick",
            "icon": None,
            "image": image,
            "size": "quick",
        }
        texture = self._load_texture(image, 16) if image else None
        if texture is not None:
            tag = self.backend.add_image_button(
                texture, parent=self.quick_row, width=16, height=16,
                enabled=bool(enabled), background_color=(0, 0, 0, 0),
                callback=lambda *_args, button_key=key: self._button_clicked(button_key),
            )
            record["image_tag"] = tag
        else:
            tag = self.backend.add_button(
                label=str(label),
                parent=self.quick_row,
                width=max(20, int(width)),
                height=self.QUICK_ACCESS_HEIGHT - 4,
                enabled=bool(enabled),
                callback=lambda *_args, button_key=key: self._button_clicked(button_key),
            )
        record.update({"tag": tag, "items": [tag]})
        self._buttons[key] = record
        self._refresh_button_theme(key)
        self._add_tooltip(tag, tooltip)
        return tag

    def add_quick_separator(self):
        if self.quick_row is None:
            return None
        tag = self.backend.add_child_window(
            parent=self.quick_row, width=1, height=self.QUICK_ACCESS_HEIGHT - 8,
            border=False, no_scrollbar=True, no_scroll_with_mouse=True)
        self.backend.bind_item_theme(tag, self._surface_theme("separator"))
        return tag

    # ------------------------------------------------------------------ tabs
    def add_tab(self, key: str, label: str, *, activate: bool | None = None):
        key = self._key(key, "tab")
        if key in self._tabs:
            raise ValueError("Ribbon tab {!r} already exists.".format(key))

        header = self.backend.add_button(
            label=str(label),
            parent=self.tab_row,
            width=max(58, 16 + len(str(label)) * 7),
            height=self.TAB_HEIGHT - 3,
            callback=lambda *_args, tab_key=key: self.set_active_tab(tab_key),
        )
        page = self.backend.add_child_window(
            parent=self.body,
            show=False,
            width=-1,
            height=-1,
            border=False,
            no_scrollbar=True,
            no_scroll_with_mouse=True,
        )
        self.backend.bind_item_theme(page, self._surface_theme("page"))
        row = self.backend.add_group(
            parent=page, horizontal=True, horizontal_spacing=self.GROUP_GAP)
        self._tabs[key] = {
            "key": key,
            "label": str(label),
            "header": header,
            "page": page,
            "row": row,
            "enabled": True,
            "visible": True,
        }
        if activate is True or self._active_tab is None:
            self.set_active_tab(key)
        else:
            self._refresh_tab_theme(key)
        return page

    def set_active_tab(self, key: str) -> bool:
        key = str(key)
        tab = self._tabs.get(key)
        if tab is None or not tab.get("enabled", True) or not tab.get("visible", True):
            return False
        self._active_tab = key
        for tab_key, tab_record in self._tabs.items():
            active = tab_key == key
            self.backend.configure_item(tab_record["page"], show=active and not self._minimized)
            self._refresh_tab_theme(tab_key)
        return True

    def active_tab(self) -> str | None:
        return self._active_tab

    def set_tab_enabled(self, key: str, enabled: bool) -> bool:
        tab = self._tabs.get(str(key))
        if tab is None:
            return False
        tab["enabled"] = bool(enabled)
        self.backend.configure_item(tab["header"], enabled=bool(enabled))
        return True

    def set_tab_visible(self, key: str, visible: bool) -> bool:
        key = str(key)
        tab = self._tabs.get(key)
        if tab is None:
            return False
        tab["visible"] = bool(visible)
        self.backend.configure_item(tab["header"], show=bool(visible))
        self.backend.configure_item(
            tab["page"], show=bool(visible) and key == self._active_tab and not self._minimized)
        if not visible and self._active_tab == key:
            next_key = next((k for k, row in self._tabs.items() if row.get("visible") and row.get("enabled")), None)
            self._active_tab = None
            if next_key is not None:
                self.set_active_tab(next_key)
        return True

    # ---------------------------------------------------------------- groups
    def add_group(
        self,
        tab_key: str,
        key: str,
        label: str,
        *,
        width: int = 160,
        layout: str = "mixed",
        launcher: Callable | None = None,
        launcher_tooltip: str | None = None,
    ):
        """Add one ribbon panel/group.

        ``layout="large"`` is intended for sparse CAD ribbons: commands added
        with ``size="auto"`` become full-height large buttons. ``layout="small"``
        forces compact three-row commands, while ``mixed`` preserves explicit
        per-command sizing.
        """
        tab_key = str(tab_key)
        key = self._key(key, "group")
        tab = self._tabs.get(tab_key)
        if tab is None:
            raise KeyError("Unknown ribbon tab {!r}.".format(tab_key))
        identity = (tab_key, key)
        if identity in self._groups:
            raise ValueError("Ribbon group {!r} already exists in tab {!r}.".format(key, tab_key))

        layout = self._normalize_group_layout(layout)

        group_width = max(72, int(width))
        group = self.backend.add_child_window(
            parent=tab["row"],
            width=group_width,
            # Body + page padding must also fit around the entire group.
            height=self.BODY_HEIGHT - 10,
            border=False,
            no_scrollbar=True,
            no_scroll_with_mouse=True,
        )
        self.backend.bind_item_theme(group, self._surface_theme("group"))
        controls_height = max(
            self.LARGE_BUTTON_HEIGHT + 4,
            self.BODY_HEIGHT - self.GROUP_FOOTER_HEIGHT - 16,
        )
        controls = self.backend.add_child_window(
            parent=group,
            width=-1,
            height=controls_height,
            border=False,
            no_scrollbar=True,
            no_scroll_with_mouse=True,
        )
        self.backend.bind_item_theme(controls, self._surface_theme("controls"))
        row = self.backend.add_group(parent=controls, horizontal=True, horizontal_spacing=self.COMMAND_GAP)

        footer_row = self.backend.add_group(parent=group, horizontal=True, horizontal_spacing=2)
        caption_width = max(0, len(str(label)) * 7)
        left_pad = max(2, (group_width - caption_width - (18 if callable(launcher) else 0)) // 2)
        footer_spacer = self.backend.add_spacer(parent=footer_row, width=left_pad)
        footer = self.backend.add_text(str(label), parent=footer_row)
        try:
            self.backend.bind_item_theme(footer, self._text_theme(muted=True))
        except Exception:
            pass
        launcher_tag = None
        if callable(launcher):
            launcher_tag = self.backend.add_button(
                label="v",
                parent=footer_row,
                width=18,
                height=15,
                callback=lambda *_: launcher(),
            )
            self.backend.bind_item_theme(launcher_tag, self._button_theme(compact=True))
            self._add_tooltip(launcher_tag, launcher_tooltip)

        separator_height = self.BODY_HEIGHT - 12
        separator = self.backend.add_drawlist(
            parent=tab["row"], width=7, height=separator_height)
        self.backend.draw_line(
            (3, 8), (3, separator_height - 8), parent=separator,
            color=QtFusionPalette.BORDER_LIGHT, thickness=1.0)

        self._groups[identity] = {
            "tab": tab_key,
            "key": key,
            "label": str(label),
            "tag": group,
            "controls": controls,
            "row": row,
            "footer": footer,
            "footer_row": footer_row,
            "launcher": launcher_tag,
            "separator": separator,
            "width": group_width,
            "minimum_width": group_width,
            "slot_widths": {},
            "caption_width": caption_width,
            "footer_spacer": footer_spacer,
            "layout": layout,
            "small_columns": [],
            "enabled": True,
            "visible": True,
        }
        return group

    def set_group_layout(self, tab_key: str, group_key: str, layout: str) -> bool:
        """Set the preferred size for subsequently added ``size="auto"`` commands."""
        group = self._groups.get((str(tab_key), str(group_key)))
        if group is None:
            return False
        group["layout"] = self._normalize_group_layout(layout)
        return True

    def set_group_enabled(self, tab_key: str, group_key: str, enabled: bool) -> bool:
        group = self._groups.get((str(tab_key), str(group_key)))
        if group is None:
            return False
        group["enabled"] = bool(enabled)
        for record in self._buttons.values():
            if record.get("tab") == str(tab_key) and record.get("group") == str(group_key):
                self.set_button_enabled(record["key"], enabled)
        return True

    def set_group_visible(self, tab_key: str, group_key: str, visible: bool) -> bool:
        group = self._groups.get((str(tab_key), str(group_key)))
        if group is None:
            return False
        group["visible"] = bool(visible)
        self.backend.configure_item(group["tag"], show=bool(visible))
        if group.get("separator") is not None:
            self.backend.configure_item(group["separator"], show=bool(visible))
        return True

    def add_separator(self, tab_key: str, group_key: str, *, width: int = 5):
        group = self._groups.get((str(tab_key), str(group_key)))
        if group is None:
            raise KeyError("Unknown ribbon group {!r} in tab {!r}.".format(group_key, tab_key))
        width = max(2, int(width))
        tag = self.backend.add_spacer(parent=group["row"], width=width)
        self._reserve_group_width(group, tag, width)
        return tag

    # --------------------------------------------------------------- buttons
    def add_button(
        self,
        tab_key: str,
        group_key: str,
        key: str,
        label: str,
        callback: Callable | None = None,
        *,
        size: str = "auto",
        width: int | None = None,
        icon: str | None = None,
        image: str | None = None,
        checkable: bool = False,
        checked: bool = False,
        enabled: bool = True,
        tooltip: str | None = None,
    ):
        """Add a large or small command button.

        ``icon`` is a lightweight text/glyph fallback. ``image`` may name a
        bundled PNG resource; large commands render the real icon above the label.
        """
        record = self._new_button_record(
            tab_key, group_key, key, label, callback,
            checkable=checkable, checked=checked, enabled=enabled,
        )
        group = self._groups[(str(tab_key), str(group_key))]
        size = self._resolve_button_size(group, size)
        button_width = int(width or (self.LARGE_BUTTON_WIDTH if size == "large" else self.SMALL_BUTTON_WIDTH))
        parent = group["row"] if size == "large" else self._small_button_parent(group, button_width)
        button_height = self.LARGE_BUTTON_HEIGHT if size == "large" else self.SMALL_BUTTON_HEIGHT
        record.update({"size": size, "icon": icon, "image": image, "width": button_width})
        if size == "large" and image:
            tag, items, container = self._add_large_image_command(record, parent, button_width, enabled)
            record.update({"tag": tag, "items": items, "container": container, "tooltip": tooltip})
        else:
            tag = self.backend.add_button(
                label=self._display_label(record),
                parent=parent,
                width=button_width,
                height=button_height,
                enabled=bool(enabled),
                callback=lambda *_args, button_key=record["key"]: self._button_clicked(button_key),
            )
            record.update({"tag": tag, "items": [tag], "tooltip": tooltip})
        self._buttons[record["key"]] = record
        self._reserve_group_width(group, parent if size == "small" else record.get("container") or tag, button_width)
        self._refresh_button_theme(record["key"])
        self._add_tooltip(tag, tooltip)
        return tag

    def add_menu_button(
        self,
        tab_key: str,
        group_key: str,
        key: str,
        label: str,
        entries: Iterable,
        *,
        size: str = "auto",
        width: int | None = None,
        icon: str | None = None,
        image: str | None = None,
        enabled: bool = True,
        tooltip: str | None = None,
    ):
        """Add a command whose entire button opens a popup menu."""
        menu = self._create_menu(str(key), entries)
        tag = self.add_button(
            tab_key, group_key, key, label,
            callback=lambda: self._popup_menu(key, menu),
            size=size, width=width, icon=icon, image=image, enabled=enabled, tooltip=tooltip,
        )
        self._buttons[str(key)]["menu"] = menu
        self._buttons[str(key)]["menu_indicator"] = True
        self.backend.configure_item(tag, label=self._display_label(self._buttons[str(key)]))
        return tag

    def add_split_button(
        self,
        tab_key: str,
        group_key: str,
        key: str,
        label: str,
        callback: Callable | None,
        entries: Iterable,
        *,
        size: str = "auto",
        width: int | None = None,
        icon: str | None = None,
        image: str | None = None,
        enabled: bool = True,
        tooltip: str | None = None,
    ):
        """Add a true split command: main area executes, arrow opens a menu."""
        record = self._new_button_record(
            tab_key, group_key, key, label, callback,
            checkable=False, checked=False, enabled=enabled,
        )
        group = self._groups[(str(tab_key), str(group_key))]
        size = self._resolve_button_size(group, size)
        total_width = int(width or (self.LARGE_BUTTON_WIDTH if size == "large" else self.SMALL_BUTTON_WIDTH))
        parent = group["row"] if size == "large" else self._small_button_parent(group, total_width)
        menu = self._create_menu(str(key), entries)
        record.update({"size": size, "icon": icon, "image": image, "menu": menu, "split": True})

        if size == "large":
            container = self.backend.add_group(parent=parent, horizontal=False, horizontal_spacing=0)
            main = self.backend.add_button(
                label=self._display_label(record), parent=container,
                width=total_width, height=max(38, self.LARGE_BUTTON_HEIGHT - 18),
                enabled=bool(enabled),
                callback=lambda *_args, button_key=record["key"]: self._button_clicked(button_key),
            )
            arrow = self.backend.add_button(
                label="v", parent=container, width=total_width, height=17,
                enabled=bool(enabled),
                callback=lambda *_args, button_key=record["key"], popup=menu: self._popup_menu(button_key, popup, anchor=arrow),
            )
            items = [main, arrow]
        else:
            container = self.backend.add_group(parent=parent, horizontal=True, horizontal_spacing=0)
            main_width = max(24, total_width - self.SPLIT_ARROW_WIDTH)
            main = self.backend.add_button(
                label=self._display_label(record), parent=container,
                width=main_width, height=self.SMALL_BUTTON_HEIGHT,
                enabled=bool(enabled),
                callback=lambda *_args, button_key=record["key"]: self._button_clicked(button_key),
            )
            arrow = self.backend.add_button(
                label="v", parent=container, width=self.SPLIT_ARROW_WIDTH,
                height=self.SMALL_BUTTON_HEIGHT, enabled=bool(enabled),
                callback=lambda *_args, button_key=record["key"], popup=menu: self._popup_menu(button_key, popup, anchor=arrow),
            )
            items = [main, arrow]

        record.update({"tag": main, "items": items, "arrow": arrow, "container": container, "tooltip": tooltip})
        self._buttons[record["key"]] = record
        self._reserve_group_width(group, parent if size == "small" else container, total_width)
        self._refresh_button_theme(record["key"])
        self._add_tooltip(main, tooltip)
        return main
