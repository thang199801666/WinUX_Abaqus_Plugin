"""Inline rename must use the painted canvas origin, not its scroll wrapper."""
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from WinUx.ui.components.explorer_rename import ExplorerRenameMixin
from WinUx.ui.components.explorer_rename_textbox import ExplorerRenameTextBox


class RenameEditorGeometryTests(unittest.TestCase):
    def view(self):
        return SimpleNamespace(
            _rename_active=False,
            items=[SimpleNamespace(name="Test-17-0285.inp", is_dir=False)] * 4,
            body_window="body", body_canvas="canvas",
            ROW_HEIGHT=28, RENAME_EDITOR_HEIGHT=20, CELL_PADDING=6,
            RENAME_TEXT_AND_CARET_COLOR=(0, 0, 0, 255),
            RENAME_SELECTION_COLOR=(0, 120, 215, 255),
            _fonts={"body": "font"},
            _column_geometry=Mock(return_value={"name": (0, 240)}),
            _body_viewport_rect=Mock(return_value=(20, 100, 320, 350)),
            _quiesce_pointer_for_inline_rename=Mock(),
            _install_native_cursor_hook=Mock(),
            _row_for_index=Mock(return_value={"texts": {"name": "label"}}),
            _rename_text_render_height=Mock(return_value=15),
            _rename_textbox=SimpleNamespace(begin=Mock(return_value=True)),
        )

    def test_editor_covers_painted_row_when_wrapper_origin_differs(self):
        view = self.view()
        with patch("WinUx.ui.components.explorer_rename.dpg") as backend:
            backend.get_x_scroll.return_value = 0
            backend.get_y_scroll.return_value = 0
            backend.get_item_rect_min.return_value = (12, 72)
            backend.get_text_size.return_value = (110, 16)
            self.assertTrue(ExplorerRenameMixin.begin_inline_rename(view, 2))
        request = view._rename_textbox.begin.call_args.kwargs
        self.assertEqual(request["left"], 35)
        self.assertEqual(request["top"], 132)
        self.assertEqual(request["source_text_tag"], "label")

    def test_canvas_scroll_offset_is_not_subtracted_twice(self):
        view = self.view()
        with patch("WinUx.ui.components.explorer_rename.dpg") as backend:
            backend.get_x_scroll.return_value = 8
            backend.get_y_scroll.return_value = 28
            backend.get_item_rect_min.return_value = (12, 72)
            backend.get_text_size.return_value = (110, 16)
            self.assertTrue(ExplorerRenameMixin.begin_inline_rename(view, 2))
        request = view._rename_textbox.begin.call_args.kwargs
        self.assertEqual(request["left"], 35)
        self.assertEqual(request["top"], 132)

    def test_geometry_fallback_works_before_canvas_is_available(self):
        view = self.view()
        with patch("WinUx.ui.components.explorer_rename.dpg") as backend:
            backend.get_x_scroll.return_value = 0
            backend.get_y_scroll.return_value = 28
            backend.get_item_rect_min.side_effect = RuntimeError("not rendered")
            backend.get_text_size.return_value = (110, 16)
            self.assertTrue(ExplorerRenameMixin.begin_inline_rename(view, 2))
        request = view._rename_textbox.begin.call_args.kwargs
        self.assertEqual(request["left"], 43)
        self.assertEqual(request["top"], 132)


class NativeRenameCoordinateTests(unittest.TestCase):
    def test_multi_viewport_screen_position_is_converted_once(self):
        import ctypes
        from ctypes import wintypes

        def screen_to_client(hwnd, point):
            position = ctypes.cast(point, ctypes.POINTER(wintypes.POINT)).contents
            position.x -= 269
            position.y -= 271
            return 1

        request = SimpleNamespace(left=360, top=425, native_hwnd=123)
        with patch("WinUx.ui.components.explorer_rename_textbox.NativeWindowBackend") as native, \
                patch("WinUx.ui.components.explorer_rename_textbox.os", SimpleNamespace(name="nt")), \
                patch.object(ctypes, "windll", create=True) as windll:
            native.return_value.isEnabled.return_value = True
            windll.user32.ScreenToClient.side_effect = screen_to_client
            self.assertEqual(ExplorerRenameTextBox._native_position(request), (91, 154))
            windll.user32.ScreenToClient.assert_called_once()
            # NativeRenameEditor's ClientToScreen restores the painted position.
            self.assertEqual((91 + 269, 154 + 271), (360, 425))

    def test_legacy_renderer_keeps_client_coordinates(self):
        request = SimpleNamespace(left=91, top=154, native_hwnd=123)
        with patch("WinUx.ui.components.explorer_rename_textbox.NativeWindowBackend") as native:
            native.return_value.isEnabled.return_value = False
            self.assertEqual(ExplorerRenameTextBox._native_position(request), (91, 154))


if __name__ == "__main__":
    unittest.main()
