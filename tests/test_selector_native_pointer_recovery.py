"""Guard native press recovery; do not steal valid ImGui or popup input."""
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from DearUIQt.core.object import QPoint
from WinUx.dialogs.local_folder_form import LocalFolderDialog, FolderListView
from WinUx.ui.hosting.floating_runtime import FloatingDialogRuntime
from DearUIQt.qt.item_list import QtListView


class NativeRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.runtime = object.__new__(FloatingDialogRuntime)
        self.runtime.native = SimpleNamespace(hwnd=123, is_foreground=Mock(return_value=True))
        self.runtime.form = SimpleNamespace(winfo_exists=Mock(return_value=True),
                                            native_pointer_press=Mock(return_value=True))
        self.runtime._trace_browser_input = Mock()

    def press(self, mouse=(0., 0.), enabled=True):
        # The runtime recovers presses through the renderer-neutral QCursor
        # facade, so the pointer source is replaced at that boundary.
        with patch("WinUx.ui.hosting.floating_runtime.QCursor.pos",
                   return_value=QPoint(int(mouse[0]), int(mouse[1]))), \
                patch("ctypes.windll.user32.IsWindowEnabled", Mock(return_value=enabled)):
            self.runtime._browser_pointer_pressed("mouse-down", (250, 75))

    def test_unavailable_imgui_mouse_still_recovers_the_press(self):
        # QCursor falls back to QPoint(0, 0) when the renderer cannot report
        # the pointer; that unavailable-looking position is forwarded and the
        # form decides whether the press point is still a selector row.
        self.press()
        self.runtime.form.native_pointer_press.assert_called_once_with(QPoint(0, 0))

    def test_valid_imgui_mouse_is_not_replayed_even_if_it_moved(self):
        self.press(mouse=(260, 80))
        self.runtime.form.native_pointer_press.assert_not_called()

    def test_background_window_never_recovers_a_press(self):
        self.runtime.native.is_foreground.return_value = False
        self.press()
        self.runtime.form.native_pointer_press.assert_not_called()

    def test_disabled_window_never_recovers_a_press(self):
        self.press(enabled=False)
        self.runtime.form.native_pointer_press.assert_not_called()

    def test_closed_form_never_recovers_a_press(self):
        self.runtime.form.winfo_exists.return_value = False
        self.press()
        self.runtime.form.native_pointer_press.assert_not_called()


class BrowserRecoveryOwnershipTests(unittest.TestCase):
    def setUp(self):
        self.form = object.__new__(LocalFolderDialog)
        self.form.winfo_exists = Mock(return_value=True)
        self.form._folder_menu_is_open = Mock(return_value=False)
        self.form._folder_menu_action_pending = False
        self.form._rename_path = self.form._rename_after_load = None
        self.form.listbox = SimpleNamespace(_row_pointer_clicked=Mock(return_value=True))

    def press(self, modal=False, popup=False):
        application = SimpleNamespace(
            activePopupWidget=Mock(return_value=Mock() if popup else None),
            activeModalWidget=Mock(return_value=None),
        )
        with patch("DearUIQt.input_gate.native_background_input_blocked", return_value=modal), \
                patch("WinUx.dialogs.local_folder_form.QApplication.instance",
                      return_value=application), \
                patch("WinUx.dialogs.local_folder_form.QGuiRuntime",
                      return_value=SimpleNamespace(
                          hasActivePopupSurface=Mock(return_value=False))):
            return self.form.native_pointer_press((250, 75))

    def test_browser_rows_can_recover(self):
        self.assertTrue(self.press())
        self.form.listbox._row_pointer_clicked.assert_called_once_with(point=(250, 75))

    def test_nested_native_selector_blocks_recovery(self):
        self.assertFalse(self.press(modal=True))
        self.form.listbox._row_pointer_clicked.assert_not_called()

    def test_open_popup_blocks_recovery(self):
        self.assertFalse(self.press(popup=True))
        self.form.listbox._row_pointer_clicked.assert_not_called()

    def test_context_menu_blocks_recovery(self):
        self.form._folder_menu_is_open.return_value = True
        self.assertFalse(self.press())
        self.form.listbox._row_pointer_clicked.assert_not_called()

    def test_inline_rename_blocks_recovery(self):
        self.form._rename_path = "entry"
        self.assertFalse(self.press())
        self.form.listbox._row_pointer_clicked.assert_not_called()


class BrowserDoubleClickTests(unittest.TestCase):
    def test_inherited_imgui_double_flag_does_not_activate_new_selector_row(self):
        view = object.__new__(FolderListView)
        view._deleted = False
        view.items = {"entry": 100}
        view._values = [SimpleNamespace(key="entry", enabled=True)]
        view._last_click_frame = view._last_click_key = None
        view._last_click_at = 0.0
        view.doubleClicked, view.activated = Mock(), Mock()
        with patch.object(QtListView, "_clicked") as dispatch:
            view._clicked(100, True, "entry")
        dispatch.assert_called_once()
        self.assertFalse(view._is_double_click())
        view.doubleClicked.emit.assert_not_called()
        view.activated.emit.assert_not_called()


class MissingTableGeometryTests(unittest.TestCase):
    def test_missing_table_rect_uses_clipped_viewport_and_current_row(self):
        """A row outside the clipped dialog surface (or under no row) must not
        be activated even though the press lands somewhere inside the window.

        Real FolderListView instances hit-test through QWidget.globalGeometry
        plus per-item row geometry instead of raw renderer item rects.
        """
        view = object.__new__(FolderListView)
        view._deleted = False
        view.items = {"entry": 3}
        view.isVisible = Mock(return_value=True)
        view._clicked = Mock()

        class _FakeRect:
            def isEmpty(self):
                return False

            def contains(self, point):
                return point == (500, 75)

        class _FakeRowRect:
            def isEmpty(self):
                return False

            def top(self):
                return 70.0

            def height(self):
                return 24.0

            def left(self):
                return 208.0

        view.globalGeometry = Mock(return_value=_FakeRect())
        view.itemGeometry = Mock(return_value=_FakeRowRect())
        view.nativeItem = Mock(return_value=3)

        self.assertTrue(view._row_pointer_clicked(point=(500, 75)))
        self.assertFalse(view._row_pointer_clicked(point=(500, 450)))
        # The dialog viewport test is the clipped geometry, not the raw table.
        view.globalGeometry.assert_called_with(clipped=True)
        view.itemGeometry.assert_called_once_with("entry", include_check_indicator=False)
        view._clicked.assert_called_once_with(3, True, "entry")


if __name__ == "__main__":
    unittest.main()
