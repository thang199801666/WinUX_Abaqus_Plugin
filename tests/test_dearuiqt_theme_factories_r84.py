from contextlib import contextmanager

from DearUIQt.themes import (
    menu_button_theme,
    menu_image_button_theme,
    menu_surface_theme,
    viewport_surface_theme,
)


class FakeThemeBackend:
    mvAll = 1
    mvButton = 2
    mvImageButton = 3
    mvThemeCol_WindowBg = 10
    mvThemeCol_ChildBg = 11
    mvThemeCol_PopupBg = 12
    mvThemeCol_Text = 13
    mvThemeCol_TextDisabled = 14
    mvThemeCol_Separator = 15
    mvThemeCol_Border = 16
    mvThemeCol_Button = 17
    mvThemeCol_ButtonHovered = 18
    mvThemeCol_ButtonActive = 19
    mvThemeCol_ScrollbarBg = 20
    mvThemeCol_ScrollbarGrab = 21
    mvThemeCol_ScrollbarGrabHovered = 22
    mvThemeCol_ScrollbarGrabActive = 23
    mvStyleVar_WindowPadding = 30
    mvStyleVar_ItemSpacing = 31
    mvStyleVar_WindowRounding = 32
    mvStyleVar_PopupRounding = 33
    mvStyleVar_WindowBorderSize = 34
    mvStyleVar_FramePadding = 35
    mvStyleVar_FrameRounding = 36
    mvStyleVar_FrameBorderSize = 37
    mvStyleVar_ButtonTextAlign = 38
    mvStyleVar_Alpha = 39
    mvStyleVar_ScrollbarSize = 40
    mvStyleVar_ScrollbarRounding = 41

    def __init__(self):
        self.events = []
        self._next = 100

    def does_item_exist(self, item):
        return False

    @contextmanager
    def theme(self, **kwargs):
        value = kwargs.get("tag") or self._next
        self._next += 1
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


def test_menu_surface_factory_maps_popup_roles_at_backend_boundary():
    backend = FakeThemeBackend()
    menu_surface_theme(backend=backend, padding=(4, 4), spacing=(0, 1), tag=None, cache=False)
    assert ("component", backend.mvAll, {}) in backend.events
    assert any(event[:2] == ("color", backend.mvThemeCol_PopupBg) for event in backend.events)
    assert ("style", backend.mvStyleVar_WindowPadding, (4, 4)) in backend.events
    assert ("style", backend.mvStyleVar_ItemSpacing, (0, 1)) in backend.events
    assert any(event[:2] == ("style", backend.mvStyleVar_PopupRounding) for event in backend.events)


def test_menu_button_factories_cover_keyboard_disabled_and_icon_states():
    backend = FakeThemeBackend()
    menu_button_theme(
        backend=backend, keyboard=True, align=(0.0, 0.5),
        frame_padding=(8, 4), tag=None, cache=False,
    )
    assert ("style", backend.mvStyleVar_FrameBorderSize, (1,)) in backend.events
    assert ("style", backend.mvStyleVar_ButtonTextAlign, (0.0, 0.5)) in backend.events

    backend.events.clear()
    menu_image_button_theme(backend=backend, disabled=True, tag=None, cache=False)
    assert ("style", backend.mvStyleVar_Alpha, (0.38,)) in backend.events


def test_viewport_surface_factory_owns_shared_scrollbar_contract():
    backend = FakeThemeBackend()
    viewport_surface_theme(
        backend=backend,
        background=(10, 11, 12, 255),
        text=(20, 21, 22, 255),
        border=(30, 31, 32, 255),
        scrollbar=True,
    )
    assert any(event[:2] == ("color", backend.mvThemeCol_ScrollbarGrab) for event in backend.events)
    assert any(event[:2] == ("style", backend.mvStyleVar_ScrollbarSize) for event in backend.events)
