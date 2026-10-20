"""End-to-end QMenu submenu lifecycle with a simulated DPG native popup stack.

This backend intentionally models two production edge cases: native popups
reject opening over an existing popup by default, and DPG child windows do not
expose get_item_rect_min. It tests actual QMenu construction, routing and
visibility rather than patching _show_submenu itself.
"""
from contextlib import contextmanager
from unittest.mock import patch

from DearUIQt.widgets import QMenu


class PopupBackend:
    mvMouseButton_Left = 0
    mvMouseButton_Right = 1

    def __init__(self, *, viewport_width=800):
        self.uid = 0
        self.items = {}
        self.viewport_width = viewport_width
        self.frame = 1
        self.mouse = (0, 0)
        self.handlers = {}
        self.bound = {}

    def generate_uuid(self):
        self.uid += 1
        return 'uuid-{}'.format(self.uid)

    def _add(self, kind, *, parent=None, **props):
        key = self.generate_uuid()
        self.items[key] = dict(kind=kind, parent=parent, show=True,
                               pos=(0, 0), width=14, height=14)
        self.items[key].update(props)
        return key

    @contextmanager
    def window(self, **props):
        key = props['tag']
        self.items[key] = dict(kind='mvWindowAppItem', parent=None, pos=(0, 0), **props)
        yield key

    def add_child_window(self, **props):
        parent = props['parent']
        # Mimic Dear ImGui row position inside the menu's window padding.
        index = sum(1 for item in self.items.values()
                    if item.get('parent') == parent and item['kind'] == 'mvChildWindow')
        data = {k: v for k, v in props.items() if k != 'parent'}
        item = self._add('mvChildWindow', parent=parent, **data)
        self.items[item]['pos'] = (4, 3 + 23 * index)
        return item

    def add_text(self, label, **props):
        return self._add('mvText', text=label, **props)

    def add_drawlist(self, **props):
        return self._add('mvDrawlist', **props)

    def draw_triangle(self, *vertices, **props):
        return self._add('mvDrawTriangle', vertices=vertices, **props)

    def add_spacer(self, **props):
        return self._add('mvSpacer', **props)

    def add_separator(self, **props):
        return self._add('mvSeparator', **props)

    def bind_item_theme(self, *_args):
        pass

    def delete_item(self, key, *, children_only=False, **_kwargs):
        if not children_only:
            self.items.pop(key, None)

    def does_item_exist(self, key):
        return key in self.items

    def get_item_children(self, key, slot):
        return [name for name, item in self.items.items() if item['parent'] == key] if slot == 1 else []

    def get_item_info(self, key):
        return {'type': 'mvAppItemType::' + self.items[key]['kind']}

    def get_item_state(self, key):
        item = self.items[key]
        return {'pos': item['pos'], 'rect_size': (item['width'], item['height'])}

    def get_item_parent(self, key):
        return self.items[key]['parent']

    def get_item_rect_min(self, key):
        raise RuntimeError('rect_min is not populated for DPG child windows')

    def get_text_size(self, text):
        return len(text) * 7, 14

    def get_item_configuration(self, key):
        return dict(self.items[key])

    def get_viewport_client_width(self):
        return self.viewport_width

    def get_viewport_client_height(self):
        return 720

    def get_viewport_pos(self):
        return (360, 100)

    def set_item_pos(self, key, pos):
        self.items[key]['pos'] = tuple(pos)

    def configure_item(self, key, **kwargs):
        item = self.items[key]
        if kwargs.get('show') and item.get('popup') and item.get('no_open_over_existing_popup', True):
            if any(other is not item and other.get('popup') and other.get('show')
                   for other in self.items.values()):
                # Dear ImGui refuses to open a second native popup with this flag.
                return
        item.update(kwargs)

    def is_item_shown(self, key):
        return bool(self.items[key]['show'])

    def focus_item(self, _key):
        pass

    def get_frame_count(self):
        return self.frame

    def get_mouse_pos(self, local=False):
        return self.mouse

    @contextmanager
    def handler_registry(self):
        yield self.generate_uuid()

    @contextmanager
    def item_handler_registry(self):
        yield self.generate_uuid()

    def add_item_hover_handler(self, **_kwargs):
        pass

    def add_item_clicked_handler(self, **_kwargs):
        pass

    def add_mouse_click_handler(self, **_kwargs):
        pass

    def add_key_press_handler(self, **_kwargs):
        pass

    def bind_item_handler_registry(self, *_args):
        pass


