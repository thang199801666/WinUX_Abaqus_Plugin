"""Headless contracts for the dialog-hosting split.

Main-window dialogs are in-process Qt-like QDialogs (WinUx/dialogs/inprocess/*
built on DearUIQt.dialogs.qt_dialog, with public ``WinUx/dialogs/<name>_dialog``
modules forwarding into ``inprocess_adapters``).  Explicit process-isolated
hosting still lives in ``WinUx/dialogs/floating_adapters.py`` where every class
subclasses ``FloatingDialogController``/``ResultDialog`` and is launched through
``WinUx/ui/hosting/floating_runtime.py`` against the single shared native
host in ``WinUx/ui/native/native_dialog_host.py``.
"""

from pathlib import Path
import ast
import unittest


ROOT = Path(__file__).resolve().parents[1]
DIALOGS = ROOT / "WinUx" / "dialogs"
INPROCESS = ROOT / "WinUx" / "dialogs" / "inprocess"
# Retained main-window dialogs (hidden on close, deleted at app shutdown).
RETAINED_DIALOGS = (
    (ROOT / "WinUx" / "dialogs" / "settings_dialog.py", "SettingsDialog", "settings"),
    (ROOT / "WinUx" / "dialogs" / "bookmarks_dialog.py", "BookmarksDialog", "bookmarks"),
    (ROOT / "WinUx" / "dialogs" / "site_manager_dialog.py", "SiteManagerDialog", "site_manager"),
    (ROOT / "WinUx" / "dialogs" / "sync_preview_dialog.py", "SyncPreviewDialog", "sync_preview"),
    (ROOT / "WinUx" / "dialogs" / "job_schedule_dialog.py", "JobScheduleDialog", "job_schedule"),
    (ROOT / "WinUx" / "dialogs" / "transfer_center_dialog.py", "TransferCenterDialog", "transfer_center"),
)
# One-shot transient dialogs (destroyed when their operation completes).
TRANSIENT_DIALOGS = (
    (ROOT / "WinUx" / "dialogs" / "login_dialog.py", "LoginDialog", "login"),
    (ROOT / "WinUx" / "dialogs" / "blocking_dialog.py", "BlockingDialog", "blocking"),
    (ROOT / "WinUx" / "dialogs" / "job_edit_dialog.py", "JobEditDialog", "job_edit"),
    (ROOT / "WinUx" / "dialogs" / "job_manager_dialog.py", "JobManagerDialog", "job_manager"),
    (ROOT / "WinUx" / "dialogs" / "server_path_dialog.py", "ServerPathDialog", "server_path"),
    (ROOT / "WinUx" / "dialogs" / "progress_dialog.py", "ProgressDialog", "progress"),
)
FLOATING_ADAPTERS = ROOT / "WinUx" / "dialogs" / "floating_adapters.py"
INPROCESS_ADAPTERS = ROOT / "WinUx" / "dialogs" / "inprocess_adapters.py"
FLOATING_DIALOG = ROOT / "WinUx" / "ui" / "hosting" / "floating_dialog.py"
FLOATING_RUNTIME = ROOT / "WinUx" / "ui" / "hosting" / "floating_runtime.py"
PROCESS_HOST = ROOT / "WinUx" / "ui" / "hosting" / "process.py"
RESULT_DIALOG = ROOT / "WinUx" / "ui" / "hosting" / "result_dialog.py"
NATIVE_HOST = ROOT / "WinUx" / "ui" / "native" / "native_dialog_host.py"
FLOATING_VIEWPORT = ROOT / "WinUx" / "ui" / "native" / "floating_viewport.py"
QT_DIALOG = ROOT / "DearUIQt" / "dialogs" / "qt_dialog.py"

# Dialog classes that must still be explicit process-isolated native windows.
FLOATING_CLASSES = (
    "BlockingDialog", "JobEditDialog", "ODBExtractDialog", "ReferenceChartDialog",
    "ODBCheckDialog", "ODBXYResultDialog", "SettingsDialog", "DiagnosticsDialog",
    "BookmarksDialog", "SiteManagerDialog", "SyncPreviewDialog", "LocalFolderDialog",
    "LocalFileDialog", "ServerPathDialog", "ProgressDialog", "JobScheduleDialog",
    "JobManagerDialog", "ConsoleDialog", "TransferCenterDialog",
)


def text(name):
    return (DIALOGS / name).read_text(encoding="utf-8")


def text_at(path):
    return path.read_text(encoding="utf-8")


