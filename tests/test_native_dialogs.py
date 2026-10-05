"""Headless contracts for floating DPG dialogs and the remaining native host."""

from pathlib import Path
import ast
import unittest


ROOT = Path(__file__).resolve().parents[1]
LOGIN_DIALOG = ROOT / "WinUx" / "dialogs" / "login_dialog.py"
NATIVE_HOST = ROOT / "WinUx" / "platform" / "native_dialog_host.py"
JOB_SCHEDULE_DIALOG = ROOT / "WinUx" / "dialogs" / "job_schedule_dialog.py"
SETTINGS_DIALOG = ROOT / "WinUx" / "dialogs" / "settings_dialog.py"
JOB_EDIT_DIALOG = ROOT / "WinUx" / "dialogs" / "job_edit_dialog.py"
JOB_MANAGER_DIALOG = ROOT / "WinUx" / "dialogs" / "job_manager_dialog.py"



DIALOGS = ROOT / "WinUx" / "dialogs"

def text(name):
    return (DIALOGS / name).read_text(encoding="utf-8")

def assert_floating(test, path, name):
    source = path.read_text(encoding="utf-8")
    if name != "LoginDialog":
        test.assertIn("from .floating_adapters import " + name, source)
        source = text("floating_adapters.py")
    tree = ast.parse(source)
    classes = {node.name: node for node in tree.body if isinstance(node, ast.ClassDef)}
    bases = {ast.unparse(base) for base in classes[name].bases}
    if "ResultDialog" in bases:
        bases.update(ast.unparse(base) for base in classes["ResultDialog"].bases)
    test.assertIn("FloatingDialogController", bases)
    test.assertNotIn("tk.Toplevel", bases)
    test.assertNotIn("dpg.window(", source)



def assert_child_result_before_destroy(test, filename, classname):
    tree = ast.parse(text(filename))
    cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == classname)
    method = next(n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name == "finish")
    source = ast.unparse(method)
    callback_pos = source.find("self.on_result(value)")
    destroy_pos = source.find("self.destroy()")
    test.assertGreaterEqual(callback_pos, 0)
    test.assertGreaterEqual(destroy_pos, 0)
    test.assertLess(callback_pos, destroy_pos)
    test.assertNotIn("self.view.after(self.ASYNC_RESULT_DELAY_MS, self.on_result, value)", source)
def assert_result_lifecycle(test, filename, classname):
    tree = ast.parse(text(filename))
    cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == classname)
    method = next(n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name == "finish")
    method.decorator_list = []
    namespace = {}
    exec(compile(ast.fix_missing_locations(ast.Module(body=[method], type_ignores=[])), filename, "exec"), namespace)
    from types import SimpleNamespace
    queued, delivered = [], []
    state = SimpleNamespace(result={"done": False, "value": None}, ASYNC_RESULT_DELAY_MS=20, _notify_cancel=True, closed=False)
    state.destroy = lambda: setattr(state, "closed", True)
    state.on_result = lambda value: delivered.append((value, state.closed))
    state.view = SimpleNamespace(after=lambda delay, callback, value: queued.append((delay, callback, value)))
    namespace["finish"](state, True)
    namespace["finish"](state, False)
    test.assertTrue(state.closed)
    test.assertEqual(delivered, [])
    test.assertEqual(len(queued), 1)
    delay, callback, value = queued[0]
    test.assertGreater(delay, 0)
    callback(value)
    test.assertEqual(delivered, [(True, True)])