def make_menu(backend):
    # The UI palette is irrelevant to menu behavior and its real constructor
    # allocates DPG theme resources, so keep the test strictly on input/geometry.
    with patch('DearUIQt.widgets.menu._menu_theme', return_value='menu'), \
         patch('DearUIQt.widgets.menu._row_theme', return_value='row'), \
         patch('DearUIQt.widgets.menu._text_theme', return_value='text'), \
         patch('DearUIQt.widgets.menu.acquire_popup_input', return_value=True), \
         patch('DearUIQt.widgets.menu.release_popup_input'):
        menu = QMenu([
            {'id': 'quick', 'label': 'Quick Upload', 'children': [
                {'action': 'quick:.inp', 'label': 'Upload *.inp'},
                {'action': 'quick:.dat', 'label': 'Upload *.dat'},
            ]},
            {'id': 'new', 'label': 'New', 'children': [
                {'action': 'command:new_folder', 'label': 'New Folder'},
            ]},
        ], backend=backend, min_width=200)
        yield menu


def test_group_click_opens_real_submenu_and_leaf_triggers_action():
    backend = PopupBackend()
    for menu in make_menu(backend):
        events = []
        menu.triggered.connect(lambda action, ctx: events.append((action, ctx)))
        assert menu.popup((100, 100), context={'source': 'explorer'})
        backend.frame += 1
        # The menu's child row deliberately has no rect_min property.
        assert menu._row_clicked(user_data='quick') is None
        assert menu._open_submenu == 'quick'
        child = menu._submenus['quick']
        assert child.isVisible()
        assert backend.items[child.tag]['no_open_over_existing_popup'] is False
        assert backend.items[child.tag]['pos'][0] > 100
        child._row_clicked(user_data='quick:.inp')
        assert events == [('quick:.inp', {'source': 'explorer'})]
        assert not menu.isVisible()


def test_submenu_opens_to_left_when_near_right_edge():
    backend = PopupBackend(viewport_width=340)
    for menu in make_menu(backend):
        assert menu.popup((130, 60))
        backend.frame += 1
        menu._row_clicked(user_data='quick')
        child = menu._submenus['quick']
        assert child.isVisible()
        assert backend.items[child.tag]['pos'][0] < backend.items[menu.tag]['pos'][0]
        assert backend.items[child.tag]['pos'][0] >= 0


def test_global_popup_position_stays_in_screen_space_and_tracks_viewport_origin():
    backend = PopupBackend(viewport_width=800)
    for menu in make_menu(backend):
        assert menu.popupGlobal((410, 240), context={"source": "context"})
        assert backend.items[menu.tag]["pos"] == (410.0, 240.0)


def test_local_popup_position_remains_renderer_local_for_menu_bar_and_submenus():
    backend = PopupBackend(viewport_width=800)
    for menu in make_menu(backend):
        assert menu.popup((410, 240))
        assert backend.items[menu.tag]["pos"] == (410.0, 240.0)


def test_global_popup_clamps_to_moved_viewport_screen_bounds_not_desktop_origin():
    backend = PopupBackend(viewport_width=800)
    for menu in make_menu(backend):
        assert menu.popupGlobal((20, 30))
        x, y = backend.items[menu.tag]["pos"]
        assert x == 360.0
        assert y == 100.0


def test_global_context_submenu_inherits_screen_coordinate_space():
    backend = PopupBackend(viewport_width=800)
    for menu in make_menu(backend):
        assert menu.popupGlobal((610, 240), context={"source": "context"})
        backend.frame += 1
        menu._row_clicked(user_data='quick')
        child = menu._submenus['quick']
        assert child.isVisible()
        root_x, root_y = backend.items[menu.tag]['pos']
        child_x, child_y = backend.items[child.tag]['pos']
        assert menu._popup_global_position is True
        assert child._popup_global_position is True
        assert child_x > root_x
        assert child_y >= root_y
        assert child_x >= 360.0


def test_global_context_submenu_flips_inside_moved_viewport_screen_bounds():
    backend = PopupBackend(viewport_width=800)
    for menu in make_menu(backend):
        # Moved viewport spans x=360..1160. The root is clamped near its right
        # edge; the child must flip left without ever falling back to x~=0.
        assert menu.popupGlobal((1120, 180), context={"source": "context"})
        backend.frame += 1
        menu._row_clicked(user_data='quick')
        child = menu._submenus['quick']
        root_x, _ = backend.items[menu.tag]['pos']
        child_x, _ = backend.items[child.tag]['pos']
        assert child_x < root_x
        assert child_x >= 360.0
