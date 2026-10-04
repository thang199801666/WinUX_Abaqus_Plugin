"""Compatibility exports for dialogs moved to dedicated modules.

New code should import each dialog from its named module. These re-exports
preserve existing integrations that import from ``WinUx.dialogs.other_dialogs``.
"""

from .blocking_dialog import BlockingDialog
from .job_edit_dialog import JobEditDialog
from .job_schedule_dialog import JobScheduleDialog
from .server_path_dialog import ServerPathDialog
from .local_folder_dialog import LocalFolderDialog
from .settings_dialog import SettingsDialog

__all__ = [
    "BlockingDialog",
    "ServerPathDialog",
    "LocalFolderDialog",
    "SettingsDialog",
    "JobScheduleDialog",
    "JobEditDialog",
]
