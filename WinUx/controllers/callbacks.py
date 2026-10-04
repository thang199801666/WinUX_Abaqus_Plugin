"""Callback contract shared by the WinUX controller and view."""


REQUIRED_CALLBACK_KEYS = (
    "navigate",
    "open_path",
    "sort_changed",
    "command",
    "active_command",
    "double_click",
    "drag_start",
    "drop",
    "drag_motion",
    "cancel",
    "login",
    "choose_path",
    "run_job",
    "check_inp",
    "check_odb",
    "edit_server_file",
    "extract_odb",
    "quick_transfer",
    "job_command",
    "job_schedule",
    "job_schedule_command",
    "console_output",
    "console_command",
    "console_interrupt",
    "job_user",
    "bookmark_command",
    "site_manager",
    "sync_preview",
)


def build_controller_callbacks(controller):
    """Bind the complete view callback contract to ``controller``."""
    callbacks = {
        "navigate": controller.navigate,
        "open_path": controller.open_path,
        "sort_changed": controller.sort_changed,
        "command": controller.command,
        "active_command": controller.active_command,
        "double_click": controller.double_click,
        "drag_start": controller.drag_start,
        "drop": controller.drop,
        "drag_motion": controller.drag_motion,
        "external_drop": controller.external_drop,
        "external_drop_missed": controller.external_drop_missed,
        "shell_drag": controller.shell_drag,
        "cancel": controller.cancel,
        "login": controller.login,
        "choose_path": controller.choose_path,
        "run_job": controller.run_job,
        "check_inp": controller.check_inp,
        "check_odb": controller.check_odb,
        "edit_server_file": controller.edit_server_file,
        "extract_odb": controller.extract_odb,
        "quick_transfer": controller.quick_transfer,
        "job_command": controller.job_command,
        "job_schedule": controller.job_schedules,
        "job_schedule_command": controller.job_schedule_command,
        "console_output": controller.server.shell_output,
        "console_connected": lambda: controller.server.connected,
        "console_command": controller.console_command,
        "console_interrupt": controller.console_interrupt,
        "job_user": lambda: controller.server.username or "",
        "bookmark_command": controller.bookmark_command,
        "site_manager": controller.site_manager,
        "sync_preview": controller.sync_preview,
    }
    return validate_callbacks(callbacks)


def validate_callbacks(callbacks):
    """Return ``callbacks`` after validating the required callable contract."""
    if not hasattr(callbacks, "get"):
        raise TypeError("WinUX callbacks must be provided as a mapping")

    missing = [key for key in REQUIRED_CALLBACK_KEYS if key not in callbacks]
    if missing:
        raise ValueError(
            "Missing required WinUX callback(s): {}".format(
                ", ".join(missing)
            )
        )

    invalid = [
        key for key in REQUIRED_CALLBACK_KEYS
        if not callable(callbacks.get(key))
    ]
    if invalid:
        raise TypeError(
            "WinUX callback(s) must be callable: {}".format(
                ", ".join(invalid)
            )
        )
    return callbacks
