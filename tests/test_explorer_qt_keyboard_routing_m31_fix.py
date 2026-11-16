import unittest
from types import SimpleNamespace

from DearUIQt import QApplication
from DearUIQt.core import QEvent, QInputTarget, QKeyEvent, Qt
from WinUx.ui.components.explorer.keyboard import ExplorerKeyboardController, ExplorerKeyboardInput


class _View:
    def __init__(self):
        self.popup = False
        self.commands = []
        self._has_focus = True
        self._rename_active = False

    def _context_menu_is_visible(self):
        return self.popup

    def _on_context_menu_key(self, user_data=None):
        self.commands.append(("popup", user_data))


class ExplorerQtKeyboardRoutingTests(unittest.TestCase):
    def setUp(self):
        self.view = _View()
        state = ExplorerKeyboardInput(
            ctrl=lambda: False,
            shift=lambda: False,
            alt=lambda: False,
            overlay_owns_input=lambda: False,
            pointer_blocked=lambda _view: False,
        )
        # The central path must not depend on renderer-native mvKey values.
        self.controller = ExplorerKeyboardController(self.view, SimpleNamespace(), state)

    def _press(self, key, modifiers=Qt.NoModifier):
        return self.controller.handle_qt_key_event(
            QKeyEvent(QEvent.KeyPress, key, modifiers))

    def test_delete_and_function_keys_use_qt_key_domain(self):
        seen = []
        self.controller._on_delete_shortcut = lambda *a, **k: seen.append("delete")
        self.controller._on_rename_shortcut = lambda *a, **k: seen.append("f2")
        self.controller._on_edit_shortcut = lambda *a, **k: seen.append("f4")
        self.controller._on_transfer_shortcut = lambda *a, **k: seen.append("f5")
        self.controller._on_new_folder_shortcut = lambda *a, **k: seen.append("f7")

        for key in (Qt.Key_Delete, Qt.Key_F2, Qt.Key_F4, Qt.Key_F5, Qt.Key_F7):
            self.assertTrue(self._press(key))

        self.assertEqual(seen, ["delete", "f2", "f4", "f5", "f7"])

    def test_navigation_enter_space_and_escape_use_qt_keys(self):
        seen = []
        self.controller._on_navigation_key = lambda *a, **k: seen.append(("nav", k.get("user_data")))
        self.controller._on_enter_pressed = lambda *a, **k: seen.append(("enter", None))
        self.controller._on_space_pressed = lambda *a, **k: seen.append(("space", None))
        self.controller._on_escape_pressed = lambda *a, **k: seen.append(("escape", None))

        self.assertTrue(self._press(Qt.Key_Down))
        self.assertTrue(self._press(Qt.Key_Home))
        self.assertTrue(self._press(Qt.Key_Return))
        self.assertTrue(self._press(Qt.Key_Space))
        self.assertTrue(self._press(Qt.Key_Escape))
        self.assertEqual(seen, [
            ("nav", "down"), ("nav", "home"), ("enter", None),
            ("space", None), ("escape", None),
        ])

    def test_popup_navigation_uses_qt_keys(self):
        self.view.popup = True
        self.assertTrue(self._press(Qt.Key_Up))
        self.assertTrue(self._press(Qt.Key_Right))
        self.assertTrue(self._press(Qt.Key_Enter))
        self.assertEqual(self.view.commands, [
            ("popup", "up"), ("popup", "right"), ("popup", "activate")])


class ExplorerQtKeyboardApplicationIntegrationTests(unittest.TestCase):
    def tearDown(self):
        app = QApplication.instance()
        if app is not None:
            app.delete()

    def test_application_focus_target_delivers_delete_and_f2_as_qt_keys(self):
        app = QApplication()
        view = _View()
        state = ExplorerKeyboardInput(
            ctrl=lambda: False, shift=lambda: False, alt=lambda: False,
            overlay_owns_input=lambda: False, pointer_blocked=lambda _view: False)
        controller = ExplorerKeyboardController(view, SimpleNamespace(), state)
        seen = []
        controller._on_delete_shortcut = lambda *a, **k: seen.append("delete")
        controller._on_rename_shortcut = lambda *a, **k: seen.append("f2")
        target = QInputTarget(parent=app, key_handler=controller.handle_qt_key_event)
        self.assertTrue(target.setFocus())

        self.assertTrue(app.dispatchKeyEvent(QKeyEvent(QEvent.KeyPress, Qt.Key_Delete)))
        self.assertTrue(app.dispatchKeyEvent(QKeyEvent(QEvent.KeyPress, Qt.Key_F2)))
        self.assertEqual(seen, ["delete", "f2"])


if __name__ == "__main__":
    unittest.main()
