"""In-process file/folder selectors retain their launching tool as owner."""
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import run_winux
run_winux._configure_bundled_dependencies(str(ROOT))
from DearUIQt.core import QObject
from DearUIQt.dialogs.qt_dialog import QtDialog
from WinUx.ui.file_dialog import FileSelector
from WinUx.ui.hosting.inprocess_dialog import register_inprocess_dialog, close_inprocess_dialogs


class SelectorExplicitOwnerTests(unittest.TestCase):
    def test_parent_first_present_cannot_activate_over_a_new_modal(self):
        backend = Mock()
        dialog = SimpleNamespace(_native_window_backend=backend,
                                 winfo_exists=lambda: True, isVisible=lambda: True)
        app = SimpleNamespace(activeModalWidget=lambda: object())
        with patch('DearUIQt.core.application.QApplication.instance', return_value=app):
            self.assertFalse(QtDialog._activate_native_modal_once(dialog))
        backend.activateOwnedWindow.assert_not_called()

    def test_file_and_folder_facades_forward_the_visual_parent(self):
        for directory, constructor in ((False, 'LocalFileDialog'), (True, 'LocalFolderDialog')):
            with self.subTest(directory=directory):
                parent = SimpleNamespace(own_dialog=Mock())
                form = SimpleNamespace(tag=42, center=Mock())
                selector = FileSelector(view=SimpleNamespace(), parent=parent,
                                        directory=directory, accepted=Mock())
                with patch('WinUx.dialogs.inprocess_adapters.' + constructor, return_value=form) as create:
                    self.assertEqual(selector.open(), 42)
                self.assertIs(create.call_args.kwargs['parent'], parent)

    def test_registration_does_not_reparent_explicitly_owned_dialog(self):
        view = SimpleNamespace()
        parent = QObject()
        dialog = QObject(parent=parent)
        dialog._requested_parent = parent
        register_inprocess_dialog(view, dialog)
        self.assertIs(dialog.parent, parent)
        self.assertIn(dialog, view._inprocess_dialogs)
        self.assertFalse(hasattr(view, '_inprocess_dialog_owner'))
        parent.delete()

    def test_unowned_dialog_still_uses_application_lifetime_root(self):
        view = SimpleNamespace()
        dialog = QObject()
        register_inprocess_dialog(view, dialog)
        self.assertIs(dialog.parent, view._inprocess_dialog_owner)
        view._inprocess_dialog_owner.delete()

    def test_explicitly_owned_dialog_still_participates_in_shutdown(self):
        view = SimpleNamespace()
        parent = QObject()
        dialog = QObject(parent=parent)
        dialog._requested_parent = parent
        dialog.hard_destroy = Mock(side_effect=dialog.delete)
        register_inprocess_dialog(view, dialog)
        close_inprocess_dialogs(view)
        dialog.hard_destroy.assert_called_once_with()
        self.assertTrue(dialog._deleted)
        self.assertFalse(view._inprocess_dialogs)
        parent.delete()


if __name__ == '__main__':
    unittest.main()
