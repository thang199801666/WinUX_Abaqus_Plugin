from contextlib import contextmanager

from DearUIQt.themes import compact_layout_surface_theme, floating_window_theme


class FakeBackend:
    mvAll = 1
    mvThemeCol_Border = 10
    mvThemeCol_WindowBg = 11
    mvThemeCol_TitleBg = 12
    mvThemeCol_TitleBgActive = 13
    mvThemeCol_TitleBgCollapsed = 14
    mvThemeCol_Text = 15
    mvThemeCol_ResizeGrip = 16
    mvThemeCol_ResizeGripHovered = 17
    mvThemeCol_ResizeGripActive = 18
    mvStyleVar_WindowPadding = 30
    mvStyleVar_ItemSpacing = 31
    mvStyleVar_ItemInnerSpacing = 32
    mvStyleVar_ChildBorderSize = 33
    mvStyleVar_CellPadding = 34
    mvStyleVar_WindowRounding = 35
    mvStyleVar_WindowBorderSize = 36
    # Intentionally omit mvStyleVar_WindowTitleAlign: it is optional.

    def __init__(self):
        self.events = []

    def does_item_exist(self, _tag):
        return False

    @contextmanager
    def theme(self, **kwargs):
        self.events.append(("theme", kwargs))
        yield 99

    @contextmanager
    def theme_component(self, target, **kwargs):
        self.events.append(("component", target, kwargs))
        yield target

    def add_theme_color(self, role, value):
        self.events.append(("color", role, value))

    def add_theme_style(self, role, *values):
        self.events.append(("style", role, values))


def test_shell_theme_factories_hide_layout_and_floating_window_renderer_constants():
    backend = FakeBackend()
    assert compact_layout_surface_theme(backend=backend) == 99
    assert ("style", backend.mvStyleVar_WindowPadding, (0, 0)) in backend.events
    assert ("style", backend.mvStyleVar_CellPadding, (0, 0)) in backend.events

    backend.events.clear()
    assert floating_window_theme(backend=backend) == 99
    assert any(event[:2] == ("color", backend.mvThemeCol_TitleBgActive) for event in backend.events)
    assert any(event[:2] == ("color", backend.mvThemeCol_ResizeGrip) for event in backend.events)
    # Missing optional title-align support must not prevent theme creation.
