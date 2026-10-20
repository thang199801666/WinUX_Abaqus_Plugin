"""Regression coverage for stable top-level QMenuBar popup anchoring.

Dear PyGui may transiently return the first sibling's rect_min for another
menu-bar button while a popup is changing focus.  QMenuBar must derive the
anchor from the horizontal bar layout instead of trusting that stale value.
"""

from DearUIQt.widgets.menu_bar import QMenuBar


class _Backend:
    def __init__(self):
        self.rects = {
            "bar": (10, 30),
            "file": (10, 30),
            # Simulate the production failure: every later button reports the
            # File button's origin for one transient input frame.
            "bookmarks": (10, 30),
            "commands": (10, 30),
            "reference": (10, 30),
            "view": (10, 30),
        }
        self.sizes = {
            "file": (38, 20),
            "bookmarks": (75, 20),
            "commands": (78, 20),
            "reference": (72, 20),
            "view": (42, 20),
        }

    def get_item_rect_min(self, item):
        return self.rects[item]

    def get_item_rect_size(self, item):
        return self.sizes[item]


class _Menu:
    def __init__(self, tag):
        self.tag = tag
        self.positions = []

    def popup(self, position=None):
        self.positions.append(position)
        return True

    def hide(self, consume_pointer=False):
        return True


def _bar(backend):
    bar = QMenuBar.__new__(QMenuBar)
    bar.backend = backend
    bar.tag = "bar"
    bar._menus = []
    bar._buttons = {}
    bar._active_menu = None
    bar._active_button = None
    bar._set_button_active = lambda *_args, **_kwargs: None
    return bar


def test_later_menu_uses_horizontal_layout_when_direct_rect_min_is_stale():
    backend = _Backend()
    bar = _bar(backend)
    menus = [_Menu(name) for name in ("file", "bookmarks", "commands", "reference", "view")]
    buttons = ("file", "bookmarks", "commands", "reference", "view")
    bar._menus = menus
    bar._buttons = dict(zip(menus, buttons))

    view = menus[-1]
    assert bar._open_menu(view)

    expected_x = 10 + 38 + 75 + 78 + 72
    assert view.positions == [(expected_x, 50.0)]
    assert bar._active_menu is view
    assert bar._active_button == "view"


def test_anchor_falls_back_to_bar_origin_when_first_button_rect_is_unavailable():
    backend = _Backend()
    original = backend.get_item_rect_min

    def rect_min(item):
        if item == "file":
            raise RuntimeError("transient rect state unavailable")
        return original(item)

    backend.get_item_rect_min = rect_min
    bar = _bar(backend)
    menus = [_Menu("file"), _Menu("view")]
    bar._menus = menus
    bar._buttons = {menus[0]: "file", menus[1]: "view"}

    rect = bar._button_anchor_rect("view")
    assert rect == (48.0, 30.0, 42.0, 20.0)


def test_moved_viewport_uses_screen_space_popup_anchor(monkeypatch):
    from DearUIQt.QtCore import QPoint
    import DearUIQt.widgets.menu_bar as menu_bar_module

    class _GlobalMenu(_Menu):
        def __init__(self, tag):
            super().__init__(tag)
            self.global_positions = []

        def popupGlobal(self, position=None):
            self.global_positions.append(position)
            return True

    backend = _Backend()
    bar = _bar(backend)
    menus = [_GlobalMenu(name) for name in ("file", "bookmarks", "commands", "reference")]
    buttons = ("file", "bookmarks", "commands", "reference")
    bar._menus = menus
    bar._buttons = dict(zip(menus, buttons))

    # Reference is at local x=10+38+75+78=201. Simulate WinUx client origin
    # at desktop screen (563, 61) while the pointer is inside Reference.
    monkeypatch.setattr(
        menu_bar_module.QCursor, "localPos",
        staticmethod(lambda backend=None: QPoint(220, 40)),
    )
    monkeypatch.setattr(
        menu_bar_module.QCursor, "screenPos",
        staticmethod(lambda backend=None: QPoint(783, 101)),
    )

    reference = menus[-1]
    assert bar._open_menu(reference)
    assert reference.global_positions == [(764.0, 111.0)]
    assert reference.positions == []


def test_screen_anchor_does_not_double_offset_screen_space_rect(monkeypatch):
    from DearUIQt.QtCore import QPoint
    import DearUIQt.widgets.menu_bar as menu_bar_module

    backend = _Backend()
    bar = _bar(backend)
    monkeypatch.setattr(
        menu_bar_module.QCursor, "localPos",
        staticmethod(lambda backend=None: QPoint(220, 40)),
    )
    monkeypatch.setattr(
        menu_bar_module.QCursor, "screenPos",
        staticmethod(lambda backend=None: QPoint(783, 101)),
    )
    # Cursor is already inside this desktop-space rectangle, so it must stay
    # unchanged instead of adding the local->screen offset a second time.
    rect = (760.0, 90.0, 72.0, 20.0)
    assert bar._button_anchor_screen_rect(rect) == rect
