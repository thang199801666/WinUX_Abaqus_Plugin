"""Verify Job Manager's real Run callback without connecting/submitting remotely."""
from pathlib import Path, PurePosixPath
import sys
import time
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import WinUx
from DearUIQt.backends import dpg
from DearUIQt.backends.native_windows import NativeWindowBackend
from WinUx.ui import StandaloneUiHost, configure_ui_context
from WinUx.dialogs.job_manager_form import JobManagerDialog
from WinUx.runtime.dpg_callbacks import run_callback_jobs, invoke_callback_job


def main():
    dpg.create_context()
    form = None
    payloads = []
    try:
        NativeWindowBackend(dpg).enable()
        host = StandaloneUiHost(dpg)
        configure_ui_context(host)
        dpg.create_viewport(title="Job submit form check", width=1200, height=650)
        dpg.setup_dearpygui()
        dpg.show_viewport()
        with patch("WinUx.dialogs.logic.job_manager.JobManagerPreferences.save"):
            path = PurePosixPath("/home/test/model.inp")
            form = JobManagerDialog(host, [path], lambda dialog, jobs: payloads.append(jobs), lambda *_: None)
            for _ in range(8):
                run_callback_jobs(dpg.get_callback_queue() or [])
                host.pump()
                dpg.render_dearpygui_frame()
                time.sleep(.005)
            row = form.rows_by_path[path]
            print("FORM_VALUES", {key: form.control_value(row[key]) for key in
                                  ("run", "version", "cpus", "precision", "overwrite", "schedule", "time")})
            callback = dpg.get_item_configuration(form.run_button)["callback"]
            invoke_callback_job((callback, form.run_button, None, None))
            for _ in range(5):
                host.pump()
                dpg.render_dearpygui_frame()
            print("RUN_PAYLOADS", payloads, "status", form.control_value(form.status))
            assert len(payloads) == 1, "Run never reached the submit callback"
            assert payloads[0][0]["path"] == path
            assert payloads[0][0]["cpus"] > 0
            form.submission_job_complete(path, "model (1234)")
            form.submission_finished(1, 0)
            form.job_view_failed("Connection refused\nqstat: cannot connect to server")
            for _ in range(3):
                host.pump()
                dpg.render_dearpygui_frame()
            status = form.control_value(form.status)
            assert "PBS verification failed" in status, status
            assert "Connection refused" in status, status
            assert not dpg.get_item_configuration(form.run_button)["enabled"]
            print("JOB_MANAGER_PBS_ERROR_VISIBLE", status)
        print("JOB_MANAGER_RUN_CALLBACK_OK (no remote submit performed)")
    finally:
        if form is not None:
            form.destroy()
        dpg.destroy_context()


if __name__ == "__main__":
    main()
