"""Check shared dialog combos without saving preferences or submitting jobs."""
import os
from pathlib import Path, PurePosixPath
import sys
import tempfile
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import WinUx
from DearUIQt.backends import get_backend
from DearUIQt.backends.native_windows import NativeWindowBackend
from DearUIQt.core import QEvent, QKeyEvent
from DearUIQt.core.application import QApplication
from DearUIQt.input_gate import popup_input_active
from DearUIQt.widgets import QComboBox
from WinUx.ui import StandaloneUiHost, configure_ui_context
from WinUx.dialogs.job_manager_form import JobManagerDialog
from WinUx.dialogs.settings_form import SettingsDialog
from WinUx.dialogs.site_manager_form import SiteManagerDialog
from WinUx.dialogs.odb_extract_form import ODBExtractDialog, ODBXYResultDialog
from WinUx.dialogs.local_file_form import LocalFileDialog
from WinUx.ui.components.explorer_list_view import apply_white_explorer_theme


def main():
    temp_root = Path(os.environ["LOCALAPPDATA"]) / "Temp" / "opencode"
    temp_root.mkdir(parents=True, exist_ok=True)
    b = get_backend()
    b.create_context()
    b.configure_app(manual_callback_management=True)
    app, forms = None, []
    try:
        NativeWindowBackend(b).enable()
        host = StandaloneUiHost(b)
        configure_ui_context(host)
        app = QApplication(after=host.after)
        app.installInputBackend(b)
        b.create_viewport(title="Application combo check", width=1200, height=800)
        with b.window(tag="app_combo_owner"):
            b.add_text("Application combo test owner")
        b.setup_dearpygui()
        b.set_primary_window("app_combo_owner", True)
        b.show_viewport()
        apply_white_explorer_theme()

        def frames(count=10):
            for _ in range(count):
                host.pump()
                b.render_dearpygui_frame()
                b.run_callbacks(b.get_callback_queue())

        def opened(form):
            forms.append(form)
            form.show()
            frames()
            return form

        def choose(form, tag, index):
            combo = form.control_wrapper(tag)
            assert isinstance(combo, QComboBox) and combo._choice_field is not None
            assert not combo.isEditable(), "Fixed option fields must remain constrained"
            assert combo._choice_popup_parent == form.tag
            combo.setFocus()
            frames(3)
            app.dispatchKeyEvent(QKeyEvent(QEvent.KeyPress, b.mvKey_F4))
            frames(3)
            assert combo.popupVisible(), (
                "The dialog did not route F4 to its focused combo", type(form).__name__,
                combo.isVisible(), combo.isEnabled(), form._accepts_dialog_keys(),
                type(form.focusWidget()).__name__, b.get_focused_item(),
                b.get_item_state(combo._choice_field.button),
                type(app.focusObject()).__name__, app.activeModalWidget() is form)
            app.dispatchKeyEvent(QKeyEvent(QEvent.KeyPress, b.mvKey_Home))
            for _ in range(index):
                app.dispatchKeyEvent(QKeyEvent(QEvent.KeyPress, b.mvKey_Down))
            app.dispatchKeyEvent(QKeyEvent(QEvent.KeyPress, b.mvKey_Return))
            frames(3)
            assert combo.currentIndex() == index
            assert not combo.popupVisible() and not popup_input_active()
            return combo

        def closed(form):
            form.destroy()
            frames(6)
            assert not popup_input_active() and app.activePopupWidget() is None

        with tempfile.TemporaryDirectory(prefix="winux-app-combos-", dir=temp_root) as sandbox, \
                patch.dict(os.environ, {"APPDATA": sandbox, "LOCALAPPDATA": sandbox}), \
                patch("WinUx.dialogs.logic.job_manager.JobManagerPreferences.save"):
            path = PurePosixPath("/test/example.inp")
            submit = Mock()
            job = opened(JobManagerDialog(host, [path], submit, Mock()))
            row = job.rows_by_path[path]
            choose(job, row["schedule"], 1)
            assert row["mode"] == "Run After", "Schedule lost its path user_data"
            assert job.control_value(row["time"]) == "00:30:00"
            assert not submit.called, "Selecting a combo unexpectedly submitted a job"
            closed(job)
            print("APP_COMBO_JOB_MANAGER_OK")

            settings = opened(SettingsDialog(host))
            settings._ensure_page("general", defer_io=False)
            frames()
            settings.set_control_value(settings.formula, next(iter(settings.FORMULA_LABELS)))
            settings._formula_changed()
            choose(settings, settings.formula, 1)
            assert settings.control_wrapper(settings.inp_fields["core_step"]).isEnabled()
            settings._show_page("updates")
            settings._ensure_page("updates", defer_io=False)
            frames()
            choose(settings, settings.update_provider, 1)
            assert settings.control_value(settings.update_provider) == "GitHub Releases (recommended)"
            closed(settings)
            print("APP_COMBO_SETTINGS_OK")

            sites = opened(SiteManagerDialog(host, [
                {"id": "a", "name": "Alpha", "host": "alpha", "port": 22},
                {"id": "b", "name": "Beta", "host": "beta", "port": 2222}], Mock(), Mock(), Mock()))
            choose(sites, sites.site_list, 1)
            assert sites._selected_id == "b" and sites.control_value(sites.fields["host"]) == "beta"
            closed(sites)
            print("APP_COMBO_SITE_MANAGER_OK")

            result = Mock()
            odb = opened(ODBExtractDialog(host, {"historyOutputs": [
                {"id": "t", "output": "Time", "points": 3},
                {"id": "u", "output": "U", "points": 3}]}, result))
            choose(odb, odb.reverse, 3)
            odb._x_ids, odb._y_ids = ["t"], ["u"]
            odb._accept()
            assert result.call_args.args[0]["reverse"] == "Reverse Both"
            frames()
            curves = opened(ODBXYResultDialog(host, {"curves": [
                {"name": "First", "points": [(0, 1)]},
                {"name": "Second", "points": [(0, 2), (1, 3)]}]}))
            choose(curves, curves.combo, 1)
            assert len(curves.table.rows) == 2, "Two-argument curve selection callback was lost"
            closed(curves)
            print("APP_COMBO_ODB_OK")

            picker = opened(LocalFileDialog(host, sandbox, Mock(), extensions=("inp",)))
            choose(picker, picker.file_type, 1)
            assert picker._show_all_files
            closed(picker)
            print("APP_COMBO_FILE_SELECTOR_OK")
        print("APP_SHARED_COMBOBOXES_OK")
    finally:
        for form in reversed(forms):
            form.destroy()
        if app is not None:
            app.delete()
        b.destroy_context()


if __name__ == "__main__":
    main()
