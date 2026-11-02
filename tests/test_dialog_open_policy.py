"""Native dialog opening policy: abaqus python tests/test_dialog_open_policy.py."""
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import run_winux
run_winux._configure_bundled_dependencies(str(ROOT))

from DearUIQt.dialogs.qt_dialog import QtDialog
from DearUIQt.backends import native_windows as windows


class DialogOpeningTests(unittest.TestCase):
    def dialog(self, modal=True, activated=True):
        backend = Mock()
        backend.activateOwnedWindow.return_value = activated
        backend.preserveFirstClientClick.return_value = True
        dialog = SimpleNamespace(
            tag=20, modal=modal, _native_window_backend=backend,
            _native_owner_open_lease=object(), _native_modality_armed=False,
            _native_presentation_pending=True, winfo_exists=lambda: True,
            isVisible=lambda: True, view=SimpleNamespace(after_render=Mock()),
            _prepare_native_first_click_once=Mock(),
            _recover_native_owner_presentation=Mock(),
            _apply_initial_focus_if_idle=Mock())
        dialog._arm_native_modality = lambda value: QtDialog._arm_native_modality(dialog, value)
        dialog._activate_native_modal_once = lambda *args: QtDialog._activate_native_modal_once(dialog, *args)
        return dialog, backend

    def test_refused_activation_does_not_disable_foreground_owner(self):
        dialog, backend = self.dialog(activated=False)
        QtDialog._native_first_present_ready(dialog)
        backend.activateOwnedWindow.assert_called_once()
        backend.setModal.assert_not_called()
        self.assertFalse(dialog._native_modality_armed)

    def test_missing_hwnd_defers_owner_disable(self):
        dialog, backend = self.dialog(activated=None)
        QtDialog._native_first_present_ready(dialog)
        backend.setModal.assert_not_called()
        dialog.view.after_render.assert_called_once()

    def test_successful_activation_arms_modality_once(self):
        dialog, backend = self.dialog()
        QtDialog._native_first_present_ready(dialog)
        dialog._activate_native_modal_once()
        backend.setModal.assert_called_once_with(20, True)

    def test_later_activation_can_complete_refused_handoff(self):
        dialog, backend = self.dialog(activated=False)
        QtDialog._native_first_present_ready(dialog)
        backend.activateOwnedWindow.return_value = True
        dialog._activate_native_modal_once()
        backend.setModal.assert_called_once_with(20, True)

    def test_modeless_open_explicitly_activates_without_disabling_owner(self):
        dialog, backend = self.dialog(modal=False)
        QtDialog._native_first_present_ready(dialog)
        backend.activateOwnedWindow.assert_called_once_with(
            20, opening=dialog._native_owner_open_lease)
        backend.setModal.assert_not_called()


