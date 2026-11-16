"""Regression tests for the WinUXView composition boundary."""
from __future__ import annotations

import unittest
from unittest.mock import patch

from WinUx.ui.main_window import WinUXView
from WinUx.ui.behaviors.window import (
    ApplicationMenuMixin,
    DialogFacadeMixin,
    StartupDockingMixin,
)
from WinUx.ui.behaviors.window import dialog_facade, startup_docking


class ViewCompositionTests(unittest.TestCase):
    def test_window_facades_are_inherited_from_feature_mixins(self):
        self.assertIs(WinUXView._build_menu, ApplicationMenuMixin._build_menu)
        self.assertIs(WinUXView.show_login, DialogFacadeMixin.show_login)
        self.assertIs(
            WinUXView._finish_deferred_startup,
            StartupDockingMixin._finish_deferred_startup,
        )
        self.assertIs(
            WinUXView._install_console_character_hook,
            StartupDockingMixin._install_console_character_hook,
        )

    def test_dialog_constructor_resolution_preserves_main_window_patch_point(self):
        marker = object()
        with patch("WinUx.ui.main_window._dialog_type", return_value=marker) as resolver:
            self.assertIs(dialog_facade._resolve_dialog_type("LoginDialog"), marker)
        resolver.assert_called_once_with("LoginDialog")

    def test_dialog_process_policy_preserves_main_window_patch_point(self):
        with patch("WinUx.ui.main_window._use_inprocess_dialogs", return_value=False) as resolver:
            self.assertFalse(dialog_facade._inprocess_dialogs_enabled())
        resolver.assert_called_once_with()

    def test_native_ctypes_patch_point_stays_on_main_window_module(self):
        marker = object()
        with patch("WinUx.ui.main_window.ctypes", marker):
            self.assertIs(startup_docking._view_ctypes(), marker)


if __name__ == "__main__":
    unittest.main(verbosity=2)