def class_bases(test, path, name, module_source=None):
    tree = ast.parse(text_at(path) if module_source is None else module_source)
    classes = {node.name: node for node in tree.body if isinstance(node, ast.ClassDef)}
    test.assertIn(name, classes)
    return {ast.unparse(base) for base in classes[name].bases}


def _result_dialog_bases():
    """Resolve the parent-side ResultDialog bases from its current module."""
    tree = ast.parse(text_at(RESULT_DIALOG))
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name == "ResultDialog":
            return node
    raise AssertionError("ResultDialog moved out of {}".format(RESULT_DIALOG))


def assert_floating(test, source, name):
    """Assert a class in *source* is still a process-isolated native dialog."""
    tree = ast.parse(source)
    classes = {node.name: node for node in tree.body if isinstance(node, ast.ClassDef)}
    bases = {ast.unparse(base) for base in classes[name].bases}
    if "ResultDialog" in bases:
        result_class = _result_dialog_bases()
        bases.update({ast.unparse(base) for base in result_class.bases})
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


def assert_result_lifecycle(test, path, classname):
    tree = ast.parse(text_at(path))
    cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == classname)
    method = next(n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name == "finish")
    method.decorator_list = []
    namespace = {}
    exec(compile(ast.fix_missing_locations(ast.Module(body=[method], type_ignores=[])), path.name, "exec"), namespace)
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
    def test_main_window_dialogs_are_inprocess_qt_dialogs(self):
        # Main-window dialogs no longer spawn dialog processes: the public
        # modules forward into inprocess_adapters and the application-facing
        # classes are transient or retained Qt-like QDialogs.
        for public_path, name, _ in tuple(RETAINED_DIALOGS) + tuple(TRANSIENT_DIALOGS):
            source = text_at(public_path)
            self.assertIn("from .inprocess_adapters import " + name, source,
                          public_path.name)
        adapters = text_at(INPROCESS_ADAPTERS)
        self.assertIn("from . import inprocess as _inprocess", adapters)
        self.assertIn("__all__ = list(_inprocess.__all__)", adapters)

    def test_retained_dialogs_use_the_retained_inprocess_lifetime(self):
        module = text_at(INPROCESS / "common.py")
        self.assertIn("class RetainedTool", module)
        self.assertIn("RetainedInProcessDialogMixin", module)
        for public_path, name, module_name in RETAINED_DIALOGS:
            source = text_at(INPROCESS / (module_name + ".py"))
            self.assertIn("class {}(RetainedTool, ".format(name), source,
                          module_name)

    def test_transient_dialogs_use_the_transient_inprocess_lifetime(self):
        source = text_at(INPROCESS / "transient.py")
        self.assertIn("TransientInProcessDialogMixin", source)
        for public_path, name, _ in TRANSIENT_DIALOGS:
            self.assertIn("class {name}(_TransientTool, ".format(name=name),
                          source, name)
            self.assertIn("_init_inprocess_lifetime(view)", source, name)

    def test_inprocess_lifetime_registers_and_owns_anchor_dialogs(self):
        module = text_at(
            ROOT / "WinUx" / "ui" / "hosting" / "inprocess_dialog.py")
        self.assertIn("def register_inprocess_dialog", module)
        self.assertIn("def close_inprocess_dialogs", module)
        self.assertIn("class TransientInProcessDialogMixin", module)
        self.assertIn("class RetainedInProcessDialogMixin", module)
        self.assertIn('owner.setObjectName("WinUxInProcessDialogs")', module)

    def test_process_isolated_dialogs_remain_native_hosted(self):
        adapters = text_at(FLOATING_ADAPTERS)
        for name in FLOATING_CLASSES:
            assert_floating(self, adapters, name)

    def test_process_isolated_launch_uses_a_dedicated_child_viewport(self):
        runtime = text_at(FLOATING_RUNTIME)
        self.assertIn("class ChildView", runtime)
        self.assertIn("class FloatingDialogRuntime", runtime)
        self.assertIn("self.gui.createViewport(", runtime)
        self.assertIn('getattr(self.form, "preferred_size", None)', runtime)
        # Forms for every floating dialog kind are dispatched centrally.
        self.assertIn("def create_form", text("floating_forms.py"))
        # Every dialog process is spawned as a controlled child process.
        process = text_at(PROCESS_HOST)
        self.assertIn("QProcess(childLabel=", process)
        self.assertIn("launch_dialog_process", process)

    def test_job_manager_schedule_clock_updates_live(self):
        source = text("job_manager_form.py")
        self.assertIn('"00:30:00"', source)
        self.assertIn('row["live"]', source)
        self.assertIn('strftime(self.RUN_AT_FORMAT)', source)
        self.assertIn('self._clock_timer = self.create_timer(1000, self._tick)', source)
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
        self.assertIn('self.view.after(0, self._deliver_event, message)',
                      text_at(FLOATING_DIALOG))

    def test_schedule_edit_accepts_second_resolution(self):
        from WinUx.dialogs.logic.job_manager import JobManagerLogic
        self.assertEqual(JobManagerLogic._parse_run_after("00:00:17").total_seconds(), 17)
        source = (ROOT / "WinUx/controllers/job_schedule.py").read_text(encoding="utf-8")
        self.assertIn('Enter duration (HH:MM:SS):', source)
        self.assertIn('seconds=seconds', source)

    def test_job_edit_uses_full_delete_datetime(self):
        from datetime import datetime
        from WinUx.dialogs.logic.job_schedule import JobEditScheduleLogic
        expected = datetime(2030, 1, 2, 3, 4, 5)
        self.assertEqual(JobEditScheduleLogic._parse_delete_at("2030-01-02 03:04:05"), expected)
        self.assertEqual(JobEditScheduleLogic._parse_delete_at("03:04:05 01-02-2030"), expected)
        self.assertIn("YYYY-MM-DD HH:MM:SS", text("job_edit_form.py"))

    def test_settings_keeps_all_preference_pages(self):
        source = text("settings_form.py")
        for key, label in (("general", "General"), ("abaqus", "Abaqus Versions"),
                           ("account", "Saved Login"), ("performance", "Performance"),
                           ("updates", "Updates")):
            self.assertIn(repr((key, label)).replace("'", '"'), source)
        for token in ('INPPreferences().save(values)', 'GeneralPreferences().save(',
                      'PerformancePreferences().save(',
                      'AbaqusVersionPreferences().save(self._versions, self.control_value(self.default_command))',
                      'preferences.clear()'):
            self.assertIn(token, source)

    def test_job_schedule_refresh_updates_rows_in_place(self):
        source = text("job_schedule_form.py")
        for token in ('rebuilt = identities != previous',
                      'old_row = None if rebuilt else self._snapshot[index]',
                      'str(old_row[column]) != text'):
            self.assertIn(token, source)

    def test_job_schedule_callbacks_return_to_app_ui_thread(self):
        # In-process form dispatches directly on the main event loop; the
        # process-isolated adapters route through the same view.after.
        source = text("job_schedule_form.py")
        for token in ('self.view.after(0, self.schedule_command, str(action), str(kind), str(key))',
                      'def request_refresh', 'self.view.after(0, self.refresh)'):
            self.assertIn(token, source)
        self.assertIn('self.view.after(0, self.schedule_command, str(action), str(kind), str(key))',
                      text_at(FLOATING_ADAPTERS))
        self.assertIn('self.view.after(0, self._deliver_event, message)',
                      text_at(FLOATING_DIALOG))

    def test_native_dialogs_share_qt_form_and_groupbox_layouts(self):
        shared = text_at(QT_DIALOG)
        self.assertIn('def labeled_widget(', shared)
        self.assertIn('def section(', shared)
        # Login intentionally mirrors the pre-migration compact flat form;
        # the larger settings/site/job dialogs continue to use QGroupBox-like sections.
        self.assertNotIn('self.section(', text('login_form.py'))
        for filename in ('site_manager_form.py', 'settings_form.py', 'job_edit_form.py'):
            self.assertIn('self.section(', text(filename))

    def test_native_dialogs_center_over_active_parent(self):
        source = text_at(NATIVE_HOST)
        self.assertIn("resolve_native_dialog_parent", source)
        self.assertIn("CENTER_ON_PARENT = True", source)
        self.assertIn("CENTER_ON_SHOW = True", source)
        self.assertIn("restore_position=not self._center_on_parent_enabled()", source)
        self.assertIn("self._center_window_on_parent(window)", source)

    def test_native_host_reference_counts_modal_owner(self):
        source = text_at(NATIVE_HOST)
        self.assertIn("_acquire_modal_owner", source)
        self.assertIn("_release_modal_owner", source)
        self.assertIn("_MODAL_OWNER_COUNTS", source)


