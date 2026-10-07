"""Regression coverage for stable main-window visibility around dialogs."""
from __future__ import annotations

from pathlib import Path
import unittest
from unittest.mock import Mock

from WinUx.platform.dialog_focus import queue_owner_focus


ROOT = Path(__file__).resolve().parents[1]
NATIVE_HOST = ROOT / "WinUx" / "platform" / "native_dialog_host.py"
FLOATING_VIEWPORT = ROOT / "WinUx" / "platform" / "floating_viewport.py"
FLOATING_DIALOG = ROOT / "WinUx" / "dialogs" / "floating_dialog.py"
FLOATING_RUNTIME = ROOT / "WinUx" / "dialogs" / "floating_runtime.py"
VIEW = ROOT / "WinUx" / "view.py"
PREWARM_POOL = ROOT / "WinUx" / "dialogs" / "prewarm_pool.py"


class _QueueView:
    def __init__(self):
        self.pending = []
        self._floating_dialogs = set()
        self._floating_focus_suppressed = False

    def after(self, _delay, callback, *args):
        self.pending.append((callback, args))

    def winfo_exists(self):
        return True

    def tick(self):
        callback, args = self.pending.pop(0)
        callback(*args)


class _Dialog:
    def __init__(self, view, hwnd, owner=100, *, visible=True, closed=False, modal=False,
                 owner_was_visible=False):
        self.view = view
        self._hwnd = hwnd
        self._owner_hwnd = owner
        self._owned_dialogs = []
        self._focus_return_generation = 0
        self._owner_was_visible = bool(owner_was_visible)
        self._visible = visible
        self._closed = closed
        self.modal = modal
        view._floating_dialogs.add(self)


