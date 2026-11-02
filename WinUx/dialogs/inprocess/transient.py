"""One-shot dialogs hosted by the main DearUIQt QApplication event loop."""
from __future__ import annotations

from ...ui.hosting.inprocess_dialog import TransientInProcessDialogMixin
from ..blocking_form import BlockingDialog as BlockingForm
from ..jobs.job_edit_form import JobEditDialog as JobEditForm
from ..jobs.job_manager_form import JobManagerDialog as JobManagerForm
from ..selectors.local_folder_form import LocalFolderDialog as LocalFolderForm
from ..selectors.local_file_form import LocalFileDialog as LocalFileForm
from ..login_form import LoginForm
from ..odb.odb_check_form import ODBCheckDialog as ODBCheckForm
from ..odb.odb_extract_form import ODBExtractDialog as ODBExtractForm, ODBXYResultDialog as ODBXYResultForm
from ..progress_form import ProgressDialog as ProgressForm
from ..server_path_form import ServerPathDialog as ServerPathForm


class _TransientTool(TransientInProcessDialogMixin):
    """MRO anchor that registers a form with the QApplication owner tree."""


class BlockingDialog(_TransientTool, BlockingForm):
    def __init__(self, view, title, message, kind="message", initial="", on_result=None,
                 primary_text=None, secondary_text=None, intent="info", owner_hwnd=None,
                 option_text=None, option_checked=False, parent=None):
        # owner_hwnd is process-host compatibility; explicit visual ownership
        # is established by parent before preparing the native modal window.
        BlockingForm.__init__(self, view, title, message, kind, initial, on_result,
                              primary_text, secondary_text, intent,
                               option_text, option_checked, parent=parent)
        self._init_inprocess_lifetime(view)


class LoginDialog(_TransientTool, LoginForm):
    def __init__(self, view, callback):
        LoginForm.__init__(self, view, callback)
        self._init_inprocess_lifetime(view)


class JobEditDialog(_TransientTool, JobEditForm):
    def __init__(self, view, values, settings=None, on_result=None):
        JobEditForm.__init__(self, view, values, settings=settings, on_result=on_result)
        self._init_inprocess_lifetime(view)


class JobManagerDialog(_TransientTool, JobManagerForm):
    def __init__(self, view, paths, run_callback, compute_callback):
        JobManagerForm.__init__(self, view, paths, run_callback, compute_callback)
        self._init_inprocess_lifetime(view)


class LocalFolderDialog(_TransientTool, LocalFolderForm):
    def __init__(self, view, initial, on_selected=None, *, multiple=False,
                 show_hidden=False, title=None):
        LocalFolderForm.__init__(self, view, initial, on_selected,
                                 multiple=multiple, show_hidden=show_hidden, title=title)
        self._init_inprocess_lifetime(view)


class LocalFileDialog(_TransientTool, LocalFileForm):
    def __init__(self, view, initial="", on_selected=None, *, extensions=(),
                 save=False, default_filename="", width=840, height=540,
                 multiple=False, show_hidden=False, title=None):
        LocalFileForm.__init__(self, view, initial, on_selected,
                               extensions=extensions, save=save,
                               default_filename=default_filename, multiple=multiple,
                               show_hidden=show_hidden, title=title)
        self.width, self.height = int(width), int(height)
        self.preferred_size = (self.width, self.height)
        self._init_inprocess_lifetime(view)


class ServerPathDialog(_TransientTool, ServerPathForm):
    def __init__(self, view, initial, suggestion_provider, on_selected=None, task_submitter=None):
        ServerPathForm.__init__(self, view, initial, suggestion_provider,
                                on_selected=on_selected, task_submitter=task_submitter)
        self._init_inprocess_lifetime(view)


class ProgressDialog(_TransientTool, ProgressForm):
    def __init__(self, view, operation, cancel_event, items=None):
        ProgressForm.__init__(self, view, operation, cancel_event, items=items)
        self._init_inprocess_lifetime(view)


class ODBCheckDialog(_TransientTool, ODBCheckForm):
    def __init__(self, view, result):
        ODBCheckForm.__init__(self, view, result)
        self._init_inprocess_lifetime(view)


class ODBExtractDialog(_TransientTool, ODBExtractForm):
    def __init__(self, view, catalog, on_result):
        ODBExtractForm.__init__(self, view, catalog, on_result)
        self._init_inprocess_lifetime(view)


class ODBXYResultDialog(_TransientTool, ODBXYResultForm):
    def __init__(self, view, result):
        ODBXYResultForm.__init__(self, view, result)
        self._init_inprocess_lifetime(view)


__all__ = [
    "BlockingDialog", "LoginDialog", "JobEditDialog", "JobManagerDialog",
    "LocalFolderDialog", "LocalFileDialog", "ServerPathDialog", "ProgressDialog",
    "ODBCheckDialog", "ODBExtractDialog", "ODBXYResultDialog",
]