class NativeDialogThreadingRegressionTests(unittest.TestCase):
    def test_process_isolated_dialogs_still_run_in_dedicated_toplevels(self):
        adapters = text_at(FLOATING_ADAPTERS)
        for name in ("BlockingDialog", "JobScheduleDialog", "SettingsDialog", "JobManagerDialog"):
            assert_floating(self, adapters, name)
        self.assertIn('QProcess(childLabel=', text_at(PROCESS_HOST))
        self.assertIn('self.gui.createViewport(', text_at(FLOATING_RUNTIME))

    def test_native_host_reaps_tk_objects_on_owner_thread(self):
        source = text_at(NATIVE_HOST)
        self.assertIn("_retired_windows", source)
        self.assertIn("_reap_retired_windows", source)
        self.assertIn("gc.collect()", source)
        self.assertIn("self._host._retire_window(window)", source)

    def test_native_host_owns_the_only_shared_tk_root(self):
        # One hidden tk root runs on the dedicated winux-native-ui thread that
        # every process-isolated dialog shares.
        source = text_at(NATIVE_HOST)
        self.assertIn('name="winux-native-ui"', source)
        self.assertEqual(source.count("tk.Tk("), 1)
        self.assertIn("restore_owner_focus", source)
        self.assertIn("AttachThreadInput", source)

    def test_blocking_result_is_published_before_child_form_closes(self):
        assert_child_result_before_destroy(self, "blocking_form.py", "BlockingDialog")


    def test_native_host_applies_app_icon_to_dialogs(self):
        source = text_at(NATIVE_HOST)
        resources = (ROOT / "WinUx" / "resources.py").read_text(encoding="utf-8")
        self.assertIn("apply_tk_app_icon", source)
        self.assertIn("apply_tk_app_icon(window)", source)
        self.assertIn("def apply_tk_app_icon", resources)
        self.assertIn('resource_path("WinUx.ico", required=True)', resources)

    def test_finalize_has_no_stale_modal_counter(self):
        source = text_at(NATIVE_HOST)
        self.assertNotIn("_native_modal_state_acquired", source)
        self.assertNotIn("_release_native_modal_state", source)

    def test_finalize_releases_owner_before_focus_restore(self):
        tree = ast.parse(text_at(NATIVE_HOST))
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
            if (isinstance(node.func, ast.Attribute)
                    and isinstance(node.func.value, ast.Name)
                    and node.func.value.id == "self"):
                # _finalize_window releases the modal owner through
                # _set_modal_owner_active(False) (which passes
                # restore_focus=False) before queueing the bounded foreground
                # restore.
                if (node.func.attr == "_set_modal_owner_active" and node.args):
                    release_line = release_line or node.lineno
                if node.func.attr in (
                        "restore_owner_focus_async",
                        "restore_owner_foreground_async"):
                    focus_line = focus_line or node.lineno
        self.assertIsNotNone(release_line)
        self.assertIsNotNone(focus_line)
        self.assertLess(release_line, focus_line)

    def test_modal_focus_restore_is_dispatched_to_winux_ui_thread(self):
        source = text_at(NATIVE_HOST)
        self.assertIn("restore_focus=False", source)
        self.assertIn("self.view.after", source)
        self.assertIn("restore_owner_focus_async", source)
        self.assertIn("restore_owner_foreground_async", source)

    def test_dialog_close_preserves_parent_window_placement(self):
        source = text_at(NATIVE_HOST)
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
        shared = text_at(QT_DIALOG)
        self.assertIn('width_fixed=True', shared)
        self.assertIn('height=DialogMetrics.BUTTON_HEIGHT', shared)
        self.assertIn('DialogMetrics.BUTTON_WIDTH', shared)

    def test_blocking_dialog_tears_down_before_dispatching_result(self):
        assert_result_lifecycle(self, RESULT_DIALOG, "ResultDialog")

    def test_floating_root_result_forms_publish_before_destroy(self):
        for filename, classname, callback in (
            ("blocking_form.py", "BlockingDialog", "self.on_result(value)"),
            ("job_edit_form.py", "JobEditDialog", "self.on_result(value)"),
            ("odb_extract_form.py", "ODBExtractDialog", "self.on_result(value)"),
            ("server_path_form.py", "ServerPathDialog", "self.on_selected(str(value))"),
        ):
            source_file = text(filename)
            tree = ast.parse(source_file)
            cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == classname)
            method = next(n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name == "finish")
            source = ast.unparse(method)
            self.assertIn(callback, source, filename)
            self.assertIn("self.destroy()", source, filename)
            self.assertLess(source.find(callback), source.find("self.destroy()"), filename)

    def test_child_result_does_not_force_a_second_parent_side_close(self):
        # The parent-side lifecycle records the result from the child event and
        # must not close/finish the native window a second time.
        result_source = text_at(RESULT_DIALOG)
        method = next(
            node for node in ast.parse(result_source).body
            if isinstance(node, ast.ClassDef) and node.name == "ResultDialog")
        event_source = ast.unparse(next(
            node for node in method.body
            if isinstance(node, ast.FunctionDef) and node.name == "handle_event"))
        self.assertIn("_record_result(message", event_source)
        self.assertNotIn("self.destroy()", event_source)
        self.assertNotIn("self.finish(", event_source)

    def test_inprocess_result_forms_record_pending_results_first(self):
        # In-process file/folder browsers keep the same guarantee: selection
        # goes through one finish() path that never double-closes.
        self.assertIn('def finish(self, value)', text("local_folder_form.py"))
        self.assertIn('self.finish(str(path))', text("local_file_form.py"))

    def test_settings_exposes_default_abaqus_command(self):
        source = text("settings_form.py")
        # One QFormLayout powers the executable-command page; the default
        # selection lives in the same labeled row instead of a separate grid.
        self.assertIn('command_form = self.form_layout(parent=commands, label_width=78)', source)
        self.assertIn('command_form, "Default",', source)
        self.assertIn('self.default_command', source)


