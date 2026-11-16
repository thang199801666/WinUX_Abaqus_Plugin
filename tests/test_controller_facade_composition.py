"""Architecture contract for the application-controller facade composition."""
from __future__ import annotations

import unittest

from WinUx.app.controller import WinUXController
from WinUx.app.facades import (
    AnalysisFacadeMixin,
    ConnectionFacadeMixin,
    ExplorerFacadeMixin,
    JobsFacadeMixin,
    TransferFacadeMixin,
)


class ControllerFacadeCompositionTests(unittest.TestCase):
    def test_public_feature_entry_points_are_owned_by_facades(self):
        self.assertIs(WinUXController.login, ConnectionFacadeMixin.login)
        self.assertIs(WinUXController.job_command, JobsFacadeMixin.job_command)
        self.assertIs(WinUXController.open_path, ExplorerFacadeMixin.open_path)
        self.assertIs(WinUXController.check_inp, AnalysisFacadeMixin.check_inp)
        self.assertIs(WinUXController.check_odb, AnalysisFacadeMixin.check_odb)
        self.assertIs(WinUXController.quick_transfer, TransferFacadeMixin.quick_transfer)

    def test_controller_root_keeps_only_composition_and_lifecycle_methods(self):
        local = set(WinUXController.__dict__)
        for name in (
            "login", "job_command", "open_path", "command", "check_inp",
            "check_odb", "upgrade_odb", "quick_transfer", "sync_preview",
        ):
            self.assertNotIn(name, local)
        for name in (
            "__init__", "run", "close", "_finish_close",
            "_submit_background", "_submit_transfer", "_submit_analysis",
            "_connection_controller", "_job_polling_controller",
            "_schedule_execution_controller", "_transfer_controller",
        ):
            self.assertIn(name, local)

    def test_feature_facades_do_not_own_duplicate_state(self):
        for mixin in (
            AnalysisFacadeMixin, ConnectionFacadeMixin, ExplorerFacadeMixin,
            JobsFacadeMixin, TransferFacadeMixin,
        ):
            init = mixin.__dict__.get("__init__")
            self.assertIsNone(init, mixin.__name__)


if __name__ == "__main__":
    unittest.main()
