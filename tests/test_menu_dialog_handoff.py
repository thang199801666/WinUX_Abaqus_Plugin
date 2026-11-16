"""Menu-to-dialog handoff policy: abaqus python tests/test_menu_dialog_handoff.py."""
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import run_winux
run_winux._configure_bundled_dependencies(str(ROOT))

from DearUIQt.widgets.menu import QMenu
from DearUIQt.backends.native_presentation import NativePresentation
from WinUx.runtime.operation_context import OperationContext


class MenuHandoffTests(unittest.TestCase):
    def test_menu_hides_before_emitting_plain_command(self):
        events = []
        context = {'index': 0}
        root = SimpleNamespace(
            _context=context,
            _deleted=False, _popup_global_position=False,
            hide=lambda **kwargs: events.append('hide'),
            triggered=SimpleNamespace(emit=lambda *args: events.append(args)))
        menu = SimpleNamespace(
            _row_specs={'edit': {'action': 'edit'}}, _root_menu=lambda: root)
        QMenu._row_clicked(menu, user_data='edit')
        self.assertEqual(events, ['hide', ('edit', context)])

    def hide_menu(self, fail_native=False):
        events = []
        native = Mock()
        native.isEnabled.return_value = True

        def handoff(*args):
            events.append('handoff')
            if fail_native:
                raise RuntimeError('Native window was already destroyed')

        native.beginOwnerClose.side_effect = handoff
        menu = SimpleNamespace(
            tag=20, backend=Mock(), _submenus={}, _parent_menu=None,
            _parent_window=None, _popup_global_position=True,
            _popup_input_owned=False, _context=None, aboutToHide=Mock(),
            _hide_open_submenu=Mock(), isVisible=lambda: True)
        menu.backend.configure_item.side_effect = lambda *a, **k: events.append('hide')
        with patch('DearUIQt.gui.popup_tracking.untrack_popup'), \
                patch('DearUIQt.backends.native_windows.NativeWindowBackend', return_value=native), \
                patch('DearUIQt.backends.native_presentation.presentation_for', return_value=None), \
                patch('DearUIQt.core.application.QApplication.instance', return_value=None):
            self.assertTrue(QMenu.hide(menu))
        menu.backend.configure_item.assert_called_once_with(20, show=False)
        return events

    def test_native_owner_handoff_precedes_popup_hide(self):
        self.assertEqual(self.hide_menu(), ['handoff', 'hide'])

    def test_failed_native_handoff_does_not_strand_popup(self):
        self.assertEqual(self.hide_menu(fail_native=True), ['handoff', 'hide'])

    def test_native_command_waits_for_entire_menu_stack(self):
        presentation = NativePresentation(SimpleNamespace())
        callback = Mock()
        presentation.after_windows_hidden((20, 30), callback)
        visible = {30}
        with patch('ctypes.windll.user32.IsWindowVisible',
                   side_effect=lambda handle: handle.value in visible):
            presentation._deliver_after_hidden()
            callback.assert_not_called()
            visible.clear()
            presentation._deliver_after_hidden()
            callback.assert_called_once()
            presentation._deliver_after_hidden()
            callback.assert_called_once()

    def test_dialog_replacement_uses_same_teardown_boundary_as_menu(self):
        presentation = NativePresentation(SimpleNamespace())
        presentation.native._rawWinId = Mock(return_value=20)
        presentation.native.isPrimaryItem = Mock(return_value=False)
        presentation.cancel(1)
        with patch('ctypes.windll.user32.IsWindowVisible', return_value=True):
            self.assertEqual(presentation.retiring_windows(), (20,))


class RenderDeliveryTests(unittest.TestCase):
    def setUp(self):
        self.queued = []
        self.view = SimpleNamespace(
            after=Mock(), winfo_exists=lambda: True,
            after_render=lambda *args: self.queued.append(args))
        self.app = SimpleNamespace(_closing=False, _connection_generation=1, view=self.view)
        self.context = OperationContext(self.app, remote=True)
        self.callback = Mock()

    def deliver(self):
        callback, *args = self.queued.pop()
        callback(*args)

    def test_dialog_waits_for_render_not_same_turn_timer(self):
        self.context.post_after_render(self.callback, 'edit', ('123',))
        self.callback.assert_not_called()
        self.view.after.assert_not_called()
        self.deliver()
        self.callback.assert_called_once_with('edit', ('123',))

    def test_disconnect_cancels_queued_command(self):
        self.context.post_after_render(self.callback)
        self.app._connection_generation += 1
        self.deliver()
        self.callback.assert_not_called()

    def test_shutdown_cancels_queued_command(self):
        self.context.post_after_render(self.callback)
        self.app._closing = True
        self.deliver()
        self.callback.assert_not_called()


if __name__ == '__main__':
    unittest.main(verbosity=2)
