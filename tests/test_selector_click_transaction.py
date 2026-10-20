"""A delayed release callback must not undo the Qt selector press target."""
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from WinUx.dialogs.local_folder_form import FolderListView
from DearUIQt.modelview import QtListView


class SelectorClickTransactionTests(unittest.TestCase):
    def listbox(self):
        return SimpleNamespace(
            _deleted=False, items={"Beta": 2, "Alpha": 1},
            _values=[SimpleNamespace(key="Beta", enabled=True),
                     SimpleNamespace(key="Alpha", enabled=True)],
            _last_click_frame=(2, 1), _qt_bridge_click=("Beta", 1, 0.),
            backend=SimpleNamespace(mvKey_Spacebar=32, mvKey_Return=13,
                                    is_key_down=Mock(return_value=False)),
        )

    def test_release_after_many_frames_does_not_count_as_second_click(self):
        view = self.listbox()
        with patch("WinUx.dialogs.local_folder_form.QApplication") as app:
            app.instance.return_value.frameCount.return_value = 100
            FolderListView._clicked(view, 2, False, "Beta")
        # A duplicate must not advance the last physical-click history at all.
        self.assertEqual(view._last_click_frame, (2, 1))
        self.assertEqual(view._qt_bridge_click, ("Beta", 1, 0.))

    def test_late_notification_from_first_row_cannot_override_pressed_row(self):
        view = self.listbox()
        with patch("WinUx.dialogs.local_folder_form.QApplication") as app:
            app.instance.return_value.frameCount.return_value = 100
            FolderListView._clicked(view, 1, True, "Alpha")
        self.assertEqual(view._last_click_frame, (2, 1))

    def test_keyboard_activation_is_not_swallowed_by_old_pointer_transaction(self):
        # Use a real instance without native construction so super() keeps its
        # ordinary dispatch, while substituting only the renderer-facing method.
        view = object.__new__(FolderListView)
        view.__dict__.update(self.listbox().__dict__)
        view._last_click_key, view._last_click_at = None, 0.
        view._double_click_interval = .5
        view.backend.is_key_down.return_value = True
        with patch("WinUx.dialogs.local_folder_form.QApplication") as app, \
                patch.object(QtListView, "_clicked") as clicked:
            app.instance.return_value.frameCount.return_value = 100
            FolderListView._clicked(view, 2, True, "Beta")
        clicked.assert_called_once_with(2, True, "Beta")
        self.assertIsNone(view._qt_bridge_click)


if __name__ == "__main__":
    unittest.main()
