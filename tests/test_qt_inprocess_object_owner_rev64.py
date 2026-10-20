from DearUIQt.qt import QObject
from WinUx.ui.hosting.inprocess_dialog import (
    close_inprocess_dialogs,
    register_inprocess_dialog,
    unregister_inprocess_dialog,
)


class View:
    def __init__(self):
        self.calls = []
        self._inprocess_dialogs = set()

    def after(self, delay, callback, *args):
        self.calls.append((delay, callback, args))
        return len(self.calls)


class OwnedDialog(QObject):
    def __init__(self, view):
        super().__init__(after=view.after)
        self.hard_destroyed = 0

    def hard_destroy(self):
        self.hard_destroyed += 1
        self.delete()


def test_inprocess_dialog_registry_uses_qobject_owner_as_canonical_tree():
    view = View()
    dialog = OwnedDialog(view)

    register_inprocess_dialog(view, dialog)
    owner = view._inprocess_dialog_owner
    assert owner.objectName() == "WinUxInProcessDialogs"
    assert dialog.parent is owner
    assert owner.children() == [dialog]
    assert dialog in view._inprocess_dialogs

    unregister_inprocess_dialog(view, dialog)
    assert dialog.parent is None
    assert dialog not in view._inprocess_dialogs


def test_inprocess_shutdown_enumerates_qobject_children_and_releases_owner():
    view = View()
    first = register_inprocess_dialog(view, OwnedDialog(view))
    second = register_inprocess_dialog(view, OwnedDialog(view))

    # The QObject tree is sufficient even if legacy compatibility state is lost.
    view._inprocess_dialogs.clear()
    close_inprocess_dialogs(view)

    assert first.hard_destroyed == second.hard_destroyed == 1
    assert first._deleted and second._deleted
    assert view._inprocess_dialog_owner is None
