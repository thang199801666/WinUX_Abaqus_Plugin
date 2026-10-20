from pathlib import Path

from DearUIQt.qt.core import QEvent, QObject
from DearUIQt.qt.widget import QWidget

ROOT = Path(__file__).resolve().parents[1]


class FakeBackend:
    def __init__(self):
        self.config = {1: {"show": True}}

    def configure_item(self, tag, **kwargs):
        self.config.setdefault(tag, {}).update(kwargs)

    def get_item_configuration(self, tag):
        return dict(self.config.get(tag, {}))

    def does_item_exist(self, tag):
        return True

    def get_item_parent(self, tag):
        return 0

    def delete_item(self, tag):
        pass


class PolishedWidget(QWidget):
    def __init__(self, *args, **kwargs):
        self.polish_count = 0
        super().__init__(*args, **kwargs)

    def polishEvent(self, event):
        self.polish_count += 1


def test_qwidget_ensure_polished_is_one_shot():
    widget = PolishedWidget(1, backend=FakeBackend())
    assert widget.ensurePolished() is True
    assert widget.polish_count == 1
    assert widget.ensurePolished() is False
    assert widget.polish_count == 1
    assert QEvent.Polish > QEvent.WindowDeactivate


def test_qdialog_main_context_uses_hidden_construction_transaction():
    source = (ROOT / "DearUIQt/dialogs/qt_dialog.py").read_text(encoding="utf-8")
    assert "show=not self._construction_deferred" in source
    assert "self._construction_layout_dirty = self._construction_deferred" in source
    assert "def _finish_initial_construction(self):" in source
    finish = source[source.index("    def _finish_initial_construction"):source.index("    def _apply_layout")]
    assert "QEvent(QEvent.Polish)" in finish
    assert "QEvent(QEvent.LayoutRequest)" in finish
    assert finish.index("QEvent(QEvent.Polish)") < finish.index("QEvent(QEvent.LayoutRequest)")
    assert "return self._show_now()" in finish


def test_qdialog_construction_layout_requests_do_not_wake_event_loop():
    source = (ROOT / "DearUIQt/dialogs/qt_dialog.py").read_text(encoding="utf-8")
    update = source[source.index("    def updateGeometry(self):"):source.index("    def _on_native_resize")]
    assert "if self.isConstructing():" in update
    assert "self._construction_layout_dirty = True" in update
    assert update.index("if self.isConstructing():") < update.index("application.postEvent")


def test_main_retained_tools_explicitly_show_after_complete_constructor():
    source = (ROOT / "WinUx/view.py").read_text(encoding="utf-8")
    for method, attr in (("show_settings", "settings_dialog"),
                         ("show_diagnostics", "diagnostics_dialog"),
                         ("show_job_schedule", "job_schedule_dialog")):
        start = source.index(f"    def {method}(")
        end = source.find("\n    def ", start + 8)
        block = source[start:end if end != -1 else None]
        assert f"self.{attr}.show()" in block


def test_job_schedule_does_not_refresh_twice_on_hidden_first_show():
    source = (ROOT / "WinUx/dialogs/job_schedule_form.py").read_text(encoding="utf-8")
    init = source[source.index("    def __init__"):source.index("    def showEvent")]
    assert "if self.isVisible():" in init
    assert "self.refresh()" in init
    show = source[source.index("    def showEvent"):source.index("    def hideEvent")]
    assert "self.refresh()" in show


class ConstructionOwner(QObject):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._construction_layout_dirty = False

    def isConstructing(self):
        return True


def test_child_geometry_invalidations_bubble_to_constructing_dialog_owner():
    scheduled = []
    after = lambda delay, callback, *args: scheduled.append((callback, args))
    owner = ConstructionOwner(after=after)
    bridge = QObject(parent=owner, after=after)
    child = QWidget(1, parent=bridge, after=after, backend=FakeBackend())
    for _ in range(20):
        assert child.updateGeometry() is True
    assert owner._construction_layout_dirty is True
    assert scheduled == []
