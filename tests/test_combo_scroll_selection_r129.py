from types import SimpleNamespace

import DearUIQt.widgets.menu as menu_module
from DearUIQt.widgets.menu import ImGuiMenu


class _Backend:
    mvMouseButton_Left = 0
    mvMouseButton_Right = 1

    def __init__(self):
        self.frame = 20
        self.mouse = (150.0, 112.0)
        self.scroll_y = 72.0

    def get_frame_count(self):
        return self.frame

    def is_item_shown(self, item):
        return True

    def get_mouse_pos(self, local=False):
        return self.mouse

    def get_y_scroll(self, item):
        return self.scroll_y if item == 'popup' else 0.0

    def get_x_scroll(self, item):
        return 0.0


def _menu():
    m = object.__new__(ImGuiMenu)
    m.backend = _Backend()
    m.tag = 'popup'
    m._parent_menu = None
    m._submenus = {}
    m._open_submenu = None
    m._opened_frame = -1
    m._last_row_click_frame = None
    m._rows = {str(i): f'row{i}' for i in range(8)}
    m._row_specs = {str(i): {'action': str(i), 'enabled': True} for i in range(8)}
    m._items = {}
    m._context = None
    return m


def test_pointer_row_rect_subtracts_popup_scroll_before_hit_testing(monkeypatch):
    m = _menu()
    rects = {
        'popup': (100.0, 100.0, 300.0, 220.0),
        'row3': (100.0, 172.0, 300.0, 196.0),
    }
    monkeypatch.setattr(menu_module, 'dpg_window_rect', lambda backend, item, clip=False: rects.get(item))
    assert m._pointer_row_rect('row3') == (100.0, 100.0, 300.0, 124.0)


def test_scrolled_combo_click_maps_to_visible_model_row(monkeypatch):
    m = _menu()
    # Raw child-window positions stay at their pre-scroll coordinates. After a
    # 72 px scroll, logical row 3 is painted where row 0 originally appeared.
    rects = {'popup': (100.0, 100.0, 300.0, 220.0)}
    for i in range(8):
        top = 100.0 + i * 24.0
        rects[f'row{i}'] = (100.0, top, 300.0, top + 24.0)
    monkeypatch.setattr(menu_module, 'dpg_window_rect', lambda backend, item, clip=False: rects.get(item))

    clicked = []
    m._row_clicked = lambda sender=None, app_data=None, user_data=None: clicked.append(str(user_data))
    m._pointer_clicked()
    assert clicked == ['3']


def test_rows_scrolled_outside_popup_are_not_click_targets(monkeypatch):
    m = _menu()
    rects = {
        'popup': (100.0, 100.0, 300.0, 220.0),
        'row0': (100.0, 100.0, 300.0, 124.0),
    }
    monkeypatch.setattr(menu_module, 'dpg_window_rect', lambda backend, item, clip=False: rects.get(item))
    assert m._pointer_row_rect('row0') is None