class DialogFocusRaceTests(unittest.TestCase):
    def test_new_sibling_without_hwnd_blocks_stale_focus_return(self):
        view = _QueueView()
        closing = _Dialog(view, 200)
        _Dialog(view, None)  # newly requested sibling, not published yet
        restore = Mock()

        queue_owner_focus(
            closing,
            force=True,
            foreground=lambda: 200,
            state=lambda hwnd: (True, False if hwnd == 200 else True, True),
            restore=restore,
            keyboard=lambda hwnd: False,
        )
        view.tick()
        restore.assert_not_called()

    def test_external_foreground_after_close_is_never_stolen(self):
        view = _QueueView()
        closing = _Dialog(view, 200)
        restore = Mock()

        queue_owner_focus(
            closing,
            force=False,
            foreground=lambda: 999,  # unrelated application was already active
            state=lambda hwnd: (True, False if hwnd == 200 else True, True),
            restore=restore,
            keyboard=lambda hwnd: False,
        )
        self.assertFalse(view.pending)
        restore.assert_not_called()

    def test_foreground_owned_close_returns_focus_after_native_hide_transition(self):
        view = _QueueView()
        closing = _Dialog(view, 200, owner_was_visible=True)
        restore = Mock()
        queue_owner_focus(
            closing,
            force=True,  # captured while the child was foreground, before SW_HIDE
            foreground=lambda: 999,
            state=lambda hwnd: (True, False, True) if hwnd == 200 else (True, True, True),
            restore=restore,
            keyboard=lambda hwnd: False,
        )
        view.tick()

        restore.assert_called_once_with(100)

    def test_active_dialog_close_repairs_owner_that_was_visible_when_opened(self):
        view = _QueueView()
        closing = _Dialog(view, 200, owner_was_visible=True)
        restore = Mock()
        visibility = {"owner": False}

        def state(hwnd):
            if hwnd == 100:
                return (True, visibility["owner"], True)
            return (True, False, True)

        def reveal(hwnd):
            self.assertEqual(hwnd, 100)
            visibility["owner"] = True
            return True

        with unittest.mock.patch(
                "WinUx.platform.dialog_focus.ensure_owner_visible",
                side_effect=reveal) as ensure_visible:
            queue_owner_focus(
                closing,
                foreground=lambda: 200,
                state=state,
                restore=restore,
                keyboard=lambda hwnd: False,
            )
            view.tick()

        ensure_visible.assert_called_once_with(100)
        restore.assert_called_once_with(100)

    def test_dialog_close_never_reveals_owner_that_started_hidden(self):
        view = _QueueView()
        closing = _Dialog(view, 200, owner_was_visible=False)
        restore = Mock()

        def state(hwnd):
            if hwnd == 100:
                return (True, False, True)
            return (True, False, True)

        with unittest.mock.patch(
                "WinUx.platform.dialog_focus.ensure_owner_visible") as ensure_visible:
            queue_owner_focus(
                closing,
                foreground=lambda: 200,
                state=state,
                restore=restore,
                keyboard=lambda hwnd: False,
            )
            view.tick()

        ensure_visible.assert_not_called()
        restore.assert_not_called()

    def test_external_focus_is_preserved_without_revealing_hidden_owner(self):
        view = _QueueView()
        closing = _Dialog(view, 200, owner_was_visible=True)
        restore = Mock()
        foreground_values = iter((200, 999))

        def state(hwnd):
            if hwnd == 100:
                return (True, False, True)
            return (True, False, True)

        with unittest.mock.patch(
                "WinUx.platform.dialog_focus.ensure_owner_visible") as ensure_visible:
            queue_owner_focus(
                closing,
                foreground=lambda: next(foreground_values),
                state=state,
                restore=restore,
                keyboard=lambda hwnd: False,
            )
            view.tick()

        # An unrelated foreground application is authoritative. Do not pop the
        # WinUx owner back onto the desktop merely to repair visibility.
        ensure_visible.assert_not_called()
        restore.assert_not_called()

    def test_explicit_modal_completion_can_recover_hidden_owner(self):
        view = _QueueView()
        closing = _Dialog(view, 200)
        closing._explicit_owner_return = True
        restore = Mock()
        visibility = {"owner": False}

        def state(hwnd):
            if hwnd == 100:
                return (True, visibility["owner"], True)
            return (True, False, True)

        def reveal(hwnd):
            self.assertEqual(hwnd, 100)
            visibility["owner"] = True
            return True

        with unittest.mock.patch(
                "WinUx.platform.dialog_focus.ensure_owner_visible",
                side_effect=reveal) as ensure_visible:
            queue_owner_focus(
                closing,
                force=True,
                foreground=lambda: 999,
                state=state,
                restore=restore,
                keyboard=lambda hwnd: False,
            )
            view.tick()

        ensure_visible.assert_called_once_with(100)
        restore.assert_called_once_with(100)


    def test_new_dialog_invalidates_pending_owner_focus_return(self):
        from WinUx.platform.dialog_focus import cancel_owner_focus_return

        view = _QueueView()
        closing = _Dialog(view, 200, owner_was_visible=True)
        restore = Mock()
        queue_owner_focus(
            closing,
            force=True,
            foreground=lambda: 200,
            state=lambda hwnd: (True, False, True) if hwnd == 200 else (True, True, True),
            restore=restore,
            keyboard=lambda hwnd: False,
        )
        cancel_owner_focus_return(100)
        view.tick()
        restore.assert_not_called()


