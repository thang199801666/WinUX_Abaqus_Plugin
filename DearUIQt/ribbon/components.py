"""Object-oriented Ribbon composition over the existing DearUIQt RibbonBar.

The model deliberately owns no application resources and does not import WinUx.
Views are created by RibbonBar through the configured backend. Existing key-based
RibbonBar methods remain supported and interoperable with these objects.
"""
from __future__ import annotations

from typing import Callable, Iterable


class RibbonButton:
    """A ribbon command with a stable identifier and runtime state helpers."""

    def __init__(self, bar, key: str, tag):
        self.bar = bar
        self.key = str(key)
        self.tag = tag

    def set_enabled(self, enabled: bool) -> bool:
        return self.bar.set_button_enabled(self.key, enabled)

    def set_visible(self, visible: bool) -> bool:
        return self.bar.set_button_visible(self.key, visible)

    def set_checked(self, checked: bool) -> bool:
        return self.bar.set_button_checked(self.key, checked)

    def is_checked(self) -> bool:
        return self.bar.is_button_checked(self.key)

    def set_text(self, text: str) -> bool:
        return self.bar.set_button_label(self.key, text)

    def set_icon(self, icon: str | None) -> bool:
        return self.bar.set_button_icon(self.key, icon)

    def set_image(self, image: str | None) -> bool:
        return self.bar.set_button_image(self.key, image)


class RibbonMenuButton(RibbonButton):
    """Command that opens its associated popup menu."""


class RibbonSplitButton(RibbonButton):
    """Command with separate action and popup arrow targets."""


class RibbonGroup:
    """Visually separated ribbon group, with caption and command arrangement."""

    def __init__(self, tab: 'RibbonTab', key: str, tag):
        self.tab = tab
        self.bar = tab.bar
        self.key = str(key)
        self.tag = tag
        self._commands: dict[str, RibbonButton] = {}

    @property
    def commands(self) -> tuple[RibbonButton, ...]:
        return tuple(self._commands.values())

    def _register(self, key, tag, cls=RibbonButton):
        obj = cls(self.bar, key, tag)
        self._commands[obj.key] = obj
        return obj

    def add_button(self, key: str, text: str, callback: Callable | None = None,
                   *, size: str = 'auto', width: int | None = None,
                   icon: str | None = None, image: str | None = None,
                   checkable: bool = False, checked: bool = False,
                   enabled: bool = True, tooltip: str | None = None) -> RibbonButton:
        tag = self.bar.add_button(self.tab.key, self.key, key, text, callback,
                                  size=size, width=width, icon=icon, image=image,
                                  checkable=checkable, checked=checked,
                                  enabled=enabled, tooltip=tooltip)
        return self._register(key, tag)

    def add_menu_button(self, key: str, text: str, entries: Iterable, *,
                        size: str = 'auto', width: int | None = None,
                        icon: str | None = None, image: str | None = None,
                        enabled: bool = True, tooltip: str | None = None) -> RibbonMenuButton:
        tag = self.bar.add_menu_button(self.tab.key, self.key, key, text, entries,
                                       size=size, width=width, icon=icon, image=image,
                                       enabled=enabled, tooltip=tooltip)
        return self._register(key, tag, RibbonMenuButton)

    def add_split_button(self, key: str, text: str, callback: Callable | None,
                         entries: Iterable, *, size: str = 'auto',
                         width: int | None = None, icon: str | None = None,
                         image: str | None = None, enabled: bool = True,
                         tooltip: str | None = None) -> RibbonSplitButton:
        tag = self.bar.add_split_button(self.tab.key, self.key, key, text, callback,
                                        entries, size=size, width=width, icon=icon,
                                        image=image, enabled=enabled, tooltip=tooltip)
        return self._register(key, tag, RibbonSplitButton)

    def add_separator(self, *, width: int = 5):
        return self.bar.add_separator(self.tab.key, self.key, width=width)

    def set_layout(self, layout: str) -> bool:
        return self.bar.set_group_layout(self.tab.key, self.key, layout)

    def set_enabled(self, enabled: bool) -> bool:
        return self.bar.set_group_enabled(self.tab.key, self.key, enabled)

    def set_visible(self, visible: bool) -> bool:
        return self.bar.set_group_visible(self.tab.key, self.key, visible)

    @property
    def display_state(self) -> str | None:
        """Current adaptive visual state: large, medium, small or collapsed."""
        return self.bar.group_display_state(self.tab.key, self.key)


