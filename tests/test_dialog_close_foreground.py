"""abaqus python -m unittest discover -s tests -p test_dialog_close_foreground.py"""
import os
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from DearUIQt.backends import native_windows as windows


class DialogCloseForegroundTests(unittest.TestCase):
    def setUp(self):
        self.foreground = 99
        self.tick = 123
        self.api = SimpleNamespace(**{name: Mock(return_value=True) for name in (
            'IsWindowEnabled', 'EnableWindow', 'BringWindowToTop',
            'SetActiveWindow', 'SetFocus')})
        self.api.GetForegroundWindow = Mock(side_effect=lambda: self.foreground)
        self.api.SetForegroundWindow = Mock(side_effect=self.activate)
        self.native = windows.NativeWindowBackend(object())
        self.native._interaction_hwnd = 20
        self.native._interaction_open_lease = windows._OwnerOpenLease(10, self.tick, os.getpid())
        for mocked in (
                patch.object(windows, '_windows_user32', return_value=self.api),
                patch.object(windows, '_last_input_tick', side_effect=lambda api: self.tick),
                patch.object(windows, '_window_process_id', return_value=os.getpid() + 1),
                patch.object(self.native, 'isEnabled', return_value=True),
                patch.object(self.native, 'winId', return_value=20),
                patch.object(self.native, '_owner_from_child', return_value=10),
                patch.object(self.native, '_window_valid_visible', return_value=(True, True))):
            mocked.start()
            self.addCleanup(mocked.stop)

    def activate(self, handle):
        self.foreground = handle.value
        return True

    def test_ok_click_authorizes_return_after_platform_already_lost_foreground(self):
        lease = self.native.beginOwnerClose(1)
        self.assertTrue(lease.return_foreground)
        self.assertEqual(self.foreground, 10)

    def test_alt_tab_after_ok_click_does_not_authorize_return(self):
        self.tick += 1
        lease = self.native.beginOwnerClose(1)
        self.assertFalse(lease.return_foreground)
        self.api.SetForegroundWindow.assert_not_called()

    def test_another_same_process_dialog_supersedes_close(self):
        with patch.object(windows, '_window_process_id', return_value=os.getpid()):
            lease = self.native.beginOwnerClose(1)
        self.assertFalse(lease.return_foreground)
        self.api.SetForegroundWindow.assert_not_called()

    def test_other_child_interaction_does_not_authorize_return(self):
        self.native._interaction_hwnd = 30
        self.assertFalse(self.native.beginOwnerClose(1).return_foreground)

    def test_missing_input_snapshot_does_not_authorize_return(self):
        self.native._interaction_open_lease = windows._OwnerOpenLease(10, None, os.getpid())
        self.assertFalse(self.native.beginOwnerClose(1).return_foreground)

    def test_refused_activation_is_not_success(self):
        self.api.SetForegroundWindow.side_effect = None
        self.api.SetForegroundWindow.return_value = False
        self.assertFalse(self.native._activate_owner(self.api, 10))

    def test_post_hide_retries_a_refused_activation(self):
        lease = windows._OwnerCloseLease(20, 10, True, True, self.tick, os.getpid())
        with patch.object(self.native, '_window_valid_visible',
                          side_effect=((False, False), (True, True))), \
                patch.object(self.native, '_activate_owner', return_value=False):
            self.assertIsNone(self.native.repairOwnerAfterHide(lease))

    def test_post_hide_restores_owner_after_platform_fallback(self):
        lease = windows._OwnerCloseLease(20, 10, True, True, self.tick, os.getpid())
        with patch.object(self.native, '_window_valid_visible',
                          side_effect=((False, False), (True, True))):
            self.assertTrue(self.native.repairOwnerAfterHide(lease))
        self.assertEqual(self.foreground, 10)

    def test_new_input_after_close_cancels_post_hide_activation(self):
        lease = windows._OwnerCloseLease(20, 10, True, True, self.tick, os.getpid())
        self.tick += 1
        with patch.object(self.native, '_window_valid_visible',
                          side_effect=((False, False), (True, True))):
            self.assertTrue(self.native.repairOwnerAfterHide(lease))
        self.api.SetForegroundWindow.assert_not_called()

    def test_new_dialog_after_close_cancels_post_hide_activation(self):
        lease = windows._OwnerCloseLease(20, 10, True, True, self.tick, os.getpid())
        with patch.object(self.native, '_window_valid_visible',
                          side_effect=((False, False), (True, True))), \
                patch.object(windows, '_window_process_id', return_value=os.getpid()):
            self.assertTrue(self.native.repairOwnerAfterHide(lease))
        self.api.SetForegroundWindow.assert_not_called()

    def test_native_hide_precedes_owner_activation(self):
        lease = windows._OwnerCloseLease(20, 10, True, True, self.tick, os.getpid())
        calls = []
        def hide(handle, mode):
            calls.append(('hide', handle.value, mode))
            self.foreground = 99  # USER32's automatic fallback on native hide.
        def activate(api, handle, **kwargs):
            calls.append(('activate', handle))
            self.foreground = handle
            return True
        self.api.ShowWindow = Mock(side_effect=hide)
        with patch.object(self.native, '_window_valid_visible', side_effect=(
                (True, True), (True, False), (True, True))), \
                patch.object(self.native, '_activate_owner', side_effect=activate):
            self.assertTrue(self.native.hideForOwnerClose(lease))
        self.assertEqual(calls, [('hide', 20, 0), ('activate', 10)])

    def test_background_close_hides_child_without_activating_owner(self):
        lease = windows._OwnerCloseLease(20, 10, True, False, self.tick, os.getpid())
        self.api.ShowWindow = Mock()
        with patch.object(self.native, '_window_valid_visible', side_effect=(
                (True, True), (True, False), (True, True))):
            self.assertTrue(self.native.hideForOwnerClose(lease))
        self.api.ShowWindow.assert_called_once()
        self.api.SetForegroundWindow.assert_not_called()

    def test_native_hide_refuses_a_reassigned_child_handle(self):
        lease = windows._OwnerCloseLease(20, 10, True, True, self.tick, os.getpid())
        self.api.ShowWindow = Mock()
        with patch.object(self.native, '_owner_from_child', return_value=30):
            self.assertFalse(self.native.hideForOwnerClose(lease))
        self.api.ShowWindow.assert_not_called()

    def test_input_tick_change_inside_foreground_close_does_not_cancel_handoff(self):
        # Real trace: input changed while the closing dialog still owned
        # foreground, then SW_HIDE selected a foreign app. No app switch
        # happened before hiding; a tick comparison must not veto this handoff.
        lease = windows._OwnerCloseLease(20, 10, True, True, self.tick, os.getpid())
        self.foreground = 20
        self.tick += 15
        def hide(handle, mode):
            self.foreground = 99
            self.tick += 16
        self.api.ShowWindow = Mock(side_effect=hide)
        with patch.object(self.native, '_window_valid_visible', side_effect=lambda api, hwnd:
                          (True, hwnd == 10 or self.foreground == 20)):
            self.assertTrue(self.native.hideForOwnerClose(lease))
        self.assertEqual(self.foreground, 10)
        self.api.SetForegroundWindow.assert_called_once()

    def test_new_input_in_foreign_app_before_hide_still_cancels_handoff(self):
        lease = windows._OwnerCloseLease(20, 10, True, True, self.tick, os.getpid())
        self.foreground = 99
        self.tick += 15
        self.api.ShowWindow = Mock()
        with patch.object(self.native, '_window_valid_visible', side_effect=(
                (True, True), (True, False), (True, True))):
            self.assertTrue(self.native.hideForOwnerClose(lease))
        self.api.SetForegroundWindow.assert_not_called()


if __name__ == '__main__':
    unittest.main()
