from collections import deque
from pathlib import Path

from DearUIQt.qt import QApplication, QObject


class Scheduler:
    def __init__(self):
        self.pending = deque()

    def after(self, _delay, callback, *args):
        self.pending.append((callback, args))
        return len(self.pending)


class Popup(QObject):
    pass


class Modal(QObject):
    pass


def test_qapplication_tracks_popup_stack_without_owning_deleted_widgets():
    scheduler = Scheduler()
    app = QApplication(after=scheduler.after)
    try:
        first = Popup(after=scheduler.after)
        second = Popup(after=scheduler.after)
        assert app.activePopupWidget() is None
        assert app._register_popup(first)
        assert app.activePopupWidget() is first
        assert app._register_popup(second)
        assert app.activePopupWidget() is second

        # Raising an existing popup moves it to the top without duplication.
        assert app._register_popup(first)
        assert app.activePopupWidget() is first
        assert len(app._popup_stack) == 2

        # QPointer storage means deletion cannot keep a stale popup alive.
        first.delete()
        assert app.activePopupWidget() is second
        assert len(app._popup_stack) == 1
    finally:
        app.delete()


def test_clear_widget_removes_popup_and_modal_descendants():
    scheduler = Scheduler()
    app = QApplication(after=scheduler.after)
    try:
        owner = QObject(after=scheduler.after)
        popup = Popup(parent=owner)
        modal = Modal(parent=owner)
        app._register_popup(popup)
        app._register_modal(modal)
        assert app.activePopupWidget() is popup
        assert app.activeModalWidget() is modal

        app._clear_widget(owner)
        assert app.activePopupWidget() is None
        assert app.activeModalWidget() is None
    finally:
        app.delete()


def test_qmenu_and_qdialog_use_application_level_activation_contract():
    root = Path(__file__).resolve().parents[1]
    menu = (root / "DearUIQt" / "qt" / "menu.py").read_text(encoding="utf-8")
    dialog = (root / "DearUIQt" / "dialogs" / "qt_dialog.py").read_text(encoding="utf-8")
    reference = (root / "WinUx" / "dialogs" / "reference_chart_form.py").read_text(encoding="utf-8")

    assert "qobject_parent = _parent_menu if _parent_menu is not None else parent" in menu
    assert "application._register_popup(self)" in menu
    assert "application._unregister_popup(self)" in menu
    assert "application._register_modal(self)" in dialog
    assert "application._unregister_modal(self)" in dialog
    assert "parent_window=self.tag, parent=self" in reference
