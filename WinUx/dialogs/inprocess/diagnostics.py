from __future__ import annotations

from DearUIQt.backends import dpg

from ..diagnostics_form import DiagnosticsDialog as DiagnosticsForm
from .common import RetainedTool


class DiagnosticsDialog(RetainedTool, DiagnosticsForm):
    """In-process diagnostics with non-blocking report collection.

    Building the diagnostics report touches dependency/runtime/log metadata and
    used to run synchronously inside the constructor.  That put filesystem and
    environment work directly on the menu-click path.  A Qt application would
    normally move that work off the GUI thread and publish the result back via
    signals, so use the dialog-owned shared QThreadPool bridge here.
    """

    def __init__(self, view):
        from ...diagnostics import build_diagnostics_report
        self._diagnostics_future = None
        DiagnosticsForm.__init__(self, view, report_provider=build_diagnostics_report)
        self._init_inprocess_lifetime(view)

    def refresh(self, *_args):
        future = self._diagnostics_future
        if future is not None and not future.isFinished():
            return False
        try:
            dpg.set_value(self.status, "Refreshing diagnostics...")
        except Exception:
            pass
        self._diagnostics_future = self.runAsync(
            self._report_provider,
            on_result=self._diagnostics_ready,
            on_error=self._diagnostics_failed,
            on_finished=self._diagnostics_finished,
        )
        return True

    def _diagnostics_ready(self, report):
        dpg.set_value(self.text, str(report))
        dpg.set_value(self.status, "Diagnostics refreshed")

    def _diagnostics_failed(self, error):
        dpg.set_value(self.status, "Diagnostics refresh failed: {}".format(error))

    def _diagnostics_finished(self):
        self._diagnostics_future = None
