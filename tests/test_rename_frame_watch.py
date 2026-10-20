"""Rename must be pumped by a drawable with a supported visible handler."""
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch, call

from WinUx.ui.components.explorer_layout import ExplorerLayoutMixin
from WinUx.ui.components.explorer_rename import ExplorerRenameMixin


class RenameFrameWatchTests(unittest.TestCase):
    def test_watch_uses_canvas_without_replacing_body_geometry_binding(self):
        geometry_binding = object()
        view = SimpleNamespace(body_window="body", body_canvas="canvas",
                               _rename_active=False, _pending_slow_rename=None,
                               _process_inline_rename_focus=Mock(),
                               _process_pending_slow_rename=Mock(),
                               _auto_width_geometry_registries=[geometry_binding])
        with patch("WinUx.ui.components.explorer_layout.QItemInputBinding") as binding:
            active = binding.return_value.onVisible.return_value.activate.return_value
            ExplorerLayoutMixin._install_layout_watch(view)
            self.assertEqual(binding.call_args_list, [call("body"), call("canvas")])
            self.assertEqual(view._auto_width_geometry_registries,
                             [geometry_binding, active, active])
            rename_watch = binding.return_value.onVisible.call_args_list[-1].args[0]
            rename_watch()
            view._process_inline_rename_focus.assert_not_called()
            view._process_pending_slow_rename.assert_not_called()
            view._rename_active = True
            rename_watch()
            view._process_inline_rename_focus.assert_called_once_with()

    def test_frame_pump_dispatches_commit_and_cancel(self):
        view = SimpleNamespace(
            _rename_active=True,
            _rename_textbox=SimpleNamespace(pump=Mock(side_effect=["commit", "cancel", None])),
            commit_inline_rename=Mock(), cancel_inline_rename=Mock())
        for _ in range(3):
            ExplorerRenameMixin._process_inline_rename_focus(view)
        view.commit_inline_rename.assert_called_once_with()
        view.cancel_inline_rename.assert_called_once_with()