class NativeDialogArchitectureTests(unittest.TestCase):
    def test_ssh_login_is_not_a_dearpygui_window(self):
        assert_floating(self, LOGIN_DIALOG, "LoginDialog")


    def test_job_schedule_is_a_native_top_level(self):
        assert_floating(self, JOB_SCHEDULE_DIALOG, "JobScheduleDialog")


    def test_job_manager_is_a_native_top_level(self):
        assert_floating(self, JOB_MANAGER_DIALOG, "JobManagerDialog")

    def test_job_manager_schedule_clock_updates_live(self):
        source = text("job_manager_form.py")
        self.assertIn('"00:30:00"', source)
        self.assertIn('row["live"]', source)
        self.assertIn('strftime(self.RUN_AT_FORMAT)', source)
        self.assertIn('self.view.after(1000, self._tick)', source)
        self.assertIn('_resolve_run_at_clock(text, live=row["live"])', source)

    def test_run_at_uses_full_date_and_time(self):
        from datetime import datetime
        from WinUx.dialogs.logic.job_manager import JobManagerLogic
        now = datetime(2030, 1, 2, 3, 4, 5)
        self.assertEqual(JobManagerLogic._resolve_run_at_clock("2030-01-02 03:04:06", now), datetime(2030, 1, 2, 3, 4, 6))
        with self.assertRaises(ValueError):
            JobManagerLogic._resolve_run_at_clock("03:04:06", now)
        with self.assertRaises(ValueError):
            JobManagerLogic._resolve_run_at_clock("2030-01-02 03:04:04", now)

    def test_job_manager_callbacks_return_to_app_ui_thread(self):
        source = text("job_manager_form.py")
        self.assertIn('self.view.after(0, self._request_core_estimates)', source)
        self.assertIn('self.view.after(0, self._submit_from_native, jobs)', source)
        self.assertIn('self.view.after(0, self._deliver_event, message)', text("floating_dialog.py"))

    def test_schedule_edit_accepts_second_resolution(self):
        from WinUx.dialogs.logic.job_manager import JobManagerLogic
        self.assertEqual(JobManagerLogic._parse_run_after("00:00:17").total_seconds(), 17)
        source = (ROOT / "WinUx/controllers/job_schedule.py").read_text(encoding="utf-8")
        self.assertIn('Enter duration (HH:MM:SS):', source)
        self.assertIn('seconds=seconds', source)

    def test_job_edit_is_a_native_top_level(self):
        assert_floating(self, JOB_EDIT_DIALOG, "JobEditDialog")

    def test_job_edit_uses_full_delete_datetime(self):
        from datetime import datetime
        from WinUx.dialogs.logic.job_schedule import JobEditScheduleLogic
        expected = datetime(2030, 1, 2, 3, 4, 5)
        self.assertEqual(JobEditScheduleLogic._parse_delete_at("2030-01-02 03:04:05"), expected)
        self.assertEqual(JobEditScheduleLogic._parse_delete_at("03:04:05 01-02-2030"), expected)
        self.assertIn("YYYY-MM-DD HH:MM:SS", text("job_edit_form.py"))

    def test_settings_is_a_native_top_level(self):
        assert_floating(self, SETTINGS_DIALOG, "SettingsDialog")

    def test_settings_keeps_all_three_preference_pages(self):
        source = text("settings_form.py")
        for key, label in (("general", "General"), ("abaqus", "Abaqus Versions"), ("account", "Saved Login"), ("performance", "Performance")):
            self.assertIn(repr((key, label)).replace("'", '"'), source)
        for token in ('INPPreferences().save(values)', 'GeneralPreferences().save(', 'PerformancePreferences().save(', 'AbaqusVersionPreferences().save(self._versions, dpg.get_value(self.default_command))', 'LoginPreferences().clear()'):
            self.assertIn(token, source)

    def test_job_schedule_refresh_updates_rows_in_place(self):
        source = text("job_schedule_form.py")
        for token in ('if identities != previous:', 'old_row = None if rebuilt else self._snapshot[index]', 'str(old_row[column]) != text', 'self.delete_owned_item(item)'):
            self.assertIn(token, source)

    def test_job_schedule_callbacks_return_to_dpg_ui_thread(self):
        source = text("floating_adapters.py")
        self.assertIn('self.view.after(0, self.schedule_command, str(action), str(kind), str(key))', source)
        self.assertIn('self.view.after(0, self._deliver_event, message)', text("floating_dialog.py"))


    def test_native_dialogs_share_qt_form_and_groupbox_layouts(self):
        shared = text("qt_dialog.py")
        self.assertIn('def labeled_widget(', shared)
        self.assertIn('def section(', shared)
        # Login intentionally mirrors the pre-migration compact flat form;
        # the larger settings/site/job dialogs continue to use QGroupBox-like sections.
        self.assertNotIn('self.section(', text('login_form.py'))
        for filename in ('site_manager_form.py', 'settings_form.py', 'job_edit_form.py'):
            self.assertIn('self.section(', text(filename))

    def test_native_dialogs_center_over_active_parent(self):
        source = NATIVE_HOST.read_text(encoding="utf-8")
        self.assertIn("resolve_native_dialog_parent", source)
        self.assertIn("CENTER_ON_PARENT = True", source)
        self.assertIn("CENTER_ON_SHOW = True", source)
        self.assertIn("restore_position=not self._center_on_parent_enabled()", source)
        self.assertIn("self._center_window_on_parent(window)", source)

    def test_native_host_reference_counts_modal_owner(self):
        source = NATIVE_HOST.read_text(encoding="utf-8")
        self.assertIn("_acquire_modal_owner", source)
        self.assertIn("_release_modal_owner", source)
        self.assertIn("_MODAL_OWNER_COUNTS", source)


