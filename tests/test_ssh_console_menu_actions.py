"""Exercise menu click routing without creating a Dear PyGui viewport."""
import ast
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import Mock


SOURCE = Path(__file__).resolve().parents[1] / "WinUx" / "dialogs" / "console_form.py"


def load_methods(class_name, names, **namespace):
    tree = ast.parse(SOURCE.read_text(encoding="utf-8"))
    cls = next(node for node in tree.body if isinstance(node, ast.ClassDef)
               and node.name == class_name)
    methods = [node for node in cls.body if isinstance(node, ast.FunctionDef)
               and node.name in names]
    exec(compile(ast.Module(body=methods, type_ignores=[]), str(SOURCE), "exec"), namespace)
    return {name: namespace[name] for name in names}


class ConsoleMenuActionsTests(unittest.TestCase):
    def setUp(self):
        self.dpg = Mock()
        self.dpg.does_item_exist.return_value = True
        self.dpg.is_item_shown.return_value = True
        self.dpg.is_item_hovered.return_value = False
        self.dpg.get_mouse_pos.return_value = (450, 330)
        self.dpg.get_item_pos.return_value = (400, 300)
        # Hidden-window rect origin is deliberately obsolete.
        self.dpg.get_item_rect_min.return_value = (0, 0)
        self.dpg.get_item_rect_size.return_value = (240, 150)
        self.dpg.get_item_configuration.return_value = {"width": 240, "height": 150}
        self.methods = load_methods(
            "ConsoleDialog", ["_mouse_over_context_menu", "_mouse_click",
                              "_context_menu_triggered"], dpg=self.dpg)
        self.panel = SimpleNamespace(
            _context_menu_obj=SimpleNamespace(tag="menu", is_open=True),
            winfo_exists=lambda: True, view=SimpleNamespace(after=Mock()),
            _deactivate_keyboard_if_pointer_outside=Mock())
        self.panel._mouse_over_context_menu = lambda: self.methods[
            "_mouse_over_context_menu"](self.panel)

    def test_click_inside_repositioned_menu_does_not_queue_dismissal(self):
        self.methods["_mouse_click"](self.panel)
        self.panel.view.after.assert_not_called()
        self.dpg.get_item_rect_min.assert_not_called()

    def test_first_frame_uses_configured_size(self):
        self.dpg.get_item_rect_size.return_value = (0, 0)
        self.assertTrue(self.panel._mouse_over_context_menu())

    def test_hovered_menu_does_not_need_geometry(self):
        self.dpg.is_item_hovered.return_value = True
        self.assertTrue(self.panel._mouse_over_context_menu())
        self.dpg.get_item_pos.assert_not_called()

    def test_outside_click_still_queues_dismissal(self):
        self.dpg.get_mouse_pos.return_value = (700, 500)
        self.methods["_mouse_click"](self.panel)
        self.panel.view.after.assert_called_once_with(
            0, self.panel._deactivate_keyboard_if_pointer_outside)

    def test_each_enabled_button_dispatches_its_action_after_release(self):
        methods = load_methods("_ConsoleContextMenu", ["_clicked"])
        actions = {"copy": "_copy_selection", "paste": "_paste_clipboard",
                   "select_all": "_select_all", "find": "_open_find",
                   "clear": "_clear_console"}
        self.panel._menu_action = lambda callback: callback()
        self.panel._context_menu_triggered = lambda action, context: self.methods[
            "_context_menu_triggered"](self.panel, action, context)
        for attribute in actions.values():
            setattr(self.panel, attribute, Mock())
        for action, attribute in actions.items():
            with self.subTest(action=action):
                queued = []
                self.panel.view.after = lambda delay, callback, *args: queued.append((callback, args))
                menu = SimpleNamespace(owner=self.panel, _enabled={action: True},
                                       _set_current=Mock())
                methods["_clicked"](menu, user_data=action)
                getattr(self.panel, attribute).assert_not_called()
                callback, args = queued.pop()
                callback(*args)
                getattr(self.panel, attribute).assert_called_once_with()

    def test_disabled_action_does_not_dispatch(self):
        methods = load_methods("_ConsoleContextMenu", ["_clicked"])
        menu = SimpleNamespace(owner=self.panel, _enabled={"copy": False},
                               _set_current=Mock())
        methods["_clicked"](menu, user_data="copy")
        self.panel.view.after.assert_not_called()


if __name__ == "__main__":
    unittest.main()
