from __future__ import annotations

import os

from DearUIQt.core import QThreadPool
from ..settings_form import SettingsDialog as SettingsForm
from .common import RetainedTool


class SettingsDialog(RetainedTool, SettingsForm):
    def __init__(self, view):
        SettingsForm.__init__(
            self,
            view,
            on_install_update=self._install_update,
            on_settings_saved=view.apply_general_preferences,
        )
        self._init_inprocess_lifetime(view)

    def _install_update(self):
        from winux_launcher import launch_winux
        project_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))

        def worker():
            try:
                launch_winux(
                    project_dir=project_dir,
                    existing_pid=os.getpid(),
                    install_update=True,
                )
            except Exception as exc:
                self.post("update_launch_failed", str(exc))
            else:
                self.view.after(0, self.hide)

        QThreadPool.globalInstance().start(worker)
