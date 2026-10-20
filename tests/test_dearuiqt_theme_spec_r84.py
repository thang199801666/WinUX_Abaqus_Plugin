from contextlib import contextmanager

from DearUIQt.themes import ThemeColor, ThemeStyle, ThemeTarget, make_theme, theme_component


class FakeBackend:
    mvWindowAppItem = 1
    mvThemeCol_PopupBg = 2
    mvStyleVar_Alpha = 3
    mvStyleVar_PopupRounding = 4

    def __init__(self):
        self.events = []

    def does_item_exist(self, _tag):
        return False

    @contextmanager
    def theme(self, **kwargs):
        self.events.append(("theme", kwargs))
        yield 10

    @contextmanager
    def theme_component(self, target, **kwargs):
        self.events.append(("component", target, kwargs))
        yield target

    def add_theme_color(self, role, value):
        self.events.append(("color", role, value))

    def add_theme_style(self, role, *values):
        self.events.append(("style", role, values))


def test_r84_theme_roles_keep_window_popup_and_alpha_symbols_at_backend_boundary():
    backend = FakeBackend()
    make_theme(theme_component(
        ThemeTarget.WINDOW,
        colors={ThemeColor.POPUP_BACKGROUND: (1, 2, 3, 255)},
        styles={ThemeStyle.ALPHA: .5, ThemeStyle.POPUP_ROUNDING: 2},
    ), backend=backend)
    assert ("component", backend.mvWindowAppItem, {}) in backend.events
    assert ("color", backend.mvThemeCol_PopupBg, (1, 2, 3, 255)) in backend.events
    assert ("style", backend.mvStyleVar_Alpha, (.5,)) in backend.events
    assert ("style", backend.mvStyleVar_PopupRounding, (2,)) in backend.events
