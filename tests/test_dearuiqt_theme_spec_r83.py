from contextlib import contextmanager
from unittest.mock import patch

from DearUIQt.themes import (
    ThemeTarget, ThemeColor, ThemeStyle,
    theme_component, theme_spec, create_theme, with_scrollbar,
)


class FakeBackend:
    mvChildWindow = 10
    mvThemeCol_ChildBg = 20
    mvThemeCol_Border = 21
    mvStyleVar_WindowPadding = 30
    mvStyleVar_ChildBorderSize = 31
    mvThemeCol_ScrollbarBg = 40
    mvThemeCol_ScrollbarGrab = 41
    mvThemeCol_ScrollbarGrabHovered = 42
    mvThemeCol_ScrollbarGrabActive = 43
    mvStyleVar_ScrollbarSize = 44
    mvStyleVar_ScrollbarRounding = 45

    def __init__(self):
        self.events = []
        self.existing = set()
        self.next_theme = 100

    def does_item_exist(self, tag):
        return tag in self.existing

    @contextmanager
    def theme(self, **kwargs):
        tag = kwargs.get("tag")
        value = tag if tag is not None else self.next_theme
        self.next_theme += 1
        self.events.append(("theme", kwargs, value))
        yield value

    @contextmanager
    def theme_component(self, target, **kwargs):
        self.events.append(("component", target, kwargs))
        yield target

    def add_theme_color(self, role, value):
        self.events.append(("color", role, value))

    def add_theme_style(self, role, *values):
        self.events.append(("style", role, values))


def test_theme_spec_maps_semantic_roles_only_at_renderer_boundary():
    backend = FakeBackend()
    spec = theme_spec(theme_component(
        ThemeTarget.CHILD_WINDOW,
        colors={
            ThemeColor.CHILD_BACKGROUND: (250, 250, 250, 255),
            ThemeColor.BORDER: (10, 20, 30, 255),
        },
        styles={
            ThemeStyle.WINDOW_PADDING: (4, 5),
            ThemeStyle.CHILD_BORDER_SIZE: 1,
        },
    ))
    theme_id = create_theme(spec, backend=backend)
    assert theme_id == 100
    assert ("component", backend.mvChildWindow, {}) in backend.events
    assert ("color", backend.mvThemeCol_ChildBg, (250, 250, 250, 255)) in backend.events
    assert ("color", backend.mvThemeCol_Border, (10, 20, 30, 255)) in backend.events
    assert ("style", backend.mvStyleVar_WindowPadding, (4, 5)) in backend.events
    assert ("style", backend.mvStyleVar_ChildBorderSize, (1,)) in backend.events


def test_optional_theme_symbol_is_skipped_for_older_renderer():
    backend = FakeBackend()
    component = theme_component(ThemeTarget.CHILD_WINDOW).with_style(
        ThemeStyle.BUTTON_TEXT_ALIGN, 0.0, 0.5, optional=True,
    )
    create_theme(theme_spec(component), backend=backend)
    assert not any(event[0] == "style" for event in backend.events)


def test_named_cached_theme_reuses_existing_renderer_item():
    backend = FakeBackend()
    backend.existing.add("cached-theme")
    spec = theme_spec(
        theme_component(ThemeTarget.CHILD_WINDOW),
        tag="cached-theme", cache=True,
    )
    assert create_theme(spec, backend=backend) == "cached-theme"
    assert backend.events == []


def test_with_scrollbar_adds_shared_dearuiqt_scroll_contract():
    backend = FakeBackend()
    component = with_scrollbar(
        theme_component(ThemeTarget.CHILD_WINDOW),
        track=(1, 2, 3, 255),
    )
    create_theme(theme_spec(component), backend=backend)
    assert ("color", backend.mvThemeCol_ScrollbarBg, (1, 2, 3, 255)) in backend.events
    assert any(e[:2] == ("color", backend.mvThemeCol_ScrollbarGrab) for e in backend.events)
    assert any(e[:2] == ("style", backend.mvStyleVar_ScrollbarSize) for e in backend.events)


def test_public_theme_factory_resolves_backend_when_application_omits_it():
    from DearUIQt.themes import factories
    backend = object()
    with patch.object(factories, "get_backend", return_value=backend), \
         patch.object(factories._style, "tool_bar_theme", return_value="theme") as build:
        assert factories.tool_bar_theme() == "theme"
    build.assert_called_once_with(backend)
