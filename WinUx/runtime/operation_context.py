"""Connection-scoped asynchronous operation and UI delivery guard."""
from __future__ import annotations


class OperationContext:
    def __init__(self, app, remote=False):
        self.app = app
        self.remote = remote
        self.connection = getattr(app, "_connection_generation", None)

    def current(self):
        return (not self.app._closing and
                (not self.remote or self.connection == getattr(self.app, "_connection_generation", None)))

    def check(self):
        if not self.current():
            raise RuntimeError("Operation cancelled because the application or server session changed")

    def post(self, delay, callback, *args):
        if self.current():
            self.app.view.after(delay, self._deliver, callback, args)

    def _deliver(self, callback, args):
        if self.current() and self.app.view.winfo_exists():
            owner = getattr(callback, "__self__", None)
            exists = getattr(owner, "winfo_exists", None)
            if callable(exists) and not exists():
                return
            callback(*args)

    def report_rejection(self, handle, callback, *args):
        if getattr(handle, "state", None) == "rejected":
            self.post(0, callback, *args, "Background queue is full; try again")
