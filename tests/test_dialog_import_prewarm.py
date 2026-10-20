"""Common imports warm off the click path, without constructing UI/state."""
from unittest.mock import patch

from WinUx.dialogs import floating_forms


def test_common_import_warmup_is_bounded_and_does_not_build_forms():
    with patch.dict("os.environ", {"WINUX_INPROCESS_DIALOGS": "1"}), \
         patch("importlib.import_module") as load, \
         patch.object(floating_forms, "create_form") as build:
        floating_forms.prepare_common_form_imports()
    assert [call.args for call in load.call_args_list] == [
        (".blocking_form", "WinUx.dialogs"),
        (".login_form", "WinUx.dialogs"),
        (".local_folder_form", "WinUx.dialogs"),
        (".local_file_form", "WinUx.dialogs"),
    ]
    build.assert_not_called()


def test_legacy_process_mode_restores_light_dialog_warm_imports():
    with patch.dict("os.environ", {"WINUX_INPROCESS_DIALOGS": "0"}), \
         patch("importlib.import_module") as load:
        floating_forms.prepare_common_form_imports()
    names = [call.args[0] for call in load.call_args_list]
    for name in (
        ".settings_form", ".job_schedule_form", ".bookmarks_form",
        ".site_manager_form", ".sync_preview_form", ".diagnostics_form",
        ".transfer_center_form",
    ):
        assert name in names

