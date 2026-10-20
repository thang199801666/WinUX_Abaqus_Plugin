"""Starting a native rename must not strand either application mouse grab."""
import unittest
from unittest.mock import Mock

from DearUIQt.core import QInputTarget
from DearUIQt.core.application import QApplication
from DearUIQt.input_gate import acquire_pointer_input, release_pointer_input
from WinUx.ui.components.explorer_rename import ExplorerRenameMixin
from WinUx.ui.components.explorer_pointer_capture import ExplorerPointerCaptureMixin


class RenameView(ExplorerRenameMixin, ExplorerPointerCaptureMixin):
    pass


class RenamePointerReleaseTests(unittest.TestCase):
    def test_native_editor_takes_over_without_stranding_list_capture(self):
        app = QApplication(after=lambda *args: None)
        view = RenameView()
        target = QInputTarget(parent=app)
        view._qt_input_target = target
        view._pointer_input_owned = False
        view._mouse_down = True
        view._rename_schedule_serial = 0
        for name in ("_hide_rubber_rect", "_set_separator_hover_state",
                     "_update_row_visual", "_set_mouse_cursor", "_clear_hover"):
            setattr(view, name, Mock())
        other_pane = object()
        try:
            self.assertTrue(view._claim_pointer_gesture())
            self.assertTrue(app.setMouseGrabberObject(target))
            self.assertFalse(acquire_pointer_input(other_pane))
            view._quiesce_pointer_for_inline_rename()
            self.assertFalse(view._pointer_input_owned)
            self.assertIsNone(app.mouseGrabberObject())
            self.assertTrue(acquire_pointer_input(other_pane))
            self.assertTrue(view._suppress_next_left_release)
        finally:
            release_pointer_input(other_pane)
            release_pointer_input(view)
            app.delete()
