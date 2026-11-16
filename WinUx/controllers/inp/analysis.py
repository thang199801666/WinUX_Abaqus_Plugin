from __future__ import annotations

from ...preferences.inp import INPPreferences
from ...services.inp_reader import INPReader
from ...runtime.operation_context import OperationContext


class InpAnalysisController:
    def __init__(self, app):
        self.app = app

    @property
    def view(self):
        return self.app.view

    @property
    def server(self):
        return self.app.server

    def check_inp(self, panel):
        if self.app._closing:
            return
        paths = [path for path in panel.selected_transfer_paths()
                 if path.suffix.casefold() == ".inp"]
        if len(paths) != 1:
            return
        path = paths[0]
        panel.status.set("Checking {}...".format(path.name))

        context = OperationContext(self.app, remote=panel.panel_id == "server")
        server = context.server if context.remote else None

        def worker():
            context.check()
            if panel.panel_id == "server":
                content = server.read_text(path)
            else:
                content = path.read_text(encoding="utf-8", errors="replace")
            settings = INPPreferences().load()
            return INPReader(content, settings).summary(path.name)

        def completed(handle):
            # Completion always arrives through BackgroundTaskManager's shared
            # UiDispatcher. The parser/file worker never schedules retained UI.
            if not context.current():
                return
            if handle.state in {"failed", "rejected"}:
                error = handle.exception or RuntimeError(
                    "Background queue is full; try again")
                self.app._inp_check_failed(panel, str(error))
                return
            if handle.state == "completed":
                self.app._inp_check_succeeded(panel, handle.result)

        context.submit_background("check-inp", worker,
            key=("check-inp", panel.panel_id, str(path), context.connection if context.remote else None),
            coalesce=True, on_done=completed)

    def _inp_check_succeeded(self, panel, summary):
        panel.status.set("INP check completed")
        self.view.show_message("Check INP", summary)

    def _inp_check_failed(self, panel, error):
        panel.status.set("INP check failed")
        self.view.show_error("Check INP", error)

