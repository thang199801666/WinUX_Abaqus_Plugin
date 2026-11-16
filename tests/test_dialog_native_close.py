"""Caption X must use QDialog's owner-safe close path for every native form."""
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import run_winux
run_winux._configure_bundled_dependencies(str(ROOT))
from DearUIQt.dialogs.qt_dialog import QtDialog


class DialogNativeCloseTests(unittest.TestCase):
    def make_dialog(self, ready=True):
        backend = SimpleNamespace(
            preserveFirstClientClick=Mock(return_value=ready),
            setCloseRequestHandler=Mock())
        return SimpleNamespace(
            tag=42, _native_window_backend=backend,
            winfo_exists=lambda: True, isVisible=lambda: True,
            _queue_native_close_request=Mock(),
            _prepare_native_first_click_once=Mock(),
            view=SimpleNamespace(after_render=Mock()))

    def test_plain_dialog_installs_close_handler_without_opt_in(self):
        dialog = self.make_dialog()
        self.assertTrue(QtDialog._prepare_native_first_click_once(dialog))
        dialog._native_window_backend.setCloseRequestHandler.assert_called_once_with(
            42, dialog._queue_native_close_request)

    def test_legacy_opt_out_does_not_bypass_safe_caption_close(self):
        dialog = self.make_dialog()
        dialog.NATIVE_DEFER_CLOSE = False
        QtDialog._prepare_native_first_click_once(dialog)
        dialog._native_window_backend.setCloseRequestHandler.assert_called_once()

    def test_missing_hwnd_retries_before_installing_close_handler(self):
        dialog = self.make_dialog(ready=None)
        self.assertIsNone(QtDialog._prepare_native_first_click_once(dialog))
        dialog._native_window_backend.setCloseRequestHandler.assert_not_called()
        dialog.view.after_render.assert_called_once_with(
            dialog._prepare_native_first_click_once, 1)

    def test_hidden_dialog_does_not_install_close_handler(self):
        dialog = self.make_dialog()
        dialog.isVisible = lambda: False
        self.assertFalse(QtDialog._prepare_native_first_click_once(dialog))
        dialog._native_window_backend.setCloseRequestHandler.assert_not_called()

    def test_repeated_native_close_requests_queue_one_reject(self):
        pending = []
        dialog = SimpleNamespace(
            _closed=False, winfo_exists=lambda: True, isVisible=lambda: True,
            reject=Mock(), view=SimpleNamespace(
                after=lambda delay, callback: pending.append(callback)))
        QtDialog._queue_native_close_request(dialog)
        QtDialog._queue_native_close_request(dialog)
        self.assertEqual(len(pending), 1)
        dialog.reject.assert_not_called()
        pending.pop()()
        dialog.reject.assert_called_once_with()


if __name__ == '__main__':
    unittest.main()
