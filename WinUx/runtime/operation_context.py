"""Connection-scoped asynchronous operation and UI delivery guard."""
from __future__ import annotations


class OperationContext:
    def __init__(self, app, remote=False):
        self.app = app
        self.remote = remote
        self.connection = getattr(app, "_connection_generation", None)
        manager = getattr(app, "session_manager", None) if remote else None
        self.session_token = manager.capture() if manager is not None else None
        self.session_id = (
            self.session_token.session_id if self.session_token is not None else None)
        self.task_scope = (
            self.session_token.task_scope if self.session_token is not None else None)
        # Capture the remote server object at operation creation.  app.server is
        # the *active* tab server and can change on a session switch; workers
        # must never resolve it lazily after they have been submitted.
        self.server = getattr(app, "server", None) if remote else None

    def current(self):
        if self.app._closing:
            return False
        if not self.remote:
            return True
        if self.connection != getattr(self.app, "_connection_generation", None):
            return False
        if self.session_token is not None:
            manager = getattr(self.app, "session_manager", None)
            if manager is None or not manager.is_token_current(self.session_token):
                return False
        return True

    def check(self):
        if not self.current():
            raise RuntimeError(
                "Operation cancelled because the application or server session changed")

    def post(self, delay, callback, *args):
        if self.current():
            self.app.view.after(delay, self._deliver, callback, args)

    def post_after_render(self, callback, *args):
        """Deliver after native popup/platform-window teardown has completed."""
        if self.current():
            schedule = getattr(self.app.view, "after_render", None)
            if callable(schedule):
                schedule(self._deliver, callback, args)
            else:
                self.post(0, callback, *args)

    def _deliver(self, callback, args):
        if self.current() and self.app.view.winfo_exists():
            owner = getattr(callback, "__self__", None)
            exists = getattr(owner, "winfo_exists", None)
            if callable(exists) and not exists():
                return
            callback(*args)

    def submit_background(self, name, callback, *args, **kwargs):
        submit = getattr(self.app, "_submit_background")
        if self.remote:
            submit = getattr(self.app, "_submit_remote_background", submit)
        return submit(name, callback, *args, **kwargs)

    def _submit_session_lane(self, attribute, name, callback, *args, **kwargs):
        submit = getattr(self.app, attribute)
        if self.remote:
            kwargs = dict(kwargs)
            kwargs["session_scoped"] = True
        try:
            return submit(name, callback, *args, **kwargs)
        except TypeError as exc:
            # Focused legacy/test adapters can expose the pre-session wrapper
            # without ``session_scoped``. Retry only that compatibility case.
            if not self.remote or "session_scoped" not in str(exc):
                raise
            kwargs.pop("session_scoped", None)
            return submit(name, callback, *args, **kwargs)

    def submit_transfer(self, name, callback, *args, **kwargs):
        return self._submit_session_lane(
            "_submit_transfer", name, callback, *args, **kwargs)

    def submit_analysis(self, name, callback, *args, **kwargs):
        return self._submit_session_lane(
            "_submit_analysis", name, callback, *args, **kwargs)

    def report_rejection(self, handle, callback, *args):
        if getattr(handle, "state", None) == "rejected":
            self.post(0, callback, *args, "Background queue is full; try again")