class DialogForegroundHandoffTests(unittest.TestCase):
    def test_queue_uses_foreground_handoff_only_after_closing_child_is_gone(self):
        from WinUx.platform.dialog_focus import queue_owner_focus

        class View:
            def __init__(self):
                self.pending = []
                self._floating_dialogs = set()
            def after(self, _delay, callback, *args):
                self.pending.append((callback, args))
            def winfo_exists(self):
                return True
            def tick(self):
                callback, args = self.pending.pop(0)
                callback(*args)

        class Dialog:
            pass

        view = View()
        dialog = Dialog()
        dialog.view = view
        dialog._hwnd = 20
        dialog._owner_hwnd = 10
        dialog._owned_dialogs = []
        dialog._focus_return_generation = 0
        dialog._owner_was_visible = True
        dialog._explicit_owner_return = False
        dialog._logical_parent = None
        view._floating_dialogs.add(dialog)
        child_visible = {"value": True}
        foreground = {"value": 20}
        restored = []

        def state(hwnd):
            if hwnd == 10:
                return True, True, True
            if hwnd == 20:
                return True, child_visible["value"], True
            return False, False, False

        queue_owner_focus(
            dialog, force=True,
            foreground=lambda: foreground["value"],
            state=state, restore=lambda hwnd: restored.append(hwnd),
            keyboard=lambda _hwnd: False,
        )
        view.tick()
        self.assertEqual(restored, [])
        child_visible["value"] = False
        view.tick()
        self.assertEqual(restored, [10])


    def test_owner_already_foreground_needs_no_second_raise(self):
        view = _QueueView()
        closing = _Dialog(view, 200, owner_was_visible=True)
        restore = Mock()
        foreground_values = iter((200, 100, 100))

        queue_owner_focus(
            closing,
            force=True,
            foreground=lambda: next(foreground_values),
            state=lambda hwnd: (True, False, True) if hwnd == 200 else (True, True, True),
            restore=restore,
            keyboard=lambda hwnd: False,
        )
        view.tick()

        restore.assert_not_called()