class QtNativeDialogChromeTests(unittest.TestCase):
    def test_native_host_forces_top_level_qt_like_chrome(self):
        source = text_at(NATIVE_HOST)
        self.assertIn("def apply_native_qt_chrome", source)
        self.assertIn("DWMWA_WINDOW_CORNER_PREFERENCE", source)
        self.assertIn("DWMWCP_ROUND", source)
        self.assertIn("style & ~WS_CHILD", source)
        self.assertIn("apply_native_qt_chrome(", source)
        self.assertIn('window_role=getattr(self, "WINDOW_ROLE", "dialog")', source)
        self.assertIn('WS_EX_TOOLWINDOW', source)

    def test_normal_dialog_preserves_tk_style_but_floating_dpg_uses_full_caption(self):
        source = text_at(NATIVE_HOST)
        self.assertIn("desired_ex = ex_style", source)
        self.assertIn('if role == "tool":', source)
        self.assertIn('_winux_force_normal_caption', source)
        self.assertIn('desired_ex &= ~(WS_EX_TOOLWINDOW | WS_EX_APPWINDOW)', source)
        floating = text_at(FLOATING_VIEWPORT)
        self.assertIn('self._winux_force_normal_caption', floating)
        self.assertIn('window_role="tool" if hide_taskbar else "dialog"', floating)
        # The per-dialog viewport chrome contract is feature-owned: the runtime
        # reads ALLOW_MINIMIZE/ALLOW_MAXIMIZE from the form and applies it.
        runtime = text_at(FLOATING_RUNTIME)
        self.assertIn('"allow_minimize": bool(getattr(self.form, "ALLOW_MINIMIZE"', runtime)
        self.assertIn('"allow_maximize": bool(getattr(self.form, "ALLOW_MAXIMIZE"', runtime)
        self.assertIn('"allow_minimize", False))', runtime)
        self.assertIn("ensure_native_dialog_interactive", source)

    def test_login_sizes_to_layout_so_button_box_is_not_clipped(self):
        source = text("login_form.py")
        self.assertIn('self.preferred_size = (420, 204)', source)
        self.assertIn('self.button_box(', source)
        runtime = text_at(FLOATING_RUNTIME)
        self.assertIn('getattr(self.form, "preferred_size", None)', runtime)
        viewport = text_at(FLOATING_VIEWPORT)
        self.assertIn('window_role="tool" if hide_taskbar else "dialog"', viewport)

    def test_public_dialog_modules_do_not_create_dpg_windows(self):
        for path in DIALOGS.glob("*_dialog.py"):
            if path.name in ("qt_dialog.py", "floating_dialog.py"):
                continue
            source = path.read_text(encoding="utf-8")
            self.assertNotIn('dpg.add_window', source, path.name)
            self.assertNotIn('with dpg.window', source, path.name)

    def test_modern_toplevel_applies_native_chrome(self):
        source = (ROOT / "WinUx" / "dialogs" / "modern.py").read_text(
            encoding="utf-8")
        self.assertIn("apply_native_qt_chrome", source)
        self.assertIn("prepare_modern_toplevel", source)


if __name__ == "__main__":
    unittest.main()
