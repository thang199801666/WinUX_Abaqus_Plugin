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
from .layout import RibbonLayoutEngine
from .display_templates import get_ribbon_display_template
from .visual_styles import get_ribbon_visual_style
from .renderers import RibbonTabRenderer
from .appearance_templates import (
    get_ribbon_appearance_template,
    normalize_tab_render_style,
    normalize_group_render_style,
    normalize_button_render_style,
)


class RibbonBar(RibbonStateMixin, RibbonInternalsMixin, QWidget):
    """Create and manage an Inventor/Office-like ribbon bar.

    Buttons are key-addressable so callers can enable, check, relabel or hide a
    command later without retaining Dear PyGui implementation details.
    """

    QUICK_ACCESS_HEIGHT = 25
    TAB_HEIGHT = 30
    TAB_INDICATOR_HEIGHT = 2
    BODY_HEIGHT = 124
    GROUP_FOOTER_HEIGHT = 20
    GROUP_GAP = 2
    COMMAND_GAP = 2
    GROUP_HORIZONTAL_PADDING = 3
    CONTROLS_HORIZONTAL_PADDING = 2
    GROUP_MIN_WIDTH = 72
    GROUP_SEPARATOR_WIDTH = 7
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
    TAB_MIN_WIDTH = 58
    TAB_CHAR_WIDTH = 7
    TAB_PADDING_X = 8
    TAB_PADDING_Y = 3
    GROUP_CAPTION_CHAR_WIDTH = 7
    BUTTON_PADDING_X = 5
    BUTTON_PADDING_Y = 3
    COMPACT_BUTTON_PADDING_X = 3
    COMPACT_BUTTON_PADDING_Y = 1
    BUTTON_ROUNDING = 3
    SURFACE_SPACING_X = 2
    SURFACE_SPACING_Y = 1
    OVERFLOW_WIDTH = 65
    RESPONSIVE_PADDING = 10
    SMALL_BUTTON_WIDTH = 98
    SMALL_BUTTON_HEIGHT = 20
    SMALL_ROWS = 3
    SPLIT_ARROW_WIDTH = 22

    def __init__(
        self,
        parent,
        *,
        height: int | None = None,
        quick_access: bool | None = None,
        density: str | None = None,
        display_template=None,
        visual_style=None,
        appearance_template=None,
        tab_style=None,
        group_style=None,
        button_style=None,
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
        # ``density`` remains a compatibility alias.  New code should select a
        # visual preset through ``display_template``.  If density is explicitly
        # supplied and no non-default display template is requested, map it to
        # the equivalent visual preset.
        density_key = str(density or "normal").strip().lower()
        if density_key not in self.DENSITY_PRESETS:
            raise ValueError("Ribbon density must be 'normal' or 'compact'.")
        appearance = None
        if appearance_template is not None:
            appearance = get_ribbon_appearance_template(appearance_template)
        self.appearance_template = appearance
        self.appearance_template_key = appearance.key if appearance is not None else None

        legacy_density_mode = display_template is None and appearance is None
        requested_template = display_template
        if requested_template is None and appearance is not None:
            requested_template = appearance.display_template
        if legacy_density_mode:
            requested_template = "compact" if density_key == "compact" else "classic"
        spec = get_ribbon_display_template(requested_template or "classic")
        self.display_template = spec
        self.display_template_key = spec.key
        style_request = visual_style
        if style_request is None and appearance is not None:
            style_request = appearance.visual_style
        if style_request is None:
            # Legacy density-only callers retain the historical ribbon chrome.
            style_request = "classic" if legacy_density_mode else spec.visual_style
        style = get_ribbon_visual_style(style_request)
        self.visual_style = style
        self.visual_style_key = style.key
        self.tab_render_style = normalize_tab_render_style(
            tab_style or (appearance.tab_style if appearance is not None else "filled")
        )
        self.group_render_style = normalize_group_render_style(
            group_style or (appearance.group_style if appearance is not None else "separator")
        )
        self.button_render_style = normalize_button_render_style(
            button_style or (appearance.button_style if appearance is not None else "flat")
        )
        self._adaptive_policy = spec.adaptive_policy
        self.density = density_key
        for name, value in spec.metrics().items():
            setattr(self, name, value)
        self._show_group_labels = bool(spec.show_group_labels)
        self._show_group_separators = bool(spec.show_group_separators)
        if quick_access is None:
            # Preserve the historical RibbonBar default when callers still use
            # density= only. Explicit display templates may provide their own
            # recommended QAT visibility.
            quick_access = True if legacy_density_mode else spec.quick_access_default
        self._show_quick_access = bool(quick_access)
        self._quick_height = self.QUICK_ACCESS_HEIGHT if self._show_quick_access else 0
        minimum = self._quick_height + self.TAB_HEIGHT + self.BODY_HEIGHT + 6
        self._expanded_height = max(minimum, int(height or minimum))
        self.height = self._expanded_height
        self._minimized = False
        self._tabs: dict[str, dict] = {}
        self._context_groups: dict[str, dict] = {}
        self._groups: dict[tuple[str, str], dict] = {}
        self._buttons: dict[str, dict] = {}
        self._menus: list[QMenu] = []
        self._active_tab: str | None = None
        self._themes: dict[tuple, object] = {}
        self._theme_factory = RibbonThemeFactory(self)
        self._tab_renderer = RibbonTabRenderer(self)
        self._application_button = None
        self._responsive = False
        self._adaptive_override = None
        self._adaptive_responsive = bool(self._adaptive_policy.enabled)
        self._ribbon_available_width = None
        self._layout_engine = RibbonLayoutEngine(
            separator_width=self.GROUP_SEPARATOR_WIDTH, gap=self.GROUP_GAP,
            overflow_width=self.OVERFLOW_WIDTH, padding=self.RESPONSIVE_PADDING)
        self._overflow_buttons = {}
        self._overflow_menus = {}
        self._quick_separators = []


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

    # ----------------------------------------------------- composition API
    def create_tab(
        self, key: str, label: str, *, activate: bool | None = None, accent=None,
        context=None, badge=None, badge_color=None, badge_text_color=None,
    ):
        """Create and return a :class:`RibbonTab` object.

        ``context`` optionally attaches the tab to a generic contextual group;
        ``badge`` adds retained status/count decoration.  Neither option defines
        application semantics. Existing ``add_tab`` / ``add_group`` APIs remain
        fully supported.
        """
        from .components import RibbonTab
        key = self._key(key, "tab")
        page = self.add_tab(
            key, label, activate=activate, accent=accent, context=context, badge=badge,
            badge_color=badge_color, badge_text_color=badge_text_color)
        return RibbonTab(self, key, page)

    def create_context_group(self, key: str, label: str, *, accent=None, visible: bool = False):
        """Create a content-agnostic contextual tab group.

        Context groups only coordinate tab visibility and a retained accent band.
        The host application decides when a context becomes visible.
        """
        from .components import RibbonContextGroup
        key = self.add_context_group(key, label, accent=accent, visible=visible)
        return RibbonContextGroup(self, key)

    def apply_template(self, template, **bindings):
        """Populate this ribbon from an optional composition RibbonTemplate."""
        from .templates import apply_ribbon_template
        return apply_ribbon_template(self, template, **bindings)

    @classmethod
    def from_display_template(cls, parent, template="classic", **kwargs):
        """Construct an empty ribbon using one of the generic visual presets."""
        return cls(parent, display_template=template, **kwargs)

    @staticmethod
    def display_template_names():
        """Return the registered visual preset keys without defining app content."""
        from .display_templates import ribbon_display_template_names
        return ribbon_display_template_names()

    @staticmethod
    def visual_style_names():
        """Return registered generic ribbon chrome/style keys."""
        from .visual_styles import ribbon_visual_style_names
        return ribbon_visual_style_names()

    @staticmethod
    def appearance_template_names():
        """Return complete, content-independent appearance template keys."""
        from .appearance_templates import ribbon_appearance_template_names
        return ribbon_appearance_template_names()

    @classmethod
    def from_appearance_template(cls, parent, template="modern-clean", **kwargs):
        """Construct an empty ribbon from one ready-made appearance template."""
        return cls(parent, appearance_template=template, **kwargs)

    def _rebind_visual_themes(self):
        """Rebind chrome to existing widgets without recreating ribbon content."""
        self._themes = {}
        self._theme_factory = RibbonThemeFactory(self)
        self.backend.bind_item_theme(self.tag, self._surface_theme("root"))
        if self.quick_access is not None:
            self.backend.bind_item_theme(self.quick_access, self._surface_theme("quick"))
        for tag in self._quick_separators:
            self.backend.bind_item_theme(tag, self._surface_theme("separator"))
        self.backend.bind_item_theme(self.tab_strip, self._surface_theme("tabs"))
        self.backend.bind_item_theme(self.body, self._surface_theme("body"))
        for tab_key, tab in self._tabs.items():
            self.backend.bind_item_theme(tab["page"], self._surface_theme("page"))
            self._refresh_tab_theme(tab_key)
        for group in self._groups.values():
            self.backend.bind_item_theme(group["tag"], self._surface_theme("group"))
            self.backend.bind_item_theme(group["controls"], self._surface_theme("controls"))
            try:
                self.backend.bind_item_theme(group["footer"], self._text_theme(muted=True))
            except Exception:
                pass
            if group.get("launcher") is not None:
                self.backend.bind_item_theme(group["launcher"], self._button_theme(compact=True))
            line = group.get("separator_line")
            if line is not None:
                try:
                    self.backend.configure_item(
                        line, color=self.visual_style.separator,
                        show=self._show_group_separators and self.group_render_style == "separator",
                    )
                except Exception:
                    pass
            separator = group.get("separator")
            if separator is not None:
                try:
                    self.backend.configure_item(
                        separator,
                        show=bool(group.get("visible", True))
                        and self._show_group_separators
                        and self.group_render_style == "separator",
                    )
                except Exception:
                    pass
        for key in tuple(self._buttons):
            self._refresh_button_theme(key)
        for button in self._overflow_buttons.values():
            self.backend.bind_item_theme(button, self._button_theme(compact=True))

    def set_visual_style(self, style):
        """Apply ribbon colors/chrome at runtime without rebuilding content."""
        spec = get_ribbon_visual_style(style)
        self.visual_style = spec
        self.visual_style_key = spec.key
        # Large image tiles bake their label color into the texture; refresh only
        # those size-sensitive retained assets while preserving command widgets.
        for record in self._buttons.values():
            if record.get("large_tile"):
                self._apply_button_display_geometry(record)
        self._rebind_visual_themes()
        return spec

    def set_render_styles(self, *, tab_style=None, group_style=None, button_style=None):
        """Change semantic tab/group/button rendering without recreating controls."""
        if tab_style is not None:
            self.tab_render_style = normalize_tab_render_style(tab_style)
        if group_style is not None:
            self.group_render_style = normalize_group_render_style(group_style)
        if button_style is not None:
            self.button_render_style = normalize_button_render_style(button_style)
        self._rebind_visual_themes()
        return {
            "tab_style": self.tab_render_style,
            "group_style": self.group_render_style,
            "button_style": self.button_render_style,
        }

    def appearance_state(self):
        """Return the six content-independent runtime appearance axes."""
        return {
            "appearance_template": self.appearance_template_key,
            "display_template": self.display_template_key,
            "visual_style": self.visual_style_key,
            "tab_style": self.tab_render_style,
            "group_style": self.group_render_style,
            "button_style": self.button_render_style,
        }

    def _apply_runtime_display_geometry(self, old_minimum: int | None = None):
        """Reflow retained Ribbon widgets for the current display metrics.

        No tab/group/command is destroyed or recreated.  This method only
        reconfigures geometry and regenerates size-sensitive tile textures.
        """
        self._quick_height = self.QUICK_ACCESS_HEIGHT if self.quick_access is not None else 0
        minimum = self._quick_height + self.TAB_HEIGHT + self.BODY_HEIGHT + 6
        previous_minimum = int(old_minimum if old_minimum is not None else minimum)
        extra_height = max(0, int(self._expanded_height) - previous_minimum)
        self._expanded_height = minimum + extra_height
        self.height = self._quick_height + self.TAB_HEIGHT + 6 if self._minimized else self._expanded_height

        self.backend.configure_item(self.tag, height=self.height)
        if self.quick_access is not None:
            self.backend.configure_item(self.quick_access, height=self.QUICK_ACCESS_HEIGHT)
        self.backend.configure_item(self.tab_strip, height=self.TAB_HEIGHT)
        self.backend.configure_item(self.body, height=self.BODY_HEIGHT)

        self._layout_engine = RibbonLayoutEngine(
            separator_width=self.GROUP_SEPARATOR_WIDTH, gap=self.GROUP_GAP,
            overflow_width=self.OVERFLOW_WIDTH, padding=self.RESPONSIVE_PADDING)

        for tab_key, tab in self._tabs.items():
            self._tab_renderer.refresh(tab, active=tab_key == self._active_tab)
            try:
                self.backend.configure_item(tab["row"], horizontal_spacing=self.GROUP_GAP)
            except Exception:
                pass

        footer_height = self.GROUP_FOOTER_HEIGHT if self._show_group_labels else 0
        controls_height = max(
            self.LARGE_BUTTON_HEIGHT + 4,
            self.BODY_HEIGHT - footer_height - 16,
        )
        separator_height = max(1, self.BODY_HEIGHT - 12)
        for group in self._groups.values():
            group["caption_width"] = max(
                0, len(str(group.get("label", ""))) * self.GROUP_CAPTION_CHAR_WIDTH)
            self.backend.configure_item(
                group["tag"], height=max(1, self.BODY_HEIGHT - 10))
            self.backend.configure_item(group["controls"], height=controls_height)
            self.backend.configure_item(
                group["footer_row"], show=self._show_group_labels)
            try:
                self.backend.configure_item(group["row"], horizontal_spacing=self.COMMAND_GAP)
            except Exception:
                pass
            separator = group.get("separator")
            if separator is not None:
                self.backend.configure_item(
                    separator, width=self.GROUP_SEPARATOR_WIDTH, height=separator_height)
            line = group.get("separator_line")
            if line is not None:
                x = self.GROUP_SEPARATOR_WIDTH // 2
                self.backend.configure_item(
                    line, p1=(x, 8), p2=(x, max(8, separator_height - 8)),
                    color=self.visual_style.separator, thickness=1.0)

        for record in self._buttons.values():
            self._apply_button_display_geometry(record)

        for group in self._groups.values():
            natural = self._recalculate_group_natural_width(group)
            if not self._responsive:
                self.backend.configure_item(group["tag"], width=natural)
                group["width"] = natural
                group["adaptive_state"] = "large"
                self._update_group_footer_alignment(group, natural)

        for button in self._overflow_buttons.values():
            self.backend.configure_item(
                button, width=max(54, self.OVERFLOW_WIDTH - 4),
                height=self.SMALL_BUTTON_HEIGHT + 5)

    def set_display_template(self, template):
        """Switch generic Ribbon geometry at runtime without rebuilding content."""
        spec = get_ribbon_display_template(template)
        old_minimum = self._quick_height + self.TAB_HEIGHT + self.BODY_HEIGHT + 6
        self.display_template = spec
        self.display_template_key = spec.key
        self._adaptive_policy = spec.adaptive_policy
        for name, value in spec.metrics().items():
            setattr(self, name, value)
        self._show_group_labels = bool(spec.show_group_labels)
        self._show_group_separators = bool(spec.show_group_separators)
        if getattr(self, "_adaptive_override", None) is None:
            self._adaptive_responsive = bool(spec.adaptive_policy.enabled)
        self._apply_runtime_display_geometry(old_minimum)
        self._rebind_visual_themes()
        if self._responsive:
            self.relayout()
        return spec

    def set_appearance_template(
        self, template, *, display_template=None, visual_style=None,
        tab_style=None, group_style=None, button_style=None,
    ):
        """Apply a complete content-independent appearance preset at runtime.

        Explicit axis overrides are supported for settings/preview workflows.
        Existing tab/group/button identities, callbacks, checked state, badges
        and contextual state are retained.
        """
        appearance = get_ribbon_appearance_template(template)
        display = get_ribbon_display_template(display_template or appearance.display_template)
        style = get_ribbon_visual_style(visual_style or appearance.visual_style)
        tab_mode = normalize_tab_render_style(tab_style or appearance.tab_style)
        group_mode = normalize_group_render_style(group_style or appearance.group_style)
        button_mode = normalize_button_render_style(button_style or appearance.button_style)

        old_minimum = self._quick_height + self.TAB_HEIGHT + self.BODY_HEIGHT + 6
        self.appearance_template = appearance
        self.appearance_template_key = appearance.key
        self.display_template = display
        self.display_template_key = display.key
        self.visual_style = style
        self.visual_style_key = style.key
        self.tab_render_style = tab_mode
        self.group_render_style = group_mode
        self.button_render_style = button_mode
        self._adaptive_policy = display.adaptive_policy
        for name, value in display.metrics().items():
            setattr(self, name, value)
        self._show_group_labels = bool(display.show_group_labels)
        self._show_group_separators = bool(display.show_group_separators)
        if getattr(self, "_adaptive_override", None) is None:
            self._adaptive_responsive = bool(display.adaptive_policy.enabled)

        self._apply_runtime_display_geometry(old_minimum)
        self._rebind_visual_themes()
        if self._responsive:
            self.relayout()
        return self.appearance_state()

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
        self._quick_separators.append(tag)
        return tag

    # --------------------------------------------------------- contextual tabs
    def add_context_group(self, key: str, label: str, *, accent=None, visible: bool = False):
        from .renderers import _rgba
        key = self._key(key, "context group")
        if key in self._context_groups:
            raise ValueError("Ribbon context group {!r} already exists.".format(key))
        self._context_groups[key] = {
            "key": key, "label": str(label), "accent": _rgba(accent),
            "visible": bool(visible), "tabs": [],
        }
        return key

    def set_context_group_visible(self, key: str, visible: bool) -> bool:
        record = self._context_groups.get(str(key).strip())
        if record is None:
            return False
        visible = bool(visible)
        if record.get("visible") == visible:
            return True
        record["visible"] = visible
        for tab_key in tuple(record.get("tabs", ())):
            self._sync_tab_visibility(tab_key, allow_fallback=False)
        if self._active_tab is None:
            next_key = next((
                tab_key for tab_key, tab in self._tabs.items()
                if tab.get("visible") and tab.get("enabled", True)
            ), None)
            if next_key is not None:
                self.set_active_tab(next_key)
        return True

    def set_context_group_accent(self, key: str, accent=None) -> bool:
        from .renderers import _rgba
        record = self._context_groups.get(str(key).strip())
        if record is None:
            return False
        record["accent"] = _rgba(accent)
        for tab_key in tuple(record.get("tabs", ())):
            tab = self._tabs.get(tab_key)
            if tab is not None:
                self._tab_renderer.set_context_accent(tab, record["accent"])
        return True

    def context_group(self, key: str):
        record = self._context_groups.get(str(key).strip())
        if record is None:
            return None
        from .components import RibbonContextGroup
        return RibbonContextGroup(self, str(key).strip())

    def _tab_effective_visible(self, tab: dict) -> bool:
        if not bool(tab.get("user_visible", True)):
            return False
        context_key = tab.get("context_group")
        if not context_key:
            return True
        context = self._context_groups.get(context_key)
        return bool(context and context.get("visible"))

    def _sync_tab_visibility(self, key: str, *, allow_fallback: bool = True) -> bool:
        key = str(key)
        tab = self._tabs.get(key)
        if tab is None:
            return False
        visible = self._tab_effective_visible(tab)
        tab["visible"] = visible
        self.backend.configure_item(tab.get("host", tab["header"]), show=visible)
        self.backend.configure_item(tab["header"], show=visible)
        self.backend.configure_item(
            tab["page"], show=visible and key == self._active_tab and not self._minimized)
        self._refresh_tab_theme(key)
        if not visible and self._active_tab == key:
            self._active_tab = None
            if allow_fallback:
                next_key = next((
                    tab_key for tab_key, row in self._tabs.items()
                    if row.get("visible") and row.get("enabled", True)
                ), None)
                if next_key is not None:
                    self.set_active_tab(next_key)
        elif visible and self._active_tab is None and tab.get("enabled", True) and allow_fallback:
            self.set_active_tab(key)
        return True

    def set_tab_context(self, key: str, context=None) -> bool:
        key = str(key)
        tab = self._tabs.get(key)
        if tab is None:
            return False
        context_key = None if context in (None, "") else str(context).strip()
        if context_key is not None and context_key not in self._context_groups:
            raise KeyError("Unknown ribbon context group {!r}.".format(context_key))
        previous = tab.get("context_group")
        if previous == context_key:
            return True
        if previous in self._context_groups:
            tabs = self._context_groups[previous]["tabs"]
            if key in tabs:
                tabs.remove(key)
        tab["context_group"] = context_key
        if context_key is not None:
            target = self._context_groups[context_key]
            if key not in target["tabs"]:
                target["tabs"].append(key)
            context_accent = target.get("accent")
        else:
            context_accent = None
        self._tab_renderer.set_context_accent(tab, context_accent)
        self._sync_tab_visibility(key)
        return True

    def tab_context(self, key: str):
        tab = self._tabs.get(str(key))
        return None if tab is None else tab.get("context_group")

    # ------------------------------------------------------------------ tabs
    def add_tab(
        self, key: str, label: str, *, activate: bool | None = None, accent=None,
        context=None, badge=None, badge_color=None, badge_text_color=None,
    ):
        key = self._key(key, "tab")
        if key in self._tabs:
            raise ValueError("Ribbon tab {!r} already exists.".format(key))
        context_key = None if context in (None, "") else str(context).strip()
        if context_key is not None and context_key not in self._context_groups:
            raise KeyError("Unknown ribbon context group {!r}.".format(context_key))
        context_accent = (
            self._context_groups[context_key].get("accent") if context_key is not None else None)

        rendered = self._tab_renderer.create(
            key, label, accent=accent, context_accent=context_accent, badge=badge,
            badge_color=badge_color, badge_text_color=badge_text_color)
        header = rendered["header"]
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
            "host": rendered["host"],
            "header": header,
            "indicator": rendered["indicator"],
            "indicator_line": rendered["indicator_line"],
            "header_width": rendered["header_width"],
            "accent": rendered["accent"],
            "context_accent": rendered["context_accent"],
            "context_group": context_key,
            "badge": rendered["badge"],
            "badge_color": rendered["badge_color"],
            "badge_text_color": rendered["badge_text_color"],
            "indicator_anchor": rendered["indicator_anchor"],
            "decoration_anchor": rendered["decoration_anchor"],
            "decoration": rendered["decoration"],
            "context_line": rendered["context_line"],
            "badge_bg": rendered["badge_bg"],
            "badge_text_item": rendered["badge_text_item"],
            "page": page,
            "row": row,
            "enabled": True,
            "user_visible": True,
            "visible": True,
        }
        if context_key is not None:
            self._context_groups[context_key]["tabs"].append(key)
        self._tabs[key]["visible"] = self._tab_effective_visible(self._tabs[key])
        self._sync_tab_visibility(key)
        if (activate is True or self._active_tab is None) and self._tabs[key]["visible"]:
            self.set_active_tab(key)
        else:
            self._refresh_tab_theme(key)
        if self._responsive:
            self._ensure_overflow_button(key)
            self.relayout()
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
        tab["user_visible"] = bool(visible)
        return self._sync_tab_visibility(key)

    def set_tab_accent(self, key: str, accent=None) -> bool:
        """Set an optional per-tab accent used by retained tab indicators.

        ``accent=None`` restores the accent supplied by the active visual style.
        The tab widget and callback remain intact.
        """
        tab = self._tabs.get(str(key))
        if tab is None:
            return False
        self._tab_renderer.set_accent(tab, accent)
        return True

    def tab_accent(self, key: str):
        tab = self._tabs.get(str(key))
        return None if tab is None else tab.get("accent")

    def set_tab_badge(self, key: str, value=None, *, color=None, text_color=None) -> bool:
        """Set or clear a retained status/count badge on a tab."""
        tab = self._tabs.get(str(key))
        if tab is None:
            return False
        self._tab_renderer.set_badge(tab, value, color=color, text_color=text_color)
        return True

    def tab_badge(self, key: str):
        tab = self._tabs.get(str(key))
        return None if tab is None else tab.get("badge")

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

        group_width = max(self.GROUP_MIN_WIDTH, int(width))
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
        footer_height = self.GROUP_FOOTER_HEIGHT if self._show_group_labels else 0
        controls_height = max(
            self.LARGE_BUTTON_HEIGHT + 4,
            self.BODY_HEIGHT - footer_height - 16,
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

        footer_row = self.backend.add_group(parent=group, horizontal=True, horizontal_spacing=2, show=self._show_group_labels)
        caption_width = max(0, len(str(label)) * self.GROUP_CAPTION_CHAR_WIDTH)
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
            parent=tab["row"], width=self.GROUP_SEPARATOR_WIDTH, height=separator_height, show=self._show_group_separators and self.group_render_style == "separator")
        separator_line = self.backend.draw_line(
            (self.GROUP_SEPARATOR_WIDTH // 2, 8),
            (self.GROUP_SEPARATOR_WIDTH // 2, separator_height - 8), parent=separator,
            color=self.visual_style.separator, thickness=1.0)

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
            "separator_line": separator_line,
            "width": group_width,
            "natural_width": group_width,
            "minimum_width": group_width,
            "adaptive_state": "large",
            "slot_widths": {},
            "fixed_slots": {},
            "caption_width": caption_width,
            "footer_spacer": footer_spacer,
            "layout": layout,
            "small_columns": [],
            "enabled": True,
            "visible": True,
        }
        if self._responsive:
            self.relayout()
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
            self.backend.configure_item(
                group["separator"], show=bool(visible) and self._show_group_separators)
        if self._responsive:
            self.relayout()
        return True

    def add_separator(self, tab_key: str, group_key: str, *, width: int = 5):
        group = self._groups.get((str(tab_key), str(group_key)))
        if group is None:
            raise KeyError("Unknown ribbon group {!r} in tab {!r}.".format(group_key, tab_key))
        width = max(2, int(width))
        tag = self.backend.add_spacer(parent=group["row"], width=width)
        group.setdefault("fixed_slots", {})[tag] = width
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
        record.update({
            "size": size, "icon": icon, "image": image, "width": button_width,
            "uses_template_width": width is None,
        })
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
        record["layout_slot"] = parent if size == "small" else record.get("container") or tag
        self._buttons[record["key"]] = record
        self._reserve_group_width(group, record["layout_slot"], button_width)
        self._refresh_button_theme(record["key"])
        self._add_tooltip(tag, tooltip)
        if self._responsive:
            self.relayout()
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
        record.update({
            "size": size, "icon": icon, "image": image, "menu": menu, "split": True,
            "width": total_width, "uses_template_width": width is None,
        })

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
        record["layout_slot"] = parent if size == "small" else container
        self._buttons[record["key"]] = record
        self._reserve_group_width(group, record["layout_slot"], total_width)
        self._refresh_button_theme(record["key"])
        self._add_tooltip(main, tooltip)
        if self._responsive:
            self.relayout()
        return main

    # ------------------------------------------------------- responsive layout
    def set_responsive(
        self,
        enabled: bool = True,
        *,
        width: int | None = None,
        adaptive: bool | None = None,
    ):
        """Enable responsive ribbon layout.

        By default the selected :class:`RibbonDisplayTemplate` controls whether
        adaptive states are used.  Adaptive mode reduces groups through
        ``large -> medium -> small -> collapsed``.  Pass ``adaptive=False`` to
        retain the legacy whole-group overflow behaviour.

        The host should call :meth:`relayout` (or :meth:`handle_resize`) with the
        available content width from its resize event.  No polling or worker is
        introduced.
        """
        self._responsive = bool(enabled)
        if adaptive is not None:
            self._adaptive_override = bool(adaptive)
            self._adaptive_responsive = bool(adaptive)
        else:
            self._adaptive_override = None
            self._adaptive_responsive = bool(self._adaptive_policy.enabled)
        if width is not None:
            self._ribbon_available_width = max(0, int(width))
        if self._responsive:
            for tab_key in self._tabs:
                self._ensure_overflow_button(tab_key)
        else:
            for tab_key, tab in self._tabs.items():
                for (owner, _), group in self._groups.items():
                    if owner == tab_key:
                        self._restore_group_natural_state(group)
                        shown = bool(group.get("visible", True))
                        self.backend.configure_item(group["tag"], show=shown)
                        self.backend.configure_item(
                            group["separator"],
                            show=shown and self._show_group_separators and self.group_render_style == "separator",
                        )
                if tab_key in self._overflow_buttons:
                    self.backend.configure_item(self._overflow_buttons[tab_key], show=False)
            self._responsive_layouts = {}
        return self.relayout() if self._responsive else {}

    def handle_resize(self, width: int):
        """Resize-event friendly alias for :meth:`relayout`."""
        return self.relayout(width)

    def group_display_state(self, tab_key: str, group_key: str) -> str | None:
        """Return ``large``, ``medium``, ``small`` or ``collapsed`` for a group."""
        group = self._groups.get((str(tab_key), str(group_key)))
        if group is None:
            return None
        if not self._responsive:
            return "large"
        plan = getattr(self, "_responsive_layouts", {}).get(str(tab_key))
        if plan is not None and hasattr(plan, "state_for"):
            return plan.state_for(str(group_key), group.get("adaptive_state", "large"))
        if plan is not None and str(group_key) in getattr(plan, "overflow", ()):
            return "collapsed"
        return group.get("adaptive_state", "large")

    def _ensure_overflow_button(self, tab_key):
        if tab_key in self._overflow_buttons:
            return
        row = self._tabs[tab_key]["row"]
        button = self.backend.add_button(
            label="More ▾", parent=row, show=False, width=max(54, self.OVERFLOW_WIDTH - 4),
            height=self.SMALL_BUTTON_HEIGHT + 5,
            callback=lambda *_args, key=tab_key: self._open_overflow(key),
        )
        self._overflow_buttons[tab_key] = button
        self.backend.bind_item_theme(button, self._button_theme(compact=True))

    def _open_overflow(self, tab_key):
        layout = self._responsive_layouts.get(tab_key) if hasattr(self, "_responsive_layouts") else None
        if not layout or not layout.overflow:
            return
        entries = []
        for group_key in layout.overflow:
            group = self._groups[(tab_key, group_key)]
            entries.append({"label": group["label"], "enabled": False})
            for key, record in self._buttons.items():
                if record.get("tab") != tab_key or record.get("group") != group_key:
                    continue
                if not record.get("visible", True):
                    continue
                entries.append({
                    "label": record.get("label", key), "enabled": record.get("enabled", True),
                    "callback": lambda command=key: self._button_clicked(command),
                })
            entries.append(None)
        if entries and entries[-1] is None:
            entries.pop()
        if not entries:
            return
        menu = self._create_menu("ribbon_overflow_" + tab_key, entries)
        menu.popup()

    def relayout(self, width: int | None = None):
        """Apply adaptive/overflow layout after a host resize event."""
        if width is not None:
            self._ribbon_available_width = max(0, int(width))
        if not self._responsive or self._ribbon_available_width is None:
            return {}
        plans = {}
        policy = self._adaptive_policy
        for tab_key in self._tabs:
            groups = [
                (key, group.get("natural_width", group["width"]))
                for (owner, key), group in self._groups.items()
                if owner == tab_key and group.get("visible", True)
            ]
            if self._adaptive_responsive:
                plan = self._layout_engine.allocate_adaptive(
                    groups,
                    self._ribbon_available_width,
                    medium_scale=policy.medium_scale,
                    small_scale=policy.small_scale,
                    medium_min_width=policy.medium_min_width,
                    small_min_width=policy.small_min_width,
                )
            else:
                plan = self._layout_engine.allocate(groups, self._ribbon_available_width)
            plans[tab_key] = plan

            for key, _ in groups:
                group = self._groups[(tab_key, key)]
                shown = key in plan.visible
                if shown:
                    state = plan.state_for(key, "large") if hasattr(plan, "state_for") else "large"
                    target_width = plan.width_for(key, group.get("natural_width", group["width"])) if hasattr(plan, "width_for") else group.get("natural_width", group["width"])
                    self._apply_group_adaptive_state(group, state, target_width)
                else:
                    group["adaptive_state"] = "collapsed"
                self.backend.configure_item(group["tag"], show=shown)
                self.backend.configure_item(
                    group["separator"],
                    show=shown and self._show_group_separators and self.group_render_style == "separator",
                )
            if tab_key in self._overflow_buttons:
                self.backend.configure_item(self._overflow_buttons[tab_key], show=bool(plan.overflow))
        self._responsive_layouts = plans
        return plans