class DialogFlickerSourceTests(unittest.TestCase):
    def test_owner_activation_never_reveals_or_uses_topmost(self):
        source = NATIVE_HOST.read_text(encoding="utf-8")
        body = source.split("def _restore_owner_activation", 1)[1]
        body = body.split("def restore_owner_focus", 1)[0]
        self.assertIn("IsWindowVisible", body)
        self.assertNotIn("user32.SetWindowPos", body)

    def test_dialog_foreground_handoff_has_one_shot_non_topmost_raise(self):
        source = NATIVE_HOST.read_text(encoding="utf-8")
        body = source.split("def _restore_owner_activation", 1)[1]
        body = body.split("def restore_owner_focus", 1)[0]
        self.assertIn("if raise_z_order:", body)
        self.assertIn("user32.BringWindowToTop(hwnd)", body)
        weak = source.split("def restore_owner_focus", 1)[1].split(
            "def restore_owner_foreground", 1)[0]
        strong = source.split("def restore_owner_foreground", 1)[1].split(
            "def is_native_window_foreground", 1)[0]
        self.assertIn("raise_z_order=False", weak)
        self.assertIn("raise_z_order=True", strong)

    def test_chrome_frame_change_is_nonactivating_and_keeps_z_order(self):
        source = NATIVE_HOST.read_text(encoding="utf-8")
        self.assertIn(
            "SWP_NOMOVE | SWP_NOSIZE | SWP_NOZORDER |\n"
            "                SWP_NOACTIVATE | SWP_FRAMECHANGED",
            source,
        )

    def test_floating_viewport_reveal_is_nonactivating(self):
        source = FLOATING_VIEWPORT.read_text(encoding="utf-8")
        self.assertIn("SW_SHOWNOACTIVATE = 4", source)
        helper = source.split("def set_native_window_visible", 1)[1]
        helper = helper.split("class ViewportCreationGuard", 1)[0]
        self.assertIn("SW_SHOWNOACTIVATE if bool(visible) else SW_HIDE", helper)
        show_body = source.split("def _show(self, visible):", 1)[1]
        show_body = show_body.split("def set_visible", 1)[0]
        self.assertIn("set_native_window_visible(self.hwnd, visible)", show_body)

    def test_modal_owner_is_acquired_before_child_publish(self):
        parent = FLOATING_DIALOG.read_text(encoding="utf-8")
        runtime = FLOATING_RUNTIME.read_text(encoding="utf-8")
        self.assertIn('if event == "prepared":', parent)
        prepared_body = parent.split('if event == "prepared":', 1)[1]
        prepared_body = prepared_body.split('elif event == "staged":', 1)[0]
        self.assertIn('self.post("publish")', prepared_body)
        self.assertNotIn("_acquire_modal_owner", prepared_body)
        staged_body = parent.split('elif event == "staged":', 1)[1]
        staged_body = staged_body.split('elif event == "ready":', 1)[0]
        self.assertLess(staged_body.index("_acquire_modal_owner"),
                        staged_body.index('self.post("publish_commit")'))
        self.assertIn('self.emit("prepared", hwnd=self.native.hwnd, pid=os.getpid())', runtime)
        self.assertIn("if not self._wait_for_publish():", runtime)
        self.assertLess(runtime.index("if not self._wait_for_publish():"),
                        runtime.index("self.native.stage_publish(self.desired_visible)"))
        self.assertLess(runtime.index('self.emit("staged"'),
                        runtime.index("if not self._wait_for_publish_commit():"))
        self.assertLess(runtime.index("if not self._wait_for_publish_commit():"),
                        runtime.index("self.native.commit_publish(self.desired_visible)"))

    def test_open_maps_under_cloak_and_renders_before_uncloak(self):
        runtime = FLOATING_RUNTIME.read_text(encoding="utf-8")
        viewport = FLOATING_VIEWPORT.read_text(encoding="utf-8")
        publish = runtime.split("self.native.stage_publish(self.desired_visible)", 1)[1]
        publish = publish.split('self.emit(\n            "ready"', 1)[0]
        self.assertLess(publish.index("self._render_settled_frame()"),
                        publish.index("self.native.commit_publish(self.desired_visible)"))
        self.assertLess(publish.index("self.native.activate()"),
                        publish.index("self.native.commit_publish(self.desired_visible)"))
        stage = viewport.split("def stage_publish", 1)[1].split("def flush_compositor", 1)[0]
        commit = viewport.split("def commit_publish", 1)[1].split("def publish", 1)[0]
        self.assertIn("self._show(True)", stage)
        self.assertNotIn("set_cloaked(self.hwnd, False)", stage)
        self.assertIn("set_cloaked(self.hwnd, False)", commit)

    def test_floating_form_pixels_survive_until_native_hide(self):
        runtime = FLOATING_RUNTIME.read_text(encoding="utf-8")
        base = (ROOT / "WinUx" / "dialogs" / "base.py").read_text(encoding="utf-8")
        self.assertIn("self.form._defer_visual_destroy = True", runtime)
        close = runtime.split("return_focus = bool(self.native and self.native.is_foreground())", 1)[1]
        close = close.split('self.emit("closed", return_focus=return_focus)', 1)[0]
        self.assertLess(close.index("self.native.set_visible(False)"),
                        close.index("_finalize_visual_destroy"))
        destroy = base.split("def destroy(self):", 1)[1].split("def grab_release", 1)[0]
        self.assertIn('_defer_visual_destroy', destroy)
        self.assertLess(destroy.index('_defer_visual_destroy'),
                        destroy.index('dpg.configure_item(tag, show=False)'))

    def test_close_has_no_pre_hide_cleanup_delay(self):
        runtime = FLOATING_RUNTIME.read_text(encoding="utf-8")
        close = runtime.split("return_focus = bool(self.native and self.native.is_foreground())", 1)[1]
        close = close.split('self.emit("closed", return_focus=return_focus)', 1)[0]
        self.assertNotIn("deadline = time.monotonic() + .05", close)
        self.assertNotIn("time.sleep(.005)", close)

    def test_parent_arms_owner_before_hiding_result_dialog(self):
        source = FLOATING_DIALOG.read_text(encoding="utf-8")
        body = source.split("def _finish(self):", 1)[1]
        body = body.split("def winfo_exists", 1)[0]
        self.assertLess(body.index("_foreground_hwnd()"),
                        body.index("set_native_window_visible(self._hwnd, False)"))
        self.assertLess(body.index("_release_modal_owner"),
                        body.index("set_native_window_visible(self._hwnd, False)"))
        self.assertIn("self._queue_owner_focus(force=True)", body)

    def test_child_reports_foreground_and_waits_for_owner_handoff_before_hide(self):
        runtime = FLOATING_RUNTIME.read_text(encoding="utf-8")
        self.assertIn("return_focus = bool(self.native and self.native.is_foreground())", runtime)
        close_body = runtime.split("return_focus = bool(self.native and self.native.is_foreground())", 1)[1]
        close_body = close_body.split('self.emit("closed", return_focus=return_focus)', 1)[0]
        self.assertLess(close_body.index('self.emit("closing", return_focus=True)'),
                        close_body.index("self._wait_for_owner_handoff()"))
        self.assertLess(close_body.index("self._wait_for_owner_handoff()"),
                        close_body.index("self.native.set_visible(False)"))
        self.assertIn('command == "owner_handoff_ready"', runtime)

        parent = FLOATING_DIALOG.read_text(encoding="utf-8")
        closing_body = parent.split('elif event == "closing":', 1)[1]
        closing_body = closing_body.split('elif event == "closed":', 1)[0]
        self.assertLess(closing_body.index("_release_modal_owner"),
                        closing_body.index('self.post("owner_handoff_ready")'))
        self.assertNotIn("release_native_modal_input", closing_body)

    def test_hide_arms_native_owner_but_keeps_input_gate_until_confirmation(self):
        source = FLOATING_DIALOG.read_text(encoding="utf-8")
        hide_body = source.split("def hide(self):", 1)[1]
        hide_body = hide_body.split("def _set_visible", 1)[0]
        self.assertIn("_release_modal_owner", hide_body)
        self.assertIn("self._set_visible(False, return_focus=return_focus)", hide_body)
        self.assertNotIn("release_native_modal_input", hide_body)
        set_body = source.split("def _set_visible", 1)[1]
        set_body = set_body.split("def _confirm_visibility", 1)[0]
        self.assertIn("_native_visible", set_body)
        self.assertIn("_release_visibility_guards", source)


    def test_framework_style_handoff_runs_before_parent_forced_hide(self):
        source = FLOATING_DIALOG.read_text(encoding="utf-8")
        body = source.split("def _finish(self):", 1)[1]
        body = body.split("def winfo_exists", 1)[0]
        self.assertIn("handoff_owner_before_close", body)
        self.assertLess(body.index("handoff_owner_before_close"),
                        body.index("set_native_window_visible(self._hwnd, False)"))

    def test_child_transfers_foreground_before_swhide(self):
        runtime = FLOATING_RUNTIME.read_text(encoding="utf-8")
        hide_body = runtime.split("def hide(self):", 1)[1].split("def _drain_commands", 1)[0]
        self.assertLess(hide_body.index("handoff_to_owner"),
                        hide_body.index("self.native.set_visible(False)"))
        close_body = runtime.split('self.emit("closing", return_focus=True)', 1)[1]
        close_body = close_body.split('self.emit("closed", return_focus=return_focus)', 1)[0]
        self.assertLess(close_body.index("self._wait_for_owner_handoff()"),
                        close_body.index("handoff_to_owner"))
        self.assertLess(close_body.index("handoff_to_owner"),
                        close_body.index("self.native.set_visible(False)"))

    def test_native_toplevel_handoff_precedes_withdraw_and_destroy(self):
        source = NATIVE_HOST.read_text(encoding="utf-8")
        hide_body = source.split('if name == "hide":', 1)[1].split("return True", 1)[0]
        self.assertLess(hide_body.index("handoff_owner_before_close"),
                        hide_body.index("window.withdraw()"))
        destroy_body = source.split("def _host_destroy_window(self):", 1)[1]
        destroy_body = destroy_body.split("def _finalize_window", 1)[0]
        self.assertLess(destroy_body.index("handoff_owner_before_close"),
                        destroy_body.index("window.destroy()"))

    def test_handoff_never_uses_topmost_or_showwindow(self):
        source = NATIVE_HOST.read_text(encoding="utf-8")
        body = source.split("def handoff_owner_before_close", 1)[1]
        body = body.split("def restore_owner_focus", 1)[0]
        self.assertIn("current != closing_hwnd", body)
        self.assertIn("_restore_owner_activation(owner_hwnd, raise_z_order=True)", body)
        self.assertNotIn("SetWindowPos", body)
        self.assertNotIn("ShowWindow", body)

    def test_native_dialog_enables_owner_before_withdraw_and_destroy(self):
        source = NATIVE_HOST.read_text(encoding="utf-8")
        hide_body = source.split('if name == "hide":', 1)[1]
        hide_body = hide_body.split("return True", 1)[0]
        self.assertLess(hide_body.index("self._set_modal_owner_active(False)"),
                        hide_body.index("window.withdraw()"))
        self.assertGreater(hide_body.index("self._set_native_modal_input(False)"),
                           hide_body.index("window.withdraw()"))

        destroy_body = source.split("def _host_destroy_window(self):", 1)[1]
        destroy_body = destroy_body.split("def _finalize_window", 1)[0]
        self.assertLess(destroy_body.index("self._set_modal_owner_active(False)"),
                        destroy_body.index("window.destroy()"))

    def test_floating_dialog_rejects_owner_hwnd_as_child(self):
        source = FLOATING_DIALOG.read_text(encoding="utf-8")
        self.assertIn("int(hwnd) == int(self._owner_hwnd)", source)
        self.assertIn("cancel_owner_focus_return(self._owner_hwnd)", source)

    def test_focus_retries_are_bounded_and_coalesced_per_owner(self):
        source = (ROOT / "WinUx" / "platform" / "dialog_focus.py").read_text(encoding="utf-8")
        self.assertIn("_OWNER_FOCUS_GENERATIONS", source)
        self.assertIn("owner_generation != _OWNER_FOCUS_GENERATIONS", source)
        self.assertIn("if attempt < 32", source)


    def test_modal_input_is_not_acquired_during_floating_child_bootstrap(self):
        source = FLOATING_DIALOG.read_text(encoding="utf-8")
        init = source.split("def __init__(self, view, kind, title", 1)[1]
        init = init.split("def post(self, command", 1)[0]
        self.assertNotIn("acquire_native_modal_input(self)", init)
        prepared = source.split('if event == "prepared":', 1)[1]
        prepared = prepared.split('elif event == "staged":', 1)[0]
        self.assertIn("acquire_native_modal_input(self)", prepared)

    def test_dialog_prewarm_starts_during_view_construction(self):
        source = VIEW.read_text(encoding="utf-8")
        init = source.split("def __init__(self, callbacks):", 1)[1]
        init = init.split("def _find_main_viewport_hwnd", 1)[0]
        self.assertIn("start_dialog_prewarm(self)", init)
        run = source.split("def run(self):", 1)[1]
        run = run.split("def after(self, delay", 1)[0]
        self.assertNotIn("self.after(0, start_dialog_prewarm, self)", run)

    def test_default_prewarm_pool_keeps_two_workers_ready_or_preparing(self):
        source = PREWARM_POOL.read_text(encoding="utf-8")
        self.assertIn("def __init__(self, capacity=2):", source)

    def test_prewarmed_dialog_uses_shorter_hidden_settle_path(self):
        source = FLOATING_RUNTIME.read_text(encoding="utf-8")
        self.assertIn("settle_frames = 2 if self.prepared is not None else 3", source)
        self.assertIn("if self.prepared is None:\n                self._render_settled_frame()", source)


if __name__ == "__main__":
    unittest.main()
