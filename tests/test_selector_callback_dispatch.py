"""Regression coverage for the selector's Dear PyGui callback dispatch."""
from __future__ import annotations

from collections import deque
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from WinUx.runtime.dpg_callbacks import invoke_callback_job
from WinUx.ui.behaviors.window.lifecycle import ViewLifecycleMixin


class _Runtime:
    def __init__(self, jobs):
        self._jobs = list(jobs)
        self.backend = SimpleNamespace(run_callbacks=self._unsafe_run_callbacks)
        self.unsafe_calls = 0

    def callbackQueue(self):
        jobs, self._jobs = self._jobs, []
        return jobs

    def _unsafe_run_callbacks(self, _jobs):
        self.unsafe_calls += 1
        raise AssertionError("Dear PyGui run_callbacks must not be used")


class _View(ViewLifecycleMixin):
    def __init__(self, jobs):
        self._gui_runtime = _Runtime(jobs)
        self._dpg_callbacks = deque()
        self._alive = True
        self.errors = []

    def _handle_ui_callback_error(self, callback, exc_info):
        self.errors.append((callback, exc_info[1]))

    def _preserve_native_close_requests(self):
        pass


class SelectorCallbackDispatchTests(unittest.TestCase):
    def test_optional_callback_parameter_does_not_over_index_native_job(self):
        calls = []

        def callback(sender, app_data, user_data=None, path="selected.png"):
            calls.append((sender, app_data, user_data, path))

        self.assertTrue(invoke_callback_job((callback, 10, "Open", None)))
        self.assertEqual(calls, [(10, "Open", None, "selected.png")])

    def test_view_callback_pump_never_falls_back_to_dpg_run_callbacks(self):
        calls = []

        def callback(sender, app_data, user_data=None, path="selected.png"):
            calls.append((sender, app_data, user_data, path))

        view = _View([(callback, 10, "Open", None)])
        with patch("WinUx.ui.behaviors.window.lifecycle.native_background_input_blocked", return_value=False):
            view._drain_dpg_callbacks()

        self.assertEqual(calls, [(10, "Open", None, "selected.png")])
        self.assertEqual(view._gui_runtime.unsafe_calls, 0)
        self.assertEqual(view.errors, [])


if __name__ == "__main__":
    unittest.main()
