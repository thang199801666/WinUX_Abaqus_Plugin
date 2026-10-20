"""Regressions for QMenu's full-row triangle canvas and popup routing."""
from contextlib import contextmanager
from unittest.mock import Mock, patch

from DearUIQt.widgets import QMenu


class MenuBackend:
    mvMouseButton_Left = 0

    def __init__(self):
        self.counter = 0
        self.items = {}
        self.handlers = {}
        self.frame = 2
        self.mouse = (75, 20)
        self.bound = {}

    def _add(self, kind, **kwargs):
        self.counter += 1
        item = f"{kind}-{self.counter}"
        self.items[item] = dict(kwargs)
        return item

    def add_child_window(self, **kwargs):
        return self._add('row', **kwargs)

    def add_text(self, text, **kwargs):
        return self._add('text', text=text, **kwargs)

    def add_drawlist(self, **kwargs):
        return self._add('canvas', **kwargs)

    def draw_triangle(self, *points, **kwargs):
        return self._add('triangle', points=points, **kwargs)

    def bind_item_theme(self, *_args):
        pass

    def delete_item(self, *_args, **_kwargs):
        pass

    def get_text_size(self, text):
        return (len(text)*7, 14)

    @contextmanager
    def item_handler_registry(self):
        key = self._add('handlers')
        self.handlers[key] = []
        self._registry = key
        try:
            yield key
        finally:
            self._registry = None

    def add_item_hover_handler(self, **kwargs):
        self.handlers[self._registry].append(('hover', kwargs))

    def add_item_clicked_handler(self, **kwargs):
        self.handlers[self._registry].append(('clicked', kwargs))

    def bind_item_handler_registry(self, item, registry):
        self.bound[item] = registry

    def is_item_shown(self, _item):
        return True

    def get_frame_count(self):
        return self.frame

    def get_mouse_pos(self, local=False):
        return self.mouse

    def get_item_rect_min(self, _item):
        return (10, 10)

    def get_item_rect_size(self, _item):
        return (240, 23)


def make_menu(backend=None):
    backend = backend or MenuBackend()
    menu = object.__new__(QMenu)
    menu.backend = backend
    menu.tag = 'popup'
    menu._parent_menu = None
    menu._rows = {}
    menu._row_specs = {}
    menu._items = {}
    menu._handlers = []
    menu._arrow_offsets = {}
    menu._has_checkables = False
    menu._submenus = {}
    menu._open_submenu = None
    menu._opened_frame = 1
    menu._last_row_click_frame = None
    menu._context = None
    return menu


def test_row_wide_triangle_canvas_routes_hover_and_click_to_action():
    backend = MenuBackend()
    menu = make_menu(backend)
    spec = {'id': 'quick_upload_group', 'label': 'Quick Upload',
            'enabled': True, 'children': [{'id': 'inp', 'action': 'inp', 'label': 'INP'}]}
    with patch('DearUIQt.widgets.menu._row_theme', return_value='rowtheme'), \
         patch('DearUIQt.widgets.menu._text_theme', return_value='texttheme'):
        menu._build_row(spec, 270)
    arrow = menu._items['quick_upload_group']['arrow']
    row = menu._rows['quick_upload_group']
    assert backend.items[arrow]['width'] == 270 - 2 * menu.WINDOW_PAD_X
    assert backend.items[arrow]['pos'] == (0, 0)
    assert backend.items[arrow]['parent'] == row
    assert any(info['points'][0][0] > 200 for key, info in backend.items.items()
               if key.startswith('triangle-'))

    handlers = backend.handlers[backend.bound[arrow]]
    assert [kind for kind, _options in handlers] == ['hover', 'clicked']
    menu._row_hovered = Mock()
    menu._row_clicked = Mock()
    handlers[0][1]['callback'](user_data=handlers[0][1]['user_data'])
    menu._row_hovered.assert_called_once_with(None, None, 'quick_upload_group')
    handlers[1][1]['callback'](user_data=handlers[1][1]['user_data'])
    menu._row_clicked.assert_called_once_with(user_data='quick_upload_group')

    # A global click handler may fire for the same frame: never dispatch twice.
    menu._pointer_clicked()
    menu._row_clicked.assert_called_once()
    # But a distinct mouse click in another frame still works.
    backend.frame += 1
    with patch('DearUIQt.widgets.menu.dpg_window_rect', return_value=(10, 10, 250, 33)):
        menu._pointer_clicked()
    assert menu._row_clicked.call_count == 2


def test_group_reopens_after_native_popup_was_hidden():
    backend = MenuBackend()
    menu = make_menu(backend)
    menu._rows['more'] = 'row'
    child = Mock()
    child.isVisible.return_value = False
    child.popup.return_value = True
    menu._submenus['more'] = child
    menu._open_submenu = 'more'  # stale cache after native auto-dismiss
    menu._show_submenu('more', {'children': [{'id': 'child'}]})
    child.popup.assert_called_once_with((248, 10), context=None)
    assert menu._open_submenu == 'more'
    child.isVisible.return_value = True
    menu._show_submenu('more', {'children': [{'id': 'child'}]})
    child.popup.assert_called_once()  # no redundant reopening


def test_group_can_be_clicked_in_parent_when_another_submenu_is_open():
    backend = MenuBackend()
    menu = make_menu(backend)
    menu._rows['quick_upload_group'] = 'parent_row'
    menu._row_clicked = Mock()
    child = make_menu(backend)
    child._parent_menu = menu
    child.tag = 'child_popup'
    child._rows['child_item'] = 'child_row'
    child._row_clicked = Mock()
    menu._submenus['new'] = child
    menu._open_submenu = 'new'
    with patch('DearUIQt.widgets.menu.dpg_window_rect', side_effect=lambda _b, item, **_kwargs:
               (10, 10, 250, 33) if item == 'parent_row' else (260, 10, 410, 33)):
        menu._pointer_clicked()
    menu._row_clicked.assert_called_once_with(user_data='quick_upload_group')
    child._row_clicked.assert_not_called()


def test_drawlist_hover_and_click_open_submenu_without_triggering_leaf_action():
    backend = MenuBackend()
    menu = make_menu(backend)
    menu._row_specs['quick_upload_group'] = {
        'id': 'quick_upload_group', 'enabled': True,
        'children': [{'action': 'quick:.inp', 'label': 'Upload *.inp'}],
    }
    menu._set_active_action = Mock()
    menu._show_submenu = Mock()
    menu._hide_open_submenu = Mock()
    menu._drawlist_hovered(user_data='quick_upload_group')
    menu._set_active_action.assert_called_once_with('quick_upload_group')
    menu._show_submenu.assert_called_once_with(
        'quick_upload_group', menu._row_specs['quick_upload_group'])
    menu._drawlist_clicked(user_data='quick_upload_group')
    assert menu._show_submenu.call_count == 2
    menu._hide_open_submenu.assert_not_called()


def test_drawlist_click_after_popup_hide_is_ignored():
    backend = MenuBackend()
    backend.is_item_shown = Mock(return_value=False)
    menu = make_menu(backend)
    menu._row_clicked = Mock()
    menu._drawlist_clicked(user_data='quick_upload_group')
    menu._row_clicked.assert_not_called()
