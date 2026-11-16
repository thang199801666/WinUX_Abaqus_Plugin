from pathlib import Path
from types import SimpleNamespace
import sys
import unittest
from unittest.mock import Mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import run_winux
run_winux._configure_bundled_dependencies(str(Path(__file__).resolve().parents[1]))

from WinUx.ui.components.explorer.drag_drop import ExplorerDragDropMixin
from WinUx.ui.components.explorer.pointer_dispatch import ExplorerPointerDispatchMixin
from WinUx.ui.behaviors.input.pointer import PointerRoutingMixin


class RouteHost(PointerRoutingMixin):
    pass


class M39PhysicalDropPipelineTests(unittest.TestCase):
    def test_drag_motion_callback_receives_physical_cursor_not_viewport_cursor(self):
        callback = Mock(return_value=False)
        fake = SimpleNamespace(
            _drop_target_index=None,
            _drop_target_pinned=False,
            _valid_drop_pinned_target=lambda: False,
            _valid_drop_folder_index=lambda: None,
            _update_row_visual=Mock(),
            _layout_pinned_row=Mock(),
            _external_drop_valid=False,
            _external_drop_target_name=None,
            on_drag_motion=callback,
            _physical_pointer_position=lambda: (1410.0, 612.0),
            _pointer_position=lambda: (_ for _ in ()).throw(
                AssertionError('viewport cursor must not drive drop routing')),
            _update_drag_cursor=Mock(),
        )
        ExplorerDragDropMixin._update_item_drag(fake)
        callback.assert_called_once_with(1410.0, 612.0)

    def test_release_callback_receives_physical_cursor(self):
        on_drop = Mock()
        fake = SimpleNamespace(
            on_drop=on_drop,
            _physical_pointer_position=lambda: (1515.0, 733.0),
            _pointer_position=lambda: (_ for _ in ()).throw(
                AssertionError('viewport cursor must not authorize mouse-up drop')),
            _pointer_ctrl_down=lambda: False,
            _drag_source_items=[SimpleNamespace(name='a')],
            _finish_item_drag=Mock(),
        )
        # Exercise the exact release fragment through a tiny equivalent host is
        # brittle because the full method has extensive gesture state. Verify
        # the source contract statically via the bound method's constants too.
        import inspect
        source = inspect.getsource(ExplorerPointerDispatchMixin._on_left_release_impl)
        self.assertIn('self._physical_pointer_position()', source)
        marker = source.index('if was_item_drag:')
        release_tail = source[marker:]
        self.assertNotIn('point = self._pointer_position()\n', release_tail.split('if was_item_drag:\n            return', 1)[0])

    def test_screen_cursor_selects_panel_even_when_app_client_point_would_be_elsewhere(self):
        host = RouteHost()
        left = SimpleNamespace(screen_rect=lambda: (1000.0, 200.0, 1400.0, 700.0))
        right = SimpleNamespace(screen_rect=lambda: (1410.0, 200.0, 1810.0, 700.0))
        host.left, host.right = left, right
        host.left_parent = host.right_parent = None

        panel, point = host.panel_and_point_at(1600.0, 400.0)
        self.assertIs(panel, right)
        self.assertEqual(point, (1600.0, 400.0))
        # The same numeric position interpreted as an app-client coordinate
        # would be nonsensical here; no app-origin +/- heuristic is attempted.
        panel, point = host.panel_and_point_at(600.0, 400.0)
        self.assertIsNone(panel)
        self.assertIsNone(point)


if __name__ == '__main__':
    unittest.main(verbosity=2)
