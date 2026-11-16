"""Plot Digitizer user-close confirmation behavior."""
from pathlib import Path
import sys
import unittest
from unittest.mock import Mock
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import run_winux
run_winux._configure_bundled_dependencies(str(ROOT))
from WinUx.plotdigitizer.ui.dialog import PlotDigitizerDialog
from DearUIQt.dialogs.qt_dialog import QtDialog


class _ConfirmingView:
    def __init__(self):
        self.requests = []

    def confirm_action_async(self, title, message, callback, **kwargs):
        self.requests.append((title, message, callback, kwargs))
        return object()


class PlotDigitizerCloseConfirmationTests(unittest.TestCase):
    def make_dialog(self):
        dialog = PlotDigitizerDialog.__new__(PlotDigitizerDialog)
        dialog._closed = False
        dialog._close_confirmation_pending = False
        dialog._close_confirmation_dialog = None
        dialog.view = _ConfirmingView()
        dialog.destroy = Mock()
        return dialog

    def test_close_request_is_confirmed_and_deduplicated(self):
        dialog = self.make_dialog()
        self.assertTrue(dialog._request_close_confirmation())
        self.assertTrue(dialog._close_confirmation_pending)
        self.assertEqual(len(dialog.view.requests), 1)

        title, message, callback, options = dialog.view.requests[0]
        self.assertEqual(title, "Confirm Exit Plot Digitizer")
        self.assertIn("unsaved changes", message.lower())
        self.assertEqual(options["primary_text"], "Exit")
        self.assertEqual(options["secondary_text"], "Cancel")
        self.assertEqual(options["intent"], "warning")
        self.assertIs(options["parent"], dialog)

        self.assertFalse(dialog._request_close_confirmation())
        self.assertEqual(len(dialog.view.requests), 1)

        callback(False)
        self.assertFalse(dialog._close_confirmation_pending)
        dialog.destroy.assert_not_called()

    def test_confirmed_close_destroys_digitizer(self):
        dialog = self.make_dialog()
        dialog._request_close_confirmation()
        callback = dialog.view.requests[0][2]
        callback(True)
        self.assertFalse(dialog._close_confirmation_pending)
        dialog.destroy.assert_called_once_with()

    def test_native_close_uses_confirmation(self):
        dialog = self.make_dialog()
        dialog._request_close_confirmation = Mock()
        dialog._close_from_native()
        dialog._request_close_confirmation.assert_called_once_with()
        dialog.destroy.assert_not_called()

    def test_native_window_close_is_deferred_until_ui_confirmation(self):
        self.assertTrue(PlotDigitizerDialog.NATIVE_DEFER_CLOSE)
        callbacks = []
        dialog = SimpleNamespace(_closed=False, winfo_exists=lambda: True, isVisible=lambda: True,
            _close_from_native=Mock(), reject=Mock(),
            view=SimpleNamespace(after=lambda delay, callback: callbacks.append(callback)))
        QtDialog._queue_native_close_request(dialog)
        QtDialog._queue_native_close_request(dialog)
        self.assertEqual(1, len(callbacks))
        dialog._close_from_native.assert_not_called()
        callbacks.pop()()
        dialog._close_from_native.assert_called_once_with()
        self.assertFalse(dialog._native_close_request_pending)
        QtDialog._queue_native_close_request(dialog)
        self.assertEqual(1, len(callbacks))

    def test_queued_native_close_does_not_run_after_teardown(self):
        callbacks = []
        dialog = SimpleNamespace(_closed=False, winfo_exists=lambda: True, isVisible=lambda: True,
            _close_from_native=Mock(), reject=Mock(),
            view=SimpleNamespace(after=lambda delay, callback: callbacks.append(callback)))
        QtDialog._queue_native_close_request(dialog)
        dialog._closed = True
        callbacks.pop()()
        dialog._close_from_native.assert_not_called()

    def test_queued_native_close_does_not_reopen_hidden_tool(self):
        callbacks = []
        dialog = SimpleNamespace(_closed=False, winfo_exists=lambda: True, isVisible=lambda: False,
            _close_from_native=Mock(), reject=Mock(),
            view=SimpleNamespace(after=lambda delay, callback: callbacks.append(callback)))
        QtDialog._queue_native_close_request(dialog)
        callbacks.pop()()
        dialog._close_from_native.assert_not_called()

    def test_final_escape_uses_confirmation(self):
        dialog = self.make_dialog()
        dialog._request_close_confirmation = Mock()
        dialog._point_press = None
        dialog._edit_enabled = False
        dialog._selected_point = None
        dialog.result_grid = Mock()
        dialog.result_grid.selectedKeys.return_value = set()
        dialog._pick_mode = None
        dialog._close_from_escape()
        dialog._request_close_confirmation.assert_called_once_with()
        dialog.destroy.assert_not_called()


if __name__ == "__main__":
    unittest.main()
