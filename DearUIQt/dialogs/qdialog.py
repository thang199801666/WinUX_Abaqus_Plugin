"""Qt-compatible QDialog result/lifecycle facade.

``QtDialog`` remains DearUIQt's compatibility form base used by WinUx forms.
``QDialog`` adds the standard Qt result-code contract without changing legacy
validation callbacks that historically live on ``QtDialog.accept()``.
"""
from __future__ import annotations

from enum import IntEnum

from ..core.object import Qt, Signal, QCloseEvent
from .qt_dialog import QtDialog


class DialogCode(IntEnum):
    Rejected = 0
    Accepted = 1


class QDialog(QtDialog):
    """Qt-style dialog with explicit result code and completion signals.

    The class is intentionally separate from :class:`QtDialog`: WinUx's older
    forms use ``accept()`` as "invoke the default/validation action", whereas a
    real QDialog uses ``accept()`` as ``done(Accepted)``.  New library consumers
    therefore get the Qt contract while legacy forms keep their established
    semantics.
    """

    Rejected = int(DialogCode.Rejected)
    Accepted = int(DialogCode.Accepted)
    DialogCode = DialogCode

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.accepted = Signal(self)
        self.rejected = Signal(self)
        self.finished = Signal(self)
        self._dialog_result = self.Rejected
        self._dialog_done = False

    @staticmethod
    def _coerce_result(code):
        if isinstance(code, DialogCode):
            return int(code)
        if type(code) is not int:
            raise TypeError("QDialog result code must be an integer")
        return int(code)

    def result(self):
        return int(self._dialog_result)

    def setResult(self, code):
        self._dialog_result = self._coerce_result(code)

    def done(self, code):
        """Finish one visibility lease and emit QDialog completion signals once."""
        code = self._coerce_result(code)
        if self._dialog_done:
            return False
        self._dialog_done = True
        self._dialog_result = code
        if self.isVisible():
            self.hide()
        if code == self.Accepted:
            self.accepted.emit()
        elif code == self.Rejected:
            self.rejected.emit()
        self.finished.emit(code)
        if self.testAttribute(Qt.WA_DeleteOnClose):
            self.deleteLater()
        return True

    def accept(self):
        return self.done(self.Accepted)

    def reject(self):
        return self.done(self.Rejected)

    def show(self):
        # A QDialog can be reused after a previous done(). Qt preserves the
        # result value until changed, but a new visibility lease may finish and
        # emit signals again.
        if self._dialog_done and not self.isVisible():
            self._dialog_done = False
        return super().show()

    def open(self):
        """Show non-blocking, retaining the dialog's configured modality."""
        return self.show()

    def exec(self):
        """Run a nested UI pump until the dialog is completed/hidden.

        DearUIQt does not create a second renderer loop; it pumps the owning
        view just as native WinUx selector waits do.  This keeps event ordering
        deterministic and avoids a renderer-specific nested event loop.
        """
        self._dialog_done = False
        self.show()
        update = getattr(self.view, "update", None)
        exists = getattr(self.view, "winfo_exists", lambda: True)
        while self.isVisible() and not self._dialog_done and exists():
            if not callable(update):
                break
            update()
        return self.result()

    exec_ = exec

    def close(self):
        """A user/programmatic close maps to Rejected after close-event approval."""
        if self._closed or self._destroy_scheduled:
            return True
        event = QCloseEvent()
        self.sendEvent(event)
        if not event.isAccepted():
            return False
        return self.reject()


__all__ = ["DialogCode", "QDialog"]
