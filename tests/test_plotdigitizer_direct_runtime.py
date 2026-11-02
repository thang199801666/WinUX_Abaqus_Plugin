"""Direct Plot Digitizer runtime/threading regressions."""
from __future__ import annotations

from pathlib import Path
import sys
import threading
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from DearUIQt.backends.native_windows import NativeWindowBackend
from DearUIQt.modelview.spreadsheet_behavior import SpreadsheetBehavior
from WinUx.plotdigitizer import standalone


class _FakeApplication:
    current = None

    def __init__(self, after=None):
        type(self).current = self
        self.after = after
        self.backend = None

    @classmethod
    def instance(cls):
        return cls.current

    def installInputBackend(self, backend):
        self.backend = backend
        return True

    def delete(self):
        type(self).current = None


class _FakeRuntime:
    def __init__(self, native=True):
        self.backend = object()
        self.native = native
        self.calls = []

    def createContext(self, *, manual_callbacks=True):
        self.calls.append(('createContext', manual_callbacks))
        return True

    def supportsNativeWindows(self):
        self.calls.append(('supportsNativeWindows',))
        return self.native

    def enableNativeWindows(self):
        self.calls.append(('enableNativeWindows',))
        return True


class _FakeView:
    def __init__(self):
        self._qapplication = None
        self._native_dialogs = False

    def after(self, *_args):
        return None


class DirectRuntimeTests(unittest.TestCase):
    def tearDown(self):
        _FakeApplication.current = None

    def test_standalone_forces_manual_callback_management_and_native_children(self):
        runtime = _FakeRuntime(native=True)
        view = _FakeView()
        with patch.object(standalone, 'QApplication', _FakeApplication), \
                patch.object(standalone, 'configure_ui_context') as configure:
            application, native = standalone._configure_standalone_qt_runtime(
                runtime, view, native_dialogs=True)
        self.assertEqual(('createContext', True), runtime.calls[0])
        self.assertIn(('enableNativeWindows',), runtime.calls)
        self.assertTrue(native and view._native_dialogs)
        self.assertIs(view._qapplication, application)
        self.assertIs(application.backend, runtime.backend)
        configure.assert_called_once_with(view)

    def test_standalone_can_explicitly_keep_child_dialogs_embedded(self):
        runtime = _FakeRuntime(native=True)
        view = _FakeView()
        with patch.object(standalone, 'QApplication', _FakeApplication), \
                patch.object(standalone, 'configure_ui_context'):
            _application, native = standalone._configure_standalone_qt_runtime(
                runtime, view, native_dialogs=False)
        self.assertFalse(native)
        self.assertNotIn(('enableNativeWindows',), runtime.calls)

    def test_spreadsheet_rejects_wrong_thread_before_native_window_query(self):
        behavior = object.__new__(SpreadsheetBehavior)
        behavior._thread_id = threading.get_ident()
        behavior._thread_affinity = None
        with patch('DearUIQt.modelview.spreadsheet_behavior.threading.get_ident',
                   return_value=behavior._thread_id + 1):
            self.assertFalse(behavior._input_available())


    def test_native_child_resolves_registered_primary_owner_without_secondary_abi(self):
        native = object.__new__(NativeWindowBackend)
        native.backend = object()
        native._configured_item_tag = 22
        native._configured_owner_tag = 11
        native._configured_owner_hwnd = 0
        with patch.object(NativeWindowBackend, 'isPrimaryItem', return_value=True), \
                patch.object(NativeWindowBackend, 'primaryWinId', return_value=54321):
            self.assertEqual(54321, native._desiredOwnerHwnd(22))

    def test_secondary_winid_returns_zero_off_owner_thread(self):
        native = object.__new__(NativeWindowBackend)
        native.backend = object()
        native.extension = object()
        NativeWindowBackend._owner_threads[id(native.backend)] = 100
        try:
            with patch.object(NativeWindowBackend, 'isPrimaryItem', return_value=False), \
                    patch.object(NativeWindowBackend, 'require'), \
                    patch('DearUIQt.backends.native_windows.threading.get_ident', return_value=200), \
                    patch.object(NativeWindowBackend, '_rawWinId', side_effect=AssertionError('native ABI called')):
                self.assertEqual(0, native.winId(99))
        finally:
            NativeWindowBackend._owner_threads.pop(id(native.backend), None)

    def test_primary_winid_does_not_enter_secondary_native_abi(self):
        native = object.__new__(NativeWindowBackend)
        native.backend = object()
        with patch.object(NativeWindowBackend, 'isPrimaryItem', return_value=True), \
                patch.object(NativeWindowBackend, 'primaryWinId', return_value=12345), \
                patch.object(NativeWindowBackend, 'require', side_effect=AssertionError('secondary ABI')), \
                patch.object(NativeWindowBackend, '_rawWinId', side_effect=AssertionError('secondary ABI')):
            self.assertEqual(12345, native.winId(99))


if __name__ == '__main__':
    unittest.main()
