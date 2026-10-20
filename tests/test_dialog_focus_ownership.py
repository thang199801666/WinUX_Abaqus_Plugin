"""Hidden tools and nested selectors retain their own focus/visibility intent."""
import ctypes
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from WinUx.ui.hosting.floating_runtime import FloatingDialogRuntime
from WinUx.ui.native.floating_viewport import NativeViewport
from WinUx.ui.native.dialog_focus import queue_owner_focus


class RuntimeFocusOwnershipTests(unittest.TestCase):
    def test_reactivate_digitizer_does_not_focus_behind_nested_selector(self):
        runtime = object.__new__(FloatingDialogRuntime)
        runtime.native = SimpleNamespace(visible=True, is_foreground=Mock(return_value=False),
                                         activate=Mock())
        runtime._focus_form = Mock()
        runtime.view = SimpleNamespace()
        runtime.emit = Mock()
        with patch("DearUIQt.input_gate.native_modal_input_active", return_value=True):
            runtime.show()
        self.assertTrue(runtime.desired_visible)
        runtime.native.activate.assert_not_called()
        runtime._focus_form.assert_not_called()
        runtime.emit.assert_called_once_with("visibility", visible=True)

    def test_reactivate_without_selector_still_restores_form_focus(self):
        runtime = object.__new__(FloatingDialogRuntime)
        runtime.native = SimpleNamespace(visible=True, is_foreground=Mock(return_value=False),
                                         activate=Mock())
        runtime._focus_form = Mock()
        runtime.view = SimpleNamespace()
        runtime.emit = Mock()
        with patch("DearUIQt.input_gate.native_modal_input_active", return_value=False):
            runtime.show()
        runtime.native.activate.assert_called_once_with()
        runtime._focus_form.assert_called_once_with()

    def test_native_activate_refuses_disabled_viewport(self):
        viewport = NativeViewport(100, True)
        viewport._owner_hwnd = 200
        api = Mock()
        api.IsWindowEnabled.return_value = False
        api.IsIconic.return_value = False
        api.GetForegroundWindow.return_value = 100
        with patch("WinUx.ui.native.floating_viewport.os.name", "nt"), \
                patch.object(ctypes, "windll", SimpleNamespace(user32=api), create=True), \
                patch("WinUx.ui.native.floating_viewport.prepare_owned_dialog_stack") as stack:
            viewport.activate()
        stack.assert_not_called()


class DeferredFocusOwnershipTests(unittest.TestCase):
    def test_hidden_logical_parent_is_not_revealed_by_late_selector_close(self):
        self._assert_hidden_parent_is_not_focused(hide_after_queue=False)

    def test_parent_hidden_during_retry_cancels_selector_focus_return(self):
        self._assert_hidden_parent_is_not_focused(hide_after_queue=True)

    def _assert_hidden_parent_is_not_focused(self, hide_after_queue):
        pending = []
        parent = SimpleNamespace(_closed=False, _visible=bool(hide_after_queue))
        view = SimpleNamespace(_floating_dialogs=set(),
                               after=lambda delay, callback, *args: pending.append((callback, args)),
                               winfo_exists=lambda: True)
        dialog = SimpleNamespace(_hwnd=200, _owner_hwnd=100, _owned_dialogs=[],
                                 _logical_parent=parent, view=view, _owner_was_visible=True)
        restore, repair = Mock(), Mock()
        with patch("WinUx.ui.native.dialog_focus.ensure_owner_visible") as reveal:
            queue_owner_focus(dialog, force=True, foreground=lambda: 0,
                              state=lambda hwnd: (True, False, True),
                              restore=restore, repair_keyboard=repair)
            parent._visible = False
            while pending:
                callback, args = pending.pop(0)
                callback(*args)
        reveal.assert_not_called()
        restore.assert_not_called()
        repair.assert_not_called()


class HideWithOwnedSelectorTests(unittest.TestCase):
    def runtime(self):
        runtime = object.__new__(FloatingDialogRuntime)
        runtime.owner_hwnd = 50
        runtime.desired_visible = True
        runtime.native = SimpleNamespace(hwnd=100, visible=True,
            is_foreground=Mock(return_value=False), set_visible=Mock(), handoff_to_owner=Mock())
        runtime.view = SimpleNamespace(_floating_dialogs=[], _floating_focus_suppressed=False)
        runtime.emit = Mock()
        return runtime

    def test_hide_closes_owned_selector_before_hiding_retained_parent(self):
        runtime = self.runtime()
        order = []
        child = SimpleNamespace(_owner_hwnd=100, _closed=False)
        child.destroy = Mock(side_effect=lambda: order.append(
            ("child", runtime.view._floating_focus_suppressed)))
        runtime.view._floating_dialogs.append(child)
        runtime.native.set_visible.side_effect = lambda visible: order.append(("parent", visible))
        with patch("WinUx.ui.native.dialog_focus.cancel_owner_focus_return") as cancel:
            runtime.hide()
        self.assertEqual(order, [("child", True), ("parent", False)])
        cancel.assert_called_once_with(100)
        self.assertFalse(runtime.view._floating_focus_suppressed)
        self.assertFalse(runtime.desired_visible)

    def test_hide_does_not_destroy_unrelated_sibling_or_prewarmer(self):
        runtime = self.runtime()
        sibling = SimpleNamespace(_owner_hwnd=50, _closed=False, destroy=Mock())
        pool = Mock()
        runtime.view._dialog_host_pool = pool
        runtime.view._floating_dialogs.append(sibling)
        with patch("WinUx.ui.native.dialog_focus.cancel_owner_focus_return"):
            runtime.hide()
        sibling.destroy.assert_not_called()
        pool.close.assert_not_called()

    def test_existing_focus_suppression_is_preserved(self):
        runtime = self.runtime()
        runtime.view._floating_focus_suppressed = True
        with patch("WinUx.ui.native.dialog_focus.cancel_owner_focus_return"):
            runtime.hide()
        self.assertTrue(runtime.view._floating_focus_suppressed)


if __name__ == "__main__":
    unittest.main()
