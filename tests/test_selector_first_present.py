"""Deferred construction must not drop a selector's initial directory load."""
from types import SimpleNamespace
import unittest
from unittest.mock import Mock

from DearUIQt.dialogs.qt_dialog import QtDialog


class FirstPresentTests(unittest.TestCase):
    def dialog(self):
        return SimpleNamespace(
            winfo_exists=Mock(return_value=True), isVisible=Mock(return_value=False),
            isConstructing=Mock(return_value=True), _initial_visibility_requested=True,
            view=SimpleNamespace(after_render=Mock()),
        )

    def test_first_hidden_frame_retries_directory_loading_after_construction(self):
        dialog = self.dialog()
        load = Mock()
        QtDialog.after_first_present(dialog, load)
        first = dialog.view.after_render.call_args.args[0]
        first()
        load.assert_not_called()
        self.assertEqual(dialog.view.after_render.call_count, 2)
        dialog.isConstructing.return_value = False
        dialog.isVisible.return_value = True
        dialog.view.after_render.call_args.args[0]()
        load.assert_called_once()

    def test_closed_selector_does_not_load_or_reschedule(self):
        dialog = self.dialog()
        load = Mock()
        QtDialog.after_first_present(dialog, load)
        dialog.winfo_exists.return_value = False
        dialog.view.after_render.call_args.args[0]()
        load.assert_not_called()
        self.assertEqual(dialog.view.after_render.call_count, 1)

    def test_intentionally_hidden_finished_dialog_does_not_spin(self):
        dialog = self.dialog()
        dialog.isConstructing.return_value = False
        load = Mock()
        QtDialog.after_first_present(dialog, load)
        dialog.view.after_render.call_args.args[0]()
        load.assert_not_called()
        self.assertEqual(dialog.view.after_render.call_count, 1)


if __name__ == "__main__":
    unittest.main()
