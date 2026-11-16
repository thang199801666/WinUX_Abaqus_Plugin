"""Dialog/popup activation stability regressions for Windows native viewports."""
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from DearUIQt.widgets.menu import QMenu
from DearUIQt.backends.native_windows import NativeWindowBackend


class PopupActivationTests(unittest.TestCase):
    def test_qmenu_popup_does_not_focus_renderer_window(self):
        backend = Mock()
        backend.get_frame_count.return_value = 7
        backend.is_mouse_button_down.return_value = False
        menu = SimpleNamespace(
            _context=None,
            _popup_global_position=False,
            _parent_window=123,
            _parent_menu=None,
            aboutToShow=Mock(),
            _popup_position_resolver=None,
            tag=456,
            backend=backend,
            _min_width=120,
            _popup_input_owned=True,
            _opened_frame=-1,
            _opening_release_frame=-1,
            _opening_pointer_buttons=set(),
            _visible_action_ids=lambda: ['one'],
            _set_active_action=Mock(),
            _native_popup_geometry=None,
            _native_popup_pending=None,
            _last_popup_geometry=None,
            _refresh_popup_position=Mock(),
            threadId=lambda: 1,
        )
        # This lightweight namespace has no QObject/weak-reference lifetime;
        # popup tracking is covered separately with real weak-reference owners.
        with patch('DearUIQt.core.application.QApplication.instance', return_value=None), \
                patch('DearUIQt.gui.popup_tracking.track_popup'):
            self.assertTrue(QMenu.popup(menu, position=(10, 20)))
        backend.configure_item.assert_called_once_with(456, show=True)
        backend.focus_item.assert_not_called()
        menu._set_active_action.assert_called_once_with('one')

    def test_native_popup_style_declares_noactivate(self):
        source = (ROOT / 'DearUIQt' / 'backends' / 'native_windows.py').read_text()
        block = source[source.index('def positionPopup'):source.index('def centerBeforeShow')]
        self.assertIn('WS_EX_NOACTIVATE = 0x08000000', block)
        self.assertIn('WS_EX_TOOLWINDOW | WS_EX_NOACTIVATE', block)
        self.assertIn('NOACTIVATE | FRAMECHANGED', block)


class DialogCaptionStabilityTests(unittest.TestCase):
    def test_dialog_guard_repairs_only_when_native_invariant_breaks(self):
        source = (ROOT / 'DearUIQt' / 'dialogs' / 'qt_dialog.py').read_text()
        block = source[source.index('def _guard_native_modal_owner_visibility'):
                       source.index('def _synchronize_native_owner_once')]
        self.assertIn('foreground != dialog_hwnd', block)
        self.assertIn('ownerPresentationNeedsRepair', block)
        self.assertIn('and needs_repair(owner_hwnd, dialog_hwnd))', block)
        self.assertEqual(block.count('self._recover_native_owner_presentation()'), 1)

    def test_dialog_guard_backs_off_to_timer_when_stable(self):
        source = (ROOT / 'DearUIQt' / 'dialogs' / 'qt_dialog.py').read_text()
        block = source[source.index('def _guard_native_modal_owner_visibility'):
                       source.index('def _synchronize_native_owner_once')]
        self.assertIn('stable = True', block)
        self.assertIn('if not stable:', block)
        # Stable native owner/dialog pairs must stop polling completely; the
        # old 120 ms timer could reset USER32 non-client hot tracking and make
        # the caption Close button flash while the pointer was stationary.
        self.assertNotIn('schedule(120, self._guard_native_modal_owner_visibility,', block)
        self.assertIn('Once stable, STOP polling completely', block)

    def test_native_backend_exposes_stability_predicate(self):
        self.assertTrue(hasattr(NativeWindowBackend, 'ownerPresentationNeedsRepair'))


if __name__ == '__main__':
    unittest.main(verbosity=2)
