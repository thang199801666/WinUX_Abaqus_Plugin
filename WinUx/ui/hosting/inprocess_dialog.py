"""Qt-style lifetime for WinUx dialogs on the application GUI event loop.

Application dialogs live in the main DearUIQt renderer/context.  When the native
multi-window backend is available they can still own independent HWNDs, but the
widget tree, event dispatch and rendering remain in the same process and GUI
thread.  This removes dialog-process acquisition, socket IPC and duplicate render
loops from the normal application path.

Retained tools use QWidget-like close semantics (hide now, terminal destruction at
application shutdown); transient dialogs delete their widget tree when complete.
"""
from __future__ import annotations

from DearUIQt.core import QObject


def _registry(view):
    dialogs = getattr(view, "_inprocess_dialogs", None)
    if dialogs is None:
        dialogs = view._inprocess_dialogs = set()
    return dialogs


def _qt_owner(view):
    """Return the QObject root for retained main-context dialogs.

    ``_inprocess_dialogs`` remains as a compatibility facade for integrations
    that inspect the historical registry. The QObject tree is the canonical
    lifetime/ancestry model for DearUIQt dialogs, matching Qt parent ownership.
    """
    owner = getattr(view, "_inprocess_dialog_owner", None)
    if owner is None or getattr(owner, "_deleted", False):
        after = getattr(view, "after", None)
        owner = QObject(after=after if callable(after) else None)
        owner.setObjectName("WinUxInProcessDialogs")
        view._inprocess_dialog_owner = owner
    return owner


def register_inprocess_dialog(view, dialog):
    _registry(view).add(dialog)
    if isinstance(dialog, QObject):
        owner = _qt_owner(view)
        if dialog.parent is not owner:
            dialog.setParent(owner)
    return dialog


def unregister_inprocess_dialog(view, dialog):
    dialogs = getattr(view, "_inprocess_dialogs", None)
    if dialogs is not None:
        dialogs.discard(dialog)
    owner = getattr(view, "_inprocess_dialog_owner", None)
    if (isinstance(dialog, QObject) and owner is not None
            and dialog.parent is owner and not dialog._deleted):
        dialog.setParent(None)


def close_inprocess_dialogs(view):
    """Terminally dispose all main-context dialogs before DPG shutdown.

    QObject-owned dialogs are enumerated from the retained ownership tree. The
    historical set is merged only for non-QObject/third-party compatibility.
    """
    owner = getattr(view, "_inprocess_dialog_owner", None)
    owned = tuple(owner.children()) if isinstance(owner, QObject) and not owner._deleted else ()
    legacy = tuple(getattr(view, "_inprocess_dialogs", ()) or ())
    dialogs = tuple(dict.fromkeys((*owned, *legacy)))
    for dialog in dialogs:
        try:
            dialog.hard_destroy()
        except Exception:
            try:
                # Compatibility fallback for a third-party dialog registered in
                # the set without using RetainedInProcessDialogMixin.
                dialog.destroy()
            except Exception:
                pass
    registry = getattr(view, "_inprocess_dialogs", None)
    if registry is not None:
        registry.clear()
    owner = getattr(view, "_inprocess_dialog_owner", None)
    if isinstance(owner, QObject) and not owner._deleted and not owner.children():
        owner.delete()
        view._inprocess_dialog_owner = None


class TransientInProcessDialogMixin:
    """Own a one-shot QDialog in the main QApplication without retaining it.

    Transient selectors/message boxes/editors should be destroyed when their
    semantic operation completes, but they still participate in the same
    QObject owner tree so application shutdown can close any dialog that is
    still open.  No process, socket or secondary renderer is involved.
    """

    INPROCESS_DIALOG = True
    RETAIN_ON_CLOSE = False

    def _init_inprocess_lifetime(self, view):
        self._inprocess_view = view
        self._inprocess_hard_destroy = False
        register_inprocess_dialog(view, self)

    def destroy(self, *args, **kwargs):
        # ``wait=``/``timeout=`` are accepted for compatibility with the old
        # process controller. In-process destruction is already non-blocking and
        # therefore never waits for child-process acknowledgement.
        if getattr(self, "_inprocess_hard_destroy", False):
            return super().destroy()
        self._inprocess_hard_destroy = True
        view = getattr(self, "_inprocess_view", None)
        try:
            return super().destroy()
        finally:
            if view is not None:
                unregister_inprocess_dialog(view, self)

    def hard_destroy(self):
        return self.destroy()



class RetainedInProcessDialogMixin:
    """Retain a QDialog tree after user close, delete it only at app shutdown.

    Forms historically call ``destroy`` from Close/Cancel buttons.  Rebuilding
    those forms on every open defeats Qt's normal retained-object semantics and
    is particularly expensive for Settings/table-heavy tools.  This mixin maps
    that historical call to ``hide`` while keeping ``hard_destroy`` as the
    terminal destructor used by the application owner.
    """

    INPROCESS_DIALOG = True
    RETAIN_ON_CLOSE = True

    def _init_inprocess_lifetime(self, view):
        self._inprocess_view = view
        self._inprocess_hard_destroy = False
        self._inprocess_delete_scheduled = False
        register_inprocess_dialog(view, self)

    def destroy(self, *args, **kwargs):
        if getattr(self, "_inprocess_hard_destroy", False):
            return super().destroy()
        # Historical forms bind Close/Cancel directly to destroy().  QWidget
        # close semantics keep the object alive by default, so make this a
        # constant-time visibility transition for retained application tools.
        if getattr(self, "winfo_exists", lambda: False)():
            return self.hide()
        return False

    def close(self):
        if not getattr(self, "winfo_exists", lambda: False)():
            return True
        # Use the QDialog close event contract when available; the final
        # visibility transition remains retained and therefore non-destructive.
        try:
            from DearUIQt.core import QCloseEvent
            event = QCloseEvent()
            self.sendEvent(event)
            if not event.isAccepted():
                return False
        except Exception:
            pass
        return bool(self.hide())

    def delete(self):
        return self.hard_destroy()

    def deleteLater(self):
        if getattr(self, "_inprocess_hard_destroy", False) or getattr(self, "_inprocess_delete_scheduled", False):
            return
        view = getattr(self, "_inprocess_view", None)
        if view is None or not hasattr(view, "after"):
            return self.hard_destroy()
        self._inprocess_delete_scheduled = True
        view.after(0, self._hard_destroy_now)

    def _hard_destroy_now(self):
        if getattr(self, "_inprocess_hard_destroy", False):
            return
        self._inprocess_delete_scheduled = False
        self._inprocess_hard_destroy = True
        view = getattr(self, "_inprocess_view", None)
        try:
            super().destroy()
            # DialogBase normally defers visual deletion to the next UI turn.
            # A terminal owner teardown may close the dispatcher immediately,
            # so finish that deferred phase synchronously while the DPG context
            # is still alive. The finalizer is idempotent if an already-queued
            # callback later runs.
            if (getattr(self, "_destroy_scheduled", False) and
                    not getattr(self, "_defer_visual_destroy", False)):
                finalizer = getattr(self, "_finalize_visual_destroy", None)
                if callable(finalizer):
                    finalizer()
        finally:
            if view is not None:
                unregister_inprocess_dialog(view, self)

    def hard_destroy(self):
        if getattr(self, "_inprocess_hard_destroy", False):
            return None
        self._inprocess_delete_scheduled = False
        return self._hard_destroy_now()


__all__ = [
    "RetainedInProcessDialogMixin",
    "register_inprocess_dialog",
    "TransientInProcessDialogMixin",
    "unregister_inprocess_dialog",
    "close_inprocess_dialogs",
]
