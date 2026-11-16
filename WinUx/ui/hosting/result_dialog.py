"""Qt-style asynchronous result lifecycle for native dialog controllers."""
from .floating_dialog import FloatingDialogController
from DearUIQt.core import Signal, QEventLoop, QTimer


class ResultDialog(FloatingDialogController):
    ASYNC_RESULT_DELAY_MS = 20
    Accepted = 1
    Rejected = 0

    def _init_result(self, callback, cancel_value=None, notify_cancel=True):
        self.result = {"done": False, "value": None}
        self.on_result = callback
        self._cancel_value = cancel_value
        self._notify_cancel = notify_cancel
        self._result_notified = False
        self._explicit_result_code = None
        self._wait_loop = None
        self.accepted = Signal()
        self.rejected = Signal()
        self.finished = Signal()

    def dialogResult(self):
        """Qt-style close code; retain the historical result dict for payloads."""
        if self._explicit_result_code is not None:
            return self._explicit_result_code
        value = self.result["value"]
        return self.Accepted if self.result["done"] and value is not None and value is not False else self.Rejected

    def done(self, code, value=None):
        """Close asynchronously with an explicit code independent of payload."""
        if type(code) is not int or code not in (self.Accepted, self.Rejected):
            raise ValueError("dialog result code must be Accepted (1) or Rejected (0)")
        self.finish(value, result_code=code)

    def reject(self):
        self.done(self.Rejected, self._cancel_value)

    def accept(self):
        """Ask the client to validate and run its acceptance action."""
        return self.post("dialog_accept")

    def _record_result(self, value):
        if self.result["done"]:
            return False
        self.result.update(done=True, value=value)
        wait_loop = self._wait_loop
        if wait_loop is not None and wait_loop.isRunning():
            wait_loop.quit()
        return True

    def finish(self, value, *, result_code=None):
        """Programmatic completion requests a close; callbacks run after close."""
        # Keep self-contained for legacy lifecycle probes using a duck-type owner.
        if self.result["done"]:
            return
        if result_code is not None:
            if type(result_code) is not int or result_code not in (0, 1):
                raise ValueError("dialog result code must be Accepted (1) or Rejected (0)")
            self._explicit_result_code = result_code
        self.result.update(done=True, value=value)
        wait_loop = self._wait_loop
        if wait_loop is not None and wait_loop.isRunning():
            wait_loop.quit()
        self.destroy()
        if getattr(self, "_reuse_host", False) and not getattr(self, "_host_returned", False):
            return
        if not getattr(self, "_result_notified", False):
            self._result_notified = True
            if callable(self.on_result) and (value is not None or self._notify_cancel):
                self.view.after(self.ASYNC_RESULT_DELAY_MS, self.on_result, value)

    _window_finished = finish

    def handle_event(self, event, message):
        if event == "result":
            # Native client has begun closing; do not hide its HWND a second time.
            self._record_result(message.get("value"))

    def _notify_result(self):
        if self._result_notified:
            return
        self._result_notified = True
        value = self.result["value"]
        code = self.dialogResult()
        signal = self.accepted if code == self.Accepted else self.rejected
        self.view.after(0, signal.emit)
        self.view.after(0, self.finished.emit, code)
        if callable(self.on_result) and (value is not None or self._notify_cancel):
            self.view.after(0, self.on_result, value)

    def _close_completed(self):
        self._notify_result()

    def _finish(self):
        if not self.result["done"]:
            self.result.update(done=True, value=self._cancel_value)
        wait_loop = self._wait_loop
        if wait_loop is not None and wait_loop.isRunning():
            wait_loop.quit()
        super()._finish()

    def wait(self, timeout=None):
        if self.result["done"]:
            return self.result["value"]
        loop = QEventLoop()
        self._wait_loop = loop
        timeout_timer = None
        if timeout is not None:
            milliseconds = max(0, int(float(timeout) * 1000.0))
            timeout_timer = QTimer.singleShot(milliseconds, loop.quit, context=loop)
        try:
            loop.exec()
        finally:
            if timeout_timer is not None and not timeout_timer._deleted:
                timeout_timer.delete()
            if self._wait_loop is loop:
                self._wait_loop = None
            loop.delete()
        return self.result["value"]