class NativeDialogThreadingRegressionTests(unittest.TestCase):
    def test_native_windows_are_toplevels_not_independent_tk_roots(self):
        for path, name in ((LOGIN_DIALOG, "LoginDialog"), (JOB_SCHEDULE_DIALOG, "JobScheduleDialog"), (SETTINGS_DIALOG, "SettingsDialog"), (JOB_MANAGER_DIALOG, "JobManagerDialog")):
            assert_floating(self, path, name)
        self.assertIn('subprocess.Popen(', text("floating_dialog.py"))
        self.assertIn('create_viewport(', text("floating_runtime.py"))

    def test_native_host_reaps_tk_objects_on_owner_thread(self):
        source = NATIVE_HOST.read_text(encoding="utf-8")
        self.assertIn("_retired_windows", source)
        self.assertIn("_reap_retired_windows", source)
        self.assertIn("gc.collect()", source)
        self.assertIn("self._host._retire_window(window)", source)

    def test_native_host_owns_the_only_tk_root(self):
        source = NATIVE_HOST.read_text(encoding="utf-8")
        self.assertIn('name="winux-native-ui"', source)
        self.assertEqual(source.count("tk.Tk("), 1)
        dialogs_source = "\n".join(
            path.read_text(encoding="utf-8")
            for path in (ROOT / "WinUx" / "dialogs").glob("*.py")
        )
        self.assertNotIn("tk.Tk(", dialogs_source)
        self.assertIn("restore_owner_focus", source)
        self.assertIn("AttachThreadInput", source)

    def test_blocking_result_is_published_before_child_form_closes(self):
        assert_child_result_before_destroy(self, "blocking_form.py", "BlockingDialog")


    def test_native_host_applies_app_icon_to_dialogs(self):
        source = NATIVE_HOST.read_text(encoding="utf-8")
        resources = (ROOT / "WinUx" / "resources.py").read_text(encoding="utf-8")
        self.assertIn("apply_tk_app_icon", source)
        self.assertIn("apply_tk_app_icon(window)", source)
        self.assertIn("def apply_tk_app_icon", resources)
        self.assertIn('resource_path("WinUx.ico", required=True)', resources)

    def test_finalize_has_no_stale_modal_counter(self):
        source = NATIVE_HOST.read_text(encoding="utf-8")
        self.assertNotIn("_native_modal_state_acquired", source)
        self.assertNotIn("_release_native_modal_state", source)

    def test_finalize_releases_owner_before_focus_restore(self):
        path = NATIVE_HOST
        tree = ast.parse(path.read_bytes())
        cls = next(
            node for node in tree.body
            if isinstance(node, ast.ClassDef)
            and node.name == "NativeDialogController"
        )
        method = next(
            node for node in cls.body
            if isinstance(node, ast.FunctionDef)
            and node.name == "_finalize_window"
        )
        release_line = None
        focus_line = None
        for node in ast.walk(method):
            if not isinstance(node, ast.Call):
                continue
            if isinstance(node.func, ast.Name) and node.func.id == "_release_modal_owner":
                release_line = node.lineno
            if (isinstance(node.func, ast.Attribute)
                    and isinstance(node.func.value, ast.Name)
                    and node.func.value.id == "self"
                    and node.func.attr == "_set_modal_owner_active"):
                release_line = node.lineno
            if (isinstance(node.func, ast.Attribute)
                    and isinstance(node.func.value, ast.Name)
                    and node.func.value.id == "self"
                    and node.func.attr in (
                        "restore_owner_focus_async",
                        "restore_owner_foreground_async",
                    )):
                focus_line = node.lineno
        self.assertIsNotNone(release_line)
        self.assertIsNotNone(focus_line)
        self.assertLess(release_line, focus_line)

    def test_modal_focus_restore_is_dispatched_to_winux_ui_thread(self):
        source = NATIVE_HOST.read_text(encoding="utf-8")
        self.assertIn("restore_focus=False", source)
        self.assertIn("self.view.after", source)
        self.assertIn("restore_owner_focus_async", source)
        self.assertIn("restore_owner_foreground_async", source)



    def test_dialog_close_preserves_parent_window_placement(self):
        source = NATIVE_HOST.read_text(encoding="utf-8")
        self.assertIn("def _restore_owner_only_if_minimized", source)
        self.assertIn("user32.IsIconic", source)
        self.assertIn("_restore_owner_only_if_minimized(user32, owner_hwnd)", source)
        # Focus restoration must no longer unconditionally restore the GLFW
        # owner, which would unmaximize/resize it to the saved normal rect.
        restore_source = source.split("def restore_owner_focus", 1)[1]
        restore_source = restore_source.split("def is_native_window_foreground", 1)[0]
        self.assertNotIn("ShowWindow(wintypes.HWND(owner_hwnd), SW_RESTORE)", restore_source)

    def test_blocking_dialog_uses_fixed_right_aligned_action_footer(self):
        self.assertIn('self.button_box(actions)', text("blocking_form.py"))
        shared = text("qt_dialog.py")
        self.assertIn('width_fixed=True', shared)
        self.assertIn('height=DialogMetrics.BUTTON_HEIGHT', shared)
        self.assertIn('DialogMetrics.BUTTON_WIDTH', shared)

    def test_blocking_dialog_tears_down_before_dispatching_result(self):
        assert_result_lifecycle(self, "floating_adapters.py", "ResultDialog")

    def test_floating_root_result_forms_publish_before_destroy(self):
        for filename, classname, callback in (
            ("blocking_form.py", "BlockingDialog", "self.on_result(value)"),
            ("job_edit_form.py", "JobEditDialog", "self.on_result(value)"),
            ("odb_extract_form.py", "ODBExtractDialog", "self.on_result(value)"),
            ("server_path_form.py", "ServerPathDialog", "self.on_selected(str(value))"),
        ):
            tree = ast.parse(text(filename))
            cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == classname)
            method = next(n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name == "finish")
            source = ast.unparse(method)
            self.assertIn(callback, source, filename)
            self.assertIn("self.destroy()", source, filename)
            self.assertLess(source.find(callback), source.find("self.destroy()"), filename)

    def test_child_result_does_not_force_a_second_parent_side_close(self):
        source = text("floating_adapters.py")
        body = source.split('def handle_event(self, event, message):', 1)[1]
        body = body.split('def _notify_result', 1)[0]
        self.assertIn('self._record_result(message.get("value"))', body)
        self.assertNotIn('self.destroy()', body)
        self.assertNotIn('self.finish(', body)


    def test_settings_exposes_default_abaqus_command(self):
        source = text("settings_form.py")
        # Rev13 consolidates related fields into one QFormLayout instead of
        # creating a separate mini-grid per labeled widget.
        self.assertIn('command_form = self.form_layout(parent=commands, label_width=78)', source)
        self.assertIn('command_form, "Default",', source)
        self.assertIn('self.default_command', source)


