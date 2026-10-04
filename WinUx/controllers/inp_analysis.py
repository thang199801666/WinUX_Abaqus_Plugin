from __future__ import annotations

from ..inp_preferences import INPPreferences
from ..inp_reader import INPReader
from ..runtime.operation_context import OperationContext


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

        def worker():
            try:
                context.check()
                if panel.panel_id == "server":
                    content = self.server.read_text(path)
                else:
                    content = path.read_text(encoding="utf-8", errors="replace")
                settings = INPPreferences().load()
                summary = INPReader(content, settings).summary(path.name)
            except Exception as exc:
                context.post(0, self.app._inp_check_failed, panel, str(exc))
                return
            context.post(0, self.app._inp_check_succeeded, panel, summary)

        handle = self.app._submit_background("check-inp", worker,
            key=("check-inp", panel.panel_id, str(path), context.connection if context.remote else None),
            coalesce=True)
        context.report_rejection(handle, self.app._inp_check_failed, panel)

    def _inp_check_succeeded(self, panel, summary):
        panel.status.set("INP check completed")
        self.view.show_message("Check INP", summary)

    def _inp_check_failed(self, panel, error):
        panel.status.set("INP check failed")
        self.view.show_error("Check INP", error)

