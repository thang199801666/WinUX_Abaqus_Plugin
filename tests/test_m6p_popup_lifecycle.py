"""M6p retained popup lifecycle regressions."""
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from DearUIQt.widgets.menu import QMenu


class PopupLifecycleTests(unittest.TestCase):
    def menu(self):
        backend = Mock()
        backend.configure_item = Mock()
        menu = SimpleNamespace(
            tag=42,
            backend=backend,
            _popup_open=True,
            _popup_global_position=False,
            _parent_window=None,
            _parent_menu=None,
            _popup_input_owned=False,
            _context="ctx",
            _submenus={},
            _popup_position_resolver=object(),
            _last_popup_geometry=(1, 2, 3, 4),
            _native_popup_pending=((1, 2), (3, 4)),
            _native_popup_geometry=((1, 2), (3, 4)),
            aboutToHide=Mock(),
            _hide_open_submenu=Mock(),
            isVisible=lambda: True,
        )
        return menu

    def test_hide_is_idempotent_and_emits_once(self):
        menu = self.menu()
        with patch('DearUIQt.gui.popup_tracking.untrack_popup'), \
             patch('DearUIQt.backends.native_presentation.presentation_for', return_value=None), \
             patch('DearUIQt.core.application.QApplication.instance', return_value=None):
            self.assertTrue(QMenu.hide(menu))
            self.assertTrue(QMenu.hide(menu))
        menu.backend.configure_item.assert_called_once_with(42, show=False)
        menu.aboutToHide.emit.assert_called_once_with('ctx')

    def test_second_hide_does_not_restart_native_owner_close(self):
        menu = self.menu()
        menu._popup_global_position = True
        native = Mock()
        native.isEnabled.return_value = True
        with patch('DearUIQt.gui.popup_tracking.untrack_popup'), \
             patch('DearUIQt.backends.native_windows.NativeWindowBackend', return_value=native), \
             patch('DearUIQt.backends.native_presentation.presentation_for', return_value=None), \
             patch('DearUIQt.core.application.QApplication.instance', return_value=None):
            QMenu.hide(menu)
            QMenu.hide(menu)
        native.beginOwnerClose.assert_called_once_with(42)


if __name__ == '__main__':
    unittest.main(verbosity=2)