if __name__ == "__main__":
    unittest.main()


class QtNativeDialogChromeTests(unittest.TestCase):
    def test_native_host_forces_top_level_qt_like_chrome(self):
        source = NATIVE_HOST.read_text(encoding="utf-8")
        self.assertIn("def apply_native_qt_chrome", source)
        self.assertIn("DWMWA_WINDOW_CORNER_PREFERENCE", source)
        self.assertIn("DWMWCP_ROUND", source)
        self.assertIn("style & ~WS_CHILD", source)
        self.assertIn("apply_native_qt_chrome(", source)
        self.assertIn('window_role=getattr(self, "WINDOW_ROLE", "dialog")', source)
        self.assertIn('WS_EX_TOOLWINDOW', source)

    def test_normal_dialog_preserves_tk_style_but_floating_dpg_uses_full_caption(self):
        source = NATIVE_HOST.read_text(encoding="utf-8")
        self.assertIn("desired_ex = ex_style", source)
        self.assertIn('if role == "tool":', source)
        self.assertIn('_winux_force_normal_caption', source)
        self.assertIn('desired_ex &= ~(WS_EX_TOOLWINDOW | WS_EX_APPWINDOW)', source)
        floating = (ROOT / "WinUx" / "platform" / "floating_viewport.py").read_text(encoding="utf-8")
        self.assertIn('self._winux_force_normal_caption = True', floating)
        self.assertIn('window_role="dialog"', floating)
        self.assertIn('allow_minimize=False, allow_maximize=False', floating)
        self.assertIn("ensure_native_dialog_interactive", source)

    def test_login_sizes_to_layout_so_button_box_is_not_clipped(self):
        source = text("login_form.py")
        self.assertIn('self.preferred_size = (420, 184)', source)
        self.assertIn('self.button_box(', source)
        self.assertIn('resizable=False', LOGIN_DIALOG.read_text(encoding="utf-8"))
        self.assertIn('getattr(self.form, "preferred_size", None)', text("floating_runtime.py"))
        self.assertIn('window_role="dialog"', (ROOT / "WinUx" / "platform" / "floating_viewport.py").read_text(encoding="utf-8"))

    def test_public_dialog_modules_do_not_create_dpg_windows(self):
        for path in DIALOGS.glob("*_dialog.py"):
            if path.name == "qt_dialog.py":
                continue
            source = path.read_text(encoding="utf-8")
            self.assertNotIn('dpg.add_window', source, path.name)
            self.assertNotIn('with dpg.window', source, path.name)

    def test_modern_toplevel_applies_native_chrome(self):
        source = (ROOT / "WinUx" / "dialogs" / "modern.py").read_text(
            encoding="utf-8")
        self.assertIn("apply_native_qt_chrome", source)
        self.assertIn("prepare_modern_toplevel", source)