class RibbonContextGroup:
    """Content-agnostic group of tabs shown only for a contextual state.

    Context groups carry an optional accent and visibility state. They do not
    define application semantics; callers decide when the context becomes active.
    """

    def __init__(self, bar, key: str):
        self.bar = bar
        self.key = str(key)

    @property
    def label(self) -> str:
        record = self.bar._context_groups.get(self.key) or {}
        return str(record.get("label", ""))

    @property
    def accent(self):
        record = self.bar._context_groups.get(self.key) or {}
        return record.get("accent")

    @property
    def visible(self) -> bool:
        record = self.bar._context_groups.get(self.key) or {}
        return bool(record.get("visible"))

    @property
    def tabs(self) -> tuple[str, ...]:
        record = self.bar._context_groups.get(self.key) or {}
        return tuple(record.get("tabs", ()))

    def create_tab(self, key: str, text: str, *, activate: bool | None = None,
                   accent=None, badge=None):
        return self.bar.create_tab(
            key, text, activate=activate, accent=accent, context=self.key, badge=badge)

    def attach_tab(self, tab) -> bool:
        key = getattr(tab, "key", tab)
        return self.bar.set_tab_context(key, self.key)

    def detach_tab(self, tab) -> bool:
        key = getattr(tab, "key", tab)
        record = self.bar._tabs.get(str(key))
        if record is None or record.get("context_group") != self.key:
            return False
        return self.bar.set_tab_context(key, None)

    def set_visible(self, visible: bool) -> bool:
        return self.bar.set_context_group_visible(self.key, visible)

    def set_accent(self, color=None) -> bool:
        return self.bar.set_context_group_accent(self.key, color)


class RibbonTab:
    """One tab in the upper strip; contains a collection of RibbonGroups."""

    def __init__(self, bar, key: str, tag):
        self.bar = bar
        self.key = str(key)
        self.tag = tag
        self._groups: dict[str, RibbonGroup] = {}

    @property
    def groups(self) -> tuple[RibbonGroup, ...]:
        return tuple(self._groups.values())

    def add_group(self, key: str, text: str, *, width: int = 160,
                  layout: str = 'mixed', launcher: Callable | None = None,
                  launcher_tooltip: str | None = None) -> RibbonGroup:
        tag = self.bar.add_group(self.key, key, text, width=width, layout=layout,
                                 launcher=launcher, launcher_tooltip=launcher_tooltip)
        group = RibbonGroup(self, key, tag)
        self._groups[group.key] = group
        return group

    def activate(self) -> bool:
        return self.bar.set_active_tab(self.key)

    def set_enabled(self, enabled: bool) -> bool:
        return self.bar.set_tab_enabled(self.key, enabled)

    def set_visible(self, visible: bool) -> bool:
        return self.bar.set_tab_visible(self.key, visible)

    def set_accent(self, color=None) -> bool:
        """Set an optional RGB/RGBA accent for this tab's retained indicator."""
        return self.bar.set_tab_accent(self.key, color)

    def set_badge(self, value=None, *, color=None, text_color=None) -> bool:
        """Set or clear a retained status/count badge on the tab header."""
        return self.bar.set_tab_badge(self.key, value, color=color, text_color=text_color)

    def set_context(self, context=None) -> bool:
        """Attach this tab to a contextual group, or detach it with ``None``."""
        key = getattr(context, "key", context)
        return self.bar.set_tab_context(self.key, key)

    @property
    def accent(self):
        return self.bar.tab_accent(self.key)

    @property
    def badge(self):
        return self.bar.tab_badge(self.key)

    @property
    def context_key(self):
        return self.bar.tab_context(self.key)
