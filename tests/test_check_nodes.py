"""Check Nodes routing: abaqus python -m unittest discover -s tests -p test_check_nodes.py"""
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import run_winux
run_winux._configure_bundled_dependencies(str(ROOT))

from WinUx.controllers.jobs.actions import CHECK_NODES_COMMAND, JobActionsController
from WinUx.ui.components.explorer.context_menu import ExplorerContextMenuMixin


class CheckNodesTests(unittest.TestCase):
    def test_command_is_one_shell_line(self):
        self.assertEqual(CHECK_NODES_COMMAND,
                         "pbsnodes -a | awk '/^[^[:space:]]/ {node=$1} /state =/ {print node, $3}'")
        self.assertNotIn('\n', CHECK_NODES_COMMAND)
        self.assertNotIn('\r', CHECK_NODES_COMMAND)

    def dispatch_menu(self, index, items, action='check_nodes', enabled=True):
        view = SimpleNamespace(
            _context_item_index=index, items=items,
            _find_context_menu_action_spec=Mock(return_value={'enabled': enabled}),
            _hide_context_menus=Mock(), get_selected=Mock(return_value=[]),
            on_item_menu_action=Mock())
        ExplorerContextMenuMixin._on_item_menu_action(view, None, None, action)
        return view

    def test_blank_area_dispatches_without_a_job(self):
        view = self.dispatch_menu(None, [])
        view.on_item_menu_action.assert_called_once_with('check_nodes', [])
        view._hide_context_menus.assert_called_once_with(consume_pointer=True)

    def test_job_disappearing_while_menu_open_does_not_drop_command(self):
        view = self.dispatch_menu(4, [])
        view.on_item_menu_action.assert_called_once_with('check_nodes', [])

    def test_selected_job_is_not_required_to_belong_to_current_user(self):
        item = object()
        view = self.dispatch_menu(0, [item])
        view.on_item_menu_action.assert_called_once_with('check_nodes', [item])

    def test_target_dependent_actions_still_require_a_job(self):
        view = self.dispatch_menu(None, [], action='cancel')
        view.on_item_menu_action.assert_not_called()

    def test_disabled_action_is_not_dispatched(self):
        view = self.dispatch_menu(None, [], enabled=False)
        view.on_item_menu_action.assert_not_called()

    def make_controller(self):
        self.pending = []
        view = SimpleNamespace(
            after_render=lambda callback, *args: self.pending.append((callback, args)),
            after=Mock(), winfo_exists=lambda: True, set_console_visible=Mock())
        app = SimpleNamespace(_closing=False, _connection_generation=1, view=view,
                              console_command=Mock(return_value=True))
        return JobActionsController(app)

    def pump(self):
        pending, self.pending = self.pending, []
        for callback, args in pending:
            callback(*args)

    def test_console_opens_and_command_sends_once_after_popup_teardown(self):
        controller = self.make_controller()
        controller.job_command('check_nodes')
        controller.view.after.assert_not_called()
        controller.view.set_console_visible.assert_not_called()
        controller.app.console_command.assert_not_called()
        self.pump()
        controller.view.set_console_visible.assert_called_once_with(
            True, persist=True, request_login=False)
        controller.app.console_command.assert_called_once_with(CHECK_NODES_COMMAND)
        self.pump()
        controller.app.console_command.assert_called_once()

    def test_repeated_clicks_send_one_command_per_click(self):
        controller = self.make_controller()
        for _ in range(3):
            controller.job_command('check_nodes')
            self.pump()
        self.assertEqual(controller.app.console_command.call_count, 3)

    def test_connection_change_cancels_stale_command(self):
        controller = self.make_controller()
        controller.job_command('check_nodes')
        controller.app._connection_generation += 1
        self.pump()
        controller.app.console_command.assert_not_called()

    def test_closing_application_does_not_send(self):
        controller = self.make_controller()
        controller.app._closing = True
        controller.job_command('check_nodes')
        self.pump()
        controller.app.console_command.assert_not_called()


if __name__ == '__main__':
    unittest.main()
