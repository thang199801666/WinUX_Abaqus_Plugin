import unittest
from types import SimpleNamespace
from unittest.mock import Mock

from DearUIQt.widgets.menu import QMenu


class MenuHoverStabilityTests(unittest.TestCase):
    def _menu(self):
        menu = SimpleNamespace()
        menu._active_action = 'one'
        menu._rows = {'one': 101, 'two': 102, 'three': 103}
        menu._row_specs = {
            'one': {'enabled': True},
            'two': {'enabled': True},
            'three': {'enabled': True},
        }
        menu._row_hover_state = {}
        menu.backend = Mock()
        menu._set_row_hover = lambda action_id, hovered: QMenu._set_row_hover(menu, action_id, hovered)
        return menu

    def test_stationary_hover_is_a_complete_noop(self):
        menu = self._menu()
        menu._row_hover_state['one'] = (True, False)
        changed = QMenu._set_active_action(menu, 'one')
        self.assertFalse(changed)
        menu.backend.bind_item_theme.assert_not_called()

    def test_transition_touches_only_old_and_new_rows(self):
        menu = self._menu()
        menu._row_hover_state.update({
            'one': (True, False),
            'two': (False, False),
            'three': (False, False),
        })
        changed = QMenu._set_active_action(menu, 'two')
        self.assertTrue(changed)
        self.assertEqual(menu._active_action, 'two')
        bound_rows = [call.args[0] for call in menu.backend.bind_item_theme.call_args_list]
        self.assertEqual(bound_rows, [101, 102])
        self.assertNotIn(103, bound_rows)


    def test_draw_layer_hover_does_not_rebind_row_theme(self):
        menu = self._menu()
        menu._row_hover_layers = {'one': 201, 'two': 202, 'three': 203}
        menu._row_hover_state.update({
            'one': (True, False),
            'two': (False, False),
            'three': (False, False),
        })
        changed = QMenu._set_active_action(menu, 'two')
        self.assertTrue(changed)
        menu.backend.bind_item_theme.assert_not_called()
        self.assertEqual(
            menu.backend.configure_item.call_args_list,
            [unittest.mock.call(201, show=False), unittest.mock.call(202, show=True)],
        )

    def test_repeated_row_theme_state_does_not_rebind(self):
        menu = self._menu()
        menu._row_hover_state['two'] = (True, False)
        self.assertFalse(QMenu._set_row_hover(menu, 'two', True))
        menu.backend.bind_item_theme.assert_not_called()

    def test_duplicate_row_and_drawlist_hover_do_not_repeat_work(self):
        submenu = SimpleNamespace(isVisible=lambda: True)
        menu = self._menu()
        menu._active_action = None
        menu._row_specs['two'] = {'enabled': True, 'children': []}
        menu._open_submenu = None
        menu._submenus = {'two': submenu}
        menu._hide_open_submenu = Mock()
        menu._show_submenu = Mock()
        menu._set_active_action = lambda action_id: QMenu._set_active_action(menu, action_id)

        QMenu._row_hovered(menu, user_data='two')
        first_count = menu.backend.bind_item_theme.call_count
        QMenu._row_hovered(menu, user_data='two')
        self.assertEqual(menu.backend.bind_item_theme.call_count, first_count)
        menu._show_submenu.assert_not_called()
        menu._hide_open_submenu.assert_not_called()


if __name__ == '__main__':
    unittest.main(verbosity=2)