class OwnerPresentationTests(unittest.TestCase):
    def setUp(self):
        self.api = SimpleNamespace(**{name: Mock(return_value=True) for name in (
            'IsWindow', 'IsWindowVisible', 'ShowWindow', 'SetWindowPos', 'SetForegroundWindow')})
        self.api.IsIconic = Mock(return_value=False)
        self.api.GetForegroundWindow = Mock(return_value=20)
        self.order = {20: 30, 30: 10, 10: 0}
        self.api.GetWindow = Mock(side_effect=lambda hwnd, mode: self.order.get(hwnd.value, 0))
        self.native = windows.NativeWindowBackend(SimpleNamespace())
        for mocked in (
                patch.object(windows, '_windows_user32', return_value=self.api),
                patch('ctypes.windll.dwmapi.DwmGetWindowAttribute', return_value=0)):
            mocked.start()
            self.addCleanup(mocked.stop)

    def test_obscured_owner_is_raised_without_activation(self):
        self.assertTrue(self.native.preserveOwnerPresentation(10, 20))
        args = self.api.SetWindowPos.call_args.args
        self.assertEqual((args[0].value, args[1].value, args[-1]), (10, 20, 0x13))
        self.api.SetForegroundWindow.assert_not_called()

    def test_foreign_thread_repair_is_asynchronous_and_nonactivating(self):
        self.assertTrue(self.native.preserveOwnerPresentation(10, 20, asynchronous=True))
        self.assertEqual(self.api.SetWindowPos.call_args.args[-1], 0x4013)
        self.api.SetForegroundWindow.assert_not_called()

    def test_correct_stack_does_not_reorder_each_frame(self):
        self.order[20] = 10
        self.assertTrue(self.native.preserveOwnerPresentation(10, 20))
        self.api.SetWindowPos.assert_not_called()

    def test_same_process_sibling_between_dialog_and_owner_is_not_reordered(self):
        # A retained WinUx sibling (Plots/Transfer Center/etc.) may legitimately
        # sit between a modal dialog and the primary HWND. Reordering the owner
        # across that sibling causes a visible one-frame flash.
        self.order = {20: 30, 30: 10, 10: 0}
        with patch.object(windows, '_window_process_id', return_value=4242):
            self.assertTrue(self.native.preserveOwnerPresentation(10, 20))
        self.api.SetWindowPos.assert_not_called()

    def test_foreign_window_between_dialog_and_owner_is_still_repaired(self):
        self.order = {20: 30, 30: 10, 10: 0}
        pids = {10: 4242, 20: 4242, 30: 9999}
        with patch.object(windows, '_window_process_id', side_effect=lambda _api, hwnd: pids.get(int(hwnd), 0)):
            self.assertTrue(self.native.preserveOwnerPresentation(10, 20))
        args = self.api.SetWindowPos.call_args.args
        self.assertEqual((args[0].value, args[1].value, args[-1]), (10, 20, 0x13))

    def test_process_host_uses_same_noop_policy_for_correct_stack(self):
        from WinUx.ui.native.native_dialog_host import prepare_owned_dialog_stack
        self.order[20] = 10
        with patch('ctypes.windll.user32.IsWindowVisible', return_value=True):
            self.assertTrue(prepare_owned_dialog_stack(10, 20))
            self.assertTrue(prepare_owned_dialog_stack(10, 20))
        self.api.SetWindowPos.assert_not_called()
        self.api.SetForegroundWindow.assert_not_called()

    def test_alt_tab_does_not_raise_or_reveal_owner(self):
        self.api.GetForegroundWindow.return_value = 99
        self.assertFalse(self.native.preserveOwnerPresentation(10, 20))
        self.api.SetWindowPos.assert_not_called()
        self.api.ShowWindow.assert_not_called()
        self.api.SetForegroundWindow.assert_not_called()

    def test_minimized_owner_is_not_restored(self):
        self.api.IsIconic.return_value = True
        self.assertFalse(self.native.preserveOwnerPresentation(10, 20))
        self.api.ShowWindow.assert_not_called()
        self.api.SetWindowPos.assert_not_called()

    def test_previously_hidden_owner_is_not_revealed(self):
        self.assertFalse(self.native.preserveOwnerPresentation(10, 20, was_visible=False))
        self.api.ShowWindow.assert_not_called()

    def test_provisional_dialog_never_lowers_owner(self):
        self.order = {20: 30, 30: 0}
        self.assertTrue(self.native.preserveOwnerPresentation(10, 20))
        self.api.SetWindowPos.assert_not_called()


class PopupPresentationBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.presentation = Mock()
        self.presentation.retiring_windows.return_value = (20, 30)
        self.dialog = SimpleNamespace(
            _native_window_backend=Mock(), view=SimpleNamespace(),
            _closed=False, winfo_exists=lambda: True, _show_now=Mock())
        mocked = patch('DearUIQt.backends.native_presentation.presentation_for', return_value=self.presentation)
        mocked.start()
        self.addCleanup(mocked.stop)

    def test_every_native_dialog_waits_for_popup_teardown(self):
        self.assertTrue(QtDialog._wait_for_native_popup_teardown(self.dialog))
        self.assertTrue(QtDialog._wait_for_native_popup_teardown(self.dialog))
        self.presentation.after_windows_hidden.assert_called_once()
        self.dialog._show_now.assert_not_called()
        handles, show = self.presentation.after_windows_hidden.call_args.args
        self.assertEqual(handles, (20, 30))
        show()
        self.dialog._show_now.assert_called_once()

    def test_hide_cancels_pending_native_show(self):
        QtDialog._wait_for_native_popup_teardown(self.dialog)
        self.dialog._native_show_wait_token = None  # hide()/destroy() invalidates it.
        self.presentation.after_windows_hidden.call_args.args[1]()
        self.dialog._show_now.assert_not_called()

    def test_no_popup_keeps_normal_show_synchronous(self):
        self.presentation.retiring_windows.return_value = ()
        self.assertFalse(QtDialog._wait_for_native_popup_teardown(self.dialog))
        self.presentation.after_windows_hidden.assert_not_called()


if __name__ == '__main__':
    unittest.main(verbosity=2)
