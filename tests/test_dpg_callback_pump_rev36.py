from pathlib import Path

from WinUx.runtime.dpg_callbacks import invoke_callback_job, run_callback_jobs


ROOT = Path(__file__).resolve().parents[1]


def test_optional_capture_parameter_uses_python_default_instead_of_overindexing_job():
    calls = []

    def callback(sender, app_data, user_data, captured="folder-A"):
        calls.append((sender, app_data, user_data, captured))

    assert invoke_callback_job((callback, 11, "click", None)) is True
    assert calls == [(11, "click", None, "folder-A")]


def test_varargs_callback_receives_every_available_native_value():
    calls = []

    def callback(*args):
        calls.append(args)

    run_callback_jobs([(callback, 1, 2, 3)])
    assert calls == [(1, 2, 3)]


def test_callback_with_fewer_parameters_is_trimmed_cleanly():
    calls = []

    def callback(sender):
        calls.append(sender)

    run_callback_jobs([(callback, "sender", "app", "user")])
    assert calls == ["sender"]


def test_empty_and_disabled_jobs_are_ignored():
    assert invoke_callback_job(()) is False
    assert invoke_callback_job((None, 1, 2, 3)) is False


def test_folder_browser_callbacks_do_not_capture_path_as_fourth_dpg_parameter():
    form = (ROOT / "WinUx" / "dialogs" / "local_folder_form.py").read_text(encoding="utf-8")
    address = (ROOT / "WinUx" / "dialogs" / "folder_browser_address.py").read_text(encoding="utf-8")
    assert "user_data=str(path)" in form
    assert "callback=self._place_clicked" in form
    assert "def _place_clicked(self, _sender, _app_data, path):" in form
    assert "user_data=str(ancestor)" in address
    assert "callback=lambda _s, _a, p: self.dialog._navigate(p)" in address
    assert "_u, p=str(path)" not in form
    assert "_u, p=str(ancestor)" not in address


def test_floating_runtime_no_longer_uses_dearpygui_run_callbacks_helper():
    source = (ROOT / "WinUx" / "dialogs" / "floating_runtime.py").read_text(encoding="utf-8")
    assert "run_callback_jobs(dpg.get_callback_queue() or [])" in source
    assert "dpg.run_callbacks(" not in source
